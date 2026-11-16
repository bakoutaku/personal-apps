// Phase 5A-2：衣物详情中的照片颜色分析 → 整组预览 → 生成待确认提议。API 全部为 mock，不访问网络。
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { ColorAnalysis, Proposal } from "../src/api/types";
import { routes } from "../src/router";
import { toasts } from "../src/lib/toast";
import { detail } from "./fixtures";

const mocks = vi.hoisted(() => {
  const names = ["item", "proposals", "colorAnalysis", "colorSuggestion", "wearItem", "acceptProposal", "rejectProposal", "bulkProposals", "verifyItem", "returnItem", "deleteItem", "restoreItem"] as const;
  return Object.fromEntries(names.map((n) => [n, vi.fn()])) as Record<(typeof names)[number], ReturnType<typeof vi.fn>>;
});

vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});

import App from "../src/App.vue";
import ItemDetailView from "../src/views/ItemDetailView.vue";
import { ApiError } from "../src/api/client";

const NAVY = "#1F2A44";
const WHITE = "#FFFFFF";

function analysis(overrides: Partial<ColorAnalysis> = {}): ColorAnalysis {
  return {
    item_id: 1, item_version: 1, image_id: 8, image_sha256: "ab".repeat(32),
    current_color: { color_code: null, color_name: null, color_hex: null },
    resolved_color: { code: "69", name: "NAVY", hex: NAVY, family: "navy", source: "purchase_line" },
    status: "ok", reason: null, algorithm: "wardrobe-color/1", parameters: {}, region: null, stats: {},
    candidates: [
      { rank: 1, hex: NAVY, color_family: "navy", pixel_count: 75, pixel_share: 0.75 },
      { rank: 2, hex: WHITE, color_family: "white", pixel_count: 25, pixel_share: 0.25 },
    ],
    ...overrides,
  };
}

function proposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    proposal_id: 41, entity: "wardrobe_item", entity_id: 1, field: "color",
    current_value: { color_code: null, color_name: null, color_hex: null },
    proposed_value: { color_code: null, color_name: null, color_hex: NAVY },
    reason: "本地照片颜色分析的候选（像素统计，不是语义识别）", actor: "web-ui", import_job_id: null, status: "pending",
    created_at: "2026-10-27T00:00:00Z", decided_at: null,
    ai_context: {
      kind: "color", source: "local_image_analysis", target_version: 1, image_id: 8, image_sha256: "ab".repeat(32),
      region: null, algorithm: "wardrobe-color/1", parameters: {},
      candidate: { rank: 1, hex: NAVY, color_family: "navy", pixel_count: 75, pixel_share: 0.75 }, candidates: [],
      created_at: "2026-10-27T00:00:00Z",
    },
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
  await button(w, "分析照片颜色")!.trigger("click");
  await flushPromises();
}

