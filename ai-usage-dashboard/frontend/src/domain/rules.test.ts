import { describe, expect, it } from 'vitest';
import type { QuotaWindow, UsageBucket } from '../api/types';
import { parseHash, formatHash } from '../route/hash';
import { calendarRange, fmtRangeLabel, localMonthRange, localWeekRange, shiftDateKey } from '../time/tz';
import { boundarySourceText, cardState } from './quota';
import { canStack, classifyBucket, plottableTotal } from './usage';

const nullComponents = { uncached_input_tokens: null, cache_read_input_tokens: null, cache_write_input_tokens: null, output_tokens: null };

function bucket(over: Partial<UsageBucket>): UsageBucket {
  return {
    from: '2026-10-22T03:00:00.000Z',
    to: '2026-10-22T03:15:00.000Z',
    is_partial_bucket: false,
    record_state: 'observed',
    coverage_status: 'partial',
    coverage_reasons: [],
    source_ids: [],
    event_count: 1,
    known_total_count: 1,
    unknown_total_count: 0,
    total_tokens: 1000,
    total_status: 'known',
    components: nullComponents,
    components_complete: false,
    ...over,
  };
}

describe('token 桶：缺失 / 未知不是 0', () => {
  it('no_records 按覆盖状态分开画，且没有可画数值', () => {
    const nr = { record_state: 'no_records', total_tokens: null, total_status: 'unknown', event_count: 0 } as const;
    expect(classifyBucket(bucket({ ...nr, coverage_status: 'unknown' }))).toBe('no_records_unknown');
    expect(classifyBucket(bucket({ ...nr, coverage_status: 'gap' }))).toBe('no_records_gap');
    expect(classifyBucket(bucket({ ...nr, coverage_status: 'complete' }))).toBe('no_records_covered');
    expect(plottableTotal(bucket({ ...nr }))).toBeNull();
  });

  it('有事件但用量未知 → unknown_total，不画 0', () => {
    const b = bucket({ total_tokens: null, total_status: 'unknown', known_total_count: 0, unknown_total_count: 1 });
    expect(classifyBucket(b)).toBe('unknown_total');
    expect(plottableTotal(b)).toBeNull();
  });

  it('partial 是已知小计；future 不画', () => {
    expect(classifyBucket(bucket({ total_status: 'partial', total_tokens: 500 }))).toBe('partial_total');
    expect(classifyBucket(bucket({ record_state: 'future', total_tokens: null }))).toBe('future');
  });

  it('只有 components_complete=true 才堆叠', () => {
    const full = { uncached_input_tokens: 100, cache_read_input_tokens: 600, cache_write_input_tokens: 100, output_tokens: 200 };
    expect(canStack(bucket({ components: full, components_complete: true }))).toBe(true);
    expect(canStack(bucket({ components: full, components_complete: false }))).toBe(false);
    expect(canStack(bucket({ components: full, components_complete: true, total_status: 'partial' }))).toBe(false);
  });
});

const baseWindow: QuotaWindow = {
  id: 'w',
  pool_id: 'p',
  slot: 'primary',
  starts_at: '2026-10-22T00:58:00.000Z',
  ends_at: '2026-10-22T05:58:00.000Z',
  duration_seconds: 18000,
  start_source: 'derived',
  end_source: 'reported',
  semantics: 'unknown',
  status: 'current',
  freshness: 'fresh',
  latest_snapshot: {
    id: 's',
    pool_id: 'p',
    window_id: 'w',
    source_id: 'src',
    observed_at: null,
    recorded_at: '2026-10-22T03:59:00.000Z',
    ingested_at: '2026-10-22T04:01:00.000Z',
    effective_at: '2026-10-22T03:59:00.000Z',
    time_basis: 'recorded_at',
    used_percent: 62,
    value_basis: 'reported',
  },
  previous_window_id: null,
  next_window_id: null,
};

describe('额度卡', () => {
  it('observed_at=null 时标“日志记录于”', () => {
    expect(cardState(baseWindow).timeLabel).toBe('日志记录于');
  });
  it('expired 优先于 stale；百分比不封顶', () => {
    const s = cardState({ ...baseWindow, status: 'expired', freshness: 'stale' });
    expect(s.status).toBe('expired');
    expect(s.stale).toBe(false);
    const over = cardState({ ...baseWindow, latest_snapshot: { ...baseWindow.latest_snapshot!, used_percent: 104 } });
    expect(over.percent).toBe(104);
    expect(over.overHundred).toBe(true);
  });
  it('used_percent=null 不显示成 0', () => {
    expect(cardState({ ...baseWindow, latest_snapshot: { ...baseWindow.latest_snapshot!, used_percent: null } }).percent).toBeNull();
  });
  it('推导开始边界说明来源', () => {
    expect(boundarySourceText('start', baseWindow)).toBe('推导：结束 − 300 分');
    expect(boundarySourceText('end', baseWindow)).toBe('来源报告');
  });
});

