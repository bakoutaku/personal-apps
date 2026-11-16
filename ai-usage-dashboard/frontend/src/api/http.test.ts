import { describe, expect, it, vi } from 'vitest';
import { AuthClient } from './auth';
import { HttpAdapter } from './httpAdapter';

const liveMeta = {
  api_version: '0.2.0',
  data_mode: 'live',
  as_of: '2026-10-22T08:00:00.000Z',
  data_revision: 7,
  scenario_id: null,
  timezone: 'Asia/Tokyo',
  stale_after_seconds: 900,
  warnings: [],
};

interface Call {
  url: string;
  init: RequestInit;
}

function fakeFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init: init ?? {} });
    return handler(url, init ?? {});
  }) as unknown as typeof fetch;
  return { impl, calls };
}

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

const scope = { provider: 'gpt', account_id: 'acct_x' } as const;

describe('HttpAdapter', () => {
  it('同源相对路径、same-origin、不带 Authorization；接受 live 数据', async () => {
    const { impl, calls } = fakeFetch(() => json(200, { data: [], meta: liveMeta }));
    const r = await new HttpAdapter({ fetchImpl: impl }).getSources(scope);
    expect(r.ok).toBe(true);
    expect(calls[0]!.url).toBe('/api/v1/sources?provider=gpt&account_id=acct_x');
    expect(calls[0]!.init.credentials).toBe('same-origin');
    expect(JSON.stringify(calls[0]!.init.headers)).not.toMatch(/authorization/i);
  });

  it('HTTP 返回 mock 数据时拒绝，不混用', async () => {
    const { impl } = fakeFetch(() => json(200, { data: [], meta: { ...liveMeta, data_mode: 'mock' } }));
    const r = await new HttpAdapter({ fetchImpl: impl }).getSources(scope);
    expect(r).toMatchObject({ ok: false, kind: 'invalid_response' });
  });

  it('401 → unauthorized 并通知回到配对', async () => {
    const onUnauthorized = vi.fn();
    const { impl } = fakeFetch(() => json(401, { error: { code: 'unauthorized', message: '', details: [] }, meta: liveMeta }));
    const r = await new HttpAdapter({ fetchImpl: impl, onUnauthorized }).getAccounts();
    expect(r).toMatchObject({ ok: false, kind: 'unauthorized' });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it('网络失败或代理非 JSON 5xx → unreachable', async () => {
    const a = await new HttpAdapter({ fetchImpl: fakeFetch(() => Promise.reject(new TypeError('x'))).impl }).getHealth();
    expect(a).toMatchObject({ ok: false, kind: 'unreachable' });
    const b = await new HttpAdapter({ fetchImpl: fakeFetch(() => new Response('proxy error', { status: 500 })).impl }).getHealth();
    expect(b).toMatchObject({ ok: false, kind: 'unreachable' });
  });

  it('422 等错误体 → http_error，保留 code', async () => {
    const { impl } = fakeFetch(() => json(422, { error: { code: 'invalid_query', message: 'too big', details: [] }, meta: liveMeta }));
    const r = await new HttpAdapter({ fetchImpl: impl }).getUsageSeries({ ...scope, from: 'a', to: 'b', bucket: '15m' });
    expect(r).toMatchObject({ ok: false, kind: 'http_error', status: 422, code: 'invalid_query' });
  });

  it('分页游标 409 时从第一页重读一次', async () => {
    let round = 0;
    const { impl, calls } = fakeFetch((url) => {
      if (!url.includes('cursor=')) {
        round++;
        return json(200, { data: [round], meta: liveMeta, page: { has_more: true, next_cursor: `c${round}` } });
      }
      if (round === 1) return json(409, { error: { code: 'cursor_expired', message: '', details: [] }, meta: liveMeta });
      return json(200, { data: [99], meta: liveMeta, page: { has_more: false, next_cursor: null } });
    });
    const r = await new HttpAdapter({ fetchImpl: impl }).getLabels({ ...scope, from: 'a', to: 'b' });
    expect(r.ok && r.data).toEqual([2, 99]);
    expect(calls).toHaveLength(4);
  });
});

describe('AuthClient', () => {
  const session = { authenticated: true, auth_mode: 'cookie_session', csrf_token: 'f'.repeat(64), expires_at: '2026-10-29T08:00:00.000Z', idle_timeout_seconds: 86400 };
  const code = 'A'.repeat(32);

  it('GET 401 → unpaired；200 → 恢复并把 CSRF 放内存', async () => {
    const a = new AuthClient(fakeFetch(() => json(401, { error: { code: 'unauthorized' } })).impl);
    expect(await a.restore()).toEqual({ status: 'unpaired' });
    const b = new AuthClient(fakeFetch(() => json(200, { data: session, meta: liveMeta })).impl);
    expect((await b.restore()).status).toBe('authenticated');
    expect(b.csrfHeaders()).toEqual({ 'X-CSRF-Token': 'f'.repeat(64) });
  });

  it('配对：JSON + X-Dashboard-Pairing，去掉空白；201 成功', async () => {
    const { impl, calls } = fakeFetch(() => json(201, { data: session, meta: liveMeta }));
    const r = await new AuthClient(impl).pair(`  ${code}\n`);
    expect(r.ok).toBe(true);
    const init = calls[0]!.init;
    expect(init.method).toBe('POST');
    expect(init.body).toBe(JSON.stringify({ pairing_code: code }));
    expect(init.headers).toMatchObject({ 'X-Dashboard-Pairing': '1', 'Content-Type': 'application/json' });
    expect(calls[0]!.url).toBe('/api/v1/auth/session');
  });

  it('格式不对的码不发请求', async () => {
    const { impl, calls } = fakeFetch(() => json(201, {}));
    expect(await new AuthClient(impl).pair('123456')).toMatchObject({ ok: false, reason: 'malformed' });
    expect(calls).toHaveLength(0);
  });

  it('401 码无效；429 读 Retry-After', async () => {
    const bad = await new AuthClient(fakeFetch(() => json(401, { error: { code: 'pairing_invalid' } })).impl).pair(code);
    expect(bad).toMatchObject({ ok: false, reason: 'invalid_code' });
    const limited = await new AuthClient(fakeFetch(() => json(429, { error: { code: 'too_many_attempts' } }, { 'Retry-After': '120' })).impl).pair(code);
    expect(limited).toEqual({ ok: false, reason: 'rate_limited', retryAfterSeconds: 120 });
  });

  it('退出带 X-CSRF-Token 的 DELETE，之后清掉 CSRF', async () => {
    const { impl, calls } = fakeFetch((_, init) =>
      init.method === 'DELETE' ? new Response(null, { status: 204 }) : json(200, { data: session, meta: liveMeta }),
    );
    const a = new AuthClient(impl);
    await a.restore();
    expect(await a.logout()).toBe(true);
    expect(calls[1]!.init.method).toBe('DELETE');
    expect(calls[1]!.init.headers).toMatchObject({ 'X-CSRF-Token': 'f'.repeat(64) });
    expect(a.hasCsrf).toBe(false);
  });
});
