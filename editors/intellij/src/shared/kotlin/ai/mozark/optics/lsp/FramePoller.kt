package ai.mozark.optics.lsp

import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/**
 * A capture takes about a second, so the next one starts [delayMs] after the last ends: queued ones
 * show a stale screen, and a fixed rate would burst to catch up after a stall.
 */
class FramePoller(private val delayMs: Long, private val tick: () -> Unit) {

    private val executor = Executors.newSingleThreadScheduledExecutor {
        Thread(it, "optics-device-view").apply { isDaemon = true }
    }
    private var running: ScheduledFuture<*>? = null

    @Synchronized
    fun start() {
        // The tick reports its own failures, and an exception would end the schedule.
        running = running ?: executor.scheduleWithFixedDelay(
            { try { tick() } catch (_: Exception) {} }, 0, delayMs, TimeUnit.MILLISECONDS,
        )
    }

    @Synchronized
    fun stop() {
        running?.cancel(false)
        running = null
    }
}
