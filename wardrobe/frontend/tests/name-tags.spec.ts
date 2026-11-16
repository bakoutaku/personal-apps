// 试用反馈：标签建议增加「商品名称中的常用叫法」（wardrobe-tagcat/3）。API 全部为 mock，不访问网络。
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { ItemSuggestions, Proposal } from "../src/api/types";
import { routes } from "../src/router";
import { toasts } from "../src/lib/toast";
import { detail } from "./fixtures";

const mocks = vi.hoisted(() => {
  const names = ["item", "proposals", "similarItems", "tagSuggestions", "createTagSuggestions"] as const;
  return Object.fromEntries(names.map((n) => [n, vi.fn()])) as Record<(typeof names)[number], ReturnType<typeof vi.fn>>;
});

vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});

import App from "../src/App.vue";

const NAME = { kind: "name_alias", label: "商品名称含「パーカ」（常用叫法）" };

function suggestions(): ItemSuggestions {
  return {
    algorithm: "wardrobe-tagcat/3", item_id: 1, item_version: 1, category_note: "already_categorized", category: null,
    tags: [
      { name: "卫衣", reasons: [{ kind: "name_alias", label: "商品名称含「スウェット」（常用叫法）" }], evidence: { same_product_item_ids: [], name_words: ["スウェット"], similar_item_ids: [], similar_pool: 0 } },
      { name: "帽衫", reasons: [NAME], evidence: { same_product_item_ids: [], name_words: ["パーカ"], similar_item_ids: [], similar_pool: 0 } },
      { name: "连帽卫衣", reasons: [NAME], evidence: { same_product_item_ids: [], name_words: ["パーカ"], similar_item_ids: [], similar_pool: 0 } },
    ],
  };
}

function tagsProposal(algorithm: string, id: number): Proposal {
  return {
    proposal_id: id, entity: "wardrobe_item", entity_id: 1, field: "tags_add", current_value: [], proposed_value: ["帽衫"],
    reason: null, actor: "web-ui", import_job_id: null, status: "pending", created_at: "2026-10-28T00:00:00Z", decided_at: null,
    ai_context: null,
    rule_context: { kind: "tags", source: "rule_based", algorithm, target_version: 1, created_at: "", evidence: { tags: [{ name: "帽衫", reasons: [NAME] }] } },
  };
}

async function mountAt(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(path);
  await router.isReady();
  const w = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return w;
}

const button = (w: ReturnType<typeof mount>, text: string) => w.findAll("button").find((b) => b.text().trim() === text);

beforeEach(() => {
  for (const m of Object.values(mocks)) m.mockReset();
  toasts.splice(0);
  mocks.item.mockResolvedValue(detail({ tags: [] }));
  mocks.proposals.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  mocks.similarItems.mockResolvedValue({ item_id: 1, algorithm: "", weights: {}, max_shared_tags: 3, min_score: 3, status: "owned", items: [] });
  mocks.tagSuggestions.mockResolvedValue(suggestions());
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("common-name tags from the product name", () => {
  it("lists every common name with its reason and submits the picked ones", async () => {
    mocks.createTagSuggestions.mockResolvedValue({ proposals: [tagsProposal("wardrobe-tagcat/3", 61)] });
    const w = await mountAt("/items/1");
    await button(w, "建议标签/分类")!.trigger("click");
    await flushPromises();
    for (const name of ["卫衣", "帽衫", "连帽卫衣"]) expect(w.find(`[data-testid="tag-opt-${name}"]`).exists()).toBe(true);
    expect(w.find('[data-testid="tag-opt-帽衫"]').text()).toContain("商品名称含「パーカ」（常用叫法）");
    await w.find('[data-testid="tag-opt-卫衣"] input').setValue(false);
    await button(w, "生成待确认提议")!.trigger("click");
    await flushPromises();
    expect(mocks.createTagSuggestions).toHaveBeenCalledWith(1, { version: 1, tags: ["帽衫", "连帽卫衣"], category_id: null });
    w.unmount();
  });

  it("describes the tag source according to the rule version of the proposal", async () => {
    mocks.proposals.mockResolvedValue({ items: [tagsProposal("wardrobe-tagcat/3", 61), tagsProposal("wardrobe-tagcat/2", 62)], total: 2, limit: 50, offset: 0 });
    const w = await mountAt("/items/1");
    const v3 = w.find('[data-testid="proposal-61"] [data-testid="rule-source"]').text();
    const v2 = w.find('[data-testid="proposal-62"] [data-testid="rule-source"]').text();
    expect(v3).toContain("根据同一商品的其他衣物、同类相似衣物的标签和商品名称中的常用叫法");
    expect(v3).toContain("#帽衫：商品名称含「パーカ」（常用叫法）");
    expect(v2).toContain("根据同一商品的其他衣物和同类相似衣物的标签");
    expect(v2).not.toContain("常用叫法，");
    w.unmount();
  });
});
