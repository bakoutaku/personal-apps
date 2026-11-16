import type { Fetched } from '../api/adapter';
import { PRODUCTS_BY_PROVIDER, type Product, type Provider, type QuotaPool, type QuotaWindow, type Source } from '../api/types';
import { selectionConnection } from '../domain/sources';
import { boundarySourceText, cardState, cardWindows, overlappingCandidates, poolMembershipText, slotTitle } from '../domain/quota';
import type { HistoryData } from '../state/loadDashboard';
import { fmtAgo, fmtDateTimeRel, fmtRemaining } from '../time/tz';
import { ActivitySummaryCard } from './ActivitySummaryCard';
import { FetchProblem, StatusDot, type Clock } from './common';

interface Props {
  pools: Fetched<QuotaPool[]>;
  pool: QuotaPool | null;
  windows: Fetched<QuotaWindow[]> | null;
  sources: Source[];
  staleAfterSeconds: number;
  clock: Clock;
  providerLabel: string;
  /** 没有额度池时，在“未接入”旁边放最近五小时活动摘要 */
  history: HistoryData | null;
  provider: Provider;
  products: Product[] | null;
}

export function QuotaSection({ pools, pool, windows, sources, staleAfterSeconds, clock, providerLabel, history, provider, products }: Props) {
  const noPool = pools.ok && pools.data.length === 0;
  return (
    <section className="section" aria-labelledby="quota-h">
      <div className="section-head">
        <div>
          <div className="eyebrow">01 · 现在</div>
          <h2 id="quota-h">
            {noPool ? '额度' : '额度池'} {pool && <span className="num">{pool.label}</span>}
            {noPool && <span className="num">尚无额度来源</span>}
          </h2>
          {noPool && (
            <p className="section-note">
              额度池与关联产品：未知
              <br />
              下方只显示 token 活动，不能换算成额度百分比。
            </p>
          )}
          {pool && (
            <p className="section-note">
              {poolMembershipText(pool, PRODUCTS_BY_PROVIDER[pool.provider])}（依据：{pool.membership_evidence}）
              <br />
              同一池的各槽位分别显示，不能相加；额度按池显示，不随上方产品筛选变化。
            </p>
          )}
        </div>
      </div>
      {!pools.ok ? (
        <FetchProblem result={pools} what="额度池" />
      ) : !pool ? (
        <div className="cards">
          <article className="card not-connected" aria-label="供应商额度未接入">
            <div className="card-head">
              <span className="eyebrow">供应商额度</span>
              <span className="badge ghost">
                <StatusDot kind="off" /> 未接入
              </span>
            </div>
            <div className="big-word">未接入</div>
            <p className="card-note" style={{ fontSize: 14 }}>
              {providerLabel} 目前没有额度快照来源。这里不显示百分比、进度条或重置时间，不会为只有 token 的来源生成额度窗口，也不会把读不到的额度写成 0。
            </p>
          </article>
          {history?.kind === 'recent5h' && (
            <ActivitySummaryCard history={history} clock={clock} connection={selectionConnection(sources, provider, products, PRODUCTS_BY_PROVIDER)} />
          )}
        </div>
      ) : !windows ? null : !windows.ok ? (
        <FetchProblem result={windows} what="额度窗口" />
      ) : windows.data.length === 0 ? (
        <div className="placeholder">
          最近五小时内没有该池的额度窗口记录。没有当前窗口，不显示额度百分比，也不把更早的值当作现在的额度。
        </div>
      ) : (
        <QuotaCards windows={windows.data} sources={sources} staleAfterSeconds={staleAfterSeconds} clock={clock} />
      )}
    </section>
  );
}

export function QuotaCards({
  windows,
  sources,
  staleAfterSeconds,
  clock,
}: {
  windows: QuotaWindow[];
  sources: Source[];
  staleAfterSeconds: number;
  clock: Clock;
}) {
  return (
    <div className="cards">
      {cardWindows(windows).map((w) => (
        <QuotaCard key={w.id} w={w} others={overlappingCandidates(windows, w)} sources={sources} clock={clock} staleAfterSeconds={staleAfterSeconds} />
      ))}
    </div>
  );
}

