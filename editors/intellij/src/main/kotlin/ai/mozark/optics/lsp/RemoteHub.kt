package ai.mozark.optics.lsp

import com.google.gson.Gson
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.intellij.openapi.project.Project
import com.intellij.platform.lsp.api.LspClientManager
import org.eclipse.lsp4j.ExecuteCommandParams

/** What the language server offers for a device on a hub: only it can hold a session there. */
object RemoteHub {

    private const val TIMEOUT_MS = 300_000

    fun device(project: Project, uri: String): Device? {
        val found = ask(project, "optics.remoteDevice", uri) as? JsonObject ?: return null
        return Device(found["id"].asString, found["name"].asString, found["platform"].asString)
    }

    fun screenshot(project: Project, uri: String): JsonObject =
        ask(project, "optics.remoteScreen", uri) as? JsonObject ?: JsonObject()

    private fun ask(project: Project, command: String, vararg args: String): JsonElement? {
        val client = LspClientManager.getInstance(project).getClients(OpticsLspIntegrationProvider::class.java).firstOrNull()
            ?: return null
        val raw = client.sendRequestSync(TIMEOUT_MS) {
            it.workspaceService.executeCommand(ExecuteCommandParams(command, args.toList<Any>()))
        }
        return Gson().toJsonTree(raw).takeIf { !it.isJsonNull }
    }
}
