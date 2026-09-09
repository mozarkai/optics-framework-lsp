package ai.mozark.optics.lsp

/**
 * How an MCP client is told to launch the bridge. Separate from [OpticsMcp] so the serverTest
 * suite, which has no IntelliJ platform on its classpath, can assert the shape.
 *
 * agent-lsp needs no config file: the language server is one argument, `id:command,arg,arg`. The
 * interpreter's `PYTHONPATH` has to reach it through the environment instead, since the bridge
 * passes its own env to the server it spawns.
 */
object OpticsMcpConfig {

    /** The name every client knows the server by. */
    const val NAME = "optics-lsp"

    /**
     * The language id agent-lsp routes under. Deliberately not [NAME]: the two appear side by side
     * in `claude mcp list`, and the same word twice reads as two servers.
     */
    const val LANGUAGE = "optics-csv"

    /**
     * The single argument that tells agent-lsp what to run. Comma-separated after the language id,
     * which is why nothing here may contain a comma — an interpreter path never does.
     */
    fun serverSpec(python: String, args: List<String>): String =
        (listOf(python) + args).joinToString(",", prefix = "$LANGUAGE:")

    /** What the server needs in its environment: the bundled payload, and no bytecode written. */
    fun serverEnv(libs: String): Map<String, String> = mapOf(
        "PYTHONPATH" to libs,
        // Otherwise the server writes __pycache__ into the payload we packaged.
        "PYTHONDONTWRITEBYTECODE" to "1",
    )
}
