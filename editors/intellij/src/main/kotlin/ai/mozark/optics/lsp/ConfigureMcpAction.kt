package ai.mozark.optics.lsp

import com.intellij.notification.NotificationAction
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.ide.CopyPasteManager
import com.intellij.openapi.options.ShowSettingsUtil
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.DialogWrapper
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBRadioButton
import com.intellij.ui.dsl.builder.panel
import java.awt.GridLayout
import java.awt.datatransfer.StringSelection
import java.nio.file.Path
import javax.swing.ButtonGroup
import javax.swing.JComponent
import javax.swing.JPanel

/**
 * Fetches the bridge if needed and registers it with whichever agents on this machine keep their
 * own MCP config. Those are other tools' user-level files, so nothing is
 * written without the dialog first.
 *
 * The entry always lands on the clipboard too, for an agent we do not know about.
 */
class ConfigureMcpAction : AnAction() {

    private val log = logger<ConfigureMcpAction>()

    override fun actionPerformed(event: AnActionEvent) {
        val project = event.getData(CommonDataKeys.PROJECT) ?: return
        val root = project.basePath ?: return

        // Detection is a file check and a PATH lookup, so it is cheap enough to do before the
        // dialog. Asking first means a declined dialog costs no download.
        val detected = McpClients.detected()
        val skillHomes = McpClients.skillHomes()
        var chosen = emptyList<McpClients.Target>()
        var scope = McpClients.Scope.GLOBAL
        var skill = false
        if (detected.isNotEmpty() || skillHomes.isNotEmpty()) {
            val dialog = ChooseClientsDialog(detected, skillHomes)
            if (!dialog.showAndGet()) return
            chosen = dialog.chosen
            scope = dialog.scope
            skill = dialog.skill
        }

        ProgressManager.getInstance().run(
            object : Task.Backgroundable(project, "Configuring Optics MCP server", true) {
                override fun run(indicator: ProgressIndicator) =
                    configure(project, root, chosen, scope, skill, indicator)
            }
        )
    }

    private fun configure(
        project: Project,
        root: String,
        clients: List<McpClients.Target>,
        scope: McpClients.Scope,
        skill: Boolean,
        indicator: ProgressIndicator,
    ) {
        // The interpreter has to be established before it can go in the config, and probing runs it.
        OpticsPython.probeBlocking()
        val python = when (val resolved = OpticsPython.resolve()) {
            is OpticsPython.Result.Ok -> resolved.exe
            is OpticsPython.Result.TooOld -> return fail(
                project,
                "Python ${OpticsPython.describe(resolved.version)} at ${resolved.exe} is too old. " +
                    "The Optics language server needs 3.12 or newer.",
            )

            else -> return fail(
                project,
                "No Python 3.12 or newer was found on PATH. Set an interpreter under " +
                    "Settings | Tools | Optics Framework.",
            )
        }

        val binary = try {
            OpticsMcp.binaryBlocking(indicator)
        } catch (error: OpticsMcp.UnavailableException) {
            return fail(project, error.message ?: "Could not install the MCP bridge.")
        }

        // No config file: agent-lsp takes the server as one argument and the workspace from the
        // directory the agent spawns it in.
        val spec = OpticsMcpConfig.serverSpec(python.toString(), OpticsLspDescriptor.LAUNCH_ARGS)
        val env = OpticsMcpConfig.serverEnv(OpticsLspIntegrationProvider.bundledLibs.toString())

        // One agent failing must not hide the ones that worked, so each is reported by name.
        val request = McpClients.Request(binary, spec, env, scope, Path.of(root))
        CopyPasteManager.getInstance().setContents(StringSelection(McpClients.clipboardEntry(request)))
        val registered = mutableListOf<String>()
        val failed = mutableListOf<String>()
        for (client in clients) {
            indicator.text = "Registering with ${client.label}"
            try {
                client.register(request)
                registered += client.label
                log.info("registered with ${client.label} (${scope.name.lowercase()})")
            } catch (error: Exception) {
                failed += "Could not register with ${client.label}: ${error.message}"
                log.warn("could not register with ${client.label}", error)
            }
        }

        // Not scoped: an agent reads its skills from one place regardless of the project it is in.
        val skilled = if (!skill) emptyList() else try {
            indicator.text = "Installing the optics skill"
            McpClients.installSkill(OpticsLspIntegrationProvider.skillFile)
        } catch (error: Exception) {
            failed += "Could not install the optics skill: ${error.message}"
            log.warn("could not install the optics skill", error)
            emptyList()
        }

        val body = buildString {
            if (registered.isNotEmpty()) {
                append("Registered with ${registered.joinToString(", ")} ")
                append(if (scope == McpClients.Scope.PROJECT) "for this project" else "globally")
                append(". Restart the IDE or the agent to pick it up.<br/>")
            }
            // Claude treats a project server as untrusted until it is approved interactively, so
            // it is listed but not used. Silence here reads as a registration that did not work.
            if (scope == McpClients.Scope.PROJECT && McpClients.CLAUDE_CODE in registered) {
                append("Claude Code lists a project server as pending approval: run ")
                append("<code>claude</code> in this project and approve it before first use.<br/>")
            }
            if (clients.isEmpty()) {
                append("No agent that keeps its own MCP config was found on this machine, so ")
                append("nothing was registered. ")
            }
            if (skilled.isNotEmpty()) {
                append("Installed the optics skill for ${skilled.joinToString(", ")}.<br/>")
            }
            append("The client entry is on your clipboard, for AI Assistant or any other agent.")
            for (problem in failed) append("<br/>$problem")
        }

        NotificationGroupManager.getInstance()
            .getNotificationGroup("Optics")
            .createNotification(
                "Optics MCP server ready",
                body,
                if (failed.isEmpty()) NotificationType.INFORMATION else NotificationType.WARNING,
            )
            .notify(project)
    }

