import { t as translate } from "../i18n";
// 界面显示用的中文标签。枚举值本身以后端 GET /meta 为准。

export const COLOR_FAMILIES: { key: string; label: string; swatch: string }[] = [
  { key: "black", get label() { return translate("黑"); }, swatch: "#1c1c1c" },
  { key: "white", get label() { return translate("白"); }, swatch: "#ffffff" },
  { key: "gray", get label() { return translate("灰"); }, swatch: "#9a9a9a" },
  { key: "beige", get label() { return translate("米"); }, swatch: "#d8c7a8" },
  { key: "brown", get label() { return translate("棕"); }, swatch: "#7a5230" },
  { key: "red", get label() { return translate("红"); }, swatch: "#b3262e" },
  { key: "pink", get label() { return translate("粉"); }, swatch: "#e9b4c0" },
  { key: "orange", get label() { return translate("橙"); }, swatch: "#e07b39" },
  { key: "yellow", get label() { return translate("黄"); }, swatch: "#e8c547" },
  { key: "green", get label() { return translate("绿"); }, swatch: "#4f7a4a" },
  { key: "blue", get label() { return translate("蓝"); }, swatch: "#4b78b5" },
  { key: "navy", get label() { return translate("藏青"); }, swatch: "#1f2a44" },
  { key: "purple", get label() { return translate("紫"); }, swatch: "#6a4c93" },
  { key: "multi", get label() { return translate("多色"); }, swatch: "conic-gradient(#b3262e, #e8c547, #4f7a4a, #4b78b5, #6a4c93, #b3262e)" },
];

export const STATUS_LABELS: Record<string, string> = {
  get owned() { return translate("持有"); },
  get wishlist() { return translate("想买"); },
  get returned() { return translate("已退货"); },
  get disposed() { return translate("已处理"); },
  get sold() { return translate("已售出"); },
  get given_away() { return translate("已送人"); },
  get lost() { return translate("遗失"); },
};

export const FIBER_LABELS: Record<string, string> = {
  get cotton() { return translate("棉"); },
  get polyester() { return translate("聚酯纤维"); },
  get nylon() { return translate("锦纶"); },
  get polyurethane() { return translate("氨纶"); },
  get wool() { return translate("羊毛"); },
  get cashmere() { return translate("羊绒"); },
  get rayon() { return translate("粘纤"); },
  get linen() { return translate("亚麻"); },
  get acrylic() { return translate("腈纶"); },
  get silk() { return translate("真丝"); },
  get cupro() { return translate("铜氨纤维"); },
  get modal() { return translate("莫代尔"); },
  get lyocell() { return translate("莱赛尔"); },
  get down() { return translate("羽绒"); },
  get feather() { return translate("羽毛"); },
  get polypropylene() { return translate("丙纶"); },
  get other() { return translate("其他"); },
};

export const PART_LABELS: Record<string, string> = {
  get body() { return translate("主体"); },
  get shell() { return translate("面料"); },
  get lining() { return translate("里料"); },
  get rib() { return translate("罗纹"); },
  get fill() { return translate("填充物"); },
  get pocket() { return translate("袋布"); },
};

export const SCHEME_LABELS: Record<string, string> = {
  get detail_page_id() { return translate("详情页编号"); },
  get item_no() { return translate("商品番号"); },
  jan: "JAN",
  sku: "SKU",
  get other() { return translate("其他编号"); },
};

export const SOURCE_LABELS: Record<string, string> = {
  get item() { return translate("手动指定"); },
  get purchase_line() { return translate("购买记录"); },
  get product_default() { return translate("商品默认"); },
};

export const GENDER_LABELS: Record<string, string> = {
  get men() { return translate("男装"); },
  get women() { return translate("女装"); },
  get unisex() { return translate("男女通用"); },
  get kids() { return translate("童装"); },
  get baby() { return translate("婴儿"); },
};

export const CONDITION_LABELS: Record<string, string> = {
  get new() { return translate("全新"); },
  get good() { return translate("良好"); },
  get fair() { return translate("一般"); },
  get worn() { return translate("有穿着痕迹"); },
  get damaged() { return translate("有损坏"); },
};

export const SIZE_SYSTEM_LABELS: Record<string, string> = {
  get alpha() { return translate("字母（S/M/L）"); },
  get waist_cm() { return translate("腰围 cm"); },
  get shoe_cm() { return translate("鞋 cm"); },
  get numeric() { return translate("数字"); },
  get free() { return translate("均码"); },
  get other() { return translate("其他"); },
};

export const CHANNEL_LABELS: Record<string, string> = {
  get store() { return translate("门店"); },
  get online() { return translate("网店"); },
  get gift() { return translate("礼物"); },
  get secondhand() { return translate("二手"); },
  get other() { return translate("其他"); },
};

export const SEASON_LABELS: Record<string, string> = {
  get spring() { return translate("春"); },
  get summer() { return translate("夏"); },
  get autumn() { return translate("秋"); },
  get winter() { return translate("冬"); },
  get all() { return translate("四季"); },
};

