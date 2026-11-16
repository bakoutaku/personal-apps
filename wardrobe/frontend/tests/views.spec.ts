import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { routes } from "../src/router";
import { CATEGORIES, FACETS, detail, summary } from "./fixtures";

const mocks = vi.hoisted(() => ({
  items: vi.fn(),
  facets: vi.fn(),
  categories: vi.fn(),
  brands: vi.fn(),
  item: vi.fn(),
}));

vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});

import App from "../src/App.vue";
import { ApiError } from "../src/api/client";
import { tabbable } from "../src/lib/modal";

async function mountAt(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(path);
  await router.isReady();
  const w = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return { w, router };
}

beforeEach(() => {
  vi.useRealTimers();
  for (const m of Object.values(mocks)) m.mockReset();
  mocks.items.mockResolvedValue({ items: [summary(), summary({ id: 2, name: "セーター", resolved: summary().resolved })], total: 60, limit: 48, offset: 0 });
  mocks.facets.mockResolvedValue(FACETS);
  mocks.categories.mockResolvedValue({ items: CATEGORIES });
  mocks.brands.mockResolvedValue({ items: [{ id: 1, slug: "uniqlo", name: "UNIQLO" }] });
  mocks.item.mockResolvedValue(detail());
});

describe("WardrobeView", () => {
  it("loads items and facets using filters from the URL", async () => {
    const { w } = await mountAt("/?color=navy&q=ダウン&sort=name");
    expect(mocks.items).toHaveBeenCalledWith({ status: "owned", q: "ダウン", color: "navy", sort: "name", limit: 48, offset: 0 });
    expect(mocks.facets).toHaveBeenCalledWith({ status: "owned", q: "ダウン", color: "navy" });
    expect(w.findAll(".card")).toHaveLength(2);
    expect(w.text()).toContain("60 件");
    expect(w.findAll(".chip.removable").map((c) => c.text().replace(/×.*/, "").trim())).toEqual(["“ダウン”", "藏青"]);
    w.unmount();
  });

  it("removing a chip updates the URL", async () => {
    const { w, router } = await mountAt("/?color=navy,black");
    await w.findAll(".chip.removable")[0].trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ color: "black" });
    w.unmount();
  });

  it("loads more items with the next offset", async () => {
    const { w } = await mountAt("/");
    mocks.items.mockResolvedValueOnce({ items: [summary({ id: 3 })], total: 60, limit: 48, offset: 2 });
    await w.find(".more button").trigger("click");
    await flushPromises();
    expect(mocks.items).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 2 }));
    expect(w.findAll(".card")).toHaveLength(3);
    w.unmount();
  });

  it("debounces search input into the URL", async () => {
    vi.useFakeTimers();
    const { w, router } = await mountAt("/");
    await w.find("input[type=search]").setValue("ニット");
    expect(router.currentRoute.value.query.q).toBeUndefined();
    vi.advanceTimersByTime(350);
    await flushPromises();
    expect(router.currentRoute.value.query.q).toBe("ニット");
    w.unmount();
  });

  it("shows an empty state and an error state", async () => {
    mocks.items.mockResolvedValue({ items: [], total: 0, limit: 48, offset: 0 });
    let { w } = await mountAt("/?color=red");
    expect(w.text()).toContain("没有符合条件的衣物");
    w.unmount();
    ({ w } = await mountAt("/"));
    expect(w.text()).toContain("衣橱里还没有衣物");
    expect(w.text()).not.toContain("后续版本");
    expect(w.find(".empty a[href='/imports']").exists()).toBe(true);
    w.unmount();
    mocks.items.mockRejectedValue(new ApiError(0, "NETWORK", "无法连接到本机服务"));
    ({ w } = await mountAt("/"));
    expect(w.find("[role=alert]").text()).toContain("无法连接到本机服务");
    w.unmount();
  });
});

