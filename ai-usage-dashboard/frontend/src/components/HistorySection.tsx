import { PRODUCTS_BY_PROVIDER, type Product, type Provider, type QuotaWindow, type Source } from '../api/types';
import { selectionConnection } from '../domain/sources';
import { hasFullBounds, overlappingCandidates } from '../domain/quota';
import type { View } from '../route/hash';
import type { HistoryData } from '../state/loadDashboard';
import { calendarRange, fmtDate, fmtTime, fmtWeekday, localDateKey, shiftDateKey, type CalendarView } from '../time/tz';
import { CalendarHistory } from './CalendarHistory';
import { LabelTrack } from './charts/LabelTrack';
import { QuotaObsChart } from './charts/QuotaObsChart';
import { timeScale } from './charts/scale';
import { TokenBarChart, TokenLegend } from './charts/TokenBarChart';
import { ActivitySummaryCard } from './ActivitySummaryCard';
import { FetchProblem, type Clock } from './common';
import { HistoryExplainer } from './HistoryExplainer';
import { AddLabelButton } from './LabelButtons';

const LATER: { view: View; label: string; ready: boolean }[] = [
  { view: 'day', label: '日', ready: true },
  { view: 'week', label: '周', ready: true },
  { view: 'month', label: '月', ready: true },
];

const isCal = (v: View): v is CalendarView => v === 'day' || v === 'week' || v === 'month';

/** 有额度池时才有“五小时窗口”视图；最近五小时活动对任何供应商都可用。 */
function tabsFor(hasPool: boolean) {
  return [
    ...(hasPool ? [{ view: 'window' as View, label: '五小时窗口', ready: true }] : []),
    { view: 'recent5h' as View, label: '最近五小时', ready: true },
    ...LATER,
  ];
}

interface Props {
  view: View;
  selectedWindow: QuotaWindow | null;
  history: HistoryData | null;
  clock: Clock;
  sources: Source[];
  providerLabel: string;
  /** 本次查询到的全部窗口（用于提示重叠候选） */
  windows: QuotaWindow[];
  provider: Provider;
  /** 是否有已知额度池（没有时不提供额度窗口视图） */
  hasPool: boolean;
  products: Product[] | null;
  /** 日历视图换日期（null = 回到今天） */
  onDate: (key: string | null) => void;
  /** 在图上选时间段 / 清除 */
  onSelect: (range: { from: string; to: string } | null) => void;
  onView: (v: View) => void;
  onWindow: (id: string) => void;
}

