import ai.mozark.optics.lsp.SkillCopy
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths

class SkillCopyTest {

    private val packaged: Path = Paths.get(System.getProperty("optics.skills"))

    @Test
    fun `every shipped skill is copied whole, and build markers are not`(@TempDir home: Path) {
        val skills = home.resolve("skills")
        SkillCopy.into(packaged, skills)

        for (file in listOf(
            "optics-framework/SKILL.md",
            "optics-to-native/SKILL.md",
            "optics-to-native/references/ios.md",
            "optics-to-native/assets/xcuitest_run_output.swift",
        )) {
            assertTrue(Files.isRegularFile(skills.resolve(file))) { file }
        }
        assertFalse(Files.exists(skills.resolve(".installed")))
    }

    @Test
    fun `a second install overwrites rather than failing`(@TempDir home: Path) {
        SkillCopy.into(packaged, home)
        Files.writeString(home.resolve("optics-to-native/SKILL.md"), "stale")
        SkillCopy.into(packaged, home)
        assertTrue(Files.readString(home.resolve("optics-to-native/SKILL.md")).length > 100)
    }
}
