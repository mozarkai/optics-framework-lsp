import ai.mozark.optics.lsp.FramePoller
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.atomic.AtomicInteger

class FramePollerTest {

    @Test
    fun `ticks never overlap, survive a failing one, and stop when told to`() {
        val running = AtomicInteger()
        val ticks = AtomicInteger()
        var overlapped = false
        val poller = FramePoller(10) {
            val number = ticks.incrementAndGet()
            if (running.incrementAndGet() > 1) overlapped = true
            Thread.sleep(60)
            running.decrementAndGet()
            if (number == 1) error("device gone")
        }
        poller.start()
        poller.start()
        Thread.sleep(400)
        poller.stop()
        val seen = ticks.get()
        Thread.sleep(150)

        assertTrue(seen >= 3) { "ticks: $seen" }
        assertFalse(overlapped)
        assertEquals(seen, ticks.get(), "stop must stop it")
    }
}
