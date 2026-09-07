package ai.mozark.optics.lsp

import com.google.gson.GsonBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.stream.JsonReader
import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.execution.configurations.PathEnvironmentVariableUtil
import com.intellij.execution.process.CapturingProcessHandler
import com.intellij.ide.plugins.PluginManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.extensions.PluginId
import com.intellij.util.SystemProperties
import java.io.Reader
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import kotlin.io.path.exists
import kotlin.io.path.readText

/**
 * The agents on this machine that keep their own MCP config, and how to add an entry to each.
 *
 * AI Assistant reads a JSON file, so `merge` writes it. Claude Code is driven through its CLI
 * instead: it owns its schema, and `claude mcp add` is a supported interface where its config file
 * is not.
 *
 * GitHub Copilot is deliberately absent: registering it was not behaving reliably enough to ship.
 * It reads `~/.config/github-copilot/intellij/mcp.json` globally and `<project>/.github/mcp.json`
 * per project, both keyed on `servers`, so the clipboard entry covers it by hand.
 */
object McpClients {

    /** Where an entry is written. Every client supports both. */
    enum class Scope(val label: String) {
        GLOBAL("Every project on this machine"),
        PROJECT("This project only"),
    }

    class Target(
        val label: String,
        /** What the user should know before ticking it, if anything. */
        val note: String?,
        private val install: (Request) -> Unit,
    ) {
        fun register(request: Request) = install(request)
    }

    /**
     * Everything a registration needs. agent-lsp takes its workspace from the directory the agent
     * spawns it in, so no project path is baked into the entry — only into where it is written.
     */
    data class Request(
        val binary: Path,
        val spec: String,
        val env: Map<String, String>,
        val scope: Scope,
        val projectRoot: Path,
    )

    /** Referenced by the caller to say what a project-scope registration still needs. */
    const val CLAUDE_CODE = "Claude Code"

    private const val CLI_TIMEOUT_MS = 15_000

    private val log = logger<McpClients>()

    /**
     * Logged rather than reported silently: an empty list is indistinguishable from a successful
     * no-op once the action finishes, which is not a diagnosis anyone can act on.
     */
    fun detected(): List<Target> {
        val found = listOfNotNull(aiAssistant(), claudeCode())
        log.info(
            if (found.isEmpty()) {
                "no MCP client detected: AI Assistant plugin absent, no claude on PATH"
            } else {
                "MCP clients detected: ${found.joinToString(", ") { it.label }}"
            }
        )
        return found
    }

    /**
     * AI Assistant reads `~/.ai/mcp/mcp.json`, or `.ai/mcp/mcp.json` in the project. Not the
     * `llm.mcpServers.xml` beside it: that one is the plugin's own serialized state, which the IDE
     * rewrites on save.
     */
    private fun aiAssistant(): Target? {
        if (!PluginManager.isPluginInstalled(PluginId.getId("com.intellij.ml.llm"))) return null
        return Target("JetBrains AI Assistant", null) { request ->
            val file = when (request.scope) {
                Scope.GLOBAL -> Path.of(SystemProperties.getUserHome())
                Scope.PROJECT -> request.projectRoot
            }.resolve(".ai").resolve("mcp").resolve("mcp.json")
            merge(file, "mcpServers", request)
        }
    }