function QuotaCard({
  w,
  others,
  sources,
  clock,
  staleAfterSeconds,
}: {
  w: QuotaWindow;
  /** 同槽位、边界不同且重叠的其他窗口记录 */
  others: QuotaWindow[];
  sources: Source[];
  clock: Clock;
  staleAfterSeconds: number;
}) {
  const st = cardState(w);
  const t = (iso: string) => fmtDateTimeRel(iso, clock.asOfMs, clock.tz);
  const remaining = w.ends_at ? fmtRemaining(Date.parse(w.ends_at) - clock.asOfMs) : null;
  // live 时钟推进后超过结束时间：等后端确认，不自行判定已重置或生成下一窗口
  const pendingReset = st.status === 'current' && !!w.ends_at && Date.parse(w.ends_at) <= clock.asOfMs;
  const failing = sources.find((s) => s.id === w.latest_snapshot?.source_id && s.connection_status === 'error');
  const cls = [
    'card',
    st.status !== 'current' && 'dim',
    st.status === 'expired' && 'expired',
    st.stale && 'stale',
  ]
    .filter(Boolean)
    .join(' ');

  let badge: React.ReactNode;
  if (st.status === 'expired') badge = <span className="badge ghost">窗口已结束</span>;
  else if (pendingReset) badge = <span className="badge warn">待确认重置</span>;
  else if (st.status === 'unknown') badge = <span className="badge ghost">窗口状态未知</span>;
  else if (st.stale)
    badge = (
      <span className="badge warn" title={`超过 ${Math.round(staleAfterSeconds / 60)} 分钟没有新记录`}>
        观测已过时
      </span>
    );
  else if (failing?.last_success_at)
    badge = (
      <span className="badge" title="来源同步失败，显示最后一次成功同步的数据">
        截至 {t(failing.last_success_at)}
      </span>
    );
  else badge = <span className="badge">当前窗口</span>;

  let unit = '% 已用';
  if (st.status === 'expired') unit = '% 最后观测';
  else if (st.status === 'unknown') unit = '% · 最近记录';
  else if (st.stale && st.timeIso) unit = `% · ${t(st.timeIso)} 时`;

  return (
    <article className={cls} aria-label={`${slotTitle(w)}，槽位 ${w.slot}`}>
      <div className="card-head">
        <span className="eyebrow">
          {slotTitle(w)} <span className="num">· {w.slot}</span>
        </span>
        {badge}
      </div>

      <div className="big-pct">
        {st.percent === null ? (
          <span className="unit">已用比例未知</span>
        ) : (
          <>
            <span className="num value">{st.percent}</span>
            <span className="num unit">{unit}</span>
          </>
        )}
      </div>

      {st.percent !== null && st.status === 'current' && (
        <div className="meter" role="img" aria-label={`已用 ${st.percent}%`}>
          <div style={{ width: `${Math.min(st.percent, 100)}%` }} />
        </div>
      )}
      {st.overHundred && <p className="card-note">来源报告超过 100%，按原值显示。</p>}
      {st.stale && st.timeIso && (
        <p className="card-note">
          之后约 {fmtAgo(st.timeIso, clock.asOfMs).replace('前', '')}没有新的额度记录，当前实际值可能更高。
          {w.ends_at && `重置时间 ${t(w.ends_at)}（${boundarySourceText('end', w)}）仍然有效。`}
        </p>
      )}
      {st.status === 'expired' && w.ends_at && (
        <p className="card-note">
          该窗口已于 <span className="num">{t(w.ends_at)}</span> 到达重置时间，之后尚无新快照，所以不再当作当前额度，也不归零。
        </p>
      )}
      {st.status === 'unknown' && (
        <p className="card-note">来源没有给出这个窗口的起止时间，不能判断它是否为当前窗口；不画时间轴，也不参与前后翻页。</p>
      )}

      <div className="card-grid">
        <div>
          <div className="eyebrow">重置</div>
          <div className="num v">
            {w.ends_at ? t(w.ends_at) : '未知'}{' '}
            {st.status === 'current' && !st.stale && remaining && w.duration_seconds !== null && w.duration_seconds <= 86400 && (
              <span className="muted">还剩 {remaining}</span>
            )}
          </div>
        </div>
        <div>
          <div className="eyebrow">{st.timeLabel}</div>
          <div className="num v">
            {st.timeIso ? (
              <>
                {t(st.timeIso)} <span className="muted">{fmtAgo(st.timeIso, clock.asOfMs)}</span>
              </>
            ) : (
              '暂无'
            )}
          </div>
        </div>
      </div>

      {others.length > 0 && (
        <p className="card-note" title={others.map((o) => `${o.id}：${o.ends_at ? t(o.ends_at) : '结束未知'}`).join('\n')}>
          这个槽位存在 {others.length + 1} 条边界不同、时间重叠的窗口记录，当前按最新记录展示。这只是展示选择，不代表供应商已确认窗口修订，各记录的值也不相加。
        </p>
      )}

      <div className="bounds">
        <span className="num">开始 {w.starts_at ? t(w.starts_at) : '未知'}</span>
        <span className="badge ghost">{boundarySourceText('start', w)}</span>
        <span className="num">结束 {w.ends_at ? t(w.ends_at) : '未知'}</span>
        <span className="badge ghost">{boundarySourceText('end', w)}</span>
        {w.semantics === 'unknown' && <span className="subtle">固定/滑动规则未经验证</span>}
      </div>
    </article>
  );
}
