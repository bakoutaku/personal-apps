import { PRODUCTS_BY_PROVIDER, type Product, type Provider, type Source } from '../api/types';
import { coverageSummary, COVERAGE_TEXT, selectionConnection } from '../domain/sources';
import { fmtTokens, fmtTokensShort, summarizeActivity } from '../domain/usage';
import type { HistoryData } from '../state/loadDashboard';
import { CalendarQuotaChart } from './charts/CalendarQuotaChart';
import { LabelTrack } from './charts/LabelTrack';
import { calendarTicks, timeScale } from './charts/scale';
import { TokenBarChart, TokenLegend } from './charts/TokenBarChart';
import { FetchProblem, type Clock } from './common';
import { AddLabelButton } from './LabelButtons';

interface Props {
  history: HistoryData;
  clock: Clock;
  hasPool: boolean;
  sources: Source[];
  provider: Provider;
  products: Product[] | null;
  onSelect: (range: { from: string; to: string } | null) => void;
}

/** 日 / 周 / 月：上面额度最高观测值，下面 token 柱，共用时间轴。 */
export function CalendarHistory({ history, clock, hasPool, sources, provider, products, onSelect }: Props) {
  const cal = history.calendar!;
  const scale = timeScale(Date.parse(history.from), Date.parse(history.to));
  const axis = calendarTicks(cal.view, scale.from, scale.to, clock.tz);
  const unit = cal.bucket === 'hour' ? '小时' : '天';
  const { series, labels, sessions, quota } = history;

  return (
    <>
      <CalendarStats history={history} unit={unit} hasPool={hasPool} sources={sources} provider={provider} products={products} />
      <div className="chart-box">
        {hasPool && quota ? (
          <>
            <div className="chart-head">
              <span className="title">
                额度观测值 <span>各窗口在所选范围内的最高观测值 · %</span>
              </span>
              <span className="legend">
                <span>▬ 五小时窗口</span>
                <span>┅ 七天窗口</span>
                {quota.snapshots && <span>● 观测点</span>}
              </span>
            </div>
            {!quota.summaries.ok ? (
              <FetchProblem result={quota.summaries} what="额度最高观测值" />
            ) : !quota.windows.ok ? (
              <FetchProblem result={quota.windows} what="额度窗口" />
            ) : (
              <CalendarQuotaChart
                summaries={quota.summaries.data}
                windows={quota.windows.data}
                snapshots={quota.snapshots?.ok ? quota.snapshots.data : null}
                scale={scale}
                clock={clock}
              />
            )}
            <p className="small muted" style={{ margin: 0 }}>
              最高观测值是所选范围内记录到的最大值，不是实际峰值、最终消耗或用量总额；五小时与七天窗口分开显示，各窗口不相加，也不跨重置连线。
            </p>
          </>
        ) : (
          <div className="quota-off">
            <span>
              <strong>额度观测值</strong> · 未接入，不绘制
            </span>
            <span className="small">接入额度来源后，这里会出现各窗口的最高观测值</span>
          </div>
        )}

        <div className="chart-head" style={{ marginTop: 8 }}>
          <span className="title">
            token 用量 <span>每{unit} · 单位 token · 点柱子只看那一段的明细</span>
          </span>
          <TokenLegend />
        </div>
        {series.ok ? (
          <TokenBarChart
            series={series.data}
            scale={scale}
            clock={clock}
            axis={axis}
            selected={history.selection}
            onSelect={(from, to) => onSelect({ from, to })}
          />
        ) : (
          <FetchProblem result={series} what="token 用量" />
        )}

        <div className="chart-head" style={{ marginTop: 6 }}>
          <span className="title">
            任务标签 <span>按时间或会话关联，非精确消耗{history.selection ? ' · 添加时用选中的时间段' : ''}</span>
          </span>
          <AddLabelButton
            request={
              history.selection
                ? { mode: 'create-range', from: history.selection.from, to: history.selection.to }
                : { mode: 'create-range', from: history.from, to: new Date(Math.min(Date.parse(history.to), clock.asOfMs)).toISOString() }
            }
          />
        </div>
        {!labels.ok ? (
          <FetchProblem result={labels} what="标签" />
        ) : !sessions.ok ? (
          <FetchProblem result={sessions} what="会话" />
        ) : (
          <LabelTrack labels={labels.data} sessions={sessions.data} scale={scale} clock={clock} />
        )}
      </div>
    </>
  );
}

