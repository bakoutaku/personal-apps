// 试用反馈：颜色圆点显示示意色；衣橱总览一张表列出全部衣物。API 全部为 mock，不访问网络。
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { OverviewRow } from "../src/api/types";
import ColorDot from "../src/components/ColorDot.vue";
import ItemCard from "../src/components/ItemCard.vue";
import { routes } from "../src/router";
import { toasts } from "../src/lib/toast";
import { CATEGORIES, FACETS, summary } from "./fixtures";

const mocks = vi.hoisted(() => {
  const names = ["meta", "brands", "categories", "flatCategories", "tags", "items", "facets", "overview"] as const;
  return Object.fromEntries(names.map((n) => [n, vi.fn()])) as Record<(typeof names)[number], ReturnType<typeof vi.fn>>;
});

vi.mock("../src/api/client", async (orig) => {
  const real = await orig<typeof import("../src/api/client")>();
  return { ...real, api: { ...real.api, ...mocks } };
});

import App from "../src/App.vue";

function row(overrides: Partial<OverviewRow> = {}): OverviewRow {
  return {
    id: 7,
    product_id: 3,
    name_ja: "テストダウン",
    name_zh: "测试羽绒",
    name_en: null,
    brand: "UNIQLO",
    item_no: "470001",
    category: { id: 5, slug: "outer-light-down", path: ["外套", "羽绒", "轻羽绒"], path_slugs: [] },
    color: { code: "69", name: "NAVY", hex: null, family: "navy", source: "purchase_line", swatch: "#1F2A44" },
    size: { label: "M", system: "alpha", source: "purchase_line" },
    material_text: "表地:ナイロン100%／詰め物:ダウン90%・フェザー10%",
    materials: [
      { part: "shell", fiber: "nylon", fiber_raw: "ナイロン", percent: 100 },
      { part: "fill", fiber: "down", fiber_raw: "ダウン", percent: 90 },
      { part: "fill", fiber: "feather", fiber_raw: "フェザー", percent: 10 },
    ],
    seasons: ["冬"],
    tags: ["冬"],
    status: "owned",
    ...overrides,
  };
}

const bg = (w: ReturnType<typeof mount>) => (w.find(".dot").element as HTMLElement).style.background;

describe("colour dot", () => {
  it("uses the real hex first, then the name swatch, then the family colour", () => {
    expect(bg(mount(ColorDot, { props: { hex: "#123456", swatch: "#FFFFFF", family: "black" } }))).toBe("rgb(18, 52, 86)");
    const named = mount(ColorDot, { props: { hex: null, swatch: "#4A4A4A", family: "gray" } }); // 族色是 #9a9a9a
    expect(bg(named)).toBe("rgb(74, 74, 74)");
    expect(named.find(".dot").attributes("title")).toContain("示意色");
    expect(mount(ColorDot, { props: { hex: "#123456" } }).find(".dot").attributes("title")).toBeUndefined();
    expect(mount(ColorDot, { props: { family: "white" } }).find(".dot").classes()).not.toContain("empty");
    expect(mount(ColorDot, { props: {} }).find(".dot").classes()).toContain("empty");
  });

  it("item cards show the swatch when the item has only a colour name", () => {
    const item = summary({
      resolved: {
        color: { code: "08", name: "DARK GRAY", hex: null, family: null, source: "purchase_line" },
        size: { label: "M", system: "alpha", source: "purchase_line" },
      },
      color_swatch: { hex: "#4A4A4A", source: "name" },
    });
    const router = createRouter({ history: createMemoryHistory(), routes });
    const w = mount(ItemCard, { props: { item }, global: { plugins: [router] } });
    expect(w.find(".dot").classes()).not.toContain("empty");
    expect(bg(w)).toBe("rgb(74, 74, 74)");
  });
});

