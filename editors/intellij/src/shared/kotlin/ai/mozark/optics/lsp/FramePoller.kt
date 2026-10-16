package ai.mozark.optics.lsp

import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/**
 * A capture takes a while, so the next one starts [delayMs] after the last ends, asked for each time:
 * queued ones show a stale screen, and a slow device should be asked less often.
 */
class FramePoller(private val delayMs: () -> Long, private val tick: () -> Unit) {

    private val executor = Executors.newSingleThreadScheduledExecutor {
        Thread(it, "optics-device-view").apply { isDaemon = true }
    }
    private var next: ScheduledFuture<*>? = null
    private var wanted = false
    private var running = false

    @Synchronized
    fun start() {
        if (wanted) return
        wanted = true
        if (!running) next = executor.schedule(::run, 0, TimeUnit.MILLISECONDS)
    }

    @Synchronized
    fun stop() {
        wanted = false
        next?.cancel(false)
    }

    private fun run() {
        synchronized(this) { running = true }
        try {
            tick()
        } catch (_: Exception) {
            // The tick reports its own failures, and the loop must outlive them.
        }
        synchronized(this) {
            running = false
            if (wanted) next = executor.schedule(::run, delayMs(), TimeUnit.MILLISECONDS)
        }
    }
}