function CalendarStats({
  history,
  unit,
  hasPool,
  sources,
  provider,
  products,
}: {
  history: HistoryData;
  unit: string;
  hasPool: boolean;
  sources: Source[];
  provider: Provider;
  products: Product[] | null;
}) {
  if (!history.series.ok) return null;
  const buckets = history.series.data.buckets;
  const s = summarizeActivity(buckets, history.events.ok ? history.events.data.map((e) => e.occurred_at) : []);
  // as_of 切开的同一个桶算一个时段；只数已经过去的
  const past = new Set(buckets.filter((b) => b.record_state !== 'future').map((b) => b.from));
  const withRecords = new Set(buckets.filter((b) => b.record_state === 'observed').map((b) => b.from));
  const conn = selectionConnection(sources, provider, products, PRODUCTS_BY_PROVIDER);
  const own = sources.filter((x) => x.product && (products ?? PRODUCTS_BY_PROVIDER[provider]).includes(x.product) && x.connection_status !== 'not_configured');
  // 只看与当前范围重叠的覆盖声明；没有重叠就是覆盖未知（不能拿别的日期的覆盖来说这一段）
  const f = history.from;
  const t = history.to;
  const inRange = own.map((x) => ({ ...x, coverage: x.coverage.filter((c) => c.from < t && c.to > f) }));
  const cov = inRange.filter((x) => x.coverage.length > 0).map(coverageSummary);
  const base =
    cov.length === 0
      ? '覆盖未知'
      : `${cov.includes('gap') ? COVERAGE_TEXT.gap : cov.every((c) => c === 'complete') ? COVERAGE_TEXT.complete : COVERAGE_TEXT.partial}${
          inRange.every((x) => x.coverage.every((c) => c.scope === 'local_device')) ? ' · 仅本机' : ''
        }`;
  const coverageText = conn === 'none_configured' ? '所选产品未接入' : `${base}${conn === 'some_unconfigured' ? ' · 部分产品未接入' : ''}`;

  return (
    <div className="stats" role="group" aria-label="范围摘要">
      <div className="stat">
        <span className="eyebrow">token {s.unknownEvents > 0 ? '已知小计' : '已知合计'}</span>
        <b className="num" title={s.knownTotal !== null ? `${fmtTokens(s.knownTotal)} token` : undefined}>
          {s.knownTotal === null ? '—' : fmtTokensShort(s.knownTotal)}
        </b>
        {s.unknownEvents > 0 && <span className="small muted">另有 {s.unknownEvents} 条用量未知</span>}
      </div>
      <div className="stat">
        <span className="eyebrow">有记录的{unit}</span>
        <b className="num">
          {withRecords.size} / {past.size}
        </b>
        <span className="small muted">只数已过去的{unit}</span>
      </div>
      <div className="stat">
        <span className="eyebrow">记录 · 会话</span>
        <b className="num">
          {s.eventCount} · {history.sessions.ok ? history.sessions.data.length : '—'}
        </b>
      </div>
      {hasPool && history.quota?.summaries.ok && (
        <div className="stat">
          <span className="eyebrow">有观测的额度窗口</span>
          <b className="num">{history.quota.summaries.data.length} 个</b>
        </div>
      )}
      <div className="stat">
        <span className="eyebrow">覆盖</span>
        <span className="stat-text">{coverageText}</span>
      </div>
    </div>
  );
}
