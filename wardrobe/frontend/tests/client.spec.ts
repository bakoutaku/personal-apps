import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, buildUrl, request } from "../src/api/client";

afterEach(() => vi.unstubAllGlobals());

const fail = (p: Promise<unknown>) => p.then(() => { throw new Error("expected failure"); }, (e: ApiError) => e);

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => new Response(body === undefined ? "" : JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("api client", () => {
  it("sends repeated complete values instead of joining comma-containing tags", () => {
    const url = new URL(buildUrl("/items", { tag_exact: ["QA,逗号", "通勤"] }), "http://localhost");
    expect(url.searchParams.getAll("tag_exact")).toEqual(["QA,逗号", "通勤"]);
  });
  it("builds URLs and drops empty params", () => {
    expect(buildUrl("/items", { q: "ダウン", brand: "", color: undefined, limit: 48 })).toBe(
      `/api/v1/items?q=${encodeURIComponent("ダウン")}&limit=48`,
    );
  });

  it("sends the client header only on writes", async () => {
    const fetchMock = mockFetch(200, { ok: true });
    await request("GET", "/items");
    await request("POST", "/tags", { body: { name: "x" } });
    const [, getInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [, postInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect((getInit.headers as Record<string, string>)["X-Wardrobe-Client"]).toBeUndefined();
    expect((postInit.headers as Record<string, string>)["X-Wardrobe-Client"]).toBe("web-ui");
    expect(postInit.body).toBe(JSON.stringify({ name: "x" }));
  });

  it("maps the backend error format to ApiError", async () => {
    mockFetch(404, { error: { code: "NOT_FOUND", message: "wardrobe_item 9 不存在", details: [] } });
    const err = await fail(request("GET", "/items/9"));
    expect(err).toBeInstanceOf(ApiError);
    expect([err.status, err.code, err.message]).toEqual([404, "NOT_FOUND", "wardrobe_item 9 不存在"]);
  });

  it("handles non-JSON errors and network failures", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })));
    const err = await fail(request("GET", "/items"));
    expect([err.status, err.code]).toEqual([502, "HTTP_502"]);

    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const net = await fail(request("GET", "/items"));
    expect(net.code).toBe("NETWORK");
    expect(net.message).toContain("./wardrobe start");
  });
});
