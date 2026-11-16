// Phase 4 编辑与管理页面：请求体、version 链、错误显示与路由行为。API 全部为 mock，不访问网络。
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { ImportJob, Outfit, Product, Proposal, Purchase } from "../src/api/types";
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

function purchase(overrides: Partial<Purchase> = {}): Purchase {
  return {
    id: 4, version: 3, purchased_on: "2025-11-03", channel: "store", store_name: "测试店", order_no: "R-1", total_amount: null,
    currency: "JPY", notes: null, created_at: "", updated_at: "",
    lines: [
      {
        id: 11, version: 2, purchase_id: 4, product_id: null, product: null, product_match: "unmatched", item_code_raw: "465185",
        name_raw: "Mセーター", color_code: null, color_name: "GRAY", color_hex: null, size_label: "M", size_system: null,
        quantity: 1, unit_price: 3990, discount_amount: null, returned_quantity: 0, verification: "unverified", notes: null, item_ids: [],
      },
    ],
    ...overrides,
  };
}

function outfit(overrides: Partial<Outfit> = {}): Outfit {
  return {
    id: 6, version: 2, name: "秋季通勤", description: null, season: "autumn", occasion: null, rating: null, attributes: {},
    cover_image: null, items: [{ slot: "outer", sort_order: 0, item: summary() }], tags: ["通勤"], images: [],
    created_at: "", updated_at: "", ...overrides,
  };
}

function proposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    proposal_id: 41, entity: "wardrobe_item", entity_id: 1, field: "acquired_on", current_value: "2025-02-11",
    proposed_value: "2024-01-01", reason: null, actor: "ai:codex", import_job_id: null, status: "pending",
    created_at: "2026-10-26T00:00:00Z", decided_at: null, ...overrides,
  };
}

function job(overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    job_id: 7, status: "previewed", actor: "web-ui", source_label: "测试导入", options: {}, can_commit: false,
    summary: { create: 2, update: 0, propose: 0, skip: 0, error: 1, job_warnings: [] }, created_at: "2026-10-26T00:00:00Z",
    committed_at: null, reverted_at: null, backup_file: null, ...overrides,
  };
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
  mocks.items.mockResolvedValue({ items: [summary(), summary({ id: 2, name: "セーター", category: { id: 9, slug: "tops", path: ["上衣"], path_slugs: ["tops"] } })], total: 2, limit: 48, offset: 0 });
  mocks.facets.mockResolvedValue(FACETS);
  mocks.item.mockResolvedValue(detail());
  mocks.products.mockResolvedValue({ items: [product()], total: 1, limit: 20, offset: 0 });
  mocks.product.mockResolvedValue(product());
  mocks.proposals.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("item editing", () => {
  it("sends only changed fields, then tags with the version returned by the first write", async () => {
    mocks.updateItem.mockResolvedValue(detail({ version: 2, location: "玄关" }));
    mocks.setItemTags.mockResolvedValue(detail({ version: 3, location: "玄关", tags: ["通勤", "QA,逗号"] }));
    const { w, router } = await mountAt("/items/1/edit");
    await input(w, "收纳位置").setValue("玄关");
    const tagInput = w.find(".tag-input input");
    await tagInput.setValue("QA,逗号");
    await tagInput.trigger("keydown", { key: "Enter" });
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.updateItem).toHaveBeenCalledWith(1, { version: 1, location: "玄关" });
    // 含逗号的标签作为一个完整标签提交
    expect(mocks.setItemTags).toHaveBeenCalledWith(1, 2, ["通勤", "QA,逗号"]);
    expect(router.currentRoute.value.fullPath).toBe("/items/1");
    w.unmount();
  });

  it("clearing a field sends null, and an unchanged form cannot be submitted", async () => {
    const { w } = await mountAt("/items/1/edit");
    const submit = w.find(".form-actions button[type=submit]");
    expect(submit.attributes("disabled")).toBeDefined();
    await input(w, "收纳位置").setValue("");
    expect(submit.attributes("disabled")).toBeUndefined();
    mocks.updateItem.mockResolvedValue(detail({ version: 2, location: null }));
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.updateItem).toHaveBeenCalledWith(1, { version: 1, location: null });
    w.unmount();
  });

  it("on a version conflict keeps the user's edits and offers to reload the latest version", async () => {
    mocks.updateItem.mockRejectedValue(new ApiError(409, "VERSION_CONFLICT", "版本冲突"));
    const { w } = await mountAt("/items/1/edit");
    await input(w, "收纳位置").setValue("玄关");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.find("[role=alert]").text()).toContain("已在别处被修改");
    expect((input(w, "收纳位置").element as HTMLInputElement).value).toBe("玄关");
    mocks.item.mockResolvedValue(detail({ version: 5, location: "别处改的" }));
    await w.findAll("button").find((b) => b.text().includes("载入最新版本"))!.trigger("click");
    await flushPromises();
    expect((input(w, "收纳位置").element as HTMLInputElement).value).toBe("别处改的");
    w.unmount();
  });

  it("creates an item with an inline manual product, then links staged photos using each returned version", async () => {
    mocks.uploadImage.mockResolvedValueOnce({ id: 50, thumb_url: "/t/50.webp" }).mockResolvedValueOnce({ id: 51, thumb_url: "/t/51.webp" });
    const created = detail({ id: 9, version: 1, images: [] });
    mocks.createItem.mockResolvedValue(created);
    mocks.addItemImage
      .mockResolvedValueOnce({ ...created, version: 2, images: [{ id: 50, role: "main" }] })
      .mockResolvedValueOnce({ ...created, version: 3, images: [{ id: 50, role: "main" }, { id: 51, role: "gallery" }] });
    const { w, router } = await mountAt("/items/new");
    await button(w, "新建商品").trigger("click");
    await input(w, "品牌").setValue("uniqlo");
    await input(w, "日文名").setValue("自作シャツ");
    await input(w, "尺码").setValue("M");
    const file = w.find(".uploader input[type=file]");
    Object.defineProperty(file.element, "files", { value: [new File(["a"], "a.png"), new File(["b"], "b.png")], configurable: true });
    await file.trigger("change");
    await flushPromises();
    expect(w.findAll(".thumbs li")).toHaveLength(2);
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createItem).toHaveBeenCalledWith({ size_label: "M", tags: [], product: { brand: "uniqlo", name_ja: "自作シャツ" } });
    expect(mocks.addItemImage).toHaveBeenNthCalledWith(1, 9, { version: 1, image_id: 50, role: "main" });
    expect(mocks.addItemImage).toHaveBeenNthCalledWith(2, 9, { version: 2, image_id: 51, role: "gallery" });
    expect(router.currentRoute.value.fullPath).toBe("/items/9");
    w.unmount();
  });

  it("does not call the API when no product was chosen", async () => {
    const { w } = await mountAt("/items/new");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createItem).not.toHaveBeenCalled();
    expect(w.find("[role=alert]").text()).toContain("请选择商品");
    w.unmount();
  });

  it("asks before leaving with unsaved changes", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { w, router } = await mountAt("/items/1/edit");
    await input(w, "收纳位置").setValue("玄关");
    await router.push("/").catch(() => {});
    await flushPromises();
    expect(confirm).toHaveBeenCalled();
    expect(router.currentRoute.value.fullPath).toBe("/items/1/edit");
    w.unmount();
  });
});