beforeEach(() => {
  for (const m of Object.values(mocks)) m.mockReset();
  toasts.splice(0);
  mocks.item.mockResolvedValue(detail());
  mocks.proposals.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  mocks.colorAnalysis.mockResolvedValue(analysis());
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("photo colour suggestions", () => {
  it("without the item's own photos explains that one must be uploaded and never analyses product images", async () => {
    mocks.item.mockResolvedValue(detail({ images: [] }));
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    expect(w.find(".color-panel").text()).toContain("还没有自己的照片");
    expect(w.find('.color-panel a[href="/items/1/edit"]').exists()).toBe(true);
    expect(w.find(".color-panel .btn").exists()).toBe(false);
    expect(mocks.colorAnalysis).not.toHaveBeenCalled();
    w.unmount();
  });

  it("analyses the whole photo, previews the whole colour group and creates only a pending proposal", async () => {
    mocks.colorSuggestion.mockResolvedValue({ proposal: proposal(), analysis: analysis() });
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    expect(w.find(".color-panel").text()).toContain("可能受背景和光线影响");
    await button(w, "分析颜色")!.trigger("click");
    await flushPromises();
    expect(mocks.colorAnalysis).toHaveBeenCalledWith(1, 8, null);
    expect(w.findAll(".cand").map((c) => c.text())).toEqual([expect.stringContaining("像素占比 75%"), expect.stringContaining("像素占比 25%")]);
    expect((w.find(`[data-testid="cand-${NAVY}"] input`).element as HTMLInputElement).checked).toBe(true);
    const preview = w.find(".preview").text();
    expect(preview).toContain(NAVY);
    expect(w.find(".color-panel").text()).toContain("来源：购买记录");
    const before = mocks.proposals.mock.calls.length;
    await button(w, "生成待确认提议")!.trigger("click");
    await flushPromises();
    expect(mocks.colorSuggestion).toHaveBeenCalledWith(1, {
      version: 1, image_id: 8, region: null, candidate_hex: NAVY, color_code: null, color_name: null,
    });
    expect(w.find(".done").text()).toContain("已生成待确认提议 #41（尚未应用）");
    expect(mocks.proposals.mock.calls.length).toBe(before + 1); // 刷新提议列表
    expect(mocks.wearItem).not.toHaveBeenCalled();
    w.unmount();
  });

  it("sends the chosen candidate with optional name and code, and shows when existing values will be cleared", async () => {
    mocks.colorAnalysis.mockResolvedValue(analysis({ current_color: { color_code: "69", color_name: "NAVY", color_hex: "#202A40" } }));
    mocks.colorSuggestion.mockResolvedValue({ proposal: proposal(), analysis: analysis() });
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click");
    await flushPromises();
    await w.find(`[data-testid="cand-${WHITE}"] input`).setValue(true);
    await w.find('input[placeholder="例如 NAVY"]').setValue("OFF WHITE");
    // 编号留空：前后对比中标出将被清空
    expect(w.findAll(".preview td.clears").map((td) => td.text())).toEqual(["（空）"]);
    await button(w, "生成待确认提议")!.trigger("click");
    await flushPromises();
    expect(mocks.colorSuggestion).toHaveBeenCalledWith(1, expect.objectContaining({ candidate_hex: WHITE, color_name: "OFF WHITE", color_code: null }));
    w.unmount();
  });

  it("uses an exact region and changing the region discards the previous analysis", async () => {
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click");
    await flushPromises();
    expect(w.findAll(".cand")).toHaveLength(2);
    const inputs = w.findAll(".exact input");
    await inputs[0]!.setValue("20");
    await inputs[0]!.trigger("change");
    expect(w.findAll(".cand")).toHaveLength(0); // 旧结果作废
    await inputs[2]!.setValue("50");
    await inputs[2]!.trigger("change");
    await button(w, "分析颜色")!.trigger("click");
    await flushPromises();
    expect(mocks.colorAnalysis).toHaveBeenLastCalledWith(1, 8, { x: 0.2, y: 0, w: 0.5, h: 1 });
    await button(w, "使用整张图片")!.trigger("click");
    expect(w.text()).toContain("整张图片");
    w.unmount();
  });

  it("dragging on the photo selects a normalised region", async () => {
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    const frame = w.find('[data-testid="region-frame"]');
    (frame.element as HTMLElement).getBoundingClientRect = () => ({ left: 100, top: 50, width: 200, height: 400, right: 300, bottom: 450, x: 100, y: 50, toJSON: () => ({}) });
    // jsdom 没有 PointerEvent；用同名的 MouseEvent 携带坐标
    const fire = (type: string, x = 0, y = 0) => frame.element.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y, bubbles: true, cancelable: true }));
    fire("pointerdown", 150, 150);
    fire("pointermove", 250, 350);
    fire("pointerup");
    await flushPromises();
    await button(w, "分析颜色")!.trigger("click");
    await flushPromises();
    expect(mocks.colorAnalysis).toHaveBeenLastCalledWith(1, 8, { x: 0.25, y: 0.25, w: 0.5, h: 0.5 });
    w.unmount();
  });

  it("shows the reason when there is no suggestion and offers no generate button", async () => {
    mocks.colorAnalysis.mockResolvedValue(analysis({ status: "no_suggestion", reason: "no_opaque_pixels", candidates: [] }));
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click");
    await flushPromises();
    expect(w.find('[data-testid="no-suggestion"]').text()).toContain("全部是透明像素");
    expect(button(w, "生成待确认提议")).toBeUndefined();
    w.unmount();
  });

  it("ignores a late analysis result after switching to another photo", async () => {
    const two = detail({ images: [{ ...detail().images[0]!, id: 8 }, { ...detail().images[0]!, id: 9, thumb_url: "/t/9.webp" }] });
    mocks.item.mockResolvedValue(two);
    let finish!: (a: ColorAnalysis) => void;
    mocks.colorAnalysis.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click");
    await w.findAll(".pick-image input")[1]!.setValue(true);
    finish(analysis());
    await flushPromises();
    expect(w.findAll(".cand")).toHaveLength(0);
    expect(button(w, "分析颜色")!.attributes("disabled")).toBeUndefined();
    w.unmount();
  });

  it("warns and blocks generation when the item changed after the analysis", async () => {
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 3 }));
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click");
    await flushPromises();
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    expect(w.find(".color-panel [role=alert]").text()).toContain("请重新分析");
    expect(button(w, "生成待确认提议")!.attributes("disabled")).toBeDefined();
    w.unmount();
  });

  it("shows server errors from generation without claiming success", async () => {
    mocks.colorSuggestion.mockRejectedValue(new ApiError(422, "VALIDATION_ERROR", "1 个字段校验失败", [{ loc: ["candidate_hex"], message: "#1F2A44 不在本次分析的候选中" }]));
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click");
    await flushPromises();
    await button(w, "生成待确认提议")!.trigger("click");
    await flushPromises();
    expect(w.find(".color-panel [role=alert]").text()).toContain("不在本次分析的候选中");
    expect(w.find(".done").exists()).toBe(false);
    w.unmount();
  });

  it("disables generation when the proposal would not change anything", async () => {
    mocks.colorAnalysis.mockResolvedValue(analysis({ current_color: { color_code: null, color_name: null, color_hex: NAVY } }));
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click");
    await flushPromises();
    expect(button(w, "与当前颜色相同")!.attributes("disabled")).toBeDefined();
    w.unmount();
  });

  it("closes the panel when navigating to another item", async () => {
    const { w, router } = await mountAt("/items/1");
    await openPanel(w);
    expect(w.find(".color-panel").exists()).toBe(true);
    mocks.item.mockResolvedValue(detail({ id: 2 }));
    await router.push("/items/2");
    await flushPromises();
    expect(w.find(".color-panel").exists()).toBe(false);
    w.unmount();
  });
});

