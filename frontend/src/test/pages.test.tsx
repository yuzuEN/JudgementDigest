import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "../App";
import CivilResult from "../pages/CivilResult";
import Confirm from "../pages/Confirm";
import CriminalResult from "../pages/CriminalResult";
import Reading from "../pages/Reading";
import { IntakeProvider, STORAGE_KEY } from "../state";
import { CIVIL_REPORT, CRIMINAL_REPORT, GUIDE, mockApi, OPTIONS, renderApp, renderAt, TRAFFIC } from "./helpers";

describe("首頁", () => {
  it("有開始的按鈕、示例結果與免責說明", () => {
    renderApp("/");
    const starts = screen.getAllByRole("link", { name: "開始查詢" });
    expect(starts.length).toBeGreaterThan(0);
    starts.forEach((a) => expect(a).toHaveAttribute("href", "/start"));
    expect(screen.getByRole("heading", { name: "這不是法律意見" })).toBeInTheDocument();
    expect(screen.getByLabelText("結果預覽（示例）")).toHaveTextContent("示例");
    // 角色說明只在首頁和關卡 1：不是律師或法官
    expect(screen.getByRole("region", { name: "CasEY 角色說明" })).toHaveTextContent("不是律師或法官");
    expect(screen.queryByRole("navigation", { name: "進度" })).not.toBeInTheDocument();
  });
});

describe("描述案情（關卡 1–3）", () => {
  const current = () => within(screen.getByRole("navigation", { name: "進度" })).getByRole("listitem", { current: "step" });

  it("一次只顯示一關，進度圖標出目前的關卡", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start", { caseType: "" });
    expect(screen.getByRole("heading", { name: /第 1 關/ })).toBeInTheDocument();
    expect(current()).toHaveTextContent("類型");
    // 一開始沒有預設，要自己選
    expect(screen.getByRole("radio", { name: "民事" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "下一關" })).toBeDisabled();
    expect(screen.getByText("請先選一種案件類型。")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "民事" }));
    expect(screen.getByText("可能判准的金額範圍")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "刑事" }));
    expect(screen.getByText("可能的罪名與法條")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一關" }));
    expect(screen.getByRole("heading", { name: /第 2 關/ })).toHaveFocus();
    expect(screen.queryByRole("heading", { name: /第 1 關/ })).not.toBeInTheDocument();
    expect(current()).toHaveTextContent("案情");
    // 刑事不選糾紛類型，改顯示怎麼寫
    expect(screen.getByRole("heading", { name: "刑事案件怎麼寫" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /糾紛類型/ })).not.toBeInTheDocument();
    // 角色說明只在關卡 1
    expect(screen.getByRole("region", { name: "CasEY 角色說明" })).not.toHaveTextContent("不是律師或法官");
  });

  it("案情不到 30 字不能下一關，寫作提示寫到就亮起來", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start?stage=2");
    const next = screen.getByRole("button", { name: "下一關" });
    await user.type(screen.getByLabelText("用自己的話寫就好"), "今年7月在路口被汽車撞");
    expect(next).toBeDisabled();
    expect(screen.getByText("案情至少要 30 字。")).toBeInTheDocument();
    expect(screen.getByText(/再多寫一點：至少 30 字/)).toBeInTheDocument();
    expect(screen.getByText("時間").closest("li")).toHaveTextContent("已寫到");
    expect(screen.getByText("損失（金額或傷勢）").closest("li")).toHaveTextContent("還沒寫到");

    await user.type(screen.getByLabelText("用自己的話寫就好"), "，右腿骨折住院兩週，醫藥費和薪水損失加起來約64萬元。");
    expect(next).toBeEnabled();
    expect(screen.getByText("字數夠了，可以進下一關。")).toBeInTheDocument();
    expect(screen.getByText("損失（金額或傷勢）").closest("li")).toHaveTextContent("已寫到");
  });

  it("糾紛類型可以搜尋、多選、取消，右邊顯示已選類型的說明", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start?stage=2");
    const traffic = await screen.findByRole("button", { name: "侵權：交通事故" });
    const help = screen.getByRole("complementary", { name: "已選類型的說明" });
    expect(help).toHaveTextContent("還沒選");
    await user.click(traffic);
    expect(traffic).toHaveAttribute("aria-pressed", "true");
    expect(help).toHaveTextContent("因車禍造成受傷或財物損失");

    await user.type(screen.getByLabelText("搜尋糾紛類型"), "借");
    expect(screen.queryByRole("button", { name: "侵權：交通事故" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "民間借貸" }));
    await user.clear(screen.getByLabelText("搜尋糾紛類型"));
    await user.click(screen.getByRole("button", { name: "侵權：交通事故" }));
    expect(help).not.toHaveTextContent("因車禍造成受傷或財物損失");
    expect(help).toHaveTextContent("民間借貸");
  });

  it("金額告訴使用者讀成多少，看不懂就擋下一章", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start?stage=3", { text: TRAFFIC });
    const amount = screen.getByLabelText("想請求的金額");
    const next = screen.getByRole("button", { name: "下一章：確認內容" });
    expect(screen.getByText(/沒填也可以/)).toBeInTheDocument();
    await user.type(amount, "64萬8千");
    expect(screen.getByText("我讀成：648,000 元")).toBeInTheDocument();
    await user.clear(amount);
    await user.type(amount, "五十萬");
    expect(screen.getByText(/看不懂這個金額/)).toBeInTheDocument();
    expect(next).toBeDisabled();
    expect(screen.getByText("金額格式不對，請修改。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "50 萬" }));
    expect(screen.getByText("我讀成：500,000 元")).toBeInTheDocument();
    expect(next).toBeEnabled();

    // 法院可以不選，選項從 API 來
    await user.click(screen.getByLabelText(/打算在哪個法院/));
    expect(await screen.findByRole("option", { name: "臺北地方法院" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    // 對方三選一，再點一次取消
    const company = screen.getByRole("button", { name: "公司" });
    await user.click(company);
    expect(company).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("complementary", { name: "你填的資料" })).toHaveTextContent("公司");
  });

  it("刑事只問律師和證物，答案接在描述後面送出", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS, "POST /intake/followup": () => ({ questions: [], source: "rules" }) });
    const user = userEvent.setup();
    renderApp("/start?stage=3", { caseType: "criminal", text: "上個月我在超商拿了兩瓶酒沒有結帳就走出去，被店員攔下來報警。" });
    expect(screen.queryByText("對方是")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("想請求的金額")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "有" }));
    const slot = screen.getByRole("button", { name: "驗傷單、診斷證明" });
    await user.click(slot);
    expect(slot).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "下一章：確認內容" }));
    expect(await screen.findByText(/有沒有請律師：有/)).toBeInTheDocument();
    expect(screen.getByText(/手上的證據：驗傷單、診斷證明/)).toBeInTheDocument();
  });

  it("填的內容存在這個分頁，重新整理後還在", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ caseType: "civil" }));   // 第 1 關選過民事
    const page = () => render(<MemoryRouter initialEntries={["/start?stage=2"]}><IntakeProvider><App /></IntakeProvider></MemoryRouter>);
    const first = page();
    await user.type(screen.getByLabelText("用自己的話寫就好"), "被車撞");
    expect(JSON.parse(window.sessionStorage.getItem(STORAGE_KEY)!)).toMatchObject({ caseType: "civil", text: "被車撞" });
    first.unmount();
    page();
    expect(screen.getByLabelText("用自己的話寫就好")).toHaveValue("被車撞");
  });

  it("還沒選類型就直接開後面的關卡或確認頁、結果頁，回到第 1 關", async () => {
    const { calls } = mockApi({ "GET /meta/options": () => OPTIONS });
    for (const route of ["/start?stage=3", "/confirm?stage=5", "/result/civil"]) {
      const { unmount } = renderApp(route, { caseType: "", text: TRAFFIC, maskedText: TRAFFIC });
      expect(screen.getByRole("heading", { name: /第 1 關/ })).toBeInTheDocument();
      unmount();
    }
    expect(calls.map((c) => c.key)).not.toContain("POST /civil/report");
    expect(calls.map((c) => c.key)).not.toContain("POST /intake/followup");
  });

  it("直接開第 3 關、案情還不夠時回到第 2 關", () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    renderApp("/start?stage=3", { text: "太短" });
    expect(screen.getByRole("heading", { name: /第 2 關/ })).toBeInTheDocument();
  });

  it("選項載入失敗可以重試", async () => {
    mockApi({ "GET /meta/options": { status: 500 } });
    renderApp("/start?stage=2");
    expect(await screen.findByRole("alert")).toHaveTextContent("選項載入失敗");
    expect(screen.getByRole("button", { name: "再試一次" })).toBeInTheDocument();
  });
});

