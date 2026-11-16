// 购买明细表单的草稿结构与请求体转换。
import type { PurchaseLine } from "../api/types";

export interface LineDraft {
  product_id: number | null;
  product_name: string;
  item_code_raw: string;
  name_raw: string;
  color_code: string;
  color_name: string;
  color_hex: string;
  size_label: string;
  size_system: string;
  quantity: number | string;
  unit_price: number | string;
  discount_amount: number | string;
  notes: string;
}

export function emptyLine(): LineDraft {
  return {
    product_id: null, product_name: "", item_code_raw: "", name_raw: "", color_code: "", color_name: "", color_hex: "",
    size_label: "", size_system: "", quantity: 1, unit_price: "", discount_amount: "", notes: "",
  };
}

/** 转成 API 请求体：空字符串不发送（新建）或发送 null（编辑时由调用方比较差异）。 */
export function linePayload(d: LineDraft): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of ["item_code_raw", "name_raw", "color_code", "color_name", "color_hex", "size_label", "size_system", "notes"] as const) {
    out[k] = d[k].trim() === "" ? null : d[k].trim();
  }
  for (const k of ["unit_price", "discount_amount"] as const) out[k] = d[k] === "" || d[k] === null ? null : Number(d[k]);
  // 不用默认值替代用户输入：无效数量由 lineErrors 拦截（或交给后端 422），绝不把 0/空改成 1
  out.quantity = d.quantity === "" ? null : Number(d.quantity);
  out.product_id = d.product_id;
  return out;
}

export function lineDraft(l: PurchaseLine): LineDraft {
  const s = (v: string | null | undefined) => v ?? "";
  return {
    product_id: l.product_id ?? null,
    product_name: l.product?.name_ja || l.product?.name_zh || l.product?.name_en || "",
    item_code_raw: s(l.item_code_raw),
    name_raw: s(l.name_raw),
    color_code: s(l.color_code),
    color_name: s(l.color_name),
    color_hex: s(l.color_hex),
    size_label: s(l.size_label),
    size_system: s(l.size_system),
    quantity: l.quantity,
    unit_price: l.unit_price ?? "",
    discount_amount: l.discount_amount ?? "",
    notes: s(l.notes),
  };
}

/** 提交前的本地校验（与后端 LineIn.quantity 1～99 一致）。键与后端错误的 loc 相同，便于在字段旁显示。 */
export function lineErrors(d: LineDraft, prefix = ""): Record<string, string> {
  const q = d.quantity === "" ? NaN : Number(d.quantity);
  if (!Number.isInteger(q) || q < 1 || q > 99) return { [`${prefix}quantity`]: "数量必须是 1～99 的整数" };
  return {};
}