describe("item detail actions", () => {
  it("records a wear with the current version", async () => {
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 3 }));
    const { w } = await mountAt("/items/1");
    await button(w, "记一次穿着").trigger("click");
    await flushPromises();
    expect(mocks.wearItem).toHaveBeenCalledWith(1, { version: 1, worn_on: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) });
    expect(w.text()).toContain("3 次");
    w.unmount();
  });

  it("returns an item with refund amount and keeps the purchase untouched", async () => {
    mocks.returnItem.mockResolvedValue(detail({ version: 2, status: "returned", retired_on: "2025-11-10", refund_amount: 7990 }));
    const { w } = await mountAt("/items/1");
    await button(w, "退货…").trigger("click");
    await w.find(".return-form input[type=date]").setValue("2025-11-10");
    await w.find(".return-form input[type=number]").setValue("7990");
    await w.find(".return-form").trigger("submit");
    await flushPromises();
    expect(mocks.returnItem).toHaveBeenCalledWith(1, { version: 1, returned_on: "2025-11-10", refund_amount: 7990 });
    expect(mocks.updatePurchase).not.toHaveBeenCalled();
    w.unmount();
  });

  it("deletes with an undo toast that restores using the post-delete version", async () => {
    mocks.deleteItem.mockResolvedValue(null);
    mocks.restoreItem.mockResolvedValue(detail({ version: 3 }));
    const { w, router } = await mountAt("/items/1");
    await button(w, "删除").trigger("click");
    await flushPromises();
    expect(mocks.deleteItem).toHaveBeenCalledWith(1, 1);
    expect(router.currentRoute.value.fullPath).toBe("/");
    await w.findAll(".toast button").find((b) => b.text() === "撤销")!.trigger("click");
    await flushPromises();
    expect(mocks.restoreItem).toHaveBeenCalledWith(1, 2);
    expect(router.currentRoute.value.fullPath).toBe("/items/1");
    w.unmount();
  });

  it("shows pending proposals for the item and reloads after accepting one", async () => {
    mocks.proposals.mockResolvedValue({ items: [proposal()], total: 1, limit: 50, offset: 0 });
    mocks.acceptProposal.mockResolvedValue(proposal({ status: "accepted" }));
    const { w } = await mountAt("/items/1");
    expect(mocks.proposals).toHaveBeenCalledWith({ entity: "wardrobe_item", entity_id: 1 });
    expect(w.find('[data-testid="proposal-41"]').text()).toContain("2024-01-01");
    const loads = mocks.item.mock.calls.length;
    await w.find('[data-testid="proposal-41"]').findAll("button").find((b) => b.text() === "接受")!.trigger("click");
    await flushPromises();
    expect(mocks.acceptProposal).toHaveBeenCalledWith(41);
    expect(mocks.item.mock.calls.length).toBe(loads + 1);
    w.unmount();
  });

  it("a stale proposal shows the server's reason next to that proposal", async () => {
    mocks.proposals.mockResolvedValue({ items: [proposal()], total: 1, limit: 50, offset: 0 });
    mocks.acceptProposal.mockRejectedValue(new ApiError(409, "PROPOSAL_STALE", "提议 41 生成后记录已被修改，请重新确认"));
    const { w } = await mountAt("/items/1");
    await w.find('[data-testid="proposal-41"]').findAll("button").find((b) => b.text() === "接受")!.trigger("click");
    await flushPromises();
    expect(w.find('[data-testid="proposal-41"] [role=alert]').text()).toContain("已被修改");
    w.unmount();
  });
});