describe('自然周 / 自然月（按 meta.timezone）', () => {
  const asOf = Date.parse('2026-10-22T04:01:00.000Z');
  it('周从周一开始：10/19（一）– 10/26 00:00 JST', () => {
    const w = localWeekRange(asOf, 'Asia/Tokyo');
    expect(new Date(w.from).toISOString()).toBe('2026-10-18T15:00:00.000Z');
    expect(new Date(w.to).toISOString()).toBe('2026-10-25T15:00:00.000Z');
  });
  it('周日也归入本周（不是下周起点）', () => {
    const sunday = Date.parse('2026-10-25T14:00:00.000Z'); // 10/25 23:00 JST
    expect(new Date(localWeekRange(sunday, 'Asia/Tokyo').from).toISOString()).toBe('2026-10-18T15:00:00.000Z');
  });
  it('月按自然月：10/01 – 11/01 JST', () => {
    const m = localMonthRange(asOf, 'Asia/Tokyo');
    expect(new Date(m.from).toISOString()).toBe('2026-09-30T15:00:00.000Z');
    expect(new Date(m.to).toISOString()).toBe('2026-10-31T15:00:00.000Z');
  });
  it('跨夏令时的月份不假设每天 24 小时', () => {
    const m = localMonthRange(Date.parse('2026-11-15T12:00:00Z'), 'America/New_York');
    expect(new Date(m.from).toISOString()).toBe('2026-11-01T04:00:00.000Z');
    expect(new Date(m.to).toISOString()).toBe('2026-12-01T05:00:00.000Z');
  });
});

describe('hash 路由', () => {
  const defaults = { provider: 'gpt', view: 'window' } as const;
  it('往返解析', () => {
    const h = '#/gpt?products=codex&view=window&pool=pool_demo_gpt&window=win_demo_5h';
    const { route, dropped } = parseHash(h, defaults);
    expect(dropped).toEqual([]);
    expect(formatHash(route)).toBe(h);
  });
  it('非法参数忽略并回到默认，不抛错', () => {
    const { route, dropped } = parseHash('#/gpt?view=year&products=code,codex&at=123', defaults);
    expect(route.view).toBe('window');
    expect(route.products).toEqual(['codex']);
    expect(dropped).toEqual(expect.arrayContaining(['view', 'products', 'at']));
  });
  it('二级页面段：往返；首页没有页面段；未知页面回首页并提示', () => {
    for (const h of ['#/claude/details?view=day&date=2026-10-22&range=2026-10-22T01:00:00.000Z,2026-10-22T02:00:00.000Z', '#/gpt/quota?view=window', '#/gpt/sources?view=day', '#/gpt/about?view=day']) {
      const { route, dropped } = parseHash(h, defaults);
      expect(dropped).toEqual([]);
      expect(formatHash(route)).toBe(h);
    }
    expect(parseHash('#/gpt?view=day', defaults).route.page).toBe('home');
    expect(parseHash('#/gpt/home?view=day', defaults).route.page).toBe('home');
    const bad = parseHash('#/gpt/admin?view=day', defaults);
    expect(bad.route.page).toBe('home');
    expect(bad.dropped).toEqual(['page']);
    // 不回显原值
    expect(parseHash('#launch_pairing=secret_value_xxxxxxxxxxxxxxxx', defaults).dropped.join()).not.toContain('secret');
  });
});

