import { describe, expect, it } from 'vitest';
import { MockAdapter } from '../api/mockAdapter';
import type { Route } from '../route/hash';
import { loadDashboard } from './loadDashboard';

const adapter = new MockAdapter({ scenarioId: 'gpt-observed' });
const base: Route = { provider: 'gpt', page: 'home', products: ['codex'], view: 'window', pool: null, window: null, date: null, range: null };

describe('loadDashboard（gpt-observed）', () => {
  it('默认路由：一个池两张槽位卡，整窗历史全部命中样本', async () => {
    const r = await loadDashboard(adapter, base);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    const d = r.data;
    expect(d.windows?.ok && d.windows.data.map((w) => w.slot)).toEqual(['primary', 'secondary']);
    expect(d.resolved).toEqual({ pool: 'pool_demo_gpt', window: 'win_demo_5h' });
    const h = d.history!;
    for (const part of [h.snapshots, h.series, h.events, h.sessions, h.labels]) expect(part?.ok).toBe(true);
    expect(d.notices).toEqual([]);
  });

  it('选 Chat：额度卡不变，用量部分为 fixture_missing', async () => {
    const r = await loadDashboard(adapter, { ...base, products: ['chat'] });
    if (!r.ok) throw new Error('load failed');
    expect(r.data.windows?.ok).toBe(true);
    expect(r.data.history?.snapshots?.ok).toBe(true);
    expect(r.data.history?.series).toMatchObject({ ok: false, kind: 'fixture_missing' });
    expect(r.data.history?.events).toMatchObject({ ok: false, kind: 'fixture_missing' });
  });

  it('失效的 pool / window 回到默认并给出提示', async () => {
    const r = await loadDashboard(adapter, { ...base, pool: 'nope', window: 'nope' });
    if (!r.ok) throw new Error('load failed');
    expect(r.data.resolved).toEqual({ pool: 'pool_demo_gpt', window: 'win_demo_5h' });
    expect(r.data.notices).toHaveLength(2);
  });

  it('活动场景里打开日视图：按自然日请求，样本未提供就如实 fixture_missing，不回退到五小时数据', async () => {
    const r = await loadDashboard(adapter, { ...base, view: 'day' });
    if (!r.ok) throw new Error('load failed');
    expect(r.data.history?.kind).toBe('calendar');
    expect(r.data.history?.from).toBe('2026-10-21T15:00:00.000Z');
    expect(r.data.history?.series).toMatchObject({ ok: false, kind: 'fixture_missing' });
  });
});

describe('recent5h 与 Claude（无额度池）', () => {
  const both = new MockAdapter({ scenarioId: 'gpt-observed', scenarioByProvider: { gpt: 'gpt-observed', claude: 'claude-tokens' } });

  it('GPT recent5h：范围为 [as_of−5h, as_of)，不请求额度快照；样本未提供时如实 fixture_missing', async () => {
    const r = await loadDashboard(both, { ...base, view: 'recent5h' });
    if (!r.ok) throw new Error('load failed');
    const h = r.data.history!;
    expect(h.kind).toBe('recent5h');
    expect(h.window).toBeNull();
    expect(h.snapshots).toBeNull();
    expect(h.to).toBe(r.data.meta.as_of);
    expect(Date.parse(h.to) - Date.parse(h.from)).toBe(5 * 3600_000);
    expect(r.data.windows?.ok).toBe(true); // 额度卡照常
  });

  it('Claude：按 provider 选 claude-tokens 场景；没有额度池，不查窗口、不造窗口', async () => {
    const r = await loadDashboard(both, { provider: 'claude', products: ['code'], view: 'recent5h', pool: null, window: null, date: null, range: null });
    if (!r.ok) throw new Error('load failed');
    expect(r.data.account.provider).toBe('claude');
    expect(r.data.sources.ok && r.data.sources.meta.scenario_id).toBe('claude-tokens');
    expect(r.data.pools.ok && r.data.pools.data).toEqual([]);
    expect(r.data.pool).toBeNull();
    expect(r.data.windows).toBeNull();
    expect(r.data.selectedWindow).toBeNull();
    expect(r.data.history?.kind).toBe('recent5h');
  });

  it('Claude 链接里写 view=window：不加载历史，也不生成窗口', async () => {
    const r = await loadDashboard(both, { provider: 'claude', products: null, view: 'window', pool: null, window: null, date: null, range: null });
    if (!r.ok) throw new Error('load failed');
    expect(r.data.history).toBeNull();
    expect(r.data.windows).toBeNull();
  });
});

