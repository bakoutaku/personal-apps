// 同源请求的最小封装：相对路径、credentials=same-origin，不带 Authorization，不读 Cookie。

export const API_BASE = '/api/v1';

export type HttpResult =
  | { kind: 'response'; status: number; body: unknown; headers: Headers }
  | { kind: 'unreachable' };

export interface HttpInit {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  headers?: Record<string, string>;
  json?: unknown;
}

/** 代理或网关在后端不可达时返回的状态。 */
const GATEWAY = new Set([502, 503, 504]);

export async function httpCall(path: string, init: HttpInit = {}, fetchImpl: typeof fetch = fetch): Promise<HttpResult> {
  const headers: Record<string, string> = { Accept: 'application/json', ...init.headers };
  let body: string | undefined;
  if (init.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetchImpl(`${API_BASE}${path}`, {
      method: init.method ?? 'GET',
      headers,
      body,
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
    });
  } catch {
    return { kind: 'unreachable' };
  }
  if (res.status === 204) return { kind: 'response', status: 204, body: null, headers: res.headers };
  let parsed: unknown = null;
  try {
    parsed = await res.json();
  } catch {
    // 开发代理在后端未启动时会返回非 JSON 的 5xx
    if (res.status >= 500 || GATEWAY.has(res.status)) return { kind: 'unreachable' };
    parsed = null;
  }
  return { kind: 'response', status: res.status, body: parsed, headers: res.headers };
}

export function errorBody(body: unknown): { code: string; message: string } {
  const e = (body as { error?: { code?: unknown; message?: unknown } } | null)?.error;
  return {
    code: typeof e?.code === 'string' ? e.code : 'unknown',
    message: typeof e?.message === 'string' ? e.message : '',
  };
}
