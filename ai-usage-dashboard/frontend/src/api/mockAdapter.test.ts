import catalog from '@mocks/catalog.json';
import { describe, expect, it } from 'vitest';
import { findFixture, MockAdapter } from './mockAdapter';
import { normalizeQuery, queryKey } from './normalizeQuery';

const scope = { provider: 'gpt', account_id: 'acct_demo_gpt' } as const;
const win = { from: '2026-10-22T00:58:00.000Z', to: '2026-10-22T05:58:00.000Z' };

describe('normalizeQuery', () => {
  it('补默认 timezone / limit，规范化时间、产品顺序和数字', () => {
    expect(
      normalizeQuery('/api/v1/usage-events', { ...scope, from: '2026-10-22T09:58:00+09:00', to: win.to, products: 'codex,chat', limit: '100' }),
    ).toEqual({ ...scope, from: win.from, to: win.to, products: 'chat,codex', limit: '100', timezone: 'Asia/Tokyo' });
  });

  it('键顺序不影响匹配键；有语义的字段不丢', () => {
    const a = queryKey('/quota-snapshots', { ...scope, pool_id: 'p', ...win, window_id: 'w' });
    const b = queryKey('/quota-snapshots', { window_id: 'w', to: win.to, from: win.from, pool_id: 'p', ...scope });
    const c = queryKey('/quota-snapshots', { ...scope, pool_id: 'p', ...win });
    expect(a).toBe(b);
    expect(a).not.toBe(c);
  });

  it('health / accounts 不加 timezone', () => {
    expect(normalizeQuery('/health', {})).toEqual({});
  });
});

describe('findFixture', () => {
  it('按场景 + 规范化查询选中整窗样本', () => {
    const f = findFixture('gpt-observed', 'GET', '/usage-series', { ...scope, ...win, products: 'codex', bucket: '15m' });
    expect(f?.file).toBe('gpt-observed/usage-series-window.json');
  });

  it('带 window_id 的快照查询选 snapshots-window，不带的选 full', () => {
    const base = { ...scope, pool_id: 'pool_demo_gpt', ...win };
    expect(findFixture('gpt-observed', 'GET', '/quota-snapshots', { ...base, window_id: 'win_demo_5h' })?.file).toBe(
      'gpt-observed/quota-snapshots-window.json',
    );
    expect(findFixture('gpt-observed', 'GET', '/quota-snapshots', base)?.file).toBe('gpt-observed/quota-snapshots-full.json');
  });

  it('health/accounts 可复用 catalog 共享元数据；其他场景不隐式回退', () => {
    expect(findFixture('gpt-observed', 'GET', '/health', {})?.file).toBe('health.json');
    expect(findFixture('no-such-scenario', 'GET', '/sources', scope)).toBeUndefined();
  });

  it('“全部产品”（不带 products）命中独立的整窗样本，不借用 Codex 筛选的样本', () => {
    expect(findFixture('gpt-observed', 'GET', '/usage-series', { ...scope, ...win, bucket: '15m' })?.file).toBe(
      'gpt-observed/usage-series-window-all.json',
    );
  });

  it('未提供的产品筛选、日期返回 undefined（不回退到默认）', () => {
    expect(findFixture('gpt-observed', 'GET', '/usage-series', { ...scope, ...win, products: 'chat', bucket: '15m' })).toBeUndefined();
    expect(
      findFixture('gpt-observed', 'GET', '/usage-series', { ...scope, from: '2026-10-21T00:58:00Z', to: '2026-10-21T05:58:00Z', products: 'codex', bucket: '15m' }),
    ).toBeUndefined();
  });
});

describe('MockAdapter', () => {
  const adapter = new MockAdapter({ scenarioId: 'gpt-observed' });

  it('读取整窗 usage-series，meta 为 mock 且修订一致', async () => {
    const r = await adapter.getUsageSeries({ ...scope, ...win, products: ['codex'], bucket: '15m', timezone: 'Asia/Tokyo' });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.meta.data_mode).toBe('mock');
    expect(r.meta.data_revision).toBe(catalog.data_revision);
    expect(r.data.buckets).toHaveLength(21);
  });

  it('选中 Chat 时返回 fixture_missing，不残留 Codex 数据', async () => {
    const r = await adapter.getUsageSeries({ ...scope, ...win, products: ['chat'], bucket: '15m' });
    expect(r).toMatchObject({ ok: false, kind: 'fixture_missing' });
  });

  it('提供启动上下文与 getHealth / getAccounts', async () => {
    expect(adapter.getBootstrapContext()).toMatchObject({ pool_id: 'pool_demo_gpt', window_id: 'win_demo_5h', ...win });
    const [h, a] = await Promise.all([adapter.getHealth(), adapter.getAccounts()]);
    expect(h.ok && a.ok).toBe(true);
  });
});
