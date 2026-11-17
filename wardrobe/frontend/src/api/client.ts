import { t as translate } from "../i18n";
// 后端 REST API 的薄封装。所有业务规则（匹配、核实保护、撤销）都在后端，前端不重复实现。
import type {
  ApiErrorBody,
  Backup,
  Brand,
  CategoryNode,
  ChangeEntry,
  ColorAnalysis,
  ColorRegion,
  ItemSuggestions,
  SimilarItems,
  Facets,
  FlatCategory,
  ImageInfo,
  ImportJob,
  ImportRow,
  ItemDetail,
  ItemSummary,
  OverviewRow,
  MatchCandidate,
  Meta,
  Outfit,
  Page,
  Product,
  Proposal,
  Purchase,
  PurchaseLine,
  Tag,
} from "./types";

export const API_BASE = "/api/v1";
// 写请求必须带的客户端标识（后端据此做跨站写入防护与核实保护）
export const CLIENT_HEADER = { "X-Wardrobe-Client": "web-ui" };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: unknown[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | string[] | number | boolean | undefined | null>;

export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (Array.isArray(v)) v.forEach((value) => params.append(k, value));
    else if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

export async function request<T>(
  method: string,
  path: string,
  opts: { query?: Query; body?: unknown; form?: FormData } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") Object.assign(headers, CLIENT_HEADER);
  // multipart 的 Content-Type（含 boundary）由浏览器生成
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let resp: Response;
  try {
    resp = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      body: opts.form ?? (opts.body === undefined ? undefined : JSON.stringify(opts.body)),
    });
  } catch {
    throw new ApiError(0, "NETWORK", translate("无法连接到本机服务，请确认已执行 ./wardrobe start"));
  }
  const text = await resp.text();
  const data = text ? safeJson(text) : null;
  if (!resp.ok) {
    const err = (data as ApiErrorBody | null)?.error;
    throw new ApiError(resp.status, err?.code ?? `HTTP_${resp.status}`, err?.message ?? translate("请求失败（{0}）", resp.status), err?.details ?? []);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

type Body = Record<string, unknown>;
const get = <T>(path: string, query?: Query) => request<T>("GET", path, { query });
const post = <T>(path: string, body: unknown = {}) => request<T>("POST", path, { body });
const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, { body });
const put = <T>(path: string, body: unknown) => request<T>("PUT", path, { body });
// 核心实体的删除用查询参数带 version（DELETE 不带请求体）
const del = (path: string, version?: number) => request<null>("DELETE", path, { query: { version } });

