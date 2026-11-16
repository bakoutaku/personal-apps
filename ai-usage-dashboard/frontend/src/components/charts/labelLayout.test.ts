import { describe, expect, it } from 'vitest';
import { layoutLabels, overlaps, type LabelSeg } from './labelLayout';

const BOUNDS = { left: 40, right: 998, top: 2, bottom: 188 };
// 与 CalendarQuotaChart 相同的纵轴：0% 在 170，100% 在 22
const y = (v: number) => 170 - (v / 100) * 148;

const seg = (id: string, x1: number, x2: number, v: number, long = false): LabelSeg => ({
  id,
  x1,
  x2,
  y: y(v),
  text: long ? `七天 ${v}%` : `${v}%`,
  long,
});

function check(segs: LabelSeg[]) {
  const r = layoutLabels(segs, BOUNDS);
  // 已显示的标签互不重叠、都在图内
  for (const [i, a] of r.placed.entries()) {
    expect(a.box.x).toBeGreaterThanOrEqual(BOUNDS.left);
    expect(a.box.x + a.box.w).toBeLessThanOrEqual(BOUNDS.right);
    expect(a.box.y).toBeGreaterThanOrEqual(BOUNDS.top);
    expect(a.box.y + a.box.h).toBeLessThanOrEqual(BOUNDS.bottom);
    for (const b of r.placed.slice(i + 1)) expect(overlaps(a.box, b.box, 0), `${a.text} / ${b.text}`).toBe(false);
  }
  // 每个窗口不多不少：显示或收起，不合并
  const ids = [...r.placed.map((p) => p.id), ...r.hidden.map((h) => h.id)];
  expect(new Set(ids).size).toBe(ids.length);
  expect(new Set(ids)).toEqual(new Set(segs.map((s) => s.id)));
  return r;
}

describe('额度百分比标签避让', () => {
  it('截图里的情形：38% / 36% 同位置、0% / 七天 0% / 七天 6% 贴在底边和右边界', () => {
    const r = check([
      seg('w5h_a', 520, 700, 38),
      seg('w5h_b', 520, 700, 36),
      seg('w5h_c', 520, 700, 0),
      seg('w7d_a', 520, 980, 6, true),
      seg('w7d_b', 520, 980, 0, true),
      seg('w7d_c', 45, 980, 64, true),
      seg('w5h_d', 45, 170, 52),
    ]);
    // 这种密度下全部都能放下
    expect(r.hidden).toEqual([]);
    // 数值相同的不同窗口各自保留
    expect(r.placed.filter((p) => p.text.endsWith(' 0%') || p.text === '0%')).toHaveLength(2);
  });

  it('相同数值、相同位置的多个窗口：不合并；放不下的收起而不是叠在一起', () => {
    const segs = Array.from({ length: 12 }, (_, i) => seg(`w${i}`, 500, 520, 36));
    const r = check(segs);
    expect(r.placed.length).toBeGreaterThan(0);
    expect(r.placed.length + r.hidden.length).toBe(12);
  });

  it('边界值：100% 在顶边、0% 在底边、线段贴右边界', () => {
    const r = check([seg('top', 900, 990, 100), seg('bottom', 900, 990, 0), seg('right7', 960, 998, 100, true)]);
    expect(r.hidden).toEqual([]);
  });

  it('同一 window_id 只标一次', () => {
    const r = layoutLabels([seg('dup', 100, 300, 10), seg('dup', 100, 300, 10)], BOUNDS);
    expect(r.placed.length + r.hidden.length).toBe(1);
  });

  it('极短线段（窄屏或月视图里的五小时窗口）仍贴着自己的线段', () => {
    const r = check([seg('a', 600, 604, 20), seg('b', 602, 606, 22), seg('c', 604, 608, 21)]);
    for (const p of r.placed) {
      expect(p.box.x).toBeLessThanOrEqual(616);
      expect(p.box.x + p.box.w).toBeGreaterThanOrEqual(592);
    }
  });
});
