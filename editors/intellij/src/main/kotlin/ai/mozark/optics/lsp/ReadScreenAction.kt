package ai.mozark.optics.lsp

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.application.ApplicationManager
import com.intellij.platform.lsp.api.LspClientManager
import org.eclipse.lsp4j.ExecuteCommandParams

/** A remote device is only read when asked, and takes about 15 seconds. */
class ReadScreenAction : AnAction() {

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val uri = e.getData(CommonDataKeys.VIRTUAL_FILE)?.toNioPath()?.toUri()?.toString() ?: return
        ApplicationManager.getApplication().executeOnPooledThread {
            for (client in LspClientManager.getInstance(project).getClients(OpticsLspIntegrationProvider::class.java)) {
                runCatching {
                    client.sendRequestSync(TIMEOUT_MS) {
                        it.workspaceService.executeCommand(ExecuteCommandParams("optics.readScreen", listOf(uri)))
                    }
                }
            }
        }
    }

    private companion object {
        const val TIMEOUT_MS = 300_000
    }
}
