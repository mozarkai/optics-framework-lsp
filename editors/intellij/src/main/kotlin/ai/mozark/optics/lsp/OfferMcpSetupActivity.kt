package ai.mozark.optics.lsp

import com.intellij.ide.util.PropertiesComponent
import com.intellij.notification.NotificationAction
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.ActionPlaces
import com.intellij.openapi.project.Project
import com.intellij.openapi.startup.ProjectActivity

/**
 * Says once that the plugin can bridge to an AI agent. Nothing else advertises it: the action sits
 * in the Tools menu, and someone who installed this for its diagnostics has no reason to look
 * there. Skipped when no agent is on the machine, since there would be nothing to offer.
 */
class OfferMcpSetupActivity : ProjectActivity {

    override suspend fun execute(project: Project) {
        val properties = PropertiesComponent.getInstance()
        if (properties.getBoolean(SHOWN)) return
        if (McpClients.detected().isEmpty() && McpClients.skillHomes().isEmpty()) return

        NotificationGroupManager.getInstance()
            .getNotificationGroup("Optics")
            .createNotification(
                "Optics: set up your AI agent?",
                "The language server can answer an agent's questions about this project over " +
                    "MCP, and install a skill telling it where the optics documentation is.",
                NotificationType.INFORMATION,
            )
            .addAction(
                // Expiring: a sticky balloon has no timeout, so without this the offer stays on
                // screen after it has been taken.
                NotificationAction.createSimpleExpiring("Set up now") {
                    val manager = ActionManager.getInstance()
                    manager.getAction(CONFIGURE)?.let {
                        manager.tryToExecute(it, null, null, ActionPlaces.NOTIFICATION, true)
                    }
                }
            )
            .notify(project)

        // Marked only once it is actually on screen, so a failure to show is retried next time
        // rather than silently consuming the single offer.
        properties.setValue(SHOWN, true)
    }

    private companion object {
        // Application-wide rather than per project: the offer is about this machine's agents.
        const val SHOWN = "ai.mozark.optics.mcpOfferShown"
        const val CONFIGURE = "optics.mcp.configure"
    }
}