describe("進度圖", () => {
  it("已完成的關卡可以點回去，還沒到的不能點", async () => {
    mockApi({ "POST /intake/followup": () => ({ questions: [], source: "rules" }) });
    renderAt("/confirm", <Confirm />, "/confirm", { text: "朋友借錢沒還" });
    expect(await screen.findByRole("link", { name: "第 1 關 類型（已完成）" })).toHaveAttribute("href", "/start?stage=1");
    expect(screen.getByRole("link", { name: "第 3 關 資料（已完成）" })).toHaveAttribute("href", "/start?stage=3");
    expect(screen.queryByRole("link", { name: /遮名/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /結果/ })).not.toBeInTheDocument();
    expect(screen.getByText("遮名").closest("li")).toHaveAttribute("aria-current", "step");
  });

  it("結果頁可以回到前面的關卡", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容" });
    expect(await screen.findByRole("link", { name: "第 4 關 遮名（已完成）" })).toHaveAttribute("href", "/confirm?stage=4");
    expect(screen.getByRole("link", { name: "第 2 關 案情（已完成）" })).toHaveAttribute("href", "/start?stage=2");
  });
});

describe("第 6 關：整理成判決書的寫法", () => {
  const BUTTON = "請 AI 整理敘述";
  const rules = { questions: [], source: "rules", llm_available: true };
  const setup = (reply: unknown, extra: Record<string, (b: never) => unknown> = {}) => {
    const sent: { text: string; case_type: string }[] = [];
    const api = mockApi({
      "POST /intake/followup": () => rules,
      "POST /intake/rewrite": (b: { text: string; case_type: string }) => { sent.push(b); return reply; },
      ...extra,
    });
    return { sent, calls: api.calls };
  };
  const llm = { text: "原告主張被告未還款。", source: "llm", added_numbers: [] };
  const at6 = "/confirm?stage=6";

  it("沒有設定 LLM 時不顯示，直接最後確認", async () => {
    mockApi({ "POST /intake/followup": () => ({ ...rules, llm_available: false }) });
    renderAt("/confirm", <Confirm />, at6, { text: "他欠我錢" });
    expect(await screen.findByRole("heading", { name: "第 6 關　最後確認" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "看參考結果" })).toBeEnabled());
    expect(screen.queryByRole("button", { name: BUTTON })).not.toBeInTheDocument();
  });

  it("刑事也可以整理，送出案件類型", async () => {
    const { sent } = setup(llm);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at6, { text: "他打我", caseType: "criminal" });
    await user.click(await screen.findByRole("button", { name: BUTTON }));
    expect(await screen.findByText(/這段只用來推估罪名與刑期/)).toBeInTheDocument();
    expect(sent[0]).toMatchObject({ case_type: "criminal" });
  });

  it("按下按鈕才傳，送的是遮名後的文字", async () => {
    const { sent } = setup(llm);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at6, { text: "王小明的電話是0912345678，他欠我錢", names: ["王小明"] });
    const button = await screen.findByRole("button", { name: BUTTON });
    expect(sent).toHaveLength(0);
    await user.click(button);
    await screen.findByLabelText("整理後的寫法（可以直接修改）");
    expect(sent).toHaveLength(1);
    expect(sent[0].text).not.toContain("王小明");
    expect(sent[0].text).not.toContain("0912345678");
  });

  it("改過的整理會再遮一次；選原文就不送整理", async () => {
    const { calls } = setup(llm, { "POST /civil/report": () => CIVIL_REPORT, "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp(at6, { text: "他欠我錢", names: ["王小明"] });
    await user.click(await screen.findByRole("button", { name: BUTTON }));
    const box = await screen.findByLabelText("整理後的寫法（可以直接修改）");
    expect(screen.getByRole("radio", { name: "使用整理後的寫法" })).toBeChecked();
    await user.clear(box);
    await user.type(box, "原告王小明主張被告未還款");
    await user.click(screen.getByRole("button", { name: "看參考結果" }));
    await screen.findByText("62%");
    expect(calls.find((c) => c.key === "POST /civil/report")!.body).toMatchObject({ search_text: "原告【姓名】主張被告未還款" });
  });

  it("選「改用我的原文」就不用整理的文字", async () => {
    const { calls } = setup(llm, { "POST /civil/report": () => CIVIL_REPORT });
    const user = userEvent.setup();
    renderApp(at6, { text: "他欠我錢" });
    await user.click(await screen.findByRole("button", { name: BUTTON }));
    await user.click(await screen.findByRole("radio", { name: "改用我的原文" }));
    await user.click(screen.getByRole("button", { name: "看參考結果" }));
    await screen.findByText("62%");
    expect(calls.find((c) => c.key === "POST /civil/report")!.body).toMatchObject({ search_text: null });
  });

  it("提醒描述裡沒有的數字；沒有時說明都對得上", async () => {
    setup({ ...llm, added_numbers: ["112"] });
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at6, { text: "他欠我錢" });
    await user.click(await screen.findByRole("button", { name: BUTTON }));
    expect(await screen.findByRole("alert")).toHaveTextContent("整理後出現了原文沒有的數字：「112」");
  });

  it("數字都對得上時說明", async () => {
    setup(llm);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at6, { text: "他欠我錢" });
    await user.click(await screen.findByRole("button", { name: BUTTON }));
    expect(await screen.findByText("整理後的數字，都能在原文找到。")).toBeInTheDocument();
  });

  it("AI 不能用時改用原本的描述", async () => {
    setup({ source: "none", added_numbers: [], fallback: "error" });
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at6, { text: "他欠我錢" });
    await user.click(await screen.findByRole("button", { name: BUTTON }));
    expect(await screen.findByText(/會改用你原本的描述/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "看參考結果" })).toBeEnabled();
  });

  it("整理過的草稿在關卡之間來回時保留，不會再傳一次", async () => {
    const { sent } = setup(llm);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at6, { text: "他欠我錢" });
    await user.click(await screen.findByRole("button", { name: BUTTON }));
    await screen.findByLabelText("整理後的寫法（可以直接修改）");
    await user.click(screen.getByRole("button", { name: "上一關" }));
    await user.click(screen.getByRole("button", { name: /下一關/ }));
    expect(screen.getByLabelText("整理後的寫法（可以直接修改）")).toHaveValue("原告主張被告未還款。");
    expect(sent).toHaveLength(1);
  });

  it("描述改了，之前的整理就作廢", async () => {
    setup(llm);
    renderAt("/confirm", <Confirm />, at6, { text: "他欠我錢", rewriteFor: "舊的描述", rewriteDraft: "舊的整理", searchText: "舊的整理" });
    expect(await screen.findByRole("button", { name: BUTTON })).toBeInTheDocument();
    expect(screen.queryByLabelText("整理後的寫法（可以直接修改）")).not.toBeInTheDocument();
  });

  it("結果頁送出確認過的文字", async () => {
    const { calls } = mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容", searchText: "原告主張" });
    expect(await screen.findByText("用你確認過的整理文字搜尋。")).toBeInTheDocument();
    expect(calls[0].body).toMatchObject({ text: "內容", search_text: "原告主張" });
  });
});