describe("ItemDetailView", () => {
  it("renders all sections with resolved sources", async () => {
    const { w } = await mountAt("/items/1");
    expect(mocks.item).toHaveBeenCalledWith(1);
    const text = w.text();
    for (const s of ["外套", "轻羽绒", "テストダウン", "NAVY", "来源：购买记录", "衣柜", "2 次", "#通勤",
      "详情页编号", "E000000-000", "商品番号", "BLACK", "（默认）", "¥7,990", "锦纶", "100%", "手洗い30℃まで",
      "测试店", "已退 1", "秋季通勤"]) {
      expect(text, s).toContain(s);
    }
    // 衣物自己的照片在前，商品图在后
    expect(w.findAll(".thumb img").map((i) => i.attributes("src"))).toEqual(["/media/thumb/b.webp", "/media/thumb/a.webp"]);
    const link = w.find('a[target="_blank"]');
    expect(link.attributes("rel")).toBe("noopener noreferrer");
    w.unmount();
  });

  it("shows a not-found state", async () => {
    mocks.item.mockRejectedValue(new ApiError(404, "NOT_FOUND", "wardrobe_item 99 不存在"));
    const { w } = await mountAt("/items/99");
    expect(w.text()).toContain("找不到这件衣物");
    w.unmount();
  });

  it("gallery switches images", async () => {
    const { w } = await mountAt("/items/1");
    expect(w.find(".main img").attributes("src")).toBe("/media/original/b.png");
    await w.findAll(".thumb")[1].trigger("click");
    expect(w.find(".main img").attributes("src")).toBe("/media/original/a.png");
    await w.find(".nav.next").trigger("click");
    expect(w.find(".main img").attributes("src")).toBe("/media/original/b.png");
    w.unmount();
  });
});

describe("other pages", () => {
  it("renders the Phase 4 outfits page (no longer a placeholder) and 404", async () => {
    let { w } = await mountAt("/outfits");
    expect(w.find("h1").text()).toContain("穿搭组合");
    expect(w.text()).not.toContain("Phase 4");
    w.unmount();
    ({ w } = await mountAt("/nope"));
    expect(w.text()).toContain("页面不存在");
    w.unmount();
  });
});

// 延迟响应模拟真实网络乱序，而不是只验证同步的 mock。
describe("request ordering", () => {
  it("keeps the latest detail when an earlier request finishes last", async () => {
    let finish!: (value: ReturnType<typeof detail>) => void;
    mocks.item.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { w, router } = await mountAt("/items/1");
    mocks.item.mockResolvedValueOnce(detail({ id: 2, name: "当前衣物" }));
    await router.push("/items/2");
    await flushPromises();
    finish(detail({ id: 1, name: "旧衣物" }));
    await flushPromises();
    expect(w.find("h1").text()).toBe("当前衣物");
    expect(document.title).toBe("当前衣物 · Wardrobe");
    w.unmount();
  });

  it("ignores late detail errors and responses after leaving the page", async () => {
    let fail!: (reason: Error) => void;
    mocks.item.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    const { w, router } = await mountAt("/items/1");
    await router.push("/items/2");
    await flushPromises();
    fail(new ApiError(404, "NOT_FOUND", "过期错误"));
    await flushPromises();
    expect(w.find("[role=alert]").exists()).toBe(false);
    expect(w.find("h1").text()).toBe("テストダウン");
    let finish!: (value: ReturnType<typeof detail>) => void;
    mocks.item.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    await router.push("/items/3");
    await flushPromises();
    await router.push("/");
    await flushPromises();
    const titleWhenLeft = document.title; // 此测试的 memory router 不安装生产环境 afterEach
    finish(detail({ name: "已经离开的衣物" }));
    await flushPromises();
    expect(document.title).toBe(titleWhenLeft);
    w.unmount();
  });

  it("does not show an old load-more failure after changing filters", async () => {
    const { w, router } = await mountAt("/");
    let fail!: (reason: Error) => void;
    mocks.items.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    await w.find(".more button").trigger("click");
    await router.push("/?color=navy");
    await flushPromises();
    expect(w.find(".more button").attributes("disabled")).toBeUndefined();
    fail(new ApiError(0, "NETWORK", "旧分页请求失败"));
    await flushPromises();
    expect(w.find("[role=alert]").exists()).toBe(false);
    w.unmount();
  });
});

describe("filter drawer keyboard", () => {
  it("moves focus into the drawer, traps Tab, and restores focus and scrolling", async () => {
    const { w } = await mountAt("/");
    document.body.style.overflow = "auto";
    await w.find(".filter-toggle").trigger("click");
    await flushPromises();
    const done = w.find(".drawer-head button");
    expect(document.activeElement).toBe(done.element);
    expect(document.body.style.overflow).toBe("hidden");
    await done.trigger("keydown", { key: "Tab", shiftKey: true });
    expect(document.activeElement).not.toBe(done.element);
    await w.find(".sidebar").trigger("keydown", { key: "Tab" });
    expect(document.activeElement).toBe(done.element);
    await done.trigger("keydown", { key: "Escape" });
    await flushPromises();
    expect(document.activeElement).toBe(w.find(".filter-toggle").element);
    expect(document.body.style.overflow).toBe("auto");
    await w.find(".filter-toggle").trigger("click");
    await flushPromises();
    w.unmount();
    expect(document.body.style.overflow).toBe("auto");
    document.body.style.overflow = "";
  });
});

