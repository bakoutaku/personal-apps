// 界面显示用的中文标签。枚举值本身以后端 GET /meta 为准。

export const COLOR_FAMILIES: { key: string; label: string; swatch: string }[] = [
  { key: "black", label: "黑", swatch: "#1c1c1c" },
  { key: "white", label: "白", swatch: "#ffffff" },
  { key: "gray", label: "灰", swatch: "#9a9a9a" },
  { key: "beige", label: "米", swatch: "#d8c7a8" },
  { key: "brown", label: "棕", swatch: "#7a5230" },
  { key: "red", label: "红", swatch: "#b3262e" },
  { key: "pink", label: "粉", swatch: "#e9b4c0" },
  { key: "orange", label: "橙", swatch: "#e07b39" },
  { key: "yellow", label: "黄", swatch: "#e8c547" },
  { key: "green", label: "绿", swatch: "#4f7a4a" },
  { key: "blue", label: "蓝", swatch: "#4b78b5" },
  { key: "navy", label: "藏青", swatch: "#1f2a44" },
  { key: "purple", label: "紫", swatch: "#6a4c93" },
  { key: "multi", label: "多色", swatch: "conic-gradient(#b3262e, #e8c547, #4f7a4a, #4b78b5, #6a4c93, #b3262e)" },
];

export const STATUS_LABELS: Record<string, string> = {
  owned: "持有",
  wishlist: "想买",
  returned: "已退货",
  disposed: "已处理",
  sold: "已售出",
  given_away: "已送人",
  lost: "遗失",
};

export const FIBER_LABELS: Record<string, string> = {
  cotton: "棉",
  polyester: "聚酯纤维",
  nylon: "锦纶",
  polyurethane: "氨纶",
  wool: "羊毛",
  cashmere: "羊绒",
  rayon: "粘纤",
  linen: "亚麻",
  acrylic: "腈纶",
  silk: "真丝",
  cupro: "铜氨纤维",
  modal: "莫代尔",
  lyocell: "莱赛尔",
  down: "羽绒",
  feather: "羽毛",
  polypropylene: "丙纶",
  other: "其他",
};

export const PART_LABELS: Record<string, string> = {
  body: "主体",
  shell: "面料",
  lining: "里料",
  rib: "罗纹",
  fill: "填充物",
  pocket: "袋布",
};

export const SCHEME_LABELS: Record<string, string> = {
  detail_page_id: "详情页编号",
  item_no: "商品番号",
  jan: "JAN",
  sku: "SKU",
  other: "其他编号",
};

export const SOURCE_LABELS: Record<string, string> = {
  item: "手动指定",
  purchase_line: "购买记录",
  product_default: "商品默认",
};

export const GENDER_LABELS: Record<string, string> = {
  men: "男装",
  women: "女装",
  unisex: "男女通用",
  kids: "童装",
  baby: "婴儿",
};

export const CONDITION_LABELS: Record<string, string> = {
  new: "全新",
  good: "良好",
  fair: "一般",
  worn: "有穿着痕迹",
  damaged: "有损坏",
};

export const SIZE_SYSTEM_LABELS: Record<string, string> = {
  alpha: "字母（S/M/L）",
  waist_cm: "腰围 cm",
  shoe_cm: "鞋 cm",
  numeric: "数字",
  free: "均码",
  other: "其他",
};

export const CHANNEL_LABELS: Record<string, string> = {
  store: "门店",
  online: "网店",
  gift: "礼物",
  secondhand: "二手",
  other: "其他",
};

export const SEASON_LABELS: Record<string, string> = {
  spring: "春",
  summer: "夏",
  autumn: "秋",
  winter: "冬",
  all: "四季",
};

export const SLOT_LABELS: Record<string, string> = {
  outer: "外套",
  top: "上衣",
  inner: "内搭",
  bottom: "下装",
  dress: "连衣裙",
  shoes: "鞋",
  bag: "包",
  accessory: "配饰",
  other: "其他",
};

