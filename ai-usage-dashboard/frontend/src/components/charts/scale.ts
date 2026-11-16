import { localParts } from '../../time/tz';

/** 所有图表共用的横轴：viewBox 宽 1000，绘图区 [X0, X1]。标签轨道用同一比例换算百分比。 */
export const VIEW_W = 1000;
export const X0 = 40;
export const X1 = 980;

export interface TimeScale {
  from: number;
  to: number;
  x: (ms: number) => number;
  /** 0–100，给 HTML 绝对定位用 */
  pct: (ms: number) => number;
  clamp: (ms: number) => number;
}

export function timeScale(from: number, to: number): TimeScale {
  const span = Math.max(1, to - from);
  const clamp = (ms: number) => Math.min(to, Math.max(from, ms));
  const x = (ms: number) => X0 + ((clamp(ms) - from) / span) * (X1 - X0);
  return { from, to, x, pct: (ms) => (x(ms) / VIEW_W) * 100, clamp };
}

/** 当地整点刻度（按 meta.timezone，适用于非整小时偏移的时区）。 */
export function hourTicks(from: number, to: number, tz: string, everyHours = 1): number[] {
  const out: number[] = [];
  let t = Math.ceil(from / 60_000) * 60_000;
  // 找到第一个当地整点
  for (let i = 0; i < 60 && t <= to; i++, t += 60_000) {
    if (localParts(t, tz).minute === 0) break;
  }
  for (; t <= to; t += 3600_000) {
    if (localParts(t, tz).hour % everyHours === 0) out.push(t);
  }
  return out;
}

export interface Tick {
  t: number;
  label: string;
}

/**
 * 日历视图刻度（按 tz 的当地边界）：
 * 日 → 每 3 小时；周 → 每天（日期 + 星期）；月 → 1、8、15、22、29 日。
 */
export function calendarTicks(view: 'day' | 'week' | 'month', from: number, to: number, tz: string): Tick[] {
  const pad = (n: number) => String(n).padStart(2, '0');
  if (view === 'day') {
    return hourTicks(from, to, tz, 3).map((t) => ({ t, label: `${pad(localParts(t, tz).hour)}` }));
  }
  const out: Tick[] = [];
  // 逐个当地日界：从 from 起每次跨过约一天后回到当地 00:00（不按固定 86400000 毫秒累加）
  let t = from;
  for (let i = 0; i < 40 && t < to; i++) {
    const p = localParts(t, tz);
    if (view === 'week' || [1, 8, 15, 22, 29].includes(p.day)) {
      const wd = ['一', '二', '三', '四', '五', '六', '日'][p.weekdayFromMonday] ?? '';
      out.push({ t, label: view === 'week' ? `${pad(p.month)}/${pad(p.day)} ${wd}` : `${pad(p.month)}/${pad(p.day)}` });
    }
    const probe = t + 30 * 3600_000; // 一定落在下一个当地日内（23/25 小时的日子也成立）
    const q = localParts(probe, tz);
    t = probe - ((q.hour * 60 + q.minute) * 60 + q.second) * 1000;
  }
  return out;
}
