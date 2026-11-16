import catalogJson from '@mocks/catalog.json';
import {
  fetchAllPages,
  toQueryRecord,
  type BootstrapContext,
  type DataAdapter,
  type Fetched,
  type RequestDescriptor,
} from './adapter';
import { endpointPath, queryKey } from './normalizeQuery';
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

interface CatalogFixture {
  file: string;
  schema: string;
  note: string;
  method: string;
  path: string;
  query: Record<string, string | number>;
  status: number;
  scenario_id: string;
}

interface Catalog {
  data_mode: string;
  fixtures: CatalogFixture[];
  scenarios: Record<string, Record<string, unknown>>;
}

const catalog = catalogJson as unknown as Catalog;

/** 只匹配 contracts/mocks 下的 JSON；按需加载，不把契约其他文件打进运行时。 */
const fixtureLoaders = import.meta.glob<{ default: unknown }>(['@mocks/**/*.json', '!@mocks/catalog.json']);

function relativeFixturePath(globKey: string): string {
  const i = globKey.lastIndexOf('/mocks/');
  return i >= 0 ? globKey.slice(i + '/mocks/'.length) : globKey;
}

const loaderByFile = new Map<string, () => Promise<{ default: unknown }>>(
  Object.entries(fixtureLoaders).map(([k, load]) => [relativeFixturePath(k), load]),
);

/** health / accounts 属于 catalog 共享元数据，可在任一场景下复用；其他场景不做隐式回退。 */
const SHARED_SCENARIO = 'catalog';
const SHARED_PATHS = new Set(['/health', '/accounts']);

export interface MockAdapterOptions {
  /** 默认场景（不带 provider 的请求，及未在 scenarioByProvider 里列出的供应商） */
  scenarioId?: string;
  /** 按请求的 provider 选场景，例如 { gpt: 'gpt-observed', claude: 'claude-tokens' }；两个场景的数据不混在同一个响应里。 */
  scenarioByProvider?: Partial<Record<Provider, string>>;
  /** 测试时可注入加载器。 */
  loadFixture?: (file: string) => Promise<unknown>;
}

interface Envelope {
  data: unknown;
  meta: Meta;
  page?: Page;
}

export function findFixture(
  scenarioId: string,
  method: string,
  path: string,
  query: Record<string, string | number>,
): CatalogFixture | undefined {
  const ep = endpointPath(path);
  const key = queryKey(ep, query);
  return catalog.fixtures.find(
    (f) =>
      (f.scenario_id === scenarioId || (f.scenario_id === SHARED_SCENARIO && SHARED_PATHS.has(ep))) &&
      f.method === method &&
      endpointPath(f.path) === ep &&
      f.status >= 200 &&
      f.status < 300 &&
      queryKey(f.path, f.query) === key,
  );
}

export function listScenarios(): string[] {
  return Object.keys(catalog.scenarios ?? {});
}

/** states/ 下的局部状态样本（每条只是一份响应，不是整屏场景）。 */
export function stateFixtures(): CatalogFixture[] {
  return catalog.fixtures.filter((f) => f.file.startsWith('states/') && f.status >= 200 && f.status < 300);
}

export type { CatalogFixture };

export class MockAdapter implements DataAdapter {
  readonly mode = 'mock' as const;
  readonly scenarioId: string;
  private readonly byProvider: Partial<Record<Provider, string>>;
  private readonly load: (file: string) => Promise<unknown>;

  constructor(opts: MockAdapterOptions = {}) {
    this.scenarioId = opts.scenarioId ?? 'gpt-observed';
    this.byProvider = opts.scenarioByProvider ?? {};
    this.load =
      opts.loadFixture ??
      (async (file) => {
        const loader = loaderByFile.get(file);
        if (!loader) throw new Error(`fixture file not bundled: ${file}`);
        return (await loader()).default;
      });
  }

  private scenarioFor(provider: string | undefined): string {
    return (provider && this.byProvider[provider as Provider]) || this.scenarioId;
  }

  getBootstrapContext(provider?: Provider): BootstrapContext | null {
    const s = catalog.scenarios?.[this.scenarioFor(provider)];
    if (!s) return null;
    return {
      initialView: typeof s.initial_view === 'string' ? s.initial_view : null,
      provider: s.provider as Provider,
      account_id: String(s.account_id),
      products: (s.products as Product[]) ?? [],
      pool_id: s.pool_id == null ? null : String(s.pool_id),
      window_id: s.window_id == null ? null : String(s.window_id),
      from: String(s.from),
      to: String(s.to),
      bucket: s.bucket as Bucket,
      timezone: String(s.timezone),
    };
  }

  /** 按 catalog 条目原样请求；仍走同一个匹配器，场景必须与本适配器一致。 */
  getCatalogEntry(entry: CatalogFixture): Promise<Fetched<unknown>> {
    return this.get<unknown>(entry.path, entry.query);
  }

  private async get<T>(path: string, q: object): Promise<Fetched<T>> {
    const query = toQueryRecord(q);
    const request: RequestDescriptor = { method: 'GET', path, query };
    const fixture = findFixture(this.scenarioFor(query.provider), 'GET', path, query);
    if (!fixture) return { ok: false, kind: 'fixture_missing', request };
    let body: Envelope;
    try {
      body = (await this.load(fixture.file)) as Envelope;
    } catch (e) {
      return { ok: false, kind: 'invalid_response', request, detail: String(e) };
    }
    const meta = body?.meta;
    if (!meta || meta.data_mode !== 'mock') {
      return { ok: false, kind: 'invalid_response', request, detail: 'mock fixture without data_mode=mock' };
    }
    if (meta.scenario_id !== fixture.scenario_id) {
      return { ok: false, kind: 'invalid_response', request, detail: 'scenario_id mismatch' };
    }
    return { ok: true, data: body.data as T, meta, page: body.page };
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
    return fetchAllPages((cursor) => this.get<QuotaWindow[]>('/quota-windows', { ...q, cursor: cursor ?? q.cursor }));
  }
  getQuotaSnapshots(q: Parameters<DataAdapter['getQuotaSnapshots']>[0]) {
    return fetchAllPages((cursor) => this.get<QuotaSnapshot[]>('/quota-snapshots', { ...q, cursor: cursor ?? q.cursor }));
  }
  getQuotaWindowSummaries(q: Parameters<DataAdapter['getQuotaWindowSummaries']>[0]) {
    return fetchAllPages((cursor) =>
      this.get<QuotaWindowSummary[]>('/quota-window-summaries', { ...q, cursor: cursor ?? q.cursor }),
    );
  }
  getUsageSeries(q: Parameters<DataAdapter['getUsageSeries']>[0]) {
    return this.get<UsageSeries>('/usage-series', q);
  }
  getUsageEvents(q: Parameters<DataAdapter['getUsageEvents']>[0]) {
    return fetchAllPages((cursor) => this.get<UsageEvent[]>('/usage-events', { ...q, cursor: cursor ?? q.cursor }));
  }
  getSessions(q: Parameters<DataAdapter['getSessions']>[0]) {
    return fetchAllPages((cursor) => this.get<Session[]>('/sessions', { ...q, cursor: cursor ?? q.cursor }));
  }
  getLabels(q: Parameters<DataAdapter['getLabels']>[0]) {
    return fetchAllPages((cursor) => this.get<Label[]>('/labels', { ...q, cursor: cursor ?? q.cursor }));
  }
}
