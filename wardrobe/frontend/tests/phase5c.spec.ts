// Phase 5C：标签 / 分类规则建议（单件面板、批量页、提议列表显示）。API 全部为 mock，不访问网络。
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { ItemSuggestions, Proposal } from "../src/api/types";
import { dict } from "../src/lib/dictionaries";
import { routes } from "../src/router";
import { toasts } from "../src/lib/toast";
import { detail, summary } from "./fixtures";

const mocks = vi.hoisted(() => {
  const names = [
    "item", "proposals", "similarItems", "tagSuggestions", "createTagSuggestions", "batchTagSuggestions",
    "createBatchTagSuggestions", "wearItem", "changes", "imports",
  ] as const;
  return Object.fromEntries(names.map((n) => [n, vi.fn()])) as Record<(typeof names)[number], ReturnType<typeof vi.fn>>;
});

vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});

import App from "../src/App.vue";
import { ApiError } from "../src/api/client";

function suggestions(overrides: Partial<ItemSuggestions> = {}): ItemSuggestions {
  return {
    algorithm: "wardrobe-tagcat/1", item_id: 1, item_version: 1, category_note: null,
    tags: [
      { name: "冬", reasons: [{ kind: "similar_items", label: "相似衣物中 2/3 件有此标签" }], evidence: { same_product_item_ids: [], similar_item_ids: [4, 5], similar_pool: 3 } },
      { name: "雨天", reasons: [{ kind: "same_product", label: "同一商品的其他衣物有此标签（#9）" }], evidence: { same_product_item_ids: [9], similar_item_ids: [], similar_pool: 3 } },
    ],
    category: { category_id: 14, slug: "outer-down-jacket", path: ["外套", "羽绒", "羽绒服"], reasons: [{ kind: "name_keyword", label: "商品名称含「だうんじゃけっと」" }], evidence: {} },
    ...overrides,
  };
}

function proposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    proposal_id: 51, entity: "wardrobe_item", entity_id: 1, field: "category_id", current_value: null, proposed_value: 14,
    reason: null, actor: "web-ui", import_job_id: null, status: "pending", created_at: "2026-10-27T00:00:00Z", decided_at: null,
    ai_context: null,
    rule_context: { kind: "category", source: "rule_based", algorithm: "wardrobe-tagcat/1", target_version: 1, created_at: "", evidence: { reasons: [{ label: "商品名称含「だうんじゃけっと」" }] } },
    ...overrides,
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

const button = (w: ReturnType<typeof mount>, text: string) => w.findAll("button").find((b) => b.text().trim() === text);
async function openPanel(w: ReturnType<typeof mount>) {
  await button(w, "建议标签/分类")!.trigger("click");
  await flushPromises();
}

