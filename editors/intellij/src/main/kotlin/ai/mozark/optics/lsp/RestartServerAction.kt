package ai.mozark.optics.lsp

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.project.ProjectManager
import com.intellij.platform.lsp.api.LspClientManager

/** The only reason to restart is that resolution may have changed, so both caches drop here. */
internal fun restartOpticsServers() {
    OpticsPython.invalidate()
    OpticsLspIntegrationProvider.resetWarnings()
    for (project in ProjectManager.getInstance().openProjects) {
        LspClientManager.getInstance(project)
            .stopAndRestartClientsIfNeeded(OpticsLspIntegrationProvider::class.java)
    }
}

class RestartServerAction : AnAction() {

    override fun actionPerformed(e: AnActionEvent) = restartOpticsServers()
}