describe("AI source in the proposal list", () => {
  it("describes the local analysis source and a deleted source photo", async () => {
    mocks.proposals.mockResolvedValue({
      items: [proposal(), proposal({ proposal_id: 42, ai_context: { ...proposal().ai_context!, image_id: null, region: { x: 0, y: 0, w: 0.5, h: 0.5 } } })],
      total: 2, limit: 50, offset: 0,
    });
    const { w } = await mountAt("/items/1");
    const sources = w.findAll('[data-testid="ai-source"]').map((s) => s.text());
    expect(sources[0]).toContain("本地照片颜色分析（wardrobe-color/1，像素统计，不是语义识别）");
    expect(sources[0]).toContain("照片 #8 整图");
    expect(sources[0]).toContain("像素占比 75%");
    expect(sources[1]).toContain("（已删除） 的选定区域");
    w.unmount();
  });

  it("ordinary proposals without ai_context show no AI source", async () => {
    mocks.proposals.mockResolvedValue({ items: [proposal({ ai_context: null, field: "size" })], total: 1, limit: 50, offset: 0 });
    const { w } = await mountAt("/items/1");
    expect(w.find('[data-testid="ai-source"]').exists()).toBe(false);
    w.unmount();
  });
});

// Claude 独立审查（docs/REVIEW_PHASE5A_CLAUDE_2026-10-27.md）P2-1 / P2-2 的复现，原样加入
describe("independent review repros", () => {
  it("proposal list shows that code and name will be cleared", async () => {
    mocks.proposals.mockResolvedValue({ items: [proposal({
      current_value: { color_code: "69", color_name: "NAVY", color_hex: "#202A40" },
      proposed_value: { color_code: null, color_name: null, color_hex: NAVY },
    })], total: 1, limit: 50, offset: 0 });
    const { w } = await mountAt("/items/1");
    const text = w.find('[data-testid="proposal-41"]').text();
    expect(text).toMatch(/颜色编号[^，]*（空）|将清空/);
    expect(text).toMatch(/颜色名称[^，]*（空）|将清空/);
    w.unmount();
  });

  it("editing inputs after creating a proposal does not keep claiming it was created", async () => {
    mocks.colorSuggestion.mockResolvedValue({ proposal: proposal(), analysis: analysis() });
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click"); await flushPromises();
    await button(w, "生成待确认提议")!.trigger("click"); await flushPromises();
    await w.find('input[placeholder="例如 NAVY"]').setValue("DARK NAVY");
    expect(w.find(".done").exists()).toBe(false);
    expect(button(w, "生成待确认提议")).toBeDefined();
    w.unmount();
  });
});

