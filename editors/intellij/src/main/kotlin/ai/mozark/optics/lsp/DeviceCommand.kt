package ai.mozark.optics.lsp

import com.google.gson.JsonParser
import com.intellij.execution.configurations.GeneralCommandLine
import java.nio.file.Path
import java.util.concurrent.TimeUnit

data class Device(val id: String, val name: String, val platform: String) {
    override fun toString() = "$name ($platform)"
}

data class Listing(val devices: List<Device>, val notes: List<String>)

/** Blocking: call it off the EDT. */
object DeviceCommand {

    private const val TIMEOUT_SECONDS = 30L

    fun list(python: Path): Listing {
        val root = JsonParser.parseString(String(run(python, "list"))).asJsonObject
        return Listing(
            root["devices"].asJsonArray.map {
                val d = it.asJsonObject
                Device(d["id"].asString, d["name"].asString, d["platform"].asString)
            },
            root["notes"].asJsonArray.map { it.asString },
        )
    }

    fun capture(python: Path, id: String): ByteArray = run(python, "capture", id)

    fun select(python: Path, id: String) {
        run(python, "select", id)
    }

    private fun run(python: Path, vararg args: String): ByteArray {
        val line = GeneralCommandLine(listOf(python.toString()) + OpticsLspDescriptor.LAUNCH_ARGS + "_device" + args)
            .withEnvironment("PYTHONPATH", pythonPath())
            .withEnvironment("PYTHONDONTWRITEBYTECODE", "1")
        OpticsSettings.getInstance().adbPath.takeIf { it.isNotBlank() }?.let { line.withEnvironment("OPTICS_ADB", it) }
        val process = line.createProcess()
        // Stderr is a line or two, so reading stdout to the end first cannot block on a full pipe.
        val out = process.inputStream.readAllBytes()
        val err = process.errorStream.readAllBytes()
        if (!process.waitFor(TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            process.destroyForcibly()
            error("the device command did not finish within ${TIMEOUT_SECONDS}s")
        }
        if (process.exitValue() != 0) error(String(err).trim().ifEmpty { "the device command failed" })
        return out
    }
}