describe("結果頁的民事、刑事分頁", () => {
  const intake = { text: "內容", maskedText: "內容" };

  it("選民事時不能切到刑事", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { ...intake, caseType: "civil" });
    await screen.findByText("62%");
    expect(screen.queryByRole("link", { name: "刑事" })).not.toBeInTheDocument();
    expect(screen.getByText("刑事")).toHaveAttribute("aria-disabled", "true");
  });

  it("選刑事時不能切到民事", async () => {
    mockApi({ "POST /criminal/predict": () => CRIMINAL_REPORT });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", { ...intake, caseType: "criminal" });
    await screen.findByRole("heading", { name: "可能的罪名" });
    expect(screen.queryByRole("link", { name: "民事" })).not.toBeInTheDocument();
    expect(screen.getByText("民事")).toHaveAttribute("aria-disabled", "true");
  });

  it("選刑事時，直接開民事網址會回到刑事，也不查民事", async () => {
    const { calls } = mockApi({ "POST /criminal/predict": () => CRIMINAL_REPORT });
    renderApp("/result/civil", { ...intake, caseType: "criminal" });
    expect(await screen.findByRole("heading", { name: "可能的罪名" })).toBeInTheDocument();
    expect(calls.map((c) => c.key)).not.toContain("POST /civil/report");
  });

  it("不確定時可以切到刑事", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { ...intake, caseType: "unsure" });
    await screen.findByText("62%");
    expect(screen.getByRole("link", { name: "刑事" })).toHaveAttribute("href", "/result/criminal");
  });

  it("選民事時，直接開刑事網址會回到民事，也不查刑事", async () => {
    const { calls } = mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderApp("/result/criminal", { ...intake, caseType: "civil" });
    expect(await screen.findByText("62%")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).not.toContain("POST /criminal/predict");
  });
});