it("uses purchase currency independently of the product list-price currency", async () => {
  const d = detail();
  d.purchase!.currency = "USD";
  d.purchase!.line.unit_price = 50;
  d.purchase!.line.discount_amount = 5;
  mocks.item.mockResolvedValue(d);
  const { w } = await mountAt("/items/1");
  expect(w.text()).toContain("50 USD");
  expect(w.text()).toContain("折扣 5 USD");
  expect(w.text()).toContain("¥7,990");
  w.unmount();
});


// Independent QA: a recovered paging request must clear its previous error.
it("independent: clears load-more error after successful retry", async () => {
  const { w } = await mountAt("/");
  mocks.items.mockRejectedValueOnce(new ApiError(0, "NETWORK", "临时分页错误"));
  await w.find(".more button").trigger("click"); await flushPromises();
  expect(w.find("[role=alert]").exists()).toBe(true);
  mocks.items.mockResolvedValueOnce({items:[summary({id:3})],total:60,limit:48,offset:2});
  await w.find(".more button").trigger("click"); await flushPromises();
  expect(w.findAll(".card")).toHaveLength(3);
  expect(w.find("[role=alert]").exists()).toBe(false);
  w.unmount();
});

it("independent: old successful pagination cannot finish newer pagination", async () => {
  const { w, router } = await mountAt("/");
  let oldDone!: (page: unknown) => void;
  let newDone!: (page: unknown) => void;
  mocks.items.mockImplementationOnce(() => new Promise(resolve => { oldDone = resolve; }));
  await w.find(".more button").trigger("click");
  await router.push("/?color=navy"); await flushPromises();
  mocks.items.mockImplementationOnce(() => new Promise(resolve => { newDone = resolve; }));
  await w.find(".more button").trigger("click");
  oldDone({items:[summary({id:99})],total:60,limit:48,offset:2}); await flushPromises();
  expect(w.find(".more button").attributes("disabled")).toBeDefined();
  expect(w.find('[data-testid="item-card-99"]').exists()).toBe(false);
  newDone({items:[summary({id:3})],total:60,limit:48,offset:2}); await flushPromises();
  expect(w.findAll(".card")).toHaveLength(3);
  expect(w.find(".more button").attributes("disabled")).toBeUndefined();
  w.unmount();
});

it("independent: refund uses purchase currency and unmount invalidates detail error", async () => {
  const d = detail({status:"returned",refund_amount:45});
  d.purchase!.currency="USD";
  mocks.item.mockResolvedValueOnce(d);
  const {w,router}=await mountAt('/items/1');
  expect(w.text()).toContain('退款 45 USD');
  expect(w.text()).toContain('¥7,990');
  let fail!: (err: Error) => void;
  mocks.item.mockImplementationOnce(()=>new Promise((_resolve,reject)=>{fail=reject;}));
  await router.push('/items/2'); await flushPromises();
  await router.push('/'); await flushPromises();
  const title=document.title;
  fail(new ApiError(500,'QA','late detail error')); await flushPromises();
  expect(w.find('[role=alert]').exists()).toBe(false);
  expect(document.title).toBe(title);
  w.unmount();
});

it("retains and refreshes over 200 loaded items after a detail round trip", async () => {
  const records = Array.from({ length: 260 }, (_, n) => summary({ id: n + 1, name: `衣物 ${n + 1}` }));
  mocks.items.mockImplementation(async ({ limit, offset }) => ({ items: records.slice(offset, offset + limit), total: records.length, limit, offset }));
  const { w, router } = await mountAt("/?color=navy&sort=name");
  for (let i = 0; i < 5; i++) {
    await w.find(".more button").trigger("click");
    await flushPromises();
  }
  expect(w.findAll(".card")).toHaveLength(260);
  await router.push("/items/260");
  await flushPromises();
  records[259] = summary({ id: 260, name: "返回时刷新后的名称" });
  await router.push("/?color=navy&sort=name");
  await flushPromises();
  expect(w.findAll(".card")).toHaveLength(260);
  expect(w.find('[data-testid="item-card-260"]').text()).toContain("返回时刷新后的名称");
  expect(mocks.items).toHaveBeenCalledWith(expect.objectContaining({ color: "navy", sort: "name", limit: 200, offset: 0 }));
  expect(mocks.items).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 60, offset: 200 }));
  expect(new Set(w.findAll(".card").map(c => c.attributes("href"))).size).toBe(260);
  await router.push("/?color=black");
  await flushPromises();
  expect(w.findAll('.card')).toHaveLength(48);
  await router.push("/?color=navy&sort=name");
  await flushPromises();
  expect(w.findAll('.card')).toHaveLength(260);
  expect(mocks.items).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 200, limit: 60, color: "navy" }));
  w.unmount();
});

