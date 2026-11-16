// 组件测试用的虚构数据
import type { CategoryNode, Facets, ItemDetail, ItemSummary } from "../src/api/types";

export function summary(overrides: Partial<ItemSummary> = {}): ItemSummary {
  return {
    id: 1,
    version: 1,
    product_id: 1,
    name: "テストダウン",
    name_ja: "テストダウン",
    name_zh: "测试羽绒",
    brand: "UNIQLO",
    category: { id: 5, slug: "outer-light-down", path: ["外套", "羽绒", "轻羽绒"], path_slugs: ["outer", "outer-down", "outer-light-down"] },
    thumb_url: "/media/thumb/ab/abc.webp",
    resolved: {
      color: { code: "69", name: "NAVY", hex: "#1F2A44", family: "navy", source: "purchase_line" },
      size: { label: "L", system: "alpha", source: "purchase_line" },
    },
    tags: ["通勤"],
    status: "owned",
    favorite: false,
    acquired_on: "2025-11-03",
    verification: "unverified",
    ...overrides,
  };
}

export function detail(overrides: Partial<ItemDetail> = {}): ItemDetail {
  return {
    ...summary(),
    purchase_line_id: 3,
    color_code: null,
    color_name: null,
    color_hex: null,
    size_label: null,
    condition: null,
    retired_on: null,
    refund_amount: null,
    location: "衣柜",
    alterations: null,
    wear_count: 2,
    last_worn_on: "2025-12-01",
    notes: null,
    product: {
      id: 1,
      version: 1,
      origin: "catalog",
      brand: { id: 1, slug: "uniqlo", name: "UNIQLO", name_ja: null, name_zh: null, website: null },
      category: summary().category,
      name_ja: "テストダウン",
      name_zh: "测试羽绒",
      name_en: null,
      gender: "men",
      detail_url: "https://example.com/products/E000000-000",
      season_label: null,
      material_text: "表地:ナイロン100%",
      care_text: "手洗い30℃まで",
      care_symbols: [],
      description: null,
      list_price: 7990,
      currency: "JPY",
      verification: "unverified",
      identifiers: [
        { id: 1, scheme: "detail_page_id", value: "E000000-000", source: null },
        { id: 2, scheme: "item_no", value: "000000", source: "receipt" },
      ],
      colors: [{ id: 1, color_code: "09", name_ja: "BLACK", name_zh: null, hex: "#1A1A1A", color_family: "black", is_default: true }],
      sizes: [{ id: 1, size_label: "L", size_system: "alpha" }],
      materials: [{ part: "shell", part_raw: "表地", fiber: "nylon", fiber_raw: "ナイロン", percent: 100 }],
      images: [
        { id: 7, url: "/media/original/a.png", thumb_url: "/media/thumb/a.webp", width: 600, height: 800, source_type: "user_upload", source_url: null, source_note: null },
      ],
      notes: null,
    },
    purchase: {
      purchase_id: 2,
      purchased_on: "2025-11-03",
      store_name: "测试店",
      currency: "JPY",
      line: {
        id: 3,
        item_code_raw: "000000",
        name_raw: null,
        color_code: "69",
        color_name: "NAVY",
        size_label: "L",
        quantity: 2,
        unit_price: 7990,
        discount_amount: null,
        returned_quantity: 1,
        product_match: "confirmed",
      },
    },
    images: [
      { id: 8, url: "/media/original/b.png", thumb_url: "/media/thumb/b.webp", width: 600, height: 800, source_type: "user_photo", source_url: null, source_note: "自拍" },
    ],
    outfits: [{ id: 1, name: "秋季通勤" }],
    created_at: "2025-11-03T00:00:00Z",
    updated_at: "2025-11-04T00:00:00Z",
    ...overrides,
  };
}

export const CATEGORIES: CategoryNode[] = [
  {
    id: 1, slug: "outer", name_zh: "外套", name_ja: null, level: 1, parent_id: null,
    children: [
      { id: 2, slug: "outer-down", name_zh: "羽绒", name_ja: null, level: 2, parent_id: 1,
        children: [{ id: 5, slug: "outer-light-down", name_zh: "轻羽绒", name_ja: null, level: 3, parent_id: 2, children: [] }] },
    ],
  },
  { id: 9, slug: "tops", name_zh: "上衣", name_ja: null, level: 1, parent_id: null, children: [] },
  { id: 10, slug: "shoes", name_zh: "鞋", name_ja: null, level: 1, parent_id: null, children: [] },
];

export const FACETS: Facets = {
  total: 3,
  category: { "1": 2, "2": 2, "5": 2, "9": 1 },
  brand: { uniqlo: 2, gu: 1 },
  color: { navy: 2, black: 1 },
  size: { L: 2, M: 1, "76cm": 1 },
  tag: { 通勤: 2 },
  status: { owned: 3, returned: 1 },
  material: { nylon: 2 },
};
