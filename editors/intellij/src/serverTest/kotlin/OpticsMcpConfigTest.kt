import ai.mozark.optics.lsp.OpticsMcpConfig
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

/**
 * agent-lsp takes the language server as one comma-separated argument, so a wrong shape here is an
 * MCP server that starts and then bridges nothing.
 */
class OpticsMcpConfigTest {

    private val args = listOf("-S", "-m", "optics_framework_lsp")

    @Test
    fun `the spec names the language id, distinct from the server name, then the command`() {
        assertEquals(
            "optics-csv:/usr/bin/python3,-S,-m,optics_framework_lsp",
            OpticsMcpConfig.serverSpec("/usr/bin/python3", args),
        )
    }

    @Test
    fun `a windows interpreter path survives the spec`() {
        // Backslashes are not separators here, only commas are.
        assertEquals(
            """optics-csv:C:\Python312\python.exe,-S,-m,optics_framework_lsp""",
            OpticsMcpConfig.serverSpec("""C:\Python312\python.exe""", args),
        )
    }

    @Test
    fun `the environment carries the bundled payload and suppresses bytecode`() {
        assertEquals(
            mapOf("PYTHONPATH" to "/plugin/bundled/libs", "PYTHONDONTWRITEBYTECODE" to "1"),
            OpticsMcpConfig.serverEnv("/plugin/bundled/libs"),
        )
    }
}
