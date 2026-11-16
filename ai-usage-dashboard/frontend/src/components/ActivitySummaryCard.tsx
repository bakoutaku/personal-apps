import type { HistoryData } from '../state/loadDashboard';
import { fmtTokens, fmtTokensShort, summarizeActivity } from '../domain/usage';
import { fmtTime } from '../time/tz';
import type { SelectionConnection } from '../domain/sources';
import { FetchProblem, type Clock } from './common';

/** 最近五小时活动摘要：从 as_of 往回五小时的滚动范围，与供应商额度窗口无关。 */
export function ActivitySummaryCard({ history, clock, connection }: { history: HistoryData; clock: Clock; connection: SelectionConnection }) {
  const { series, events, sessions } = history;
  return (
    <article className="card activity-card" aria-label="最近五小时活动">
      <div className="card-head">
        <span className="eyebrow">最近五小时活动</span>
        <span className="badge">非额度窗口</span>
      </div>
      {!series.ok ? (
        <FetchProblem result={series} what="最近五小时用量" />
      ) : (
        <ActivityBody history={history} clock={clock} connection={connection} eventTimes={events.ok ? events.data.map((e) => e.occurred_at) : []} sessionCount={sessions.ok ? sessions.data.length : null} />
      )}
      <p className="card-note small">从现在往回推 5 小时的滚动范围，与供应商的额度窗口无关；token 不能换算成额度百分比。</p>
    </article>
  );
}

function ActivityBody({
  history,
  clock,
  connection,
  eventTimes,
  sessionCount,
}: {
  history: HistoryData;
  clock: Clock;
  connection: SelectionConnection;
  eventTimes: string[];
  sessionCount: number | null;
}) {
  if (!history.series.ok) return null;
  const s = summarizeActivity(history.series.data.buckets, eventTimes);
  // 按 /sources 判断：全部未接入才说“所选产品未接入”；部分未接入另行提示
  const notConfigured = s.eventCount === 0 && connection === 'none_configured';
  const partlyConfigured = connection === 'some_unconfigured';
  return (
    <>
      {notConfigured ? (
        <div className="big-pct">
          <span className="unit">所选产品未接入</span>
        </div>
      ) : s.eventCount === 0 ? (
        <div className="big-pct">
          <span className="unit">没有已记录事件</span>
        </div>
      ) : (
        <div className="big-pct" title={s.knownTotal !== null ? `${fmtTokens(s.knownTotal)} token` : undefined}>
          {s.knownTotal === null ? (
            <span className="unit">token 用量未知</span>
          ) : (
            <>
              <span className="num value">{fmtTokensShort(s.knownTotal)}</span>
              <span className="unit">token · {s.unknownEvents > 0 ? '已知小计' : '已知合计'}</span>
            </>
          )}
        </div>
      )}
      {notConfigured && <p className="card-note">这个产品还没有接入任何来源，没有可统计的记录；不代表没有使用。</p>}
      {s.eventCount === 0 && !notConfigured && (
        <p className="card-note">
          {partlyConfigured
            ? '没有已记录事件，所选产品中部分未接入；不等于没有使用。'
            : '这段时间没有已记录事件，不等于没有使用（本机以外的设备不在覆盖范围内）。'}
        </p>
      )}
      {s.eventCount > 0 && partlyConfigured && <p className="card-note">所选产品中部分未接入，只统计已接入的来源。</p>}
      {s.unknownEvents > 0 && <p className="card-note">另有 {s.unknownEvents} 条记录的 token 用量未知，没有计入。</p>}
      <div className="card-grid three">
        <div>
          <div className="eyebrow">范围</div>
          <div className="num v">
            {fmtTime(history.from, clock.tz)}–{fmtTime(history.to, clock.tz)}
          </div>
        </div>
        <div>
          <div className="eyebrow">会话</div>
          <div className="num v">{sessionCount ?? '—'}</div>
        </div>
        <div>
          <div className="eyebrow">最近记录</div>
          <div className="num v">{s.latestRecordAt ? fmtTime(s.latestRecordAt, clock.tz) : '—'}</div>
        </div>
      </div>
    </>
  );
}
