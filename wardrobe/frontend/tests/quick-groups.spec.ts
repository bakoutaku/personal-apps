// 试用反馈：衣橱与新建穿搭的快捷分组按钮（T恤 / 衬衫 / 半袖 … + 更多）。API 全部为 mock，不访问网络。
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { QuickGroup } from "../src/api/types";
import { routes } from "../src/router";
import { toasts } from "../src/lib/toast";
import { CATEGORIES, FACETS, summary } from "./fixtures";

const mocks = vi.hoisted(() => {
  const names = ["meta", "brands", "categories", "flatCategories", "tags", "items", "facets"] as const;
  return Object.fromEntries(names.map((n) => [n, vi.fn()])) as Record<(typeof names)[number], ReturnType<typeof vi.fn>>;
});

vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});

import App from "../src/App.vue";

const GROUPS: QuickGroup[] = [
  { key: "tshirt", label: "T恤", more: false, count: 12 },
  { key: "shirt", label: "衬衫", more: false, count: 5 },
  { key: "short_sleeve", label: "半袖", more: false, count: 4 },
  { key: "skirt", label: "裙子", more: false, count: 0 },
  { key: "socks", label: "袜子", more: true, count: 3 },
  { key: "bag", label: "包", more: true, count: 0 },
];

async function mountAt(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(path);
  await router.isReady();
  const w = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return { w, router };
}

const group = (w: ReturnType<typeof mount>, key: string) => w.find(`[data-testid="group-${key}"]`);

beforeEach(() => {
  for (const m of Object.values(mocks)) m.mockReset();
  toasts.splice(0);
  mocks.meta.mockResolvedValue({ app_version: "0.1.0", counts: {}, enums: {} });
  mocks.brands.mockResolvedValue({ items: [] });
  mocks.categories.mockResolvedValue({ items: CATEGORIES });
  mocks.flatCategories.mockResolvedValue({ items: [] });
  mocks.tags.mockResolvedValue({ items: [] });
  mocks.items.mockResolvedValue({ items: [summary()], total: 1, limit: 48, offset: 0 });
  mocks.facets.mockResolvedValue({ ...FACETS, groups: GROUPS });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("quick groups in the wardrobe", () => {
  it("shows groups that have items, keeps the rest under 更多, and filters through the URL", async () => {
    const { w, router } = await mountAt("/");
    expect(group(w, "tshirt").text()).toContain("T恤");
    expect(group(w, "tshirt").text()).toContain("12");
    expect(group(w, "skirt").exists()).toBe(false); // 没有衣物的分组不显示
    expect(group(w, "socks").exists()).toBe(false); // 收在「更多」里
    await group(w, "more").trigger("click");
    expect(group(w, "socks").exists()).toBe(true);
    expect(group(w, "bag").exists()).toBe(false);

    await group(w, "short_sleeve").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query.group).toBe("short_sleeve");
    expect(mocks.items).toHaveBeenLastCalledWith(expect.objectContaining({ group: "short_sleeve" }));
    expect(mocks.facets).toHaveBeenLastCalledWith(expect.objectContaining({ group: "short_sleeve" }));
    expect(group(w, "short_sleeve").attributes("aria-pressed")).toBe("true");

    await group(w, "short_sleeve").trigger("click"); // 再点一次取消
    await flushPromises();
    expect(router.currentRoute.value.query.group).toBeUndefined();
    w.unmount();
  });

  it("restores a group from the URL and opens 更多 when the selected group lives there", async () => {
    const { w } = await mountAt("/?group=socks");
    expect(mocks.items).toHaveBeenCalledWith(expect.objectContaining({ group: "socks" }));
    expect(group(w, "socks").attributes("aria-pressed")).toBe("true");
    w.unmount();
  });

  it("keeps a selected group visible even when its count drops to zero", async () => {
    mocks.facets.mockResolvedValue({ ...FACETS, groups: GROUPS.map((g) => (g.key === "skirt" ? { ...g, count: 0 } : g)) });
    const { w } = await mountAt("/?group=skirt");
    expect(group(w, "skirt").exists()).toBe(true);
    w.unmount();
  });
});

describe("quick groups when picking items for an outfit", () => {
  it("filters the picker by group", async () => {
    const { w } = await mountAt("/outfits/new");
    const add = w.findAll("button").find((b) => /添加衣物|加入衣物|选择衣物/.test(b.text()));
    if (add) await add.trigger("click");
    await flushPromises();
    const picker = w.find(".picker");
    expect(picker.exists()).toBe(true);
    expect(picker.find('[data-testid="group-tshirt"]').exists()).toBe(true);
    await picker.find('[data-testid="group-shirt"]').trigger("click");
    await flushPromises();
    expect(mocks.items).toHaveBeenLastCalledWith(expect.objectContaining({ group: "shirt", status: "owned" }));
    w.unmount();
  });
});
