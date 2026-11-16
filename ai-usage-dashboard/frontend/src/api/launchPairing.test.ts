import { describe, expect, it, vi } from 'vitest';
import { AuthClient } from './auth';
import { consumeLaunchFragment, LaunchConnector, parseLaunchFragment } from './launchPairing';

// 测试用的格式正确但虚构的码（不是任何真实配对码）
const CODE = 'test_code_AAAAAAAAAAAAAAAAAAAAAA';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const SESSION = { data: { authenticated: true, csrf_token: 'csrf-test', expires_at: '2026-11-01T00:00:00Z' } };
const ERR = (code: string) => ({ error: { code, message: '', details: [] } });

/** 模拟后端：Cookie 会话状态 + 一次性码（只接受一次） */
function fakeServer(opts: { hasCookie?: boolean; acceptCode?: boolean } = {}) {
  let cookie = !!opts.hasCookie;
  let codeLeft = opts.acceptCode ?? true;
  const calls: { method: string; url: string; body?: string; headers?: HeadersInit }[] = [];
  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    calls.push({ method, url: String(input), body: init?.body as string | undefined, headers: init?.headers });
    if (method === 'GET') return cookie ? json(200, SESSION) : json(401, ERR('unauthorized'));
    if (method === 'POST') {
      const ok = codeLeft && JSON.parse(String(init?.body)).pairing_code === CODE;
      codeLeft = false;
      if (!ok) return json(401, ERR('invalid_pairing_code'));
      cookie = true;
      return json(201, SESSION);
    }
    return json(404, ERR('not_found'));
  }) as unknown as typeof fetch;
  return { impl, calls };
}

describe('parseLaunchFragment', () => {
  it('只接受恰好一个 launch_pairing 且格式有效', () => {
    expect(parseLaunchFragment(`#launch_pairing=${CODE}`)).toEqual({ present: true, code: CODE });
    expect(parseLaunchFragment('')).toEqual({ present: false, code: null });
    expect(parseLaunchFragment('#/gpt?view=day')).toEqual({ present: false, code: null });
  });

  it('无效 / 重复 / 夹带其他参数 / 路由形状：present 但不给码', () => {
    for (const h of [
      '#launch_pairing=short',
      `#launch_pairing=${CODE}&launch_pairing=${CODE}`,
      `#launch_pairing=${CODE}&x=1`,
      `#/gpt?launch_pairing=${CODE}`,
      '#launch_pairing=',
      `#launch_pairing=${CODE}%20`,
    ]) {
      expect(parseLaunchFragment(h), h).toEqual({ present: true, code: null });
    }
  });
});

describe('consumeLaunchFragment', () => {
  it('同步清除 fragment，地址回到不带 hash 的首页，不回显码', () => {
    const replaceState = vi.fn();
    const f = consumeLaunchFragment({ hash: `#launch_pairing=${CODE}`, pathname: '/', search: '' }, { replaceState });
    expect(f.code).toBe(CODE);
    expect(replaceState).toHaveBeenCalledWith(null, '', '/');
    expect(JSON.stringify(replaceState.mock.calls)).not.toContain(CODE);
  });

  it('无效参数也清除', () => {
    const replaceState = vi.fn();
    consumeLaunchFragment({ hash: '#launch_pairing=bad', pathname: '/index.html', search: '' }, { replaceState });
    expect(replaceState).toHaveBeenCalledWith(null, '', '/index.html');
  });

  it('普通路由不动', () => {
    const replaceState = vi.fn();
    expect(consumeLaunchFragment({ hash: '#/claude?view=day', pathname: '/', search: '' }, { replaceState }).present).toBe(false);
    expect(replaceState).not.toHaveBeenCalled();
  });
});