// P2-3（前端部分）：生成请求进行中改变上下文时，迟到的结果不能显示为当前预览已生成
describe("review fixes: generation result lifecycle", () => {
  function pendingSuggestion() {
    let finish!: (v: unknown) => void;
    mocks.colorSuggestion.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    return (p = proposal()) => finish({ proposal: p, analysis: analysis() });
  }

  it("a generation that finishes after switching photos is not shown as done, but the list is refreshed", async () => {
    const two = detail({ images: [{ ...detail().images[0]!, id: 8 }, { ...detail().images[0]!, id: 9, thumb_url: "/t/9.webp" }] });
    mocks.item.mockResolvedValue(two);
    const finish = pendingSuggestion();
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click"); await flushPromises();
    await button(w, "生成待确认提议")!.trigger("click");
    await w.findAll(".pick-image input")[1]!.setValue(true);
    const before = mocks.proposals.mock.calls.length;
    finish();
    await flushPromises();
    expect(w.find(".done").exists()).toBe(false);
    expect(mocks.proposals.mock.calls.length).toBe(before + 1);
    w.unmount();
  });

  it("a generation that finishes after editing the name is not shown as done", async () => {
    const finish = pendingSuggestion();
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click"); await flushPromises();
    await button(w, "生成待确认提议")!.trigger("click");
    await w.find('input[placeholder="例如 NAVY"]').setValue("DARK NAVY");
    finish();
    await flushPromises();
    expect(w.find(".done").exists()).toBe(false);
    expect(button(w, "生成待确认提议")!.attributes("disabled")).toBeUndefined();
    w.unmount();
  });

  it("a generation that finishes after the panel was closed does nothing", async () => {
    const finish = pendingSuggestion();
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click"); await flushPromises();
    await button(w, "生成待确认提议")!.trigger("click");
    await button(w, "收起")!.trigger("click");
    const before = mocks.proposals.mock.calls.length;
    finish();
    await flushPromises();
    expect(w.find(".color-panel").exists()).toBe(false);
    expect(mocks.proposals.mock.calls.length).toBe(before);
    w.unmount();
  });

  it("switching photos clears the colour name and code typed for the previous photo", async () => {
    const two = detail({ images: [{ ...detail().images[0]!, id: 8 }, { ...detail().images[0]!, id: 9, thumb_url: "/t/9.webp" }] });
    mocks.item.mockResolvedValue(two);
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click"); await flushPromises();
    await w.find('input[placeholder="例如 NAVY"]').setValue("DARK NAVY");
    await w.findAll(".pick-image input")[1]!.setValue(true);
    await button(w, "分析颜色")!.trigger("click"); await flushPromises();
    expect((w.find('input[placeholder="例如 NAVY"]').element as HTMLInputElement).value).toBe("");
    w.unmount();
  });
});