describe('活动摘要（最近五小时）', () => {
  it('只合计已知数值；有未知时标为已知小计；没有已知数值时为 null 而不是 0', async () => {
    const { summarizeActivity } = await import('./usage');
    const s = summarizeActivity(
      [
        bucket({ total_tokens: 1000, event_count: 1, known_total_count: 1 }),
        bucket({ total_tokens: null, total_status: 'unknown', event_count: 1, known_total_count: 0, unknown_total_count: 1 }),
        bucket({ record_state: 'no_records', total_tokens: null, total_status: 'unknown', event_count: 0, known_total_count: 0 }),
      ],
      ['2026-10-22T03:05:00.000Z', '2026-10-22T03:50:00.000Z'],
    );
    expect(s).toEqual({ knownTotal: 1000, unknownEvents: 1, eventCount: 2, latestRecordAt: '2026-10-22T03:50:00.000Z' });
    const none = summarizeActivity([bucket({ record_state: 'no_records', total_tokens: null, total_status: 'unknown', event_count: 0, known_total_count: 0 })], []);
    expect(none.knownTotal).toBeNull();
    expect(none.latestRecordAt).toBeNull();
  });

  it('Claude 链接没写 view 时默认最近五小时', () => {
    expect(parseHash('#/claude?products=code', { provider: 'gpt', view: 'window' }).route.view).toBe('recent5h');
    expect(parseHash('#/gpt', { provider: 'gpt', view: 'window' }).route.view).toBe('window');
  });
});

describe('日历范围与翻页（按当地日历，不按固定毫秒）', () => {
  const iso = (ms: number) => new Date(ms).toISOString();
  it('与交接文档的 UTC 边界一致', () => {
    const d = calendarRange('day', '2026-10-22', 'Asia/Tokyo');
    expect([iso(d.from), iso(d.to)]).toEqual(['2026-10-21T15:00:00.000Z', '2026-10-22T15:00:00.000Z']);
    const w = calendarRange('week', '2026-10-22', 'Asia/Tokyo');
    expect([iso(w.from), iso(w.to)]).toEqual(['2026-10-18T15:00:00.000Z', '2026-10-25T15:00:00.000Z']);
    const m = calendarRange('month', '2026-10-22', 'Asia/Tokyo');
    expect([iso(m.from), iso(m.to)]).toEqual(['2026-09-30T15:00:00.000Z', '2026-10-31T15:00:00.000Z']);
  });
  it('跨月、跨年、闰年翻页', () => {
    expect(shiftDateKey('2026-10-01', 'day', -1)).toBe('2026-09-30');
    expect(shiftDateKey('2026-12-29', 'week', 1)).toBe('2027-01-05');
    expect(shiftDateKey('2026-12-15', 'month', 1)).toBe('2027-01-01');
    expect(shiftDateKey('2028-03-01', 'day', -1)).toBe('2028-02-29');
  });
  it('夏令时那天是 23 小时', () => {
    const d = calendarRange('day', '2026-03-08', 'America/New_York');
    expect((d.to - d.from) / 3600_000).toBe(23);
  });
  it('时间段标签：整天写日期，切开的桶写时间', () => {
    expect(fmtRangeLabel('2026-10-21T15:00:00.000Z', '2026-10-22T15:00:00.000Z', 'Asia/Tokyo')).toBe('10/22 周四');
    expect(fmtRangeLabel('2026-10-21T15:00:00.000Z', '2026-10-22T04:01:00.000Z', 'Asia/Tokyo')).toBe('10/22 00:00–13:01');
    expect(fmtRangeLabel('2026-09-30T15:00:00.000Z', '2026-10-22T04:01:00.000Z', 'Asia/Tokyo')).toBe('10/01 00:00 – 10/22 13:01');
    expect(fmtRangeLabel('2026-10-22T14:00:00.000Z', '2026-10-22T15:00:00.000Z', 'Asia/Tokyo', false)).toBe('23:00–00:00');
  });
});

describe('token 折线：缺失 / 未知处断开，不画成 0', () => {
  const at = (i: number, over: Partial<UsageBucket> = {}) =>
    bucket({ from: new Date(Date.UTC(2026, 9, 22, i)).toISOString(), to: new Date(Date.UTC(2026, 9, 22, i + 1)).toISOString(), ...over });
  it('只连相邻有数值的时段', async () => {
    const { lineRuns } = await import('./usage');
    const noRec = { record_state: 'no_records', total_tokens: null, total_status: 'unknown', event_count: 0, known_total_count: 0 } as const;
    const runs = lineRuns([
      at(0),
      at(1, { total_status: 'partial', total_tokens: 50 }),
      at(2, noRec),
      at(3),
      at(4, { total_tokens: null, total_status: 'unknown' }),
      at(5),
      at(6),
      at(7, { record_state: 'future', total_tokens: null }),
    ]);
    expect(runs.map((r) => r.map((b) => new Date(b.from).getUTCHours()))).toEqual([
      [0, 1],
      [5, 6],
    ]);
  });
});
