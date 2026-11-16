import type { Product, Source, SourceErrorCode } from '../api/types';
import { productName } from './quota';

/** contracts/source-errors.md 的固定表；不显示供应商 message 原文。 */
export const ERROR_TEXT: Record<SourceErrorCode, { title: string; action: string }> = {
  source_unreadable: { title: '无法读取来源', action: '检查来源是否仍可访问，查看本机诊断' },
  source_missing: { title: '来源文件或目录不存在', action: '在本机设置中重新选择来源' },
  permission_denied: { title: '没有读取权限', action: '检查所选来源的读取权限，不建议一键授予全磁盘权限' },
  unsupported_format: { title: '当前版本无法识别记录格式', action: '更新适配器；保留已有历史，不清库' },
  auth_required: { title: '来源尚未登录', action: '通过对应官方客户端登录；不在网页填供应商密码' },
  auth_expired: { title: '来源登录状态已失效', action: '在官方客户端重新登录' },
  rate_limited: { title: '来源暂时限制查询', action: '按计划等待；不以密集重试绕过限制' },
  network_unavailable: { title: '暂时无法连接来源服务', action: '检查网络，保留本机历史' },
  source_timeout: { title: '来源响应超时', action: '稍后重试，显示原有历史' },
  collector_internal_error: { title: '采集过程发生错误', action: '查看已脱敏的本机诊断' },
  unknown_error: { title: '暂时无法更新来源', action: '保留现有数据，查看本机诊断' },
};

export function errorText(code: string | null): { title: string; action: string } | null {
  if (code === null) return null;
  return ERROR_TEXT[code as SourceErrorCode] ?? ERROR_TEXT.unknown_error;
}

export const CONNECTION_TEXT: Record<Source['connection_status'], string> = {
  available: '可用',
  not_configured: '未配置',
  error: '同步失败',
  disabled: '已停用',
};

const KIND_TEXT: Record<Source['kind'], string> = {
  local_log: '本机日志',
  official_client: '官方客户端',
  manual: '手动记录',
  telemetry: '遥测',
};

export function sourceName(s: Source, providerLabel: string): string {
  if (!s.product) return `${providerLabel} · ${KIND_TEXT[s.kind]}（产品未指定）`;
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
  complete: '已覆盖',
  partial: '部分覆盖',
  gap: '存在缺口',
  unknown: '未知',
};

/**
 * 覆盖原因代码 → 中文（contracts/coverage-reasons.json，registry_version=1）。
 * 这是可扩展的已知表；未知代码显示“未识别的覆盖原因”，不猜含义，也不改变统计状态。
 * 与契约表的一致性由 sources.test.ts 校验。
 */
export const REASON_TEXT: Record<string, string> = {
  local_device_only: '仅本机日志，其他设备未覆盖',
  no_records_not_proof_of_zero: '没有已记录事件，不等于没有使用',
  selected_products_not_configured: '所选产品中有未接入的来源',
  not_yet_elapsed: '该时段尚未发生',
  synthetic_local_history: '模拟本机历史，仅包含样例记录',
  collector_could_not_read_source: '采集时无法读取来源，此段覆盖存在缺口',
  one_event_has_unknown_usage: '该桶中有一条记录的用量未知',
};

export const UNKNOWN_REASON_TEXT = '未识别的覆盖原因';

export function isKnownReason(code: string): boolean {
  return Object.prototype.hasOwnProperty.call(REASON_TEXT, code);
}

export function reasonText(code: string): string {
  return isKnownReason(code) ? REASON_TEXT[code]! : UNKNOWN_REASON_TEXT;
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
