// 整屏读取的统一协调：首次加载、范围变化、手动刷新、定时刷新、回到页面都经过这里。
// - 同一时间只有一个读取在进行；进行中又有请求时合并为“结束后再读一次”，不并发、不让旧响应覆盖新结果。
// - live：页面可见时每 intervalMs 读一次；隐藏时暂停；回到可见立即读。mock：不定时。
// - 读取失败按 60 / 120 / 240 / 300 秒退避；成功后回到正常间隔。
// - 401：停止，交给重新配对流程（组件卸载时 stop()）。

export type LoadOutcome = 'ok' | 'failed' | 'unauthorized';
export type RefreshReason = 'initial' | 'scope' | 'manual' | 'timer' | 'visible' | 'retry' | 'reset';

export interface SchedulerDeps {
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
  isVisible: () => boolean;
}

export interface SchedulerOptions {
  /** 是否定时读取（live = true，mock = false） */
  polling: boolean;
  intervalMs?: number;
  maxBackoffMs?: number;
}

export interface SchedulerState {
  inFlight: boolean;
  /** 连续失败次数（成功清零） */
  failures: number;
  /** 下次定时读取的延迟；null = 当前没有计划（隐藏、mock、已停止或正在读取） */
  nextDelayMs: number | null;
  stopped: boolean;
}

export class RefreshScheduler {
  private inFlight = false;
  private queued: RefreshReason | null = null;
  private timer: unknown = null;
  private failures = 0;
  private nextDelay: number | null = null;
  private stopped = false;
  private readonly interval: number;
  private readonly maxBackoff: number;

  constructor(
    private readonly run: (reason: RefreshReason) => Promise<LoadOutcome>,
    private readonly deps: SchedulerDeps,
    private readonly opts: SchedulerOptions,
    private readonly onChange: (s: SchedulerState) => void = () => {},
  ) {
    this.interval = opts.intervalMs ?? 30_000;
    this.maxBackoff = opts.maxBackoffMs ?? 300_000;
  }

  state(): SchedulerState {
    return { inFlight: this.inFlight, failures: this.failures, nextDelayMs: this.nextDelay, stopped: this.stopped };
  }

  /** 请求读取一次。正在读取时只记下“结束后再读”，多个请求合并成一个。 */
  request(reason: RefreshReason): void {
    if (this.stopped) return;
    this.clearTimer();
    if (this.inFlight) {
      // 范围变化优先于普通刷新（结束后按最新范围再读）
      if (this.queued !== 'scope') this.queued = reason;
      this.emit();
      return;
    }
    void this.exec(reason);
  }

  /** 页面可见性变化：隐藏时暂停计划；回到可见立即读取。 */
  visibilityChanged(): void {
    if (this.stopped || !this.opts.polling) return;
    if (this.deps.isVisible()) this.request('visible');
    else {
      this.clearTimer();
      this.emit();
    }
  }

  stop(): void {
    this.stopped = true;
    this.queued = null;
    this.clearTimer();
    this.emit();
  }

  /** 下一次延迟：正常间隔；连续失败时 2^n 倍退避，封顶 maxBackoff。 */
  delayFor(failures: number): number {
    return failures === 0 ? this.interval : Math.min(this.interval * 2 ** failures, this.maxBackoff);
  }

  private async exec(reason: RefreshReason): Promise<void> {
    this.inFlight = true;
    this.emit();
    let outcome: LoadOutcome;
    try {
      outcome = await this.run(reason);
    } catch {
      outcome = 'failed';
    }
    this.inFlight = false;
    if (this.stopped) return;
    if (outcome === 'unauthorized') {
      this.stop();
      return;
    }
    this.failures = outcome === 'ok' ? 0 : this.failures + 1;
    const next = this.queued;
    if (next) {
      this.queued = null;
      void this.exec(next);
      return;
    }
    this.schedule();
  }

  private schedule(): void {
    this.clearTimer();
    if (!this.opts.polling || this.stopped || !this.deps.isVisible()) {
      this.emit();
      return;
    }
    const delay = this.delayFor(this.failures);
    this.nextDelay = delay;
    this.timer = this.deps.setTimeout(() => {
      this.timer = null;
      this.request(this.failures > 0 ? 'retry' : 'timer');
    }, delay);
    this.emit();
  }

  private clearTimer(): void {
    if (this.timer !== null) this.deps.clearTimeout(this.timer);
    this.timer = null;
    this.nextDelay = null;
  }

  private emit(): void {
    this.onChange(this.state());
  }
}
