import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RefreshScheduler, type LoadOutcome, type RefreshReason } from './refreshScheduler';
import { classifyLoad, type LoadResult } from './loadDashboard';

/** 可控的读取：每次调用返回一个由测试决定何时完成的 Promise。 */
function controllableRun() {
  const calls: { reason: RefreshReason; resolve: (o: LoadOutcome) => void }[] = [];
  let concurrent = 0;
  let maxConcurrent = 0;
  const run = vi.fn(
    (reason: RefreshReason) =>
      new Promise<LoadOutcome>((resolve) => {
        concurrent++;
        maxConcurrent = Math.max(maxConcurrent, concurrent);
        calls.push({
          reason,
          resolve: (o) => {
            concurrent--;
            resolve(o);
          },
        });
      }),
  );
  return { run, calls, maxConcurrent: () => maxConcurrent };
}

const flush = () => Promise.resolve().then(() => Promise.resolve());

describe('RefreshScheduler', () => {
  let visible = true;
  const deps = {
    setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms),
    clearTimeout: (h: unknown) => clearTimeout(h as ReturnType<typeof setTimeout>),
    isVisible: () => visible,
  };

  beforeEach(() => {
    vi.useFakeTimers();
    visible = true;
  });
  afterEach(() => vi.useRealTimers());

  it('live 可见：读取完成后每 30 秒读一次', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    c.calls[0]!.resolve('ok');
    await flush();
    expect(s.state().nextDelayMs).toBe(30_000);
    vi.advanceTimersByTime(29_999);
    expect(c.run).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(c.run).toHaveBeenCalledTimes(2);
    expect(c.calls[1]!.reason).toBe('timer');
  });

  it('隐藏时暂停；回到可见立即读取', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    c.calls[0]!.resolve('ok');
    await flush();
    visible = false;
    s.visibilityChanged();
    expect(s.state().nextDelayMs).toBeNull();
    vi.advanceTimersByTime(10 * 60_000);
    expect(c.run).toHaveBeenCalledTimes(1);
    visible = true;
    s.visibilityChanged();
    expect(c.run).toHaveBeenCalledTimes(2);
    expect(c.calls[1]!.reason).toBe('visible');
  });

  it('隐藏期间读取完成也不排下一次计划', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    visible = false;
    c.calls[0]!.resolve('ok');
    await flush();
    expect(s.state().nextDelayMs).toBeNull();
    vi.advanceTimersByTime(60_000);
    expect(c.run).toHaveBeenCalledTimes(1);
  });

  it('不重叠：进行中的多次请求合并成结束后的一次读取', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    s.request('manual');
    s.request('timer');
    s.request('visible');
    expect(c.run).toHaveBeenCalledTimes(1);
    c.calls[0]!.resolve('ok');
    await flush();
    expect(c.run).toHaveBeenCalledTimes(2);
    expect(c.maxConcurrent()).toBe(1);
  });

  it('范围变化优先：进行中有范围变化时，结束后按“scope”再读', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    s.request('scope');
    s.request('timer');
    c.calls[0]!.resolve('ok');
    await flush();
    expect(c.calls[1]!.reason).toBe('scope');
  });

  it('失败退避 60 / 120 / 240 / 300 / 300 秒，成功后回到 30 秒', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    const delays: (number | null)[] = [];
    for (let i = 0; i < 5; i++) {
      c.calls[i]!.resolve('failed');
      await flush();
      delays.push(s.state().nextDelayMs);
      vi.advanceTimersByTime(s.state().nextDelayMs!);
    }
    expect(delays).toEqual([60_000, 120_000, 240_000, 300_000, 300_000]);
    expect(c.calls[1]!.reason).toBe('retry');
    c.calls[5]!.resolve('ok');
    await flush();
    expect(s.state()).toMatchObject({ failures: 0, nextDelayMs: 30_000 });
  });

  it('401：停止，不再定时，也不响应后续请求', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    c.calls[0]!.resolve('unauthorized');
    await flush();
    expect(s.state().stopped).toBe(true);
    vi.advanceTimersByTime(10 * 60_000);
    s.request('manual');
    s.visibilityChanged();
    expect(c.run).toHaveBeenCalledTimes(1);
  });

  it('mock（polling=false）：不定时，回到页面也不读；手动 / 范围变化照常读', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: false });
    s.request('initial');
    c.calls[0]!.resolve('ok');
    await flush();
    expect(s.state().nextDelayMs).toBeNull();
    vi.advanceTimersByTime(10 * 60_000);
    s.visibilityChanged();
    expect(c.run).toHaveBeenCalledTimes(1);
    s.request('manual');
    expect(c.run).toHaveBeenCalledTimes(2);
  });

  it('stop() 清掉计划：卸载后不会留下重复轮询', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    c.calls[0]!.resolve('ok');
    await flush();
    expect(vi.getTimerCount()).toBe(1);
    s.stop();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * 60_000);
    expect(c.run).toHaveBeenCalledTimes(1);
  });

  it('读取进行中 stop()：结束后不再排计划', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    s.request('manual');
    s.stop();
    c.calls[0]!.resolve('ok');
    await flush();
    expect(c.run).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('手动刷新会取消原计划并重新计时', async () => {
    const c = controllableRun();
    const s = new RefreshScheduler(c.run, deps, { polling: true });
    s.request('initial');
    c.calls[0]!.resolve('ok');
    await flush();
    vi.advanceTimersByTime(20_000);
    s.request('manual');
    c.calls[1]!.resolve('ok');
    await flush();
    vi.advanceTimersByTime(20_000);
    expect(c.run).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(10_000);
    expect(c.run).toHaveBeenCalledTimes(3);
  });
});

describe('classifyLoad', () => {
  const req = { method: 'GET' as const, path: '/x', query: {} };
  const meta = {} as never;
  const okData = (over: Record<string, unknown> = {}) =>
    ({
      ok: true,
      data: {
        sources: { ok: true, data: [], meta },
        pools: { ok: true, data: [], meta },
        windows: null,
        history: null,
        ...over,
      },
    }) as unknown as LoadResult;

  it('全部成功 → ok；样本未提供 / 没有导入 也是有意义的结果 → ok', () => {
    expect(classifyLoad(okData())).toBe('ok');
    expect(classifyLoad(okData({ sources: { ok: false, kind: 'fixture_missing', request: req } }))).toBe('ok');
    expect(classifyLoad({ ok: false, reason: 'no_accounts', meta } as LoadResult)).toBe('ok');
  });

  it('不可达 / HTTP 错误 / 未读完 / 修订不一致 → failed（保留上次画面）', () => {
    expect(classifyLoad(okData({ sources: { ok: false, kind: 'unreachable', request: req } }))).toBe('failed');
    expect(classifyLoad(okData({ pools: { ok: false, kind: 'http_error', request: req, status: 500, code: 'x', message: '' } }))).toBe('failed');
    expect(classifyLoad({ ok: false, reason: 'base_unavailable', detail: { ok: false, kind: 'unreachable', request: req } } as LoadResult)).toBe('failed');
    expect(classifyLoad({ ok: false, reason: 'revision_mismatch', detail: '' } as LoadResult)).toBe('failed');
  });

  it('任何部分 401 → unauthorized', () => {
    expect(classifyLoad(okData({ sources: { ok: false, kind: 'unauthorized', request: req } }))).toBe('unauthorized');
    expect(classifyLoad({ ok: false, reason: 'base_unavailable', detail: { ok: false, kind: 'unauthorized', request: req } } as LoadResult)).toBe('unauthorized');
  });
});
