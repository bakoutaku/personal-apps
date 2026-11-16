// 把后端统一错误格式（API §1.2）转成界面文字。
import { ApiError } from "../api/client";

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "VERSION_CONFLICT") return "这条记录已在别处被修改。请重新载入后再操作。";
    const first = fieldDetails(e)[0];
    // 校验错误的总述（"2 个字段校验失败"）不如第一条具体信息有用
    if (e.code === "VALIDATION_ERROR" && first) return first.message + (fieldDetails(e).length > 1 ? `（另有 ${fieldDetails(e).length - 1} 处）` : "");
    return e.message;
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
    .map((d) => ({ loc: d.loc!, message: d.message! }));
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