export const api = {
  meta: () => get<Meta>("/meta"),
  brands: () => get<{ items: Brand[] }>("/brands"),
  createBrand: (body: Body) => post<Brand>("/brands", body),
  updateBrand: (id: number, body: Body) => patch<Brand>(`/brands/${id}`, body),
  categories: () => get<{ items: CategoryNode[] }>("/categories"),
  flatCategories: () => get<{ items: FlatCategory[] }>("/categories", { format: "flat" }),
  createCategory: (body: Body) => post<FlatCategory>("/categories", body),
  updateCategory: (id: number, body: Body) => patch<FlatCategory>(`/categories/${id}`, body),
  deleteCategory: (id: number) => del(`/categories/${id}`),
  tags: () => get<{ items: Tag[] }>("/tags"),
  createTag: (body: Body) => post<Tag & { existing: boolean }>("/tags", body),
  updateTag: (id: number, body: Body) => patch<Tag>(`/tags/${id}`, body),
  deleteTag: (id: number) => del(`/tags/${id}`),

  items: (query: Query) => get<Page<ItemSummary>>("/items", query),
  facets: (query: Query) => get<Facets>("/items/facets", query),
  overview: (query: Query = {}) => get<{ items: OverviewRow[]; total: number }>("/items/overview", query),
  item: (id: number) => get<ItemDetail>(`/items/${id}`),
  createItem: (body: Body) => post<ItemDetail & { warnings: unknown[] }>("/items", body),
  updateItem: (id: number, body: Body) => patch<ItemDetail>(`/items/${id}`, body),
  setItemTags: (id: number, version: number, tags: string[]) => put<ItemDetail>(`/items/${id}/tags`, { version, tags }),
  returnItem: (id: number, body: Body) => post<ItemDetail>(`/items/${id}/return`, body),
  wearItem: (id: number, body: Body) => post<ItemDetail>(`/items/${id}/wear`, body),
  deleteItem: (id: number, version: number) => del(`/items/${id}`, version),
  restoreItem: (id: number, version: number) => post<ItemDetail>(`/items/${id}/restore`, { version }),
  similarItems: (id: number, limit = 8) => get<SimilarItems>(`/items/${id}/similar`, { limit }),
  tagSuggestions: (id: number) => get<ItemSuggestions>(`/items/${id}/tag-suggestions`),
  createTagSuggestions: (id: number, body: Body) => post<{ proposals: Proposal[] }>(`/items/${id}/tag-suggestions`, body),
  batchTagSuggestions: (query: Query = {}) =>
    get<{ algorithm: string; total: number; limit: number; offset: number; items: (ItemSuggestions & { item: ItemSummary })[] }>("/tag-suggestions", query),
  createBatchTagSuggestions: (items: Body[]) =>
    post<{
      results: { item_id: number; ok: boolean; proposals?: Proposal[]; error?: { code: string; message: string } }[];
      succeeded: number;
      failed: number;
    }>("/tag-suggestions/batch", { items }),
  colorAnalysis: (id: number, imageId: number, region: ColorRegion | null) =>
    post<ColorAnalysis>(`/items/${id}/color-analysis`, region ? { image_id: imageId, region } : { image_id: imageId }),
  colorSuggestion: (id: number, body: Body) => post<{ proposal: Proposal; analysis: ColorAnalysis }>(`/items/${id}/color-suggestions`, body),
  verifyItem: (id: number, version: number, verified: boolean) =>
    post<ItemDetail>(`/items/${id}/${verified ? "verify" : "unverify"}`, { version }),
  addItemImage: (id: number, body: Body) => post<ItemDetail>(`/items/${id}/images`, body),
  removeItemImage: (id: number, imageId: number, version: number) =>
    request<ItemDetail>("DELETE", `/items/${id}/images/${imageId}`, { query: { version } }),

  products: (query: Query) => get<Page<Product>>("/products", query),
  product: (id: number) => get<Product>(`/products/${id}`),
  createProduct: (body: Body) => post<Product & { warnings?: unknown[] }>("/products", body),
  updateProduct: (id: number, body: Body) => patch<Product>(`/products/${id}`, body),
  deleteProduct: (id: number, version: number) => del(`/products/${id}`, version),
  restoreProduct: (id: number, version: number) => post<Product>(`/products/${id}/restore`, { version }),
  putProductColors: (id: number, version: number, colors: unknown[]) => put<Product>(`/products/${id}/colors`, { version, colors }),
  putProductSizes: (id: number, version: number, sizes: unknown[]) => put<Product>(`/products/${id}/sizes`, { version, sizes }),
  putProductMaterials: (id: number, version: number, materials: unknown[] | null) =>
    put<Product>(`/products/${id}/materials`, materials === null ? { version } : { version, materials }),
  addIdentifier: (id: number, body: Body) => post<Product>(`/products/${id}/identifiers`, body),
  removeIdentifier: (id: number, identifierId: number, version: number) =>
    request<Product>("DELETE", `/products/${id}/identifiers/${identifierId}`, { query: { version } }),
  addProductImage: (id: number, body: Body) => post<Product>(`/products/${id}/images`, body),
  removeProductImage: (id: number, imageId: number, version: number) =>
    request<Product>("DELETE", `/products/${id}/images/${imageId}`, { query: { version } }),
  verifyProduct: (id: number, version: number, verified: boolean) =>
    post<Product>(`/products/${id}/${verified ? "verify" : "unverify"}`, { version }),

  purchases: (query: Query) => get<Page<Purchase>>("/purchases", query),
  purchase: (id: number) => get<Purchase>(`/purchases/${id}`),
  createPurchase: (body: Body) => post<Purchase>("/purchases", body),
  updatePurchase: (id: number, body: Body) => patch<Purchase>(`/purchases/${id}`, body),
  deletePurchase: (id: number, version: number) => del(`/purchases/${id}`, version),
  restorePurchase: (id: number, version: number) => post<Purchase>(`/purchases/${id}/restore`, { version }),
  addLine: (purchaseId: number, body: Body) => post<Purchase>(`/purchases/${purchaseId}/lines`, body),
  updateLine: (id: number, body: Body) => patch<PurchaseLine>(`/purchase-lines/${id}`, body),
  deleteLine: (id: number, purchaseVersion: number) => del(`/purchase-lines/${id}`, purchaseVersion),
  matchLine: (id: number, body: Body) => post<PurchaseLine>(`/purchase-lines/${id}/match`, body),
  matchCandidates: (id: number) =>
    get<{ line_id: number; current_product_id: number | null; candidates: MatchCandidate[] }>(`/purchase-lines/${id}/match-candidates`),
  verifyLine: (id: number, version: number, verified: boolean) =>
    post<PurchaseLine>(`/purchase-lines/${id}/${verified ? "verify" : "unverify"}`, { version }),

  outfits: (query: Query) => get<Page<Outfit>>("/outfits", query),
  outfit: (id: number) => get<Outfit>(`/outfits/${id}`),
  createOutfit: (body: Body) => post<Outfit>("/outfits", body),
  updateOutfit: (id: number, body: Body) => patch<Outfit>(`/outfits/${id}`, body),
  setOutfitItems: (id: number, version: number, items: unknown[]) => put<Outfit>(`/outfits/${id}/items`, { version, items }),
  setOutfitTags: (id: number, version: number, tags: string[]) => put<Outfit>(`/outfits/${id}/tags`, { version, tags }),
  deleteOutfit: (id: number, version: number) => del(`/outfits/${id}`, version),

  uploadImage: (file: File, sourceType = "user_photo") => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_type", sourceType);
    return request<ImageInfo & { deduplicated?: boolean }>("POST", "/images", { form });
  },

  imports: (query: Query = {}) => get<Page<ImportJob>>("/imports", query),
  importJob: (id: number) => get<ImportJob>(`/imports/${id}`),
  importRows: (id: number, query: Query = {}) => get<{ items: ImportRow[] }>(`/imports/${id}/rows`, query),
  previewImport: (payload: unknown) => post<ImportJob>("/imports", payload),
  commitImport: (id: number, allowPartial = false) =>
    post<ImportJob>(`/imports/${id}/commit`, allowPartial ? { allow_partial: true } : {}),
  revertImport: (id: number) => post<Record<string, unknown>>(`/imports/${id}/revert`),
  discardImport: (id: number) => request<ImportJob>("DELETE", `/imports/${id}`),

  proposals: (query: Query = {}) => get<Page<Proposal>>("/proposals", query),
  acceptProposal: (id: number) => post<Proposal>(`/proposals/${id}/accept`),
  rejectProposal: (id: number) => post<Proposal>(`/proposals/${id}/reject`),
  bulkProposals: (ids: number[], decision: "accept" | "reject") =>
    post<{ results: { proposal_id: number; ok: boolean; status?: string; error?: { code: string; message: string } }[]; succeeded: number; failed: number }>(
      "/proposals/bulk",
      { ids, decision },
    ),
  changes: (query: Query = {}) => get<Page<ChangeEntry>>("/changes", query),

  backups: () => get<{ items: Backup[] }>("/backups"),
  createBackup: () => post<Backup>("/backups"),
  exportAll: () => get<unknown>("/export"),
};
