import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import App from "../src/App.vue";
import { ApiError } from "../src/api/client";
import { routes } from "../src/router";
import { toasts } from "../src/lib/toast";
import { CATEGORIES, FACETS, detail, summary } from "./fixtures";

const mocks = vi.hoisted(() => Object.fromEntries([
  "item", "items", "facets", "categories", "flatCategories", "brands", "tags", "meta",
  "proposals", "acceptProposal", "wearItem", "outfits", "purchases",
].map((name) => [name, vi.fn()])) as Record<string, ReturnType<typeof vi.fn>>);
vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});
function pending<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll("button").find((b) => b.text().trim() === text)!;
async function mountAt(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(path); await router.isReady();
  const w = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return { w, router };
}
beforeEach(() => {
  vi.useFakeTimers();
  Object.values(mocks).forEach((m) => m.mockReset());
  toasts.splice(0);
  mocks.item!.mockResolvedValue(detail());
  mocks.items!.mockResolvedValue({ items: [summary()], total: 1, limit: 48, offset: 0 });
  mocks.facets!.mockResolvedValue(FACETS);
  mocks.categories!.mockResolvedValue({ items: CATEGORIES });
  mocks.brands!.mockResolvedValue({ items: [] });
  mocks.flatCategories!.mockResolvedValue({ items: [] });
  mocks.tags!.mockResolvedValue({ items: [] });
  mocks.meta!.mockResolvedValue({ enums: { item_status: ["owned"] } });
  mocks.proposals!.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  mocks.outfits!.mockResolvedValue({ items: [], total: 0, limit: 48, offset: 0 });
  mocks.purchases!.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
});
afterEach(() => {
  vi.useRealTimers(); vi.restoreAllMocks(); document.body.innerHTML = "";
});