export function HistorySection({
  view,
  selectedWindow,
  history,
  clock,
  sources,
  providerLabel,
  windows,
  provider,
  hasPool,
  products,
  onView,
  onWindow,
  onDate,
  onSelect,
}: Props) {
  const cal = history?.kind === 'calendar' ? history.calendar : null;
  const todayKey = localDateKey(clock.asOfMs, clock.tz);
  const calTitle = (() => {
    if (!cal || !history) return null;
    const f = Date.parse(history.from);
    if (cal.view === 'day') return `${fmtDate(f, clock.tz)} ${fmtWeekday(f, clock.tz)}${cal.dateKey === todayKey ? ' · 今天' : ''}`;
    if (cal.view === 'week') return `${fmtDate(f, clock.tz)} – ${fmtDate(Date.parse(history.to) - 1, clock.tz)}`;
    return `${cal.dateKey.slice(0, 4)} 年 ${Number(cal.dateKey.slice(5, 7))} 月`;
  })();
  // 下一段整段都在 as_of 之后时不让翻过去（未来没有数据）
  const nextDisabled = cal ? calendarRange(cal.view, shiftDateKey(cal.dateKey, cal.view, 1), clock.tz).from > clock.asOfMs : true;
  const w = view === 'window' ? (history?.window ?? selectedWindow) : null;
  // 前后导航只是同槽位的已知边界记录，可能指向时间重叠的另一条记录，而不是相邻的重置周期。
  const overlapIds = new Set(w ? overlappingCandidates(windows, w).map((x) => x.id) : []);
  const navTitle = (dir: '上' | '下', target: string | null | undefined) =>
    !target
      ? `没有同槽位${dir}一条窗口记录`
      : overlapIds.has(target)
        ? `同槽位另一条时间重叠的窗口记录（不是${dir}一个重置周期）`
        : `同槽位${dir}一条已知边界的窗口记录；不保证与当前窗口首尾相接`;
  const title =
    view === 'window' && w?.starts_at && w.ends_at
      ? `${fmtDate(w.starts_at, clock.tz)} ${fmtTime(w.starts_at, clock.tz)} – ${fmtTime(w.ends_at, clock.tz)}`
      : view === 'recent5h' && history
        ? `${fmtDate(history.from, clock.tz)} ${fmtTime(history.from, clock.tz)} – ${fmtTime(history.to, clock.tz)}`
        : null;
  const heading =
    view === 'window' ? '额度窗口' : view === 'recent5h' ? '最近五小时活动' : view === 'day' ? '自然日' : view === 'week' ? '自然周' : '自然月';

  return (
    <section className="section" aria-labelledby="history-h">
      <div className="section-head">
        <div>
          <div className="eyebrow">02 · 历史</div>
          <h2 id="history-h">
            {heading} {(title ?? calTitle) && <span className="num">{title ?? calTitle}</span>}
            {view === 'recent5h' && (
              <span className="badge" style={{ marginLeft: 10, verticalAlign: 'middle' }}>
                非额度窗口
              </span>
            )}
          </h2>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div role="tablist" aria-label="时间视图" className="tabs">
            {tabsFor(hasPool).map((t) => (
              <button
                key={t.view}
                type="button"
                role="tab"
                className="tab"
                aria-selected={view === t.view}
                disabled={!t.ready}
                title={t.ready ? undefined : '尚未实现'}
                onClick={() => onView(t.view)}
              >
                {t.label}
                {!t.ready && <span className="small"> · 未实现</span>}
              </button>
            ))}
          </div>
          {cal && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <button type="button" className="ibtn" aria-label={`上一${cal.view === 'day' ? '天' : cal.view === 'week' ? '周' : '个月'}`} onClick={() => onDate(shiftDateKey(cal.dateKey, cal.view, -1))}>
                <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M15 6l-6 6 6 6" />
                </svg>
              </button>
              <button type="button" className="ibtn" aria-label={`下一${cal.view === 'day' ? '天' : cal.view === 'week' ? '周' : '个月'}`} disabled={nextDisabled} onClick={() => onDate(shiftDateKey(cal.dateKey, cal.view, 1))}>
                <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </button>
              {cal.dateKey !== todayKey && calendarRange(cal.view, cal.dateKey, clock.tz).to <= clock.asOfMs && (
                <button type="button" className="text-btn" onClick={() => onDate(null)}>
                  回到今天
                </button>
              )}
            </div>
          )}
          {view === 'window' && (
            <div style={{ display: 'flex', gap: 6 }}>
              <button type="button" className="ibtn" aria-label="同槽位上一条窗口记录" title={navTitle('上', w?.previous_window_id)} disabled={!w?.previous_window_id} onClick={() => w?.previous_window_id && onWindow(w.previous_window_id)}>
                <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M15 6l-6 6 6 6" />
                </svg>
              </button>
              <button type="button" className="ibtn" aria-label="同槽位下一条窗口记录" title={navTitle('下', w?.next_window_id)} disabled={!w?.next_window_id} onClick={() => w?.next_window_id && onWindow(w.next_window_id)}>
                <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </button>
            </div>
          )}
        </div>
      </div>

      {view === 'window' && w && overlappingCandidates(windows, w).length > 0 && (
        <div className="notice" role="note">
          同一槽位还有 {overlappingCandidates(windows, w).length} 条边界不同、时间重叠的窗口记录。这里只画所选记录（{w.id}）的观测点，不跨记录连线，也不把它们当作连续的重置周期。
        </div>
      )}

      {view === 'recent5h' ? (
        history?.kind === 'recent5h' ? (
          <>
            {hasPool && (
              <div className="cards">
                <ActivitySummaryCard history={history} clock={clock} connection={selectionConnection(sources, provider, products, PRODUCTS_BY_PROVIDER)} />
              </div>
            )}
            <UsageCharts history={history} clock={clock} hasPool={hasPool} />
          </>
        ) : null
      ) : isCal(view) ? (
        history?.kind === 'calendar' ? (
          <CalendarHistory history={history} clock={clock} hasPool={hasPool} sources={sources} provider={provider} products={products} onSelect={onSelect} />
        ) : null
      ) : !hasPool ? (
        <div className="placeholder">
          没有已知额度池，不能按额度窗口查看，也不会为只有 token 的来源生成额度窗口。
          <div style={{ marginTop: 12 }}>
            <button type="button" className="btn-primary" onClick={() => onView('recent5h')}>
              看最近五小时活动
            </button>
          </div>
        </div>
      ) : !w ? (
        <div className="placeholder">
          没有边界完整的当前额度窗口，所以不画窗口时间轴，也不把旧窗口当作当前窗口。
          <HistoryExplainer sources={sources} providerLabel={providerLabel} clock={clock} />
        </div>
      ) : !hasFullBounds(w) || !history ? (
        <div className="placeholder">这个窗口的起止边界未知，不能画窗口时间轴；记录仍会在明细中出现。</div>
      ) : (
        <UsageCharts history={history} clock={clock} hasPool={hasPool} />
      )}
    </section>
  );
}

