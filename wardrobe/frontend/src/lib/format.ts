import { t as translate } from "../i18n";
// 把提议、审计日志、导入差异中的任意值转成一行可读文字。
import { FIELD_LABELS, label } from "./labels";

export function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return translate("（空）");
  if (typeof v === "boolean") return v ? translate("是") : translate("否");
  if (typeof v === "string" || typeof v === "number") return String(v);
  if (Array.isArray(v)) return v.length ? v.map(formatValue).join("；") : translate("（无）");
  if (typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>).filter(([, x]) => x !== null && x !== undefined && x !== "");
    if (!entries.length) return translate("（空）");
    return entries.map(([k, x]) => `${label(FIELD_LABELS, k)}: ${formatValue(x)}`).join("，");
  }
  return String(v);
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
