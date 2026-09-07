package ai.mozark.optics.lsp

import com.intellij.openapi.application.PathManager
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.util.SystemInfo
import com.intellij.util.io.Decompressor
import com.intellij.util.io.HttpRequests
import com.intellij.util.system.CpuArch
import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest
import java.util.HexFormat
import kotlin.io.path.deleteIfExists
import kotlin.io.path.exists
import kotlin.io.path.isExecutable

/**
 * The same answers the editor gets, offered to an AI agent.
 *
 * [agent-lsp](https://github.com/blackwell-systems/agent-lsp) is a generic LSP-to-MCP bridge: it
 * spawns a language server and re-exposes its requests as MCP tools. It needs no config file — the
 * server is one command-line argument — and it takes its workspace from the working directory the
 * agent spawns it in.
 *
 * The IDE has no extension point for contributing an MCP server, so unlike the VS Code client this
 * cannot register itself; [ConfigureMcpAction] writes the agents' own config instead.
 *
 * The binary is fetched on demand rather than bundled, which keeps one platform-independent plugin
 * zip. [OpticsSettings.bridgePath] skips the fetch, for a network that cannot reach GitHub.
 */
object OpticsMcp {

    /**
     * Pinned, not floated: the checksums below are the ones published with this release, and
     * `agent-lsp update` must never be called — the binary that runs is the binary we verified.
     */
    const val VERSION = "0.19.2"

    private const val RELEASE =
        "https://github.com/blackwell-systems/agent-lsp/releases/download/v$VERSION"

    private data class Asset(val archive: String, val sha256: String)

    private val assets = mapOf(
        "mac-aarch64" to Asset(
            "agent-lsp_darwin_arm64.tar.gz",
            "b5ae67f20e7aedc511bedee875f0a25066c0ab493d765fed53b4cc8c8d425e2e",
        ),
        "mac-x86_64" to Asset(
            "agent-lsp_darwin_amd64.tar.gz",
            "44943ad9065c22f90376de8a1242787a3a3d0ee5c6df779bfa22b59fbeac8d6e",
        ),
        "linux-aarch64" to Asset(
            "agent-lsp_linux_arm64.tar.gz",
            "325ad82236e976d4b0741167fcdbaa9125c9f4852e63fab553692a7495dc5153",
        ),
        "linux-x86_64" to Asset(
            "agent-lsp_linux_amd64.tar.gz",
            "03a8cdc9a190a096d1e865154daf37d2d15fbdbc1ea0655b46ffe483e8ffeca9",
        ),
        "windows-aarch64" to Asset(
            "agent-lsp_windows_arm64.zip",
            "65fe0ef6f70828f7739a4941f43bf8e73a9173ad110ec63e6337a3010b355d47",
        ),
        "windows-x86_64" to Asset(
            "agent-lsp_windows_amd64.zip",
            "938eccf79cc957090b20aadce71ff46cdf14931e925d4436908cd598e0b5a92b",
        ),
    )

    class UnavailableException(message: String) : Exception(message)

    /** Version in the directory name, so a bump is a fresh download rather than a stale hit. */
    private fun home(): Path =
        Path.of(PathManager.getSystemPath(), "optics-framework-lsp", "agent-lsp-$VERSION")

    /**
     * The configured binary if there is one, else the cached download, else fetch it. Runs the
     * network, so never on the EDT.
     */
    @Throws(UnavailableException::class)
    fun binaryBlocking(indicator: ProgressIndicator?): Path {
        OpticsSettings.getInstance().bridgePath.trim().takeIf { it.isNotEmpty() }?.let {
            return Path.of(it)
        }

        val asset = assets[platform()]
            ?: throw UnavailableException(
                "agent-lsp publishes no build for ${platform()}. Set a binary under " +
                    "Settings | Tools | Optics Framework."
            )

        val binary = home().resolve(if (SystemInfo.isWindows) "agent-lsp.exe" else "agent-lsp")
        if (binary.exists()) return binary

        val archive = home().resolve(asset.archive)
        try {
            Files.createDirectories(home())
            // HttpRequests rather than a raw connection: it honours the IDE's proxy settings, which
            // is the difference between working and not on a corporate network.
            HttpRequests.request("$RELEASE/${asset.archive}").saveToFile(archive, indicator)

            val digest = sha256(archive)
            if (digest != asset.sha256) {
                throw UnavailableException(
                    "agent-lsp $VERSION checksum mismatch: expected ${asset.sha256}, got $digest"
                )
            }

            if (asset.archive.endsWith(".zip")) {
                Decompressor.Zip(archive).extract(home())
            } else {
                Decompressor.Tar(archive).extract(home())
            }
        } catch (error: IOException) {
            throw UnavailableException("Could not install agent-lsp $VERSION: ${error.message}")
        } finally {
            archive.deleteIfExists()
        }

        if (!binary.exists()) {
            throw UnavailableException("agent-lsp $VERSION unpacked without a ${binary.fileName}")
        }
        if (!binary.isExecutable()) {
            binary.toFile().setExecutable(true, true)
        }
        return binary
    }

    private fun platform(): String {
        val name = when {
            SystemInfo.isMac -> "mac"
            SystemInfo.isWindows -> "windows"
            else -> "linux"
        }
        return "$name-${if (CpuArch.isArm64()) "aarch64" else "x86_64"}"
    }

    /** Read whole: the archive is a few megabytes, and a streaming loop buys nothing here. */
    private fun sha256(file: Path): String =
        HexFormat.of().formatHex(
            MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file))
        )
}