// GPT 独立审查（REVIEW_PHASE5A_GPT_INDEPENDENT_2026-10-27.md）QA-001 / QA-002 的复现，原样加入
describe("GPT independent race probes", () => {
  it("late wear result must not replace another item after route navigation", async () => {
    let finish!: (a: ReturnType<typeof detail>) => void;
    mocks.wearItem.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const { w, router } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    mocks.item.mockResolvedValue(detail({ id: 2, name: "GPT SECOND ITEM" }));
    await router.push("/items/2"); await flushPromises();
    expect(w.text()).toContain("GPT SECOND ITEM");
    finish(detail({ id: 1, name: "GPT FIRST ITEM", version: 2 })); await flushPromises();
    expect(router.currentRoute.value.path).toBe("/items/2");
    expect(w.text()).toContain("GPT SECOND ITEM");
    expect(w.find('a[href="/items/1/edit"]').exists()).toBe(false);
    w.unmount();
  });
  it("a later wear click must target the item in the current route", async () => {
    let finish!: (a: ReturnType<typeof detail>) => void;
    mocks.wearItem.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const { w, router } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    mocks.item.mockResolvedValue(detail({ id: 2, name: "GPT SECOND ITEM" }));
    await router.push("/items/2"); await flushPromises();
    finish(detail({ id: 1, name: "GPT FIRST ITEM", version: 2 })); await flushPromises();
    mocks.wearItem.mockResolvedValue(detail({ id: 2, version: 2 }));
    await button(w, "记一次穿着")!.trigger("click"); await flushPromises();
    expect(mocks.wearItem.mock.calls[1]![0]).toBe(2);
    w.unmount();
  });
  it("late failed proposals read must not erase current item proposals", async () => {
    let rejectOld!: (e: unknown) => void;
    mocks.proposals.mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }));
    const { w, router } = await mountAt("/items/1");
    mocks.item.mockResolvedValue(detail({ id: 2, name: "GPT SECOND ITEM" }));
    mocks.proposals.mockResolvedValue({ items: [proposal({ entity_id: 2 })], total: 1, limit: 50, offset: 0 });
    await router.push("/items/2"); await flushPromises();
    expect(w.find('[data-testid="proposal-41"]').exists()).toBe(true);
    rejectOld(new Error("late old failure")); await flushPromises();
    expect(w.find('[data-testid="proposal-41"]').exists()).toBe(true);
    w.unmount();
  });
});

// 修复计划 §3 第 2 项的补充：迟到的失败与卸载后完成
describe("review fixes: item detail request lifecycle", () => {
  it("a late wear failure from the previous item shows no error and leaves busy alone", async () => {
    let fail!: (e: unknown) => void;
    mocks.wearItem.mockImplementationOnce(() => new Promise((_r, reject) => { fail = reject; }));
    const { w, router } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    mocks.item.mockResolvedValue(detail({ id: 2, name: "第二件" }));
    await router.push("/items/2"); await flushPromises();
    expect(button(w, "记一次穿着")!.attributes("disabled")).toBeUndefined();
    fail(new ApiError(500, "X", "旧衣物的失败")); await flushPromises();
    expect(w.text()).not.toContain("旧衣物的失败");
    expect(w.text()).toContain("第二件");
    w.unmount();
  });

  it("a wear that completes after leaving the page does nothing", async () => {
    let finish!: (a: ReturnType<typeof detail>) => void;
    mocks.wearItem.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { w } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    const calls = mocks.proposals.mock.calls.length;
    w.unmount();
    finish(detail({ version: 2 })); await flushPromises();
    expect(mocks.proposals.mock.calls.length).toBe(calls);
    expect(toasts.length).toBe(0);
  });
});

describe("review fixes: proposal refresh ordering", () => {
  it("an older proposal response arriving after a newer one for the same item is ignored", async () => {
    let finishOld!: (v: unknown) => void;
    mocks.proposals.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve; }));
    mocks.proposals.mockResolvedValueOnce({ items: [proposal()], total: 1, limit: 50, offset: 0 });
    const { w } = await mountAt("/items/1");
    mocks.wearItem.mockResolvedValue(detail({ version: 2 }));
    await button(w, "记一次穿着")!.trigger("click"); // 再次读取提议（新请求）
    await flushPromises();
    finishOld({ items: [], total: 0, limit: 50, offset: 0 }); await flushPromises();
    expect(w.find('[data-testid="proposal-41"]').exists()).toBe(true);
    w.unmount();
  });
});


// GPT 收尾：通过真实路由和可控挂起请求检查边界，不靠测试计数替代行为断言。
function pending<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const proposalPage = (items: Proposal[]) => ({ items, total: items.length, limit: 50, offset: 0 });

