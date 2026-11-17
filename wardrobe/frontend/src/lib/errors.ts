import { language, t as translate } from "../i18n";
// 把后端统一错误格式（API §1.2）转成界面文字。
import { ApiError } from "../api/client";

const errorLabels: Record<string, string> = {
  ALREADY_RETURNED: "这条购买明细已退货。",
  BACKUP_FAILED: "创建备份失败。",
  DUPLICATE: "已有相同的记录。",
  IMAGE_UNAVAILABLE: "图片文件暂时无法读取。",
  IMAGE_UNREADABLE: "无法读取这张图片。",
  IMPORT_NOT_COMMITTED: "这批导入尚未提交。",
  IMPORT_NOT_PREVIEWED: "请先预览这批导入。",
  IN_USE: "这条记录还在使用，无法删除。",
  INVALID_IMAGE: "图片格式无效或文件已损坏。",
  NOT_DELETED: "这条记录没有被删除。",
  NOT_FOUND: "没有找到这条记录。",
  PAYLOAD_TOO_LARGE: "上传的文件太大。",
  PRIVILEGED_ONLY: "当前操作没有权限。",
  PROPOSAL_NOT_PENDING: "这条提议已处理。",
  PROPOSAL_STALE: "衣物已更新，请重新生成提议。",
  REGION_EMPTY: "选区内没有可分析的像素。",
  REVERT_CONFLICT: "导入后的修改阻止了撤销。",
  VALIDATION_ERROR: "请检查标出的字段。",
  VERSION_CONFLICT: "这条记录已在别处被修改。请重新载入后再操作。",
};

export function apiErrorText(code: string, message: string): string {
  const exact = translate(message);
  if (language.value === "zh-CN" || !/[\u3400-\u9fff]/.test(message) || exact !== message) return exact;
  const summary = errorLabels[code];
  return summary ? translate(summary) : translate("操作未完成（{0}）", code);
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "VERSION_CONFLICT") return translate(errorLabels.VERSION_CONFLICT!);
    const details = fieldDetails(e);
    if (e.code === "VALIDATION_ERROR" && details[0]) {
      return details[0].message + (details.length > 1 ? translate("（另有 {0} 处）", details.length - 1) : "");
    }
    return apiErrorText(e.code, e.message);
  }
  return e instanceof Error ? e.message : String(e);
}

export interface FieldDetail {
  loc: (string | number)[];
  message: string;
}

export function fieldDetails(e: unknown): FieldDetail[] {
  if (!(e instanceof ApiError)) return [];
  return (e.details as { loc?: (string | number)[]; message?: string }[])
    .filter((d) => d && typeof d === "object" && Array.isArray(d.loc) && typeof d.message === "string")
    .map((d) => ({ loc: d.loc!, message: apiErrorText("VALIDATION_ERROR", d.message!) }));
}

/** 按字段名（loc 的最后一个字符串）归集错误信息，供表单在字段旁显示。 */
export function fieldErrors(e: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  for (const d of fieldDetails(e)) {
    const key = d.loc.filter((x) => x !== "body").join(".");
    if (key && !out[key]) out[key] = d.message;
  }
  return out;
}

export function isConflict(e: unknown): boolean {
  return e instanceof ApiError && e.code === "VERSION_CONFLICT";
}
