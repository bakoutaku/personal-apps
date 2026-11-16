import type { DataAdapter, Fetched } from '../api/adapter';
import type {
  Account,
  Bucket,
  Health,
  Label,
  Meta,
  Product,
  QuotaPool,
  QuotaSnapshot,
  QuotaWindow,
  QuotaWindowSummary,
  Session,
  Source,
  UsageEvent,
  UsageSeries,
} from '../api/types';
import { defaultWindow, hasFullBounds } from '../domain/quota';
import type { Route } from '../route/hash';
import { calendarRange, localDateKey, type CalendarView } from '../time/tz';

/** 某个范围的活动数据：四项都用同一范围、同一产品筛选。 */
export interface UsageBundle {
  series: Fetched<UsageSeries>;
  events: Fetched<UsageEvent[]>;
  sessions: Fetched<Session[]>;
  labels: Fetched<Label[]>;
}

/** 日 / 周 / 月视图的额度历史：按窗口的最高观测值，绝不相加。 */
export interface QuotaHistory {
  summaries: Fetched<QuotaWindowSummary[]>;
  /** 同范围的窗口（取 slot / 时长 / 边界；其 latest_snapshot 是截至 as_of 的，不用于历史数值） */
  windows: Fetched<QuotaWindow[]>;
  /** 仅日视图：同范围的原始观测点 */
  snapshots: Fetched<QuotaSnapshot[]> | null;
}

export interface HistoryData {
  /**
   * window：所选额度窗口的起止（含额度快照）。
   * recent5h：从 as_of 往前五小时的活动范围，不是额度窗口，不请求额度快照。
   */
  kind: 'window' | 'recent5h' | 'calendar';
  /** 仅 kind=calendar */
  calendar: { view: CalendarView; dateKey: string; bucket: Bucket } | null;
  /** 仅 kind=calendar 且有额度池 */
  quota: QuotaHistory | null;
  /** 在图上选中的时间段（只过滤明细），未选或不在范围内为 null */
  selection: ({ from: string; to: string } & UsageBundle) | null;
  /** 仅 kind=window */
  window: QuotaWindow | null;
  from: string;
  to: string;
  /** 仅 kind=window */
  snapshots: Fetched<QuotaSnapshot[]> | null;
  series: Fetched<UsageSeries>;
  events: Fetched<UsageEvent[]>;
  sessions: Fetched<Session[]>;
  labels: Fetched<Label[]>;
}

export interface DashboardData {
  meta: Meta;
  health: Health;
  account: Account;
  /** 同一供应商下的全部本机账户命名空间（多于一个时让用户选）。 */
  accounts: Account[];
  sources: Fetched<Source[]>;
  pools: Fetched<QuotaPool[]>;
  pool: QuotaPool | null;
  windows: Fetched<QuotaWindow[]> | null;
  selectedWindow: QuotaWindow | null;
  /** view=window 且选中窗口边界完整，或 view=recent5h 时加载；其他视图尚未实现。 */
  history: HistoryData | null;
  /** 路由修正后的规范值（用于回写 hash）。 */
  resolved: { pool: string | null; window: string | null };
  notices: string[];
}

export type LoadResult =
  | { ok: true; data: DashboardData }
  | { ok: false; reason: 'base_unavailable'; detail: Fetched<unknown> }
  | { ok: false; reason: 'no_account'; meta: Meta }
  /** 后端里还没有任何账户：尚未导入。不回退到 mock。 */
  | { ok: false; reason: 'no_accounts'; meta: Meta }
  | { ok: false; reason: 'revision_mismatch' | 'mode_mismatch'; detail: string };

const FIVE_HOURS = 5 * 3600_000;