/** 额度观测（仅额度窗口视图）+ token 用量 + 标签，共用同一条时间轴。 */
function UsageCharts({ history, clock, hasPool }: { history: HistoryData; clock: Clock; hasPool: boolean }) {
  const scale = timeScale(Date.parse(history.from), Date.parse(history.to));
  const { snapshots, series, labels, sessions } = history;
  return (
    <div className="chart-box">
      {history.kind === 'window' && history.window && snapshots ? (
        <>
          <div className="chart-head">
            <span className="title">
              额度观测值 <span>%</span>
            </span>
            <span className="legend">
              <span>
                <span className="dot d-ok" /> 观测点
              </span>
              <span>┄ 上次观测值（不代表期间确认不变）</span>
            </span>
          </div>
          {snapshots.ok ? (
            <QuotaObsChart window={history.window} snapshots={snapshots.data} scale={scale} clock={clock} />
          ) : (
            <FetchProblem result={snapshots} what="额度快照" />
          )}
        </>
      ) : (
        <div className="quota-off">
          <span>
            <strong>额度观测值</strong> · {hasPool ? '这是活动范围，不是额度窗口，不绘制' : '未接入，不绘制'}
          </span>
          <span className="small">{hasPool ? '额度观测请看“五小时窗口”视图' : '接入额度来源后，这里会出现额度折线，与下方用量共用时间轴'}</span>
        </div>
      )}

      <div className="chart-head" style={{ marginTop: 8 }}>
        <span className="title">
          token 用量 <span>每 15 分钟 · 单位 token · 不是订阅额度或费用</span>
        </span>
        <TokenLegend />
      </div>
      {series.ok ? <TokenBarChart series={series.data} scale={scale} clock={clock} /> : <FetchProblem result={series} what="token 用量" />}

      <div className="chart-head" style={{ marginTop: 6 }}>
        <span className="title">
          任务标签 <span>按时间或会话关联，非精确消耗</span>
        </span>
        <AddLabelButton
          request={{
            mode: 'create-range',
            from: history.from,
            to: new Date(Math.min(Date.parse(history.to), clock.asOfMs)).toISOString(),
          }}
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
  );
}
