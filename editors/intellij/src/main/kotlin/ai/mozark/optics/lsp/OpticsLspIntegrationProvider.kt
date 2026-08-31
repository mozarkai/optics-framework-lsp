package ai.mozark.optics.lsp

import com.intellij.notification.NotificationAction
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.options.ShowSettingsUtil
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.platform.lsp.api.LspClientManager
import com.intellij.platform.lsp.api.LspIntegrationProvider
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean

class OpticsLspIntegrationProvider : LspIntegrationProvider {

    override fun fileOpened(
        project: Project,
        file: VirtualFile,
        clientStarter: LspIntegrationProvider.LspClientStarter,
    ) {
        if (file.extension != "csv") return

        when (val python = OpticsPython.resolve()) {
            is OpticsPython.Result.Ok ->
                clientStarter.ensureClientStarted(OpticsLspDescriptor(project, python.exe))

            // This runs under a read action, so the interpreter cannot be run here. Probe on a
            // pooled thread and ask the platform to reconsider the open files afterwards.
            OpticsPython.Result.Unprobed -> probeThenRetry(project)

            OpticsPython.Result.NotFound -> warnOnce(
                project,
                "No Python 3.12 or newer was found on PATH. Set an interpreter under " +
                    "Settings | Tools | Optics Framework.",
            )

            is OpticsPython.Result.TooOld -> warnOnce(
                project,
                "Python ${OpticsPython.describe(python.version)} at ${python.exe} is too old. " +
                    "The Optics language server needs 3.12 or newer.",
            )
        }
    }

    private fun probeThenRetry(project: Project) {
        if (!probing.compareAndSet(false, true)) return
        val application = ApplicationManager.getApplication()
        application.executeOnPooledThread {
            try {
                OpticsPython.probeBlocking()
            } finally {
                probing.set(false)
            }
            application.invokeLater {
                if (!project.isDisposed) {
                    LspClientManager.getInstance(project)
                        .startClientsIfNeeded(OpticsLspIntegrationProvider::class.java)
                }
            }
        }
    }

    /** Once per project per message: a failed resolution repeats on every CSV opened. */
    private fun warnOnce(project: Project, message: String) {
        if (!warned.add(project.locationHash + message)) return
        NotificationGroupManager.getInstance()
            .getNotificationGroup("Optics")
            .createNotification("Optics language server not started", message, NotificationType.WARNING)
            .addAction(
                NotificationAction.createSimple("Configure…") {
                    ShowSettingsUtil.getInstance()
                        .showSettingsDialog(project, OpticsConfigurable::class.java)
                }
            )
            .notify(project)
    }

    companion object {
        private val probing = AtomicBoolean(false)
        private val warned = ConcurrentHashMap.newKeySet<String>()

        fun resetWarnings() = warned.clear()
    }
}
