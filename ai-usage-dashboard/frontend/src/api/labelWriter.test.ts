import workflow from '@mocks/label-workflow/workflow.json';
import { describe, expect, it, vi } from 'vitest';
import type { AuthClient } from './auth';
import { explicitProducts, LabelWriter, nameLength, validateName, type LabelCreateBody, type LabelTarget } from './labelWriter';

const fixtures = import.meta.glob<{ default: unknown }>('@mocks/label-workflow/*.json', { eager: true });
function fixture(file: string | null): unknown {
  if (!file) return null;
  const key = Object.keys(fixtures).find((k) => k.endsWith(file.replace('label-workflow/', '/')));
  return key ? fixtures[key]!.default : null;
}

const CSRF = 'c'.repeat(64);

function stubAuth(csrf: string | null) {
  return {
    csrfHeaders: () => (csrf ? { 'X-CSRF-Token': csrf } : {}),
    forget: vi.fn(),
    restore: vi.fn(async () => ({ status: 'authenticated', expiresAt: '' })),
  } as unknown as AuthClient & { forget: ReturnType<typeof vi.fn>; restore: ReturnType<typeof vi.fn> };
}

interface Case {
  id: string;
  request: { method: string; path: string; headers: Record<string, string>; body: unknown; auth: string };
  expected: { status: number; response_file: string | null; error_code: string | null; headers: Record<string, string> };
}

const LABEL_ID = 'label_test_1';

/** 按 workflow 的期望状态回应；同时记录前端实际发出的请求。 */
function respondWith(c: Case) {
  const calls: { url: string; init: RequestInit }[] = [];
  const impl = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    if (c.expected.status === 204) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(fixture(c.expected.response_file)), {
      status: c.expected.status,
      headers: { 'Content-Type': 'application/json', ...c.expected.headers },
    });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

const expectedKind: Record<number, string> = {
  401: 'unauthorized',
  403: 'csrf_invalid',
  404: 'not_found',
  409: 'idempotency_conflict',
  412: 'revision_conflict',
  422: 'invalid',
  428: 'precondition_required',
};

