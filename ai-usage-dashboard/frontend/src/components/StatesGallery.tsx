// 仅 mock：把 contracts/mocks/states/ 下每份局部状态样本单独画出来。
// 每份样本只是一份响应，不是整屏场景，所以逐块展示，不拼进主页面。
import { useEffect, useState } from 'react';
import type { Fetched } from '../api/adapter';
import { MockAdapter, stateFixtures, type CatalogFixture } from '../api/mockAdapter';
import type { QuotaWindow, QuotaWindowSummary, Source, UsageSeries } from '../api/types';
import { hasFullBounds } from '../domain/quota';
import { fmtDateTimeRel } from '../time/tz';
import { CalendarQuotaChart } from './charts/CalendarQuotaChart';
import { QuotaObsChart } from './charts/QuotaObsChart';
import { timeScale } from './charts/scale';
import { TokenBarChart, TokenLegend } from './charts/TokenBarChart';
import { FetchProblem, type Clock } from './common';
import { QuotaCards } from './QuotaSection';
import { SourcesTable } from './SourcesTable';
import { FailureBars, StaleBar } from './StateBars';

interface Loaded {
  entry: CatalogFixture;
  result: Fetched<unknown>;
}

/** 状态样本的阅读顺序：先额度，再来源，最后用量。 */
const ORDER = ['WindowsResponse', 'SourcesResponse', 'SeriesResponse'];

