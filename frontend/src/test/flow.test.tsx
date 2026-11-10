import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CIVIL_REPORT, CRIMINAL_REPORT, GUIDE, mockApi, OPTIONS, renderApp } from "./helpers";

describe("完整流程", () => {
  it("首頁 → 描述 → 確認遮名 → 民事結果 → 刑事結果 → 判決導讀", async () => {
    const { calls } = mockApi({
      "GET /meta/options": () => OPTIONS,
      "POST /intake/followup": () => ({ questions: [], source: "rules" }),
      "POST /civil/report": () => CIVIL_REPORT,
      "POST /criminal/predict": () => CRIMINAL_REPORT,
      "GET /judgments/civil/11/guide": () => GUIDE,
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(screen.getAllByRole("link", { name: "開始查詢" })[0]);
    await user.click(screen.getByRole("radio", { name: "不確定" }));
    await user.click(screen.getByRole("button", { name: "下一關" }));
    await user.type(screen.getByLabelText("用自己的話寫就好"), "去年三月朋友向我借了五十萬，說好半年就還，到現在一直不還，他的電話0912345678");
    await user.click(await screen.findByRole("button", { name: "民間借貸" }));
    await user.click(screen.getByRole("button", { name: "下一關" }));
    await user.type(screen.getByLabelText("想請求的金額"), "50萬");
    await user.click(screen.getByRole("button", { name: "沒有" }));
    await user.click(screen.getByRole("button", { name: "下一章：確認內容" }));

    expect(await screen.findByRole("heading", { name: /第 4 關/ })).toBeInTheDocument();
    expect((await screen.findAllByText("【電話】")).length).toBeGreaterThan(0);
    const next = screen.getByRole("button", { name: "下一關" });
    await waitFor(() => expect(next).toBeEnabled());
    await user.click(next);
    await user.click(screen.getByRole("button", { name: "略過，下一關" }));
    const go = screen.getByRole("button", { name: "看參考結果" });
    await waitFor(() => expect(go).toBeEnabled());
    await user.click(go);

    expect(await screen.findByText("62%")).toBeInTheDocument();
    const report = calls.find((c) => c.key === "POST /civil/report")!.body;
    expect(report).toMatchObject({ mid: "民間借貸", claimed_amount: 500000, plaintiff_has_lawyer: false });
    expect(JSON.stringify(report)).not.toContain("0912345678");

    await user.click(screen.getByRole("link", { name: "刑事" }));
    expect(await screen.findByRole("heading", { name: "可能的罪名" })).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /criminal/predict")!.body).toEqual({ text: expect.stringContaining("【電話】") });

    await user.click(screen.getByRole("link", { name: "民事" }));
    await user.click((await screen.findAllByRole("link", { name: "判決導讀" }))[0]);
    expect(await screen.findByText("本件爭點為被告有無過失。")).toBeInTheDocument();
  });
});
