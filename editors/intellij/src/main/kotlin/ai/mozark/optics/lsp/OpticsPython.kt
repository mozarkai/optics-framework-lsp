package ai.mozark.optics.lsp

import com.intellij.execution.ExecutionException
import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.execution.configurations.PathEnvironmentVariableUtil
import com.intellij.execution.process.CapturingProcessHandler
import com.intellij.util.EnvironmentUtil
import java.nio.file.Path
import java.util.concurrent.ConcurrentHashMap

/**
 * Finds an interpreter, and refuses one below 3.12 — there the server dies on `Path.walk()` in a log
 * nobody opens. Establishing the version means running it, which a read action forbids, so
 * [resolve] answers from cache only and [probeBlocking] is the part a caller hands to a thread.
 */
object OpticsPython {

    /** Encoded as major * 100 + minor so it compares as a plain Int. */
    private const val MIN_VERSION = 312
    private const val PROBE_TIMEOUT_MS = 5_000
    private const val UNUSABLE = -1

    private val probed = ConcurrentHashMap<String, Int>()

    sealed interface Result {
        data class Ok(val exe: Path) : Result
        data object NotFound : Result
        data class TooOld(val exe: Path, val version: Int) : Result

        /** No verdict yet: the caller should run [probeBlocking] off the current thread. */
        data object Unprobed : Result
    }

    /** Cheap and non-blocking, so it is safe under a read action. */
    fun resolve(): Result {
        val exe = candidate() ?: return Result.NotFound
        val version = probed[exe.toString()] ?: return Result.Unprobed
        return when {
            version == UNUSABLE -> Result.NotFound
            version < MIN_VERSION -> Result.TooOld(exe, version)
            else -> Result.Ok(exe)
        }
    }

    /** Runs the interpreter. Never call this on the EDT or under a read action. */
    fun probeBlocking() {
        val exe = candidate() ?: return
        probed.computeIfAbsent(exe.toString()) { probe(exe) }
    }

    /** Call after the setting changes, so a corrected path is not answered from the cache. */
    fun invalidate() = probed.clear()

    fun describe(version: Int): String = "${version / 100}.${version % 100}"

    private fun candidate(): Path? {
        configured(OpticsSettings.getInstance().pythonPath)?.let { return it }
        configured(EnvironmentUtil.getValue("OPTICS_LSP_PYTHON"))?.let { return it }
        // Reads PATH via EnvironmentUtil, which on macOS is the shell PATH rather than the empty
        // one a GUI-launched IDE inherits, and appends %PATHEXT% on Windows.
        return onPath("python3") ?: onPath("python")
    }

    private fun onPath(name: String): Path? =
        PathEnvironmentVariableUtil.findInPath(name)?.toPath()

    private fun configured(value: String?): Path? =
        value?.trim()?.takeIf { it.isNotEmpty() }?.let { Path.of(it) }

    private fun probe(exe: Path): Int =
        try {
            val command = GeneralCommandLine(
                exe.toString(), "-c",
                "import sys;print(sys.version_info[0] * 100 + sys.version_info[1])",
            )
            val output = CapturingProcessHandler(command).runProcess(PROBE_TIMEOUT_MS)
            if (output.exitCode == 0) output.stdout.trim().toIntOrNull() ?: UNUSABLE else UNUSABLE
        } catch (_: ExecutionException) {
            UNUSABLE
        }
}
