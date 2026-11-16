// HTTP 适配器：同源 /api/v1，Cookie 会话由浏览器自动携带；构造时不发请求。
import {
  fetchAllPages,
  toQueryRecord,
  type DataAdapter,
  type Fetched,
  type RequestDescriptor,
} from './adapter';
import { errorBody, httpCall } from './http';
import type {
  Account,
  Health,
  Label,
  Meta,
  Page,
  QuotaPool,
  QuotaSnapshot,
  QuotaWindow,
  QuotaWindowSummary,
  Session,
  Source,
  UsageEvent,
  UsageSeries,
} from './types';

interface Envelope {
  data: unknown;
  meta: Meta;
  page?: Page;
}

export interface HttpAdapterOptions {
  fetchImpl?: typeof fetch;
  /** 任何数据请求返回 401（未配对或会话失效）时调用，用于回到配对界面。 */
  onUnauthorized?: () => void;
}

export class HttpAdapter implements DataAdapter {
  readonly mode = 'http' as const;
  private readonly fetchImpl: typeof fetch;
  onUnauthorized: (() => void) | undefined;

  constructor(opts: HttpAdapterOptions = {}) {
    this.fetchImpl = opts.fetchImpl ?? ((...args) => fetch(...args));
    this.onUnauthorized = opts.onUnauthorized;
  }

  /** 真实服务没有模拟启动上下文；当前窗口按 as_of 查询（见 loadDashboard）。 */
  getBootstrapContext() {
    return null;
  }

  private async get<T>(path: string, q: object): Promise<Fetched<T>> {
    const query = toQueryRecord(q);
    const request: RequestDescriptor = { method: 'GET', path, query };
    const qs = new URLSearchParams(query).toString();
    const r = await httpCall(qs ? `${path}?${qs}` : path, {}, this.fetchImpl);
    if (r.kind === 'unreachable') return { ok: false, kind: 'unreachable', request };
    if (r.status === 401) {
      this.onUnauthorized?.();
      return { ok: false, kind: 'unauthorized', request };
    }
    if (r.status !== 200) {
      const e = errorBody(r.body);
      return { ok: false, kind: 'http_error', request, status: r.status, ...e };
    }
    const body = r.body as Envelope | null;
    if (!body || typeof body !== 'object' || !body.meta || !('data' in body)) {
      return { ok: false, kind: 'invalid_response', request, detail: 'response is not a data envelope' };
    }
    // 真实服务只能返回 live；不与 mock 混用。
    if (body.meta.data_mode !== 'live') {
      return { ok: false, kind: 'invalid_response', request, detail: `unexpected data_mode=${body.meta.data_mode}` };
    }
    return { ok: true, data: body.data as T, meta: body.meta, page: body.page };
  }

  /** 读完所有分页；游标失效（409 cursor_expired）时从第一页重读一次。 */
  private async list<T>(path: string, q: object & { cursor?: string }): Promise<Fetched<T[]>> {
    const run = () => fetchAllPages((cursor) => this.get<T[]>(path, { ...q, cursor: cursor ?? q.cursor }));
    const first = await run();
    if (!first.ok && first.kind === 'http_error' && first.status === 409 && first.code === 'cursor_expired') {
      return run();
    }
    return first;
  }

  getHealth() {
    return this.get<Health>('/health', {});
  }
  getAccounts() {
    return this.get<Account[]>('/accounts', {});
  }
  getSources(q: Parameters<DataAdapter['getSources']>[0]) {
    return this.get<Source[]>('/sources', q);
  }
  getQuotaPools(q: Parameters<DataAdapter['getQuotaPools']>[0]) {
    return this.get<QuotaPool[]>('/quota-pools', q);
  }
  getQuotaWindows(q: Parameters<DataAdapter['getQuotaWindows']>[0]) {
    return this.list<QuotaWindow>('/quota-windows', q);
  }
  getQuotaSnapshots(q: Parameters<DataAdapter['getQuotaSnapshots']>[0]) {
    return this.list<QuotaSnapshot>('/quota-snapshots', q);
  }
  getQuotaWindowSummaries(q: Parameters<DataAdapter['getQuotaWindowSummaries']>[0]) {
    return this.list<QuotaWindowSummary>('/quota-window-summaries', q);
  }
  getUsageSeries(q: Parameters<DataAdapter['getUsageSeries']>[0]) {
    return this.get<UsageSeries>('/usage-series', q);
  }
  getUsageEvents(q: Parameters<DataAdapter['getUsageEvents']>[0]) {
    return this.list<UsageEvent>('/usage-events', q);
  }
  getSessions(q: Parameters<DataAdapter['getSessions']>[0]) {
    return this.list<Session>('/sessions', q);
  }
  getLabels(q: Parameters<DataAdapter['getLabels']>[0]) {
    return this.list<Label>('/labels', q);
  }
}
