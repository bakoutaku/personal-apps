import { t as translate } from "../i18n";
import type { Product, Source, SourceErrorCode } from '../api/types';
import { productName } from './quota';

/** contracts/source-errors.md 的固定表；不显示供应商 message 原文。 */
export const ERROR_TEXT: Record<SourceErrorCode, { title: string; action: string }> = {
  source_unreadable: { get title() { return translate("无法读取来源"); }, get action() { return translate("检查来源是否仍可访问，查看本机诊断"); } },
  source_missing: { get title() { return translate("来源文件或目录不存在"); }, get action() { return translate("在本机设置中重新选择来源"); } },
  permission_denied: { get title() { return translate("没有读取权限"); }, get action() { return translate("检查所选来源的读取权限，不建议一键授予全磁盘权限"); } },
  unsupported_format: { get title() { return translate("当前版本无法识别记录格式"); }, get action() { return translate("更新适配器；保留已有历史，不清库"); } },
  auth_required: { get title() { return translate("来源尚未登录"); }, get action() { return translate("通过对应官方客户端登录；不在网页填供应商密码"); } },
  auth_expired: { get title() { return translate("来源登录状态已失效"); }, get action() { return translate("在官方客户端重新登录"); } },
  rate_limited: { get title() { return translate("来源暂时限制查询"); }, get action() { return translate("按计划等待；不以密集重试绕过限制"); } },
  network_unavailable: { get title() { return translate("暂时无法连接来源服务"); }, get action() { return translate("检查网络，保留本机历史"); } },
  source_timeout: { get title() { return translate("来源响应超时"); }, get action() { return translate("稍后重试，显示原有历史"); } },
  collector_internal_error: { get title() { return translate("采集过程发生错误"); }, get action() { return translate("查看已脱敏的本机诊断"); } },
  unknown_error: { get title() { return translate("暂时无法更新来源"); }, get action() { return translate("保留现有数据，查看本机诊断"); } },
};

export function errorText(code: string | null): { title: string; action: string } | null {
  if (code === null) return null;
  return ERROR_TEXT[code as SourceErrorCode] ?? ERROR_TEXT.unknown_error;
}

export const CONNECTION_TEXT: Record<Source['connection_status'], string> = {
  get available() { return translate("可用"); },
  get not_configured() { return translate("未配置"); },
  get error() { return translate("同步失败"); },
  get disabled() { return translate("已停用"); },
};

const KIND_TEXT: Record<Source['kind'], string> = {
  get local_log() { return translate("本机日志"); },
  get official_client() { return translate("官方客户端"); },
  get manual() { return translate("手动记录"); },
  get telemetry() { return translate("遥测"); },
};

export function sourceName(s: Source, providerLabel: string): string {
  if (!s.product) return translate("{0} · {1}（产品未指定）", providerLabel, KIND_TEXT[s.kind]);
  return `${productName(s.product)} · ${KIND_TEXT[s.kind]}`;
}

export type CoverageSummary = 'complete' | 'partial' | 'gap' | 'unknown';

/** 来源自身声明的覆盖；各区间状态不合成“全账户完整”。 */
export function coverageSummary(s: Source): CoverageSummary {
  if (s.coverage.length === 0) return 'unknown';
  const st = new Set(s.coverage.map((c) => c.status));
  if (st.has('gap')) return 'gap';
  if (st.size === 1 && st.has('complete')) return 'complete';
  if (st.has('partial') || st.has('complete')) return 'partial';
  return 'unknown';
}

export const COVERAGE_TEXT: Record<CoverageSummary, string> = {
  get complete() { return translate("已覆盖"); },
  get partial() { return translate("部分覆盖"); },
  get gap() { return translate("存在缺口"); },
  get unknown() { return translate("未知"); },
};

/**
 * 覆盖原因代码 → 中文（contracts/coverage-reasons.json，registry_version=1）。
 * 这是可扩展的已知表；未知代码显示“未识别的覆盖原因”，不猜含义，也不改变统计状态。
 * 与契约表的一致性由 sources.test.ts 校验。
 */
export const REASON_TEXT: Record<string, string> = {
  get local_device_only() { return translate("仅本机日志，其他设备未覆盖"); },
  get no_records_not_proof_of_zero() { return translate("没有已记录事件，不等于没有使用"); },
  get selected_products_not_configured() { return translate("所选产品中有未接入的来源"); },
  get not_yet_elapsed() { return translate("该时段尚未发生"); },
  get synthetic_local_history() { return translate("模拟本机历史，仅包含样例记录"); },
  get collector_could_not_read_source() { return translate("采集时无法读取来源，此段覆盖存在缺口"); },
  get one_event_has_unknown_usage() { return translate("该桶中有一条记录的用量未知"); },
};

export const UNKNOWN_REASON_TEXT = '未识别的覆盖原因';

export function isKnownReason(code: string): boolean {
  return Object.prototype.hasOwnProperty.call(REASON_TEXT, code);
}

export function reasonText(code: string): string {
  return isKnownReason(code) ? REASON_TEXT[code]! : translate(UNKNOWN_REASON_TEXT);
}

export type ProductStatus = 'available' | 'error' | 'not_configured' | 'disabled' | 'none';

/** 产品筛选芯片上的接入状态（只看声明了该产品的来源）。 */
export function productStatus(sources: Source[], p: Product): { status: ProductStatus; localOnly: boolean } {
  const own = sources.filter((s) => s.product === p);
  if (own.length === 0) return { status: 'none', localOnly: false };
  const pick: ProductStatus = own.some((s) => s.connection_status === 'error')
    ? 'error'
    : own.some((s) => s.connection_status === 'available')
      ? 'available'
      : own.some((s) => s.connection_status === 'disabled')
        ? 'disabled'
        : 'not_configured';
  const localOnly =
    pick === 'available' &&
    own.filter((s) => s.connection_status === 'available').every((s) => s.coverage.every((c) => c.scope === 'local_device'));
  return { status: pick, localOnly };
}

export type SelectionConnection = 'all_configured' | 'some_unconfigured' | 'none_configured';

/**
 * 所选产品的接入情况（按 /sources 判断，不只看 coverage_reasons）：
 * selected_products_not_configured 只说明“所选产品中有未接入的”，不一定全部未接入。
 */
export function selectionConnection(
  sources: Source[],
  provider: 'gpt' | 'claude',
  products: readonly Product[] | null,
  all: Record<'gpt' | 'claude', readonly Product[]>,
): SelectionConnection {
  const selected = products ?? all[provider];
  const connected = selected.filter((p) =>
    sources.some((s) => s.product === p && (s.connection_status === 'available' || s.connection_status === 'error')),
  );
  if (connected.length === 0) return 'none_configured';
  return connected.length === selected.length ? 'all_configured' : 'some_unconfigured';
}