describe("proposal bulk decisions", () => {
  it("reports per-proposal failures from a bulk accept", async () => {
    mocks.proposals.mockResolvedValue({ items: [proposal(), proposal({ proposal_id: 42, field: "color" })], total: 2, limit: 100, offset: 0 });
    mocks.bulkProposals.mockResolvedValue({
      results: [{ proposal_id: 41, ok: true, status: "accepted" }, { proposal_id: 42, ok: false, error: { code: "PROPOSAL_STALE", message: "记录已变化" } }],
      succeeded: 1, failed: 1,
    });
    const { w } = await mountAt("/imports?tab=proposals");
    for (const cb of w.findAll(".proposal .pick input")) await cb.setValue(true);
    await w.findAll(".proposals .head button").find((b) => b.text().startsWith("接受所选"))!.trigger("click");
    await flushPromises();
    expect(mocks.bulkProposals).toHaveBeenCalledWith([41, 42], "accept");
    expect(w.find('[data-testid="proposal-42"] [role=alert]').text()).toContain("记录已变化");
    w.unmount();
  });
});

describe("product page", () => {
  it("saves only changed basic fields and keeps unsaved edits in other sections", async () => {
    mocks.putProductColors.mockResolvedValue(product({ version: 2 }));
    mocks.updateProduct.mockResolvedValue(product({ version: 3, name_zh: "新中文名" }));
    const { w } = await mountAt("/products/1");
    await input(w, "中文名").setValue("新中文名");
    await input(w, "标价").setValue("6990");
    // 先保存颜色：基本资料里未保存的修改不能被服务器结果覆盖
    await button(w, "保存颜色").trigger("click");
    await flushPromises();
    expect(mocks.putProductColors).toHaveBeenCalledWith(1, 1, [{ color_code: "09", name_ja: "BLACK", hex: "#1A1A1A", is_default: true, sort_order: 0 }]);
    expect((input(w, "中文名").element as HTMLInputElement).value).toBe("新中文名");
    await button(w, "保存基本资料").trigger("click");
    await flushPromises();
    expect(mocks.updateProduct).toHaveBeenCalledWith(1, { version: 2, name_zh: "新中文名", list_price: 6990 });
    w.unmount();
  });

  it("adds an identifier and re-parses materials from the raw text", async () => {
    mocks.addIdentifier.mockResolvedValue(product({ version: 2 }));
    mocks.putProductMaterials.mockResolvedValue(product({ version: 3 }));
    const { w } = await mountAt("/products/1");
    await w.find(".inline-form select").setValue("jan");
    await w.find(".inline-form input").setValue(" 4550000000000 ");
    await w.find(".inline-form").trigger("submit");
    await flushPromises();
    expect(mocks.addIdentifier).toHaveBeenCalledWith(1, { version: 1, scheme: "jan", value: "4550000000000" });
    await button(w, "按材质原文重新解析").trigger("click");
    await flushPromises();
    expect(mocks.putProductMaterials).toHaveBeenCalledWith(1, 2, null);
    w.unmount();
  });
});

describe("numeric inputs", () => {
  it("material percentages typed into number inputs are sent as numbers", async () => {
    mocks.putProductMaterials.mockResolvedValue(product({ version: 2 }));
    const { w } = await mountAt("/products/1");
    const pct = w.find('input[aria-label="比例"]');
    await pct.setValue("85.5");
    await button(w, "保存材质").trigger("click");
    await flushPromises();
    expect(mocks.putProductMaterials).toHaveBeenCalledWith(1, 1, [{ part: "shell", part_raw: "表地", fiber: "nylon", fiber_raw: "ナイロン", percent: 85.5 }]);
    w.unmount();
  });
});

