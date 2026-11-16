// 与后端响应体对应的类型（backend/wardrobe/api/serializers.py）

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ResolvedColor {
  code: string | null;
  name: string | null;
  hex: string | null;
  family: string | null;
  source: "item" | "purchase_line" | "product_default" | null;
}

export interface ResolvedSize {
  label: string | null;
  system: string | null;
  source: "item" | "purchase_line" | "product_default" | null;
}

export interface CategoryRef {
  id: number;
  slug: string;
  path: string[];
  path_slugs: string[];
}

export interface ItemSummary {
  id: number;
  version: number;
  product_id: number;
  name: string;
  name_ja: string | null;
  name_zh: string | null;
  brand: string | null;
  category: CategoryRef | null;
  thumb_url: string | null;
  resolved: { color: ResolvedColor; size: ResolvedSize };
  /** 圆点显示用；颜色值为空时是按颜色名称 / 色号推算的示意色（source 为 name / name_code） */
  color_swatch?: { hex: string | null; source: "hex" | "name" | "name_code" | null };
  tags: string[];
  status: string;
  favorite: boolean;
  acquired_on: string | null;
  verification: "verified" | "unverified";
}

export interface OverviewRow {
  id: number;
  product_id: number;
  name_ja: string | null;
  name_zh: string | null;
  name_en: string | null;
  brand: string | null;
  item_no: string | null;
  category: CategoryRef | null;
  color: ResolvedColor & { swatch: string | null };
  size: ResolvedSize;
  material_text: string | null;
  materials: { part: string; fiber: string; fiber_raw: string | null; percent: number | null }[];
  seasons: string[];
  tags: string[];
  status: string;
}

export interface ImageInfo {
  id: number;
  url: string;
  thumb_url: string;
  width: number;
  height: number;
  role?: string;
  color_code?: string | null;
  source_type: string;
  source_url: string | null;
  source_note: string | null;
}

export interface Brand {
  id: number;
  slug: string;
  name: string;
  name_ja: string | null;
  name_zh: string | null;
  website: string | null;
}

export interface Product {
  id: number;
  item_count?: number;
  attributes?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  version: number;
  origin: "catalog" | "manual";
  brand: Brand | null;
  category: CategoryRef | null;
  name_ja: string | null;
  name_zh: string | null;
  name_en: string | null;
  gender: string | null;
  detail_url: string | null;
  season_label: string | null;
  material_text: string | null;
  care_text: string | null;
  care_symbols: string[];
  description: string | null;
  list_price: number | null;
  currency: string;
  verification: "verified" | "unverified";
  identifiers: { id: number; scheme: string; value: string; source: string | null }[];
  colors: {
    id: number;
    color_code: string | null;
    name_ja: string | null;
    name_zh: string | null;
    hex: string | null;
    color_family: string | null;
    is_default: boolean;
    sort_order?: number;
  }[];
  sizes: { id: number; size_label: string; size_system: string; size_detail?: Record<string, unknown> | null }[];
  materials: { part: string; part_raw: string | null; fiber: string; fiber_raw: string | null; percent: number | null }[];
  images: ImageInfo[];
  notes: string | null;
}

export interface ProductSummary {
  id: number;
  brand: string | null;
  name_ja: string | null;
  name_zh: string | null;
  name_en: string | null;
  origin: string;
  verification: "verified" | "unverified";
}

export interface PurchaseLine {
  id: number;
  version?: number;
  purchase_id?: number;
  product_id?: number | null;
  product?: ProductSummary | null;
  color_hex?: string | null;
  size_system?: string | null;
  verification?: "verified" | "unverified";
  notes?: string | null;
  item_ids?: number[];
  item_code_raw: string | null;
  name_raw: string | null;
  color_code: string | null;
  color_name: string | null;
  size_label: string | null;
  quantity: number;
  unit_price: number | null;
  discount_amount: number | null;
  returned_quantity: number;
  product_match: string;
}

export interface ItemDetail extends ItemSummary {
  purchase_line_id: number | null;
  category_id?: number | null;
  size_system?: string | null;
  tag_details?: { id: number; name: string; kind: string; color_hex: string | null }[];
  color_code: string | null;
  color_name: string | null;
  color_hex: string | null;
  size_label: string | null;
  condition: string | null;
  retired_on: string | null;
  refund_amount: number | null;
  location: string | null;
  alterations: string | null;
  wear_count: number;
  last_worn_on: string | null;
  notes: string | null;
  product: Product;
  purchase: { purchase_id: number; purchased_on: string; store_name: string | null; currency: string; line: PurchaseLine } | null;
  images: ImageInfo[];
  outfits: { id: number; name: string }[];
  created_at: string;
  updated_at: string;
}

export interface CategoryNode {
  id: number;
  slug: string;
  name_zh: string;
  name_ja: string | null;
  level: number;
  parent_id: number | null;
  children: CategoryNode[];
}

export interface Tag {
  id: number;
  name: string;
  kind: string;
  color_hex?: string | null;
  usage?: number;
}

export interface FlatCategory {
  id: number;
  slug: string;
  name_zh: string;
  name_ja: string | null;
  level: number;
  parent_id: number | null;
  sort_order: number;
}

export interface Purchase {
  id: number;
  version: number;
  purchased_on: string;
  channel: string;
  store_name: string | null;
  order_no: string | null;
  total_amount: number | null;
  currency: string;
  notes: string | null;
  lines: PurchaseLine[];
  created_at: string;
  updated_at: string;
}

export interface MatchCandidate {
  product: ProductSummary;
  reasons?: string[];
  reason?: string;
  score?: number;
}

export interface OutfitEntry {
  slot: string;
  sort_order: number;
  item: ItemSummary;
}