describe('标签写入：逐条重放 contracts/mocks/label-workflow/workflow.json', () => {
  const cases = (workflow as { cases: Case[] }).cases;

  for (const c of cases) {
    const body = c.request.body as Record<string, unknown> | null;
    // 前端写入器不会构造的请求（缺 If-Match、带 provider、半个 target）只用来说明后端行为，这里跳过
    const producible =
      c.request.method === 'POST' ||
      c.request.method === 'DELETE' ||
      (c.request.method === 'PATCH' && 'If-Match' in c.request.headers && body !== null && Object.keys(body).every((k) => k === 'name' || k === 'target') && (!('target' in body) || (body.target as { kind: string }).kind === 'session' || 'to' in (body.target as object)));
    (producible ? it : it.skip)(`${c.id} → ${c.expected.status}`, async () => {
      const csrf = c.request.auth === 'cookie_csrf' ? CSRF : null;
      const auth = stubAuth(csrf);
      const { impl, calls } = respondWith(c);
      const w = new LabelWriter(auth, impl);
      const revision = Number((c.request.headers['If-Match'] ?? '"0"').replace(/"/g, ''));
      let r;
      if (c.request.method === 'POST') {
        w.pending = { body: body as unknown as LabelCreateBody, unconfirmed: false };
        r = await w.submitCreate();
      } else if (c.request.method === 'DELETE') {
        r = await w.remove(LABEL_ID, revision);
      } else if (body && 'name' in body) {
        r = await w.rename(LABEL_ID, revision, String(body.name));
      } else {
        r = await w.retarget(LABEL_ID, revision, (body as { target: LabelTarget }).target);
      }

      // 发出的请求与 workflow 一致
      const sent = calls[0]!;
      expect(sent.init.method).toBe(c.request.method);
      expect(sent.url).toBe(c.request.path.replace('{id}', LABEL_ID));
      const h = sent.init.headers as Record<string, string>;
      if (csrf) expect(h['X-CSRF-Token']).toBe(CSRF);
      else expect(h['X-CSRF-Token']).toBeUndefined();
      if (c.request.method !== 'POST') expect(h['If-Match']).toBe(c.request.headers['If-Match']);
      expect(sent.init.body ?? null).toBe(body === null ? null : JSON.stringify(body));

      // 结果分类
      if (c.expected.status >= 200 && c.expected.status < 300) {
        expect(r.ok).toBe(true);
        if (r.ok && c.expected.status !== 204) {
          expect(r.label?.id).toBeTruthy();
          expect(r.replayed).toBe(c.request.method === 'POST' && c.expected.status === 200);
        }
      } else {
        expect(r).toMatchObject({ ok: false, kind: expectedKind[c.expected.status] });
      }
      if (c.expected.status === 401) expect(auth.forget).toHaveBeenCalled();
      if (c.expected.error_code === 'csrf_invalid') expect(auth.restore).toHaveBeenCalled();
    });
  }
});

describe('标签写入：未确认与重试', () => {
  const input = {
    provider: 'gpt' as const,
    account_id: 'acct',
    name: '任务',
    target: { kind: 'range' as const, from: '2026-10-22T03:00:00.000Z', to: '2026-10-22T04:00:00.000Z', products: ['codex' as const] },
  };

  it('网络中断：标记未确认，保留同一个 client_request_id 和请求体；再次确认时原样发送', async () => {
    let fail = true;
    const bodies: string[] = [];
    const impl = vi.fn(async (_u: RequestInfo | URL, init?: RequestInit) => {
      bodies.push(String(init?.body));
      if (fail) throw new TypeError('network');
      return new Response(JSON.stringify({ data: { id: 'l1', revision: 1 } }), { status: 200 });
    }) as unknown as typeof fetch;
    const w = new LabelWriter(stubAuth(CSRF), impl);
    const p = w.beginCreate(input);
    const r1 = await w.submitCreate();
    expect(r1).toEqual({ ok: false, kind: 'unconfirmed' });
    expect(w.pending?.unconfirmed).toBe(true);
    expect(w.pending?.body.client_request_id).toBe(p.body.client_request_id);
    fail = false;
    const r2 = await w.submitCreate();
    expect(r2).toMatchObject({ ok: true, replayed: true });
    expect(bodies[0]).toBe(bodies[1]);
    expect(w.pending).toBeNull();
  });

  it('409 后结束这次操作，不自动换键重放', async () => {
    const impl = vi.fn(async () => new Response(JSON.stringify({ error: { code: 'idempotency_conflict' } }), { status: 409 })) as unknown as typeof fetch;
    const w = new LabelWriter(stubAuth(CSRF), impl);
    w.beginCreate(input);
    expect(await w.submitCreate()).toMatchObject({ kind: 'idempotency_conflict' });
    expect(impl).toHaveBeenCalledTimes(1);
    expect(w.pending).toBeNull();
  });

  it('每次开始新创建都换新的 client_request_id', () => {
    const w = new LabelWriter(stubAuth(CSRF));
    const a = w.beginCreate(input).body.client_request_id;
    const b = w.beginCreate(input).body.client_request_id;
    expect(a).not.toBe(b);
  });

  it('改名 / 删除网络中断：只报告未确认，不自动重试', async () => {
    const impl = vi.fn(async () => {
      throw new TypeError('network');
    }) as unknown as typeof fetch;
    const w = new LabelWriter(stubAuth(CSRF), impl);
    expect(await w.rename('l1', 2, 'x')).toEqual({ ok: false, kind: 'unconfirmed' });
    expect(await w.remove('l1', 2)).toEqual({ ok: false, kind: 'unconfirmed' });
    expect(impl).toHaveBeenCalledTimes(2);
  });
});

describe('名称与产品', () => {
  it('按码点计数，emoji 算一个字；去首尾空白；全空白不行', () => {
    expect(nameLength('  任务  ')).toBe(2);
    expect(validateName('😀'.repeat(80))).toBeNull();
    expect(validateName('😀'.repeat(81))).not.toBeNull();
    expect(validateName('   ')).not.toBeNull();
  });
  it('“全部”转成明确的产品集合，不传 null 或空数组', () => {
    expect(explicitProducts(null, ['chat', 'work', 'codex'])).toEqual(['chat', 'work', 'codex']);
    expect(explicitProducts(['codex'], ['chat', 'work', 'codex'])).toEqual(['codex']);
  });
});
