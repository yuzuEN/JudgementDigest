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

    await user.click(screen.getByRole("link", { name: "開始描述案情" }));
    await user.click(screen.getByRole("button", { name: /不確定/ }));
    await user.type(screen.getByLabelText("發生了什麼事？"), "朋友向我借了五十萬一直不還，他的電話0912345678");
    await user.selectOptions(await screen.findByLabelText("糾紛類型"), "民間借貸");
    await user.type(screen.getByLabelText("想請求的金額（新臺幣）"), "50萬");
    await user.click(screen.getByRole("radio", { name: "還沒有" }));
    await user.click(screen.getByRole("button", { name: "下一步：確認內容" }));

    expect(await screen.findByRole("heading", { name: "確認內容" })).toBeInTheDocument();
    expect(await screen.findByText("【電話】")).toBeInTheDocument();
    const go = screen.getByRole("button", { name: "看參考結果" });
    await waitFor(() => expect(go).toBeEnabled());
    await user.click(go);

    expect(await screen.findByText("62%")).toBeInTheDocument();
    const report = calls.find((c) => c.key === "POST /civil/report")!.body;
    expect(report).toMatchObject({ mid: "民間借貸", claimed_amount: 500000, plaintiff_has_lawyer: false });
    expect(JSON.stringify(report)).not.toContain("0912345678");

    await user.click(screen.getByRole("link", { name: "刑事" }));
    expect(await screen.findByRole("heading", { name: "刑期範圍：過失傷害罪" })).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /criminal/predict")!.body).toEqual({ text: expect.stringContaining("【電話】") });

    await user.click(screen.getByRole("link", { name: "民事" }));
    await user.click((await screen.findAllByRole("link", { name: "判決導讀" }))[0]);
    expect(await screen.findByText("本件爭點為被告有無過失。")).toBeInTheDocument();
  });
});
