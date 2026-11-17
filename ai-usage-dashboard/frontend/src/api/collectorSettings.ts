import { t as translate } from "../i18n";
// 本机自动采集设置（contracts/collector-settings.md）。不属于 v0.2 数据契约，类型在这里手写。
// - 读取 GET /collector-settings；保存 POST /collector-settings，带 X-CSRF-Token。
// - 401 不自动重发：表单草稿只留在本对象内存里，重新配对后恢复，等用户再次点击保存。
// - 页面只显示后端给出的 ~/… 形式；错误只按 reason 代码翻译，不显示后端原文或路径。
import type { AuthClient } from './auth';
import { errorBody, httpCall } from './http';
import type { Provider } from './types';

export type CollectorMode = 'settings' | 'startup_config' | 'disabled';
export type HistoryChoice = 'from_enable' | 'import_history';

export interface CollectorSource {
  provider: Provider;
  product: 'codex' | 'code';
  enabled: boolean;
  location: 'standard' | 'custom' | 'startup_config';
  display_path: string | null;
  standard_display_path: string;
  history: HistoryChoice;
  enabled_at: string | null;
  boundary_status: 'not_applicable' | 'pending' | 'ready' | 'missing';
  source_id: string | null;
  connection_status: 'not_configured' | 'available' | 'error' | 'disabled' | null;
  error_code: string | null;
  consecutive_failure_count: number | null;
  retry_mode: 'automatic' | 'manual' | 'disabled' | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_record_at: string | null;
  next_attempt_at: string | null;
}

export interface CollectorSettings {
  mode: CollectorMode;
  configured: boolean;
  settings_error: string | null;
  interval_seconds: number;
  running: boolean;
  sources: CollectorSource[];
}

export type EnableRequest = {
  provider: Provider;
  enabled: true;
  location: 'standard' | 'custom';
  custom_path?: string;
  history: HistoryChoice;
  /** 页面上展示给用户、用户已勾选确认的读取范围，原样回传 */
  confirm_scope: string;
};
export type DisableRequest = { provider: Provider; enabled: false };
export type SettingsRequest = EnableRequest | DisableRequest;

export type SettingsOutcome =
  | { ok: true; settings: CollectorSettings }
  | { ok: false; kind: 'unauthorized' }
  | { ok: false; kind: 'csrf_invalid' }
  | { ok: false; kind: 'invalid'; field: string; reason: string }
  | { ok: false; kind: 'unconfirmed' }
  | { ok: false; kind: 'error'; status: number; code: string };

/** 表单草稿（仅内存）。会话失效时保存，重新配对后恢复。 */
export interface SettingsDraft {
  provider: Provider;
  location: 'standard' | 'custom';
  customPath: string;
  history: HistoryChoice;
}

function isSettings(body: unknown): body is { data: CollectorSettings } {
  const d = (body as { data?: Partial<CollectorSettings> } | null)?.data;
  return !!d && typeof d.mode === 'string' && Array.isArray(d.sources);
}

export class CollectorClient {
  draft: SettingsDraft | null = null;

  constructor(
    private readonly auth: AuthClient,
    private readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  async load(): Promise<SettingsOutcome> {
    const r = await httpCall('/collector-settings', {}, this.fetchImpl);
    return this.outcome(r);
  }

  /** 只在用户点击时调用一次；失败（含 401 / 网络中断）不自动重试。 */
  async save(request: SettingsRequest): Promise<SettingsOutcome> {
    const r = await httpCall(
      '/collector-settings',
      { method: 'POST', headers: this.auth.csrfHeaders(), json: request },
      this.fetchImpl,
    );
    return this.outcome(r);
  }

  private outcome(r: Awaited<ReturnType<typeof httpCall>>): SettingsOutcome {
    if (r.kind === 'unreachable') return { ok: false, kind: 'unconfirmed' };
    if (r.status === 200 && isSettings(r.body)) return { ok: true, settings: r.body.data };
    const { code } = errorBody(r.body);
    if (r.status === 401) {
      this.auth.forget();
      return { ok: false, kind: 'unauthorized' };
    }
    if (r.status === 403 && code === 'csrf_invalid') return { ok: false, kind: 'csrf_invalid' };
    if (r.status === 422) {
      const detail = (r.body as { error?: { details?: { field?: unknown; reason?: unknown }[] } } | null)?.error?.details?.[0];
      return {
        ok: false,
        kind: 'invalid',
        field: typeof detail?.field === 'string' ? detail.field : 'body',
        reason: typeof detail?.reason === 'string' ? detail.reason : 'invalid',
      };
    }
    return { ok: false, kind: 'error', status: r.status, code };
  }
}

/** 422 reason → 中文。未知代码用通用说明，不回显后端原文。 */
export function reasonText(reason: string): string {
  return (
    {
      scope_not_confirmed: translate("请先确认读取范围。"),
      path_too_broad: translate("这个范围太大（主目录、磁盘根目录或包含本应用数据的位置）。请选择具体的日志目录。"),
      path_not_directory: translate("找不到这个目录，或它不是目录。"),
      path_symlink: translate("不能选择符号链接，请选择实际目录。"),
      path_unreadable: translate("目录暂时无法读取，未启用。请检查读取权限后再试。"),
      not_absolute: translate("请填写完整路径（以 / 或 ~ 开头）。"),
      disable_first: translate("已启用的来源要先停用，再按新的范围重新启用。"),
      locked_by_startup_config: translate("本次由启动参数指定采集配置，页面设置只读。"),
      collection_disabled_for_this_run: translate("本次启动已关闭采集（--no-collection），页面设置只读。"),
    } as Record<string, string>
  )[reason] ?? translate("设置未保存：内容不符合要求。");
}
