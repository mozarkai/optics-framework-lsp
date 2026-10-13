/** A capture takes about a second, so a tick never starts while the last is running: queued ones show a stale screen. */
export class Poller {
  private timer: NodeJS.Timeout | undefined;
  private running = false;
  private wanted = false;

  constructor(
    private readonly tick: () => Promise<void>,
    private readonly interval: () => number
  ) {}

  start(): void {
    if (this.wanted) {
      return;
    }
    this.wanted = true;
    void this.loop();
  }

  stop(): void {
    this.wanted = false;
    clearTimeout(this.timer);
    this.timer = undefined;
  }

  private async loop(): Promise<void> {
    if (!this.wanted || this.running) {
      return;
    }
    this.running = true;
    const began = Date.now();
    try {
      await this.tick();
    } finally {
      this.running = false;
    }
    if (this.wanted) {
      this.timer = setTimeout(() => void this.loop(), Math.max(0, this.interval() - (Date.now() - began)));
    }
  }
}
