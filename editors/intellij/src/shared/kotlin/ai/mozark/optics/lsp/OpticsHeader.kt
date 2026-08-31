package ai.mozark.optics.lsp

/**
 * Whether a header row marks the file as an optics suite, mirroring `parser/csv_parser.py`. The
 * filename tells you nothing, and getting this wrong hijacks somebody's spreadsheet.
 */
object OpticsHeader {

    /** Both columns of a pair must be present, as the parser requires. */
    private val KINDS = listOf(
        "test_case" to "test_step",
        "module_name" to "module_step",
        "element_name" to "element_id",
        "error_code" to "match_string",
    )

    fun matches(headerRow: String): Boolean {
        // Lowercased and trimmed, as read_csv_headers does: the shipped samples write
        // `Element_Name,Element_ID`, and classification is case-insensitive.
        val cells = headerRow.split(',').map { it.trim().trim('"').lowercase() }.toSet()
        return KINDS.any { (first, second) -> first in cells && second in cells }
    }
}