describe("相似判決的結果", () => {
  const show = (over: Partial<typeof CIVIL_REPORT>) => {
    mockApi({ "POST /civil/report": () => ({ ...CIVIL_REPORT, ...over }) });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容" });
  };
  const prediction = (signal: "strong" | "weak" | "insufficient") => ({ ...CIVIL_REPORT.prediction, signal });

  it("主畫面是判決件數，機率放在模型細節", async () => {
    show({});
    expect(await screen.findByRole("img", { name: "全部勝訴 8 件、部分勝訴 13 件、敗訴 9 件" })).toBeInTheDocument();
    expect(screen.getByText("62%").closest("details")).not.toBeNull();
  });

  it("被告未到庭的件數另外說明", async () => {
    show({ default_cases: 12 });
    expect(await screen.findByText(/有 12 件被告未到庭/)).toBeInTheDocument();
  });

  it("沒有被告未到庭時不顯示", async () => {
    show({});
    await screen.findByText("62%");
    expect(screen.queryByText(/件被告未到庭/)).not.toBeInTheDocument();
  });

  it("模型參考依訊號顯示固定文字", async () => {
    show({ prediction: prediction("weak") });
    expect(await screen.findByText(/勝訴訊號較弱/)).toBeInTheDocument();
  });

  it("資訊不足時不說強弱", async () => {
    show({ prediction: prediction("insufficient") });
    expect(await screen.findByText(/資訊不足/)).toBeInTheDocument();
    expect(screen.queryByText(/勝訴訊號/)).not.toBeInTheDocument();
  });

  it("相似判決太少時不畫比例", async () => {
    show({ outcomes: { total: 6, win: 3, partial: 2, lose: 1 } });
    expect(await screen.findByText(/這次不顯示比例/)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /全部勝訴/ })).not.toBeInTheDocument();
  });

  it("相似判決和模型不一致時提醒看判決", async () => {
    show({ prediction: prediction("weak"), outcomes: { total: 30, win: 15, partial: 9, lose: 6 } });
    expect(await screen.findByText(/不完全一致/)).toBeInTheDocument();
  });

  it("一致時不提醒", async () => {
    show({});
    await screen.findByText("62%");
    expect(screen.queryByText(/不完全一致/)).not.toBeInTheDocument();
  });
});

describe("模型表現", () => {
  it("用 precision、recall 說明，不顯示 AUC", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容" });
    expect(await screen.findByText(/判勝訴的案件有 73% 真的勝訴/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Precision、Recall 說明/ })).toBeInTheDocument();
    expect(screen.queryByText(/AUC/)).not.toBeInTheDocument();
  });

  it("舊的模型檔沒有這些數字時不顯示", async () => {
    const { win_precision: _, ...model } = CIVIL_REPORT.prediction.model;
    mockApi({ "POST /civil/report": () => ({ ...CIVIL_REPORT, prediction: { ...CIVIL_REPORT.prediction, model } }) });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容" });
    await screen.findByText("62%");
    expect(screen.queryByText(/真的勝訴/)).not.toBeInTheDocument();
  });
});

describe("列印", () => {
  const withBuckets = {
    ...CIVIL_REPORT,
    amount_range: { ...CIVIL_REPORT.amount_range!, buckets: [{ low: 0, high: 0.2, count: 3 }] },
  };

  it("列印時展開金額明細，印完恢復", async () => {
    mockApi({ "POST /civil/report": () => withBuckets });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容" });
    const details = (await screen.findByText("看各金額範圍有幾件")).closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    window.dispatchEvent(new Event("beforeprint"));
    window.dispatchEvent(new Event("beforeprint"));   // 有些瀏覽器會觸發兩次
    expect(details.open).toBe(true);
    window.dispatchEvent(new Event("afterprint"));
    expect(details.open).toBe(false);
  });

  it("使用者自己打開的明細，印完不會被關掉", async () => {
    mockApi({ "POST /civil/report": () => withBuckets });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容" });
    const details = (await screen.findByText("看各金額範圍有幾件")).closest("details") as HTMLDetailsElement;
    details.open = true;
    window.dispatchEvent(new Event("beforeprint"));
    window.dispatchEvent(new Event("afterprint"));
    expect(details.open).toBe(true);
  });
});

describe("相似度說明", () => {
  it("表格旁有 i 和文字說明，不會讓人以為是百分比", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容" });
    const info = await screen.findByRole("link", { name: /相似度說明/ });
    expect(info.getAttribute("href")).toBe(`/guide#${encodeURIComponent("相似度")}`);
    expect(screen.getByText(/只用來排列結果，不是百分比/)).toBeInTheDocument();
  });

  it("說明頁有對應的位置", () => {
    renderApp("/guide");
    expect(document.getElementById("相似度")).not.toBeNull();
  });

  it("從 i 跳過去時標題會標黃，點別的地方就消失", () => {
    renderApp(`/guide#${encodeURIComponent("相似度")}`);
    const title = screen.getByText("相似度", { selector: "dt" });
    expect(title).toHaveClass("jump-target");
    fireEvent.click(document.body);
    expect(title).not.toHaveClass("jump-target");
  });

  it("跳到整個區段時標的是區段標題", () => {
    renderApp("/guide#dispute-types");
    expect(screen.getByRole("heading", { name: "糾紛類型說明" })).toHaveClass("jump-target");
  });

  it("直接打開說明頁時不標任何東西", () => {
    renderApp("/guide");
    expect(document.querySelector(".jump-target")).toBeNull();
  });
});

describe("金額明細", () => {
  it("展開後看到各範圍的件數", async () => {
    const buckets = [{ low: 0, high: 0.2, count: 3 }, { low: 0.2, high: 0.4, count: 7 }];
    const range = { ...CIVIL_REPORT.amount_range!, buckets };
    mockApi({ "POST /civil/report": () => ({ ...CIVIL_REPORT, amount_range: range }) });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容" });
    expect(await screen.findByText("看各金額範圍有幾件")).toBeInTheDocument();
    expect(screen.getByText("10 萬～20 萬")).toBeInTheDocument();
    expect(screen.getByText("7 件")).toBeInTheDocument();
  });

  it("沒有明細時不顯示", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容" });
    await screen.findByText("62%");
    expect(screen.queryByText("看各金額範圍有幾件")).not.toBeInTheDocument();
  });
});

