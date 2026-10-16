package ai.mozark.optics.lsp

import com.intellij.openapi.options.BoundConfigurable
import com.intellij.openapi.ui.DialogPanel
import com.intellij.ui.dsl.builder.AlignX
import com.intellij.ui.dsl.builder.bindSelected
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
        row {
            checkBox("Suggest elements from the connected Android emulator's screen")
                .bindSelected(OpticsSettings.getInstance()::screenElements)
                .comment(
                    "Reads the device in the background, about every 10 seconds and not while a " +
                        "test is running. Takes effect when the language server restarts."
                )
        }
        row {
            checkBox("Download a missing helper tool (Android platform-tools from Google)")
                .bindSelected(OpticsSettings.getInstance()::autoInstall)
                .comment("Checked against a pinned checksum. Turn off to use only your own, and set the adb binary below.")
        }
        row("adb binary:") {
            textField()
                .bindText(OpticsSettings.getInstance()::adbPath)
                .align(AlignX.FILL)
                .comment(
                    "Used by the Optics Device tool window. Leave empty to use adb from ANDROID_HOME " +
                        "or PATH."
                )
        }
        row("MCP bridge binary:") {
            textField()
                .bindText(OpticsSettings.getInstance()::bridgePath)
                .align(AlignX.FILL)
                .comment(
                    "agent-lsp, which offers the server to AI agents. Leave empty to download it " +
                        "when Tools | Configure Optics LSP MCP Server is first used."
                )
        }
    }

    override fun apply() {
        super.apply()
        restartOpticsServers()
    }
}
