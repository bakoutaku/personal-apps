// 试用反馈：「记一次穿着」点错后可以撤销，编辑页可以修改穿着次数与最近穿着日期。API 全部为 mock。
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { routes } from "../src/router";
import { toasts } from "../src/lib/toast";
import { CATEGORIES, FACETS, detail, summary } from "./fixtures";

const mocks = vi.hoisted(() => {
  const names = [
    "meta", "brands", "categories", "flatCategories", "tags", "items", "facets", "item", "updateItem", "setItemTags",
    "wearItem", "proposals", "similarItems", "tagSuggestions",
  ] as const;
  return Object.fromEntries(names.map((n) => [n, vi.fn()])) as Record<(typeof names)[number], ReturnType<typeof vi.fn>>;
});

vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});

import App from "../src/App.vue";
import { ApiError } from "../src/api/client";

async function mountAt(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(path);
  await router.isReady();
  const w = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return { w, router };
}

const input = (w: ReturnType<typeof mount>, labelText: string) =>
  w.findAll("label.field").find((l) => l.text().startsWith(labelText))?.find("input, select, textarea");
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll("button").find((b) => b.text().trim() === text);

beforeEach(() => {
  vi.useRealTimers();
  for (const m of Object.values(mocks)) m.mockReset();
  toasts.splice(0);
  mocks.meta.mockResolvedValue({ app_version: "0.1.0", counts: {}, enums: { item_status: ["owned", "wishlist", "returned", "disposed"] } });
  mocks.brands.mockResolvedValue({ items: [] });
  mocks.categories.mockResolvedValue({ items: CATEGORIES });
  mocks.flatCategories.mockResolvedValue({ items: [] });
  mocks.tags.mockResolvedValue({ items: [] });
  mocks.items.mockResolvedValue({ items: [summary()], total: 1, limit: 48, offset: 0 });
  mocks.facets.mockResolvedValue(FACETS);
  mocks.item.mockResolvedValue(detail());
  mocks.proposals.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  mocks.similarItems.mockResolvedValue({ items: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("undo a recorded wear", () => {
  it("restores the previous count and date using the version returned by the wear", async () => {
    // fixture：wear_count 2，last_worn_on 2025-12-01，version 1
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 3, last_worn_on: "2026-10-28" }));
    mocks.updateItem.mockResolvedValue(detail({ version: 3, wear_count: 2, last_worn_on: "2025-12-01" }));
    const { w } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("3 次");
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    expect(mocks.updateItem).toHaveBeenCalledWith(1, { version: 2, wear_count: 2, last_worn_on: "2025-12-01" });
    expect(w.text()).toContain("2 次");
    expect(w.text()).toContain("已撤销这次穿着记录");
    expect(button(w, "撤销")).toBeUndefined();
    w.unmount();
  });

  it("clears last_worn_on again when the item had never been worn", async () => {
    mocks.item.mockResolvedValue(detail({ wear_count: 0, last_worn_on: null }));
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 1, last_worn_on: "2026-10-28" }));
    mocks.updateItem.mockResolvedValue(detail({ version: 3, wear_count: 0, last_worn_on: null }));
    const { w } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    expect(mocks.updateItem).toHaveBeenCalledWith(1, { version: 2, wear_count: 0, last_worn_on: null });
    w.unmount();
  });

  it("does not overwrite a later change: a conflict is reported and the item is reloaded", async () => {
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 3 }));
    mocks.updateItem.mockRejectedValue(new ApiError(409, "VERSION_CONFLICT", "version 不一致"));
    const { w } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    mocks.item.mockResolvedValue(detail({ version: 3, wear_count: 4 }));
    const loadsBefore = mocks.item.mock.calls.length;
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("之后又被修改过，无法撤销");
    expect(mocks.item.mock.calls.length).toBe(loadsBefore + 1);
    expect(w.text()).toContain("4 次");
    w.unmount();
  });

  it("undoing after switching to another item changes only the original item and leaves the page alone", async () => {
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 3 }));
    mocks.updateItem.mockResolvedValue(detail({ version: 3, wear_count: 2 }));
    const { w, router } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    mocks.item.mockResolvedValue(detail({ id: 2, version: 5, wear_count: 7 }));
    await router.push("/items/2");
    await flushPromises();
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    expect(mocks.updateItem).toHaveBeenCalledWith(1, { version: 2, wear_count: 2, last_worn_on: "2025-12-01" });
    expect(router.currentRoute.value.fullPath).toBe("/items/2");
    expect(w.text()).toContain("7 次");
    w.unmount();
  });
});