describe("說明與知識", () => {
  it("每個頁面都能到說明頁", () => {
    renderApp("/");
    // 頁首和頁尾各一個
    screen.getAllByRole("link", { name: "說明與法律小知識" }).forEach((a) => expect(a).toHaveAttribute("href", "/guide"));
    expect(screen.getByRole("banner")).toContainElement(screen.getAllByRole("link", { name: "說明與法律小知識" })[0]);
  });

  it("說明頁有糾紛類型和名詞", () => {
    renderApp("/guide");
    expect(screen.getByRole("heading", { name: "糾紛類型說明" })).toBeInTheDocument();
    expect(document.getElementById("侵權：交通事故")!.querySelector("dt")).toHaveTextContent("侵權：交通事故");
    expect(screen.getByRole("heading", { name: /受傷、損害賠償（侵權）/ })).toBeInTheDocument();
    expect(screen.getByText("被告未到庭（一造辯論）")).toBeInTheDocument();
    expect(document.getElementById("民間借貸")).not.toBeNull();
  });

  it("點目錄平滑捲到該段，不直接跳轉", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    renderApp("/guide");
    const toc = screen.getByRole("navigation", { name: "本頁目錄" });
    await userEvent.setup().click(within(toc).getByRole("link", { name: "常見名詞" }));
    expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    expect(window.location.hash).toBe("#terms");
  });

});

describe("第 4 關：確認遮名與敏感資料", () => {
  const rulesApi = () => mockApi({ "POST /intake/followup": () => ({ questions: [], source: "rules" }) });

  it("預覽遮名後的內容，可以加名字、再移除", async () => {
    rulesApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "王小明撞到我，他的電話0912345678" });
    expect(await screen.findByRole("heading", { name: /第 4 關/ })).toBeInTheDocument();
    expect(await screen.findByText("【電話】")).toBeInTheDocument();
    await user.type(screen.getByLabelText("還有要遮的名字嗎？"), "王小明");
    await user.click(screen.getByRole("button", { name: "加入" }));
    await waitFor(() => expect(screen.getAllByText("【姓名】").length).toBeGreaterThan(0));
    await user.click(screen.getByRole("button", { name: "不遮「王小明」" }));
    expect(await screen.findByText(/王小明撞到我/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "修改描述" })).toHaveAttribute("href", "/start?stage=2");
  });

  it("單一個字的名字也可以遮", async () => {
    rulesApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "阿明說王打他" });
    await user.type(await screen.findByLabelText("還有要遮的名字嗎？"), "王");
    await user.click(screen.getByRole("button", { name: "加入" }));
    expect(await screen.findByRole("button", { name: "不遮「王」" })).toBeInTheDocument();
    expect(screen.getByText("【姓名】")).toBeInTheDocument();
  });

  it("原文和姓名不會出現在任何網路請求裡", async () => {
    const { calls } = rulesApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "王小明撞到我，他的電話0912345678" });
    await user.type(await screen.findByLabelText("還有要遮的名字嗎？"), "王小明");
    await user.click(screen.getByRole("button", { name: "加入" }));
    await screen.findAllByText("【姓名】");
    const sent = JSON.stringify(calls);
    expect(sent).not.toContain("0912345678");
    expect(sent).not.toContain("王小明");
    expect(sent).not.toContain("撞到我");
    expect(calls.map((c) => c.key)).not.toContain("POST /intake/mask");
  });

  it("有敏感個資時要先同意，列出偵測到的類別", async () => {
    rulesApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "我受傷了，對方有前科，後來去住院" });
    expect(await screen.findByText(/偵測到：病歷、醫療、犯罪前科/)).toBeInTheDocument();
    const next = screen.getByRole("button", { name: "下一關" });
    expect(next).toBeDisabled();
    expect(screen.getByText(/請先選擇「我同意」/)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "我同意" }));
    await waitFor(() => expect(next).toBeEnabled());
  });

  it("不同意時說明要回去刪掉，不能往下", async () => {
    rulesApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "我開刀後休養三個月" });
    await user.click(await screen.findByRole("radio", { name: "不同意，回上一步刪掉" }));
    expect(screen.getByRole("link", { name: "回描述案情" })).toHaveAttribute("href", "/start?stage=2");
    expect(screen.getByRole("button", { name: "下一關" })).toBeDisabled();
  });

  it("沒有敏感個資就不用選", async () => {
    rulesApi();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "朋友借了五十萬一直沒還" });
    await waitFor(() => expect(screen.getByRole("button", { name: "下一關" })).toBeEnabled());
    expect(screen.queryByRole("radio", { name: "我同意" })).not.toBeInTheDocument();
  });

  it("還沒同意就直接開第 5 關，會回到第 4 關", async () => {
    rulesApi();
    renderAt("/confirm", <Confirm />, "/confirm?stage=5", { text: "我骨折住院" });
    expect(await screen.findByRole("heading", { name: /第 4 關/ })).toBeInTheDocument();
  });

  it("回上一章是第 3 關", async () => {
    rulesApi();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "朋友借錢沒還" });
    expect(await screen.findByRole("link", { name: "回上一章" })).toHaveAttribute("href", "/start?stage=3");
  });
});

