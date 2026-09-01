package ai.mozark.optics.lsp

import com.intellij.openapi.options.BoundConfigurable
import com.intellij.openapi.ui.DialogPanel
import com.intellij.ui.dsl.builder.AlignX
import com.intellij.ui.dsl.builder.bindText
import com.intellij.ui.dsl.builder.panel

class OpticsConfigurable : BoundConfigurable("Optics Framework") {

    override fun createPanel(): DialogPanel = panel {
        row("Python interpreter:") {
            textField()
                .bindText(OpticsSettings.getInstance()::pythonPath)
                .align(AlignX.FILL)
                .comment(
                    "Leave empty to use OPTICS_LSP_PYTHON, then the first python3 on PATH. " +
                        "Python 3.12 or newer is required."
                )
        }
    }

    override fun apply() {
        super.apply()
        restartOpticsServers()
    }
}
