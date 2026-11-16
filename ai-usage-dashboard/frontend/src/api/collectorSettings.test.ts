import { describe, expect, it, vi } from 'vitest';
import type { AuthClient } from './auth';
import { CollectorClient, reasonText, type EnableRequest } from './collectorSettings';

const CSRF = 'c'.repeat(64);

function stubAuth() {
  return {
    csrfHeaders: () => ({ 'X-CSRF-Token': CSRF }),
    forget: vi.fn(),
  } as unknown as AuthClient & { forget: ReturnType<typeof vi.fn> };
}

const SETTINGS = {
  mode: 'settings',
  configured: true,
  settings_error: null,
  interval_seconds: 60,
  running: true,
  sources: [],
};

function reply(status: number, body: unknown) {
  return vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

const ENABLE: EnableRequest = {
  provider: 'gpt',
  enabled: true,
  location: 'standard',
  history: 'from_enable',
  confirm_scope: '~/.codex/sessions',
};

describe('CollectorClient', () => {
  it('saves once with CSRF and the confirmed scope', async () => {
    const fetchImpl = reply(200, { data: SETTINGS, meta: {} });
    const client = new CollectorClient(stubAuth(), fetchImpl);
    const r = await client.save(ENABLE);
    expect(r).toEqual({ ok: true, settings: SETTINGS });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(String(url)).toBe('/api/v1/collector-settings');
    expect(init?.method).toBe('POST');
    expect((init?.headers as Record<string, string>)['X-CSRF-Token']).toBe(CSRF);
    expect(JSON.parse(String(init?.body))).toEqual(ENABLE);
  });

  it('401 forgets CSRF and never resends the write', async () => {
    const auth = stubAuth();
    const fetchImpl = reply(401, { error: { code: 'unauthorized', message: 'x', details: [] }, meta: {} });
    const client = new CollectorClient(auth, fetchImpl);
    expect(await client.save(ENABLE)).toEqual({ ok: false, kind: 'unauthorized' });
    expect(auth.forget).toHaveBeenCalled();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('422 keeps only the reason code; message text is not shown', async () => {
    const fetchImpl = reply(422, {
      error: { code: 'invalid_body', message: '/Users/private/path', details: [{ field: 'custom_path', reason: 'path_too_broad' }] },
      meta: {},
    });
    const r = await new CollectorClient(stubAuth(), fetchImpl).save(ENABLE);
    expect(r).toEqual({ ok: false, kind: 'invalid', field: 'custom_path', reason: 'path_too_broad' });
    expect(reasonText('path_too_broad')).not.toContain('/Users');
    expect(reasonText('something_new')).toBe('设置未保存：内容不符合要求。');
  });

  it('unreachable save is unconfirmed, not failed', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('network');
    });
    expect(await new CollectorClient(stubAuth(), fetchImpl).save(ENABLE)).toEqual({ ok: false, kind: 'unconfirmed' });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('load is a plain GET without CSRF', async () => {
    const fetchImpl = reply(200, { data: SETTINGS, meta: {} });
    await new CollectorClient(stubAuth(), fetchImpl).load();
    const [, init] = fetchImpl.mock.calls[0]!;
    expect(init?.method).toBe('GET');
    expect((init?.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined();
  });
});
