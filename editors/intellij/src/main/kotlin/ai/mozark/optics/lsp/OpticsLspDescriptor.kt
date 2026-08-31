package ai.mozark.optics.lsp

import com.intellij.codeInsight.intention.IntentionAction
import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.ide.plugins.PluginManagerCore
import com.intellij.lang.annotation.AnnotationHolder
import com.intellij.openapi.extensions.PluginId
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.TextRange
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.platform.lsp.api.ProjectWideLspClientDescriptor
import com.intellij.platform.lsp.api.customization.LspCustomization
import com.intellij.platform.lsp.api.customization.LspDiagnosticsCustomizer
import com.intellij.platform.lsp.api.customization.LspDiagnosticsSupport
import com.intellij.util.EnvironmentUtil
import org.eclipse.lsp4j.Diagnostic
import java.io.File
import java.nio.file.Path

/** Project-wide because the server is: every feature returns empty outside the workspace folders. */
class OpticsLspDescriptor(project: Project, private val python: Path) :
    ProjectWideLspClientDescriptor(project, "Optics") {

    /** Every CSV: the server classifies by header row, so narrowing by name would hide real suites. */
    override fun isSupportedFile(file: VirtualFile): Boolean = file.extension == "csv"

    override fun createCommandLine(): GeneralCommandLine =
        GeneralCommandLine(python.toString(), "-S", "-m", "optics_framework_lsp")
            .withWorkDirectory(project.basePath)
            .withEnvironment("PYTHONPATH", pythonPath())
            // Otherwise the server writes __pycache__ into the payload we packaged.
            .withEnvironment("PYTHONDONTWRITEBYTECODE", "1")

    /** The platform compares descriptors to decide whether to restart; without these every CSV looks new. */
    override fun equals(other: Any?): Boolean =
        other is OpticsLspDescriptor && other.project == project && other.python == python

    override fun hashCode(): Int = 31 * project.hashCode() + python.hashCode()

    override val lspCustomization: LspCustomization =
        object : LspCustomization() {
            override val diagnosticsCustomizer: LspDiagnosticsCustomizer = OpticsDiagnostics
        }

    /**
     * LspHighlightingApplier validates ranges against the Document but annotates the PsiFile, which
     * lags it by any uncommitted edit — so range() throws past the PSI's end. Clamp to what we are
     * annotating; the daemon redraws full width once the commit lands.
     */
    private object OpticsDiagnostics : LspDiagnosticsSupport() {
        override fun createAnnotation(
            holder: AnnotationHolder,
            diagnostic: Diagnostic,
            textRange: TextRange,
            quickFixes: List<IntentionAction>,
        ) {
            val length = holder.currentAnnotationSession.file.textLength
            if (textRange.startOffset > length) return
            val clamped =
                if (textRange.endOffset <= length) textRange
                else TextRange(textRange.startOffset, length)
            super.createAnnotation(holder, diagnostic, clamped, quickFixes)
        }
    }

    private companion object {
        val PLUGIN_ID: PluginId = PluginId.getId("ai.mozark.optics-framework-lsp")

        /** `-S` keeps site-packages out, so this is the only importable tree — which is what makes
         * borrowing an arbitrary interpreter safe. */
        val bundledLibs: Path by lazy {
            checkNotNull(PluginManagerCore.getPlugin(PLUGIN_ID)) { "plugin descriptor missing" }
                .pluginPath.resolve("bundled/libs")
        }

        fun pythonPath(): String {
            val existing = EnvironmentUtil.getValue("PYTHONPATH")
            return if (existing.isNullOrEmpty()) bundledLibs.toString()
            else bundledLibs.toString() + File.pathSeparator + existing
        }
    }
}