describe('recent5h 模拟样本（data_revision 4）', () => {
  const both = new MockAdapter({ scenarioId: 'gpt-observed', scenarioByProvider: { gpt: 'gpt-observed', claude: 'claude-tokens' } });

  it('claude-tokens 启动上下文的 pool_id / window_id 保持 null，不变成字符串', () => {
    const b = both.getBootstrapContext('claude');
    expect(b?.pool_id).toBeNull();
    expect(b?.window_id).toBeNull();
  });

  it('两家 recent5h 都命中样本：20 个桶，已知小计 3000，另有 1 条未知', async () => {
    for (const route of [
      { ...base, view: 'recent5h' as const },
      { provider: 'claude' as const, products: ['code' as const], view: 'recent5h' as const, pool: null, window: null, date: null, range: null },
      { provider: 'claude' as const, products: null, view: 'recent5h' as const, pool: null, window: null, date: null, range: null },
    ]) {
      const r = await loadDashboard(both, route);
      if (!r.ok) throw new Error('load failed');
      const h = r.data.history!;
      expect(h.from).toBe('2026-10-21T23:01:00.000Z');
      for (const part of [h.series, h.events, h.sessions, h.labels]) expect(part.ok).toBe(true);
      if (!h.series.ok) continue;
      expect(h.series.data.buckets).toHaveLength(20);
      const known = h.series.data.buckets.reduce((s, b) => s + (b.total_tokens ?? 0), 0);
      const unknown = h.series.data.buckets.reduce((s, b) => s + b.unknown_total_count, 0);
      expect([known, unknown]).toEqual([3000, 1]);
    }
  });

  it('未接入产品（Cowork）：桶全部 null，不显示成 0，也没有事件', async () => {
    const r = await loadDashboard(both, { provider: 'claude', products: ['cowork'], view: 'recent5h', pool: null, window: null, date: null, range: null });
    if (!r.ok) throw new Error('load failed');
    const h = r.data.history!;
    expect(h.series.ok && h.series.data.buckets.every((b) => b.total_tokens === null)).toBe(true);
    expect(h.events.ok && h.events.data).toEqual([]);
  });
});

describe('日 / 周 / 月（gpt-history / claude-history，data_revision 5）', () => {
  const hist = new MockAdapter({ scenarioId: 'gpt-history', scenarioByProvider: { gpt: 'gpt-history', claude: 'claude-history' } });
  // GPT 交接文档的核对表：事件数、已知、未知、已知小计、会话数；切桶后的段数
  const table = {
    day: { events: 4, known: 3, unknown: 1, sum: 3000, sessions: 2, segments: 25 },
    week: { events: 7, known: 6, unknown: 1, sum: 7000, sessions: 3, segments: 8 },
    month: { events: 9, known: 8, unknown: 1, sum: 9000, sessions: 4, segments: 32 },
  } as const;

  for (const provider of ['gpt', 'claude'] as const) {
    for (const view of ['day', 'week', 'month'] as const) {
      it(`${provider} ${view}：与核对表一致，未来切桶，不把未知算成 0`, async () => {
        const products = provider === 'gpt' ? (['codex'] as const) : (['code'] as const);
        const r = await loadDashboard(hist, { provider, products: [...products], view, pool: null, window: null, date: null, range: null });
        if (!r.ok) throw new Error('load failed');
        const h = r.data.history!;
        expect(h.kind).toBe('calendar');
        for (const part of [h.series, h.events, h.sessions, h.labels]) expect(part.ok).toBe(true);
        if (!h.series.ok || !h.events.ok || !h.sessions.ok) return;
        const t = table[view];
        const b = h.series.data.buckets;
        expect(b).toHaveLength(t.segments);
        expect(b.reduce((s, x) => s + x.event_count, 0)).toBe(t.events);
        expect(b.reduce((s, x) => s + x.known_total_count, 0)).toBe(t.known);
        expect(b.reduce((s, x) => s + x.unknown_total_count, 0)).toBe(t.unknown);
        expect(b.reduce((s, x) => s + (x.total_tokens ?? 0), 0)).toBe(t.sum);
        expect(h.events.data).toHaveLength(t.events);
        expect(h.sessions.data).toHaveLength(t.sessions);
        expect(b.filter((x) => x.record_state === 'future').every((x) => x.total_tokens === null)).toBe(true);
        if (provider === 'claude') {
          expect(r.data.pool).toBeNull();
          expect(h.quota).toBeNull();
        }
      });
    }
  }

  it('GPT 额度历史：按窗口的最高观测值（日/周 3 个、月 5 个），五小时与七天分开', async () => {
    for (const [view, n] of [['day', 3], ['week', 3], ['month', 5]] as const) {
      const r = await loadDashboard(hist, { ...base, view, date: null, range: null });
      if (!r.ok) throw new Error('load failed');
      const q = r.data.history!.quota!;
      expect(q.summaries.ok && q.summaries.data.length).toBe(n);
      expect(q.windows.ok).toBe(true);
      expect(q.snapshots === null).toBe(view !== 'day');
    }
  });

  it('选区 12:00–13:00：明细只用选区数据（3 条事件，已知 2000，1 个会话）', async () => {
    const range = { from: '2026-10-22T03:00:00.000Z', to: '2026-10-22T04:00:00.000Z' };
    const r = await loadDashboard(hist, { ...base, view: 'day', date: null, range });
    if (!r.ok) throw new Error('load failed');
    const sel = r.data.history!.selection!;
    expect(sel.from).toBe(range.from);
    expect(sel.events.ok && sel.events.data.length).toBe(3);
    expect(sel.sessions.ok && sel.sessions.data.length).toBe(1);
    expect(sel.series.ok && sel.series.data.buckets.reduce((s, x) => s + (x.total_tokens ?? 0), 0)).toBe(2000);
  });

  it('选区不在当前范围内时忽略并提示', async () => {
    const r = await loadDashboard(hist, { ...base, view: 'day', date: null, range: { from: '2026-10-20T03:00:00.000Z', to: '2026-10-20T04:00:00.000Z' } });
    if (!r.ok) throw new Error('load failed');
    expect(r.data.history!.selection).toBeNull();
    expect(r.data.notices.join()).toContain('选中的时间段不在当前范围内');
  });
});
