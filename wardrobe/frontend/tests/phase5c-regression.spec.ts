// Phase 5C 修复回归。第一部分为 GPT 独立审查复现（REVIEW_PHASE5C_GPT_INDEPENDENT_2026-10-28.md），原样加入，仅格式化。
import { mount, flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Batch from "../src/components/BatchSuggestions.vue";
import Panel from "../src/components/TagSuggestPanel.vue";
import { toasts } from "../src/lib/toast";
import { detail, summary } from "./fixtures";

const api = vi.hoisted(() => ({
  batchTagSuggestions: vi.fn(),
  createBatchTagSuggestions: vi.fn(),
  tagSuggestions: vi.fn(),
  createTagSuggestions: vi.fn(),
}));
// 唯一适配：保留模块的其他导出（ApiError），以便同一 mock 复用于错误分支的回归
vi.mock("../src/api/client", async (orig) => ({ ...(await orig<typeof import("../src/api/client")>()), api }));
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll("button").find((b) => b.text().startsWith(text))!;
const suggestion = (id = 1) => ({
  item_id: id,
  item_version: 1,
  algorithm: "wardrobe-tagcat/1",
  tags: [{ name: "冬", reasons: [], evidence: {} }],
  category: null,
  category_note: null,
});
const page = (ids: number[], total: number) => ({
  items: ids.map((id) => ({ ...suggestion(id), item: summary({ id, name: `衣物${id}` }) })),
  total,
  offset: 0,
  limit: 50,
});
const result = () => ({ results: [{ item_id: 1, ok: true, proposals: [] }], succeeded: 1, failed: 0 });
const defer = () => {
  let resolve!: (v: any) => void;
  const promise = new Promise((r) => {
    resolve = r;
  });
  return { promise, resolve };
};
beforeEach(() => Object.values(api).forEach((m) => m.mockReset()));

describe("GPT independent Phase5C reproducers", () => {
  it("loading the next page cannot be invalidated by submission", async () => {
    const pending = defer();
    api.batchTagSuggestions.mockResolvedValueOnce(page([1], 2)).mockReturnValueOnce(pending.promise);
    api.createBatchTagSuggestions.mockResolvedValue(result());
    const w = mount(Batch, { global: { stubs: { RouterLink: true } } });
    await flushPromises();
    await button(w, "加载更多").trigger("click");
    if (button(w, "为选中的").attributes("disabled") === undefined) await button(w, "为选中的").trigger("click");
    await flushPromises();
    pending.resolve(page([2], 2));
    await flushPromises();
    expect(w.text()).not.toContain("正在计算");
    expect(w.findAll(".rows > li")).toHaveLength(2);
    w.unmount();
  });
  it("submission cannot lose results or remain busy when more is clicked", async () => {
    const pending = defer();
    api.batchTagSuggestions.mockResolvedValueOnce(page([1], 2)).mockResolvedValueOnce(page([2], 2));
    api.createBatchTagSuggestions.mockReturnValue(pending.promise);
    const w = mount(Batch, { global: { stubs: { RouterLink: true } } });
    await flushPromises();
    await button(w, "为选中的").trigger("click");
    if (button(w, "加载更多").attributes("disabled") === undefined) await button(w, "加载更多").trigger("click");
    await flushPromises();
    pending.resolve(result());
    await flushPromises();
    expect(w.find('[data-testid="batch-1"]').text()).toContain("已生成");
    expect(w.text()).not.toContain("生成中");
    w.unmount();
  });
  it("a changed item reread during generation does not strand the single panel", async () => {
    const pending = defer();
    api.tagSuggestions.mockResolvedValue(suggestion());
    api.createTagSuggestions.mockReturnValue(pending.promise);
    const w = mount(Panel, { props: { item: detail() } });
    await flushPromises();
    await button(w, "生成待确认").trigger("click");
    await w.setProps({ item: detail({ version: 2 }) });
    api.tagSuggestions.mockResolvedValue({ ...suggestion(), item_version: 2 });
    if (button(w, "重新读取").attributes("disabled") === undefined) await button(w, "重新读取").trigger("click");
    await flushPromises();
    pending.resolve({ proposals: [] });
    await flushPromises();
    expect(w.text()).not.toContain("生成中");
    w.unmount();
  });
  it("does not send more than 100 selected items in one API batch", async () => {
    api.batchTagSuggestions
      .mockResolvedValueOnce(page(Array.from({ length: 50 }, (_, i) => i + 1), 101))
      .mockResolvedValueOnce(page(Array.from({ length: 50 }, (_, i) => i + 51), 101))
      .mockResolvedValueOnce(page([101], 101));
    api.createBatchTagSuggestions.mockResolvedValue({ results: [], succeeded: 0, failed: 0 });
    const w = mount(Batch, { global: { stubs: { RouterLink: true } } });
    await flushPromises();
    await button(w, "加载更多").trigger("click");
    await flushPromises();
    await button(w, "加载更多").trigger("click");
    await flushPromises();
    const submit = button(w, "为选中的");
    if (submit.attributes("disabled") === undefined) {
      await submit.trigger("click");
      await flushPromises();
      for (const [body] of api.createBatchTagSuggestions.mock.calls) expect(body.length).toBeLessThanOrEqual(100);
    } else expect(w.text()).toContain("100");
    w.unmount();
  });
});

// ───────────── 修复回归（docs/PHASE5C_FIXES_2026-10-28.md） ─────────────

const reject = () => {
  let fail!: (e: unknown) => void;
  const promise = new Promise((_, r) => {
    fail = r;
  });
  return { promise, fail };
};
const ids = (from: number, n: number) => Array.from({ length: n }, (_, i) => from + i);
const mountBatch = () => mount(Batch, { global: { stubs: { RouterLink: true } } });

describe("Phase 5C batch: load / submit isolation", () => {
  beforeEach(() => toasts.splice(0));

  it("disables generating while a page is loading and loading while generating", async () => {
    const more = defer();
    api.batchTagSuggestions.mockResolvedValueOnce(page([1], 2)).mockReturnValueOnce(more.promise);
    const w = mountBatch();
    await flushPromises();
    await button(w, "加载更多").trigger("click");
    expect(button(w, "为选中的").attributes("disabled")).toBeDefined();
    expect(api.createBatchTagSuggestions).not.toHaveBeenCalled();
    more.resolve(page([2], 2));
    await flushPromises();

    const gen = defer();
    api.createBatchTagSuggestions.mockReturnValue(gen.promise);
    await button(w, "为选中的").trigger("click");
    for (const t of ["全选", "全不选"]) expect(button(w, t).attributes("disabled")).toBeDefined();
    gen.resolve({ results: [1, 2].map((id) => ({ item_id: id, ok: true, proposals: [{}] })), succeeded: 2, failed: 0 });
    await flushPromises();
    expect(w.find('[data-testid="batch-2"]').text()).toContain("已生成 1 条提议");
    expect(w.text()).not.toContain("生成中");
    w.unmount();
  });

  it("a failed generation releases busy, keeps the rows and allows a new attempt", async () => {
    const gen = reject();
    api.batchTagSuggestions.mockResolvedValueOnce(page([1, 2], 2));
    api.createBatchTagSuggestions.mockReturnValueOnce(gen.promise).mockResolvedValueOnce(result());
    const w = mountBatch();
    await flushPromises();
    await button(w, "为选中的").trigger("click");
    gen.fail(new Error("网络中断"));
    await flushPromises();
    expect(w.find('[role="alert"]').text()).toContain("网络中断");
    expect(w.findAll(".rows > li")).toHaveLength(2);
    expect(w.text()).not.toContain("生成中");
    await button(w, "为选中的").trigger("click");
    await flushPromises();
    expect(api.createBatchTagSuggestions).toHaveBeenCalledTimes(2);
    w.unmount();
  });

  it("late results after unmount change nothing and raise no toast", async () => {
    const more = defer();
    const gen = defer();
    const failing = reject();
    api.batchTagSuggestions.mockResolvedValueOnce(page([1], 2)).mockReturnValueOnce(more.promise);
    api.createBatchTagSuggestions.mockReturnValue(gen.promise);
    const a = mountBatch();
    await flushPromises();
    await button(a, "为选中的").trigger("click");
    a.unmount();
    gen.resolve(result());
    await flushPromises();
    expect(toasts).toHaveLength(0);

    api.batchTagSuggestions.mockReset().mockResolvedValueOnce(page([1], 2)).mockReturnValueOnce(failing.promise);
    const b = mountBatch();
    await flushPromises();
    await button(b, "加载更多").trigger("click");
    b.unmount();
    failing.fail(new Error("迟到的失败"));
    more.resolve(page([2], 2));
    await flushPromises();
    expect(toasts).toHaveLength(0);
  });
});

describe("Phase 5C batch: at most 100 items per request", () => {
  async function loaded(n: number) {
    const pages = [];
    for (let from = 1; from <= n; from += 50) pages.push(page(ids(from, Math.min(50, n - from + 1)), n));
    for (const pg of pages) api.batchTagSuggestions.mockResolvedValueOnce(pg);
    api.createBatchTagSuggestions.mockResolvedValue({ results: [], succeeded: 0, failed: 0 });
    const w = mountBatch();
    await flushPromises();
    for (let i = 1; i < pages.length; i++) {
      await button(w, "加载更多").trigger("click");
      await flushPromises();
    }
    expect(w.findAll(".rows > li")).toHaveLength(n);
    return w;
  }

  it("exactly 100 selected items are sent in one request", async () => {
    const w = await loaded(100);
    expect(w.find('[data-testid="batch-limit"]').exists()).toBe(false);
    await button(w, "为选中的 100 件").trigger("click");
    await flushPromises();
    expect(api.createBatchTagSuggestions).toHaveBeenCalledTimes(1);
    expect(api.createBatchTagSuggestions.mock.calls[0]![0]).toHaveLength(100);
    w.unmount();
  });

  it.each([101, 150])("%i selected items cannot be sent; keeping the first 100 sends exactly those", async (n) => {
    const w = await loaded(n);
    expect(button(w, `为选中的 ${n} 件`).attributes("disabled")).toBeDefined();
    expect(w.find('[data-testid="batch-limit"]').text()).toContain("一次最多为 100 件");
    await button(w, "为选中的").trigger("click");
    expect(api.createBatchTagSuggestions).not.toHaveBeenCalled();
    await button(w, "只保留前 100 件").trigger("click");
    await button(w, "为选中的 100 件").trigger("click");
    await flushPromises();
    expect(api.createBatchTagSuggestions).toHaveBeenCalledTimes(1);
    expect(api.createBatchTagSuggestions.mock.calls[0]![0].map((b: { item_id: number }) => b.item_id)).toEqual(ids(1, 100));
    w.unmount();
  });
});

describe("Phase 5C single panel: load / submit isolation", () => {
  it("rereading is disabled while generating; after a failure it works again", async () => {
    const gen = reject();
    api.tagSuggestions.mockResolvedValue(suggestion());
    api.createTagSuggestions.mockReturnValue(gen.promise);
    const w = mount(Panel, { props: { item: detail() } });
    await flushPromises();
    await button(w, "生成待确认").trigger("click");
    await w.setProps({ item: detail({ version: 2 }) });
    expect(button(w, "重新读取").attributes("disabled")).toBeDefined();
    gen.fail(new Error("服务器错误"));
    await flushPromises();
    expect(w.text()).toContain("服务器错误");
    expect(w.text()).not.toContain("生成中");
    api.tagSuggestions.mockResolvedValue({ ...suggestion(), item_version: 2 });
    await button(w, "重新读取").trigger("click");
    await flushPromises();
    expect(api.tagSuggestions).toHaveBeenCalledTimes(2);
    expect(w.text()).not.toContain("已被修改");
    w.unmount();
  });

  it("a generation that finishes after the item changed still reports what was created", async () => {
    const gen = defer();
    api.tagSuggestions.mockResolvedValue(suggestion());
    api.createTagSuggestions.mockReturnValue(gen.promise);
    const w = mount(Panel, { props: { item: detail() } });
    await flushPromises();
    await button(w, "生成待确认").trigger("click");
    await w.setProps({ item: detail({ version: 2 }) });
    gen.resolve({ proposals: [{ proposal_id: 9 }] });
    await flushPromises();
    expect(w.emitted("created")).toEqual([[[{ proposal_id: 9 }]]]);
    expect(w.text()).toContain("已生成 1 条待确认提议");
    w.unmount();
  });

  it("changing the picks during generation does not label the new picks as generated", async () => {
    const gen = defer();
    api.tagSuggestions.mockResolvedValue({ ...suggestion(), tags: [{ name: "冬", reasons: [], evidence: {} }, { name: "夏", reasons: [], evidence: {} }] });
    api.createTagSuggestions.mockReturnValue(gen.promise);
    const w = mount(Panel, { props: { item: detail() } });
    await flushPromises();
    await button(w, "生成待确认").trigger("click");
    await w.find('[data-testid="tag-opt-夏"] input').setValue(false);
    gen.resolve({ proposals: [{ proposal_id: 9 }] });
    await flushPromises();
    expect(w.emitted("created")).toHaveLength(1); // 服务器上确实已建立，列表仍刷新
    expect(w.text()).not.toContain("已生成");
    expect(w.text()).not.toContain("生成中");
    w.unmount();
  });

  it("late success or failure after unmount emits nothing", async () => {
    const gen = defer();
    const failing = reject();
    api.tagSuggestions.mockResolvedValue(suggestion());
    api.createTagSuggestions.mockReturnValueOnce(gen.promise).mockReturnValueOnce(failing.promise);
    const a = mount(Panel, { props: { item: detail() } });
    await flushPromises();
    await button(a, "生成待确认").trigger("click");
    a.unmount();
    gen.resolve({ proposals: [{ proposal_id: 1 }] });
    await flushPromises();
    expect(a.emitted("created")).toBeUndefined();
    const b = mount(Panel, { props: { item: detail() } });
    await flushPromises();
    await button(b, "生成待确认").trigger("click");
    b.unmount();
    failing.fail(new Error("迟到"));
    await flushPromises();
    expect(b.emitted("created")).toBeUndefined();
  });
});
