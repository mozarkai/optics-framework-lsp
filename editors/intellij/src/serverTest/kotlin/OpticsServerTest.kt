import java.io.InputStream
import java.nio.file.Path
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.io.path.readText
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assertions.fail
import org.junit.jupiter.api.Test

/**
 * End-to-end check of the shipped payload: bundled libs, launch args, stdio framing and the
 * server's own parse/validate/publish path. No IDE, so it runs in seconds. Framing is hand-rolled
 * to avoid an LSP4J dependency that could collide with the platform's copy.
 */
class OpticsServerTest {

    @Test
    fun `publishes a diagnostic for a step naming no module`() {
        val fixture = Path.of(System.getProperty("optics.fixture"))
        val testCases = fixture.resolve("test_cases.csv")

        val process = ProcessBuilder(python(), "-S", "-m", "optics_framework_lsp")
            .directory(fixture.toFile())
            .apply {
                environment()["PYTHONPATH"] = System.getProperty("optics.bundledLibs")
                // Otherwise this run litters the shared payload with __pycache__ for whichever
                // interpreter happens to be on PATH, and that lands in the packaged plugin.
                environment()["PYTHONDONTWRITEBYTECODE"] = "1"
            }
            .redirectError(ProcessBuilder.Redirect.INHERIT)
            .start()

        try {
            val frames = LinkedBlockingQueue<String>()
            Thread({ readFrames(process.inputStream, frames) }, "optics-lsp-reader")
                .apply { isDaemon = true }
                .start()

            val root = fixture.toUri().toString().removeSuffix("/")
            send(
                process, """{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
                  "processId":null,"rootUri":"$root","capabilities":{},
                  "workspaceFolders":[{"uri":"$root","name":"broken-suite"}]}}"""
            )
            send(process, """{"jsonrpc":"2.0","method":"initialized","params":{}}""")
            send(
                process, """{"jsonrpc":"2.0","method":"textDocument/didOpen","params":{
                  "textDocument":{"uri":"${testCases.toUri()}","languageId":"plaintext",
                  "version":1,"text":${quote(testCases.readText())}}}}"""
            )

            val diagnostics = awaitDiagnostics(frames, testCases)
            assertTrue(diagnostics.contains("Missing Module")) {
                "expected a diagnostic naming the unknown module, got: $diagnostics"
            }
            // Row 3 of the fixture, zero-based.
            assertTrue(Regex(""""line"\s*:\s*2""").containsMatchIn(diagnostics)) {
                "expected the diagnostic on line 2, got: $diagnostics"
            }
        } finally {
            process.destroyForcibly()
        }
    }

    private fun python(): String = System.getenv("OPTICS_LSP_PYTHON") ?: "python3"

    private fun send(process: Process, json: String) {
        val body = json.trimIndent().replace("\n", "").toByteArray()
        process.outputStream.apply {
            write("Content-Length: ${body.size}\r\n\r\n".toByteArray())
            write(body)
            flush()
        }
    }

    /** Waits for a publishDiagnostics for the given file that actually carries a finding. */
    private fun awaitDiagnostics(frames: LinkedBlockingQueue<String>, file: Path): String {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30)
        while (System.nanoTime() < deadline) {
            val frame = frames.poll(1, TimeUnit.SECONDS) ?: continue
            if (!frame.contains("textDocument/publishDiagnostics")) continue
            if (!frame.contains(file.fileName.toString())) continue
            if (frame.contains(""""diagnostics":[]""")) continue
            return frame
        }
        return fail<String>("no diagnostics published within 30s")
    }

    /** Content-Length counts bytes, so the body is read as bytes and decoded afterwards. */
    private fun readFrames(stream: InputStream, into: LinkedBlockingQueue<String>) {
        while (true) {
            var length = -1
            while (true) {
                val line = readLine(stream) ?: return
                if (line.isEmpty()) break
                if (line.startsWith("Content-Length:", ignoreCase = true)) {
                    length = line.substringAfter(':').trim().toInt()
                }
            }
            if (length < 0) return
            val body = ByteArray(length)
            var read = 0
            while (read < length) {
                val n = stream.read(body, read, length - read)
                if (n < 0) return
                read += n
            }
            into.put(String(body, Charsets.UTF_8))
        }
    }

    /** Header lines are ASCII and CRLF-terminated; stops at the blank separator line. */
    private fun readLine(stream: InputStream): String? {
        val line = StringBuilder()
        while (true) {
            when (val b = stream.read()) {
                -1 -> return if (line.isEmpty()) null else line.toString()
                '\n'.code -> return line.toString()
                '\r'.code -> {}
                else -> line.append(b.toChar())
            }
        }
    }

    /** Enough escaping for the one CSV body this test sends; the fixture is ours. */
    private fun quote(text: String): String =
        "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\""
}