export async function loadDashboard(adapter: DataAdapter, route: Omit<Route, 'page'>, accountId?: string): Promise<LoadResult> {
  const notices: string[] = [];
  const [health, accounts] = await Promise.all([adapter.getHealth(), adapter.getAccounts()]);
  if (!health.ok) return { ok: false, reason: 'base_unavailable', detail: health };
  if (!accounts.ok) return { ok: false, reason: 'base_unavailable', detail: accounts };
  const meta = health.meta;
  const tz = meta.timezone;

  const boot = adapter.getBootstrapContext(route.provider);
  if (accounts.data.length === 0) return { ok: false, reason: 'no_accounts', meta };
  const providerAccounts = accounts.data.filter((a) => a.provider === route.provider);
  const account =
    providerAccounts.find((a) => a.id === accountId) ??
    providerAccounts.find((a) => a.id === boot?.account_id) ??
    providerAccounts[0];
  if (!account) return { ok: false, reason: 'no_account', meta };
  const scope = { provider: account.provider, account_id: account.id } as const;

  const products: Product[] | undefined = route.products ?? undefined;
  const loadUsage = async (from: string, to: string, bucket: Bucket = '15m'): Promise<UsageBundle> => {
    const usageQ = { ...scope, from, to, timezone: tz, products };
    const [series, events, sessions, labels] = await Promise.all([
      adapter.getUsageSeries({ ...usageQ, bucket }),
      adapter.getUsageEvents(usageQ),
      adapter.getSessions(usageQ),
      adapter.getLabels(usageQ),
    ]);
    return { series, events, sessions, labels };
  };
  const asOfMs = Date.parse(meta.as_of);
  // 活动范围在这一批里冻结，与额度池/窗口无关，立即并行请求，不等额度结果。
  // recent5h：[as_of−5h, as_of)；日/周/月：按 meta.timezone 的自然边界（周一起），不是最近 N 天。
  const calView: CalendarView | null =
    route.view === 'day' || route.view === 'week' || route.view === 'month' ? route.view : null;
  const dateKey = calView ? (route.date ?? localDateKey(asOfMs, tz)) : null;
  const activity: { from: string; to: string; bucket: Bucket } | null =
    route.view === 'recent5h'
      ? { from: new Date(asOfMs - FIVE_HOURS).toISOString(), to: meta.as_of, bucket: '15m' }
      : calView && dateKey
        ? (() => {
            const r = calendarRange(calView, dateKey, tz);
            return { from: new Date(r.from).toISOString(), to: new Date(r.to).toISOString(), bucket: calView === 'day' ? 'hour' : 'day' };
          })()
        : null;
  const activityUsage = activity ? loadUsage(activity.from, activity.to, activity.bucket) : null;
  // 选中的时间段（仅日历视图，且须落在当前范围内）：只重读明细用的数据，按小时分桶。
  const sel =
    calView && activity && route.range && route.range.from >= activity.from && route.range.to <= activity.to
      ? route.range
      : null;
  if (calView && route.range && !sel) notices.push('选中的时间段不在当前范围内，已忽略。');
  const selectionUsage = sel ? loadUsage(sel.from, sel.to, 'hour') : null;

  const [sources, pools] = await Promise.all([adapter.getSources(scope), adapter.getQuotaPools(scope)]);

  let pool: QuotaPool | null = null;
  if (pools.ok && pools.data.length > 0) {
    pool = (route.pool && pools.data.find((p) => p.id === route.pool)) || null;
    if (route.pool && !pool) notices.push('链接里的额度池不存在，已回到默认额度池。');
    pool ??= pools.data.find((p) => p.id === boot?.pool_id) ?? pools.data[0] ?? null;
  }

  let windows: Fetched<QuotaWindow[]> | null = null;
  let selectedWindow: QuotaWindow | null = null;
  if (pool) {
    // 窗口查询范围：mock 用场景给出的启动范围；HTTP 按 B8 答复取 [as_of−5h, as_of+1ms)。
    // /quota-windows 返回与查询区间重叠的窗口，所以七天窗口也会出现。
    const useBoot = boot && boot.pool_id === pool.id && boot.account_id === account.id;
    const asOf = Date.parse(meta.as_of);
    const from = useBoot ? boot.from : new Date(asOf - FIVE_HOURS).toISOString();
    const to = useBoot ? boot.to : new Date(asOf + 1).toISOString();
    windows = await adapter.getQuotaWindows({ ...scope, pool_id: pool.id, from, to, timezone: tz });
    if (windows.ok) {
      selectedWindow = (route.window && windows.data.find((w) => w.id === route.window)) || null;
      if (route.window && !selectedWindow) notices.push('链接里的额度窗口不在当前结果中，已回到默认窗口。');
      selectedWindow ??=
        windows.data.find((w) => w.id === boot?.window_id && hasFullBounds(w)) ?? defaultWindow(windows.data) ?? null;
    }
  }

  let history: HistoryData | null = null;
  const none = { calendar: null, quota: null, selection: null };
  if (route.view === 'window' && pool && selectedWindow && hasFullBounds(selectedWindow)) {
    const from = selectedWindow.starts_at!;
    const to = selectedWindow.ends_at!;
    const [snapshots, usage] = await Promise.all([
      adapter.getQuotaSnapshots({ ...scope, pool_id: pool.id, from, to, window_id: selectedWindow.id }),
      loadUsage(from, to),
    ]);
    history = { kind: 'window', window: selectedWindow, from, to, snapshots, ...usage, ...none };
  } else if (route.view === 'recent5h' && activity && activityUsage) {
    // 契约：from=as_of−5h、to=as_of，不对齐整刻；与额度池、额度窗口无关。
    history = { kind: 'recent5h', window: null, from: activity.from, to: activity.to, snapshots: null, ...(await activityUsage), ...none };
  } else if (calView && dateKey && activity && activityUsage) {
    // 额度历史用最高观测值摘要；窗口只取 slot / 时长 / 边界。不传 products。
    const poolQ = pool ? { ...scope, pool_id: pool.id, from: activity.from, to: activity.to, timezone: tz } : null;
    const [usage, quota, selUsage] = await Promise.all([
      activityUsage,
      poolQ
        ? Promise.all([
            adapter.getQuotaWindowSummaries(poolQ),
            adapter.getQuotaWindows(poolQ),
            calView === 'day' ? adapter.getQuotaSnapshots(poolQ) : Promise.resolve(null),
          ]).then(([summaries, qWindows, snapshots]) => ({ summaries, windows: qWindows, snapshots }))
        : Promise.resolve(null),
      selectionUsage,
    ]);
    history = {
      kind: 'calendar',
      window: null,
      from: activity.from,
      to: activity.to,
      snapshots: null,
      ...usage,
      calendar: { view: calView, dateKey, bucket: activity.bucket },
      quota,
      selection: sel && selUsage ? { ...sel, ...selUsage } : null,
    };
  }

  // 多个请求的 data_revision / data_mode 必须一致，否则整屏重新加载。
  const parts: (Fetched<unknown> | null)[] = history
    ? [
        history.snapshots,
        history.series,
        history.events,
        history.sessions,
        history.labels,
        history.quota?.summaries ?? null,
        history.quota?.windows ?? null,
        history.quota?.snapshots ?? null,
        history.selection?.series ?? null,
        history.selection?.events ?? null,
        history.selection?.sessions ?? null,
        history.selection?.labels ?? null,
      ]
    : [];
  const all: (Fetched<unknown> | null)[] = [health, accounts, sources, pools, windows, ...parts];
  const metas: Meta[] = all.flatMap((x) => (x && x.ok ? [x.meta] : []));
  if (new Set(metas.map((m) => m.data_mode)).size > 1) {
    return { ok: false, reason: 'mode_mismatch', detail: 'mock 与 live 数据不能混用' };
  }
  const revisions = new Set(metas.map((m) => m.data_revision));
  if (revisions.size > 1) {
    return { ok: false, reason: 'revision_mismatch', detail: `data_revision: ${[...revisions].join(', ')}` };
  }

  return {
    ok: true,
    data: {
      meta,
      health: health.data,
      account,
      accounts: providerAccounts,
      sources,
      pools,
      pool,
      windows,
      selectedWindow,
      history,
      resolved: { pool: pool?.id ?? null, window: selectedWindow?.id ?? null },
      notices,
    },
  };
}

