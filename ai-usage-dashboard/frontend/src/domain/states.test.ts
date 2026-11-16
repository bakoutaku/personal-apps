import { describe, expect, it } from 'vitest';
import { fetchAllPages, type Fetched } from '../api/adapter';
import { MockAdapter, stateFixtures } from '../api/mockAdapter';
import type { Meta, QuotaWindow, Source } from '../api/types';
import { cardWindows, defaultWindow, overlappingCandidates, slotTitle } from './quota';
import { sourceName } from './sources';

const meta = { data_revision: 1 } as Meta;

describe('fetchAllPages', () => {
  it('达到页数上限仍有下一页时返回 incomplete，不当作完整数据', async () => {
    const r = await fetchAllPages<number>(
      async (cursor) => ({ ok: true, data: [Number(cursor ?? 0)], meta, page: { has_more: true, next_cursor: String(Number(cursor ?? 0) + 1) } }),
      3,
    );
    expect(r).toMatchObject({ ok: false, kind: 'incomplete', loadedRows: 3 });
  });

  it('has_more 但缺游标也是 incomplete', async () => {
    const r = await fetchAllPages<number>(async () => ({ ok: true, data: [1], meta, page: { has_more: true, next_cursor: null } }));
    expect(r).toMatchObject({ ok: false, kind: 'incomplete' });
  });

  it('读完时正常返回', async () => {
    const pages: Record<string, Fetched<number[]>> = {
      start: { ok: true, data: [1], meta, page: { has_more: true, next_cursor: 'b' } },
      b: { ok: true, data: [2], meta, page: { has_more: false, next_cursor: null } },
    };
    const r = await fetchAllPages<number>(async (c) => pages[c ?? 'start']!);
    expect(r.ok && r.data).toEqual([1, 2]);
  });
});

function win(over: Partial<QuotaWindow>): QuotaWindow {
  return {
    id: 'w',
    pool_id: 'p',
    slot: 'a',
    starts_at: '2026-10-22T00:00:00.000Z',
    ends_at: '2026-10-22T05:00:00.000Z',
    duration_seconds: 18000,
    start_source: 'derived',
    end_source: 'reported',
    semantics: 'unknown',
    status: 'current',
    freshness: 'fresh',
    latest_snapshot: null,
    previous_window_id: null,
    next_window_id: null,
    ...over,
  };
}

describe('窗口选择（B8 / B9 答复）', () => {
  it('每个池 + slot 一张卡，优先 current，按时长排序', () => {
    const ws = [
      win({ id: 'week', slot: 'x', duration_seconds: 604800, ends_at: '2026-10-27T00:00:00.000Z' }),
      win({ id: 'old5h', slot: 'y', status: 'expired', ends_at: '2026-10-21T20:00:00.000Z' }),
      win({ id: 'cur5h', slot: 'y' }),
    ];
    expect(cardWindows(ws).map((w) => w.id)).toEqual(['cur5h', 'week']);
  });

  it('某槽位没有当前窗口时显示其最近的窗口（作为已结束），默认历史窗口不拿它顶替', () => {
    const ws = [win({ id: 'old', status: 'expired' })];
    expect(cardWindows(ws).map((w) => w.id)).toEqual(['old']);
    expect(defaultWindow(ws)).toBeUndefined();
  });

  it('不假设 primary 是五小时；标题按时长，未知时说明', () => {
    const ws = [win({ id: 'p7', slot: 'primary', duration_seconds: 604800 }), win({ id: 's5', slot: 'secondary' })];
    expect(defaultWindow(ws)?.id).toBe('s5');
    expect(slotTitle({ duration_seconds: 18000 })).toBe('五小时窗口');
    expect(slotTitle({ duration_seconds: 604800 })).toBe('七天窗口');
    expect(slotTitle({ duration_seconds: null })).toBe('时长未知的窗口');
  });
});

describe('来源名称（B10 答复）', () => {
  it('产品未指定的来源不改写成额度接口', () => {
    const s = { product: null, kind: 'official_client' } as Source;
    expect(sourceName(s, 'GPT')).toBe('GPT · 官方客户端（产品未指定）');
  });
});

describe('states 样本', () => {
  it('每份样本都能按自己的场景通过匹配器读到', async () => {
    const entries = stateFixtures();
    expect(entries.length).toBeGreaterThanOrEqual(4);
    for (const e of entries) {
      const r = await new MockAdapter({ scenarioId: e.scenario_id }).getCatalogEntry(e);
      expect(r.ok, e.file).toBe(true);
    }
  });

  it('场景不对时不会读到别的场景的样本', async () => {
    const stale = stateFixtures().find((e) => e.scenario_id === 'stale-current-window')!;
    const r = await new MockAdapter({ scenarioId: 'gpt-observed' }).getCatalogEntry(stale);
    // gpt-observed 恰好有同一查询的正常样本：读到的必须是正常场景，而不是过时样本
    if (r.ok) expect(r.meta.scenario_id).toBe('gpt-observed');
  });
});

describe('重叠候选（真实抽样中的 1 秒差）', () => {
  const snap = (id: string, windowId: string, at: string) => ({
    id,
    pool_id: 'p',
    window_id: windowId,
    source_id: 's',
    observed_at: null,
    recorded_at: at,
    ingested_at: at,
    effective_at: at,
    time_basis: 'recorded_at' as const,
    used_percent: 10,
    value_basis: 'reported' as const,
  });
  // A：重置晚 1 秒，但记录更旧；B：重置早 1 秒，记录更新
  const a5 = win({ id: 'a5', slot: 'primary', starts_at: '2026-10-22T00:00:01.000Z', ends_at: '2026-10-22T05:00:01.000Z', latest_snapshot: snap('sa', 'a5', '2026-10-22T02:00:00.000Z') });
  const b5 = win({ id: 'b5', slot: 'primary', latest_snapshot: snap('sb', 'b5', '2026-10-22T03:30:00.000Z') });
  const a7 = win({ id: 'a7', slot: 'secondary', duration_seconds: 604800, ends_at: '2026-10-27T00:00:01.000Z', latest_snapshot: snap('sa7', 'a7', '2026-10-22T02:00:00.000Z') });
  const b7 = win({ id: 'b7', slot: 'secondary', duration_seconds: 604800, ends_at: '2026-10-27T00:00:00.000Z', latest_snapshot: snap('sb7', 'b7', '2026-10-22T03:30:00.000Z') });

  it('按最新快照记录选，不按更晚的重置时间；卡片与默认历史是同一个 window_id，与响应顺序无关', () => {
    for (const order of [[a5, b5, a7, b7], [b7, a7, b5, a5]]) {
      const cards = cardWindows(order);
      expect(cards.map((w) => w.id)).toEqual(['b5', 'b7']);
      expect(defaultWindow(order)?.id).toBe('b5');
      expect(cards).toContain(defaultWindow(order));
    }
  });

  it('保留重叠候选用于提示，不合并', () => {
    expect(overlappingCandidates([a5, b5, a7, b7], b5).map((w) => w.id)).toEqual(['a5']);
    expect(overlappingCandidates([a5, b5, a7, b7], b7).map((w) => w.id)).toEqual(['a7']);
  });

  it('非当前候选即使记录更新也不压过当前窗口', () => {
    const expiredNewer = win({ id: 'x', slot: 'primary', status: 'expired', latest_snapshot: snap('sx', 'x', '2026-10-22T04:00:00.000Z') });
    expect(cardWindows([expiredNewer, a5]).map((w) => w.id)).toEqual(['a5']);
  });
});
