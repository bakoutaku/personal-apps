import type { QuotaSnapshot, QuotaWindow } from '../../api/types';
import { snapshotTimeLabel } from '../../domain/quota';
import { fmtTime } from '../../time/tz';
import type { Clock } from '../common';
import { X0, X1, type TimeScale } from './scale';

const TOP = 20;
const BOTTOM = 170;

interface Props {
  window: QuotaWindow;
  snapshots: QuotaSnapshot[];
  scale: TimeScale;
  clock: Clock;
}

/** 额度观测值：只在观测点画点；虚线是“上次观测值”，不跨窗口、不延伸到未来。 */
export function QuotaObsChart({ window: w, snapshots, scale, clock }: Props) {
  const pts = snapshots
    .filter((s) => s.window_id === w.id)
    .sort((a, b) => Date.parse(a.effective_at) - Date.parse(b.effective_at));
  const known = pts.filter((s) => s.used_percent !== null);
  const yMax = Math.max(100, ...known.map((s) => s.used_percent as number));
  const y = (v: number) => BOTTOM - (v / yMax) * (BOTTOM - TOP);
  const nowX = scale.x(clock.asOfMs);
  const nowInside = clock.asOfMs > scale.from && clock.asOfMs < scale.to;
  const stepEnd = Math.min(clock.asOfMs, scale.to);
  // 过时：最后一段不延伸到现在，改画“之后没有新记录”的斜线区。
  const stale = w.status === 'current' && w.freshness === 'stale';

  let path = '';
  known.forEach((s, i) => {
    const t = Date.parse(s.effective_at);
    const next = known[i + 1];
    const endT = next ? Date.parse(next.effective_at) : stale ? t : stepEnd;
    const yy = y(s.used_percent as number);
    // 只画水平段，不画竖向连接，避免暗示两次观测之间的变化过程。
    path += `M${scale.x(t)} ${yy} H${scale.x(endT)} `;
  });
  const last = known.at(-1);
  const lastT = last ? Date.parse(last.effective_at) : null;
  const startLine = w.start_source === 'unknown' || !w.starts_at ? null : w.start_source;
  const endLine = w.end_source === 'unknown' || !w.ends_at ? null : w.end_source;
  const desc = known.length
    ? `窗口内 ${known.length} 个额度观测点，从 ${known[0]!.used_percent}% 到 ${last!.used_percent}%`
    : '窗口内没有额度观测点';

  return (
    <svg className="chart-svg" viewBox="0 0 1000 190" role="img" aria-label={desc}>
      <defs>
        <pattern id="hatch-stale" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="8" stroke="var(--track)" strokeWidth="2" />
        </pattern>
      </defs>
      {nowInside && <rect x={nowX} y={14} width={X1 - nowX} height={160} fill="var(--future)" />}
      {stale && lastT !== null && scale.x(stepEnd) - scale.x(lastT) > 1 && (
        <g>
          <rect x={scale.x(lastT)} y={14} width={scale.x(stepEnd) - scale.x(lastT)} height={156} fill="url(#hatch-stale)">
            <title>最近一次记录之后没有新的额度记录</title>
          </rect>
          {scale.x(stepEnd) - scale.x(lastT) > 120 && (
            <text x={(scale.x(lastT) + scale.x(stepEnd)) / 2} y={40} fontSize={12} fill="var(--accent-strong)" textAnchor="middle">
              之后没有新记录
            </text>
          )}
        </g>
      )}
      <line x1={X0} y1={BOTTOM} x2={X1} y2={BOTTOM} stroke="var(--border)" />
      {[50, 100].map((v) => (
        <line key={v} x1={X0} y1={y(v)} x2={X1} y2={y(v)} stroke="var(--grid)" />
      ))}
      {[0, 50, 100].map((v) => (
        <text key={v} x={30} y={y(v) + 4} fontSize={11} fill="var(--text-subtle)" textAnchor="end" className="mono">
          {v}
        </text>
      ))}
      {startLine && (
        <>
          <line x1={X0} y1={10} x2={X0} y2={174} stroke={startLine === 'reported' ? 'var(--accent)' : 'var(--line-derived)'} strokeWidth={startLine === 'reported' ? 1.5 : 1} strokeDasharray={startLine === 'derived' ? '4 4' : undefined} />
          <text x={X0 + 6} y={10} fontSize={11} fill="var(--text-muted)">
            开始（{startLine === 'reported' ? '报告' : '推导'}）
          </text>
        </>
      )}
      {endLine && (
        <>
          <line x1={X1} y1={10} x2={X1} y2={174} stroke={endLine === 'reported' ? 'var(--accent)' : 'var(--line-derived)'} strokeWidth={endLine === 'reported' ? 1.5 : 1} strokeDasharray={endLine === 'derived' ? '4 4' : undefined} />
          <text x={X1 - 6} y={10} fontSize={11} fill="var(--accent-strong)" textAnchor="end">
            重置（{endLine === 'reported' ? '报告' : '推导'}）
          </text>
        </>
      )}
      {nowInside && (
        <>
          <line x1={nowX} y1={10} x2={nowX} y2={174} stroke="var(--text)" />
          <text x={nowX + 6} y={24} fontSize={11} fill="var(--text)">
            现在 {fmtTime(clock.asOfMs, clock.tz)}
          </text>
          {X1 - nowX > 80 && (
            <text x={(nowX + X1) / 2} y={100} fontSize={12} fill="var(--text-muted)" textAnchor="middle">
              尚未发生
            </text>
          )}
        </>
      )}
      <path d={path} fill="none" stroke="var(--bar)" strokeWidth={2} strokeDasharray="5 5" />
      {pts.map((s) => {
        const cx = scale.x(Date.parse(s.effective_at));
        const tip = `${s.used_percent === null ? '百分比未知' : `${s.used_percent}%`} · ${snapshotTimeLabel(s)} ${fmtTime(s.effective_at, clock.tz)}`;
        if (s.used_percent === null) {
          return (
            <circle key={s.id} cx={cx} cy={BOTTOM} r={4} fill="var(--surface)" stroke="var(--text-subtle)" strokeWidth={1.5}>
              <title>{tip}</title>
            </circle>
          );
        }
        const isLast = s === last;
        return (
          <circle key={s.id} cx={cx} cy={y(s.used_percent)} r={isLast ? 6 : 5} fill="var(--accent)" stroke={isLast ? '#fff' : undefined} strokeWidth={isLast ? 2 : undefined}>
            <title>{tip}</title>
          </circle>
        );
      })}
      {last && (
        <text x={scale.x(Date.parse(last.effective_at))} y={y(last.used_percent as number) - 13} fontSize={12} fill="var(--text)" textAnchor="middle" className="mono">
          {last.used_percent}%
        </text>
      )}
    </svg>
  );
}
