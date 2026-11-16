import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import type { DataAdapter } from './api/adapter';
import type { Product, Provider } from './api/types';
import { FetchProblem, type Clock } from './components/common';
import { AboutPage } from './components/AboutPage';
import { DetailSection } from './components/DetailSection';
import { HistoryExplainer } from './components/HistoryExplainer';
import { HistorySection } from './components/HistorySection';
import { HomeView, type ChartType } from './components/HomeView';
import { ProductFilter } from './components/ProductFilter';
import { QuotaSection } from './components/QuotaSection';
import { SourcesTable } from './components/SourcesTable';
import { FailureBars, StaleBar } from './components/StateBars';
import { TopBar } from './components/TopBar';
import { LabelEditor } from './components/LabelEditor';
import { LabelEditingContext, type EditorRequest, type LabelEditing } from './components/labelEditing';
import type { LabelWriter } from './api/labelWriter';
import type { CollectorClient } from './api/collectorSettings';
import { CollectorSettingsPanel } from './components/CollectorSettingsPanel';
import { formatHash, PAGES, parseHash, VIEWS, type Page, type Route, type View } from './route/hash';
import { classifyLoad, loadDashboard, type LoadResult } from './state/loadDashboard';
import { RefreshScheduler, type LoadOutcome, type SchedulerState } from './state/refreshScheduler';
import { fmtDate, fmtTime } from './time/tz';

const PROVIDER_LABEL: Record<Provider, string> = { gpt: 'GPT', claude: 'Claude' };

// 状态样例页只在 mock 构建里存在；HTTP 构建中这一分支被常量折叠掉，模拟数据不进产物。
const StatesGallery =
  import.meta.env.VITE_DATA_ADAPTER === 'http'
    ? null
    : lazy(() => import('./components/StatesGallery').then((m) => ({ default: m.StatesGallery })));

const isGalleryHash = () => window.location.hash.startsWith('#/states');

