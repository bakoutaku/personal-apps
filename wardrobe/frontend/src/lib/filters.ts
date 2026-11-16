// 衣橱筛选条件与 URL 查询参数互转：筛选状态保存在地址栏，前进/后退、刷新、分享链接都能还原。
import type { LocationQuery, LocationQueryRaw } from "vue-router";

export interface Filters {
  q: string;
  category: string | null;
  /** 快捷分组（「T恤」「半袖」…，定义在后端 services/quick_groups.py） */
  group: string | null;
  brand: string[];
  color: string[];
  size: string[];
  tag: string[];
  material: string[];
  status: string;
  sort: string;
}

export const DEFAULT_FILTERS: Filters = {
  q: "",
  category: null,
  group: null,
  brand: [],
  color: [],
  size: [],
  tag: [],
  material: [],
  status: "owned",
  sort: "-created_at",
};

export const LIST_KEYS = ["brand", "color", "size", "tag", "material"] as const;
export type ListKey = (typeof LIST_KEYS)[number];

function one(v: LocationQuery[string]): string | null {
  const x = Array.isArray(v) ? v[0] : v;
  return x === undefined || x === null || x === "" ? null : String(x);
}

function list(v: LocationQuery[string]): string[] {
  const s = one(v);
  return s ? s.split(",").filter(Boolean) : [];
}

function exactList(v: LocationQuery[string]): string[] {
  return (Array.isArray(v) ? v : [v]).filter((x): x is string => typeof x === "string" && x.length > 0);
}

export function fromQuery(query: LocationQuery): Filters {
  return {
    q: one(query.q) ?? "",
    category: one(query.category),
    group: one(query.group),
    brand: list(query.brand),
    color: list(query.color),
    size: [...new Set([...list(query.size), ...exactList(query.size_exact)])],
    tag: [...new Set([...list(query.tag), ...exactList(query.tag_exact)])],
    material: list(query.material),
    status: one(query.status) ?? DEFAULT_FILTERS.status,
    sort: one(query.sort) ?? DEFAULT_FILTERS.sort,
  };
}

/** 只写入与默认值不同的条件，地址栏保持简短。 */
export function toQuery(f: Filters): LocationQueryRaw {
  const out: LocationQueryRaw = {};
  if (f.q.trim()) out.q = f.q.trim();
  if (f.category) out.category = f.category;
  if (f.group) out.group = f.group;
  for (const k of LIST_KEYS) {
    if (!f[k].length) continue;
    if ((k === "tag" || k === "size") && f[k].some((v) => v.includes(","))) out[`${k}_exact`] = [...f[k]];
    else out[k] = f[k].join(",");
  }
  if (f.status !== DEFAULT_FILTERS.status) out.status = f.status;
  if (f.sort !== DEFAULT_FILTERS.sort) out.sort = f.sort;
  return out;
}

/** 后端 GET /items 与 /items/facets 的查询参数（多值用逗号分隔，与后端约定一致）。 */
export function toApiQuery(f: Filters): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = { status: f.status };
  if (f.q.trim()) out.q = f.q.trim();
  if (f.category) out.category = f.category;
  if (f.group) out.group = f.group;
  for (const k of LIST_KEYS) {
    if (!f[k].length) continue;
    if ((k === "tag" || k === "size") && f[k].some((v) => v.includes(","))) out[`${k}_exact`] = [...f[k]];
    else out[k] = f[k].join(",");
  }
  if (f.tag.length) out.tag_mode = "all";
  return out;
}

export function toggle(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

export function activeCount(f: Filters): number {
  return (
    (f.q.trim() ? 1 : 0) +
    (f.category ? 1 : 0) +
    (f.group ? 1 : 0) +
    LIST_KEYS.reduce((n, k) => n + f[k].length, 0) +
    (f.status !== DEFAULT_FILTERS.status ? 1 : 0)
  );
}