// 验证 DOM 连续性、请求时序和目标隔离；动画/滚动效果由真实浏览器验收。
describe("navigation loading continuity", () => {
  async function refreshingDetail() {
    mocks.proposals!.mockResolvedValueOnce({ items: [{ proposal_id: 41, entity: "wardrobe_item", entity_id: 1, field: "notes", current_value: null, proposed_value: "test", status: "pending", actor: "test", created_at: "2026-10-27T00:00:00Z" }], total: 1 });
    const mounted = await mountAt("/items/1");
    const refresh = pending<ReturnType<typeof detail>>();
    mocks.item!.mockReturnValueOnce(refresh.promise);
    mocks.acceptProposal!.mockResolvedValue({});
    return { ...mounted, refresh };
  }

  it("proposal refresh keeps the same content nodes, reports slow loading and blocks stale-version writes", async () => {
    const { w, refresh } = await refreshingDetail();
    const heading = w.find("h1").element;
    const facts = w.find(".key-facts").element;
    await button(w, "接受").trigger("click"); await flushPromises();
    expect(mocks.item).toHaveBeenCalledTimes(2); // 请求没有等视觉反馈计时器
    expect(w.find("h1").element).toBe(heading);
    expect(w.find(".key-facts").element).toBe(facts);
    expect(w.find(".detail").attributes("aria-busy")).toBe("true");
    expect(w.find("article").attributes("inert")).toBeDefined();
    expect(button(w, "记一次穿着").attributes("disabled")).toBeDefined();
    await button(w, "记一次穿着").trigger("click");
    expect(mocks.wearItem).not.toHaveBeenCalled();
    expect(w.find("[role=status]").text()).toBe("");
    await vi.advanceTimersByTimeAsync(160);
    expect(w.find("[role=status]").text()).toContain("正在刷新");
    expect(w.find("h1").element).toBe(heading);
    refresh.resolve(detail({ version: 2, name: "已刷新" })); await flushPromises();
    expect(w.find("h1").element).toBe(heading);
    expect(w.find("h1").text()).toBe("已刷新");
    expect(document.title).toBe("已刷新 · Wardrobe");
    expect(w.find("article").attributes("inert")).toBeUndefined();
    expect(button(w, "记一次穿着").attributes("disabled")).toBeUndefined();
    expect(w.find("[role=status]").text()).toBe("");
    w.unmount();
  });

  it("refresh failure shows an immediate error while retaining the last content", async () => {
    const { w, refresh } = await refreshingDetail();
    const facts = w.find(".key-facts").element;
    await button(w, "接受").trigger("click"); await flushPromises();
    refresh.reject(new ApiError(500, "X", "刷新读取失败")); await flushPromises();
    expect(w.find(".key-facts").element).toBe(facts);
    expect(w.find("[role=alert]").text()).toContain("刷新读取失败");
    expect(w.find("article").attributes("inert")).toBeDefined();
    expect(button(w, "记一次穿着").attributes("disabled")).toBeDefined();
    mocks.item!.mockResolvedValue(detail({ version: 2 }));
    await button(w, "重试刷新").trigger("click"); await flushPromises();
    expect(w.find(".key-facts").element).toBe(facts);
    expect(w.find("article").attributes("inert")).toBeUndefined();
    expect(w.find(".detail").attributes("aria-busy")).toBe("false");
    w.unmount();
  });

  it("fast first detail read never shows a skeleton or delayed loading message", async () => {
    const read = pending<ReturnType<typeof detail>>(); mocks.item!.mockReturnValueOnce(read.promise);
    const { w } = await mountAt("/items/1");
    expect(mocks.item).toHaveBeenCalledWith(1);
    expect(w.find(".detail").attributes("aria-busy")).toBe("true");
    expect(w.find(".skeleton").exists()).toBe(false);
    await vi.advanceTimersByTimeAsync(80);
    read.resolve(detail()); await flushPromises();
    await vi.advanceTimersByTimeAsync(200);
    expect(w.find("[role=status]").text()).toBe("");
    expect(w.find(".skeleton").exists()).toBe(false);
    expect(w.find("h1").text()).toBe(detail().name);
    w.unmount();
  });

  it("a different item hides old actions immediately and has slow feedback until its own response arrives", async () => {
    const { w, router } = await mountAt("/items/1");
    const read = pending<ReturnType<typeof detail>>(); mocks.item!.mockReturnValueOnce(read.promise);
    await router.push("/items/2"); await flushPromises();
    expect(router.currentRoute.value.path).toBe("/items/2");
    expect(mocks.item).toHaveBeenLastCalledWith(2);
    expect(w.find(".key-facts").exists()).toBe(false);
    expect(w.find('.item-actions').exists()).toBe(false);
    expect(document.title).toBe("衣物详情 · Wardrobe");
    await vi.advanceTimersByTimeAsync(160);
    expect(w.find("[role=status]").text()).toContain("正在加载");
    expect(w.find(".skeleton").exists()).toBe(true);
    read.resolve(detail({ id: 2, name: "第二件" })); await flushPromises();
    expect(w.find("h1").text()).toBe("第二件");
    w.unmount();
  });

  it("unmount cancels pending visual feedback", async () => {
    const read = pending<ReturnType<typeof detail>>(); mocks.item!.mockReturnValueOnce(read.promise);
    const { w } = await mountAt("/items/1");
    w.unmount();
    expect(vi.getTimerCount()).toBe(0);
    read.resolve(detail()); await flushPromises();
  });

  it("wardrobe return preserves cached cards and filters during refresh", async () => {
    const { w, router } = await mountAt("/?q=test&color=navy");
    const card = w.find(".card").element;
    const search = w.find('input[type=search]').element;
    await router.push("/items/1"); await flushPromises();
    const read = pending<unknown>(); mocks.items!.mockReturnValueOnce(read.promise);
    await router.back(); await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ q: "test", color: "navy" });
    expect(w.find(".card").element).toBe(card);
    expect(w.find('input[type=search]').element).toBe(search);
    expect((search as HTMLInputElement).value).toBe("test");
    expect(w.find(".title-row .count").text()).toBe("1 件");
    expect(w.find('.content').attributes('aria-busy')).toBe('true');
    await vi.advanceTimersByTimeAsync(160);
    expect(w.find(".title-row .count").text()).toContain("加载中");
    read.resolve({ items: [summary()], total: 1, limit: 48, offset: 0 }); await flushPromises();
    expect(w.find(".card").element).toBe(card);
    w.unmount();
  });

  it.each(["/outfits", "/purchases"])("%s starts immediately, reports a slow request and never reports an early empty result", async (path) => {
    const read = pending<unknown>();
    const target = path === "/outfits" ? mocks.outfits! : mocks.purchases!;
    target.mockReturnValueOnce(read.promise);
    const { w } = await mountAt("/items/1");
    await w.find(`header a[href="${path}"]`).trigger("click"); await flushPromises();
    expect(target).toHaveBeenCalledTimes(1);
    expect(w.find(".page").attributes("aria-busy")).toBe("true");
    expect(w.find(".empty-note").exists()).toBe(false);
    expect(w.find("[role=status]").text()).toBe("");
    await vi.advanceTimersByTimeAsync(160);
    expect(w.find("[role=status]").text()).toContain("正在加载");
    read.resolve({ items: [], total: 0, limit: 48, offset: 0 }); await flushPromises();
    expect(w.find("[role=status]").text()).toBe("");
    expect(w.find(".empty-note").exists()).toBe(true);
    w.unmount();
  });
});
