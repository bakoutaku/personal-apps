import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import FilterPanel from "../src/components/FilterPanel.vue";
import ImageGallery from "../src/components/ImageGallery.vue";
import ItemCard from "../src/components/ItemCard.vue";
import { DEFAULT_FILTERS } from "../src/lib/filters";
import { CATEGORIES, FACETS, detail, summary } from "./fixtures";

function router() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", name: "wardrobe", component: { template: "<div/>" } },
      { path: "/items/:id", name: "item", component: { template: "<div/>" } },
    ],
  });
}

describe("ItemCard", () => {
  it("shows brand, names, resolved color and size, and links to detail", async () => {
    const w = mount(ItemCard, { props: { item: summary() }, global: { plugins: [router()] } });
    expect(w.text()).toContain("UNIQLO");
    expect(w.text()).toContain("テストダウン");
    expect(w.text()).toContain("测试羽绒");
    expect(w.text()).toContain("NAVY");
    expect(w.text()).toContain("L");
    expect(w.find("a").attributes("href")).toBe("/items/1");
    expect(w.find("img").attributes("loading")).toBe("lazy");
    expect(w.find(".status").exists()).toBe(false);
  });

  it("shows a status badge and a placeholder when there is no image", () => {
    const w = mount(ItemCard, {
      props: { item: summary({ status: "returned", thumb_url: null, name_zh: null }) },
      global: { plugins: [router()] },
    });
    expect(w.find(".status").text()).toBe("已退货");
    expect(w.find("img").exists()).toBe(false);
    expect(w.find(".placeholder").attributes("style")).toContain("background");
  });
});

describe("FilterPanel", () => {
  const mountPanel = (filters = DEFAULT_FILTERS) =>
    mount(FilterPanel, {
      props: { filters, facets: FACETS, categories: CATEGORIES, brands: [] },
    });

  it("only offers colors that have items, plus selected ones", () => {
    const labels = (w: ReturnType<typeof mountPanel>) => w.findAll(".swatch-label").map((x) => x.text());
    expect(labels(mountPanel())).toEqual(["黑", "藏青"]);
    expect(labels(mountPanel({ ...DEFAULT_FILTERS, color: ["red"] }))).toEqual(["黑", "红", "藏青"]);
  });

  it("emits a toggled list when a swatch is clicked", async () => {
    const w = mountPanel({ ...DEFAULT_FILTERS, color: ["black"] });
    await w.findAll(".swatch")[1].trigger("click"); // 藏青
    expect(w.emitted("change")?.[0]).toEqual([{ color: ["black", "navy"] }]);
    await w.findAll(".swatch")[0].trigger("click"); // 再点黑色 → 取消
    expect(w.emitted("change")?.[1]).toEqual([{ color: [] }]);
  });

  it("hides empty categories and expands the selected path", async () => {
    let w = mountPanel();
    expect(w.findAll(".node .name").map((x) => x.text())).toEqual(["外套", "上衣"]); // 鞋没有衣物
    w = mountPanel({ ...DEFAULT_FILTERS, category: "outer-light-down" });
    expect(w.findAll(".node .name").map((x) => x.text())).toEqual(["外套", "羽绒", "轻羽绒", "上衣"]);
    await w.findAll(".node")[2].trigger("click"); // 再点已选中的分类 → 取消
    expect(w.emitted("change")?.[0]).toEqual([{ category: null }]);
  });

  it("orders sizes sensibly and shows status counts", () => {
    const w = mountPanel();
    expect(w.findAll(".pill").slice(0, 3).map((x) => x.text())).toEqual(["M", "L", "76cm"]);
    const status = w.findAll("section").at(-1)!.text();
    expect(status).toContain("持有中");
    expect(status).toContain("已退货");
    expect(status).toContain("全部");
  });
});

describe("failed images", () => {
  it("replaces a broken card thumbnail and retries when its URL changes", async () => {
    const w = mount(ItemCard, { props: { item: summary() }, global: { plugins: [router()] } });
    await w.find("img").trigger("error");
    expect(w.find("img").exists()).toBe(false);
    expect(w.find(".placeholder").text()).toContain("テストダウン");
    await w.setProps({ item: summary({ thumb_url: "/media/new.webp" }) });
    expect(w.find("img").attributes("src")).toBe("/media/new.webp");
    w.unmount();
  });

  it("shows a gallery fallback and still allows switching to a working image", async () => {
    const d = detail();
    const w = mount(ImageGallery, { props: { images: [...d.images, ...d.product.images], alt: d.name } });
    await w.find(".main img").trigger("error");
    expect(w.find(".no-image").text()).toContain("图片加载失败");
    await w.find(".nav.next").trigger("click");
    expect(w.find(".main img").attributes("src")).toBe("/media/original/a.png");
    w.unmount();
  });
});
