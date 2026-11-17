import { t as translate } from "../i18n";
// 标签写入（POST / PATCH / DELETE），依据 docs/label-editing-handoff.md。
// - 所有写入带 X-CSRF-Token（AuthClient 内存值），Cookie 由浏览器自动携带。
// - 网络中断 / 服务不可达 = 结果未确认，不是失败；不自动换键、不自动拿新版本覆盖。
// - 未确认的创建请求（client_request_id + 原请求体）只保存在本对象内存里，不写浏览器存储或日志。
import type { AuthClient } from './auth';
import { errorBody, httpCall } from './http';
import type { Label, Product, Provider } from './types';
import type { components } from './schema.gen';

export type LabelTarget = components['schemas']['LabelTarget'];
export type LabelCreateBody = components['schemas']['LabelCreate'];

export type WriteOutcome =
  /** 201 首次创建 / 200 等价重试 / PATCH 200：采用服务端返回的规范化标签 */
  | { ok: true; label: Label; replayed: boolean }
  /** DELETE 204 */
  | { ok: true; label: null; replayed: false }
  | { ok: false; kind: 'unconfirmed' }
  | { ok: false; kind: 'unauthorized' }
  | { ok: false; kind: 'csrf_invalid'; restored: boolean }
  | { ok: false; kind: 'forbidden'; code: string }
  | { ok: false; kind: 'not_found' }
  | { ok: false; kind: 'idempotency_conflict' }
  | { ok: false; kind: 'revision_conflict' }
  | { ok: false; kind: 'invalid'; fields: { field: string; reason: string }[] }
  | { ok: false; kind: 'precondition_required' }
  | { ok: false; kind: 'rate_limited'; retryAfterSeconds: number | null }
  | { ok: false; kind: 'error'; status: number; code: string };

/** 一次创建操作：同一操作重试必须用同一个 ID 和同一份请求体。 */
export interface PendingCreate {
  body: LabelCreateBody;
  /** 上一次提交的结果未确认（网络中断等） */
  unconfirmed: boolean;
}

export const NAME_MAX = 80;

/** 名称按 Unicode 码点计 1–80，不能全是空白（后端去首尾空白）。返回错误文字或 null。 */
export function validateName(name: string): string | null {
  const trimmed = name.trim();
  if (trimmed.length === 0) return translate("请输入名称（不能全是空白）。");
  if (Array.from(trimmed).length > NAME_MAX) return translate("名称最多 {0} 个字。", NAME_MAX);
  return null;
}

export function nameLength(name: string): number {
  return Array.from(name.trim()).length;
}

export function ifMatch(revision: number): string {
  return `"${revision}"`;
}

function newRequestId(): string {
  return crypto.randomUUID();
}

export class LabelWriter {
  /** 当前未确认 / 待重试的创建操作（仅内存）。换供应商或账户时由调用方丢弃。 */
  pending: PendingCreate | null = null;
  /** 会话失效时保存的编辑器状态（仅内存），重新配对后用来恢复表单 */
  resume: { request: unknown; name: string; products?: Product[] } | null = null;

  constructor(
    private readonly auth: AuthClient,
    private readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  /** 开始一次新创建：生成新的 client_request_id，后续重试都沿用它。 */
  beginCreate(input: { provider: Provider; account_id: string; name: string; target: LabelTarget }): PendingCreate {
    this.pending = {
      body: { ...input, client_request_id: newRequestId() },
      unconfirmed: false,
    };
    return this.pending;
  }

  /** 提交（或用同键同体再次确认）当前创建操作。 */
  async submitCreate(): Promise<WriteOutcome> {
    const p = this.pending;
    if (!p) throw new Error('no pending create');
    const r = await this.send('POST', '/labels', p.body, {});
    if (!r.ok && r.kind === 'unconfirmed') p.unconfirmed = true;
    // 成功、或服务端明确拒绝（不会因为同键重试而改变的结果）后，这次操作结束
    if (r.ok || (r.kind !== 'unconfirmed' && r.kind !== 'unauthorized' && r.kind !== 'csrf_invalid' && r.kind !== 'rate_limited')) {
      this.pending = null;
    }
    return r;
  }

  discardCreate(): void {
    this.pending = null;
  }

  rename(id: string, revision: number, name: string): Promise<WriteOutcome> {
    return this.send('PATCH', `/labels/${encodeURIComponent(id)}`, { name }, { 'If-Match': ifMatch(revision) });
  }

  /** 重新指定完整关联目标（不能只传 from 或 to）。 */
  retarget(id: string, revision: number, target: LabelTarget): Promise<WriteOutcome> {
    return this.send('PATCH', `/labels/${encodeURIComponent(id)}`, { target }, { 'If-Match': ifMatch(revision) });
  }

  remove(id: string, revision: number): Promise<WriteOutcome> {
    return this.send('DELETE', `/labels/${encodeURIComponent(id)}`, undefined, { 'If-Match': ifMatch(revision) });
  }

  private async send(
    method: 'POST' | 'PATCH' | 'DELETE',
    path: string,
    json: unknown,
    headers: Record<string, string>,
  ): Promise<WriteOutcome> {
    const r = await httpCall(path, { method, json, headers: { ...headers, ...this.auth.csrfHeaders() } }, this.fetchImpl);
    if (r.kind === 'unreachable') return { ok: false, kind: 'unconfirmed' };
    const { status, body } = r;
    if (status === 204) return { ok: true, label: null, replayed: false };
    if (status === 200 || status === 201) {
      const label = (body as { data?: Label } | null)?.data;
      if (!label || typeof label.id !== 'string') return { ok: false, kind: 'error', status, code: 'invalid_response' };
      return { ok: true, label, replayed: method === 'POST' && status === 200 };
    }
    const { code } = errorBody(body);
    switch (status) {
      case 401:
        this.auth.forget();
        return { ok: false, kind: 'unauthorized' };
      case 403:
        if (code === 'csrf_invalid') {
          // 当前写入未获验证：恢复会话、刷新内存 CSRF，再由用户决定是否重新提交
          const s = await this.auth.restore();
          return { ok: false, kind: 'csrf_invalid', restored: s.status === 'authenticated' };
        }
        return { ok: false, kind: 'forbidden', code };
      case 404:
        return { ok: false, kind: 'not_found' };
      case 409:
        return code === 'idempotency_conflict' ? { ok: false, kind: 'idempotency_conflict' } : { ok: false, kind: 'error', status, code };
      case 412:
        return { ok: false, kind: 'revision_conflict' };
      case 422: {
        const details = (body as { error?: { details?: { field?: unknown; reason?: unknown }[] } } | null)?.error?.details ?? [];
        return {
          ok: false,
          kind: 'invalid',
          fields: details.map((d) => ({ field: String(d.field ?? ''), reason: String(d.reason ?? '') })),
        };
      }
      case 428:
        return { ok: false, kind: 'precondition_required' };
      case 429: {
        const ra = Number(r.headers.get('Retry-After'));
        return { ok: false, kind: 'rate_limited', retryAfterSeconds: Number.isFinite(ra) && ra > 0 ? ra : null };
      }
      default:
        return { ok: false, kind: 'error', status, code };
    }
  }
}

/** “全部”转成该供应商明确的产品集合；products 不能为 null 或空数组。 */
export function explicitProducts(selected: readonly Product[] | null, all: readonly Product[]): Product[] {
  const list = selected && selected.length > 0 ? selected : all;
  return [...new Set(list)];
}