it("keeps cached cards on refresh failure and resets pagination for a new filter", async () => {
  const { w, router } = await mountAt("/");
  await router.push("/items/1");
  await flushPromises();
  mocks.items.mockRejectedValueOnce(new ApiError(0, "NETWORK", "刷新失败"));
  await router.push("/");
  await flushPromises();
  expect(w.findAll(".card")).toHaveLength(2);
  expect(w.find('[role=alert]').text()).toBe("刷新失败");
  await router.push("/?color=navy");
  await flushPromises();
  expect(mocks.items).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0, limit: 48, color: "navy" }));
  expect(w.find('[role=alert]').exists()).toBe(false);
  w.unmount();
});

it("pagination retry cannot clear an independent dictionary error", async () => {
  mocks.brands.mockRejectedValueOnce(new ApiError(0, "NETWORK", "品牌加载失败"));
  const { w } = await mountAt("/");
  mocks.items.mockRejectedValueOnce(new ApiError(0, "NETWORK", "分页失败"));
  await w.find(".more button").trigger("click"); await flushPromises();
  expect(w.findAll('[role=alert]')).toHaveLength(2);
  mocks.items.mockResolvedValueOnce({ items: [summary({ id: 3 })], total: 60, limit: 48, offset: 2 });
  await w.find(".more button").trigger("click"); await flushPromises();
  expect(w.findAll('[role=alert]').map(x => x.text())).toEqual(["品牌加载失败"]);
  w.unmount();
});

it.each(["owned", "returned", "all"])("drawer cycles from the selected %s radio and restores inert state", async (status) => {
  mocks.facets.mockResolvedValue({ ...FACETS, status: { owned: 2, returned: 1 } });
  const { w } = await mountAt(`/?status=${status}`);
  await w.find(".filter-toggle").trigger("click"); await flushPromises();
  const root = w.find(".sidebar").element as HTMLElement;
  const selected = root.querySelector<HTMLInputElement>('input[type=radio]:checked')!;
  expect(tabbable(root).at(-1)).toBe(selected);
  selected.focus();
  await w.find('input[type=radio]:checked').trigger('keydown', { key: 'Tab' });
  expect(document.activeElement).toBe(w.find('.drawer-head button').element);
  expect(w.find('.content').attributes('inert')).toBeDefined();
  expect(w.find('header').attributes('inert')).toBeDefined();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await flushPromises();
  expect(w.find('.content').attributes('inert')).toBeUndefined();
  expect(w.find('header').attributes('inert')).toBeUndefined();
  w.unmount();
});

it("closes the drawer and releases inert/overflow when the window widens past the drawer breakpoint", async () => {
  let onChange: ((e: { matches: boolean }) => void) | undefined;
  const mql = {
    matches: true,
    addEventListener: vi.fn((_: string, cb: (e: { matches: boolean }) => void) => { onChange = cb; }),
    removeEventListener: vi.fn(),
  };
  window.matchMedia = vi.fn(() => mql) as unknown as typeof window.matchMedia;
  document.body.style.overflow = "auto";
  const { w } = await mountAt("/");
  await w.find(".filter-toggle").trigger("click"); await flushPromises();
  expect(window.matchMedia).toHaveBeenCalledWith("(max-width: 900px)");
  expect(w.find(".content").attributes("inert")).toBeDefined();
  onChange!({ matches: false });
  await flushPromises();
  expect(w.find(".filter-toggle").attributes("aria-expanded")).toBe("false");
  expect(w.find(".content").attributes("inert")).toBeUndefined();
  expect(w.find("header").attributes("inert")).toBeUndefined();
  expect(document.body.style.overflow).toBe("auto");
  expect(mql.removeEventListener).toHaveBeenCalledWith("change", onChange);
  document.body.style.overflow = "";
  // @ts-expect-error jsdom 默认没有 matchMedia
  delete window.matchMedia;
  w.unmount();
});

