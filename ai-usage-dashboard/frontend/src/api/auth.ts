// 本应用的浏览器会话（contracts/browser-auth.md）。与 OpenAI / Claude 登录无关。
// Cookie 为 HttpOnly，JS 读不到也不读；CSRF 值只放在这个对象的内存里，刷新后通过 GET 恢复。
import { errorBody, httpCall } from './http';

export type SessionState =
  | { status: 'authenticated'; expiresAt: string }
  | { status: 'unpaired' }
  | { status: 'unreachable' }
  | { status: 'error'; code: string; httpStatus: number };

export type PairResult =
  | { ok: true; expiresAt: string }
  | { ok: false; reason: 'invalid_code' | 'malformed' | 'forbidden' | 'unreachable' | 'error'; code?: string }
  | { ok: false; reason: 'rate_limited'; retryAfterSeconds: number | null };

interface SessionBody {
  data?: { authenticated?: boolean; csrf_token?: unknown; expires_at?: unknown };
}

/** 后端接受的配对码格式（security.py）。粘贴时去掉首尾空白。 */
const CODE_RE = /^[A-Za-z0-9_-]{22,128}$/;

export function isPairingCode(code: string): boolean {
  return CODE_RE.test(code);
}

export class AuthClient {
  private csrf: string | null = null;

  constructor(private readonly fetchImpl: typeof fetch = (...args) => fetch(...args)) {}

  get hasCsrf(): boolean {
    return this.csrf !== null;
  }

  /** 写入请求（标签等）用的请求头。 */
  csrfHeaders(): Record<string, string> {
    return this.csrf ? { 'X-CSRF-Token': this.csrf } : {};
  }

  private accept(body: unknown): string | null {
    const d = (body as SessionBody | null)?.data;
    if (d?.authenticated !== true || typeof d.csrf_token !== 'string' || typeof d.expires_at !== 'string') return null;
    this.csrf = d.csrf_token;
    return d.expires_at;
  }

  async restore(): Promise<SessionState> {
    const r = await httpCall('/auth/session', {}, this.fetchImpl);
    if (r.kind === 'unreachable') return { status: 'unreachable' };
    if (r.status === 401) {
      this.csrf = null;
      return { status: 'unpaired' };
    }
    if (r.status === 200) {
      const exp = this.accept(r.body);
      if (exp) return { status: 'authenticated', expiresAt: exp };
    }
    return { status: 'error', code: errorBody(r.body).code, httpStatus: r.status };
  }

  async pair(rawCode: string): Promise<PairResult> {
    const code = rawCode.trim();
    if (!CODE_RE.test(code)) return { ok: false, reason: 'malformed' };
    const r = await httpCall(
      '/auth/session',
      { method: 'POST', headers: { 'X-Dashboard-Pairing': '1' }, json: { pairing_code: code } },
      this.fetchImpl,
    );
    if (r.kind === 'unreachable') return { ok: false, reason: 'unreachable' };
    if (r.status === 201) {
      const exp = this.accept(r.body);
      return exp ? { ok: true, expiresAt: exp } : { ok: false, reason: 'error', code: 'invalid_session_body' };
    }
    const { code: errCode } = errorBody(r.body);
    if (r.status === 429) {
      const ra = Number(r.headers.get('Retry-After'));
      return { ok: false, reason: 'rate_limited', retryAfterSeconds: Number.isFinite(ra) && ra > 0 ? ra : null };
    }
    if (r.status === 401) return { ok: false, reason: 'invalid_code', code: errCode };
    if (r.status === 422) return { ok: false, reason: 'malformed', code: errCode };
    if (r.status === 403) return { ok: false, reason: 'forbidden', code: errCode };
    return { ok: false, reason: 'error', code: errCode };
  }

  /** 撤销本应用的浏览器会话（不是退出供应商账号）。 */
  async logout(): Promise<boolean> {
    const r = await httpCall('/auth/session', { method: 'DELETE', headers: this.csrfHeaders() }, this.fetchImpl);
    this.csrf = null;
    return r.kind === 'response' && (r.status === 204 || r.status === 401);
  }

  /** 会话在别处失效（数据请求 401）时清掉内存里的 CSRF。 */
  forget(): void {
    this.csrf = null;
  }
}