describe("outfits", () => {
  it("creates an outfit with picked items, guessed slots and tags", async () => {
    mocks.createOutfit.mockResolvedValue(outfit({ id: 8 }));
    mocks.outfit.mockResolvedValue(outfit({ id: 8 }));
    const { w, router } = await mountAt("/outfits/new");
    await input(w, "名称").setValue("周末");
    await button(w, "添加衣物").trigger("click");
    await flushPromises();
    for (const b of w.findAll(".picker .pick")) await b.trigger("click");
    const tag = w.find(".tag-input input");
    await tag.setValue("休闲");
    await tag.trigger("keydown", { key: "Enter" });
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createOutfit).toHaveBeenCalledWith({
      name: "周末",
      items: [{ item_id: 1, slot: "outer", sort_order: 0 }, { item_id: 2, slot: "top", sort_order: 1 }],
      tags: ["休闲"],
    });
    expect(router.currentRoute.value.fullPath).toBe("/outfits/8");
    // 路由复用同一个组件实例：新建后必须回到查看模式
    expect(w.find("form").exists()).toBe(false);
    expect(w.find("h1").text()).toBe("秋季通勤");
    w.unmount();
  });

  it("saves fields, items and tags as a version chain", async () => {
    mocks.outfit.mockResolvedValue(outfit());
    mocks.updateOutfit.mockResolvedValue(outfit({ version: 3, name: "改名" }));
    mocks.setOutfitItems.mockResolvedValue(outfit({ version: 4, name: "改名" }));
    mocks.setOutfitTags.mockResolvedValue(outfit({ version: 5, name: "改名", tags: [] }));
    const { w } = await mountAt("/outfits/6");
    await button(w, "编辑").trigger("click");
    await input(w, "名称").setValue("改名");
    await w.find(".entries select").setValue("top");
    await w.find(".tag-input .x").trigger("click");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.updateOutfit).toHaveBeenCalledWith(6, { version: 2, name: "改名" });
    expect(mocks.setOutfitItems).toHaveBeenCalledWith(6, 3, [{ item_id: 1, slot: "top", sort_order: 0 }]);
    expect(mocks.setOutfitTags).toHaveBeenCalledWith(6, 4, []);
    expect(w.find("form").exists()).toBe(false);
    w.unmount();
  });
});

describe("purchases", () => {
  it("shows the product selector on new lines by default", async () => {
    const { w } = await mountAt("/purchases/new");
    // 回归：布尔 prop 省略时被当作 false，曾导致无法为明细选择商品
    expect(w.find(".product-row").exists()).toBe(true);
    w.unmount();
  });

  it("creates a purchase with lines and shows the backend's reason when create_items needs products", async () => {
    mocks.createPurchase.mockRejectedValueOnce(new ApiError(422, "VALIDATION_ERROR", "1 个字段校验失败", [{ loc: ["lines", 0, "product_id"], message: "create_items=true 时每行都需要 product_id" }]));
    const { w } = await mountAt("/purchases/new");
    await input(w, "店铺").setValue("测试店");
    await input(w, "小票名称").setValue("Mセーター");
    await input(w, "单价").setValue("3990");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createPurchase).toHaveBeenCalledWith(expect.objectContaining({
      store_name: "测试店",
      create_items: true,
      lines: [expect.objectContaining({ name_raw: "Mセーター", unit_price: 3990, quantity: 1, product_id: null })],
    }));
    expect(w.find("[role=alert]").text()).toContain("每行都需要 product_id");
    w.unmount();
  });

  it("confirms a suggested product match with the line's own version", async () => {
    mocks.purchase.mockResolvedValue(purchase());
    mocks.matchCandidates.mockResolvedValue({ line_id: 11, current_product_id: null, candidates: [{ product: { id: 12, brand: "UNIQLO", name_ja: "メリノセーター", name_zh: null, name_en: null, origin: "catalog", verification: "unverified" }, score: 0.83, reasons: ["name_similarity:0.83"] }] });
    mocks.matchLine.mockResolvedValue({});
    const { w } = await mountAt("/purchases/4");
    await button(w, "匹配商品").trigger("click");
    await flushPromises();
    expect(w.find(".candidates").text()).toContain("名称相似 83%");
    await w.find(".candidates button").trigger("click");
    await flushPromises();
    expect(mocks.matchLine).toHaveBeenCalledWith(11, { version: 2, product_id: 12, product_match: "confirmed" });
    w.unmount();
  });

  it("deleting a line uses the purchase version and shows IN_USE errors", async () => {
    mocks.purchase.mockResolvedValue(purchase());
    mocks.deleteLine.mockRejectedValue(new ApiError(409, "IN_USE", "该明细仍关联衣物，不能删除"));
    const { w } = await mountAt("/purchases/4");
    await w.find('[data-testid="line-11"]').findAll("button").find((b) => b.text() === "删除")!.trigger("click");
    await flushPromises();
    expect(mocks.deleteLine).toHaveBeenCalledWith(11, 3);
    expect(w.find("[role=alert]").text()).toContain("仍关联衣物");
    w.unmount();
  });
});

