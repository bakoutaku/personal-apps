import { t as translate, useLanguage } from "../../i18n";
import type { UsageBucket, UsageSeries } from '../../api/types';
import {
  canStack,
  classifyBucket,
  COMPONENT_KEYS,
  COMPONENT_LABELS,
  describeComponents,
  fmtTokens,
  fmtTokensShort,
  lineRuns,
  niceTicks,
  plottableTotal,
  type BucketKind,
} from '../../domain/usage';
import { fmtRangeLabel, fmtTime } from '../../time/tz';
import type { Clock } from '../common';
import { hourTicks, X0, X1, type Tick, type TimeScale } from './scale';

const TOP = 20;
const STACK_FILLS = ['var(--stack-1)', 'var(--stack-2)', 'var(--stack-3)', 'var(--stack-4)'];

const KIND_TEXT: Record<BucketKind, string> = {
  get future() { return translate("尚未发生"); },
  get no_records_unknown() { return translate("无记录 · 覆盖未知 · 不计为 0"); },
  get no_records_gap() { return translate("采集缺口 · 不计为 0"); },
  get no_records_covered() { return translate("已覆盖 · 无活动记录"); },
  get unknown_total() { return translate("有记录 · token 用量未知"); },
  get partial_total() { return translate("已知小计（部分事件用量未知）"); },
  get known_total() { return translate("合计"); },
};

interface Props {
  series: UsageSeries;
  scale: TimeScale;
  clock: Clock;
  /** 自定义横轴刻度（日历视图）；缺省为当地整点 */
  axis?: Tick[];
  /** 点选某个已过去的桶（日历视图用来过滤明细） */
  onSelect?: (from: string, to: string) => void;
  /** 当前选中的时间段，用于高亮 */
  selected?: { from: string; to: string } | null;
  /** 柱状（默认）或折线。折线只连相邻的有数值时段；无记录 / 用量未知处断开，不画成 0。 */
  variant?: 'bar' | 'line';
  /** 绘图区高度（viewBox 单位，宽 1000）；首页主图更高 */
  plotHeight?: number;
  /** 首页：不在图里写“无记录 / 无活动”字样，靠图案和图例区分（整幅无数据由调用方提示一次） */
  quiet?: boolean;
}

function bucketTip(b: UsageBucket, tz: string): string {
  const k = classifyBucket(b);
  const head = `${fmtRangeLabel(b.from, b.to, tz)}${b.is_partial_bucket ? translate("（不完整的桶）") : ''}`;
  const lines = [head, KIND_TEXT[k]];
  const v = plottableTotal(b);
  if (v !== null) lines.push(`${k === 'partial_total' ? translate("已知小计") : translate("合计")} ${fmtTokens(v)} token`);
  if (b.event_count > 0) lines.push(translate("事件 {0}（已知 {1} / 未知 {2}）", b.event_count, b.known_total_count, b.unknown_total_count));
  if (v !== null && !canStack(b)) {
    const parts = describeComponents(b.components);
    lines.push(parts ? translate("已知分项：{0}", parts) : translate("分项未知"));
  }
  return lines.join('\n');
}

