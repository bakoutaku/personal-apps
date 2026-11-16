// 额度线段的百分比标签避让（纯布局，不改数据）。
// 每个窗口（window_id）最多一个标签；不同窗口即使数值相同也各自保留，不合并、不取最大值、不相加。
// 依次尝试线段旁的候选位置，避开已放的标签和其他线段；放不下的标签收起，由调用方在悬停 / 列表里给出。

export interface LabelSeg {
  id: string;
  /** 线段两端 x（viewBox 单位） */
  x1: number;
  x2: number;
  y: number;
  text: string;
  /** 七天等长窗口：优先放右端 */
  long: boolean;
}

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PlacedLabel {
  id: string;
  text: string;
  /** 文字基线位置，textAnchor 固定 start */
  x: number;
  y: number;
  box: Box;
}

export interface LabelLayout {
  placed: PlacedLabel[];
  /** 没有空间显示的标签（保持原顺序） */
  hidden: LabelSeg[];
}

export interface LayoutBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
  fontSize?: number;
}

/** 估算文字宽度：等宽数字 ≈ 0.62em，中文 ≈ 1em。 */
export function textWidth(text: string, fontSize: number): number {
  let w = 0;
  for (const ch of text) w += /[⺀-￿]/.test(ch) ? fontSize : fontSize * 0.62;
  return w;
}

export function overlaps(a: Box, b: Box, pad = 1): boolean {
  return a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;
}

export function layoutLabels(segs: LabelSeg[], bounds: LayoutBounds): LabelLayout {
  const fs = bounds.fontSize ?? 11;
  const h = fs + 2;
  const gap = 3;
  // 其他线段当作障碍（线宽按 6 估）；先尝试避开线段，实在放不下再允许压线
  const lines: (Box & { id: string })[] = segs.map((s) => ({ id: s.id, x: Math.min(s.x1, s.x2), y: s.y - 3, w: Math.abs(s.x2 - s.x1), h: 6 }));
  const placed: PlacedLabel[] = [];
  const hidden: LabelSeg[] = [];
  const seen = new Set<string>();

  for (const s of segs) {
    if (seen.has(s.id)) continue; // 同一窗口只标一次
    seen.add(s.id);
    const w = textWidth(s.text, fs);
    const mid = (s.x1 + s.x2) / 2;
    // 候选 x（文字左端）：长窗口先右端，短窗口先中间；再试两端与 1/4、3/4 处
    const xs = (s.long ? [s.x2 - w, mid - w / 2, s.x1] : [mid - w / 2, s.x2 - w, s.x1, s.x2 + 4])
      .concat([s.x1 + (s.x2 - s.x1) / 4 - w / 2, s.x1 + ((s.x2 - s.x1) * 3) / 4 - w / 2]);
    // 候选 y（文字框顶）：线上方 / 下方，再往外一层
    const ys = s.long ? [s.y + gap, s.y - gap - h, s.y + gap + h, s.y - gap - 2 * h] : [s.y - gap - h, s.y + gap, s.y - gap - 2 * h, s.y + gap + h];
    const clampBox = (x: number, y: number): Box | null => {
      const cx = Math.min(Math.max(x, bounds.left), bounds.right - w);
      if (cx < bounds.left) return null; // 比绘图区还宽
      // 竖直方向不夹紧（夹紧会把标签挪离自己的线段），越界的候选直接跳过
      if (y < bounds.top || y + h > bounds.bottom) return null;
      // 夹紧后仍要挨着自己的线段（允许超出线段端点一点）
      if (cx > Math.max(s.x1, s.x2) + 8 || cx + w < Math.min(s.x1, s.x2) - 8) return null;
      return { x: cx, y, w, h };
    };
    const candidates: Box[] = [];
    for (const y of ys) for (const x of xs) {
      const b = clampBox(x, y);
      if (b) candidates.push(b);
    }
    const free = (b: Box, avoidLines: boolean) =>
      placed.every((p) => !overlaps(p.box, b)) && (!avoidLines || lines.every((l) => l.id === s.id || !overlaps(l, b, 0)));
    const box = candidates.find((b) => free(b, true)) ?? candidates.find((b) => free(b, false));
    if (!box) {
      hidden.push(s);
      continue;
    }
    placed.push({ id: s.id, text: s.text, x: box.x, y: box.y + h - 3, box });
  }
  return { placed, hidden };
}
