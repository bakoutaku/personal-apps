import type { QuotaPool, QuotaSnapshot, QuotaWindow } from '../api/types';
import { fmtDurationSeconds } from '../time/tz';

export type CardStatus = 'current' | 'expired' | 'unknown';

export interface CardState {
  status: CardStatus;
  /** 仅 status=current 时有意义；expired 优先于新鲜度。 */
  stale: boolean;
  percent: number | null;
  overHundred: boolean;
  /** observed_at 为 null 时不把记录时间说成观测时间。 */
  timeLabel: '最近观测' | '日志记录于';
  timeIso: string | null;
}

export function cardState(w: QuotaWindow): CardState {
  const snap = w.latest_snapshot;
  const status: CardStatus = w.status;
  return {
    status,
    stale: status === 'current' && w.freshness === 'stale',
    percent: snap?.used_percent ?? null,
    overHundred: (snap?.used_percent ?? 0) > 100,
    timeLabel: snap?.time_basis === 'observed_at' ? '最近观测' : '日志记录于',
    timeIso: snap ? snap.effective_at : null,
  };
}

export function snapshotTimeLabel(s: QuotaSnapshot): string {
  return s.time_basis === 'observed_at' ? '观测于' : '日志记录于';
}

/** 按时长起标题；slot 是不透明字符串，不假设 primary 就是五小时。 */
export function slotTitle(w: Pick<QuotaWindow, 'duration_seconds'>): string {
  if (w.duration_seconds === 18000) return '五小时窗口';
  if (w.duration_seconds === 604800) return '七天窗口';
  if (w.duration_seconds) return `${fmtDurationSeconds(w.duration_seconds)}窗口`;
  return '时长未知的窗口';
}

/** 窗口边界依据的短文案。 */
export function boundarySourceText(
  which: 'start' | 'end',
  w: Pick<QuotaWindow, 'start_source' | 'end_source' | 'duration_seconds'>,
): string {
  const src = which === 'start' ? w.start_source : w.end_source;
  if (src === 'reported') return '来源报告';
  if (src === 'unknown') return '未知';
  if (which === 'start' && w.end_source === 'reported' && w.duration_seconds) {
    return `推导：结束 − ${Math.round(w.duration_seconds / 60)} 分`;
  }
  return '推导';
}

export function hasFullBounds(w: QuotaWindow): boolean {
  return w.starts_at !== null && w.ends_at !== null && w.start_source !== 'unknown' && w.end_source !== 'unknown';
}

/** 记录新鲜度 = 最新快照的 effective_at。重置时间（ends_at）不代表数据更新。 */
const snapshotTime = (w: QuotaWindow) => Date.parse(w.latest_snapshot?.effective_at ?? '') || -Infinity;
const byDuration = (a: QuotaWindow, b: QuotaWindow) =>
  (a.duration_seconds ?? Infinity) - (b.duration_seconds ?? Infinity);
const slotKey = (w: QuotaWindow) => `${w.pool_id}\u0000${w.slot}`;

/** 同一组内选一个：优先 current，再取最新快照记录；记录时间相同时按 id 固定顺序，与响应顺序无关。 */
function pickLatestRecord(ws: QuotaWindow[]): QuotaWindow {
  const current = ws.filter((w) => w.status === 'current');
  const pool = current.length > 0 ? current : ws;
  return pool.reduce((a, b) => {
    const d = snapshotTime(b) - snapshotTime(a);
    if (d !== 0) return d > 0 ? b : a;
    return b.id < a.id ? b : a;
  });
}

/**
 * 额度卡：每个“池 + slot”一张，用 pickLatestRecord 选定。没有当前窗口时显示该槽位最新记录的窗口
 * （会标“窗口已结束 / 状态未知”，不当作当前额度）。按时长从短到长排列。
 * 卡片和默认历史窗口都从这里取，保证是同一个 window_id。
 */
export function cardWindows(windows: QuotaWindow[]): QuotaWindow[] {
  const groups = new Map<string, QuotaWindow[]>();
  for (const w of windows) groups.set(slotKey(w), [...(groups.get(slotKey(w)) ?? []), w]);
  return [...groups.values()].map(pickLatestRecord).sort(byDuration);
}

/** 历史视图默认窗口：在 cardWindows 选出的窗口里取边界完整的当前窗口，五小时优先，否则最短。没有则 undefined。 */
export function defaultWindow(windows: QuotaWindow[]): QuotaWindow | undefined {
  const ok = cardWindows(windows).filter((w) => w.status === 'current' && hasFullBounds(w));
  return ok.find((w) => w.duration_seconds === 18000) ?? ok[0];
}

/**
 * 同一池 + slot 中与 w 边界不同且时间重叠（或边界未知）的其他窗口记录。
 * 只用于提示“存在不同窗口记录”；不合并、不相加，也不说明它们是同一窗口的修订。
 */
export function overlappingCandidates(windows: QuotaWindow[], w: QuotaWindow): QuotaWindow[] {
  const range = (x: QuotaWindow) =>
    x.starts_at && x.ends_at ? ([Date.parse(x.starts_at), Date.parse(x.ends_at)] as const) : null;
  const rw = range(w);
  return windows.filter((x) => {
    if (x.id === w.id || slotKey(x) !== slotKey(w)) return false;
    const rx = range(x);
    if (!rw || !rx) return true;
    const sameBounds = rx[0] === rw[0] && rx[1] === rw[1];
    return !sameBounds && rx[0] < rw[1] && rw[0] < rx[1];
  });
}

const PRODUCT_NAMES: Record<string, string> = {
  chat: 'Chat',
  work: 'Work',
  codex: 'Codex',
  code: 'Code',
  cowork: 'Cowork',
};

export function productName(p: string): string {
  return PRODUCT_NAMES[p] ?? p;
}

/** 池的关联产品说明；未列出的产品不视为不共享。 */
export function poolMembershipText(pool: QuotaPool, allProducts: readonly string[]): string {
  if (pool.products === null) return '关联产品未知';
  const listed = pool.products.map(productName).join(' / ');
  const others = allProducts.filter((p) => !pool.products!.includes(p as never));
  if (pool.product_membership_complete || others.length === 0) return `关联产品：${listed}`;
  return `关联产品：${listed} · ${others.map(productName).join(' / ')}：未知`;
}
