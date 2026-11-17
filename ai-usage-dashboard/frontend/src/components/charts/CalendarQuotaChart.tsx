import { t as translate, useLanguage } from "../../i18n";
import type { QuotaSnapshot, QuotaWindow, QuotaWindowSummary } from '../../api/types';
import { boundarySourceText, slotTitle } from '../../domain/quota';
import { fmtDateTimeRel, fmtRangeLabel } from '../../time/tz';
import type { Clock } from '../common';
import { layoutLabels, type LabelSeg } from './labelLayout';
import { X0, X1, type TimeScale } from './scale';

const TOP = 22;
const BOTTOM = 170;

interface Props {
  summaries: QuotaWindowSummary[];
  /** 同范围窗口，只取 slot / 时长 / 边界；不用其 latest_snapshot */
  windows: QuotaWindow[];
  /** 仅日视图 */
  snapshots: QuotaSnapshot[] | null;
  scale: TimeScale;
  clock: Clock;
}

/**
 * 日 / 周 / 月的额度栏：每个窗口一段“所选范围内最高观测值”，五小时与七天分开画，
 * 不相加、不跨窗口连线；日视图另画原始观测点。
 */
export function CalendarQuotaChart({ summaries, windows, snapshots, scale, clock }: Props) {
  useLanguage();
  const byId = new Map(windows.map((w) => [w.id, w]));
  const yMax = Math.max(100, ...summaries.map((s) => s.max_observed_percent ?? 0), ...(snapshots ?? []).map((s) => s.used_percent ?? 0));
  const y = (v: number) => BOTTOM - (v / yMax) * (BOTTOM - TOP);
  const nowInside = clock.asOfMs > scale.from && clock.asOfMs < scale.to;
  const nowX = scale.x(clock.asOfMs);
  const t = (iso: string) => fmtDateTimeRel(iso, clock.asOfMs, clock.tz);

  const segs = summaries
    .map((s) => {
      const w = byId.get(s.window_id);
      const known = w?.starts_at && w.ends_at && w.start_source !== 'unknown' && w.end_source !== 'unknown';
      const a = known ? Date.parse(w!.starts_at!) : s.first_sample_at ? Date.parse(s.first_sample_at) : null;
      const b = known ? Date.parse(w!.ends_at!) : s.last_sample_at ? Date.parse(s.last_sample_at) : null;
      if (a === null || b === null) return null;
      const long = (w?.duration_seconds ?? 0) > 86400;
      return { s, w, known, a: scale.clamp(a), b: scale.clamp(b), long };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null)
    // 七天窗口先画（在下层），五小时窗口后画
    .sort((p, q) => Number(q.long) - Number(p.long));

  // 百分比标签：每个窗口一个，避让后放不下的收起到图下的“+N”列表（数据不合并、不相加）
  const labelSegs: (LabelSeg & { tipRange: string; percent: number })[] = segs
    .filter((g) => g.s.max_observed_percent !== null)
    .map((g) => {
      const x1 = scale.x(g.a);
      const v = g.s.max_observed_percent as number;
      return {
        id: g.s.window_id,
        x1,
        x2: Math.max(x1 + 4, scale.x(g.b)),
        y: y(v),
        text: g.long ? translate("七天 {0}%", v) : `${v}%`,
        long: g.long,
        percent: v,
        tipRange: `${g.long ? translate("七天") : translate("五小时")} · ${g.known ? fmtRangeLabel(g.w!.starts_at!, g.w!.ends_at!, clock.tz) : translate("边界未知")}`,
      };
    })
    // 越新的窗口越优先显示；同一时间短窗口优先
    .sort((p, q) => q.x2 - p.x2 || Number(p.long) - Number(q.long));
  const labels = layoutLabels(labelSegs, { left: X0, right: 998, top: 2, bottom: 188 });

  const desc = summaries.length
    ? translate("所选范围内 {0} 个额度窗口的最高观测值，各窗口分开显示，不相加", summaries.length)
    : translate("所选范围内没有额度观测");

  return (
    <>
    <svg className="chart-svg" viewBox="0 0 1000 190" role="img" aria-label={desc}>
      {nowInside && <rect x={nowX} y={14} width={X1 - nowX} height={160} fill="var(--future)" />}
      <line x1={X0} y1={BOTTOM} x2={X1} y2={BOTTOM} stroke="var(--border)" />
      {[50, 100].map((v) => (
        <line key={v} x1={X0} y1={y(v)} x2={X1} y2={y(v)} stroke="var(--grid)" />
      ))}
      {[0, 50, 100].map((v) => (
        <text key={v} x={30} y={y(v) + 4} fontSize={11} fill="var(--text-subtle)" textAnchor="end" className="mono">
          {v}
        </text>
      ))}

      {segs.map(({ s, w, known, a, b, long }) => {
        const x1 = scale.x(a);
        const x2 = Math.max(x1 + 4, scale.x(b));
        const v = s.max_observed_percent;
        const yy = v === null ? BOTTOM : y(v);
        const tip = [
          `${w ? slotTitle(w) : translate("窗口")}${w ? ` · ${w.slot}` : ''}`,
          known ? fmtRangeLabel(w!.starts_at!, w!.ends_at!, clock.tz) : translate("起止边界未知（按首末观测点画）"),
          w && known ? translate("开始：{0}；结束：{1}", boundarySourceText('start', w), boundarySourceText('end', w)) : '',
          v === null ? translate("所选范围内没有已知数值") : translate("所选范围内最高观测 {0}%（不是实际峰值或最终消耗）", v),
          translate("{0} 个观测点{1}", s.sample_count, s.first_sample_at && s.last_sample_at ? `：${t(s.first_sample_at)} – ${t(s.last_sample_at)}` : ''),
        ]
          .filter(Boolean)
          .join('\n');
        return (
          <g key={s.window_id}>
            <line
              x1={x1}
              y1={yy}
              x2={x2}
              y2={yy}
              stroke={long ? 'var(--line-derived)' : 'var(--accent)'}
              strokeWidth={long ? 2 : 5}
              strokeDasharray={long ? '6 4' : undefined}
              strokeLinecap="round"
            >
              <title>{tip}</title>
            </line>
          </g>
        );
      })}

      {(snapshots ?? [])
        .filter((p) => p.used_percent !== null)
        .map((p) => {
          const long = (byId.get(p.window_id)?.duration_seconds ?? 0) > 86400;
          return (
            <circle
              key={p.id}
              cx={scale.x(Date.parse(p.effective_at))}
              cy={y(p.used_percent as number)}
              r={2.5}
              fill={long ? 'var(--surface)' : 'var(--accent)'}
              stroke={long ? 'var(--line-derived)' : 'none'}
            >
              <title>{`${p.used_percent}% · ${p.time_basis === 'observed_at' ? translate("观测于") : translate("日志记录于")} ${t(p.effective_at)}`}</title>
            </circle>
          );
        })}

      {nowInside && <line x1={nowX} y1={10} x2={nowX} y2={174} stroke="var(--text)" />}

      {labels.placed.map((l) => {
        const long = (byId.get(l.id)?.duration_seconds ?? 0) > 86400;
        return (
          <text key={l.id} x={l.x} y={l.y} fontSize={11} fill={long ? 'var(--text-muted)' : 'var(--text)'} className="mono label-halo" pointerEvents="none">
            {l.text}
          </text>
        );
      })}
      {summaries.length === 0 && (
        <text x={(X0 + X1) / 2} y={100} fontSize={12} fill="var(--text-muted)" textAnchor="middle">
          {translate("所选范围内没有额度观测记录（不代表没有使用）")}
        </text>
      )}
    </svg>
    {labels.hidden.length > 0 && (
      <details className="chart-more">
        <summary>{translate("另有")} {labels.hidden.length} {translate("个窗口数值")}</summary>
        <ul>
          {labels.hidden.map((h) => (
            <li key={h.id} className="num">
              {(h as (typeof labelSegs)[number]).tipRange} · {`${(h as (typeof labelSegs)[number]).percent}%`}
            </li>
          ))}
        </ul>
      </details>
    )}
    </>
  );
}
