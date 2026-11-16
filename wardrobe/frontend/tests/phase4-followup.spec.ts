// Phase 4 修复复查（P4-QA-007 / P4-QA-008）的回归：写请求响应的页面生命周期，以及新建衣物部分成功后的表单契约。
// API 全部为 mock，不访问网络。原 phase4.spec.ts 保持不变。
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { Product } from "../src/api/types";
import { routes } from "../src/router";
import { toasts } from "../src/lib/toast";
import { CATEGORIES, FACETS, detail, summary } from "./fixtures";

const mocks = vi.hoisted(() => {
  const names = [
    "meta", "brands", "categories", "flatCategories", "tags", "items", "facets", "item", "createItem", "updateItem",
    "setItemTags", "returnItem", "wearItem", "deleteItem", "restoreItem", "verifyItem", "addItemImage", "removeItemImage",
    "products", "product", "updateProduct", "putProductColors", "putProductSizes", "putProductMaterials", "addIdentifier",
    "removeIdentifier", "addProductImage", "removeProductImage", "verifyProduct", "deleteProduct", "restoreProduct",
    "purchases", "purchase", "createPurchase", "updatePurchase", "deletePurchase", "restorePurchase", "addLine",
    "updateLine", "deleteLine", "matchLine", "matchCandidates", "verifyLine", "outfits", "outfit", "createOutfit",
    "updateOutfit", "setOutfitItems", "setOutfitTags", "deleteOutfit", "uploadImage", "imports", "importJob",
    "importRows", "previewImport", "commitImport", "revertImport", "discardImport", "proposals", "acceptProposal",
    "rejectProposal", "bulkProposals", "changes", "backups", "createBackup", "exportAll", "createBrand", "updateBrand",
    "createCategory", "updateCategory", "deleteCategory", "createTag", "updateTag", "deleteTag",
  ] as const;
  return Object.fromEntries(names.map((n) => [n, vi.fn()])) as Record<(typeof names)[number], ReturnType<typeof vi.fn>>;
});

vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});

import App from "../src/App.vue";
import { ApiError } from "../src/api/client";

function product(overrides: Partial<Product> = {}): Product {
  return { ...detail().product, item_count: 1, ...overrides };
}

async function mountAt(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(path);
  await router.isReady();
  const w = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return { w, router };
}

const input = (w: ReturnType<typeof mount>, labelText: string) =>
  w.findAll("label.field").find((l) => l.text().startsWith(labelText))!.find("input, select, textarea");
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll("button").find((b) => b.text().trim() === text)!;
const photo = (id: number, role: string) => ({ ...detail().images[0]!, id, role });

function chooseFiles(w: ReturnType<typeof mount>, names: string[]) {
  const f = w.find(".uploader input[type=file]");
  Object.defineProperty(f.element, "files", { value: names.map((n) => new File([n], n)), configurable: true });
  return f.trigger("change");
}