    /**
     * `--scope user` writes Claude Code's own config; `--scope project` writes `.mcp.json`, which
     * Claude lists as pending until it is approved in an interactive session.
     */
    private fun claudeCode(): Target? {
        val cli = PathEnvironmentVariableUtil.findInPath("claude")?.toPath() ?: return null
        return Target(CLAUDE_CODE, null) { request ->
            val scope = if (request.scope == Scope.GLOBAL) "user" else "project"

            // `add` refuses when the name is taken and has no --force, so re-running the action
            // would fail where the JSON clients simply overwrite. Scoped, so registering for one
            // scope never drops the entry in the other. A missing entry exits non-zero; ignored.
            CapturingProcessHandler(
                GeneralCommandLine(cli.toString(), "mcp", "remove", OpticsMcpConfig.NAME)
                    .withParameters("--scope", scope)
                    .withWorkDirectory(request.projectRoot.toFile())
            ).runProcess(CLI_TIMEOUT_MS)

            val command = GeneralCommandLine(cli.toString(), "mcp", "add", OpticsMcpConfig.NAME)
                .withParameters("--scope", scope)
            for ((key, value) in request.env) {
                command.addParameters("-e", "$key=$value")
            }
            command.addParameters("--", request.binary.toString(), request.spec)
            command.withWorkDirectory(request.projectRoot.toFile())

            val output = CapturingProcessHandler(command).runProcess(CLI_TIMEOUT_MS)
            if (output.exitCode != 0) {
                throw IllegalStateException(
                    output.stderr.ifBlank { output.stdout }.trim()
                        .ifBlank { "claude mcp add exited ${output.exitCode}" }
                )
            }
        }
    }

    /**
     * Adds our entry to a client's JSON, leaving every other server alone. Read leniently: these
     * files are often JSONC by convention, though comments do not survive the rewrite.
     */
    private fun merge(file: Path, rootKey: String, request: Request) {
        val root = file.takeIf { it.exists() }
            ?.readText()
            ?.takeIf { it.isNotBlank() }
            ?.let { JsonParser.parseReader(lenient(it.reader())) }
            ?.takeIf { it.isJsonObject }
            ?.asJsonObject
            ?: JsonObject()

        val servers = root.getAsJsonObject(rootKey) ?: JsonObject().also { root.add(rootKey, it) }
        servers.add(OpticsMcpConfig.NAME, entry(request))

        Files.createDirectories(file.parent)
        Files.writeString(file, pretty(root))
    }

    /** The one entry shape, whether it is merged into a client's file or handed to the user. */
    private fun entry(request: Request): JsonObject = JsonObject().apply {
        addProperty("type", "stdio")
        addProperty("command", request.binary.toString())
        add("args", JsonArray().apply { add(request.spec) })
        add(
            "env",
            JsonObject().apply { for ((key, value) in request.env) addProperty(key, value) },
        )
    }

    /** What the user pastes into an agent we cannot write to. Gson handles the escaping. */
    fun clipboardEntry(request: Request): String = pretty(
        JsonObject().apply {
            add("mcpServers", JsonObject().apply { add(OpticsMcpConfig.NAME, entry(request)) })
        }
    )

    private fun pretty(json: JsonObject): String =
        GsonBuilder().setPrettyPrinting().create().toJson(json)

    private fun lenient(reader: Reader) = JsonReader(reader).apply { isLenient = true }

    /**
     * Where each agent reads Agent Skills from. Installed only where the parent already exists:
     * that is the evidence the tool is present, since the `skills` directory itself is often
     * absent until something writes one.
     */
    private val SKILL_HOMES = mapOf(
        "Claude Code" to listOf(".claude"),
        "Cursor" to listOf(".cursor"),
        "Gemini CLI" to listOf(".config", "gemini-cli"),
    )

    /** The agents that would read the skill if it were installed. */
    fun skillHomes(): List<String> =
        SKILL_HOMES.filterValues { home(it).exists() }.keys.toList()

    /**
     * Installs the skill, which tells an agent the framework post-dates its training data and
     * where the documentation is. Separate from the MCP registration because it is a different
     * mechanism: the bridge owns the MCP `instructions` field, so this is the only way to say it.
     *
     * Only our own directory is written; the agent's own files are left alone.
     */
    fun installSkill(source: Path): List<String> = skillHomes().onEach { label ->
        val target = home(SKILL_HOMES.getValue(label))
            .resolve("skills").resolve("optics-framework").resolve("SKILL.md")
        Files.createDirectories(target.parent)
        Files.copy(source, target, StandardCopyOption.REPLACE_EXISTING)
    }

    private fun home(parts: List<String>): Path =
        parts.fold(Path.of(SystemProperties.getUserHome()), Path::resolve)

}