describe("import center", () => {
  it("rejects invalid JSON locally and previews valid JSON, then opens the batch", async () => {
    mocks.previewImport.mockResolvedValue(job());
    mocks.importJob.mockResolvedValue(job());
    mocks.importRows.mockResolvedValue({ items: [] });
    const { w, router } = await mountAt("/imports");
    await w.find("textarea").setValue("{bad");
    await button(w, "预览导入").trigger("click");
    await flushPromises();
    expect(mocks.previewImport).not.toHaveBeenCalled();
    expect(w.find("[role=alert]").text()).toContain("不是有效的 JSON");
    await w.find("textarea").setValue('{"format":"wardrobe.import/v1"}');
    await button(w, "预览导入").trigger("click");
    await flushPromises();
    expect(mocks.previewImport).toHaveBeenCalledWith({ format: "wardrobe.import/v1" });
    expect(router.currentRoute.value.fullPath).toBe("/imports/7");
    w.unmount();
  });

  it("lists every field error from a 422 preview", async () => {
    mocks.previewImport.mockRejectedValue(new ApiError(422, "VALIDATION_ERROR", "2 个字段校验失败", [
      { loc: ["products", 0, "colors", 0, "hex"], message: "颜色值必须为 #RRGGBB 格式" },
      { loc: ["purchases", 0, "purchased_on"], message: "缺少日期" },
    ]));
    const { w } = await mountAt("/imports");
    await w.find("textarea").setValue("{}");
    await button(w, "预览导入").trigger("click");
    await flushPromises();
    const items = w.findAll(".details li").map((li) => li.text());
    expect(items).toEqual(["products › 0 › colors › 0 › hex：颜色值必须为 #RRGGBB 格式", "purchases › 0 › purchased_on：缺少日期"]);
    w.unmount();
  });

  it("commits only after allowing partial import when rows have errors", async () => {
    mocks.importJob.mockResolvedValue(job());
    mocks.importRows.mockResolvedValue({ items: [{ row_index: 0, entity: "product", ref: "p", action: "error", target_id: null, match_reason: null, diff: {}, errors: [{ code: "AMBIGUOUS_MATCH", message: "多个商品" }], warnings: [] }] });
    mocks.commitImport.mockResolvedValue(job({ status: "committed" }));
    const { w } = await mountAt("/imports/7");
    expect(w.find('[data-testid="row-0"]').text()).toContain("AMBIGUOUS_MATCH");
    const commit = button(w, "提交导入");
    expect(commit.attributes("disabled")).toBeDefined();
    await w.find(".actions input[type=checkbox]").setValue(true);
    await commit.trigger("click");
    await flushPromises();
    expect(mocks.commitImport).toHaveBeenCalledWith(7, true);
    w.unmount();
  });

  it("shows revert conflicts without claiming success", async () => {
    mocks.importJob.mockResolvedValue(job({ status: "committed", summary: { create: 1, error: 0 } }));
    mocks.importRows.mockResolvedValue({ items: [] });
    mocks.revertImport.mockRejectedValue(new ApiError(409, "REVERT_CONFLICT", "有 1 条记录在导入后被修改", [{ entity: "product", id: 3, reason: "modified_after_import" }]));
    const { w } = await mountAt("/imports/7");
    await button(w, "撤销整批导入").trigger("click");
    await flushPromises();
    expect(w.find("[role=alert]").text()).toContain("被修改");
    expect(w.find(".details").text()).toContain("modified_after_import");
    expect(toasts.some((t) => t.text.includes("已撤销"))).toBe(false);
    w.unmount();
  });
});

describe("settings", () => {
  it("moves a category only when the parent changed and blocks deleting used tags", async () => {
    mocks.flatCategories.mockResolvedValue({ items: [{ id: 2, slug: "outer-down", name_zh: "羽绒", name_ja: null, level: 2, parent_id: 1, sort_order: 0 }] });
    mocks.updateCategory.mockResolvedValue({});
    const { w, router } = await mountAt("/settings?tab=categories");
    const row = w.findAll(".tree li")[1]!;
    await row.findAll("button").find((b) => b.text() === "编辑/移动")!.trigger("click");
    await row.find("input").setValue("羽绒服");
    await row.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.updateCategory).toHaveBeenLastCalledWith(2, { name_zh: "羽绒服", name_ja: null, sort_order: 0 });
    await w.findAll(".tree li")[1]!.findAll("button").find((b) => b.text() === "编辑/移动")!.trigger("click");
    await w.findAll(".tree li")[1]!.find("select").setValue("");
    await w.findAll(".tree li")[1]!.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.updateCategory).toHaveBeenLastCalledWith(2, { name_zh: "羽绒", name_ja: null, sort_order: 0, parent: null });
    await router.push("/settings?tab=tags");
    await flushPromises();
    const del = w.findAll("tbody button").find((b) => b.text() === "删除")!;
    expect(del.attributes("disabled")).toBeDefined();
    w.unmount();
  });

  it("creating a duplicate brand shows the server message", async () => {
    mocks.createBrand.mockRejectedValue(new ApiError(409, "DUPLICATE", "品牌 slug 'uniqlo' 已存在"));
    const { w } = await mountAt("/settings");
    await input(w, "标识").setValue("uniqlo");
    await input(w, "名称").setValue("UNIQLO");
    await w.findAll("form").at(-1)!.trigger("submit");
    await flushPromises();
    expect(mocks.createBrand).toHaveBeenCalledWith({ slug: "uniqlo", name: "UNIQLO", name_ja: null, name_zh: null, website: null });
    expect(w.find("[role=alert]").text()).toContain("已存在");
    w.unmount();
  });
});