beforeEach(() => {
  vi.useRealTimers();
  for (const m of Object.values(mocks)) m.mockReset();
  toasts.splice(0);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mocks.meta.mockResolvedValue({ app_version: "0.1.0", counts: {}, enums: { item_status: ["owned", "wishlist", "returned", "disposed"] } });
  mocks.brands.mockResolvedValue({ items: [{ id: 1, slug: "uniqlo", name: "UNIQLO", name_ja: null, name_zh: null, website: null }] });
  mocks.categories.mockResolvedValue({ items: CATEGORIES });
  mocks.flatCategories.mockResolvedValue({ items: [] });
  mocks.tags.mockResolvedValue({ items: [{ id: 1, name: "通勤", kind: "free", usage: 2 }] });
  mocks.items.mockResolvedValue({ items: [summary()], total: 1, limit: 48, offset: 0 });
  mocks.facets.mockResolvedValue(FACETS);
  mocks.item.mockResolvedValue(detail());
  mocks.products.mockResolvedValue({ items: [product()], total: 1, limit: 20, offset: 0 });
  mocks.product.mockImplementation((id: number) => Promise.resolve(product({ id, name_ja: `QA Product ${id}` })));
  mocks.proposals.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("P4-QA-007: product write responses are bound to the page that sent them", () => {
  it("does not adopt a previous product save response after switching products", async () => {
    let finish!: (p: Product) => void;
    mocks.putProductSizes.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { w, router } = await mountAt("/products/1");
    await button(w, "保存尺码").trigger("click");
    await flushPromises();
    await router.push("/products/2");
    await flushPromises();
    expect(w.find("h1").text()).toContain("QA Product 2");
    finish(product({ id: 1, version: 2, name_ja: "QA Product 1" }));
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/products/2");
    expect(w.find("h1").text()).toContain("QA Product 2");
    expect(document.title).not.toContain("QA Product 1");
    expect(toasts.some((t) => t.text.includes("已保存尺码"))).toBe(false);
    mocks.updateProduct.mockResolvedValue(product({ id: 2, version: 3, name_ja: "QA current edit" }));
    await input(w, "日文名").setValue("QA current edit");
    await button(w, "保存基本资料").trigger("click");
    await flushPromises();
    expect(mocks.updateProduct).toHaveBeenCalledTimes(1);
    expect(mocks.updateProduct).toHaveBeenCalledWith(2, expect.objectContaining({ version: 1, name_ja: "QA current edit" }));
    w.unmount();
  });

  it("does not replace the settings title after a previous product save resolves", async () => {
    let finish!: (p: Product) => void;
    mocks.putProductSizes.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { w, router } = await mountAt("/products/1");
    await button(w, "保存尺码").trigger("click");
    await flushPromises();
    await router.push("/settings");
    await flushPromises();
    document.title = "设置 · Wardrobe";
    finish(product({ id: 1, version: 2, name_ja: "QA old product" }));
    await flushPromises();
    expect(document.title).toBe("设置 · Wardrobe");
    w.unmount();
  });

  it("an old failure does not show its error on the new product or clear the new operation's busy state", async () => {
    let failOld!: (e: unknown) => void;
    let finishNew!: (p: Product) => void;
    mocks.putProductSizes.mockImplementationOnce(() => new Promise((_resolve, reject) => { failOld = reject; }));
    mocks.putProductColors.mockImplementationOnce(() => new Promise((resolve) => { finishNew = resolve; }));
    const { w, router } = await mountAt("/products/1");
    await button(w, "保存尺码").trigger("click");
    await flushPromises();
    await router.push("/products/2");
    await flushPromises();
    await button(w, "保存颜色").trigger("click");
    await flushPromises();
    expect(mocks.putProductColors).toHaveBeenCalledWith(2, 1, expect.any(Array));
    failOld(new ApiError(500, "QA_OLD", "旧商品保存失败"));
    await flushPromises();
    expect(w.text()).not.toContain("旧商品保存失败");
    // 新商品的保存仍在进行，按钮必须保持禁用
    expect(button(w, "保存颜色").attributes("disabled")).toBeDefined();
    finishNew(product({ id: 2, version: 2, name_ja: "QA Product 2" }));
    await flushPromises();
    expect(button(w, "保存颜色").attributes("disabled")).toBeUndefined();
    expect(w.find(".page-head .muted").text()).toContain("版本 2");
    w.unmount();
  });

  it("leaving and returning to the same product ignores the earlier page's late save", async () => {
    let finish!: (p: Product) => void;
    mocks.putProductSizes.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { w, router } = await mountAt("/products/1");
    await button(w, "保存尺码").trigger("click");
    await flushPromises();
    await router.push("/settings");
    await flushPromises();
    await router.push("/products/1");
    await flushPromises();
    finish(product({ id: 1, version: 9, name_ja: "QA stale response" }));
    await flushPromises();
    expect(w.find("h1").text()).toBe("QA Product 1");
    expect(w.find(".page-head .muted").text()).toContain("版本 1");
    expect(document.title).not.toContain("QA stale response");
    w.unmount();
  });

  it("an image uploaded while the page switched products is not linked to the new product", async () => {
    let finishUpload!: (img: unknown) => void;
    mocks.uploadImage.mockImplementationOnce(() => new Promise((resolve) => { finishUpload = resolve; }));
    const { w, router } = await mountAt("/products/1");
    await chooseFiles(w, ["a.png"]);
    await flushPromises();
    await router.push("/products/2");
    await flushPromises();
    finishUpload({ id: 50, thumb_url: "/t/50.webp" });
    await flushPromises();
    expect(mocks.addProductImage).not.toHaveBeenCalled();
    expect(w.find(".pending").exists()).toBe(false);
    w.unmount();
  });

  it("asks before switching to another product with unsaved edits", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { w, router } = await mountAt("/products/1");
    await input(w, "日文名").setValue("未保存");
    await router.push("/products/2").catch(() => {});
    await flushPromises();
    expect(confirm).toHaveBeenCalled();
    expect(router.currentRoute.value.fullPath).toBe("/products/1");
    expect(mocks.product).not.toHaveBeenCalledWith(2);
    w.unmount();
  });
});

describe("P4-QA-008: after a partially successful create only the photos remain editable", () => {
  it("locks the saved fields and tags, and the retry only links photos without writing other fields", async () => {
    const created = detail({ id: 9, version: 1, images: [], location: "A", tags: ["通勤"], product: { ...detail().product, name_ja: "QA partial" } });
    mocks.uploadImage.mockResolvedValue({ id: 50, thumb_url: "/t/50.webp" });
    mocks.createItem.mockResolvedValue(created);
    mocks.item.mockResolvedValue(created);
    mocks.addItemImage
      .mockRejectedValueOnce(new ApiError(503, "TEMP", "关联失败"))
      .mockResolvedValueOnce({ ...created, version: 2, images: [photo(50, "main")] });
    const { w, router } = await mountAt("/items/new");
    await button(w, "新建商品").trigger("click");
    await input(w, "日文名").setValue("QA partial");
    await input(w, "收纳位置").setValue("A");
    const tag = w.find(".tag-input input");
    await tag.setValue("通勤");
    await tag.trigger("keydown", { key: "Enter" });
    await chooseFiles(w, ["a.png"]);
    await flushPromises();
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createItem).toHaveBeenCalledWith(expect.objectContaining({ location: "A", tags: ["通勤"], product: { name_ja: "QA partial" } }));
    // 已保存的内容不能再看起来可编辑
    expect(w.find('[data-testid="partial-created"]').text()).toContain("#9");
    expect((input(w, "收纳位置").element as HTMLInputElement).disabled).toBe(true);
    expect((input(w, "备注").element as HTMLTextAreaElement).disabled).toBe(true);
    expect((input(w, "状态").element as HTMLSelectElement).disabled).toBe(true);
    expect(w.find(".tag-input").exists()).toBe(false);
    expect(w.find('[data-testid="locked-tags"]').text()).toContain("#通勤");
    expect(w.find('[role="tablist"]').exists()).toBe(false);
    expect(w.findAll("label.field").some((l) => l.text().startsWith("日文名"))).toBe(false);
    expect(w.text()).toContain("QA");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createItem).toHaveBeenCalledTimes(1);
    expect(mocks.updateItem).not.toHaveBeenCalled();
    expect(mocks.setItemTags).not.toHaveBeenCalled();
    expect(mocks.addItemImage).toHaveBeenLastCalledWith(9, { version: 1, image_id: 50, role: "main" });
    expect(router.currentRoute.value.fullPath).toBe("/items/9");
    w.unmount();
  });

  it("with several photos, a failure after the first link keeps the linked one visible and the retry links only the rest", async () => {
    const created = detail({ id: 9, version: 1, images: [] });
    mocks.uploadImage.mockResolvedValueOnce({ id: 50, thumb_url: "/t/50.webp" }).mockResolvedValueOnce({ id: 51, thumb_url: "/t/51.webp" });
    mocks.createItem.mockResolvedValue(created);
    mocks.addItemImage
      .mockResolvedValueOnce({ ...created, version: 2, images: [photo(50, "main")] })
      .mockRejectedValueOnce(new ApiError(503, "TEMP", "第二张关联失败"))
      .mockResolvedValueOnce({ ...created, version: 3, images: [photo(50, "main"), photo(51, "gallery")] });
    mocks.item.mockResolvedValue({ ...created, version: 2, images: [photo(50, "main")] });
    const { w, router } = await mountAt("/items/new");
    await button(w, "新建商品").trigger("click");
    await input(w, "英文名").setValue("QA two photos");
    await chooseFiles(w, ["a.png", "b.png"]);
    await flushPromises();
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.find("[role=alert]").text()).toContain("还有 1 张照片未关联");
    // 已关联的照片仍然显示（不能再在这里移除），待关联的可以移除
    const thumbs = w.findAll(".thumbs li");
    expect(thumbs).toHaveLength(2);
    expect(thumbs[0]!.find("button").exists()).toBe(false);
    expect(thumbs[1]!.find("button").exists()).toBe(true);
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createItem).toHaveBeenCalledTimes(1);
    expect(mocks.addItemImage).toHaveBeenCalledTimes(3);
    expect(mocks.addItemImage).toHaveBeenLastCalledWith(9, { version: 2, image_id: 51, role: "gallery" });
    expect(router.currentRoute.value.fullPath).toBe("/items/9");
    w.unmount();
  });

  it("a successful create without photo problems never shows the locked state", async () => {
    const created = detail({ id: 9, version: 1, images: [] });
    mocks.createItem.mockResolvedValue(created);
    const { w, router } = await mountAt("/items/new");
    await button(w, "新建商品").trigger("click");
    await input(w, "日文名").setValue("QA plain");
    expect(w.find('[data-testid="partial-created"]').exists()).toBe(false);
    expect((input(w, "收纳位置").element as HTMLInputElement).disabled).toBe(false);
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createItem).toHaveBeenCalledTimes(1);
    expect(router.currentRoute.value.fullPath).toBe("/items/9");
    w.unmount();
  });
});
