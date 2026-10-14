/** A capture takes about a second, so a tick never starts while the last is running: queued ones show a stale screen. */
export class Poller {
  private timer: NodeJS.Timeout | undefined;
  private busy = false;

  constructor(
    private readonly tick: () => Promise<void>,
    private readonly interval: () => number
  ) {}

  start(): void {
    if (!this.timer) {
      void this.run();
      this.timer = setInterval(() => void this.run(), this.interval());
    }
  }

  stop(): void {
    clearInterval(this.timer);
    this.timer = undefined;
  }

  private async run(): Promise<void> {
    if (this.busy) {
      return;
    }
    this.busy = true;
    try {
      await this.tick();
    } finally {
      this.busy = false;
    }
  }
}
