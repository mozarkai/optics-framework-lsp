package ai.mozark.optics.lsp

import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/** A capture takes about a second, so a tick never starts while the last is running: queued ones show a stale screen. */
class FramePoller(private val intervalMs: () -> Long, private val tick: () -> Unit) {

    // One thread, so ticks cannot overlap.
    private val executor = Executors.newSingleThreadScheduledExecutor {
        Thread(it, "optics-device-view").apply { isDaemon = true }
    }
    private var pending: ScheduledFuture<*>? = null
    private var wanted = false

    // A tick running across stop() then start() must not reschedule a second loop.
    private var generation = 0

    @Synchronized
    fun start() {
        if (wanted) return
        wanted = true
        generation++
        schedule(generation, 0)
    }

    @Synchronized
    fun stop() {
        wanted = false
        pending?.cancel(false)
    }

    @Synchronized
    private fun schedule(forGeneration: Int, delayMs: Long) {
        pending = executor.schedule({ run(forGeneration) }, delayMs, TimeUnit.MILLISECONDS)
    }

    private fun run(forGeneration: Int) {
        val began = System.nanoTime()
        try {
            tick()
        } catch (_: Exception) {
            // The tick reports its own failures; the loop must outlive them.
        }
        synchronized(this) {
            if (wanted && forGeneration == generation) {
                val elapsed = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - began)
                schedule(forGeneration, maxOf(0, intervalMs() - elapsed))
            }
        }
    }
}
