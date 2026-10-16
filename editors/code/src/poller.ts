/** A capture takes a while, so a tick never starts while the last is running, and the wait before the next is asked for each time. */
export class Poller {
  private timer: NodeJS.Timeout | undefined;
  private wanted = false;
  private running = false;

  constructor(
    private readonly tick: () => Promise<void>,
    private readonly interval: () => number
  ) {}

  start(): void {
    if (this.wanted) {
      return;
    }
    this.wanted = true;
    if (!this.running) {
      void this.loop();
    }
  }

  stop(): void {
    this.wanted = false;
    clearTimeout(this.timer);
  }

  private async loop(): Promise<void> {
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