export function StatesGallery() {
  const [items, setItems] = useState<Loaded[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    const entries = [...stateFixtures()].sort((a, b) => ORDER.indexOf(a.schema) - ORDER.indexOf(b.schema));
    Promise.all(
      entries.map(async (entry) => ({
        entry,
        result: await new MockAdapter({ scenarioId: entry.scenario_id }).getCatalogEntry(entry),
      })),
    ).then((r) => {
      if (!cancelled) setItems(r);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="section" aria-labelledby="states-h">
      <div className="section-head">
        <div>
          <div className="eyebrow">仅模拟数据 · 状态样例</div>
          <h2 id="states-h">局部状态示例</h2>
          <p className="section-note">
            下面每一块只来自 contracts/mocks/states/ 里的一份响应，查询范围和主页面不同，不是整屏场景，也不和主页面数据拼接。
            <br />
            <a href="#/gpt">← 回到主页面</a>
          </p>
        </div>
      </div>
      {items === null ? (
        <div className="placeholder" aria-busy="true">
          正在读取状态样本…
        </div>
      ) : (
        <>
          <CrowdedQuotaLabels />
          {items.map((it) => <StatePanel key={it.entry.scenario_id + it.entry.file} item={it} />)}
        </>
      )}
    </section>
  );
}

function StatePanel({ item }: { item: Loaded }) {
  const { entry, result } = item;
  return (
    <article className="chart-box" aria-label={`场景 ${entry.scenario_id}`}>
      <div className="chart-head">
        <span className="title">
          场景 <span className="num">{entry.scenario_id}</span>
        </span>
        <span className="small muted num">{entry.file}</span>
      </div>
      {entry.note && <p className="small muted" style={{ margin: 0 }}>样本说明：{entry.note}</p>}
      {!result.ok ? (
        <FetchProblem result={result} what="状态样本" />
      ) : (
        <StateBody schema={entry.schema} result={result} />
      )}
    </article>
  );
}

function StateBody({ schema, result }: { schema: string; result: Fetched<unknown> & { ok: true } }) {
  const data = result.data;
  const clock: Clock = { tz: result.meta.timezone, asOfMs: Date.parse(result.meta.as_of) };
  const staleAfter = result.meta.stale_after_seconds;
  if (schema === 'WindowsResponse') {
    const windows = data as QuotaWindow[];
    return (
      <>
        <StaleBar windows={windows} staleAfterSeconds={staleAfter} clock={clock} />
        <QuotaCards windows={windows} sources={[]} staleAfterSeconds={staleAfter} clock={clock} />
        {windows
          .filter((w) => hasFullBounds(w) && w.latest_snapshot)
          .map((w) => (
            <div key={w.id}>
              <p className="small muted" style={{ margin: '4px 0' }}>
                窗口时间轴（样本只提供窗口和最新快照，所以只有一个观测点）
              </p>
              <QuotaObsChart window={w} snapshots={[w.latest_snapshot!]} scale={timeScale(Date.parse(w.starts_at!), Date.parse(w.ends_at!))} clock={clock} />
            </div>
          ))}
        {windows.some((w) => !hasFullBounds(w)) && (
          <div className="placeholder">起止边界未知的窗口不画时间轴、不参与前后翻页；记录仍在明细中显示。</div>
        )}
      </>
    );
  }
  if (schema === 'SourcesResponse') {
    const sources = data as Source[];
    const label = sources[0]?.provider === 'claude' ? 'Claude' : 'GPT';
    return (
      <>
        <FailureBars sources={sources} providerLabel={label} clock={clock} />
        <SourcesTable sources={result as Fetched<Source[]>} providerLabel={label} clock={clock} />
        <p className="small muted" style={{ margin: 0 }}>
          历史状态：{sources.map((s) => `${s.history_status}${s.last_record_at ? `（最近记录 ${fmtDateTimeRel(s.last_record_at, clock.asOfMs, clock.tz)}）` : ''}`).join('、')}
        </p>
      </>
    );
  }
  if (schema === 'SeriesResponse') {
    const series = data as UsageSeries;
    return (
      <>
        <div className="chart-head">
          <span className="title">
            token 用量 <span>每 {series.bucket === 'hour' ? '小时' : '15 分钟'}</span>
          </span>
          <TokenLegend />
        </div>
        <TokenBarChart series={series} scale={timeScale(Date.parse(series.from), Date.parse(series.to))} clock={clock} />
      </>
    );
  }
  return <p className="small muted">未支持的样本类型：{schema}</p>;
}

/**
 * 合成样例（前端自造，不来自 contracts/mocks）：多个窗口在相近时间、相近或相同数值（0、6、36、38、100）时，
 * 百分比标签的避让效果。复现 2026-10-23 用户截图里的重叠。同一份数据分别按全宽和窄宽画。
 */
function CrowdedQuotaLabels() {
  const tz = 'Asia/Tokyo';
  const day = Date.parse('2026-10-21T15:00:00Z'); // 10/22 00:00 JST
  const h = (n: number) => new Date(day + n * 3_600_000).toISOString();
  const clock: Clock = { tz, asOfMs: day + 14.5 * 3_600_000 };
  const win = (id: string, from: number, to: number, long: boolean): QuotaWindow => ({
    id,
    pool_id: 'pool_synth',
    slot: long ? 'secondary' : 'primary',
    starts_at: h(from),
    ends_at: h(to),
    duration_seconds: long ? 7 * 86400 : 5 * 3600,
    start_source: 'reported',
    end_source: 'reported',
    semantics: 'fixed',
    status: 'current',
    freshness: 'fresh',
    latest_snapshot: null,
    previous_window_id: null,
    next_window_id: null,
  });
  const windows = [
    win('s_52', -3, 2, false),
    win('s_38', 13, 18, false),
    win('s_36', 13, 18, false),
    win('s_0', 13, 18, false),
    win('s_100', 19, 24, false),
    win('l_64', -48, 120, true),
    win('l_6', -24, 144, true),
    win('l_0', 13, 181, true),
  ];
  const v: Record<string, number> = { s_52: 52, s_38: 38, s_36: 36, s_0: 0, s_100: 100, l_64: 64, l_6: 6, l_0: 0 };
  const summaries: QuotaWindowSummary[] = windows.map((w) => ({
    window_id: w.id,
    pool_id: w.pool_id,
    scope_from: h(0),
    scope_to: h(24),
    max_observed_percent: v[w.id]!,
    sample_count: 3,
    known_value_count: 3,
    first_sample_at: w.starts_at,
    last_sample_at: w.ends_at,
    label: 'highest_observed_in_selected_range',
  }));
  const scale = timeScale(day, day + 24 * 3_600_000);
  return (
    <article className="chart-box" aria-label="合成样例：额度标签拥挤">
      <div className="chart-head">
        <span className="title">合成样例 · 额度百分比标签避让</span>
        <span className="small muted">前端自造数据：38/36/0 同一五小时窗口位置，七天 64/6/0，另有 52、100</span>
      </div>
      <CalendarQuotaChart summaries={summaries} windows={windows} snapshots={null} scale={scale} clock={clock} />
      <div style={{ maxWidth: 360 }}>
        <div className="small muted">同一数据 · 窄宽 360px</div>
        <CalendarQuotaChart summaries={summaries} windows={windows} snapshots={null} scale={scale} clock={clock} />
      </div>
    </article>
  );
}

