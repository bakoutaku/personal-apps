import { t as translate } from "../i18n";
import type { TokenComponents, UsageBucket } from '../api/types';

/**
 * 柱状图每一段的画法。缺失、未知、未接入都不会落到 0。
 * - future：as_of 之后，不画已用/缺失
 * - no_records_unknown：无记录且覆盖未知 → 斜线底纹“不计为 0”
 * - no_records_gap：有依据的采集缺口
 * - no_records_covered：已覆盖且无活动 → 不画柱，只标字
 * - unknown_total：有事件但 token 全部未知
 * - partial_total：只有已知小计
 * - known_total：完整合计
 */
export type BucketKind =
  | 'future'
  | 'no_records_unknown'
  | 'no_records_gap'
  | 'no_records_covered'
  | 'unknown_total'
  | 'partial_total'
  | 'known_total';

export function classifyBucket(b: UsageBucket): BucketKind {
  if (b.record_state === 'future') return 'future';
  if (b.record_state === 'no_records') {
    if (b.coverage_status === 'gap') return 'no_records_gap';
    if (b.coverage_status === 'complete') return 'no_records_covered';
    return 'no_records_unknown';
  }
  if (b.total_tokens === null || b.total_status === 'unknown') return 'unknown_total';
  if (b.total_status === 'partial') return 'partial_total';
  return 'known_total';
}

/** 能画在 y 轴上的数值；null 表示不能当数值画。 */
export function plottableTotal(b: UsageBucket): number | null {
  const k = classifyBucket(b);
  return k === 'known_total' || k === 'partial_total' ? b.total_tokens : null;
}

/** 只有 components_complete=true 且合计已知时才堆叠。 */
export function canStack(b: Pick<UsageBucket, 'components_complete' | 'total_status' | 'total_tokens'>): boolean {
  return b.components_complete && b.total_status === 'known' && b.total_tokens !== null;
}

export const COMPONENT_KEYS = [
  'uncached_input_tokens',
  'cache_read_input_tokens',
  'cache_write_input_tokens',
  'output_tokens',
] as const satisfies readonly (keyof TokenComponents)[];

export const COMPONENT_LABELS: Record<(typeof COMPONENT_KEYS)[number], string> = {
  get uncached_input_tokens() { return translate("未缓存输入"); },
  get cache_read_input_tokens() { return translate("缓存读取"); },
  get cache_write_input_tokens() { return translate("缓存写入"); },
  get output_tokens() { return translate("输出"); },
};

/** 已知分项的文字；未知分项不写成 0。 */
export function describeComponents(c: TokenComponents): string | null {
  const known = COMPONENT_KEYS.filter((k) => c[k] !== null).map(
    (k) => `${COMPONENT_LABELS[k]} ${fmtTokens(c[k] as number)}`,
  );
  return known.length > 0 ? known.join(' · ') : null;
}

const nf = new Intl.NumberFormat('zh-CN');

export function fmtTokens(n: number): string {
  return nf.format(n);
}

export function fmtTokensShort(n: number): string {
  if (n >= 1_000_000) return `${trim(n / 1_000_000)}M`;
  if (n >= 1_000) return `${trim(n / 1_000)}k`;
  return String(n);
}

function trim(x: number): string {
  return x >= 100 ? String(Math.round(x)) : String(Math.round(x * 10) / 10);
}

/** y 轴“好看”的刻度上限与刻度。max 为 0 或无数值时给一个最小刻度，但不画柱。 */
export function niceTicks(max: number, count = 2): { top: number; ticks: number[] } {
  if (!(max > 0)) return { top: 1000, ticks: [0, 500, 1000] };
  const rawStep = max / count;
  const mag = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rawStep) ?? 10 * mag;
  const top = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top + step / 2; v += step) ticks.push(v);
  return { top, ticks };
}

export interface ActivitySummary {
  /** 各桶已知数值之和（桶不重叠，可相加）；没有任何已知数值时为 null，不写 0 */
  knownTotal: number | null;
  /** 有记录但 token 未知的事件数；>0 时 knownTotal 只是已知小计 */
  unknownEvents: number;
  eventCount: number;
  /** 范围内最新一条记录的时间 */
  latestRecordAt: string | null;
}

/** 某个范围（如最近五小时）的活动摘要。只在已记录事件上统计，不推断未记录部分。 */
export function summarizeActivity(buckets: UsageBucket[], eventTimes: string[]): ActivitySummary {
  let known: number | null = null;
  let unknownEvents = 0;
  let eventCount = 0;
  for (const b of buckets) {
    eventCount += b.event_count;
    unknownEvents += b.unknown_total_count;
    const v = plottableTotal(b);
    if (v !== null) known = (known ?? 0) + v;
  }
  const latestRecordAt = eventTimes.length ? eventTimes.reduce((a, b) => (Date.parse(b) > Date.parse(a) ? b : a)) : null;
  return { knownTotal: known, unknownEvents, eventCount, latestRecordAt };
}

/** 折线只连相邻、都有数值（合计或已知小计）的时段；中间隔着无记录 / 未知 / 未来就断开。 */
export function lineRuns(buckets: UsageBucket[]): UsageBucket[][] {
  const out: UsageBucket[][] = [];
  let cur: UsageBucket[] = [];
  for (const b of buckets) {
    const k = classifyBucket(b);
    const valued = (k === 'known_total' || k === 'partial_total') && plottableTotal(b) !== null;
    const prev = cur.at(-1);
    if (valued && prev && prev.to === b.from) cur.push(b);
    else {
      if (cur.length > 1) out.push(cur);
      cur = valued ? [b] : [];
    }
  }
  if (cur.length > 1) out.push(cur);
  return out;
}
