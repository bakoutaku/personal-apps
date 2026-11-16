// Phase 5B：衣物详情中的相似衣物。API 全部为 mock，不访问网络。
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { SimilarItems } from "../src/api/types";
import { routes } from "../src/router";
import { detail, summary } from "./fixtures";

const mocks = vi.hoisted(() => {
  const names = ["item", "proposals", "similarItems", "acceptProposal", "wearItem"] as const;
  return Object.fromEntries(names.map((n) => [n, vi.fn()])) as Record<(typeof names)[number], ReturnType<typeof vi.fn>>;
});

vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});

import App from "../src/App.vue";
import { ApiError } from "../src/api/client";

function similar(ids: number[], overrides: Partial<SimilarItems> = {}): SimilarItems {
  return {
    item_id: 1, algorithm: "wardrobe-similar/1", weights: {}, max_shared_tags: 3, min_score: 3, status: "owned",
    items: ids.map((id) => ({
      score: 9,
      reasons: [
        { kind: "same_category", label: "同类衣物（轻羽绒）", points: 4 },
        { kind: "same_color_family", label: "颜色相近（藏青）", points: 3 },
        { kind: "shared_tags", label: "共有标签：#通勤", points: 2 },
      ],
      item: summary({ id, name: `相似 ${id}` }),
    })),
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

beforeEach(() => {
  for (const m of Object.values(mocks)) m.mockReset();
  mocks.item.mockImplementation(async (id: number) => detail({ id, name: `衣物 ${id}` }));
  mocks.proposals.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  mocks.similarItems.mockResolvedValue(similar([2, 3]));
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("similar items", () => {
  it("lists similar items with their reasons and links to their detail pages", async () => {
    const { w } = await mountAt("/items/1");
    expect(mocks.similarItems).toHaveBeenCalledWith(1);
    const card = w.find('[data-testid="similar-2"]');
    expect(card.find('a[href="/items/2"]').exists()).toBe(true);
    expect(card.findAll(".reasons .chip").map((c) => c.text())).toEqual(["同类衣物（轻羽绒）", "颜色相近（藏青）", "共有标签：#通勤"]);
    expect(w.find(".similar").text()).toContain("不使用图像识别");
    w.unmount();
  });

  it("shows an empty state when nothing is similar enough", async () => {
    mocks.similarItems.mockResolvedValue(similar([]));
    const { w } = await mountAt("/items/1");
    expect(w.find('[data-testid="similar-empty"]').text()).toContain("没有足够相似的持有中衣物");
    w.unmount();
  });

  it("a failure only affects the section, not the item detail", async () => {
    mocks.similarItems.mockRejectedValue(new ApiError(500, "X", "服务暂时不可用"));
    const { w } = await mountAt("/items/1");
    expect(w.find(".similar").text()).toContain("服务暂时不可用");
    expect(w.find("h1").text()).toBe("衣物 1");
    w.unmount();
  });

  it("clicking a similar item opens it and reloads recommendations for that item", async () => {
    const { w, router } = await mountAt("/items/1");
    mocks.similarItems.mockResolvedValue(similar([5]));
    await w.find('[data-testid="similar-2"] a').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/items/2");
    expect(w.find("h1").text()).toBe("衣物 2");
    expect(mocks.similarItems).toHaveBeenLastCalledWith(2);
    expect(w.find('[data-testid="similar-5"]').exists()).toBe(true);
    expect(w.find('[data-testid="similar-3"]').exists()).toBe(false);
    w.unmount();
  });

  it("a late response for the previous item is ignored", async () => {
    let finishOld!: (v: SimilarItems) => void;
    mocks.similarItems.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
    const { w, router } = await mountAt("/items/1");
    mocks.similarItems.mockResolvedValue(similar([7]));
    await router.push("/items/2");
    await flushPromises();
    finishOld(similar([2, 3]));
    await flushPromises();
    expect(w.find('[data-testid="similar-7"]').exists()).toBe(true);
    expect(w.find('[data-testid="similar-3"]').exists()).toBe(false);
    w.unmount();
  });
});

describe("SimilarItems component", () => {
  it("on the same instance, a late response for the previous item id is ignored", async () => {
    const { default: SimilarItemsSection } = await import("../src/components/SimilarItems.vue");
    let finishOld!: (v: SimilarItems) => void;
    mocks.similarItems.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
    const router = createRouter({ history: createMemoryHistory(), routes });
    const w = mount(SimilarItemsSection, { props: { itemId: 1, basis: "" }, global: { plugins: [router] } });
    mocks.similarItems.mockResolvedValue(similar([7]));
    await w.setProps({ itemId: 2 });
    await flushPromises();
    finishOld(similar([2, 3]));
    await flushPromises();
    expect(w.find('[data-testid="similar-7"]').exists()).toBe(true);
    expect(w.find('[data-testid="similar-3"]').exists()).toBe(false);
    w.unmount();
  });
});

// GPT 独立审查 P5B-GPT-QA-001 的复现（REVIEW_PHASE5B_INDEPENDENT_2026-10-27.md），原样加入
it("accepting colour proposal reloads recommendations for the changed current item", async () => {
 mocks.proposals.mockResolvedValue({items:[{proposal_id:41,entity:"wardrobe_item",entity_id:1,field:"color",current_value:{color_code:null,color_name:null,color_hex:null},proposed_value:{color_code:null,color_name:null,color_hex:"#C81E1E"},status:"pending",actor:"cli",created_at:"2026-10-27",decided_at:null,reason:null,import_job_id:null,ai_context:null}],total:1,limit:50,offset:0});
 const {w}=await mountAt("/items/1");
 expect(w.find('[data-testid="similar-2"]').exists()).toBe(true);
 mocks.item.mockResolvedValue(detail({id:1,name:"UPDATED RED ITEM",version:2,color_hex:"#C81E1E"}));
 mocks.proposals.mockResolvedValue({items:[],total:0,limit:50,offset:0});
 mocks.similarItems.mockResolvedValue(similar([9]));
 mocks.acceptProposal.mockResolvedValue({});
 await w.findAll("button").find(x=>x.text().trim()==="接受")!.trigger("click"); await flushPromises();
 expect(w.find("h1").text()).toBe("UPDATED RED ITEM");
 expect(mocks.similarItems).toHaveBeenCalledTimes(2);
 expect(w.find('[data-testid="similar-9"]').exists()).toBe(true);
 expect(w.find('[data-testid="similar-2"]').exists()).toBe(false);
 w.unmount();
});

// P5B-GPT-QA-001 的补充回归：同一件衣物的推荐依据变化
describe("review fixes: recommendations follow the current item's data", () => {
  it("same version but a changed effective colour (upstream recompute) reloads", async () => {
    const { w } = await mountAt("/items/1");
    mocks.similarItems.mockResolvedValue(similar([8]));
    const base = detail({ id: 1, name: "衣物 1" });
    mocks.item.mockResolvedValue({ ...base, resolved: { ...base.resolved, color: { ...base.resolved.color, family: "red", hex: "#C81E1E" } } });
    mocks.wearItem.mockRejectedValueOnce(new ApiError(409, "VERSION_CONFLICT", "冲突"));
    await w.findAll("button").find((b) => b.text().trim() === "记一次穿着")!.trigger("click"); // 冲突后重新读取详情
    await flushPromises();
    expect(mocks.similarItems).toHaveBeenCalledTimes(2);
    expect(w.find('[data-testid="similar-8"]').exists()).toBe(true);
    w.unmount();
  });

  it("an unchanged refresh of the same item does not reload recommendations", async () => {
    const { w } = await mountAt("/items/1");
    mocks.wearItem.mockRejectedValueOnce(new ApiError(409, "VERSION_CONFLICT", "冲突"));
    await w.findAll("button").find((b) => b.text().trim() === "记一次穿着")!.trigger("click");
    await flushPromises();
    expect(mocks.similarItems).toHaveBeenCalledTimes(1);
    w.unmount();
  });

  it("marks the old list as updating, then a late older response cannot replace the newest one", async () => {
    const { default: Section } = await import("../src/components/SimilarItems.vue");
    const router = createRouter({ history: createMemoryHistory(), routes });
    const w = mount(Section, { props: { itemId: 1, basis: "a" }, global: { plugins: [router] } });
    await flushPromises();
    let finishB!: (v: SimilarItems) => void;
    mocks.similarItems.mockImplementationOnce(() => new Promise((resolve) => { finishB = resolve; }));
    await w.setProps({ basis: "b" });
    expect(w.find('[data-testid="similar-updating"]').exists()).toBe(true);
    expect(w.find(".grid").classes()).toContain("stale");
    mocks.similarItems.mockResolvedValueOnce(similar([6]));
    await w.setProps({ basis: "c" });
    await flushPromises();
    finishB(similar([5]));
    await flushPromises();
    expect(w.find('[data-testid="similar-6"]').exists()).toBe(true);
    expect(w.find('[data-testid="similar-5"]').exists()).toBe(false);
    expect(w.find('[data-testid="similar-updating"]').exists()).toBe(false);
    w.unmount();
  });

  it("a failed update stops showing recommendations based on the old data", async () => {
    const { default: Section } = await import("../src/components/SimilarItems.vue");
    const router = createRouter({ history: createMemoryHistory(), routes });
    const w = mount(Section, { props: { itemId: 1, basis: "a" }, global: { plugins: [router] } });
    await flushPromises();
    mocks.similarItems.mockRejectedValueOnce(new ApiError(500, "X", "更新失败"));
    await w.setProps({ basis: "b" });
    await flushPromises();
    expect(w.find(".grid").exists()).toBe(false);
    expect(w.text()).toContain("更新失败");
    w.unmount();
  });
});

describe("similar items retry", () => {
  it("after a failure the retry button loads the recommendations again", async () => {
    mocks.similarItems.mockRejectedValueOnce(new ApiError(500, "X", "服务暂时不可用"));
    const { w } = await mountAt("/items/1");
    expect(w.find(".similar").text()).toContain("服务暂时不可用");
    mocks.similarItems.mockResolvedValueOnce(similar([4]));
    await w.find('[data-testid="similar-retry"]').trigger("click");
    await flushPromises();
    expect(mocks.similarItems).toHaveBeenCalledTimes(2);
    expect(mocks.similarItems).toHaveBeenLastCalledWith(1);
    expect(w.find('[data-testid="similar-4"]').exists()).toBe(true);
    expect(w.find('[data-testid="similar-retry"]').exists()).toBe(false);
    w.unmount();
  });

  it("a retry that is still pending when the item changes does not show stale results", async () => {
    mocks.similarItems.mockRejectedValueOnce(new ApiError(500, "X", "失败"));
    const { w, router } = await mountAt("/items/1");
    let finishRetry!: (v: SimilarItems) => void;
    mocks.similarItems.mockImplementationOnce(() => new Promise((resolve) => { finishRetry = resolve; }));
    await w.find('[data-testid="similar-retry"]').trigger("click");
    mocks.similarItems.mockResolvedValue(similar([7]));
    await router.push("/items/2");
    await flushPromises();
    finishRetry(similar([3]));
    await flushPromises();
    expect(w.find('[data-testid="similar-7"]').exists()).toBe(true);
    expect(w.find('[data-testid="similar-3"]').exists()).toBe(false);
    w.unmount();
  });
});
