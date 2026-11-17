import { currentLanguage, t as translate } from "../i18n";
// 时区相关：一律以 meta.timezone（IANA）为准，不使用浏览器本地时区。

const partsFmtCache = new Map<string, Intl.DateTimeFormat>();

function partsFormatter(tz: string): Intl.DateTimeFormat {
  let f = partsFmtCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      weekday: 'short',
    });
    partsFmtCache.set(tz, f);
  }
  return f;
}

export interface LocalParts {
  year: number;
  month: number; // 1–12
  day: number;
  hour: number;
  minute: number;
  second: number;
  /** 周一 = 0 … 周日 = 6 */
  weekdayFromMonday: number;
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function localParts(ms: number, tz: string): LocalParts {
  const p: Record<string, string> = {};
  for (const part of partsFormatter(tz).formatToParts(new Date(ms))) p[part.type] = part.value;
  return {
    year: Number(p.year),
    month: Number(p.month),
    day: Number(p.day),
    hour: Number(p.hour),
    minute: Number(p.minute),
    second: Number(p.second),
    weekdayFromMonday: WEEKDAYS.indexOf(p.weekday ?? ''),
  };
}

/** 该时刻在 tz 中相对 UTC 的偏移（毫秒）。 */
function offsetAt(ms: number, tz: string): number {
  const p = localParts(ms, tz);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return asUtc - Math.floor(ms / 1000) * 1000;
}

/** tz 中的当地墙钟时间 → UTC 毫秒。DST 跳变处取较早的合法时刻。 */
export function zonedToUtc(year: number, month: number, day: number, tz: string, hour = 0, minute = 0): number {
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  let guess = wall - offsetAt(wall, tz);
  guess = wall - offsetAt(guess, tz);
  return guess;
}

export function startOfLocalDay(ms: number, tz: string): number {
  const p = localParts(ms, tz);
  return zonedToUtc(p.year, p.month, p.day, tz);
}

/** 自然周 [周一 00:00, 下周一 00:00)。 */
export function localWeekRange(ms: number, tz: string): { from: number; to: number } {
  const p = localParts(ms, tz);
  const mondayUtcDate = new Date(Date.UTC(p.year, p.month - 1, p.day - p.weekdayFromMonday));
  const nextMonday = new Date(mondayUtcDate.getTime() + 7 * 86400_000);
  return {
    from: zonedToUtc(mondayUtcDate.getUTCFullYear(), mondayUtcDate.getUTCMonth() + 1, mondayUtcDate.getUTCDate(), tz),
    to: zonedToUtc(nextMonday.getUTCFullYear(), nextMonday.getUTCMonth() + 1, nextMonday.getUTCDate(), tz),
  };
}

/** 自然月 [1 日 00:00, 下月 1 日 00:00)。 */
export function localMonthRange(ms: number, tz: string): { from: number; to: number } {
  const p = localParts(ms, tz);
  const nextYear = p.month === 12 ? p.year + 1 : p.year;
  const nextMonth = p.month === 12 ? 1 : p.month + 1;
  return { from: zonedToUtc(p.year, p.month, 1, tz), to: zonedToUtc(nextYear, nextMonth, 1, tz) };
}

const pad = (n: number) => String(n).padStart(2, '0');

export function fmtTime(iso: string | number, tz: string): string {
  const p = localParts(typeof iso === 'number' ? iso : Date.parse(iso), tz);
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

export function fmtDate(iso: string | number, tz: string): string {
  const p = localParts(typeof iso === 'number' ? iso : Date.parse(iso), tz);
  return `${pad(p.month)}/${pad(p.day)}`;
}

/** 与参考日同一当地日期只显示时间，否则带日期。 */
export function fmtDateTimeRel(iso: string | number, refMs: number, tz: string): string {
  const ms = typeof iso === 'number' ? iso : Date.parse(iso);
  const same = startOfLocalDay(ms, tz) === startOfLocalDay(refMs, tz);
  return same ? fmtTime(ms, tz) : `${fmtDate(ms, tz)} ${fmtTime(ms, tz)}`;
}

/** 时长 → “1:57”（时:分）或 “4 天 20 小时”。负值返回 null。 */
export function fmtRemaining(ms: number): string | null {
  if (ms < 0) return null;
  const totalMin = Math.floor(ms / 60_000);
  const days = Math.floor(totalMin / 1440);
  const h = Math.floor((totalMin % 1440) / 60);
  const m = totalMin % 60;
  if (days > 0) return translate("{0} 天 {1} 小时", days, h);
  return `${h}:${pad(m)}`;
}

/** 相对于 as_of 的“x 分钟前”。 */
export function fmtAgo(iso: string, asOfMs: number): string {
  const diffMin = Math.round((asOfMs - Date.parse(iso)) / 60_000);
  if (diffMin < 0) return translate("晚于模拟时钟");
  if (diffMin < 1) return translate("刚刚");
  if (diffMin < 60) return translate("{0} 分钟前", diffMin);
  const h = Math.floor(diffMin / 60);
  if (h < 48) return translate("{0} 小时前", h);
  return translate("{0} 天前", Math.floor(h / 24));
}

export function fmtDurationSeconds(sec: number): string {
  if (sec % 86400 === 0) return translate("{0} 天", sec / 86400);
  if (sec % 3600 === 0) return translate("{0} 小时", sec / 3600);
  return translate("{0} 分", Math.round(sec / 60));
}

// ---- 自然日 / 周 / 月（日历视图用）----

export type CalendarView = 'day' | 'week' | 'month';

/** 当地日期键 YYYY-MM-DD（按 tz）。 */
export function localDateKey(ms: number, tz: string): string {
  const p = localParts(ms, tz);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

function parseKey(key: string): { y: number; m: number; d: number } | null {
  const mt = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (!mt) return null;
  const y = Number(mt[1]);
  const m = Number(mt[2]);
  const d = Number(mt[3]);
  const check = new Date(Date.UTC(y, m - 1, d));
  if (check.getUTCFullYear() !== y || check.getUTCMonth() !== m - 1 || check.getUTCDate() !== d) return null;
  return { y, m, d };
}

export function isDateKey(key: string): boolean {
  return parseKey(key) !== null;
}

/** 日期键按日历加减（不按毫秒，避开夏令时 23/25 小时）。 */
export function shiftDateKey(key: string, view: CalendarView, n: number): string {
  const k = parseKey(key)!;
  const dt =
    view === 'month'
      ? new Date(Date.UTC(k.y, k.m - 1 + n, 1))
      : new Date(Date.UTC(k.y, k.m - 1, k.d + (view === 'week' ? 7 * n : n)));
  return `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`;
}

/** 包含该日期的自然日 / 周（周一起）/ 月，返回 UTC 毫秒的 [from, to)。 */
export function calendarRange(view: CalendarView, key: string, tz: string): { from: number; to: number } {
  const k = parseKey(key)!;
  const noon = zonedToUtc(k.y, k.m, k.d, tz, 12);
  if (view === 'week') return localWeekRange(noon, tz);
  if (view === 'month') return localMonthRange(noon, tz);
  const next = new Date(Date.UTC(k.y, k.m - 1, k.d + 1));
  return {
    from: zonedToUtc(k.y, k.m, k.d, tz),
    to: zonedToUtc(next.getUTCFullYear(), next.getUTCMonth() + 1, next.getUTCDate(), tz),
  };
}

const WEEKDAY_ZH = ['一', '二', '三', '四', '五', '六', '日'];

export function fmtWeekday(ms: number, tz: string): string {
  if (currentLanguage() !== 'zh-CN') {
    return new Intl.DateTimeFormat(currentLanguage(), { weekday: 'short', timeZone: tz }).format(ms);
  }
  return `周${WEEKDAY_ZH[localParts(ms, tz).weekdayFromMonday] ?? ''}`;
}

/** 时间段标签：整天对齐时只写日期；同一天写“日期 时:分–时:分”；withDate=false 时省略日期。 */
export function fmtRangeLabel(fromIso: string | number, toIso: string | number, tz: string, withDate = true): string {
  const f = typeof fromIso === 'number' ? fromIso : Date.parse(fromIso);
  const t = typeof toIso === 'number' ? toIso : Date.parse(toIso);
  const fromMidnight = startOfLocalDay(f, tz) === f;
  const toMidnight = startOfLocalDay(t, tz) === t;
  if (fromMidnight && toMidnight) {
    const lastDay = t - 1;
    return startOfLocalDay(lastDay, tz) === f
      ? `${fmtDate(f, tz)} ${fmtWeekday(f, tz)}`
      : `${fmtDate(f, tz)}–${fmtDate(lastDay, tz)}`;
  }
  // 跨日（结束不是起点次日的 00:00）时两端都写日期，避免看成同一天
  const sameDay = startOfLocalDay(f, tz) === startOfLocalDay(t, tz) || (toMidnight && startOfLocalDay(t - 1, tz) === startOfLocalDay(f, tz));
  if (!sameDay) return `${fmtDate(f, tz)} ${fmtTime(f, tz)} – ${fmtDate(t, tz)} ${fmtTime(t, tz)}`;
  const head = withDate ? `${fmtDate(f, tz)} ` : '';
  return `${head}${fmtTime(f, tz)}–${fmtTime(t, tz)}`;
}
