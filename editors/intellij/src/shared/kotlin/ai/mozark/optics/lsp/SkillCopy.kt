package ai.mozark.optics.lsp

import java.nio.file.Files
import java.nio.file.Path

object SkillCopy {

    /** Every skill folder under [source], whole. Plain files beside them are build markers. */
    fun into(source: Path, skills: Path) {
        Files.list(source).use { it.toList() }.filter { Files.isDirectory(it) }.forEach {
            it.toFile().copyRecursively(skills.resolve(it.fileName).toFile(), overwrite = true)
        }
    }
}