describe("edit wear count and last worn date", () => {
  it("sends only the changed wear fields", async () => {
    mocks.updateItem.mockResolvedValue(detail({ version: 2, wear_count: 1, last_worn_on: "2026-10-01" }));
    const { w, router } = await mountAt("/items/1/edit");
    expect((input(w, "穿着次数")!.element as HTMLInputElement).value).toBe("2");
    await input(w, "穿着次数")!.setValue("1");
    await input(w, "最近穿着")!.setValue("2026-10-01");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.updateItem).toHaveBeenCalledWith(1, { version: 1, wear_count: 1, last_worn_on: "2026-10-01" });
    expect(router.currentRoute.value.fullPath).toBe("/items/1");
    w.unmount();
  });

  it.each([["", "empty"], ["1.5", "fraction"], ["-1", "negative"]])("rejects %j (%s) without sending a request", async (value) => {
    const { w, router } = await mountAt("/items/1/edit");
    await input(w, "穿着次数")!.setValue(value);
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(mocks.updateItem).not.toHaveBeenCalled();
    expect(w.text()).toContain("请填写 0 或以上的整数");
    expect(router.currentRoute.value.fullPath).toBe("/items/1/edit");
    w.unmount();
  });

  it("new items do not show the wear fields", async () => {
    const { w } = await mountAt("/items/new");
    expect(input(w, "穿着次数")).toBeUndefined();
    expect(input(w, "最近穿着")).toBeUndefined();
    w.unmount();
  });
});

// GPT 独立审查 WEAR-QA-001 的复现测试（REVIEW_REAL_TRIAL_WEAR_UNDO_2026-10-28.md），原样加入
describe("GPT independent late undo response", () => {
  it("does not replace a fresh revisit and newer wear with the old undo response", async () => {
    mocks.wearItem.mockResolvedValueOnce(detail({ version: 2, wear_count: 3 })).mockResolvedValueOnce(detail({ version: 4, wear_count: 3 }));
    let finish!: (v: unknown) => void;
    mocks.updateItem.mockImplementationOnce(() => new Promise(r => { finish = r; }));
    const { w, router } = await mountAt("/items/1");
    await button(w,"记一次穿着")!.trigger("click"); await flushPromises();
    await button(w,"撤销")!.trigger("click"); await flushPromises();
    // 服务端撤销已生效(v3,count2)，仅响应在网络中延迟；离开再回到1，GET取得v3。
    mocks.item.mockResolvedValueOnce(detail({ id: 2, version: 1, wear_count: 7 }));
    await router.push("/items/2"); await flushPromises();
    mocks.item.mockResolvedValueOnce(detail({ version: 3, wear_count: 2 }));
    await router.push("/items/1"); await flushPromises();
    await button(w,"记一次穿着")!.trigger("click"); await flushPromises();
    expect(w.text()).toContain("3 次");
    finish(detail({version:3,wear_count:2})); await flushPromises();
    expect(w.text()).toContain("3 次");
    w.unmount();
  });
});

describe("late undo responses (WEAR-QA-001 regressions)", () => {
  function deferred() {
    let resolve!: (v: unknown) => void;
    let reject!: (e: unknown) => void;
    const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
    return { promise, resolve, reject };
  }

  it("a late 409 after leaving and coming back neither reloads nor changes the revisited page", async () => {
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 3 }));
    const late = deferred();
    mocks.updateItem.mockReturnValueOnce(late.promise);
    const { w, router } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    mocks.item.mockResolvedValueOnce(detail({ id: 2, version: 1, wear_count: 7 }));
    await router.push("/items/2");
    await flushPromises();
    mocks.item.mockResolvedValueOnce(detail({ version: 6, wear_count: 5 }));
    await router.push("/items/1");
    await flushPromises();
    const loads = mocks.item.mock.calls.length;
    late.reject(new ApiError(409, "VERSION_CONFLICT", "version 不一致"));
    await flushPromises();
    expect(w.text()).toContain("之后又被修改过，无法撤销");
    expect(mocks.item.mock.calls.length).toBe(loads);
    expect(w.text()).toContain("5 次");
    w.unmount();
  });

  it("on the same page a late undo result never replaces a newer version", async () => {
    mocks.wearItem.mockResolvedValueOnce(detail({ version: 2, wear_count: 3 })).mockResolvedValueOnce(detail({ version: 4, wear_count: 4 }));
    const late = deferred();
    mocks.updateItem.mockReturnValueOnce(late.promise);
    const { w } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    late.resolve(detail({ version: 3, wear_count: 2 }));
    await flushPromises();
    expect(w.text()).toContain("4 次");
    w.unmount();
  });

  it("a late success while staying on the same page is applied", async () => {
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 3 }));
    const late = deferred();
    mocks.updateItem.mockReturnValueOnce(late.promise);
    const { w } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("3 次");
    late.resolve(detail({ version: 3, wear_count: 2 }));
    await flushPromises();
    expect(w.text()).toContain("2 次");
    w.unmount();
  });

  it("a late success after moving to another item leaves that page untouched", async () => {
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 3 }));
    const late = deferred();
    mocks.updateItem.mockReturnValueOnce(late.promise);
    const { w, router } = await mountAt("/items/1");
    await button(w, "记一次穿着")!.trigger("click");
    await flushPromises();
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    mocks.item.mockResolvedValueOnce(detail({ id: 2, version: 1, wear_count: 7 }));
    await router.push("/items/2");
    await flushPromises();
    late.resolve(detail({ version: 3, wear_count: 2 }));
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/items/2");
    expect(w.text()).toContain("7 次");
    expect(w.text()).toContain("已撤销这次穿着记录");
    w.unmount();
  });
});

