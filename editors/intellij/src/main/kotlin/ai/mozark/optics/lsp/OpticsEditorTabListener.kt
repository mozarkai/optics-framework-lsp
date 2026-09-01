package ai.mozark.optics.lsp

import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.FileEditorManagerListener
import com.intellij.openapi.fileEditor.impl.LoadTextUtil
import com.intellij.openapi.fileEditor.impl.text.TextEditorProvider
import com.intellij.openapi.vfs.VirtualFile

/** Optics suites are source, not data: the table editor hides the row grouping and shows no
 * language features. Ordinary CSVs are left on whichever tab the IDE prefers. */
class OpticsEditorTabListener : FileEditorManagerListener {

    override fun fileOpened(source: FileEditorManager, file: VirtualFile) {
        if (!isOpticsSuite(file)) return
        source.setSelectedEditor(file, TextEditorProvider.getInstance().editorTypeId)
    }

    private fun isOpticsSuite(file: VirtualFile): Boolean {
        if (!file.name.endsWith(".csv", ignoreCase = true)) return false
        // The header is the first line; no point reading a multi-megabyte export to find out.
        val header = LoadTextUtil.loadText(file, 4096)
            .lineSequence()
            .firstOrNull { it.isNotBlank() }
            ?: return false
        return OpticsHeader.matches(header)
    }
}