describe("第 5 關：補充細節", () => {
  const AI_TAB = "請 AI 幫我看還缺什麼";
  const SEND = "傳給 AI，開始提問";
  type Body = { text: string; allow_llm: boolean };
  const setup = (reply: (b: Body) => unknown) => {
    const sent: Body[] = [];
    mockApi({ "POST /intake/followup": (b: Body) => { sent.push(b); return reply(b); } });
    return sent;
  };
  const rulesReply = { questions: [{ id: "when", text: "什麼時候發生的？", why: "時效" }], source: "rules", llm_available: true };
  const aiReply = { questions: [{ id: "llm1", text: "對方怎麼說？", why: "爭點" }], source: "llm", llm_available: true };
  const at5 = "/confirm?stage=5";
  const openAi = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole("tab", { name: AI_TAB }));
    return screen.getByRole("button", { name: SEND });
  };

  it("打開頁面時不會把內容傳給 LLM", async () => {
    const sent = setup(() => rulesReply);
    renderAt("/confirm", <Confirm />, at5, { text: "王小明的電話是0912345678" });
    await screen.findByRole("tab", { name: AI_TAB });
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ allow_llm: false, text: "" });
  });

  it("沒有設定 LLM 時只有固定題目", async () => {
    setup(() => ({ ...rulesReply, llm_available: false }));
    renderAt("/confirm", <Confirm />, at5, { text: "內容" });
    expect(await screen.findByLabelText("什麼時候發生的？")).toBeInTheDocument();
    expect(screen.getByText("為什麼要問：時效")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: AI_TAB })).not.toBeInTheDocument();
    expect(screen.queryByText(/付費 API/)).not.toBeInTheDocument();
  });

  it("描述已經回答的問題不用問，最多 4 題", async () => {
    const pool = ["a", "b", "c", "d", "e", "f"].map((id) => ({ id, text: `問題${id}`, why: "因為", skip_if: id === "a" ? "綠燈" : null }));
    mockApi({ "POST /intake/followup": () => ({ questions: pool, source: "rules" }) });
    renderAt("/confirm", <Confirm />, at5, { text: "當時是綠燈" });
    expect(await screen.findByText("問題b")).toBeInTheDocument();
    expect(screen.queryByText("問題a")).not.toBeInTheDocument();
    expect(screen.getByText("問題e")).toBeInTheDocument();
    expect(screen.queryByText("問題f")).not.toBeInTheDocument();
  });

  it("回答會加進送出的內容，按鈕從「略過」變成「下一關」", async () => {
    setup(() => rulesReply);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "朋友借錢沒還" });
    expect(screen.getByRole("button", { name: "略過，下一關" })).toBeInTheDocument();
    await user.type(await screen.findByLabelText("什麼時候發生的？"), "去年");
    expect(screen.getByRole("button", { name: "下一關" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "上一關" }));
    expect(await screen.findByText(/回答：去年/)).toBeInTheDocument();
  });

  it("切到 AI 分頁還不會傳，按下按鈕才傳，而且姓名已經遮掉", async () => {
    const sent = setup((b) => (b.allow_llm ? aiReply : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "王小明的電話是0912345678", names: ["王小明"] });
    const send = await openAi(user);
    expect(sent.filter((b) => b.allow_llm)).toHaveLength(0);
    await user.click(send);
    expect(await screen.findByLabelText("對方怎麼說？")).toBeInTheDocument();
    expect(screen.getByText(/由 AI 依你的案情產生/)).toBeInTheDocument();
    const toLlm = sent.filter((b) => b.allow_llm);
    expect(toLlm).toHaveLength(1);
    expect(toLlm[0].text).toBe("【姓名】的電話是【電話】");
  });

  it("AI 和固定題目可以來回切換，不會重複傳，回答也保留", async () => {
    const sent = setup((b) => (b.allow_llm ? aiReply : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "內容" });
    await user.click(await openAi(user));
    await user.type(await screen.findByLabelText("對方怎麼說？"), "他不承認");
    await user.click(screen.getByRole("tab", { name: "固定題目（不用 AI）" }));
    expect(screen.getByLabelText("什麼時候發生的？")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: AI_TAB }));
    expect(screen.getByLabelText("對方怎麼說？")).toHaveValue("他不承認");
    expect(sent.filter((b) => b.allow_llm)).toHaveLength(1);
  });

  it("AI 失敗時說不是你填錯，可以重試或改用固定題目", async () => {
    let fail = true;
    setup((b) => {
      if (!b.allow_llm) return rulesReply;
      if (fail) { fail = false; return { ...rulesReply, fallback: "error" }; }
      return aiReply;
    });
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "內容" });
    await user.click(await openAi(user));
    expect(await screen.findByText("這次沒有成功")).toBeInTheDocument();
    expect(screen.getByText("出了點問題，不是你填錯。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "再試一次" }));
    expect(await screen.findByLabelText("對方怎麼說？")).toBeInTheDocument();
  });

  it("超過用量上限時說明原因，可以改用固定題目", async () => {
    setup((b) => (b.allow_llm ? { ...rulesReply, fallback: "limited" } : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "內容" });
    await user.click(await openAi(user));
    expect(await screen.findByText("今天的 AI 次數用完了")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "改用固定題目" }));
    expect(screen.getByLabelText("什麼時候發生的？")).toBeInTheDocument();
  });

  it("內容不像法律糾紛時說明原因，不說 AI 壞了", async () => {
    setup((b) => (b.allow_llm ? { ...rulesReply, fallback: "not_dispute" } : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "今天天氣很好" });
    await user.click(await openAi(user));
    expect(await screen.findByText("這看起來不像法律糾紛")).toBeInTheDocument();
    expect(screen.queryByText("這次沒有成功")).not.toBeInTheDocument();
  });

  it("同意文字與資料使用說明寫出會傳給哪一家 AI", async () => {
    setup(() => ({ ...rulesReply, llm_vendor: "OpenAI" }));
    renderAt("/confirm", <Confirm />, "/confirm", { text: "我骨折住院" });
    expect(await screen.findByText(/這些內容也會傳給 OpenAI/)).toBeInTheDocument();
    expect(screen.getByText(/才會傳給 OpenAI 的付費 API/)).toBeInTheDocument();
  });
});