    private fun fail(project: Project, message: String) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup("Optics")
            .createNotification("Optics MCP server", message, NotificationType.WARNING)
            .addAction(
                NotificationAction.createSimple("Open Settings") {
                    ShowSettingsUtil.getInstance()
                        .showSettingsDialog(project, OpticsConfigurable::class.java)
                }
            )
            .notify(project)
    }
}

private class ChooseClientsDialog(
    private val targets: List<McpClients.Target>,
    skillHomes: List<String>,
) : DialogWrapper(true) {

    private val boxes = targets.map { target ->
        JBCheckBox(target.note?.let { "${target.label} ($it)" } ?: target.label, true)
    }

    private val skillBox = skillHomes.takeIf { it.isNotEmpty() }?.let {
        JBCheckBox("Install the optics skill for ${it.joinToString(", ")}", true)
    }
    private val scopes = McpClients.Scope.entries.map { JBRadioButton(it.label) }

    // Held in a plain panel rather than a row each: the UI DSL rejects a radio button cell unless
    // it manages the group itself, and managing it would mean binding a property and applying the
    // DialogPanel on OK for a value two getters can read directly.
    private val scopePanel = JPanel(GridLayout(0, 1)).apply { scopes.forEach { add(it) } }

    init {
        title = "Configure Optics MCP Server"
        setOKButtonText("Register")
        ButtonGroup().apply { scopes.forEach { add(it) } }
        scopes.first().isSelected = true
        init()
    }

    override fun createCenterPanel(): JComponent = panel {
        if (boxes.isNotEmpty()) {
            row { label("Add the Optics MCP server to:") }
            for (box in boxes) row { cell(box) }
            separator()
            row { label("Register for:") }
            row { cell(scopePanel) }
        }
        skillBox?.let {
            separator()
            row {
                comment(
                    "The skill tells an agent that optics-framework is newer than its training " +
                        "data, and where the documentation is."
                )
            }
            row { cell(it) }
        }
        row {
            comment(
                "Per project writes into the project directory, which you may want to ignore " +
                    "in git, and Claude Code will ask you to approve it on first use. The entry " +
                    "is copied to your clipboard either way."
            )
        }
    }

    val chosen: List<McpClients.Target>
        get() = targets.filterIndexed { index, _ -> boxes[index].isSelected }

    val scope: McpClients.Scope
        get() = McpClients.Scope.entries[scopes.indexOfFirst { it.isSelected }.coerceAtLeast(0)]

    val skill: Boolean
        get() = skillBox?.isSelected == true
}