export function TokenBarChart({ series, scale, clock, axis, onSelect, selected, variant = 'bar', plotHeight = 100, quiet = false }: Props) {
  useLanguage();
  const BASE = TOP + plotHeight;
  const line = variant === 'line';
  const buckets = series.buckets;
  const max = Math.max(0, ...buckets.map((b) => plottableTotal(b) ?? 0));
  const { top, ticks } = niceTicks(max);
  const y = (v: number) => BASE - (v / top) * (BASE - TOP);
  const loadedFrom = Date.parse(series.from);
  const loadedTo = Date.parse(series.to);
  const axisTicks: Tick[] = axis ?? hourTicks(scale.from, scale.to, clock.tz).map((t) => ({ t, label: fmtTime(t, clock.tz) }));
  const nowInside = clock.asOfMs > scale.from && clock.asOfMs < scale.to;

  // 连续“无记录·覆盖未知”合并标字
  const runs: { from: number; to: number }[] = [];
  for (const b of buckets) {
    if (classifyBucket(b) !== 'no_records_unknown') continue;
    const f = Date.parse(b.from);
    const t = Date.parse(b.to);
    const lastRun = runs.at(-1);
    if (lastRun && lastRun.to === f) lastRun.to = t;
    else runs.push({ from: f, to: t });
  }

  const unknownCount = buckets.filter((b) => classifyBucket(b) === 'unknown_total').length;
  const desc = translate("{0}每{1} token 用量。{2}{3}", line ? translate("折线：") : '', series.bucket === 'day' ? translate("天") : series.bucket === 'hour' ? translate("小时") : translate(" 15 分钟"), runs.length ? translate("部分时段无记录，覆盖未知，不计为 0。") : '', unknownCount ? translate("{0} 个时段有记录但用量未知。", unknownCount) : '');

  return (
    <svg className="chart-svg" viewBox={`0 0 1000 ${BASE + 26}`} role="img" aria-label={desc}>
      <defs>
        <pattern id="hatch-unknown" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="8" stroke="var(--hatch)" strokeWidth="2" />
        </pattern>
        <pattern id="hatch-gap" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
          <line x1="0" y1="0" x2="0" y2="5" stroke="var(--danger)" strokeWidth="1.2" opacity="0.5" />
        </pattern>
        <pattern id="dots-notloaded" width="6" height="6" patternUnits="userSpaceOnUse">
          <circle cx="3" cy="3" r="0.9" fill="var(--text-subtle)" opacity="0.5" />
        </pattern>
      </defs>

      {nowInside && <rect x={scale.x(clock.asOfMs)} y={TOP - 6} width={X1 - scale.x(clock.asOfMs)} height={BASE - TOP + 6} fill="var(--future)" />}
      {ticks.map((v, i) => (
        <g key={v}>
          <line x1={X0} y1={y(v)} x2={X1} y2={y(v)} stroke={i === 0 ? 'var(--border)' : 'var(--grid)'} />
          <text x={34} y={y(v) + 4} fontSize={11} fill="var(--text-muted)" textAnchor="end" className="mono">
            {fmtTokensShort(v)}
          </text>
        </g>
      ))}

      {/* 查询未覆盖的范围：未加载（不同于无记录） */}
      {[
        [scale.from, Math.min(loadedFrom, scale.to)],
        [Math.max(loadedTo, scale.from), scale.to],
      ]
        .filter(([a, b]) => b! > a!)
        .map(([a, b]) => (
          <g key={`nl-${a}`}>
            <rect x={scale.x(a!)} y={TOP} width={scale.x(b!) - scale.x(a!)} height={BASE - TOP} fill="url(#dots-notloaded)">
              <title>{translate("未加载：查询范围之外")}</title>
            </rect>
            <text x={(scale.x(a!) + scale.x(b!)) / 2} y={TOP - 6} fontSize={11} fill="var(--text-muted)" textAnchor="middle">
              {translate("未加载")}
            </text>
          </g>
        ))}

      {buckets.map((b) => {
        const k = classifyBucket(b);
        if (k === 'future') return null;
        const x0 = scale.x(Date.parse(b.from));
        const x1 = scale.x(Date.parse(b.to));
        const pad = x1 - x0 > 12 ? 3 : 0.5;
        const bx = x0 + pad;
        const bw = Math.max(1, x1 - x0 - pad * 2);
        const tip = bucketTip(b, clock.tz);
        const fade = b.is_partial_bucket ? 0.6 : 1;
        const key = b.from;

        if (k === 'no_records_unknown' || k === 'no_records_gap') {
          return (
            <rect key={key} x={bx} y={TOP} width={bw} height={BASE - TOP} rx={3} fill={k === 'no_records_gap' ? 'url(#hatch-gap)' : 'url(#hatch-unknown)'} stroke="var(--hatch)" strokeDasharray="3 3" opacity={fade}>
              <title>{tip}</title>
            </rect>
          );
        }
        if (k === 'no_records_covered') {
          return (
            <g key={key}>
              <rect x={bx} y={TOP} width={bw} height={BASE - TOP} fill="transparent">
                <title>{tip}</title>
              </rect>
              {bw > 20 && !quiet && (
                <text x={bx + bw / 2} y={BASE - 6} fontSize={10} fill="var(--text-muted)" textAnchor="middle">
                  {translate("无活动")}
                </text>
              )}
            </g>
          );
        }
        if (k === 'unknown_total') {
          return (
            <g key={key} opacity={fade}>
              <rect x={bx} y={TOP} width={bw} height={BASE - TOP} rx={4} fill="var(--surface)" stroke="var(--bar)" strokeDasharray="4 3">
                <title>{tip}</title>
              </rect>
              <text x={bx + bw / 2} y={(TOP + BASE) / 2 + 5} fontSize={14} fill="var(--accent-strong)" textAnchor="middle" pointerEvents="none">
                ?
              </text>
            </g>
          );
        }
        const v = b.total_tokens as number;
        if (line) {
          const cx = (x0 + x1) / 2;
          return (
            <g key={key} opacity={fade}>
              <circle cx={cx} cy={y(v)} r={3.5} fill={k === 'partial_total' ? 'var(--surface)' : 'var(--accent)'} stroke="var(--accent)" strokeWidth={1.5} />
              {k === 'partial_total' && (
                <text x={cx} y={y(v) - 7} fontSize={10} fill="var(--accent-strong)" textAnchor="middle" pointerEvents="none">
                  ≥
                </text>
              )}
              <rect x={bx} y={TOP} width={bw} height={BASE - TOP} fill="transparent">
                <title>{tip}</title>
              </rect>
            </g>
          );
        }
        if (k === 'partial_total') {
          return (
            <g key={key}>
              <rect x={bx} y={y(v)} width={bw} height={BASE - y(v)} rx={4} fill="var(--bar)" opacity={0.5 * fade} stroke="var(--accent)" strokeDasharray="3 2">
                <title>{tip}</title>
              </rect>
              <text x={bx + bw / 2} y={y(v) - 4} fontSize={10} fill="var(--accent-strong)" textAnchor="middle" pointerEvents="none">
                ≥
              </text>
            </g>
          );
        }
        if (canStack(b)) {
          let acc = 0;
          return (
            <g key={key} opacity={fade}>
              {COMPONENT_KEYS.map((ck, i) => {
                const part = b.components[ck] as number;
                const y1 = y(acc);
                acc += part;
                const y2 = y(acc);
                return <rect key={ck} x={bx} y={y2} width={bw} height={Math.max(0, y1 - y2)} fill={STACK_FILLS[i]} />;
              })}
              <rect x={bx} y={y(v)} width={bw} height={BASE - y(v)} fill="transparent">
                <title>{`${tip}\n${COMPONENT_KEYS.map((ck) => `${COMPONENT_LABELS[ck]} ${fmtTokens(b.components[ck] as number)}`).join('\n')}`}</title>
              </rect>
            </g>
          );
        }
        return (
          <rect key={key} x={bx} y={y(v)} width={bw} height={BASE - y(v)} rx={4} fill="var(--bar)" opacity={fade}>
            <title>{tip}</title>
          </rect>
        );
      })}

      {line &&
        lineRuns(buckets).map((run) => (
          <polyline
            key={run[0]!.from}
            points={run.map((b) => `${(scale.x(Date.parse(b.from)) + scale.x(Date.parse(b.to))) / 2},${y(plottableTotal(b) as number)}`).join(' ')}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={2}
            strokeLinejoin="round"
            pointerEvents="none"
          />
        ))}

      {runs.map((r) =>
        !quiet && scale.x(r.to) - scale.x(r.from) > 40 ? (
          <text key={r.from} x={(scale.x(r.from) + scale.x(r.to)) / 2} y={TOP - 6} fontSize={11} fill="var(--text-muted)" textAnchor="middle">
            {translate("无记录")}
          </text>
        ) : null,
      )}

      {nowInside && <line x1={scale.x(clock.asOfMs)} y1={TOP - 8} x2={scale.x(clock.asOfMs)} y2={BASE + 2} stroke="var(--text)" />}

      {axisTicks.map((tk) => (
        <text key={tk.t} x={scale.x(tk.t)} y={BASE + 18} fontSize={11} fill="var(--text-subtle)" textAnchor="middle" className="mono">
          {tk.label}
        </text>
      ))}

      {/* 选中高亮与点选热区（只覆盖已过去的桶；未来不能选） */}
      {selected && (
        <rect
          x={scale.x(Date.parse(selected.from))}
          y={TOP - 8}
          width={Math.max(2, scale.x(Date.parse(selected.to)) - scale.x(Date.parse(selected.from)))}
          height={BASE - TOP + 10}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={2}
          rx={4}
          pointerEvents="none"
        />
      )}
      {onSelect &&
        buckets
          .filter((b) => b.record_state !== 'future')
          .map((b) => (
            <rect
              key={`hit-${b.from}`}
              x={scale.x(Date.parse(b.from))}
              y={TOP - 8}
              width={Math.max(1, scale.x(Date.parse(b.to)) - scale.x(Date.parse(b.from)))}
              height={BASE - TOP + 10}
              fill="transparent"
              style={{ cursor: 'pointer' }}
              onClick={() => onSelect(b.from, b.to)}
            >
              <title>{translate("{0}\n点击打开这一段的明细", bucketTip(b, clock.tz))}</title>
            </rect>
          ))}
    </svg>
  );
}

export function TokenLegend() {
  useLanguage();
  return (
    <span className="legend">
      <span>
        <span className="legend-swatch" style={{ background: 'var(--bar)' }} />
        {translate("合计")}
      </span>
      <span>
        {STACK_FILLS.map((f) => (
          <span key={f} className="legend-swatch" style={{ background: f, marginRight: 0, borderRadius: 0 }} />
        ))}{' '}
        {translate("分项完整时堆叠（未缓存/缓存读/缓存写/输出）")}
      </span>
      <span>{translate("≥ 已知小计")}</span>
      <span>{translate("? 有记录·用量未知")}</span>
      <span>{translate("▨ 无记录 · 覆盖未知")}</span>
    </span>
  );
}