describe("民事結果", () => {
  const intake = { text: TRAFFIC, maskedText: TRAFFIC, mids: ["侵權：交通事故"], claimedAmount: "50萬", evidence: ["medical"] };

  it("顯示機率、金額、相似判決、證據與抗辯", async () => {
    const { calls } = mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    expect(await screen.findByText("62%")).toBeInTheDocument();
    expect(screen.getByText("18 萬～42 萬")).toBeInTheDocument();
    expect(screen.getByText(/比對了 30 件/)).toBeInTheDocument();
    expect(screen.getByText(/口語描述算出來的機率常常偏低/)).toBeInTheDocument();
    expect(screen.getByText("臺灣臺北地方法院 113 年度訴字第 1 號")).toBeInTheDocument();
    expect(screen.getByText("31 萬／48 萬")).toBeInTheDocument();
    expect(screen.getByText("你有提到")).toBeInTheDocument();
    expect(screen.getByText("沒有提到")).toBeInTheDocument();
    expect(screen.getByText("你也有過失（與有過失）")).toBeInTheDocument();
    expect(screen.queryByText(/示例資料/)).not.toBeInTheDocument();
    expect(calls[0].body).toMatchObject({ text: TRAFFIC, mid: "侵權：交通事故", claimed_amount: 500000, evidence: ["medical"] });
  });

  it("只看勝訴的判決", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    const user = userEvent.setup();
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    await user.click(screen.getByRole("checkbox", { name: "只看原告勝訴的" }));
    // 畫面上收起來，但還留在頁面上，列印時才印得出來
    expect(table.querySelectorAll("tbody tr.screen-hidden")).toHaveLength(1);
  });

  it("一造辯論的判決標示被告未到庭，並說明不計入統計", async () => {
    const [first, ...rest] = CIVIL_REPORT.similar;
    mockApi({ "POST /civil/report": () => ({ ...CIVIL_REPORT, similar: [{ ...first, default_judgment: true }, ...rest] }) });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("被告未到庭")).toHaveLength(1);
    expect(within(within(table).getAllByRole("row")[1]).getByText("被告未到庭")).toBeInTheDocument();
    expect(screen.getByText(/統計不包含這些判決/)).toBeInTheDocument();
  });

  it("沒有一造辯論的判決就不顯示說明", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    await screen.findByRole("table");
    expect(screen.queryByText("被告未到庭")).not.toBeInTheDocument();
    expect(screen.queryByText(/統計不包含這些判決/)).not.toBeInTheDocument();
  });

  it("示例資料要標示；下載 PDF 會開啟列印", async () => {
    mockApi({ "POST /civil/report": () => ({ ...CIVIL_REPORT, mock: true }) });
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    const user = userEvent.setup();
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    expect(await screen.findByText("示例資料：數字與判決都不是真的")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下載 PDF" }));
    expect(print).toHaveBeenCalledOnce();
    expect(screen.getByText(/本報告是示例資料/).closest(".print-only")).not.toBeNull();   // PDF 上也要標示
  });

  it("金額範圍：沒填請求金額、件數不足", async () => {
    const range = { ...CIVIL_REPORT.amount_range!, claimed: null, amount_low: null, amount_high: null, amount_median: null };
    mockApi({ "POST /civil/report": () => ({ ...CIVIL_REPORT, amount_range: range }) });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    expect(await screen.findByText("36%～84%")).toBeInTheDocument();
  });

  describe("金額範圍的來源", () => {
    type Range = NonNullable<typeof CIVIL_REPORT.amount_range>;
    const model: Range = { ...CIVIL_REPORT.amount_range!, source: "model", scope: "partial_win",
                           buckets: [{ low: 0, high: 0.2, count: 3 }] };
    const show = async (range: Range | null) => {
      mockApi({ "POST /civil/report": () => ({ ...CIVIL_REPORT, amount_range: range }) });
      renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
      await screen.findByText("62%");
    };

    it("沒有模型：照舊寫「如果勝訴」與相似判決的件數", async () => {
      await show({ ...model, source: "similar", scope: "win" });
      expect(screen.getByRole("heading", { name: "如果勝訴，可能判准的金額" })).toBeInTheDocument();
      expect(screen.getByText(/依 18 件相似的勝訴判決/)).toBeInTheDocument();
      expect(screen.queryByText(/一部勝訴/, { selector: "h2" })).not.toBeInTheDocument();
    });

    it("舊版後端沒有 source 欄位時視為相似判決", async () => {
      mockApi({ "POST /civil/report": () => CIVIL_REPORT });
      renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
      expect(await screen.findByRole("heading", { name: "如果勝訴，可能判准的金額" })).toBeInTheDocument();
    });

    it("模型：標明「若為一部勝訴」，不再說依幾件相似判決，並提醒範圍很寬", async () => {
      await show(model);
      expect(screen.getByRole("heading", { name: "如果判決是「一部勝訴」，可能判准的金額" })).toBeInTheDocument();
      expect(screen.getByText("18 萬～42 萬")).toBeInTheDocument();
      expect(screen.getByText(/用過去的一部勝訴判決測試，10 件約有 8 件落在這個範圍/)).toBeInTheDocument();
      expect(screen.getByText(/範圍很寬/)).toBeInTheDocument();
      expect(screen.getByText(/如果判決是全部勝訴，通常就是請求的全部金額/)).toBeInTheDocument();
      expect(screen.queryByText(/件相似的勝訴判決）/)).not.toBeInTheDocument();
    });

    it("模型：沒填請求金額時只給比例", async () => {
      await show({ ...model, claimed: null, amount_low: null, amount_median: null, amount_high: null });
      expect(screen.getByRole("heading", { name: "如果判決是「一部勝訴」，可能拿到請求金額的" })).toBeInTheDocument();
      expect(screen.getByText("36%～84%")).toBeInTheDocument();
      expect(screen.getByText(/回上一步填寫想請求的金額/)).toBeInTheDocument();
    });

    it("模型：相似判決的分布留著當對照，並說明它不是範圍的依據", async () => {
      await show(model);
      expect(screen.getByText("看各金額範圍有幾件")).toBeInTheDocument();
      expect(screen.getByText(/上面的範圍是模型推估的/)).toBeInTheDocument();
    });

    it("模型：相似的勝訴判決不夠時仍給範圍，只是沒有分布可看", async () => {
      await show({ ...model, n_cases: null, buckets: [] });
      expect(screen.getByText("18 萬～42 萬")).toBeInTheDocument();
      expect(screen.queryByText("看各金額範圍有幾件")).not.toBeInTheDocument();
      expect(screen.queryByText(/無法估出金額範圍/)).not.toBeInTheDocument();
    });
  });

  it("相似的勝訴判決不夠時不給金額", async () => {
    mockApi({ "POST /civil/report": () => ({ ...CIVIL_REPORT, amount_range: null }) });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    expect(await screen.findByText(/無法估出金額範圍/)).toBeInTheDocument();
  });

  it("錯誤可以重試", async () => {
    mockApi({ "POST /civil/report": { status: 500 } });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    expect(await screen.findByRole("alert")).toHaveTextContent("伺服器發生錯誤");
  });

  it("沒有內容就回到第一步", () => {
    renderApp("/result/civil");
    expect(screen.getByRole("heading", { name: /這是哪一類的事情/ })).toBeInTheDocument();
  });
});