// 独立 QA 追加：不改变产品实现或放宽原断言。
describe('independent Phase 4 boundary checks', () => {
  it('preserves existing measurement details when saving the sizes section', async () => {
    const size = {id:1,size_label:'M',size_system:'alpha',size_detail:{chest_cm:104,length_cm:68}};
    mocks.product.mockResolvedValue(product({sizes:[size]}));
    mocks.putProductSizes.mockResolvedValue(product({version:2,sizes:[size]}));
    const {w}=await mountAt('/products/1');
    await button(w,'保存尺码').trigger('click'); await flushPromises();
    expect(mocks.putProductSizes.mock.calls[0][2][0].size_detail).toEqual(size.size_detail);
    w.unmount();
  });

  it('does not create another item when retrying a failed staged-photo association', async () => {
    const created=detail({id:9,version:1,images:[]});
    mocks.uploadImage.mockResolvedValue({id:50,thumb_url:'/t/50.webp'});
    mocks.createItem.mockResolvedValue(created);
    mocks.addItemImage.mockRejectedValueOnce(new ApiError(503,'QA_TEMPORARY','临时图片关联失败'))
      .mockResolvedValueOnce({...created,version:2,images:[{id:50,role:'main'}]});
    const {w}=await mountAt('/items/new');
    await button(w,'新建商品').trigger('click');
    await input(w,'日文名').setValue('QA Retry Manual Item');
    const f=w.find('.uploader input[type=file]');
    Object.defineProperty(f.element,'files',{value:[new File(['a'],'a.png')],configurable:true});
    await f.trigger('change'); await flushPromises();
    await w.find('form').trigger('submit'); await flushPromises();
    expect(mocks.createItem).toHaveBeenCalledTimes(1);
    expect(w.text()).toContain('临时图片关联失败');
    await w.find('form').trigger('submit'); await flushPromises();
    expect(mocks.createItem).toHaveBeenCalledTimes(1);
    w.unmount();
  });

  it('serializes image associations for an existing item with returned versions', async () => {
    let finish!: (x:unknown)=>void;
    mocks.uploadImage.mockResolvedValueOnce({id:50}).mockResolvedValueOnce({id:51});
    mocks.addItemImage.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}))
      .mockResolvedValueOnce(detail({version:3}));
    const {w}=await mountAt('/items/1/edit');
    const f=w.find('.uploader input[type=file]');
    Object.defineProperty(f.element,'files',{value:[new File(['a'],'a.png'),new File(['b'],'b.png')],configurable:true});
    await f.trigger('change'); await flushPromises();
    const callsBeforeFirstCompletion=mocks.addItemImage.mock.calls.map(c=>[...c]);
    finish(detail({version:2})); await flushPromises();
    expect(callsBeforeFirstCompletion).toHaveLength(1);
    expect(mocks.addItemImage.mock.calls[1][1].version).toBe(2);
    w.unmount();
  });

  it('preserves unsaved purchase-header input when verifying a line', async () => {
    mocks.purchase.mockResolvedValue(purchase());
    mocks.verifyLine.mockResolvedValue({});
    const {w}=await mountAt('/purchases/4');
    await button(w,'编辑购买信息').trigger('click');
    await input(w,'店铺').setValue('QA unsaved store');
    await button(w,'核实').trigger('click'); await flushPromises();
    expect(mocks.verifyLine).toHaveBeenCalledTimes(1);
    expect((input(w,'店铺').element as HTMLInputElement).value).toBe('QA unsaved store');
    w.unmount();
  });

  it('does not silently turn zero purchase quantity into one', async () => {
    mocks.createPurchase.mockResolvedValue(purchase());
    mocks.purchase.mockResolvedValue(purchase());
    const {w}=await mountAt('/purchases/new');
    await input(w,'数量').setValue('0');
    await w.find('form').trigger('submit'); await flushPromises();
    expect(mocks.createPurchase).not.toHaveBeenCalledWith(expect.objectContaining({lines:[expect.objectContaining({quantity:1})]}));
    w.unmount();
  });
});

it('independent: an English-only new-item draft prompts before leaving', async () => {
  const {w,router}=await mountAt('/items/new');
  await button(w,'新建商品').trigger('click');
  await input(w,'英文名').setValue('QA English-only draft');
  vi.mocked(window.confirm).mockClear().mockReturnValue(false);
  await router.push('/settings'); await flushPromises();
  expect(window.confirm).toHaveBeenCalledWith('有尚未保存的修改，确定离开吗？');
  expect(router.currentRoute.value.fullPath).toBe('/items/new');
  w.unmount();
});