export const SLOT_LABELS: Record<string, string> = {
  get outer() { return translate("外套"); },
  get top() { return translate("上衣"); },
  get inner() { return translate("内搭"); },
  get bottom() { return translate("下装"); },
  get dress() { return translate("连衣裙"); },
  get shoes() { return translate("鞋"); },
  get bag() { return translate("包"); },
  get accessory() { return translate("配饰"); },
  get other() { return translate("其他"); },
};

export const TAG_KIND_LABELS: Record<string, string> = {
  get free() { return translate("自由"); },
  get season() { return translate("季节"); },
  get occasion() { return translate("场合"); },
  get style() { return translate("风格"); },
  get fit() { return translate("版型"); },
  get status() { return translate("状态"); },
};

export const IMAGE_ROLE_LABELS: Record<string, string> = {
  get main() { return translate("主图"); },
  get gallery() { return translate("图集"); },
  get color() { return translate("颜色图"); },
  get detail() { return translate("细节"); },
  get model() { return translate("模特"); },
  get size_chart() { return translate("尺码表"); },
  get tag_label() { return translate("吊牌/洗标"); },
  get receipt() { return translate("小票"); },
};

export const ENTITY_LABELS: Record<string, string> = {
  get product() { return translate("商品"); },
  get purchase() { return translate("购买记录"); },
  get purchase_line() { return translate("购买明细"); },
  get wardrobe_item() { return translate("衣物"); },
  get item() { return translate("衣物"); },
  get outfit() { return translate("穿搭"); },
  get brand() { return translate("品牌"); },
  get category() { return translate("分类"); },
  get tag() { return translate("标签"); },
  get image() { return translate("图片"); },
};

export const ACTION_LABELS: Record<string, string> = {
  get create() { return translate("新建"); },
  get update() { return translate("更新"); },
  get propose() { return translate("生成提议"); },
  get skip() { return translate("跳过"); },
  get error() { return translate("错误"); },
  get dependency_failed() { return translate("依赖出错"); },
};

export const OP_LABELS: Record<string, string> = {
  get create() { return translate("新建"); },
  get update() { return translate("修改"); },
  get delete() { return translate("删除"); },
  get restore() { return translate("恢复"); },
  get verify() { return translate("核实"); },
  get unverify() { return translate("取消核实"); },
  get revert() { return translate("撤销"); },
};

export const IMPORT_STATUS_LABELS: Record<string, string> = {
  get previewed() { return translate("已预览"); },
  get committed() { return translate("已提交"); },
  get reverted() { return translate("已撤销"); },
  get discarded() { return translate("已丢弃"); },
};

export const PROPOSAL_STATUS_LABELS: Record<string, string> = {
  get pending() { return translate("待确认"); },
  get accepted() { return translate("已接受"); },
  get rejected() { return translate("已拒绝"); },
  get superseded() { return translate("已被取代"); },
};

/** 提议/差异里出现的字段名。组字段（color/size/status/match）与子集合同样列出。 */
export const FIELD_LABELS: Record<string, string> = {
  get name_ja() { return translate("日文名"); },
  get name_zh() { return translate("中文名"); },
  get name_en() { return translate("英文名"); },
  get brand_id() { return translate("品牌"); },
  get category_id() { return translate("分类"); },
  get tags_add() { return translate("追加标签"); },
  get gender() { return translate("性别"); },
  get detail_url() { return translate("详情页"); },
  get season_label() { return translate("季节标注"); },
  get material_text() { return translate("材质原文"); },
  get care_text() { return translate("保养说明"); },
  get care_symbols() { return translate("洗涤符号"); },
  get list_price() { return translate("标价"); },
  get currency() { return translate("币种"); },
  get origin() { return translate("来源"); },
  get identifiers() { return translate("编号"); },
  get colors() { return translate("颜色列表"); },
  get sizes() { return translate("尺码列表"); },
  get materials() { return translate("材质结构"); },
  get color() { return translate("颜色"); },
  get color_code() { return translate("颜色编号"); },
  get color_name() { return translate("颜色名称"); },
  get color_hex() { return translate("颜色值"); },
  get size() { return translate("尺码"); },
  get size_label() { return translate("尺码"); },
  get size_system() { return translate("尺码体系"); },
  get product_match() { return translate("匹配状态"); },
  get status() { return translate("状态"); },
  get match() { return translate("商品匹配"); },
  get product_id() { return translate("商品"); },
  get purchase_line_id() { return translate("购买明细"); },
  get item_code_raw() { return translate("小票编号"); },
  get name_raw() { return translate("小票名称"); },
  get quantity() { return translate("数量"); },
  get unit_price() { return translate("单价"); },
  get discount_amount() { return translate("折扣"); },
  get acquired_on() { return translate("取得日期"); },
  get retired_on() { return translate("离开日期"); },
  get refund_amount() { return translate("退款"); },
  get notes() { return translate("备注"); },
  get location() { return translate("收纳位置"); },
};

export const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "-created_at", get label() { return translate("最近添加"); } },
  { value: "-acquired_on", get label() { return translate("购买日期（新→旧）"); } },
  { value: "acquired_on", get label() { return translate("购买日期（旧→新）"); } },
  { value: "name", get label() { return translate("名称"); } },
  { value: "color", get label() { return translate("颜色"); } },
  { value: "-wear_count", get label() { return translate("穿着次数"); } },
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
