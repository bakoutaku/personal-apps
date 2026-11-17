import { PRODUCTS_BY_PROVIDER, type Product, type Provider, type Source } from '../api/types';
import { selectionConnection } from '../domain/sources';
import { hasFullBounds } from '../domain/quota';
import { fmtTokens, fmtTokensShort, summarizeActivity } from '../domain/usage';
import type { View } from '../route/hash';
import type { DashboardData, HistoryData } from '../state/loadDashboard';
import { calendarRange, fmtDate, fmtTime, fmtWeekday, localDateKey, shiftDateKey, type CalendarView } from '../time/tz';
import { CalendarQuotaChart } from './charts/CalendarQuotaChart';
import { QuotaObsChart } from './charts/QuotaObsChart';
import { calendarTicks, timeScale } from './charts/scale';
import { TokenBarChart } from './charts/TokenBarChart';
import { FetchProblem, type Clock } from './common';

export type ChartType = 'bar' | 'line';

const isCal = (v: View): v is CalendarView => v === 'day' || v === 'week' || v === 'month';

const TABS: { view: View; label: string; poolOnly?: boolean }[] = [
  { view: 'window', label: '额度窗口', poolOnly: true },
  { view: 'recent5h', label: '近五小时' },
  { view: 'day', label: '日' },
  { view: 'week', label: '周' },
  { view: 'month', label: '月' },
];

interface Props {
  provider: Provider;
  view: View;
  /** 路由里的锚定日期（null = 今天） */
  date: string | null;
  products: Product[] | null;
  /** 当前范围的数据；null = 正在读取（不拿上一范围的数据配新日期） */
  data: DashboardData | null;
  /** 控件用的时钟（读取中沿用上一次） */
  clock: Clock;
  hasPool: boolean;
  chartType: ChartType;
  /** 首次读取失败等：图表区只显示这个 */
  failure?: React.ReactNode;
  onChartType: (t: ChartType) => void;
  onView: (v: View) => void;
  onDate: (key: string | null) => void;
  /** 点柱子 / 时段 → 带筛选的明细页；null = 不筛选 */
  onDetails: (range: { from: string; to: string } | null) => void;
  /** 到二级页面（额度 / 数据来源） */
  onPage: (page: 'quota' | 'sources') => void;
}

/**
 * 首页：只有时间范围切换、折线/柱状切换、主图和立绘。
 * 读取新范围时控件和图表区高度保持不变，只在图表区内显示读取中（不卸载整页，避免浏览器把滚动钳回顶部）。
 */
