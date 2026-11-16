import type {
  Account,
  Bucket,
  Health,
  Label,
  Meta,
  Page,
  Product,
  Provider,
  QuotaPool,
  QuotaSnapshot,
  QuotaWindow,
  QuotaWindowSummary,
  Session,
  Source,
  UsageEvent,
  UsageSeries,
} from './types';

/** 一次读取的结果。fixture_missing 只属于 mock 适配器，不冒充后端 404 或空数组。 */
export type Fetched<T> =
  | { ok: true; data: T; meta: Meta; page?: Page }
  | { ok: false; kind: 'fixture_missing'; request: RequestDescriptor }
  | { ok: false; kind: 'invalid_response'; request: RequestDescriptor; detail: string }
  | { ok: false; kind: 'incomplete'; request: RequestDescriptor; loadedRows: number }
  /** 以下仅 HTTP：未配对/会话失效、本地服务连不上、后端返回的错误体 */
  | { ok: false; kind: 'unauthorized'; request: RequestDescriptor }
  | { ok: false; kind: 'unreachable'; request: RequestDescriptor }
  | { ok: false; kind: 'http_error'; request: RequestDescriptor; status: number; code: string; message: string };

export interface RequestDescriptor {
  method: 'GET';
  path: string;
  query: Record<string, string>;
}

export interface AccountScope {
  provider: Provider;
  account_id: string;
}

export interface RangeQuery extends AccountScope {
  from: string;
  to: string;
  timezone?: string;
}

/** 额度接口不接受 products。 */
export interface PoolRangeQuery extends RangeQuery {
  pool_id: string;
}

export interface UsageQuery extends RangeQuery {
  /** undefined = 供应商下所有产品；数组按 OR 筛选。 */
  products?: readonly Product[];
}

export interface Paging {
  limit?: number;
  cursor?: string;
}

/** 模拟启动上下文：仅 mock 提供，解决“未知窗口范围 → 无法查询窗口”的循环。 */
export interface BootstrapContext {
  /** 场景建议的初始视图（catalog.scenarios.*.initial_view），可能缺省 */
  initialView: string | null;
  provider: Provider;
  account_id: string;
  products: Product[];
  /** 没有额度池的场景（如 claude-tokens）为 null，原样保留，不转成字符串 */
  pool_id: string | null;
  window_id: string | null;
  from: string;
  to: string;
  bucket: Bucket;
  timezone: string;
}

export interface DataAdapter {
  readonly mode: 'mock' | 'http';
  /** 模拟启动上下文（仅 mock）。provider 省略时为默认供应商。 */
  getBootstrapContext(provider?: Provider): BootstrapContext | null;
  getHealth(): Promise<Fetched<Health>>;
  getAccounts(): Promise<Fetched<Account[]>>;
  getSources(q: AccountScope & { timezone?: string }): Promise<Fetched<Source[]>>;
  getQuotaPools(q: AccountScope & { timezone?: string }): Promise<Fetched<QuotaPool[]>>;
  getQuotaWindows(q: PoolRangeQuery & Paging): Promise<Fetched<QuotaWindow[]>>;
  getQuotaSnapshots(
    q: PoolRangeQuery & Paging & { window_id?: string },
  ): Promise<Fetched<QuotaSnapshot[]>>;
  getQuotaWindowSummaries(q: PoolRangeQuery & Paging): Promise<Fetched<QuotaWindowSummary[]>>;
  getUsageSeries(q: UsageQuery & { bucket: Bucket }): Promise<Fetched<UsageSeries>>;
  getUsageEvents(
    q: UsageQuery & Paging & { session_id?: string; label_id?: string },
  ): Promise<Fetched<UsageEvent[]>>;
  getSessions(q: UsageQuery & Paging): Promise<Fetched<Session[]>>;
  getLabels(q: UsageQuery & Paging): Promise<Fetched<Label[]>>;
}

/** 把查询对象转成字符串表；undefined 字段省略，数组按逗号连接。 */
export function toQueryRecord(q: object): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null) continue;
    out[k] = Array.isArray(v) ? v.join(',') : String(v);
  }
  return out;
}

type ListFetcher<T> = (cursor: string | undefined) => Promise<Fetched<T[]>>;

/** 顺着游标读完所有页。meta 取第一页（第一页固定读取修订）。 */
export async function fetchAllPages<T>(fetchPage: ListFetcher<T>, maxPages = 50): Promise<Fetched<T[]>> {
  const first = await fetchPage(undefined);
  if (!first.ok) return first;
  const rows = [...first.data];
  let page = first.page;
  for (let i = 1; page?.has_more && page.next_cursor && i < maxPages; i++) {
    const next = await fetchPage(page.next_cursor);
    if (!next.ok) return next;
    if (next.meta.data_revision !== first.meta.data_revision) {
      return {
        ok: false,
        kind: 'invalid_response',
        request: { method: 'GET', path: '(pagination)', query: {} },
        detail: 'data_revision changed between pages',
      };
    }
    rows.push(...next.data);
    page = next.page;
  }
  // 还有下一页却没读完（达到页数上限或缺游标）：不能把截断结果当成完整数据。
  if (page?.has_more) {
    return {
      ok: false,
      kind: 'incomplete',
      request: { method: 'GET', path: '(pagination)', query: {} },
      loadedRows: rows.length,
    };
  }
  return { ok: true, data: rows, meta: first.meta, page };
}