export interface Outfit {
  id: number;
  version: number;
  name: string;
  description: string | null;
  season: string | null;
  occasion: string | null;
  rating: number | null;
  attributes: Record<string, unknown>;
  cover_image: ImageInfo | null;
  items: OutfitEntry[];
  tags: string[];
  images: ImageInfo[];
  created_at: string;
  updated_at: string;
}

export interface ColorRegion {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ColorCandidate {
  rank: number;
  hex: string;
  color_family: string | null;
  pixel_count: number;
  pixel_share: number;
}

export interface ColorGroup {
  color_code: string | null;
  color_name: string | null;
  color_hex: string | null;
}

/** POST /items/{id}/color-analysis（docs/PHASE5A_BACKEND_CONTRACT.md §2） */
export interface ColorAnalysis {
  item_id: number;
  item_version: number;
  image_id: number;
  image_sha256: string;
  current_color: ColorGroup;
  resolved_color: ResolvedColor;
  status: "ok" | "no_suggestion";
  reason: "no_opaque_pixels" | "no_dominant_color" | null;
  algorithm: string;
  parameters: Record<string, unknown>;
  region: ColorRegion | null;
  stats: Record<string, unknown>;
  candidates: ColorCandidate[];
}

export interface AiContext {
  kind: "color";
  source: "local_image_analysis";
  target_version: number;
  image_id: number | null;
  image_sha256: string;
  region: ColorRegion | null;
  algorithm: string;
  parameters: Record<string, unknown>;
  candidate: ColorCandidate;
  candidates: ColorCandidate[];
  created_at: string;
}

/** GET /items/{id}/similar（Phase 5B，规则 wardrobe-similar/1） */
export interface SimilarReason {
  kind: "same_category" | "same_group" | "same_top" | "same_color_family" | "shared_tags";
  label: string;
  points: number;
}

export interface SimilarItems {
  item_id: number;
  algorithm: string;
  weights: Record<string, number>;
  max_shared_tags: number;
  min_score: number;
  status: "owned" | "all";
  items: { score: number; reasons: SimilarReason[]; item: ItemSummary }[];
}

/** Phase 5C 规则建议（wardrobe-tagcat/3：标签增加商品名称中的常用叫法；/1、/2 为旧提议）：GET /items/{id}/tag-suggestions */
export interface SuggestionReason {
  kind: string;
  label: string;
}

export interface TagSuggestion {
  name: string;
  reasons: SuggestionReason[];
  evidence: { same_product_item_ids: number[]; name_words?: string[]; similar_item_ids: number[]; similar_pool: number };
}

export interface CategorySuggestion {
  category_id: number;
  slug: string;
  path: string[];
  reasons: SuggestionReason[];
  evidence: Record<string, unknown>;
}

export interface ItemSuggestions {
  algorithm: string;
  item_id: number;
  item_version: number;
  tags: TagSuggestion[];
  category: CategorySuggestion | null;
  category_note: "already_categorized" | "no_keyword_match" | "ambiguous" | null;
}

export interface RuleContext {
  kind: "tags" | "category";
  source: "rule_based";
  algorithm: string;
  target_version: number;
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface Proposal {
  proposal_id: number;
  entity: "product" | "purchase_line" | "wardrobe_item";
  entity_id: number;
  field: string;
  current_value: unknown;
  proposed_value: unknown;
  reason: string | null;
  actor: string;
  import_job_id: number | null;
  status: "pending" | "accepted" | "rejected" | "superseded";
  created_at: string;
  decided_at: string | null;
  /** 只有 Phase 5A 照片颜色建议才有；历史提议为 null（旧响应可能没有该字段） */
  ai_context?: AiContext | null;
  /** Phase 5C 标签 / 分类规则建议的依据；其他提议为 null */
  rule_context?: RuleContext | null;
}

export interface ImportRow {
  row_index: number;
  entity: string;
  ref: string | null;
  action: "create" | "update" | "propose" | "skip" | "error" | "dependency_failed";
  target_id: number | null;
  match_reason: string | null;
  diff: { fields?: Record<string, [unknown, unknown]>; proposals?: number[]; [k: string]: unknown };
  errors: { code: string; message: string; loc?: unknown[] }[];
  warnings: { code: string; message: string }[];
}

export interface ImportJob {
  job_id: number;
  status: "previewed" | "committed" | "reverted" | "discarded";
  actor: string;
  source_label: string | null;
  options: Record<string, unknown>;
  summary: Record<string, unknown> & { job_warnings?: { code: string; message: string }[] };
  can_commit: boolean;
  created_at: string;
  committed_at: string | null;
  reverted_at: string | null;
  backup_file: string | null;
  payload_sha256?: string;
  rows?: ImportRow[];
}

export interface ChangeEntry {
  id: number;
  occurred_at: string;
  actor: string;
  entity: string;
  entity_id: number;
  op: string;
  before: unknown;
  after: unknown;
  version_after: number | null;
  import_job_id: number | null;
  proposal_id: number | null;
}

export interface Backup {
  name: string;
  bytes: number;
  created_at?: string;
  [k: string]: unknown;
}

export interface Facets {
  total: number;
  category: Record<string, number>;
  brand: Record<string, number>;
  color: Record<string, number>;
  size: Record<string, number>;
  tag: Record<string, number>;
  status: Record<string, number>;
  material: Record<string, number>;
  /** 快捷分组的件数（应用除分组外的其他条件）；more 为 true 的收进「更多」 */
  groups?: QuickGroup[];
}

export interface QuickGroup {
  key: string;
  label: string;
  more: boolean;
  count: number;
}

export interface Meta {
  app_version: string;
  schema_revision?: string | null;
  schema_head?: string | null;
  data_dir?: string;
  counts: Record<string, number>;
  enums: Record<string, string[]>;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: unknown[] };
}
