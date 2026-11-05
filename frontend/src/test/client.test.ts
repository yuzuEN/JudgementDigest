import { describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api/client";
import { mockApi } from "./helpers";

describe("api client", () => {
  it("GET 與 POST", async () => {
    const { calls } = mockApi({
      "GET /health": () => ({ status: "ok" }),
      "POST /intake/followup": () => ({ questions: [], source: "rules" }),
    });
    await api.health();
    await api.followup("civil", null, "你好");
    expect(calls).toEqual([
      { key: "GET /health", body: undefined },
      { key: "POST /intake/followup", body: { case_type: "civil", mid: null, text: "你好", allow_llm: false } },
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
