import ai.mozark.optics.lsp.FramePoller
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.concurrent.atomic.AtomicInteger

class FramePollerTest {

    @Test
    fun `a tick never starts while the last one is running`() {
        val running = AtomicInteger()
        val ticks = AtomicInteger()
        var overlapped = false
        val poller = FramePoller({ 10 }) {
            if (running.incrementAndGet() > 1) overlapped = true
            ticks.incrementAndGet()
            Thread.sleep(60)
            running.decrementAndGet()
        }
        poller.start()
        Thread.sleep(400)
        poller.stop()
        val seen = ticks.get()
        Thread.sleep(150)

        assertTrue(seen >= 3) { "ticks: $seen" }
        assertFalse(overlapped)
        assertEquals(seen, ticks.get(), "stop must stop it")
    }

    @Test
    fun `stopping and starting while a tick runs does not leave two loops`() {
        val running = AtomicInteger()
        var overlapped = false
        val poller = FramePoller({ 10 }) {
            if (running.incrementAndGet() > 1) overlapped = true
            Thread.sleep(50)
            running.decrementAndGet()
        }
        poller.start()
        Thread.sleep(20)
        poller.stop()
        poller.start()
        Thread.sleep(300)
        poller.stop()
        assertFalse(overlapped)
    }

    @Test
    fun `a failing tick does not end the loop`() {
        val ticks = AtomicInteger()
        val poller = FramePoller({ 10 }) {
            ticks.incrementAndGet()
            error("device gone")
        }
        poller.start()
        Thread.sleep(200)
        poller.stop()
        assertTrue(ticks.get() >= 3)
    }
}