export const TAG_KIND_LABELS: Record<string, string> = {
  free: "自由",
  season: "季节",
  occasion: "场合",
  style: "风格",
  fit: "版型",
  status: "状态",
};

export const IMAGE_ROLE_LABELS: Record<string, string> = {
  main: "主图",
  gallery: "图集",
  color: "颜色图",
  detail: "细节",
  model: "模特",
  size_chart: "尺码表",
  tag_label: "吊牌/洗标",
  receipt: "小票",
};

export const ENTITY_LABELS: Record<string, string> = {
  product: "商品",
  purchase: "购买记录",
  purchase_line: "购买明细",
  wardrobe_item: "衣物",
  item: "衣物",
  outfit: "穿搭",
  brand: "品牌",
  category: "分类",
  tag: "标签",
  image: "图片",
};

export const ACTION_LABELS: Record<string, string> = {
  create: "新建",
  update: "更新",
  propose: "生成提议",
  skip: "跳过",
  error: "错误",
  dependency_failed: "依赖出错",
};

export const OP_LABELS: Record<string, string> = {
  create: "新建",
  update: "修改",
  delete: "删除",
  restore: "恢复",
  verify: "核实",
  unverify: "取消核实",
  revert: "撤销",
};

export const IMPORT_STATUS_LABELS: Record<string, string> = {
  previewed: "已预览",
  committed: "已提交",
  reverted: "已撤销",
  discarded: "已丢弃",
};

export const PROPOSAL_STATUS_LABELS: Record<string, string> = {
  pending: "待确认",
  accepted: "已接受",
  rejected: "已拒绝",
  superseded: "已被取代",
};

/** 提议/差异里出现的字段名。组字段（color/size/status/match）与子集合同样列出。 */
export const FIELD_LABELS: Record<string, string> = {
  name_ja: "日文名",
  name_zh: "中文名",
  name_en: "英文名",
  brand_id: "品牌",
  category_id: "分类",
  tags_add: "追加标签",
  gender: "性别",
  detail_url: "详情页",
  season_label: "季节标注",
  material_text: "材质原文",
  care_text: "保养说明",
  care_symbols: "洗涤符号",
  list_price: "标价",
  currency: "币种",
  origin: "来源",
  identifiers: "编号",
  colors: "颜色列表",
  sizes: "尺码列表",
  materials: "材质结构",
  color: "颜色",
  color_code: "颜色编号",
  color_name: "颜色名称",
  color_hex: "颜色值",
  size: "尺码",
  size_label: "尺码",
  size_system: "尺码体系",
  product_match: "匹配状态",
  status: "状态",
  match: "商品匹配",
  product_id: "商品",
  purchase_line_id: "购买明细",
  item_code_raw: "小票编号",
  name_raw: "小票名称",
  quantity: "数量",
  unit_price: "单价",
  discount_amount: "折扣",
  acquired_on: "取得日期",
  retired_on: "离开日期",
  refund_amount: "退款",
  notes: "备注",
  location: "收纳位置",
};

export const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "-created_at", label: "最近添加" },
  { value: "-acquired_on", label: "购买日期（新→旧）" },
  { value: "acquired_on", label: "购买日期（旧→新）" },
  { value: "name", label: "名称" },
  { value: "color", label: "颜色" },
  { value: "-wear_count", label: "穿着次数" },
];

export function label(map: Record<string, string>, key: string | null | undefined): string {
  if (!key) return "";
  return map[key] ?? key;
}

export function colorSwatch(family: string | null | undefined): string | undefined {
  return COLOR_FAMILIES.find((c) => c.key === family)?.swatch;
}

export function yen(amount: number | null | undefined, currency = "JPY"): string {
  if (amount === null || amount === undefined) return "";
  if (currency === "JPY") return `¥${amount.toLocaleString("ja-JP")}`;
  return `${amount.toLocaleString()} ${currency}`;
}