// GPT 复查 WEAR-QA-002 的复现测试（REVIEW_WEAR_UNDO_REGRESSION_2026-10-28.md），原样加入
describe("GPT pending detail read during undo", () => {
 it("does not leave the revisited item stale when undo completes before its pending detail response", async () => {
  mocks.wearItem.mockResolvedValue(detail({version:2,wear_count:3}));
  mocks.updateItem.mockResolvedValue(detail({version:3,wear_count:2}));
  const {w,router}=await mountAt("/items/1");
  await button(w,"记一次穿着")!.trigger("click");await flushPromises();
  mocks.item.mockResolvedValueOnce(detail({id:2,version:1,wear_count:7}));
  await router.push("/items/2");await flushPromises();
  let finishRead!:(v:unknown)=>void;
  mocks.item.mockImplementationOnce(()=>new Promise(r=>{finishRead=r;}));
  await router.push("/items/1");await flushPromises();
  // A的详情GET已经读取v2、3次，但响应还没到。全局撤销按钮此时仍可点。
  await button(w,"撤销")!.trigger("click");await flushPromises();
  expect(mocks.updateItem).toHaveBeenCalledWith(1,{version:2,wear_count:2,last_worn_on:"2025-12-01"});
  finishRead(detail({version:2,wear_count:3}));await flushPromises();
  expect(w.text()).toContain("2 次");
  expect(w.text()).not.toContain("3 次");w.unmount();
 });
});

describe("undo while the revisited detail is still loading (WEAR-QA-002 regressions)", () => {
  async function revisitWithPendingRead() {
    mocks.wearItem.mockResolvedValue(detail({ version: 2, wear_count: 3 }));
    const ctx = await mountAt("/items/1");
    await button(ctx.w, "记一次穿着")!.trigger("click");
    await flushPromises();
    mocks.item.mockResolvedValueOnce(detail({ id: 2, version: 1, wear_count: 7 }));
    await ctx.router.push("/items/2");
    await flushPromises();
    let resolveRead!: (v: unknown) => void;
    let rejectRead!: (e: unknown) => void;
    mocks.item.mockImplementationOnce(() => new Promise((res, rej) => { resolveRead = res; rejectRead = rej; }));
    await ctx.router.push("/items/1");
    await flushPromises();
    return { ...ctx, resolveRead: (v: unknown) => resolveRead(v), rejectRead: (e: unknown) => rejectRead(e) };
  }

  it("a stale read that fails late leaves no error behind", async () => {
    mocks.updateItem.mockResolvedValue(detail({ version: 3, wear_count: 2 }));
    const { w, rejectRead } = await revisitWithPendingRead();
    mocks.item.mockResolvedValueOnce(detail({ version: 3, wear_count: 2 }));
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    rejectRead(new ApiError(0, "NETWORK", "旧读取失败"));
    await flushPromises();
    expect(w.text()).toContain("2 次");
    expect(w.text()).not.toContain("旧读取失败");
    w.unmount();
  });

  it("if the fresh read fails the error is shown, and the stale snapshot is still discarded", async () => {
    mocks.updateItem.mockResolvedValue(detail({ version: 3, wear_count: 2 }));
    const { w, resolveRead } = await revisitWithPendingRead();
    mocks.item.mockRejectedValueOnce(new ApiError(0, "NETWORK", "无法连接到本机服务"));
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    resolveRead(detail({ version: 2, wear_count: 3 }));
    await flushPromises();
    expect(w.text()).toContain("无法连接到本机服务");
    expect(w.text()).not.toContain("3 次");
    w.unmount();
  });

  it("when the stale read returns before the undo finishes, the undo result still wins", async () => {
    let finishUndo!: (v: unknown) => void;
    mocks.updateItem.mockImplementationOnce(() => new Promise((r) => { finishUndo = r; }));
    const { w, resolveRead } = await revisitWithPendingRead();
    await button(w, "撤销")!.trigger("click");
    await flushPromises();
    resolveRead(detail({ version: 2, wear_count: 3 }));
    await flushPromises();
    expect(w.text()).toContain("3 次");
    const loads = mocks.item.mock.calls.length;
    finishUndo(detail({ version: 3, wear_count: 2 }));
    await flushPromises();
    expect(w.text()).toContain("2 次");
    expect(mocks.item.mock.calls.length).toBe(loads);
    w.unmount();
  });
});