// Claude 针对 Phase 4 独立审查的补充回归（P4-QA-001～006 的相邻路径）
describe("review fixes: data fidelity and partial saves", () => {
  it("keeps size_detail when relabelling a size, and new sizes are sent without it", async () => {
    const size = { id: 1, size_label: "M", size_system: "alpha", size_detail: { chest_cm: 104 } };
    mocks.product.mockResolvedValue(product({ sizes: [size] }));
    mocks.putProductSizes.mockResolvedValue(product({ version: 2, sizes: [size] }));
    const { w } = await mountAt("/products/1");
    await w.find('input[aria-label="尺码"]').setValue("M-tall");
    await button(w, "添加尺码").trigger("click");
    await w.findAll('input[aria-label="尺码"]')[1]!.setValue("L");
    await button(w, "保存尺码").trigger("click");
    await flushPromises();
    expect(mocks.putProductSizes).toHaveBeenCalledWith(1, 1, [
      { size_label: "M-tall", size_system: "alpha", size_detail: { chest_cm: 104 }, sort_order: 0 },
      { size_label: "L", size_system: "alpha", sort_order: 1 },
    ]);
    w.unmount();
  });

  it("links several product images one after another with returned versions", async () => {
    let finish!: (p: Product) => void;
    mocks.product.mockResolvedValue(product({ images: [] }));
    mocks.uploadImage.mockResolvedValueOnce({ id: 50 }).mockResolvedValueOnce({ id: 51 });
    mocks.addProductImage
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce(product({ version: 3 }));
    const { w } = await mountAt("/products/1");
    const f = w.find(".uploader input[type=file]");
    Object.defineProperty(f.element, "files", { value: [new File(["a"], "a.png"), new File(["b"], "b.png")], configurable: true });
    await f.trigger("change");
    await flushPromises();
    expect(mocks.addProductImage).toHaveBeenCalledTimes(1);
    finish(product({ version: 2, images: [{ ...detail().product.images[0]!, id: 50, role: "main" }] }));
    await flushPromises();
    expect(mocks.addProductImage).toHaveBeenNthCalledWith(1, 1, { version: 1, image_id: 50, role: "main" });
    expect(mocks.addProductImage).toHaveBeenNthCalledWith(2, 1, { version: 2, image_id: 51, role: "gallery" });
    w.unmount();
  });

  it("a failed image association stops the queue and can be retried without re-uploading", async () => {
    mocks.uploadImage.mockResolvedValueOnce({ id: 50 }).mockResolvedValueOnce({ id: 51 });
    mocks.addItemImage.mockRejectedValueOnce(new ApiError(503, "TEMP", "暂时失败"));
    const { w } = await mountAt("/items/1/edit");
    const f = w.find(".uploader input[type=file]");
    Object.defineProperty(f.element, "files", { value: [new File(["a"], "a.png"), new File(["b"], "b.png")], configurable: true });
    await f.trigger("change");
    await flushPromises();
    expect(mocks.uploadImage).toHaveBeenCalledTimes(1); // 第一张关联失败后不再处理后续文件
    expect(w.find(".pending").text()).toContain("1 张照片");
    mocks.addItemImage.mockResolvedValueOnce(detail({ version: 2, images: [{ ...detail().images[0]!, id: 50, role: "main" }] }));
    await w.find(".pending button").trigger("click");
    await flushPromises();
    expect(mocks.uploadImage).toHaveBeenCalledTimes(1);
    expect(mocks.addItemImage).toHaveBeenLastCalledWith(1, { version: 1, image_id: 50, role: "gallery" });
    expect(w.find(".pending").exists()).toBe(false);
    w.unmount();
  });

  it("retrying a new item after a lost association response does not relink an already linked photo", async () => {
    const created = detail({ id: 9, version: 1, images: [] });
    mocks.uploadImage.mockResolvedValue({ id: 50, thumb_url: "/t/50.webp" });
    mocks.createItem.mockResolvedValue(created);
    mocks.addItemImage.mockRejectedValueOnce(new ApiError(0, "NETWORK", "连接中断"));
    // 关联其实已经成功，只是响应丢失
    mocks.item.mockResolvedValue({ ...created, version: 2, images: [{ ...detail().images[0]!, id: 50, role: "main" }] });
    const { w, router } = await mountAt("/items/new");
    await button(w, "新建商品").trigger("click");
    await input(w, "日文名").setValue("重试测试");
    const f = w.find(".uploader input[type=file]");
    Object.defineProperty(f.element, "files", { value: [new File(["a"], "a.png")], configurable: true });
    await f.trigger("change");
    await flushPromises();
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.find("[role=alert]").text()).toContain("衣物已创建（#9）");
    expect(w.find(".form-actions button[type=submit]").text()).toBe("继续关联照片");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createItem).toHaveBeenCalledTimes(1);
    expect(mocks.addItemImage).toHaveBeenCalledTimes(1);
    expect(router.currentRoute.value.fullPath).toBe("/items/9");
    w.unmount();
  });

  it("when the tag step fails after fields were saved, retry sends only tags with the new version", async () => {
    mocks.updateItem.mockResolvedValue(detail({ version: 2, location: "玄关" }));
    mocks.setItemTags.mockRejectedValueOnce(new ApiError(0, "NETWORK", "连接中断")).mockResolvedValueOnce(detail({ version: 3, location: "玄关", tags: [] }));
    const { w } = await mountAt("/items/1/edit");
    await input(w, "收纳位置").setValue("玄关");
    await w.find(".tag-input .x").trigger("click");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.find("[role=alert]").text()).toContain("连接中断");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.updateItem).toHaveBeenCalledTimes(1);
    expect(mocks.setItemTags).toHaveBeenLastCalledWith(1, 2, []);
    w.unmount();
  });

  it("when the outfit items step fails, retry does not resend saved fields", async () => {
    mocks.outfit.mockResolvedValue(outfit());
    mocks.updateOutfit.mockResolvedValue(outfit({ version: 3, name: "改名" }));
    mocks.setOutfitItems.mockRejectedValueOnce(new ApiError(0, "NETWORK", "连接中断")).mockResolvedValueOnce(outfit({ version: 4, name: "改名", items: [{ slot: "top", sort_order: 0, item: summary() }] }));
    const { w } = await mountAt("/outfits/6");
    await button(w, "编辑").trigger("click");
    await input(w, "名称").setValue("改名");
    await w.find(".entries select").setValue("top");
    await w.find("form").trigger("submit");
    await flushPromises();
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.updateOutfit).toHaveBeenCalledTimes(1);
    expect(mocks.setOutfitItems).toHaveBeenLastCalledWith(6, 3, [{ item_id: 1, slot: "top", sort_order: 0 }]);
    w.unmount();
  });
});