describe("wardrobe overview page", () => {
  beforeEach(() => {
    for (const m of Object.values(mocks)) m.mockReset();
    toasts.splice(0);
    mocks.meta.mockResolvedValue({ app_version: "0.1.0", counts: {}, enums: {} });
    mocks.brands.mockResolvedValue({ items: [] });
    mocks.categories.mockResolvedValue({ items: CATEGORIES });
    mocks.flatCategories.mockResolvedValue({ items: [] });
    mocks.tags.mockResolvedValue({ items: [] });
    mocks.items.mockResolvedValue({ items: [summary()], total: 1, limit: 48, offset: 0 });
    mocks.facets.mockResolvedValue(FACETS);
  });
  afterEach(() => {
    document.body.innerHTML = "";
  });

  async function mountAt(path: string) {
    const router = createRouter({ history: createMemoryHistory(), routes });
    await router.push(path);
    await router.isReady();
    const w = mount(App, { global: { plugins: [router] }, attachTo: document.body });
    await flushPromises();
    return { w, router };
  }

  it("lists every row as plain text, writes 未记录 for missing facts and counts coverage", async () => {
    const bare = row({
      id: 8,
      name_ja: "無地T",
      name_zh: null,
      item_no: null,
      category: null,
      color: { code: null, name: null, hex: null, family: null, source: null, swatch: null },
      size: { label: null, system: null, source: null },
      material_text: null,
      materials: [],
      seasons: [],
    });
    const raw = row({ id: 9, materials: [], material_text: "ふわふわ素材", seasons: [] });
    const body = row({ id: 10, materials: [{ part: "body", fiber: "cotton", fiber_raw: "綿", percent: 100 }] });
    mocks.overview.mockResolvedValue({ items: [row(), bare, raw, body], total: 4 });
    const { w, router } = await mountAt("/overview");
    expect(mocks.overview).toHaveBeenCalledTimes(1);
    expect(router.currentRoute.value.meta.title).toBe("衣橱总览");
    expect(w.find("h1").text()).toContain("4 件");

    const full = w.find('[data-testid="overview-row-7"]').findAll("td").map((td) => td.text());
    expect(full).toEqual([
      "7",
      "テストダウン测试羽绒", // 中文名在下一行（div）
      "UNIQLO",
      "470001",
      "NAVY（69）",
      "M",
      "面料：锦纶 100%；填充物：羽绒 90%、羽毛 10%",
      "外套 › 羽绒 › 轻羽绒",
      "冬",
    ]);
    const empty = w.find('[data-testid="overview-row-8"]').findAll("td").map((td) => td.text());
    expect(empty).toEqual(["8", "無地T", "UNIQLO", "未记录", "未记录", "未记录", "未记录", "未记录", "未记录"]);
    expect(w.find('[data-testid="overview-row-9"]').findAll("td")[6].text()).toBe("ふわふわ素材");
    expect(w.find('[data-testid="overview-row-10"]').findAll("td")[6].text()).toBe("棉 100%");
    expect(w.find('[data-testid="overview-coverage"]').text()).toContain("材质已记录 3 / 4 件");
    expect(w.find('[data-testid="overview-coverage"]').text()).toContain("适穿季节已记录 2 / 4 件");
    expect(w.find("table caption").text()).toContain("共 4 件");
    expect(w.find('[data-testid="overview-row-7"] .dot').classes()).not.toContain("empty");
    w.unmount();
  });

  it("is reachable from the main navigation", async () => {
    mocks.overview.mockResolvedValue({ items: [], total: 0 });
    const { w, router } = await mountAt("/");
    const link = w.findAll("nav .nav-link").find((a) => a.text() === "衣橱总览");
    expect(link?.attributes("href")).toBe("/overview");
    await router.push("/overview");
    await flushPromises();
    expect(w.text()).toContain("衣橱里还没有持有中的衣物");
    w.unmount();
  });

  it("shows the error instead of an empty wardrobe when loading fails", async () => {
    mocks.overview.mockRejectedValue(new Error("网络中断"));
    const { w } = await mountAt("/overview");
    expect(w.find('[role="alert"]').text()).toContain("网络中断");
    expect(w.text()).not.toContain("衣橱里还没有持有中的衣物");
    w.unmount();
  });
});
