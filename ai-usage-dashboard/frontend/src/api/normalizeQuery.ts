// 查询规范化：mock 匹配和将来 HTTP 请求共用，保证同义查询得到同一个键。

const DEFAULT_TIMEZONE = 'Asia/Tokyo';
const DEFAULT_LIMIT = '100';
const TIME_KEYS = new Set(['from', 'to']);
const LIST_PATHS = new Set([
  '/quota-windows',
  '/quota-snapshots',
  '/quota-window-summaries',
  '/usage-events',
  '/sessions',
  '/labels',
]);
/** 接受 timezone 参数的端点（health/accounts 不接受）。 */
const TIMEZONE_PATHS = new Set([
  '/sources',
  '/quota-pools',
  ...LIST_PATHS,
  '/usage-series',
]);

/** 去掉 /api/v1 前缀，得到契约里的端点路径。 */
export function endpointPath(path: string): string {
  return path.replace(/^\/api\/v1(?=\/)/, '');
}

export function normalizeQuery(path: string, query: Record<string, string | number>): Record<string, string> {
  const ep = endpointPath(path);
  const out: Record<string, string> = {};
  for (const [k, raw] of Object.entries(query)) {
    let v = String(raw);
    if (TIME_KEYS.has(k)) {
      const t = Date.parse(v);
      v = Number.isNaN(t) ? v : new Date(t).toISOString();
    } else if (k === 'products') {
      v = [...new Set(v.split(',').filter(Boolean))].sort().join(',');
    } else if (k === 'limit') {
      v = String(Number(v));
    }
    out[k] = v;
  }
  if (TIMEZONE_PATHS.has(ep) && out.timezone === undefined) out.timezone = DEFAULT_TIMEZONE;
  if (LIST_PATHS.has(ep) && out.limit === undefined) out.limit = DEFAULT_LIMIT;
  return out;
}

export function queryKey(path: string, query: Record<string, string | number>): string {
  const n = normalizeQuery(path, query);
  const entries = Object.keys(n)
    .sort()
    .map((k) => `${k}=${n[k]}`);
  return `${endpointPath(path)}?${entries.join('&')}`;
}