describe("刑事結果", () => {
  it("點罪名切換刑期分布", async () => {
    mockApi({ "POST /criminal/predict": () => CRIMINAL_REPORT });
    const user = userEvent.setup();
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", { caseType: "criminal", text: "x", maskedText: "開車撞到人" });
    expect(await screen.findByRole("heading", { name: "刑期範圍：過失傷害罪" })).toBeInTheDocument();
    expect(screen.getByText(/刑事組開發中/)).toBeInTheDocument();
    const card = (name: string) => screen.getByRole("heading", { name }).closest("[data-slot=card]");
    await user.click(screen.getByRole("button", { name: /肇事逃逸罪/ }));
    expect(screen.getByRole("button", { name: /肇事逃逸罪/ })).toHaveAttribute("aria-pressed", "true");
    expect(card("刑期範圍：肇事逃逸罪")).not.toHaveClass("screen-hidden");
    expect(card("刑期範圍：過失傷害罪")).toHaveClass("screen-hidden");
    expect(screen.getByText("98%")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "可能的刑期範圍（有期徒刑）" })).not.toBeInTheDocument();
  });

  it("有確認過的整理文字時，用它推估", async () => {
    const { calls } = mockApi({ "POST /criminal/predict": () => ({ ...CRIMINAL_REPORT, mock: false }) });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", { caseType: "criminal", text: "x", maskedText: "他打我", searchText: "被告徒手毆打被害人" });
    expect(await screen.findByText(/使用你確認過的整理文字/)).toBeInTheDocument();
    expect(calls[0].body).toEqual({ text: "被告徒手毆打被害人" });
  });

  it("罪名模型是真的時，不標示例", async () => {
    mockApi({ "POST /criminal/predict": () => ({ ...CRIMINAL_REPORT, mock: false }) });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", { caseType: "criminal", text: "x", maskedText: "開車撞到人" });
    const charges = (await screen.findByRole("heading", { name: "可能的罪名" })).closest("[data-slot=card]") as HTMLElement;
    expect(within(charges).queryByText("示例資料")).not.toBeInTheDocument();
    expect(screen.queryByText(/刑事組開發中/)).not.toBeInTheDocument();
  });

  it("真模型沒有相似判決時顯示開發中，不出現示例提示", async () => {
    mockApi({ "POST /criminal/predict": () => ({ ...CRIMINAL_REPORT, similar: [], mock: false }) });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", { caseType: "criminal", text: "x", maskedText: "開車撞到人" });
    expect(await screen.findByText("刑事的相似判決檢索開發中。")).toBeInTheDocument();
    expect(screen.queryByText(/刑事組開發中/)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("修法提示、相似判決的宣告刑、模型測試結果", async () => {
    const [first, ...rest] = CRIMINAL_REPORT.charges;
    mockApi({ "POST /criminal/predict": () => ({ ...CRIMINAL_REPORT, mock: false,
      charges: [{ ...first, law_note: "修法前為洗錢防制法第 14 條", n_similar: 50,
        similar_sentence: [{ label: "拘役、罰金", share: 0.2 }, { label: "1～6 個月", share: 0.8 }] }, ...rest],
      model: { name: "criminal_v1", description: "TF-IDF ＋ SVM", n_test: 10000, charge_top1: 0.93,
        bucket_accuracy: 0.7, bucket_within_one: 0.95 } }) });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", { caseType: "criminal", text: "x", maskedText: "開車撞到人" });
    expect(await screen.findByText("修法前為洗錢防制法第 14 條")).toBeInTheDocument();
    expect(screen.getByText(/最相似的 50 件「過失傷害罪」有罪判決/)).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText(/第一個罪名猜中 93%/)).toBeInTheDocument();
  });

  it("真的刑事判決連到司法院原文，不連判決導讀", async () => {
    const url = "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDM";
    mockApi({ "POST /criminal/predict": () => ({ ...CRIMINAL_REPORT, mock: false,
      similar: [{ ...CRIMINAL_REPORT.similar[0], url }] }) });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", { caseType: "criminal", text: "x", maskedText: "開車撞到人" });
    expect(await screen.findByRole("link", { name: "判決原文" })).toHaveAttribute("href", url);
    expect(screen.queryByRole("link", { name: "判決導讀" })).not.toBeInTheDocument();
  });
});

describe("判決導讀", () => {
  it("段落與標示切換", async () => {
    const { calls } = mockApi({ "GET /judgments/civil/11/guide": () => GUIDE });
    const user = userEvent.setup();
    const { container } = renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    expect(await screen.findByRole("heading", { name: "臺灣臺北地方法院 113 年度訴字第 1 號" })).toBeInTheDocument();
    expect(calls[0].key).toBe("GET /judgments/civil/11/guide");
    expect(container.querySelector(".para[data-fn=issue]")).toHaveAttribute("data-on", "true");
    expect(container.querySelector(".para[data-fn=claim]")).toHaveAttribute("data-on", "false");
    await user.click(screen.getByRole("checkbox", { name: /原告主張/ }));
    expect(container.querySelector(".para[data-fn=claim]")).toHaveAttribute("data-on", "true");
    expect(screen.getByText(/規則初步標示/)).toBeInTheDocument();
  });

  it("找不到判決", async () => {
    mockApi({});
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/999");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
