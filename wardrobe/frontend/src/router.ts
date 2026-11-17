import { t as translate } from "./i18n";
import { watchEffect } from "vue";
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import ImportCenterView from "./views/ImportCenterView.vue";
import ImportJobView from "./views/ImportJobView.vue";
import ItemDetailView from "./views/ItemDetailView.vue";
import ItemEditView from "./views/ItemEditView.vue";
import NotFoundView from "./views/NotFoundView.vue";
import OverviewView from "./views/OverviewView.vue";
import OutfitsView from "./views/OutfitsView.vue";
import OutfitView from "./views/OutfitView.vue";
import ProductView from "./views/ProductView.vue";
import PurchasesView from "./views/PurchasesView.vue";
import PurchaseView from "./views/PurchaseView.vue";
import SettingsView from "./views/SettingsView.vue";
import WardrobeView from "./views/WardrobeView.vue";

const idProp = (r: { params: Record<string, unknown> }) => ({ id: Number(r.params.id) });

export const routes: RouteRecordRaw[] = [
  { path: "/", name: "wardrobe", component: WardrobeView, meta: { title: "我的衣橱", section: "wardrobe" } },
  { path: "/overview", name: "overview", component: OverviewView, meta: { title: "衣橱总览", section: "overview" } },
  { path: "/items/new", name: "item-new", component: ItemEditView, meta: { title: "添加衣物", section: "wardrobe" } },
  { path: "/items/:id(\\d+)", name: "item", component: ItemDetailView, props: idProp, meta: { section: "wardrobe" } },
  { path: "/items/:id(\\d+)/edit", name: "item-edit", component: ItemEditView, props: idProp, meta: { title: "编辑衣物", section: "wardrobe" } },
  { path: "/products/:id(\\d+)", name: "product", component: ProductView, props: idProp, meta: { title: "商品资料", section: "wardrobe" } },
  { path: "/outfits", name: "outfits", component: OutfitsView, meta: { title: "穿搭组合", section: "outfits" } },
  { path: "/outfits/new", name: "outfit-new", component: OutfitView, meta: { title: "新建穿搭", section: "outfits" } },
  { path: "/outfits/:id(\\d+)", name: "outfit", component: OutfitView, props: idProp, meta: { section: "outfits" } },
  { path: "/purchases", name: "purchases", component: PurchasesView, meta: { title: "购买记录", section: "purchases" } },
  { path: "/purchases/new", name: "purchase-new", component: PurchaseView, meta: { title: "记录购买", section: "purchases" } },
  { path: "/purchases/:id(\\d+)", name: "purchase", component: PurchaseView, props: idProp, meta: { title: "购买记录", section: "purchases" } },
  { path: "/imports", name: "imports", component: ImportCenterView, meta: { title: "导入中心", section: "imports" } },
  { path: "/imports/:id(\\d+)", name: "import", component: ImportJobView, props: idProp, meta: { title: "导入批次", section: "imports" } },
  { path: "/settings", name: "settings", component: SettingsView, meta: { title: "设置", section: "settings" } },
  { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundView, meta: { title: "页面不存在" } },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, saved) {
    if (saved) return saved;
    // 同一页面内只改查询条件（筛选、标签页）时不跳动；进入其他页面时回到顶部
    if (to.name === from.name && to.path === from.path) return false;
    return { top: 0 };
  },
});

watchEffect(() => {
  const title = router.currentRoute.value.meta.title;
  document.title = typeof title === "string" ? `${translate(title)} · Wardrobe` : "Wardrobe";
});