describe('LaunchConnector', () => {
  it('没有 Cookie：restore 401 后用启动码配对一次，沿用 Origin 同源 POST + X-Dashboard-Pairing', async () => {
    const { impl, calls } = fakeServer();
    const auth = new AuthClient(impl);
    const r = await new LaunchConnector({ present: true, code: CODE }).connect(auth);
    expect(r).toMatchObject({ kind: 'session', state: { status: 'authenticated' } });
    expect(calls.map((c) => c.method)).toEqual(['GET', 'POST']);
    expect(calls[1]!.url).toBe('/api/v1/auth/session');
    expect(calls[1]!.url).not.toContain(CODE);
    expect(JSON.stringify(calls[1]!.headers)).toContain('X-Dashboard-Pairing');
    expect(auth.hasCsrf).toBe(true);
  });

  it('已有 Cookie：不额外配对，丢弃启动码', async () => {
    const { impl, calls } = fakeServer({ hasCookie: true });
    const c = new LaunchConnector({ present: true, code: CODE });
    const r = await c.connect(new AuthClient(impl));
    expect(r).toMatchObject({ kind: 'session', state: { status: 'authenticated' } });
    expect(calls.map((x) => x.method)).toEqual(['GET']);
    expect(c.pending).toBe(false);
  });

  it('StrictMode 双挂载：两次 connect 共享同一个 promise，只 POST 一次', async () => {
    const { impl, calls } = fakeServer();
    const auth = new AuthClient(impl);
    const c = new LaunchConnector({ present: true, code: CODE });
    const [a, b] = await Promise.all([c.connect(auth), c.connect(auth)]);
    expect(a).toBe(b);
    expect(a).toMatchObject({ kind: 'session', state: { status: 'authenticated' } });
    expect(calls.filter((x) => x.method === 'POST')).toHaveLength(1);
  });

  it('结束后再检查只做普通 restore，不重放启动码', async () => {
    const { impl, calls } = fakeServer({ acceptCode: false });
    const auth = new AuthClient(impl);
    const c = new LaunchConnector({ present: true, code: CODE });
    expect(await c.connect(auth)).toEqual({ kind: 'launch_failed', reason: 'invalid_code' });
    expect(c.pending).toBe(false);
    expect(await c.connect(auth)).toEqual({ kind: 'session', state: { status: 'unpaired' } });
    expect(calls.filter((x) => x.method === 'POST')).toHaveLength(1);
  });

  it('无效启动链接：不发 POST，提示重新启动', async () => {
    const { impl, calls } = fakeServer();
    const r = await new LaunchConnector({ present: true, code: null }).connect(new AuthClient(impl));
    expect(r).toEqual({ kind: 'launch_failed', reason: 'malformed' });
    expect(calls.map((x) => x.method)).toEqual(['GET']);
  });

  it('没有启动信息：等同 restore', async () => {
    const { impl } = fakeServer();
    expect(await new LaunchConnector({ present: false, code: null }).connect(new AuthClient(impl))).toEqual({
      kind: 'session',
      state: { status: 'unpaired' },
    });
  });

  it('服务不可达：返回 unreachable，码已丢弃', async () => {
    const impl = vi.fn(async () => {
      throw new TypeError('network');
    }) as unknown as typeof fetch;
    const c = new LaunchConnector({ present: true, code: CODE });
    expect(await c.connect(new AuthClient(impl))).toEqual({ kind: 'session', state: { status: 'unreachable' } });
    expect(c.pending).toBe(false);
  });
});

describe('LaunchConnector：页面打开期间收到新的启动 fragment', () => {
  it('offer 后通知并可再连接一次；discard 丢弃', async () => {
    const { impl, calls } = fakeServer();
    const auth = new AuthClient(impl);
    const c = new LaunchConnector({ present: false, code: null });
    await c.connect(auth);
    const seen = vi.fn();
    c.onOffer(seen);
    c.offer({ present: true, code: CODE });
    expect(seen).toHaveBeenCalledOnce();
    expect(c.pending).toBe(true);
    expect(await c.connect(auth)).toMatchObject({ kind: 'session', state: { status: 'authenticated' } });
    expect(calls.filter((x) => x.method === 'POST')).toHaveLength(1);
    c.offer({ present: true, code: CODE });
    c.discard();
    expect(c.pending).toBe(false);
    c.offer({ present: false, code: null });
    expect(seen).toHaveBeenCalledTimes(2);
  });
});