it("leaving during the search debounce drops the pending text instead of showing it unapplied", async () => {
  vi.useFakeTimers();
  const { w, router } = await mountAt("/?q=ダウン");
  await w.find("input[type=search]").setValue("zzz");
  await router.push("/items/1"); await flushPromises();
  vi.advanceTimersByTime(350); await flushPromises();
  expect(router.currentRoute.value.fullPath).toBe("/items/1");
  await router.back(); await flushPromises();
  vi.advanceTimersByTime(350); await flushPromises();
  expect(router.currentRoute.value.query.q).toBe("ダウン");
  expect((w.find("input[type=search]").element as HTMLInputElement).value).toBe("ダウン");
  w.unmount();
});


it("QA independent: Back cancels pending search when q is unchanged", async () => {
  vi.useFakeTimers();
  const {w,router}=await mountAt("/");
  await router.push("/?color=navy"); await flushPromises();
  await w.find("input[type=search]").setValue("pending keyword");
  router.back(); await flushPromises();
  expect(router.currentRoute.value.fullPath).toBe("/");
  vi.advanceTimersByTime(350); await flushPromises();
  expect(router.currentRoute.value.fullPath).toBe("/");
  expect((w.find("input[type=search]").element as HTMLInputElement).value).toBe("");
  w.unmount();
});

it("QA independent: inactive drawer releases global state and reopens cleanly", async () => {
  const {w,router}=await mountAt('/');
  document.body.style.overflow='auto';
  await w.find('.filter-toggle').trigger('click'); await flushPromises();
  expect(w.find('.content').attributes('inert')).toBeDefined();
  await router.push('/outfits'); await flushPromises();
  expect(document.querySelectorAll('[inert]')).toHaveLength(0);
  expect(document.body.style.overflow).toBe('auto');
  await router.push('/'); await flushPromises();
  expect(w.find('.filter-toggle').attributes('aria-expanded')).toBe('false');
  await w.find('.filter-toggle').trigger('click'); await flushPromises();
  expect(document.activeElement).toBe(w.find('.drawer-head button').element);
  expect(w.find('.content').attributes('inert')).toBeDefined();
  w.unmount();
  expect(document.querySelectorAll('[inert]')).toHaveLength(0);
  expect(document.body.style.overflow).toBe('auto');
  document.body.style.overflow='';
});

it("QA independent: pagination finishing while inactive cannot poison the restored cache", async () => {
  const {w,router}=await mountAt('/');
  let finish!: (page:unknown)=>void;
  mocks.items.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await w.find('.more button').trigger('click');
  await router.push('/items/1'); await flushPromises();
  mocks.items.mockResolvedValueOnce({items:[summary({name:'fresh on return'})],total:1,offset:0,limit:48});
  await router.push('/'); await flushPromises();
  finish({items:[summary({id:999,name:'stale inactive page'})],total:60,offset:2,limit:48}); await flushPromises();
  expect(w.findAll('.card')).toHaveLength(1);
  expect(w.text()).toContain('fresh on return');
  expect(w.find('[data-testid="item-card-999"]').exists()).toBe(false);
  await router.push('/?color=navy'); await flushPromises();
  await router.push('/'); await flushPromises();
  expect(w.find('[data-testid="item-card-999"]').exists()).toBe(false);
  w.unmount();
});

it("changing a filter during the search debounce carries the typed text into that one navigation", async () => {
  vi.useFakeTimers();
  const { w, router } = await mountAt("/");
  await w.find("input[type=search]").setValue("ニット");
  await w.find(".sort select").setValue("name"); await flushPromises();
  expect(router.currentRoute.value.query).toEqual({ q: "ニット", sort: "name" });
  vi.advanceTimersByTime(350); await flushPromises();
  router.back(); await flushPromises();
  vi.advanceTimersByTime(350); await flushPromises();
  expect(router.currentRoute.value.fullPath).toBe("/");
  expect((w.find("input[type=search]").element as HTMLInputElement).value).toBe("");
  router.forward(); await flushPromises();
  expect(router.currentRoute.value.query).toEqual({ q: "ニット", sort: "name" });
  expect((w.find("input[type=search]").element as HTMLInputElement).value).toBe("ニット");
  w.unmount();
});