/** 顶层：mock 模式下 #/states 显示状态样例页，其余交给 App。 */
export function Root({ adapter }: { adapter: DataAdapter }) {
  const [gallery, setGallery] = useState(() => !!StatesGallery && adapter.mode === 'mock' && isGalleryHash());
  useEffect(() => {
    const onHash = () => setGallery(!!StatesGallery && adapter.mode === 'mock' && isGalleryHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [adapter]);
  if (!gallery || !StatesGallery) return <App adapter={adapter} />;
  return (
    <div data-provider="gpt">
      <div className="banner" role="note">
        模拟数据 · 状态样例 · 所有数字均为虚构
      </div>
      <div className="page">
        <Suspense fallback={<div className="placeholder">正在加载…</div>}>
          <StatesGallery />
        </Suspense>
      </div>
    </div>
  );
}

/** 没有指定视图时的默认：日 / 今天（Claude Code 的已导入历史不会因为近五小时没有记录而显得没接入） */
function defaultView(adapter: DataAdapter): View {
  const initial = adapter.getBootstrapContext()?.initialView;
  return initial && (VIEWS as readonly string[]).includes(initial) ? (initial as View) : 'day';
}

function initialRoute(adapter: DataAdapter): { route: Route; dropped: string[] } {
  const boot = adapter.getBootstrapContext();
  const defaults = { provider: boot?.provider ?? 'gpt', view: defaultView(adapter) };
  const parsed = parseHash(window.location.hash, defaults);
  // 空 hash：用模拟场景给出的初始产品
  if (!window.location.hash.includes('?') && boot && parsed.route.provider === boot.provider) {
    parsed.route.products = boot.products.length ? [...boot.products] : null;
  }
  return parsed;
}

const PAGE_LABEL: Record<Page, string> = { home: '用量', quota: '额度', details: '明细', sources: '数据来源', about: '关于' };

export interface SessionControls {
  onLogout: () => void;
  /** 写入时遇到 401：回到配对 */
  onUnauthorized: () => void;
  /** 标签写入器（仅 live）；mock 没有，标签只读 */
  writer: LabelWriter;
  /** 本机自动采集设置（仅 live）；数据来源页与空库提示里显示 */
  collector?: CollectorClient;
}

export function App({ adapter, session }: { adapter: DataAdapter; session?: SessionControls }) {
  const live = adapter.mode === 'http';
  const [{ route, dropped }, setParsed] = useState(() => initialRoute(adapter));
  // 最近一次读取结果及其所属范围。范围变化时不清空（整页塌缩会让浏览器把滚动钳回顶部），
  // 而是按 resultKey 判断“当前范围的数据还没到”，只在数据区内显示读取中，绝不把上一范围的数据配上新范围。
  const [result, setResult] = useState<LoadResult | null>(null);
  const [resultKey, setResultKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // 刷新协调：首次 / 范围变化 / 手动 / 定时 / 回到页面都经过同一个调度器（见 state/refreshScheduler.ts）
  const schedRef = useRef<RefreshScheduler | null>(null);
  const [sched, setSched] = useState<SchedulerState | null>(null);
  // 页面最近一次成功读取的本机时间（不是额度观测时间）；读取失败时保留上次成功的画面并提示
  const [lastReadAt, setLastReadAt] = useState<number | null>(null);
  const [readError, setReadError] = useState<{ at: number; reason: string } | null>(null);
  const refresh = useCallback(() => schedRef.current?.request('manual'), []);
  // 多个本机账户命名空间时由用户选择（只放内存，不进 URL）
  const [accountId, setAccountId] = useState<string | undefined>(undefined);
  // 响应到达时的单调时钟读数，用来推进 live 模式的 as_of（B11）
  const [receivedAt, setReceivedAt] = useState(0);
  // 标签编辑器；重新配对后用 writer 内存里的草稿恢复
  const [editor, setEditor] = useState<EditorRequest | null>(() => (session?.writer.resume?.request as EditorRequest | undefined) ?? null);
  // 产品筛选按供应商分别记忆（仅内存）
  const productMemory = useRef(new Map<Provider, Product[] | null>());
  // 首页图表类型（仅内存）与立绘开关
  const [chartType, setChartType] = useState<ChartType>('bar');

  // 换页面时记住离开时的滚动位置，回来（后退或再点进来）时恢复；新页面从顶部开始
  const scrollMemory = useRef(new Map<string, number>());
  const currentHash = useRef(window.location.hash);
  const pendingScroll = useRef<number | null>(null);
  const routeRef = useRef(route);
  routeRef.current = route;

  useEffect(() => {
    const onHash = () => {
      const boot = adapter.getBootstrapContext();
      const next = parseHash(window.location.hash, { provider: boot?.provider ?? 'gpt', view: defaultView(adapter) });
      if (next.route.page !== routeRef.current.page) {
        scrollMemory.current.set(currentHash.current, window.scrollY);
        pendingScroll.current = scrollMemory.current.get(window.location.hash) ?? 0;
      }
      currentHash.current = window.location.hash;
      setParsed(next);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [adapter]);

  const navigate = (next: Route) => {
    const h = formatHash(next);
    if (h === window.location.hash) return;
    window.location.hash = h;
  };

  // 数据范围（供应商、账户、产品、视图、池、窗口、日期、选区）；页面不属于数据范围，换页面不重读。
  const { page, ...dataRoute } = route;
  const scopeKey = JSON.stringify([dataRoute, accountId ?? null]);
  const lastScope = useRef<string | null>(null);
  // 每次读取用最新的路由 / 账户 / 范围（读取进行中范围变化 → 结果作废，由排队的读取接上）
  const latest = useRef({ route, accountId, scopeKey });
  latest.current = { route, accountId, scopeKey };
  /** 当前画面上显示的是哪个范围的成功数据 */
  const shownScope = useRef<string | null>(null);

  const runLoad = async (): Promise<LoadOutcome> => {
    const { route: rt, accountId: acc, scopeKey: key } = latest.current;
    setLoading(true);
    let r = await loadDashboard(adapter, rt, acc);
    // data_revision 不一致：整屏重读一次；仍不一致则报错，不拼接两轮数据。
    if (!r.ok && r.reason === 'revision_mismatch') r = await loadDashboard(adapter, rt, acc);
    const outcome = classifyLoad(r);
    if (key !== latest.current.scopeKey) return 'ok'; // 已过时的范围：丢弃，不覆盖新结果
    setLoading(false);
    if (outcome === 'unauthorized') return outcome; // 适配器已通知回到配对；不动画面
    if (outcome === 'failed' && shownScope.current === key) {
      // 刷新失败：保留上一次成功的画面，明确提示，不显示成“没有数据”
      setReadError({ at: Date.now(), reason: describeFailure(r) });
      return outcome;
    }
    setReceivedAt(performance.now());
    setResult(r);
    setResultKey(key);
    if (r.ok) shownScope.current = key;
    if (outcome === 'ok') {
      setReadError(null);
      setLastReadAt(Date.now());
    }
    if (r.ok) {
      const fixed: Route = { ...latest.current.route, pool: r.data.resolved.pool, window: rt.view === 'window' ? r.data.resolved.window : rt.window };
      const h = formatHash(fixed);
      if (h !== window.location.hash) {
        history.replaceState(null, '', h);
        currentHash.current = h;
      }
    }
    return outcome;
  };
  const runRef = useRef(runLoad);
  runRef.current = runLoad;

  // 调度器随组件创建与销毁：卸载（换页面、401 回到配对）时停止定时器并移除监听，避免重复轮询
  useEffect(() => {
    const s = new RefreshScheduler(
      () => runRef.current(),
      {
        setTimeout: (fn, ms) => window.setTimeout(fn, ms),
        clearTimeout: (h) => window.clearTimeout(h as number),
        isVisible: () => document.visibilityState === 'visible',
      },
      { polling: live },
      setSched,
    );
    schedRef.current = s;
    const onVisibility = () => s.visibilityChanged();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      s.stop();
      if (schedRef.current === s) schedRef.current = null;
    };
  }, [adapter, live]);

  // 范围变化：标记新范围（旧数据不再当作当前数据显示），再请求读取（进行中的读取结束后接着读新范围）
  useEffect(() => {
    if (lastScope.current !== scopeKey) {
      lastScope.current = scopeKey;
      setReadError(null);
      shownScope.current = null;
    }
    schedRef.current?.request('scope');
  }, [scopeKey]);

  /** 当前范围的读取结果；null = 还在读 */
  const current = result && resultKey === scopeKey ? result : null;
  const data = current?.ok ? current.data : null;
  // 上一次成功的数据（可能属于旧范围）：只用来保持时钟和页面骨架，不显示其数值
  const prevData = result?.ok ? result.data : null;
  const sameProvider = prevData && prevData.account.provider === route.provider ? prevData : null;
  const clock = useLiveClock(prevData?.meta.as_of ?? null, prevData?.meta.timezone ?? null, receivedAt, live);
  const pending = current === null;
  const hasPool = data ? !!data.pool : sameProvider ? !!sameProvider.pool : route.provider === 'gpt';

  // 读取新范围时内容区保持上一次的高度（同一页面内），避免页面变短把滚动位置钳回顶部
  const contentRef = useRef<HTMLDivElement | null>(null);
  const lastHeight = useRef<{ page: Page; h: number } | null>(null);
  useLayoutEffect(() => {
    if (!pending && contentRef.current) lastHeight.current = { page, h: contentRef.current.offsetHeight };
    if (pendingScroll.current !== null && !pending) {
      window.scrollTo(0, pendingScroll.current);
      pendingScroll.current = null;
    }
  });
  const holdHeight = pending && lastHeight.current?.page === page ? lastHeight.current.h : undefined;

  // live：当前窗口的倒计时归零后显示“待确认重置”并刷新一次，不自行生成下一窗口
  const resetHandled = useRef(new Set<string>());
  useEffect(() => {
    if (!live || !clock || !data?.windows?.ok) return;
    const due = data.windows.data.find(
      (w) => w.status === 'current' && w.ends_at && Date.parse(w.ends_at) <= clock.asOfMs && !resetHandled.current.has(w.id),
    );
    if (due) {
      resetHandled.current.add(due.id);
      refresh();
    }
  }, [live, clock, data, refresh]);

  const switchProvider = (p: Provider) => {
    if (p === route.provider) return;
    productMemory.current.set(route.provider, route.products);
    // 账户命名空间按供应商区分，换供应商时不沿用
    setAccountId(undefined);
    // Claude 没有额度窗口：window → 日
    const view: View = p === 'claude' && route.view === 'window' ? 'day' : route.view;
    navigate({ provider: p, page: route.page, products: productMemory.current.get(p) ?? null, view, pool: null, window: null, date: null, range: null });
  };

  // 标签编辑器跟着当前供应商的数据走；读取新范围时沿用同一供应商的上一份数据，草稿不因换视图丢失
  const editorData = data ?? sameProvider;
  const writable = !!session?.writer && !!data && route.provider === data.account.provider;
  const labelEditing: LabelEditing = {
    writable,
    readOnlyReason: session ? '数据还在读取中' : '模拟数据只读，接入本机服务后可编辑标签',
    open: (req) => writable && setEditor(req),
  };
  // 编辑器按 id 找标签 / 会话：主范围与选区两批合起来
  const hist = editorData?.history ?? null;
  const pick = <T extends { id: string }>(xs: (T[] | null)[]) => [...new Map(xs.flatMap((x) => x ?? []).map((x) => [x.id, x])).values()];
  const knownLabels = hist ? pick([hist.labels.ok ? hist.labels.data : null, hist.selection?.labels.ok ? hist.selection.labels.data : null]) : [];
  const knownSessions = hist ? pick([hist.sessions.ok ? hist.sessions.data : null, hist.selection?.sessions.ok ? hist.selection.sessions.data : null]) : [];

  const sourcesList = data?.sources.ok ? data.sources.data : [];
  const settingsPanel =
    session?.collector && live ? (
      <CollectorSettingsPanel client={session.collector} clock={clock} refreshToken={lastReadAt} onUnauthorized={session.onUnauthorized} onChanged={refresh} />
    ) : null;
  const failure = current && !current.ok ? <LoadFailure result={current} settings={settingsPanel} /> : null;
  const loadingBox = (
    <div className="placeholder" aria-busy="true">
      {live ? '正在读取本机数据…' : '正在读取模拟数据…'}
    </div>
  );
  // 页面从本机服务读取数据的时间（不是额度观测时间）
  const readStatus =
    live && clock && lastReadAt !== null
      ? `${sched?.inFlight ? '正在读取… · ' : ''}页面读取 ${fmtClock(lastReadAt, clock.tz)}${sched && sched.nextDelayMs !== null && sched.failures === 0 ? ' · 页面可见时每 30 秒自动读取' : ''}（不是额度观测时间）`
      : null;
  const pageHref = (pg: Page, extra: Partial<Route> = {}) => formatHash({ ...route, page: pg, ...extra });

  return (
    <LabelEditingContext.Provider value={labelEditing}>
    <div data-provider={route.provider}>
      {prevData?.meta.data_mode === 'mock' && clock && (
        <div className="banner" role="note">
          模拟数据 · 所有数字均为虚构 · 模拟时钟 {fmtDate(clock.asOfMs, clock.tz)} {fmtTime(clock.asOfMs, clock.tz)}（{clock.tz}）
          {/* health/accounts 属于共享 catalog，场景名取自来源响应 */}
          {prevData.sources.ok && prevData.sources.meta.scenario_id ? ` · 场景 ${prevData.sources.meta.scenario_id}` : ''}
          {adapter.mode === 'mock' && (
            <>
              {' · '}
              <a href="#/states" style={{ color: 'inherit' }}>
                查看状态样例
              </a>
            </>
          )}
        </div>
      )}
      <div className="page">
        <TopBar
          provider={route.provider}
          onProvider={switchProvider}
          sources={sameProvider?.sources ?? null}
          clock={clock}
          sourcesHref={pageHref('sources')}
          nav={
            <nav aria-label="页面" className="page-nav">
              {PAGES.map((pg) => (
                <a key={pg} href={pageHref(pg)} aria-current={page === pg ? 'page' : undefined}>
                  {PAGE_LABEL[pg]}
                </a>
              ))}
            </nav>
          }
          actions={
            live && (
              <>
                {/* 读取时间与轮询说明放在刷新按钮的悬停说明里（数据来源页另有完整一行） */}
                <button
                  type="button"
                  className={`ibtn${sched?.inFlight ? ' spinning' : ''}`}
                  aria-label="刷新"
                  aria-busy={sched?.inFlight || undefined}
                  title={readStatus ? `重新读取整页数据\n${readStatus}` : '重新读取整页数据'}
                  onClick={refresh}
                  disabled={loading}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />
                  </svg>
                </button>
                {session && (
                  <button type="button" className="text-btn" onClick={session.onLogout} title="撤销这台浏览器的本应用会话（不是退出 OpenAI / Claude）">
                    退出本机会话
                  </button>
                )}
              </>
            )
          }
        />

        {sameProvider && sameProvider.accounts.length > 1 && (
          <label className="account-pick small">
            <span className="eyebrow">账户命名空间</span>
            <select
              value={sameProvider.account.id}
              onChange={(e) => {
                // 换账户：池和窗口 ID 属于旧账户，一并清掉
                setAccountId(e.target.value);
                navigate({ ...route, pool: null, window: null, date: null, range: null });
              }}
            >
              {sameProvider.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                  {a.identity_status === 'local_unverified' ? '（本机，未验证）' : ''}
                </option>
              ))}
            </select>
          </label>
        )}

        {readError && data && clock && (
          <div className="state-bar warn" role="status">
            <div className="state-bar-row">
              <div className="body">
                <strong>读取失败（{fmtClock(readError.at, clock.tz)}）：{readError.reason}。</strong>
                页面仍显示 {lastReadAt !== null ? fmtClock(lastReadAt, clock.tz) : '上一次'} 成功读取的数据，不代表这段时间没有新记录。
                {sched?.nextDelayMs != null && ` 约 ${Math.round(sched.nextDelayMs / 1000)} 秒后自动重试。`}
              </div>
              <button type="button" className="text-btn" onClick={refresh} disabled={loading}>
                立即重试
              </button>
            </div>
          </div>
        )}

        {(dropped.length > 0 || (data?.notices.length ?? 0) > 0) && (
          <div className="notice" role="status">
            {dropped.length > 0 && <div>链接里有无法识别的参数，已忽略：{dropped.join('、')}</div>}
            {data?.notices.map((n) => <div key={n}>{n}</div>)}
          </div>
        )}

        {data && clock && data.sources.ok && <FailureBars sources={data.sources.data} providerLabel={PROVIDER_LABEL[route.provider]} clock={clock} compact={page === 'home'} />}

        <div ref={contentRef} className="content" style={holdHeight ? { minHeight: holdHeight } : undefined}>
          {page === 'about' ? (
            <AboutPage />
          ) : page === 'home' ? (
            clock ? (
              <HomeView
                provider={route.provider}
                view={route.view}
                date={route.date}
                products={route.products}
                data={data}
                clock={clock}
                hasPool={hasPool}
                chartType={chartType}
                failure={failure}
                onChartType={setChartType}
                // 换视图保留锚定日期（日↔周↔月），清掉选区
                onView={(view) => navigate({ ...route, view, range: null })}
                onDate={(date) => navigate({ ...route, date, range: null })}
                onDetails={(range) => navigate({ ...route, page: 'details', range })}
                onPage={(pg) => navigate({ ...route, page: pg })}
              />
            ) : (
              failure ?? loadingBox
            )
          ) : failure ? (
            failure
          ) : !data || !clock ? (
            loadingBox
          ) : page === 'quota' ? (
            <>
              {data.windows?.ok && <StaleBar windows={data.windows.data} staleAfterSeconds={data.meta.stale_after_seconds} clock={clock} sources={sourcesList} />}
              {data.sources.ok && <ProductFilter provider={route.provider} selected={route.products} sources={data.sources.data} onChange={(products) => navigate({ ...route, products })} />}
              <QuotaSection
                pools={data.pools}
                pool={data.pool}
                windows={data.windows}
                sources={sourcesList}
                staleAfterSeconds={data.meta.stale_after_seconds}
                clock={clock}
                providerLabel={PROVIDER_LABEL[route.provider]}
                history={data.history}
                provider={route.provider}
                products={route.products}
              />
            </>
          ) : page === 'details' ? (
            <>
              {data.sources.ok && <ProductFilter provider={route.provider} selected={route.products} sources={data.sources.data} onChange={(products) => navigate({ ...route, products })} />}
              <HistorySection
                view={route.view}
                selectedWindow={data.selectedWindow}
                history={data.history}
                clock={clock}
                sources={sourcesList}
                providerLabel={PROVIDER_LABEL[route.provider]}
                windows={data.windows?.ok ? data.windows.data : []}
                provider={route.provider}
                hasPool={!!data.pool}
                products={route.products}
                // 换视图保留锚定日期（日↔周↔月），清掉选区
                onView={(view) => navigate({ ...route, view, range: null })}
                onWindow={(id) => navigate({ ...route, window: id })}
                onDate={(date) => navigate({ ...route, date, range: null })}
                onSelect={(range) => navigate({ ...route, range })}
              />
              {data.history && (
                <DetailSection
                  history={data.history}
                  sources={sourcesList}
                  clock={clock}
                  provider={route.provider}
                  products={route.products}
                  onClearSelection={() => navigate({ ...route, range: null })}
                />
              )}
            </>
          ) : (
            <>
              {readStatus && <p className="small muted" style={{ margin: 0 }}>{readStatus}</p>}
              {settingsPanel}
              <SourcesTable sources={data.sources} providerLabel={PROVIDER_LABEL[route.provider]} clock={clock} />
              <div className="section">
                <div className="eyebrow">已导入的历史</div>
                <HistoryExplainer sources={sourcesList} providerLabel={PROVIDER_LABEL[route.provider]} clock={clock} />
              </div>
            </>
          )}
        </div>
      </div>
      {editor && session && editorData && clock && (
        <LabelEditor
          key={JSON.stringify(editor)}
          request={editor}
          writer={session.writer}
          provider={route.provider}
          accountId={editorData.account.id}
          products={route.products}
          sources={editorData.sources.ok ? editorData.sources.data : []}
          labels={knownLabels}
          sessions={knownSessions}
          clock={clock}
          onDone={() => {
            session.writer.resume = null;
            setEditor(null);
            refresh();
          }}
          onRefresh={refresh}
          onClose={() => {
            session.writer.resume = null;
            setEditor(null);
          }}
          onUnauthorized={session.onUnauthorized}
        />
      )}
    </div>
    </LabelEditingContext.Provider>
  );
}

function LoadFailure({ result, settings }: { result: LoadResult & { ok: false }; settings: ReactNode }) {
  if (result.reason === 'base_unavailable') return <FetchProblem result={result.detail as never} what="基础信息" />;
  if (result.reason === 'no_accounts')
    return (
      <>
        <div className="placeholder">
          <strong>本机服务里还没有用量记录。</strong>
          <br />
          {settings
            ? '数据由本机服务读取，页面本身不读取日志文件。可以在下面启用本机 Codex / Claude Code 日志的自动采集。这里不会改用模拟数据。'
            : '数据由本机服务导入，页面不读取日志文件；导入后点“刷新”。这里不会改用模拟数据。'}
        </div>
        {settings}
      </>
    );
  if (result.reason === 'no_account')
    return <div className="placeholder">本机服务里还没有这个供应商的记录。</div>;
  return (
    <div className="notice error" role="alert">
      {result.reason === 'revision_mismatch' ? '多个请求的数据修订不一致，已重读仍不一致，暂不显示以免拼接两轮数据。' : '模拟与真实数据混在一起，已停止显示。'}
      <br />
      <code>{result.detail}</code>
    </div>
  );
}

/** mock：固定为 meta.as_of。live：用单调时钟从响应到达时推进 as_of，只是倒计时估计，不产生新数据。 */
function useLiveClock(asOfIso: string | null, tz: string | null, receivedAt: number, live: boolean): Clock | null {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setNow(performance.now()), 15_000);
    return () => window.clearInterval(id);
  }, [live]);
  if (!asOfIso || !tz) return null;
  const base = Date.parse(asOfIso);
  return { tz, asOfMs: live ? base + Math.max(0, now - receivedAt) : base };
}

/** 读取失败的简短原因（只用来提示，不显示后端原文）。 */
function describeFailure(r: LoadResult): string {
  if (!r.ok) {
    if (r.reason === 'revision_mismatch') return '数据在读取过程中发生变化';
    if (r.reason === 'base_unavailable') {
      const d = r.detail;
      if (!d.ok && d.kind === 'unreachable') return '本地服务不可达';
      if (!d.ok && d.kind === 'http_error') return `本地服务返回 HTTP ${d.status}`;
    }
    return '读取未完成';
  }
  const h = r.data.history;
  const parts = [r.data.sources, r.data.pools, r.data.windows, h?.series, h?.events, h?.sessions, h?.labels, h?.snapshots];
  for (const f of parts) {
    if (f && !f.ok) {
      if (f.kind === 'unreachable') return '本地服务不可达';
      if (f.kind === 'http_error') return `本地服务返回 HTTP ${f.status}`;
      if (f.kind === 'incomplete') return '分页没有读完';
    }
  }
  return '部分数据读取失败';
}

function fmtClock(ms: number, tz: string): string {
  const p = new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
  return p.format(new Date(ms));
}