beforeEach(() => {
  for (const m of Object.values(mocks)) m.mockReset();
  toasts.splice(0);
  mocks.item.mockImplementation(async (id: number) => detail({ id, name: `衣物 ${id}` }));
  mocks.proposals.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  mocks.similarItems.mockResolvedValue({ item_id: 1, algorithm: "", weights: {}, max_shared_tags: 3, min_score: 3, status: "owned", items: [] });
  mocks.tagSuggestions.mockResolvedValue(suggestions());
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("item tag / category suggestions", () => {
  it("shows the suggestions with reasons and creates only pending proposals for the picked ones", async () => {
    mocks.createTagSuggestions.mockResolvedValue({ proposals: [proposal(), proposal({ proposal_id: 52, field: "tags_add" })] });
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    expect(mocks.tagSuggestions).toHaveBeenCalledWith(1);
    expect(w.find(".tag-panel").text()).toContain("不是图像识别");
    expect(w.find('[data-testid="tag-opt-冬"]').text()).toContain("相似衣物中 2/3 件有此标签");
    expect(w.find('[data-testid="cat-opt"]').text()).toContain("外套 / 羽绒 / 羽绒服");
    await w.find('[data-testid="tag-opt-雨天"] input').setValue(false);
    const before = mocks.proposals.mock.calls.length;
    await button(w, "生成待确认提议")!.trigger("click");
    await flushPromises();
    expect(mocks.createTagSuggestions).toHaveBeenCalledWith(1, { version: 1, tags: ["冬"], category_id: 14 });
    expect(w.find(".tag-panel .done").text()).toContain("已生成 2 条待确认提议（尚未应用）");
    expect(mocks.proposals.mock.calls.length).toBe(before + 1);
    w.unmount();
  });

  it("cannot submit with nothing picked, and explains when there is nothing to suggest", async () => {
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    for (const cb of w.findAll(".tag-panel input[type=checkbox]")) await cb.setValue(false);
    expect(button(w, "生成待确认提议")!.attributes("disabled")).toBeDefined();
    w.unmount();
    mocks.tagSuggestions.mockResolvedValue(suggestions({ tags: [], category: null, category_note: "ambiguous" }));
    const again = await mountAt("/items/1");
    await openPanel(again.w);
    expect(again.w.find('[data-testid="tag-nothing"]').text()).toContain("无法判断");
    again.w.unmount();
  });

  it("blocks generation when the item changed after reading the suggestions", async () => {
    mocks.wearItem.mockResolvedValue(detail({ version: 2, name: "衣物 1" }));
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    expect(w.find(".tag-panel [role=alert]").text()).toContain("请重新读取");
    expect(button(w, "生成待确认提议")!.attributes("disabled")).toBeDefined();
    w.unmount();
  });

  it("shows server errors without claiming success", async () => {
    mocks.createTagSuggestions.mockRejectedValue(new ApiError(422, "VALIDATION_ERROR", "「冬」不在当前的标签建议中"));
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "生成待确认提议")!.trigger("click");
    await flushPromises();
    expect(w.find(".tag-panel [role=alert]").text()).toContain("不在当前的标签建议中");
    expect(w.find(".tag-panel .done").exists()).toBe(false);
    w.unmount();
  });

  it("a late suggestion response after switching items is not shown", async () => {
    let finish!: (v: ItemSuggestions) => void;
    mocks.tagSuggestions.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { w, router } = await mountAt("/items/1");
    await openPanel(w);
    await router.push("/items/2");
    await flushPromises();
    finish(suggestions());
    await flushPromises();
    expect(w.find(".tag-panel").exists()).toBe(false);
    w.unmount();
  });
});

describe("rule suggestions in the proposal list", () => {
  it("shows the category name, the rule source and the append-only note", async () => {
    dict.flatCategories = [{ id: 14, slug: "outer-down-jacket", name_zh: "羽绒服", name_ja: null, level: 3, parent_id: 2, sort_order: 0 }];
    mocks.proposals.mockResolvedValue({
      items: [proposal(), proposal({ proposal_id: 52, field: "tags_add", current_value: ["旧"], proposed_value: ["冬"], rule_context: { ...proposal().rule_context!, kind: "tags", evidence: { tags: [{ name: "冬", reasons: [{ label: "相似衣物中 2/3 件有此标签" }] }] } } })],
      total: 2, limit: 50, offset: 0,
    });
    const { w } = await mountAt("/items/1");
    const cat = w.find('[data-testid="proposal-51"]');
    expect(cat.text()).toContain("羽绒服（#14）");
    expect(cat.find('[data-testid="rule-source"]').text()).toContain("规则建议（wardrobe-tagcat/1");
    const tags = w.find('[data-testid="proposal-52"]');
    expect(tags.text()).toContain("追加");
    expect(tags.find('[data-testid="rule-source"]').text()).toContain("只追加，不删除已有标签");
    expect(tags.find('[data-testid="rule-source"]').text()).toContain("#冬：相似衣物中 2/3 件有此标签");
    w.unmount();
  });
});

describe("batch suggestions", () => {
  function batch() {
    return {
      algorithm: "wardrobe-tagcat/1", total: 2, limit: 50, offset: 0,
      items: [
        { ...suggestions({ item_id: 1 }), item: summary({ id: 1, name: "甲" }) },
        { ...suggestions({ item_id: 2, item_version: 3, category: null }), item: summary({ id: 2, name: "乙" }) },
      ],
    };
  }

  it("lists items, lets the user pick, and reports per-item results", async () => {
    mocks.batchTagSuggestions.mockResolvedValue(batch());
    mocks.createBatchTagSuggestions.mockResolvedValue({
      results: [{ item_id: 1, ok: true, proposals: [proposal()] }, { item_id: 2, ok: false, error: { code: "VERSION_CONFLICT", message: "版本冲突" } }],
      succeeded: 1, failed: 1,
    });
    const { w } = await mountAt("/imports?tab=suggest");
    expect(mocks.changes).not.toHaveBeenCalled();
    expect(w.findAll(".batch .rows > li")).toHaveLength(2);
    await button(w, "全不选")!.trigger("click");
    expect(w.find(".batch .btn").attributes("disabled")).toBeDefined();
    const row1 = w.find('[data-testid="batch-1"]');
    await row1.findAll("input[type=checkbox]").at(-1)!.setValue(true); // 分类
    await w.find('[data-testid="batch-2"] input[type=checkbox]').setValue(true); // 「冬」
    await w.find(".batch .btn").trigger("click");
    await flushPromises();
    expect(mocks.createBatchTagSuggestions).toHaveBeenCalledWith([
      { item_id: 1, version: 1, tags: [], category_id: 14 },
      { item_id: 2, version: 3, tags: ["冬"], category_id: null },
    ]);
    expect(w.find('[data-testid="batch-1"]').text()).toContain("已生成 1 条提议");
    expect(w.find('[data-testid="batch-2"]').text()).toContain("失败：版本冲突");
    w.unmount();
  });

  it("shows an empty state", async () => {
    mocks.batchTagSuggestions.mockResolvedValue({ algorithm: "", total: 0, limit: 50, offset: 0, items: [] });
    const { w } = await mountAt("/imports?tab=suggest");
    expect(w.find('[data-testid="batch-empty"]').exists()).toBe(true);
    w.unmount();
  });
});