describe("finish fixes: detail lifecycle and normal operations", () => {
  it.each(["success", "failure"] as const)("old wear %s cannot clear busy while the new item operation is pending", async (outcome) => {
    const old = pending<ReturnType<typeof detail>>();
    const current = pending<ReturnType<typeof detail>>();
    mocks.wearItem.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const { w, router } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    mocks.item.mockResolvedValue(detail({ id: 2, name: "第二件" }));
    await router.push("/items/2"); await flushPromises();
    await button(w, "记一次穿着")!.trigger("click");
    const reads = mocks.proposals.mock.calls.length;
    if (outcome === "success") old.resolve(detail({ version: 2 }));
    else old.reject(new ApiError(409, "CONFLICT", "旧操作冲突"));
    await flushPromises();
    expect(button(w, "记一次穿着")!.attributes("disabled")).toBeDefined();
    expect(button(w, "删除")!.attributes("disabled")).toBeDefined();
    expect(w.find("h1").text()).toBe("第二件");
    expect(w.text()).not.toContain("旧操作冲突");
    expect(mocks.item).toHaveBeenCalledTimes(2); // 旧冲突不能重新读取新页
    expect(mocks.proposals).toHaveBeenCalledTimes(reads);
    expect(toasts).toHaveLength(0);
    current.resolve(detail({ id: 2, name: "第二件", version: 2, wear_count: 9 }));
    await flushPromises();
    expect(button(w, "记一次穿着")!.attributes("disabled")).toBeUndefined();
    expect(w.text()).toContain("9 次");
    expect(mocks.wearItem.mock.calls.map((args) => args[0])).toEqual([1, 2]);
    w.unmount();
  });

  it("late delete keeps the new item route and busy, with undo bound to the deleted item", async () => {
    const deletion = pending<void>();
    const wear = pending<ReturnType<typeof detail>>();
    mocks.deleteItem.mockReturnValueOnce(deletion.promise);
    mocks.wearItem.mockReturnValueOnce(wear.promise);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { w, router } = await mountAt("/items/1");
    await button(w, "删除")!.trigger("click");
    mocks.item.mockResolvedValue(detail({ id: 2, name: "第二件" }));
    await router.push("/items/2"); await flushPromises();
    await button(w, "记一次穿着")!.trigger("click");
    const push = vi.spyOn(router, "push");
    deletion.resolve(); await flushPromises();
    expect(push).not.toHaveBeenCalled();
    expect(router.currentRoute.value.path).toBe("/items/2");
    expect(w.find("h1").text()).toBe("第二件");
    expect(button(w, "记一次穿着")!.attributes("disabled")).toBeDefined();
    expect(mocks.deleteItem).toHaveBeenCalledWith(1, 1);
    expect(toasts[0]?.action?.label).toBe("撤销");
    wear.resolve(detail({ id: 2, name: "第二件", version: 2 })); await flushPromises();
    push.mockResolvedValue(undefined);
    mocks.restoreItem.mockResolvedValue(detail());
    await toasts[0]!.action!.run();
    expect(mocks.restoreItem).toHaveBeenCalledWith(1, 2);
    expect(push).toHaveBeenLastCalledWith({ name: "item", params: { id: 1 } });
    push.mockRestore(); confirm.mockRestore(); w.unmount();
  });

  it("late return cannot close or change the new item's return form", async () => {
    const old = pending<ReturnType<typeof detail>>();
    mocks.returnItem.mockReturnValueOnce(old.promise);
    const { w, router } = await mountAt("/items/1");
    await button(w, "退货…")!.trigger("click");
    await w.find('.return-form input[type="number"]').setValue("7990");
    await w.find(".return-form").trigger("submit");
    mocks.item.mockResolvedValue(detail({ id: 2, name: "第二件" }));
    await router.push("/items/2"); await flushPromises();
    await button(w, "退货…")!.trigger("click");
    await w.find('.return-form input[type="number"]').setValue("500");
    const reads = mocks.proposals.mock.calls.length;
    old.resolve(detail({ status: "returned", version: 2, refund_amount: 7990 }));
    await flushPromises();
    expect(w.find("h1").text()).toBe("第二件");
    expect(w.find(".return-form").exists()).toBe(true);
    expect((w.find('.return-form input[type="number"]').element as HTMLInputElement).value).toBe("500");
    expect(mocks.proposals).toHaveBeenCalledTimes(reads);
    expect(toasts).toHaveLength(0);
    w.unmount();
  });

  it("normal wear, verify and return use the latest version and refresh proposals", async () => {
    const { w } = await mountAt("/items/1");
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 4 }));
    await button(w, "记一次穿着")!.trigger("click"); await flushPromises();
    expect(mocks.wearItem).toHaveBeenCalledWith(1, expect.objectContaining({ version: 1 }));
    expect(w.text()).toContain("4 次");
    mocks.verifyItem.mockResolvedValue(detail({ version: 3, verification: "verified" }));
    await button(w, "标记为已核实")!.trigger("click"); await flushPromises();
    expect(mocks.verifyItem).toHaveBeenCalledWith(1, 2, true);
    expect(button(w, "取消核实")).toBeDefined();
    await button(w, "退货…")!.trigger("click");
    await w.find('.return-form input[type="date"]').setValue("2026-10-27");
    await w.find('.return-form input[type="number"]').setValue("1200");
    mocks.returnItem.mockResolvedValue(detail({ version: 4, status: "returned", refund_amount: 1200 }));
    await w.find(".return-form").trigger("submit"); await flushPromises();
    expect(mocks.returnItem).toHaveBeenCalledWith(1, { version: 3, returned_on: "2026-10-27", refund_amount: 1200 });
    expect(w.find(".return-form").exists()).toBe(false);
    expect(w.text()).toContain("已退货");
    expect(mocks.proposals).toHaveBeenCalledTimes(4);
    expect(button(w, "删除")!.attributes("disabled")).toBeUndefined();
    w.unmount();
  });

  it("normal delete navigates home and undo restores the captured version", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.deleteItem.mockResolvedValue(undefined);
    mocks.restoreItem.mockResolvedValue(detail({ version: 3 }));
    const { w, router } = await mountAt("/items/1");
    const push = vi.spyOn(router, "push").mockResolvedValue(undefined);
    await button(w, "删除")!.trigger("click"); await flushPromises();
    expect(mocks.deleteItem).toHaveBeenCalledWith(1, 1);
    expect(push).toHaveBeenCalledWith("/");
    await toasts[0]!.action!.run();
    expect(mocks.restoreItem).toHaveBeenCalledWith(1, 2);
    expect(push).toHaveBeenLastCalledWith({ name: "item", params: { id: 1 } });
    expect(toasts.map((t) => t.text)).toContain("已恢复");
    push.mockRestore(); confirm.mockRestore(); w.unmount();
  });

  it("switching item resets the previous return form values", async () => {
    const { w, router } = await mountAt("/items/1");
    await button(w, "退货…")!.trigger("click");
    await w.find('.return-form input[type="date"]').setValue("2020-01-01");
    await w.find('.return-form input[type="number"]').setValue("1200");
    mocks.item.mockResolvedValue(detail({ id: 2 }));
    await router.push("/items/2"); await flushPromises();
    expect(w.find(".return-form").exists()).toBe(false);
    await button(w, "退货…")!.trigger("click");
    expect((w.find('.return-form input[type="number"]').element as HTMLInputElement).value).toBe("");
    expect((w.find('.return-form input[type="date"]').element as HTMLInputElement).value).not.toBe("2020-01-01");
    w.unmount();
  });
});