export function HomeView(p: Props) {
  const { view, clock, data } = p;
  const history = data?.history ?? null;
  const todayKey = localDateKey(clock.asOfMs, clock.tz);
  const cal = isCal(view) ? view : null;
  const dateKey = history?.calendar?.dateKey ?? p.date ?? todayKey;
  const nextDisabled = cal ? calendarRange(cal, shiftDateKey(dateKey, cal, 1), clock.tz).from > clock.asOfMs : true;
  const unitWord = cal === 'day' ? '天' : cal === 'week' ? '周' : '个月';

  const title = (() => {
    if (cal) {
      const r = calendarRange(cal, dateKey, clock.tz);
      if (cal === 'day') return `${fmtDate(r.from, clock.tz)} ${fmtWeekday(r.from, clock.tz)}${dateKey === todayKey ? ' · 今天' : ''}`;
      if (cal === 'week') return `${fmtDate(r.from, clock.tz)} – ${fmtDate(r.to - 1, clock.tz)}`;
      return `${dateKey.slice(0, 4)} 年 ${Number(dateKey.slice(5, 7))} 月`;
    }
    if (!history) return '';
    return `${fmtDate(history.from, clock.tz)} ${fmtTime(history.from, clock.tz)} – ${fmtTime(history.to, clock.tz)}`;
  })();

  return (
    <section className="home" aria-labelledby="home-h">
      <div className="home-controls">
        <h1 id="home-h" className="home-title num">
          {title || ' '}
        </h1>
        <div className="home-ctl">
          <div role="tablist" aria-label="时间范围" className="tabs">
            {TABS.filter((t) => !t.poolOnly || p.hasPool).map((t) => (
              <button key={t.view} type="button" role="tab" className="tab" aria-selected={view === t.view} onClick={() => p.onView(t.view)}>
                {t.label}
              </button>
            ))}
          </div>
          {cal && (
            <div className="date-nav">
              <button type="button" className="ibtn" aria-label={`上一${unitWord}`} onClick={() => p.onDate(shiftDateKey(dateKey, cal, -1))}>
                <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M15 6l-6 6 6 6" />
                </svg>
              </button>
              <button type="button" className="ibtn" aria-label={`下一${unitWord}`} disabled={nextDisabled} onClick={() => p.onDate(shiftDateKey(dateKey, cal, 1))}>
                <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </button>
              <button type="button" className="text-btn" onClick={() => p.onDate(null)} disabled={dateKey === todayKey} aria-label="回到今天">
                今天
              </button>
            </div>
          )}
          <div role="radiogroup" aria-label="图表类型" className="seg">
            {(['bar', 'line'] as const).map((t) => (
              <button key={t} type="button" role="radio" aria-checked={p.chartType === t} className="seg-btn" onClick={() => p.onChartType(t)}>
                {t === 'bar' ? '柱状' : '折线'}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className={p.provider === "claude" ? "stage with-art" : "stage"}>
        <div className="stage-chart">
          {p.failure ? (
            p.failure
          ) : !data ? (
            <div className="stage-loading" aria-busy="true">
              正在读取…
            </div>
          ) : (
            <HomeChart {...p} data={data} history={history} />
          )}
        </div>
        {p.provider === 'claude' && (
          <div className="character" aria-hidden="true">
            <img src={`${import.meta.env.BASE_URL}characters/claude-chibi.png`} alt="" decoding="async" draggable={false} />
          </div>
        )}
      </div>
    </section>
  );
}

function HomeChart(p: Props & { data: DashboardData; history: HistoryData | null }) {
  const { history, clock, data } = p;
  const sources: Source[] = data.sources.ok ? data.sources.data : [];
  const conn = selectionConnection(sources, p.provider, p.products, PRODUCTS_BY_PROVIDER);

  if (!history) {
    // 额度窗口视图但没有边界完整的当前窗口 / 没有额度池：简短说明，详情放二级页
    return (
      <div className="stage-empty">
        <p>{p.hasPool ? '没有边界完整的当前额度窗口，不画窗口图。' : '这个供应商没有已接入的额度来源。'}</p>
        <div className="stage-actions">
          <button type="button" className="btn-primary" onClick={() => p.onView('day')}>
            看今天的用量
          </button>
          {p.hasPool && (
            <button type="button" className="text-btn" onClick={() => p.onPage('quota')}>
              额度详情
            </button>
          )}
        </div>
      </div>
    );
  }
  if (history.kind === 'window' && (!history.window || !hasFullBounds(history.window))) {
    return (
      <div className="stage-empty">
        <p>这个窗口的起止边界未知，不画窗口图。</p>
        <button type="button" className="text-btn" onClick={() => p.onPage('quota')}>
          额度详情
        </button>
      </div>
    );
  }

  const scale = timeScale(Date.parse(history.from), Date.parse(history.to));
  const cal = history.calendar;
  const axis = cal ? calendarTicks(cal.view, scale.from, scale.to, clock.tz) : undefined;
  const unit = cal ? (cal.bucket === 'hour' ? '每小时' : '每天') : '每 15 分钟';
  const { series } = history;
  const summary = series.ok ? summarizeActivity(series.data.buckets, history.events.ok ? history.events.data.map((e) => e.occurred_at) : []) : null;
  const empty = summary && summary.eventCount === 0;
  const quota = cal && p.hasPool ? history.quota : null;
  const showQuotaWindow = history.kind === 'window' && !!history.window && !!history.snapshots?.ok;
  const showQuotaCal = !!(quota?.summaries.ok && quota.windows.ok && quota.summaries.data.length > 0);

  return (
    <>
      {showQuotaWindow && history.window && history.snapshots?.ok && (
        <div className="stage-sub">
          <div className="chart-head">
            <span className="title">额度 · %</span>
          </div>
          <QuotaObsChart window={history.window} snapshots={history.snapshots.data} scale={scale} clock={clock} />
        </div>
      )}
      {showQuotaCal && quota?.summaries.ok && quota.windows.ok && (
        <div className="stage-sub">
          <div className="chart-head">
            <span className="title">额度 · %</span>
            <span className="legend">
              <span>▬ 五小时</span>
              <span>┅ 七天</span>
            </span>
          </div>
          <CalendarQuotaChart summaries={quota.summaries.data} windows={quota.windows.data} snapshots={quota.snapshots?.ok ? quota.snapshots.data : null} scale={scale} clock={clock} />
        </div>
      )}
      <div className="chart-head">
        <span className="title" title={`${unit}一格 · 单位 token`}>用量 · token</span>
        <HomeLegend unit={unit} quota={showQuotaWindow || showQuotaCal} calendar={!!cal} />
      </div>
      {series.ok ? (
        <div className="stage-main">
          <TokenBarChart
            series={series.data}
            scale={scale}
            clock={clock}
            axis={axis}
            variant={p.chartType}
            // 上面没有额度图时，token 图独占图表区
            plotHeight={showQuotaWindow || showQuotaCal ? 170 : 300}
            quiet
            selected={null}
            onSelect={cal ? (from, to) => p.onDetails({ from, to }) : undefined}
          />
          {empty && (
            <div className="stage-overlay" role="status">
              {conn === 'none_configured'
                ? '所选产品未接入'
                : view5h(p.view)
                  ? '近五小时没有记录（不等于没有使用）'
                  : '这段时间没有记录（不等于没有使用）'}
              {view5h(p.view) && (
                <button type="button" className="text-btn" onClick={() => p.onView('day')}>
                  看今天
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        <FetchProblem result={series} what="token 用量" />
      )}
      <div className="stage-foot small">
        {summary && (
          <span className="num" title={summary.unknownEvents > 0 ? `已知小计：另有 ${summary.unknownEvents} 条记录用量未知，没有计入` : summary.knownTotal !== null ? `${fmtTokens(summary.knownTotal)} token` : undefined}>
            {summary.knownTotal !== null && (
              <>
                {summary.unknownEvents > 0 && '≥ '}
                <b>{fmtTokensShort(summary.knownTotal)}</b> token ·{' '}
              </>
            )}
            {summary.eventCount} 条
          </span>
        )}
        {conn === 'some_unconfigured' && (
          <a className="status-mini" href="#" onClick={(e) => { e.preventDefault(); p.onPage('sources'); }} title="部分产品未接入，只统计已接入的来源；详见数据来源" aria-label="部分产品未接入，查看数据来源">
            <span className="dot d-part" aria-hidden="true" /> 部分未接入
          </a>
        )}
        <button type="button" className="text-btn" onClick={() => p.onDetails(null)} title={cal ? '点图上的柱子可只看那一段' : undefined}>
          明细 →
        </button>
      </div>
    </>
  );
}

const view5h = (v: View) => v === 'recent5h';

/** 小型“图例”入口：长解释放在这里，键盘 / 点按都能打开，默认收起。 */
function HomeLegend({ unit, quota, calendar }: { unit: string; quota: boolean; calendar: boolean }) {
  return (
    <details className="legend-pop">
      <summary>图例</summary>
      <div className="legend-body" role="note">
        {quota && (
          <ul>
            <li>额度：▬ 五小时窗口、┅ 七天窗口，各窗口分开画，不相加、不跨重置连线。</li>
            {calendar && <li>日 / 周 / 月里每段是该窗口在所选范围内的最高观测值，不是实际峰值或最终消耗。</li>}
            <li>拥挤时部分百分比标签收起到图下列表，悬停线段可看详情。</li>
          </ul>
        )}
        <ul>
          <li>用量：{unit}一格，单位 token；不是订阅额度，不能换算成百分比。</li>
          <li>
            <span className="legend-swatch hatch" /> 斜线：没有记录，不计为 0（覆盖未知）。
          </li>
          <li>? 有记录但用量未知；≥ 已知小计（部分记录用量未知）。</li>
          <li>灰底：尚未发生的时间。</li>
          {calendar && <li>点柱子打开只含那一段的明细。</li>}
        </ul>
      </div>
    </details>
  );
}