describe("review fixes: purchase drafts and quantity", () => {
  it.each(["0", "", "-1", "1.5", "100"])("rejects quantity %j locally without writing anything", async (q) => {
    const { w } = await mountAt("/purchases/new");
    await input(w, "数量").setValue(q);
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createPurchase).not.toHaveBeenCalled();
    expect(w.find(".field-error").text()).toContain("1～99");
    w.unmount();
  });

  it("accepts the boundary quantities 1 and 99", async () => {
    mocks.createPurchase.mockResolvedValue(purchase());
    mocks.purchase.mockResolvedValue(purchase());
    const { w } = await mountAt("/purchases/new");
    await input(w, "数量").setValue("99");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.createPurchase).toHaveBeenCalledWith(expect.objectContaining({ lines: [expect.objectContaining({ quantity: 99 })] }));
    w.unmount();
  });

  it("validates quantity when editing and appending lines too", async () => {
    mocks.purchase.mockResolvedValue(purchase());
    const { w } = await mountAt("/purchases/4");
    await w.find('[data-testid="line-11"]').findAll("button").find((b) => b.text() === "编辑")!.trigger("click");
    await input(w.find('[data-testid="line-11"]') as never, "数量").setValue("0");
    await w.find('[data-testid="line-11"] form').trigger("submit");
    await flushPromises();
    expect(mocks.updateLine).not.toHaveBeenCalled();
    await button(w, "追加明细").trigger("click");
    const add = w.find(".sub-form");
    await add.findAll("label.field").find((l) => l.text().startsWith("数量"))!.find("input").setValue("");
    await add.trigger("submit");
    await flushPromises();
    expect(mocks.addLine).not.toHaveBeenCalled();
    w.unmount();
  });

  it("keeps the unsaved header after matching or appending lines, and explicit reload discards it", async () => {
    mocks.purchase.mockResolvedValue(purchase());
    mocks.addLine.mockResolvedValue(purchase({ version: 4 }));
    mocks.matchCandidates.mockResolvedValue({ line_id: 11, current_product_id: null, candidates: [{ product: { id: 12, brand: null, name_ja: "X", name_zh: null, name_en: null, origin: "catalog", verification: "unverified" }, reasons: [] }] });
    mocks.matchLine.mockResolvedValue({});
    const { w } = await mountAt("/purchases/4");
    await button(w, "编辑购买信息").trigger("click");
    await input(w, "店铺").setValue("草稿店名");
    await button(w, "匹配商品").trigger("click");
    await flushPromises();
    await w.find(".candidates button").trigger("click");
    await flushPromises();
    expect((input(w, "店铺").element as HTMLInputElement).value).toBe("草稿店名");
    await button(w, "追加明细").trigger("click");
    await w.find(".sub-form").findAll("label.field").find((l) => l.text().startsWith("小票名称"))!.find("input").setValue("追加的");
    await w.find(".sub-form").trigger("submit");
    await flushPromises();
    expect(mocks.addLine).toHaveBeenCalled();
    expect((input(w, "店铺").element as HTMLInputElement).value).toBe("草稿店名");
    w.unmount();
  });

  it.each([["品牌", "uniqlo"], ["中文名", "仅中文"], ["英文名", "only english"]])("a new-product draft with only %s asks before leaving", async (field, value) => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { w, router } = await mountAt("/items/new");
    await button(w, "新建商品").trigger("click");
    await input(w, field).setValue(value);
    await router.push("/settings").catch(() => {});
    await flushPromises();
    expect(confirm).toHaveBeenCalled();
    expect(router.currentRoute.value.fullPath).toBe("/items/new");
    w.unmount();
  });
});

describe("review fixes: stale loads", () => {
  it("an import batch page ignores the previous batch's late response", async () => {
    let finishOld!: (j: ImportJob) => void;
    mocks.importJob.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; })).mockResolvedValue(job({ job_id: 8, source_label: "新批次" }));
    mocks.importRows.mockResolvedValue({ items: [] });
    const { w, router } = await mountAt("/imports/7");
    await router.push("/imports/8");
    await flushPromises();
    finishOld(job({ job_id: 7, source_label: "旧批次" }));
    await flushPromises();
    expect(w.find("h1").text()).toBe("新批次");
    w.unmount();
  });
});

it("a cancelled navigation does not change the document title", async () => {
  const { router: appRouter } = await import("../src/router");
  vi.spyOn(window, "confirm").mockReturnValue(false);
  await appRouter.push("/items/1/edit");
  await appRouter.isReady();
  const w = mount(App, { global: { plugins: [appRouter] }, attachTo: document.body });
  await flushPromises();
  await input(w, "收纳位置").setValue("草稿");
  const title = document.title;
  await appRouter.push("/settings").catch(() => {});
  await flushPromises();
  expect(appRouter.currentRoute.value.name).toBe("item-edit");
  expect(document.title).toBe(title);
  w.unmount();
});
