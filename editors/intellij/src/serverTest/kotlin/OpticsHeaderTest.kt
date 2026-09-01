import ai.mozark.optics.lsp.OpticsHeader
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * A false positive here means opening somebody's spreadsheet on the wrong editor tab.
 */
class OpticsHeaderTest {

    @Test
    fun `recognises each suite kind, case-insensitively`() {
        for (header in listOf(
            "test_case,test_step",
            "module_name,module_step,param_1,param_2",
            "Element_Name,Element_ID",
            "error_code,match_string,severity",
            "  test_case , test_step  ",
            "\"module_name\",\"module_step\"",
        )) {
            assertTrue(OpticsHeader.matches(header)) { "should match: $header" }
        }
    }

    @Test
    fun `leaves ordinary CSVs alone`() {
        for (header in listOf(
            "name,email,signed_up",
            "",
            "test_case",                    // both columns are required
            "module_name,element_id",       // pairs must not be mixed
            "test_case_id,test_step_name",  // substrings are not matches
        )) {
            assertFalse(OpticsHeader.matches(header)) { "should not match: $header" }
        }
    }
}