/**
 * 把一次整屏读取归类给刷新协调：
 * - unauthorized：任何部分 401（本应用会话失效）
 * - failed：基础信息读不到、服务不可达、后端错误、未读完、修订不一致 → 保留上一次成功的画面
 * - ok：其余（包括“没有导入”“样本未提供”这类有意义的结果）
 */
export function classifyLoad(r: LoadResult): 'ok' | 'failed' | 'unauthorized' {
  const bad = (f: Fetched<unknown> | null | undefined) =>
    !!f && !f.ok && (f.kind === 'unreachable' || f.kind === 'http_error' || f.kind === 'invalid_response' || f.kind === 'incomplete');
  const unauth = (f: Fetched<unknown> | null | undefined) => !!f && !f.ok && f.kind === 'unauthorized';
  if (!r.ok) {
    if (r.reason === 'base_unavailable') return unauth(r.detail) ? 'unauthorized' : 'failed';
    if (r.reason === 'revision_mismatch' || r.reason === 'mode_mismatch') return 'failed';
    return 'ok';
  }
  const d = r.data;
  const h = d.history;
  const parts: (Fetched<unknown> | null | undefined)[] = [
    d.sources,
    d.pools,
    d.windows,
    h?.snapshots,
    h?.series,
    h?.events,
    h?.sessions,
    h?.labels,
    h?.quota?.summaries,
    h?.quota?.windows,
    h?.quota?.snapshots,
    h?.selection?.series,
    h?.selection?.events,
    h?.selection?.sessions,
    h?.selection?.labels,
  ];
  if (parts.some(unauth)) return 'unauthorized';
  return parts.some(bad) ? 'failed' : 'ok';
}