describe("finish fixes: proposal lifecycle", () => {
  it("old failed read cannot erase the list refreshed by generating a proposal", async () => {
    const old = pending<ReturnType<typeof proposalPage>>();
    mocks.proposals.mockReturnValueOnce(old.promise).mockResolvedValue(proposalPage([proposal()]));
    mocks.colorSuggestion.mockResolvedValue({ proposal: proposal(), analysis: analysis() });
    const { w } = await mountAt("/items/1");
    await openPanel(w);
    await button(w, "分析颜色")!.trigger("click"); await flushPromises();
    await button(w, "生成待确认提议")!.trigger("click"); await flushPromises();
    expect(w.find('[data-testid="proposal-41"]').exists()).toBe(true);
    old.reject(new Error("old read failed")); await flushPromises();
    expect(w.find('[data-testid="proposal-41"]').exists()).toBe(true);
    expect(w.find(".done").text()).toContain("#41");
    expect(mocks.proposals).toHaveBeenCalledTimes(2);
    w.unmount();
  });

  it.each(["success", "failure"] as const)("proposal %s after unmount does not mutate retained state or cause effects", async (outcome) => {
    const late = pending<ReturnType<typeof proposalPage>>();
    mocks.proposals.mockResolvedValueOnce(proposalPage([proposal()])).mockReturnValueOnce(late.promise);
    mocks.wearItem.mockResolvedValue(detail({ version: 2 }));
    const { w, router } = await mountAt("/items/1");
    // 卸载后 DOM 不存在，保留组件状态才能检查成功赋值 / catch 清空是否真的被阻止。
    const state = (w.findComponent(ItemDetailView).vm.$ as unknown as { setupState: Record<string, unknown> }).setupState;
    await button(w, "记一次穿着")!.trigger("click"); await flushPromises();
    const before = state.proposals;
    expect(before).toHaveLength(1);
    const title = document.title;
    const reads = mocks.item.mock.calls.length;
    const notifications = toasts.length;
    const push = vi.spyOn(router, "push");
    w.unmount();
    if (outcome === "success") late.resolve(proposalPage([proposal({ proposal_id: 99 })]));
    else late.reject(new Error("late unmounted read"));
    await flushPromises();
    expect(state.proposals).toBe(before);
    expect(document.title).toBe(title);
    expect(mocks.item).toHaveBeenCalledTimes(reads);
    expect(mocks.proposals).toHaveBeenCalledTimes(2);
    expect(toasts).toHaveLength(notifications);
    expect(push).not.toHaveBeenCalled();
    push.mockRestore();
  });

  it.each(["accept", "reject"] as const)("normal proposal %s refreshes both detail and proposal status", async (decision) => {
    mocks.proposals.mockResolvedValueOnce(proposalPage([proposal()]));
    const { w } = await mountAt("/items/1");
    mocks.item.mockResolvedValue(detail({ version: 2, name: "刷新后的衣物" }));
    mocks.proposals.mockResolvedValue(proposalPage([proposal({ status: decision === "accept" ? "accepted" : "rejected" })]));
    const apiMock = decision === "accept" ? mocks.acceptProposal : mocks.rejectProposal;
    apiMock.mockResolvedValue({});
    await button(w, decision === "accept" ? "接受" : "拒绝")!.trigger("click"); await flushPromises();
    expect(apiMock).toHaveBeenCalledWith(41);
    expect(mocks.item).toHaveBeenCalledTimes(2);
    expect(mocks.proposals).toHaveBeenCalledTimes(2);
    expect(w.find("h1").text()).toBe("刷新后的衣物");
    expect(w.find('[data-testid="proposal-41"]').text()).toContain(decision === "accept" ? "已接受" : "已拒绝");
    expect(button(w, "接受")).toBeUndefined();
    w.unmount();
  });
});


describe("finish fixes: readable resolved colour", () => {
  it.each([
    { case: "HEX-only accepted suggestion", name: null, code: null, hex: NAVY, family: "navy", text: NAVY },
    { case: "name takes priority and code stays visible", name: "深藏青", code: "69", hex: NAVY, family: "navy", text: "深藏青（69）" },
    { case: "only code is recorded", name: null, code: "69", hex: null, family: null, text: "69" },
    { case: "only family is recorded", name: null, code: null, hex: null, family: "navy", text: "藏青" },
    { case: "no colour fact is recorded", name: null, code: null, hex: null, family: null, text: "未记录" },
  ])("$case", async ({ name, code, hex, family, text }) => {
    const original = detail();
    mocks.item.mockResolvedValue(detail({
      color_name: name, color_code: code, color_hex: hex,
      resolved: { ...original.resolved, color: { name, code, hex, family, source: hex || name || code || family ? "item" : null } },
    }));
    const { w } = await mountAt("/items/1");
    const value = w.find(".key-facts dd .inline").text();
    expect(value).toBe(text);
    if (hex || name || code || family) expect(w.find(".key-facts dd").text()).not.toContain("未记录");
    w.unmount();
  });
});
