import { describe, expect, it } from "vitest";
import { DEFAULT_FILTERS, activeCount, fromQuery, toApiQuery, toQuery, toggle } from "../src/lib/filters";

describe("filters <-> URL", () => {
  it("round-trips commas and repeated exact tag/size values without splitting", () => {
    const f = { ...DEFAULT_FILTERS, tag: ["QA,逗号", "通勤"], size: ["M,L", "L"] };
    const url = toQuery(f);
    expect(url).toEqual({ tag_exact: ["QA,逗号", "通勤"], size_exact: ["M,L", "L"] });
    expect(fromQuery(url as never)).toEqual(f);
    expect(toApiQuery(f)).toEqual({ status: "owned", tag_exact: f.tag, size_exact: f.size, tag_mode: "all" });
    expect(fromQuery({ tag_exact: "QA,逗号" }).tag).toEqual(["QA,逗号"]);
    expect(fromQuery({ tag: "通勤,秋冬", tag_exact: ["QA,逗号", "通勤"] }).tag).toEqual(["通勤", "秋冬", "QA,逗号"]);
  });
  it("defaults when query is empty", () => {
    expect(fromQuery({})).toEqual(DEFAULT_FILTERS);
  });

  it("round-trips through the URL and omits defaults", () => {
    const f = { ...DEFAULT_FILTERS, q: " ダウン ", color: ["navy", "black"], category: "outer", status: "all" };
    const q = toQuery(f);
    expect(q).toEqual({ q: "ダウン", color: "navy,black", category: "outer", status: "all" });
    expect(fromQuery(q as never)).toEqual({ ...f, q: "ダウン" });
    expect(toQuery(DEFAULT_FILTERS)).toEqual({});
  });

  it("ignores empty list segments and takes the first of repeated params", () => {
    const f = fromQuery({ brand: "uniqlo,,gu", q: ["a", "b"] } as never);
    expect(f.brand).toEqual(["uniqlo", "gu"]);
    expect(f.q).toBe("a");
  });

  it("builds the API query with comma lists and AND tag mode", () => {
    const f = { ...DEFAULT_FILTERS, tag: ["通勤", "秋冬"], size: ["M"] };
    expect(toApiQuery(f)).toEqual({ status: "owned", tag: "通勤,秋冬", tag_mode: "all", size: "M" });
  });

  it("toggles values and counts active filters", () => {
    expect(toggle(["a"], "b")).toEqual(["a", "b"]);
    expect(toggle(["a", "b"], "a")).toEqual(["b"]);
    expect(activeCount(DEFAULT_FILTERS)).toBe(0);
    expect(activeCount({ ...DEFAULT_FILTERS, q: "x", color: ["navy", "black"], status: "all" })).toBe(4);
  });
});
