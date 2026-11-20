import { describe, expect, it, vi } from "vitest";
import { api, ApiError, clearReportCache } from "../api/client";
import { mockApi } from "./helpers";

describe("api client", () => {
  it("相同結果共用進行中的請求，返回頁面時沿用結果；修改描述或重設後重算", async () => {
    const { calls } = mockApi({ "POST /criminal/predict": (body) => ({ text: body.text }) });
    const first = api.criminalReport("原案情");
    expect(api.criminalReport("原案情")).toBe(first);
    const result = await first;
    expect(await api.criminalReport("原案情")).toBe(result);
    expect(calls).toHaveLength(1);
    await api.criminalReport("修改案情");
    expect(calls).toHaveLength(2);
    clearReportCache();
    await api.criminalReport("修改案情");
    expect(calls).toHaveLength(3);
  });

  it("民事與刑事分開快取，民事條件改變會重算", async () => {
    const { calls } = mockApi({ "POST /civil/report": () => ({}), "POST /criminal/predict": () => ({}) });
    const input = { text: "案情", evidence: [] };
    await api.civilReport(input);
    await api.criminalReport(input.text);
    await api.civilReport({ ...input });
    expect(calls).toHaveLength(2);
    await api.civilReport({ ...input, claimed_amount: 10000 });
    expect(calls).toHaveLength(3);
  });

  it("失敗的結果不快取，可以重試", async () => {
    let attempts = 0;
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      attempts++;
      return new Response(attempts === 1 ? "error" : "{}", { status: attempts === 1 ? 500 : 200 });
    });
    await expect(api.criminalReport("案情")).rejects.toThrow();
    await expect(api.criminalReport("案情")).resolves.toEqual({});
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("GET 與 POST", async () => {
    const { calls } = mockApi({
      "GET /health": () => ({ status: "ok" }),
      "POST /intake/followup": () => ({ questions: [], source: "rules" }),
    });
    await api.health();
    await api.followup("civil", null, "你好");
    expect(calls).toEqual([
      { key: "GET /health", body: undefined },
      { key: "POST /intake/followup", body: { case_type: "civil", role: "plaintiff", mid: null, text: "你好", allow_llm: false } },
    ]);
  });

  it("422 給看得懂的訊息", async () => {
    mockApi({ "POST /civil/report": { status: 422 } });
    await expect(api.civilReport({ text: "", evidence: [] })).rejects.toThrow("格式不正確");
  });

  it("伺服器錯誤", async () => {
    mockApi({ "GET /meta/options": { status: 500 } });
    await expect(api.options()).rejects.toBeInstanceOf(ApiError);
  });

  it("連不上", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.health()).rejects.toThrow("連不上伺服器");
  });
});
