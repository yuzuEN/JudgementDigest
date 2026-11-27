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
    expect(screen.getByRole("heading", { name: "結果的使用限制" })).toBeInTheDocument();
    expect(screen.getByLabelText("民事查詢結果範例（示例）")).toHaveTextContent("一部勝訴 10 件");
    const criminal = screen.getByLabelText("刑事查詢結果範例（示例）");
    expect(criminal).toHaveTextContent("示例");
    expect(criminal).toHaveTextContent("最接近罪名竊盜罪（刑法第 320 條）預測刑度");
    expect(criminal).toHaveTextContent("30 件相似案件中，有 18 件落在這個範圍");
    expect(criminal).not.toHaveTextContent("比對 30 件相似判決");
    expect(screen.getByLabelText("民事查詢結果範例（示例）")).toHaveTextContent("30 件相似案件中，有 25 件落在這個範圍");
    // 首頁不放「不是律師或法官」的角色補充（只留關卡 1）
    expect(screen.getByRole("region", { name: "CasEY 角色說明" })).not.toHaveTextContent("不是律師或法官");
    expect(screen.queryByRole("navigation", { name: "進度" })).not.toBeInTheDocument();
  });

  it("頁底的按鈕回到最上方", async () => {
    const scrollTo = vi.fn();
    window.scrollTo = scrollTo as unknown as typeof window.scrollTo;
    renderApp("/");
    await userEvent.setup().click(screen.getByRole("button", { name: "回到最上方" }));
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 0 }));
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
    expect(screen.getByText(/辯解先不用寫/)).toBeInTheDocument();
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
    await user.type(screen.getByLabelText("事情經過"), "今年7月在路口被汽車撞");
    expect(next).toBeDisabled();
    expect(screen.getByText("案情至少要 30 字。")).toBeInTheDocument();
    expect(screen.getByText(`還需 ${30 - "今年7月在路口被汽車撞".length} 字`)).toBeInTheDocument();
    expect(screen.getByText("時間").closest("li")).toHaveTextContent("已寫到");
    expect(screen.getByText("損失（金額或傷勢）").closest("li")).toHaveTextContent("還沒寫到");

    await user.type(screen.getByLabelText("事情經過"), "，右腿骨折住院兩週，醫藥費和薪水損失加起來約64萬元。");
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
    expect(help).toHaveTextContent("尚未選擇");
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

  it("糾紛類型依說明頁的大類收合，46 類都選得到；搜尋時有結果的大類自動打開", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start?stage=2", { mids: ["民間借貸"] });
    const group = (title: string) => screen.getByText(title, { selector: "summary span" }).closest("details")!;
    // 和說明頁同樣的 6 個大類，加起來 46 類
    const groups = Array.from(document.querySelectorAll("details.group\\/kind"));
    expect(groups.map((d) => d.querySelector("summary span")!.textContent)).toEqual(["受傷、損害賠償（侵權）", "契約", "借錢與金融", "勞動", "房屋與土地", "確認與其他"]);
    expect(groups.flatMap((d) => Array.from(d.querySelectorAll("button"))).length).toBe(46);
    // 一開始只打開有已選類型的大類，標出已選幾類
    expect(group("借錢與金融")).toHaveAttribute("open");
    expect(group("借錢與金融")).toHaveTextContent("已選 1");
    expect(group("勞動")).not.toHaveAttribute("open");
    // 自己打開大類，就能直接點裡面的類型
    await user.click(screen.getByText("勞動", { selector: "summary span" }));
    expect(group("勞動")).toHaveAttribute("open");
    await user.click(within(group("勞動")).getByRole("button", { name: "勞動：資遣費" }));
    expect(group("勞動")).toHaveTextContent("已選 1");
    // 搜尋：用說明的字也找得到，有結果的大類自動打開
    await user.type(screen.getByLabelText("搜尋糾紛類型"), "押金");
    expect(group("契約")).toHaveAttribute("open");
    expect(within(group("契約")).getByRole("button", { name: "契約：租金" })).toBeInTheDocument();
    expect(screen.queryByText("勞動", { selector: "summary span" })).not.toBeInTheDocument();
  });

  it("金額告訴使用者讀成多少，看不懂就擋下一關", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start?stage=3", { text: TRAFFIC });
    const next = screen.getByRole("button", { name: "下一關" });
    expect(screen.getByText("未填入時，結果僅會顯示求償比例")).toBeInTheDocument();
    // 一進來就是輸入框，旁邊只有「不確定」
    const amount = screen.getByLabelText("想請求的金額");
    expect(screen.queryByRole("button", { name: "自訂" })).not.toBeInTheDocument();
    await user.type(amount, "64萬8千");
    expect(document.getElementById("amount-status")).toHaveTextContent(/^648,000 元$/);
    await user.clear(amount);
    await user.type(amount, "五十萬");
    expect(screen.getByText(/看不懂這個金額/)).toBeInTheDocument();
    expect(next).toBeDisabled();
    expect(screen.getByText("金額格式不對，請修改。")).toBeInTheDocument();
    await user.clear(amount);
    await user.type(amount, "50萬");
    expect(document.getElementById("amount-status")).toHaveTextContent(/^500,000 元$/);
    expect(next).toBeEnabled();
    // 「不確定」清空金額；再打字就取消
    const unsure = screen.getByRole("button", { name: "不確定" });
    await user.click(unsure);
    expect(unsure).toHaveAttribute("aria-pressed", "true");
    expect(amount).toHaveValue("");
    expect(screen.getByText("未填入時，結果僅會顯示求償比例")).toBeInTheDocument();
    await user.type(amount, "3萬");
    expect(unsure).toHaveAttribute("aria-pressed", "false");
    await user.clear(amount);

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
    await user.click(screen.getByRole("button", { name: "下一關" }));
    expect(await screen.findByText(/被告有沒有請辯護律師：有/)).toBeInTheDocument();
    expect(screen.getByText(/手上的證據：驗傷單、診斷證明/)).toBeInTheDocument();
  });

  it("填的內容存在這個分頁，重新整理後還在", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ caseType: "civil" }));   // 第 1 關選過民事
    const page = () => render(<MemoryRouter initialEntries={["/start?stage=2"]}><IntakeProvider><App /></IntakeProvider></MemoryRouter>);
    const first = page();
    await user.type(screen.getByLabelText("事情經過"), "被車撞");
    expect(JSON.parse(window.sessionStorage.getItem(STORAGE_KEY)!)).toMatchObject({ caseType: "civil", text: "被車撞" });
    first.unmount();
    page();
    expect(screen.getByLabelText("事情經過")).toHaveValue("被車撞");
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
    expect(await screen.findByText(/被告、被害人與「敘述者」是否對應正確/)).toBeInTheDocument();
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
    expect(screen.getByRole("radio", { name: "整理後的寫法" })).toBeChecked();
    await user.clear(box);
    await user.type(box, "原告王小明主張被告未還款");
    await user.click(screen.getByRole("button", { name: "看參考結果" }));
    await screen.findByText("62%");
    expect(calls.find((c) => c.key === "POST /civil/report")!.body).toMatchObject({ search_text: "原告【姓名】主張被告未還款" });
  });

  it("選「我的原文」就不用整理的文字", async () => {
    const { calls } = setup(llm, { "POST /civil/report": () => CIVIL_REPORT });
    const user = userEvent.setup();
    renderApp(at6, { text: "他欠我錢" });
    await user.click(await screen.findByRole("button", { name: BUTTON }));
    await user.click(await screen.findByRole("radio", { name: "我的原文" }));
    await user.click(screen.getByRole("button", { name: "看參考結果" }));
    await screen.findByText("62%");
    expect(calls.find((c) => c.key === "POST /civil/report")!.body).toMatchObject({ search_text: null });
  });

  it("切到「我的原文」時文字框換成原文，切回來整理的內容還在", async () => {
    setup(llm);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at6, { text: "他欠我錢" });
    await user.click(await screen.findByRole("button", { name: BUTTON }));
    expect(await screen.findByLabelText("整理後的寫法（可以直接修改）")).toHaveValue("原告主張被告未還款。");
    await user.click(screen.getByRole("radio", { name: "我的原文" }));
    expect(screen.getByLabelText("我的原文（遮名後）")).toHaveValue("他欠我錢");
    expect(screen.getByLabelText("我的原文（遮名後）")).toHaveAttribute("readonly");
    expect(screen.queryByLabelText("整理後的寫法（可以直接修改）")).toBeNull();
    await user.click(screen.getByRole("radio", { name: "整理後的寫法" }));
    expect(screen.getByLabelText("整理後的寫法（可以直接修改）")).toHaveValue("原告主張被告未還款。");
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

  it("有敏感個資時，勾選同意才能整理；不勾也能直接看結果（用原本的描述）", async () => {
    const { sent } = setup(llm);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at6, { text: "我骨折住院，對方不賠" });
    const button = await screen.findByRole("button", { name: BUTTON });
    expect(button).toBeDisabled();
    expect(screen.queryByRole("radio", { name: /不同意/ })).not.toBeInTheDocument();
    expect(screen.getByText(/不想用 AI 的話不用勾，直接看參考結果，會用你原本的描述/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "看參考結果" })).toBeEnabled();
    await user.click(screen.getByRole("checkbox", { name: "我同意傳給 AI" }));
    await user.click(screen.getByRole("button", { name: BUTTON }));
    await screen.findByLabelText("整理後的寫法（可以直接修改）");
    expect(sent).toHaveLength(1);
  });

  it("結果頁送出確認過的文字", async () => {
    const { calls } = mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容", searchText: "原告主張" });
    expect(await screen.findByRole("heading", { name: "這次比對用的描述（整理後的寫法）" })).toBeInTheDocument();
    expect(calls[0].body).toMatchObject({ text: "內容", search_text: "原告主張" });
  });
});

describe("結果頁的民事、刑事切換", () => {
  const intake = { text: "內容", maskedText: "內容" };

  it("選民事時只有民事，沒有切換", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { ...intake, caseType: "civil" });
    await screen.findByText("62%");
    expect(screen.queryByRole("navigation", { name: "結果類型" })).not.toBeInTheDocument();
  });

  it("選刑事時只有刑事，沒有切換", async () => {
    mockApi({ "POST /criminal/predict": () => CRIMINAL_REPORT });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", { ...intake, caseType: "criminal" });
    await screen.findByRole("heading", { name: "可能的罪名" });
    expect(screen.queryByRole("navigation", { name: "結果類型" })).not.toBeInTheDocument();
  });

  it("選刑事時，直接開民事網址會回到刑事，也不查民事", async () => {
    const { calls } = mockApi({ "POST /criminal/predict": () => CRIMINAL_REPORT });
    renderApp("/result/civil", { ...intake, caseType: "criminal" });
    expect(await screen.findByRole("heading", { name: "可能的罪名" })).toBeInTheDocument();
    expect(calls.map((c) => c.key)).not.toContain("POST /civil/report");
  });

  it("不確定時同一頁上面是民事、下面是刑事，不用切換", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT, "POST /criminal/predict": () => CRIMINAL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { ...intake, caseType: "unsure" });
    const civil = await screen.findByRole("heading", { level: 2, name: /^民事參考結果/ });
    const criminal = await screen.findByRole("heading", { level: 2, name: "刑事參考結果" });
    expect(civil.compareDocumentPosition(criminal) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "結果類型" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "可能的罪名" })).toBeInTheDocument();
    // 每一區的分頁列最右邊都有下載 PDF
    expect(screen.getAllByRole("button", { name: "下載 PDF" })).toHaveLength(2);
  });

  it("不確定選原告（預設）時，提醒真正的被告回第 1 關改", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT, "POST /criminal/predict": () => CRIMINAL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { ...intake, caseType: "unsure" });
    expect(await screen.findByText("勝訴機率（勝訴或一部勝訴）")).toBeInTheDocument();
    expect(screen.getByText(/這就變成對方贏的機率/)).toBeInTheDocument();
    expect(screen.queryByText(/這裡假設對方指控的事都成立/)).not.toBeInTheDocument();
  });

  it("選民事原告時，不出現回第 1 關改被告的提醒", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { ...intake, caseType: "civil" });
    expect(await screen.findByText("62%")).toBeInTheDocument();
    expect(screen.queryByText(/這就變成對方贏的機率/)).not.toBeInTheDocument();
  });

  it("不確定時開刑事網址，會到合併頁", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT, "POST /criminal/predict": () => CRIMINAL_REPORT });
    renderApp("/result/criminal?tab=cases", { ...intake, caseType: "unsure" });
    expect(await screen.findByRole("heading", { level: 2, name: "刑事參考結果" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: /^民事參考結果/ })).toBeInTheDocument();
  });

  it("選民事時，直接開刑事網址會回到民事，也不查刑事", async () => {
    const { calls } = mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderApp("/result/criminal", { ...intake, caseType: "civil" });
    expect(await screen.findByText("62%")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).not.toContain("POST /criminal/predict");
  });
});

describe("相似判決怎麼找的說明", () => {
  it("說明頁有對應的位置", () => {
    renderApp("/guide");
    expect(document.getElementById("相似判決怎麼找")).not.toBeNull();
  });

  it("從 i 跳過去時標題會標黃，點別的地方就消失", () => {
    renderApp(`/guide#${encodeURIComponent("相似判決怎麼找")}`);
    const title = screen.getByText("相似判決怎麼找", { selector: "dt" });
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

  it("新增的名詞有分類標籤", () => {
    renderApp("/guide");
    const term = document.getElementById("與有過失")!;
    expect(term).toHaveTextContent("民事");
    expect(document.getElementById("拘役")).toHaveTextContent("未滿 60 天");
    expect(document.getElementById("告訴乃論")).toHaveTextContent("刑事");
  });

  it("從結果頁跳到收起來的糾紛類型時，會先打開", () => {
    renderApp(`/guide#${encodeURIComponent("民間借貸")}`);
    expect(document.getElementById("民間借貸")!.closest("details")).toHaveAttribute("open");
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

  it("資料使用說明在說明頁，目錄也連得到", () => {
    renderApp("/guide");
    const section = screen.getByRole("region", { name: "你的資料怎麼使用？" });
    expect(section).toHaveTextContent("蒐集者：本專題團隊");
    expect(section).toHaveTextContent("AI 服務不拿你的資料訓練模型");
    const toc = screen.getByRole("navigation", { name: "本頁目錄" });
    expect(within(toc).getByRole("link", { name: "資料使用說明" })).toHaveAttribute("href", "#privacy");
  });

  it("手機上的目錄可以展開、點了某一段就收起來", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    const user = userEvent.setup();
    renderApp("/guide");
    const toc = screen.getByRole("navigation", { name: "本頁目錄" });
    const toggle = within(toc).getByRole("button", { name: "目錄" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "guide-toc");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(within(toc).getByRole("link", { name: "常見名詞" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
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
    await user.type(screen.getByLabelText("有沒遮到的名稱嗎？"), "王小明");
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
    await user.type(await screen.findByLabelText("有沒遮到的名稱嗎？"), "王");
    await user.click(screen.getByRole("button", { name: "加入" }));
    expect(await screen.findByRole("button", { name: "不遮「王」" })).toBeInTheDocument();
    expect(screen.getByText("【姓名】")).toBeInTheDocument();
  });

  it("原文和姓名不會出現在任何網路請求裡", async () => {
    const { calls } = rulesApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "王小明撞到我，他的電話0912345678" });
    await user.type(await screen.findByLabelText("有沒遮到的名稱嗎？"), "王小明");
    await user.click(screen.getByRole("button", { name: "加入" }));
    await screen.findAllByText("【姓名】");
    const sent = JSON.stringify(calls);
    expect(sent).not.toContain("0912345678");
    expect(sent).not.toContain("王小明");
    expect(sent).not.toContain("撞到我");
    expect(calls.map((c) => c.key)).not.toContain("POST /intake/mask");
  });

  it("有敏感個資時只說明，不擋下一關，也不問同意", async () => {
    rulesApi();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "我受傷了，對方有前科，後來去住院" });
    expect(await screen.findByText(/偵測到：病歷、醫療、犯罪前科/)).toBeInTheDocument();
    expect(screen.getByText(/只用來比對相似判決，不會保存/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "下一關" })).toBeEnabled());
    expect(screen.queryByRole("radio", { name: /我同意/ })).not.toBeInTheDocument();
  });

  it("沒有敏感個資就不說明", async () => {
    rulesApi();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "朋友借了五十萬一直沒還" });
    await waitFor(() => expect(screen.getByRole("button", { name: "下一關" })).toBeEnabled());
    expect(screen.queryByText(/偵測到：/)).not.toBeInTheDocument();
  });

  it("沒同意也可以直接看結果（不用 AI）", async () => {
    rulesApi();
    renderAt("/confirm", <Confirm />, "/confirm?stage=6", { text: "我骨折住院" });
    await waitFor(() => expect(screen.getByRole("button", { name: "看參考結果" })).toBeEnabled());
  });

  it("第 4 關的上一關是第 3 關", async () => {
    rulesApi();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "朋友借錢沒還" });
    expect(await screen.findByRole("link", { name: "上一關" })).toHaveAttribute("href", "/start?stage=3");
  });
});

describe("第 5 關：補充細節", () => {
  const AI_TAB = "AI 提問";
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
    await user.click(await screen.findByRole("button", { name: AI_TAB }));
    return screen.getByRole("button", { name: SEND });
  };

  it("打開頁面時不會把內容傳給 LLM", async () => {
    const sent = setup(() => rulesReply);
    renderAt("/confirm", <Confirm />, at5, { text: "王小明的電話是0912345678" });
    await screen.findByRole("button", { name: AI_TAB });
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ allow_llm: false, text: "" });
  });

  it("沒有設定 LLM 時只有固定題目", async () => {
    setup(() => ({ ...rulesReply, llm_available: false }));
    renderAt("/confirm", <Confirm />, at5, { text: "內容" });
    expect(await screen.findByLabelText("什麼時候發生的？")).toBeInTheDocument();
    expect(screen.getByText("時效")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: AI_TAB })).not.toBeInTheDocument();
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

  it("回答會加進送出的內容；不管有沒有回答，按鈕都是「下一關」", async () => {
    setup(() => rulesReply);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "朋友借錢沒還" });
    expect(screen.getByRole("button", { name: "下一關" })).toBeInTheDocument();
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
    expect(screen.queryByText(/由 AI 依你的案情產生/)).not.toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "固定題目" }));
    expect(screen.getByLabelText("什麼時候發生的？")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: AI_TAB }));
    expect(screen.getByLabelText("對方怎麼說？")).toHaveValue("他不承認");
    expect(sent.filter((b) => b.allow_llm)).toHaveLength(1);
  });

  it("AI 失敗時提示重試或改用固定題目", async () => {
    let fail = true;
    setup((b) => {
      if (!b.allow_llm) return rulesReply;
      if (fail) { fail = false; return { ...rulesReply, fallback: "error" }; }
      return aiReply;
    });
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "內容" });
    await user.click(await openAi(user));
    expect(await screen.findByText("無法產生補充問題")).toBeInTheDocument();
    expect(screen.getByText("請再試一次，或改用固定題目。")).toBeInTheDocument();
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
    expect(screen.queryByText("無法產生補充問題")).not.toBeInTheDocument();
  });

  it("有敏感個資時，傳給 AI 前要先同意；沒同意按鈕不能按", async () => {
    const sent = setup((b) => (b.allow_llm ? aiReply : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "我骨折住院" });
    const send = await openAi(user);
    expect(screen.getByRole("heading", { name: "傳給 AI 前，需要你同意" })).toBeInTheDocument();
    expect(send).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "我同意傳給 AI" }));
    expect(send).toBeEnabled();
    await user.click(screen.getByRole("checkbox", { name: "我同意傳給 AI" }));
    expect(send).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "我同意傳給 AI" }));
    await user.click(send);
    expect(await screen.findByLabelText("對方怎麼說？")).toBeInTheDocument();
    expect(sent.filter((b) => b.allow_llm)).toHaveLength(1);
  });

  it("不勾選同意就不會傳給 AI，可以改答固定題目", async () => {
    const sent = setup((b) => (b.allow_llm ? aiReply : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "我骨折住院" });
    const send = await openAi(user);
    expect(send).toBeDisabled();
    expect(screen.getByText("不想用 AI 的話，改答上面的固定題目就好。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "固定題目" }));
    expect(screen.getByLabelText("什麼時候發生的？")).toBeInTheDocument();
    expect(sent.every((b) => !b.allow_llm)).toBe(true);
  });

  it("沒有敏感個資就不用同意", async () => {
    setup(() => rulesReply);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "朋友借錢沒還" });
    const send = await openAi(user);
    expect(screen.queryByRole("heading", { name: "傳給 AI 前，需要你同意" })).not.toBeInTheDocument();
    expect(send).toBeEnabled();
  });

  it("同意說明只寫偵測到的資料與用途", async () => {
    setup(() => ({ ...rulesReply, llm_vendor: "OpenAI" }));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "我骨折住院" });
    await openAi(user);
    expect(screen.getByText(/^你的描述裡有法律特別保護的資料（偵測到：.+）。$/)).toBeInTheDocument();
    expect(screen.getByText("只傳遮名內容，不做其他用途。")).toBeInTheDocument();
    expect(screen.queryByText(/遮名後的內容會傳給/)).toBeNull();
    expect(screen.getByText("AI 不拿來訓練模型")).toBeInTheDocument();
  });
});

describe("民事結果", () => {
  const intake = { text: TRAFFIC, maskedText: TRAFFIC, mids: ["侵權：交通事故"], claimedAmount: "50萬", evidence: ["medical"] };
  type Report = typeof CIVIL_REPORT;
  type Range = NonNullable<Report["amount_range"]>;
  const show = async (over: Partial<Report> = {}, route = "/result/civil") => {
    const api = mockApi({ "POST /civil/report": () => ({ ...CIVIL_REPORT, ...over }) });
    renderAt("/result/civil", <CivilResult />, route, intake);
    await screen.findByRole("tab", { name: "整體結果" });
    return api;
  };
  const user = () => userEvent.setup();
  const openTab = async (name: string) => {
    await user().click(screen.getByRole("tab", { name }));
    return screen.getByRole("tabpanel");
  };
  const prediction = (signal: "strong" | "weak" | "insufficient") => ({ ...CIVIL_REPORT.prediction, signal });

  describe("分頁", () => {
    it("五個分頁，預設整體結果；解說員的話每個分頁都一樣", async () => {
      const { calls } = await show();
      expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["整體結果", "可能的金額", "相似判決", "證據對照", "對方的說法"]);
      expect(screen.getByRole("tab", { name: "整體結果" })).toHaveAttribute("aria-selected", "true");
      const scene = screen.getByRole("region", { name: "CasEY 角色說明" });
      expect(scene).toHaveTextContent("你可以參考模型給出的結果，也可以在相似判決中查找前10件最相似的判決書資訊，並參考導讀內容。");
      await openTab("對方的說法");
      expect(scene).toHaveTextContent("你可以參考模型給出的結果，也可以在相似判決中查找前10件最相似的判決書資訊，並參考導讀內容。");
      expect(screen.getByText(/比對了 30 件案由相同的真實判決/)).toBeInTheDocument();
      expect(calls[0].body).toMatchObject({ text: TRAFFIC, mid: "侵權：交通事故", claimed_amount: 500000, evidence: ["medical"] });
    });

    it("網址可以直接開某個分頁", async () => {
      await show({}, "/result/civil?tab=amount");
      expect(screen.getByRole("tab", { name: "可能的金額" })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("tabpanel")).toHaveTextContent("可能判准的金額");
    });

    it("沒看的分頁也在頁面上，列印時全部印出來", async () => {
      await show();
      expect(screen.getAllByRole("tabpanel", { hidden: true })).toHaveLength(5);
      expect(screen.getByRole("tablist")).toHaveClass("no-print");
    });

    it("手機上選中的頁籤在畫面外時，只把頁籤列橫向捲過去", async () => {
      // jsdom 沒有版面：頁籤每個寬 110、間隔 120，頁籤列只看得到 300
      const tabIndex = (el: HTMLElement) => [...(el.parentElement?.querySelectorAll('[role="tab"]') ?? [])].indexOf(el);
      vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (this: HTMLElement) { return Math.max(0, tabIndex(this)) * 120; });
      vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function (this: HTMLElement) { return this.getAttribute("role") === "tab" ? 110 : 0; });
      vi.spyOn(Element.prototype, "clientWidth", "get").mockImplementation(function (this: Element) { return this.getAttribute("role") === "tablist" ? 300 : 0; });
      const scrollTo = vi.fn();
      Element.prototype.scrollTo = scrollTo;
      try {
        // 從判決導讀回來（?tab=cases）：第一次就捲，不用動畫
        await show({}, "/result/civil?tab=cases");
        expect(scrollTo).toHaveBeenCalledWith({ left: 350 - 300 + 16, behavior: "auto" });   // 相似判決是第 3 個：240 + 110
        expect(scrollTo.mock.contexts[0]).toBe(screen.getByRole("tablist"));
        scrollTo.mockClear();
        await user().click(screen.getByRole("tab", { name: "整體結果" }));
        expect(scrollTo).not.toHaveBeenCalled();     // 已經在畫面內
        await user().click(screen.getByRole("tab", { name: "對方的說法" }));
        expect(scrollTo).toHaveBeenCalledWith({ left: 590 - 300 + 16, behavior: "smooth" });   // 對方的說法是第 5 個：480 + 110
      } finally {
        vi.restoreAllMocks();
        delete (Element.prototype as Partial<Element>).scrollTo;
      }
    });
  });

  describe("整體結果", () => {
    it("最上面是模型判定：機率，並說明只是參考；模型怎麼算放在說明頁；相似判決在後面當對照", async () => {
      await show();
      const verdict = screen.getByRole("region", { name: "模型判定" });
      expect(within(verdict).getByText("62%")).toBeInTheDocument();
      expect(verdict).toHaveTextContent("這是模型以過去判決來預估的數值，請當作參考；通常來說口語描述會降低模型判定的準確性，因此會比較分不出輸贏。");
      expect(verdict).toHaveTextContent("對模型如何處理感到好奇？點擊可以參考");
      expect(within(verdict).getByRole("link", { name: /勝敗模型怎麼算的說明/, hidden: true })).toHaveAttribute("href", `/guide#${encodeURIComponent("勝敗模型怎麼算")}`);
      expect(verdict).not.toHaveTextContent("測試成績");
      expect(verdict).not.toHaveTextContent("金額模型");
      expect(screen.getByText("62%").closest("details")).toBeNull();
      const outcome = screen.getByRole("img", { name: "全部勝訴 8 件、一部勝訴 13 件、敗訴 9 件" });
      expect(verdict.compareDocumentPosition(outcome) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("系統代選糾紛類型的提醒只把類型加粗", async () => {
      const warning = "未選擇或選擇多個糾紛類型時，系統判斷比較接近 侵權：交通事故。若你認為有誤，請手動選擇最接近的糾紛類型。";
      await show({ prediction: { ...CIVIL_REPORT.prediction, warnings: [warning] }, search_scope: { n: 9156, mid: "侵權：交通事故", mid_inferred: true } });
      const verdict = screen.getByRole("region", { name: "模型判定" });
      expect(verdict).toHaveTextContent(warning);
      expect(within(verdict).getByText("侵權：交通事故").tagName).toBe("B");
    });

    it("相似的勝訴判決裡有幾件是全部勝訴，列在整體結果", async () => {
      await show({ amount_range: { ...CIVIL_REPORT.amount_range!, n_wins: 21, n_full_wins: 17 } });
      expect(screen.getByText(/相似的勝訴判決 21 件中，/).closest("li")).toHaveTextContent("相似的勝訴判決 21 件中，17 件是全部勝訴");
    });

    it.each([
      ["strong", "參考訊號：較強", "勝訴機會較高"],
      ["weak", "參考訊號：較弱", "勝訴機會較低"],
      ["insufficient", "參考訊號：資訊不足", "描述太短"],
    ] as const)("參考訊號 %s 用固定文字", async (signal, title, text) => {
      await show({ prediction: prediction(signal) });
      expect(screen.getByText(title)).toBeInTheDocument();
      expect(screen.getByText(new RegExp(text))).toBeInTheDocument();
    });

    it("資訊不足時不說強弱", async () => {
      await show({ prediction: prediction("insufficient") });
      expect(screen.queryByText(/勝訴機會較(高|低)/)).not.toBeInTheDocument();
    });

    it("相似判決太少時不畫比例，說明原因", async () => {
      await show({ outcomes: { total: 6, win: 3, partial: 2, lose: 1 } });
      expect(screen.getByText("有被告答辯的相似判決不多（只找到 6 件）")).toBeInTheDocument();
      expect(screen.queryByRole("img", { name: /全部勝訴/ })).not.toBeInTheDocument();
    });

    it("0 件的結果不畫，但圖例還在", async () => {
      await show({ outcomes: { total: 30, win: 0, partial: 30, lose: 0 } });
      expect(screen.getByRole("img", { name: "全部勝訴 0 件、一部勝訴 30 件、敗訴 0 件" })).toBeInTheDocument();
      expect(screen.getByText("全部勝訴").parentElement).toHaveTextContent("0 件");
    });

    it("相似判決和模型不一致時提醒看判決；一致時不提醒", async () => {
      await show({ prediction: prediction("weak"), outcomes: { total: 30, win: 15, partial: 9, lose: 6 } });
      expect(screen.getByText(/不完全一致/)).toBeInTheDocument();
    });

    it("一致時不提醒", async () => {
      await show();
      expect(screen.queryByText(/不完全一致/)).not.toBeInTheDocument();
    });

    it("被告未到庭的件數另外說明；沒有就不顯示", async () => {
      await show({ default_cases: 12 });
      expect(screen.getByText(/有 12 件被告沒有到庭/)).toBeInTheDocument();
    });

    it("沒有被告未到庭時不顯示", async () => {
      await show();
      expect(screen.queryByText(/件被告沒有到庭/)).not.toBeInTheDocument();
    });

  });

  describe("可能的金額", () => {
    const model: Range = { ...CIVIL_REPORT.amount_range!, source: "model", scope: "partial_win", buckets: [{ low: 0, high: 0.2, count: 3 }] };
    const amount = async (range: Range | null) => {
      await show({ amount_range: range });
      return openTab("可能的金額");
    };

    it("相似判決（舊版後端沒有 source 也一樣）：寫「如果勝訴」與件數，實線範圍條", async () => {
      const panel = await amount(CIVIL_REPORT.amount_range);
      expect(within(panel).getByRole("heading", { name: "如果勝訴，可能判准的金額" })).toBeInTheDocument();
      expect(panel).toHaveTextContent("來源：相似判決");
      expect(panel).toHaveTextContent("180,000 ～ 420,000 元");
      expect(panel).toHaveTextContent("你請求 500,000 元");
      expect(panel).toHaveTextContent("依 18 件相似的勝訴判決");
      expect(within(panel).getByRole("group", { name: /金額範圍：180,000 元到 420,000 元，中位數 300,000 元/ })).toBeInTheDocument();
    });

    it("模型：標明「若為一部勝訴」，不說依幾件相似判決，並提醒範圍很寬", async () => {
      const panel = await amount(model);
      expect(within(panel).getByRole("heading", { name: "如果判決是「一部勝訴」，可能判准的金額" })).toBeInTheDocument();
      expect(panel).toHaveTextContent("來源：模型推估");
      expect(panel).toHaveTextContent("用過去的一部勝訴判決測試，10 件約有 8 件落在這個範圍");
      expect(panel).toHaveTextContent("很寬");
      expect(panel).toHaveTextContent("如果判決是全部勝訴，通常就是請求的全部金額");
      expect(panel).not.toHaveTextContent("件相似的勝訴判決）");
    });

    it("沒填請求金額時只給比例，並說明可以回去填", async () => {
      const panel = await amount({ ...model, claimed: null, amount_low: null, amount_median: null, amount_high: null });
      expect(within(panel).getByRole("heading", { name: "如果判決是「一部勝訴」，可能判准的比例" })).toBeInTheDocument();
      expect(panel).toHaveTextContent("沒有填請求金額");
      expect(panel).toHaveTextContent("請求金額的 36%～84%");
      expect(within(panel).getByRole("link", { name: "回上一步填寫想請求的金額" })).toHaveAttribute("href", "/start?stage=3");
    });

    it("相似的勝訴判決不夠時不給金額", async () => {
      const panel = await amount(null);
      expect(panel).toHaveTextContent("無法估出金額範圍");
    });

    it("各範圍的件數；模型時說明那是對照", async () => {
      const panel = await amount({ ...model, buckets: [{ low: 0, high: 0.2, count: 3 }, { low: 0.2, high: 0.4, count: 7 }] });
      expect(within(panel).getByText("看各金額範圍有幾件")).toBeInTheDocument();
      expect(within(panel).getByText("20–40%")).toBeInTheDocument();
      expect(within(panel).getByText("7 件")).toBeInTheDocument();
      expect(panel).toHaveTextContent("上面的範圍是模型推估的");
    });

    it("全部勝訴的件數移到整體結果；金額模型沒用時在這裡說明", async () => {
      const panel = await amount({ ...CIVIL_REPORT.amount_range!, n_wins: 21, n_full_wins: 17 });
      expect(panel).not.toHaveTextContent("件是全部勝訴");
      expect(panel).toHaveTextContent("金額模型：要選一個糾紛類型，並填法院或請求金額才會使用；這次改用相似判決的判准比例。");
    });

    it("用了金額模型時不再說明金額模型的條件", async () => {
      const panel = await amount(model);
      expect(panel).not.toHaveTextContent("才會使用");
    });

    it("有標註金額斟酌的相似判決：列出法院怎麼決定金額的原文，連到判決導讀", async () => {
      const [first, second] = CIVIL_REPORT.similar;
      const dam = { label: "DAM", polarity: "酌減", quote: "審酌〔略〕為適當", text: "審酌原告傷勢等一切情狀，認慰撫金以十萬元為適當" };
      await show({ similar: [{ ...first, reasoning: [dam] }, { ...second, reasoning: [{ ...dam, label: "SUB" }] }] });
      const panel = await openTab("可能的金額");
      const section = within(panel).getByRole("region", { name: "相似判決的法院怎麼決定金額" });
      expect(section).toHaveTextContent("1 件相似判決");
      expect(section).toHaveTextContent("「審酌⋯⋯為適當」");                    // 先顯示引文（保留結尾的金額）
      await userEvent.setup().click(within(section).getByRole("button", { name: "看完整原文" }));
      expect(section).toHaveTextContent("「審酌原告傷勢等一切情狀，認慰撫金以十萬元為適當」");
      expect(section).toHaveTextContent("酌減");
      expect(section).toHaveTextContent("判准 310,000 ／ 請求 480,000 元");
      expect(section).not.toHaveTextContent(second.case_number);
      expect(within(section).getByRole("link", { name: `${first.case_number} 判決導讀` })).toHaveAttribute("href", "/judgment/civil/11");
      expect(within(section).getByRole("link", { name: /酌減的說明/ }).getAttribute("href")).toBe(`/guide#${encodeURIComponent("酌減")}`);
    });

    it("法院怎麼決定金額：慰撫金排前面、每件最多 2 處，超過 5 件先收起", async () => {
      const [first] = CIVIL_REPORT.similar;
      const q = (text: string) => ({ label: "DAM", polarity: "酌減", quote: text, text });
      const similar = Array.from({ length: 7 }, (_, i) => ({ ...first, case_id: 100 + i, case_number: `判決${i + 1}號`,
        reasoning: [q("機車修理費折舊後為710元"), q("看護費以每日2,500元計算"), q("慰撫金以3萬元為適當")] }));
      await show({ similar });
      const user = userEvent.setup();
      const panel = await openTab("可能的金額");
      const section = within(panel).getByRole("region", { name: "相似判決的法院怎麼決定金額" });
      const cards = () => within(section).getAllByRole("link", { name: /判決導讀/ });
      expect(cards()).toHaveLength(5);
      const firstCard = section.querySelector("li")!;
      expect(firstCard.textContent!.indexOf("慰撫金")).toBeLessThan(firstCard.textContent!.indexOf("機車修理費"));
      expect(firstCard).not.toHaveTextContent("看護費");
      expect(firstCard).toHaveTextContent("還有 1 處");
      await user.click(within(section).getByRole("button", { name: "顯示其他 2 件" }));
      expect(cards()).toHaveLength(7);
      await user.click(within(section).getByRole("button", { name: "收起" }));
      expect(cards()).toHaveLength(5);
    });

    it("沒有標註時不顯示法院怎麼決定金額", async () => {
      const panel = await amount(CIVIL_REPORT.amount_range);
      expect(within(panel).queryByRole("region", { name: "相似判決的法院怎麼決定金額" })).not.toBeInTheDocument();
    });

    it("模型：相似的勝訴判決不夠時仍給範圍，只是沒有分布可看", async () => {
      const panel = await amount({ ...model, n_cases: null, buckets: [] });
      expect(panel).toHaveTextContent("180,000 ～ 420,000 元");
      expect(within(panel).queryByText("看各金額範圍有幾件")).not.toBeInTheDocument();
      expect(panel).not.toHaveTextContent("無法估出金額範圍");
    });
  });

  it("證據對照：比例與你有沒有提到", async () => {
    await show();
    const panel = await openTab("證據對照");
    expect(within(panel).getByText("你有提到")).toBeInTheDocument();
    expect(within(panel).getByText("你沒有提到").closest("span")).toHaveClass("text-ink-faint");
    expect(panel).toHaveTextContent("以相似的勝訴判決中，統計了這項證據出現的案件比例。");
    expect(panel).not.toHaveTextContent("沒提到不代表會輸");
    expect(within(panel).getByRole("img", { name: "診斷證明、病歷：82% 的相似勝訴判決有提到" })).toBeInTheDocument();
  });

  it("沒有證據資料時說明原因", async () => {
    await show({ evidence: [] });
    expect(await openTab("證據對照")).toHaveTextContent("沒有可以對照的證據資料");
  });

  it("對方的說法：名稱與出現比例", async () => {
    await show();
    const panel = await openTab("對方的說法");
    expect(within(panel).getByText("你也有過失（與有過失）")).toBeInTheDocument();
    expect(within(panel).getByText("46%")).toBeInTheDocument();
  });

  it("與有過失的抗辯連到說明頁", async () => {
    await show();
    const panel = await openTab("對方的說法");
    expect(within(panel).getByRole("link", { name: "什麼是「與有過失」？" })).toHaveAttribute("href", `/guide#${encodeURIComponent("與有過失")}`);
  });

  describe("相似判決", () => {
    it("表格、說明連結與判決導讀；不顯示相似度數字", async () => {
      await show();
      const panel = await openTab("相似判決");
      const table = within(panel).getByRole("table");
      expect(within(table).getByText("臺灣臺北地方法院 113 年度訴字第 1 號")).toBeInTheDocument();
      expect(within(table).getByText("310,000")).toBeInTheDocument();
      expect(within(table).getAllByRole("link", { name: "判決導讀" })[0]).toHaveAttribute("href", "/judgment/civil/11");
      expect(within(panel).getByRole("link", { name: /相似判決怎麼找的說明/ }).getAttribute("href")).toBe(`/guide#${encodeURIComponent("相似判決怎麼找")}`);
      expect(within(table).queryByRole("columnheader", { name: /相似度/ })).not.toBeInTheDocument();
      expect(table).not.toHaveTextContent(String(CIVIL_REPORT.similar[0].similarity));
    });

    it("手機上表格改排成卡片：欄名用 data-label，不加進文字", async () => {
      await show();
      const table = within(await openTab("相似判決")).getByRole("table");
      expect(table).toHaveClass("table-stack");
      const cells = within(within(table).getAllByRole("row")[1]).getAllByRole("cell");
      expect(cells.map((c) => c.getAttribute("data-label"))).toEqual([null, "結果", "判准／請求（元）", null]);
      expect(table.querySelector("tbody")).not.toHaveTextContent("判准／請求（元）");
    });

    it("沒有限定類型時：標題不帶類型，旁邊寫檢索範圍共幾件", async () => {
      await show({ n_corpus: 188334, search_scope: { n: 188334, mid: null } });
      const panel = await openTab("相似判決");
      expect(within(panel).getByRole("heading", { level: 2, name: "相似的真實判決" })).toBeInTheDocument();
      expect(panel).toHaveTextContent("共 188,334 件");
      expect(panel).not.toHaveTextContent("越上面越接近");
      expect(panel).not.toHaveTextContent("%");
    });

    it("限定類型時：標題帶系統判斷的糾紛類型", async () => {
      await show({ search_scope: { n: 9156, mid: "侵權：交通事故", mid_inferred: true } });
      const panel = await openTab("相似判決");
      expect(within(panel).getByRole("heading", { level: 2, name: "相似的真實判決——侵權：交通事故" })).toBeInTheDocument();
      expect(panel).toHaveTextContent("共 9,156 件");
    });

    it("每件判決下面列出相同點；沒有就不顯示", async () => {
      const [first, second] = CIVIL_REPORT.similar;
      await show({ similar: [{ ...first, common: ["請求金額相近（你 30 萬／這件 28 萬）", "同一法院"] }, { ...second, common: [] }] });
      const table = within(await openTab("相似判決")).getByRole("table");
      const rows = within(table).getAllByRole("row").slice(1);
      // 相同的地方直接列標籤，不加「相同點」前綴
      expect(rows[0]).toHaveTextContent("請求金額相近（你 30 萬／這件 28 萬）同一法院");
      expect(rows[0]).not.toHaveTextContent("相同點");
      expect(rows[1]).not.toHaveTextContent("同一法院");
    });

    it("有標註的判決下面顯示法院怎麼認定：結論方向與一句原文（金額優先，EV 不放摘要）", async () => {
      const [first, second] = CIVIL_REPORT.similar;
      const q = (label: string, text: string, polarity: string | null = null) => ({ label, polarity, quote: text, text });
      await show({ similar: [
        { ...first, reasoning: [q("CONCL", "一部有理由之結論", "一部有理由"), q("CONCL", "其餘無理由", "無理由"),
          q("EV", "證人證述堪信為真實", "有利原告"), q("SUB", "被告有過失"), q("DAM", "慰撫金以十萬元為適當", "酌減")] },
        { ...second, reasoning: [q("EV", "證人證述堪信為真實", "有利原告")] },
      ] });
      const panel = await openTab("相似判決");
      const rows = within(within(panel).getByRole("table")).getAllByRole("row").slice(1);
      expect(rows[0]).toHaveTextContent("法院怎麼認定一部有理由無理由");
      expect(rows[0]).toHaveTextContent("金額怎麼決定：「慰撫金以十萬元為適當」");
      expect(rows[0]).not.toHaveTextContent("堪信為真實");
      expect(rows[1]).not.toHaveTextContent("法院怎麼認定");     // 只有 EV → 摘要沒有可顯示的
      expect(panel).toHaveTextContent("由 AI 依標註手冊標註、人工抽查");
      expect(within(rows[0]).getByRole("link", { name: /有理由、一部有理由、無理由的說明/ }).getAttribute("href"))
        .toBe(`/guide#${encodeURIComponent("有理由、一部有理由、無理由")}`);
      expect(within(panel).getByRole("link", { name: /^法院怎麼認定的說明/ }).getAttribute("href"))
        .toBe(`/guide#${encodeURIComponent("法院怎麼認定")}`);
    });

    it("法院怎麼認定：結論方向固定順序，金額摘要優先挑慰撫金", async () => {
      const [first] = CIVIL_REPORT.similar;
      const q = (label: string, text: string, polarity: string | null = null) => ({ label, polarity, quote: text, text });
      await show({ similar: [{ ...first, reasoning: [q("CONCL", "其餘無理由", "無理由"), q("CONCL", "部分准許", "一部有理由"),
        q("CONCL", "此部分准許", "有理由"), q("DAM", "機車修理費折舊後為710元", "酌減"), q("DAM", "請求227,400元尚屬過高，應以33,045元為宜", "酌減")] }] });
      const panel = await openTab("相似判決");
      const row = within(within(panel).getByRole("table")).getAllByRole("row")[1];
      expect(row).toHaveTextContent("法院怎麼認定有理由一部有理由無理由");
      expect(row).toHaveTextContent("金額怎麼決定：「請求227,400元尚屬過高，應以33,045元為宜」");   // 沒寫「慰撫金」也算
    });

    it("沒有標註時不顯示法院怎麼認定", async () => {
      await show();
      const panel = await openTab("相似判決");
      expect(panel).not.toHaveTextContent("法院怎麼認定");
    });

    it("相似判決沒有請求金額時，判准金額照樣顯示", async () => {
      const [first, second] = CIVIL_REPORT.similar;
      await show({ similar: [{ ...first, claimed_amount: null, awarded_amount: 14540 }, { ...second, claimed_amount: null, awarded_amount: null }] });
      const rows = within(within(await openTab("相似判決")).getByRole("table")).getAllByRole("row").slice(1);
      expect(rows[0]).toHaveTextContent("14,540 ／ —");
      expect(rows[1]).not.toHaveTextContent("／");
    });

    it("示例資料不說語料件數", async () => {
      await show({ mock: true, n_corpus: 158330, search_scope: { n: 158330, mid: null } });
      expect(await openTab("相似判決")).not.toHaveTextContent("158,330");
    });

    it("有司法院網址時，判決導讀旁邊附原文連結；沒有就不顯示", async () => {
      const url = "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDV";
      const [first, ...rest] = CIVIL_REPORT.similar;
      await show({ similar: [{ ...first, url }, ...rest.map((c) => ({ ...c, url: null }))] });
      const table = within(await openTab("相似判決")).getByRole("table");
      const links = within(table).getAllByRole("link", { name: /判決原文/ });
      expect(links).toHaveLength(1);
      expect(links[0]).toHaveAttribute("href", url);
      expect(links[0]).toHaveAttribute("target", "_blank");
      expect(within(table).getAllByRole("link", { name: "判決導讀" })).toHaveLength(CIVIL_REPORT.similar.length);
    });

    it("只看原告勝訴的：畫面上收起來，但列印時還印得出來", async () => {
      await show();
      const panel = await openTab("相似判決");
      const table = within(panel).getByRole("table");
      expect(within(table).getAllByRole("row")).toHaveLength(3);
      await user().click(within(panel).getByRole("switch", { name: "只看原告勝訴的" }));
      expect(table.querySelectorAll("tbody tr.screen-hidden")).toHaveLength(1);
    });

    it("一造辯論的判決標示被告未到庭，並說明不計入統計", async () => {
      const [first, ...rest] = CIVIL_REPORT.similar;
      await show({ similar: [{ ...first, default_judgment: true }, ...rest] });
      const panel = await openTab("相似判決");
      expect(within(within(panel).getAllByRole("row")[1]).getByText("被告未到庭")).toBeInTheDocument();
      const note = within(panel).getByText(/統計不包含這些判決/);
      expect(note).toHaveTextContent("「被告未到庭」的判決沒有經過雙方攻防，原告幾乎都會贏（僅作參考）。金額範圍、證據與抗辯的統計不包含這些判決。");
      // 最左邊是說明連結
      expect(note.parentElement!.firstElementChild).toHaveAttribute("href", `/guide#${encodeURIComponent("被告未到庭（一造辯論）")}`);
    });

    it("沒有一造辯論的判決就不顯示說明", async () => {
      await show();
      const panel = await openTab("相似判決");
      expect(within(panel).queryByText("被告未到庭")).not.toBeInTheDocument();
      expect(within(panel).queryByText(/統計不包含這些判決/)).not.toBeInTheDocument();
    });
  });

  it("示例資料：頁面上方、每個分頁、PDF 頁尾都標；下載 PDF 會開啟列印", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    await show({ mock: true });
    expect(screen.getByText("這一頁是示例資料")).toBeInTheDocument();
    expect(screen.getAllByText("示例資料").length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText("※ 示例資料，不是真實的查詢結果。").closest(".print-only")).not.toBeNull();
    expect(screen.getByText(/本報告是示例資料/).closest(".print-only")).not.toBeNull();
    await user().click(screen.getByRole("button", { name: "下載 PDF" }));
    expect(print).toHaveBeenCalledOnce();
  });

  it("不是示例資料時不標", async () => {
    await show();
    expect(screen.queryByText(/示例資料/)).not.toBeInTheDocument();
  });

  it("手機上下載 PDF 是標題旁的圖示按鈕，分頁列上不再放", async () => {
    window.matchMedia = vi.fn((q: string) => ({
      matches: q.includes("40rem"), media: q, addEventListener: () => {}, removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia;
    try {
      const print = vi.spyOn(window, "print").mockImplementation(() => {});
      await show();
      const pdf = screen.getByRole("button", { name: "下載 PDF" });
      expect(pdf.parentElement).toContainElement(screen.getByRole("heading", { level: 1, name: /^民事參考結果/ }));
      expect(screen.getByRole("tablist").parentElement).not.toContainElement(pdf);
      await user().click(pdf);
      expect(print).toHaveBeenCalledOnce();
    } finally {
      delete (window as { matchMedia?: unknown }).matchMedia;
    }
  });

  it("頁尾沒有「請注意」，列印時直接印出條列", async () => {
    await show();
    expect(screen.queryByRole("button", { name: "請注意" })).not.toBeInTheDocument();
    const printed = screen.getByRole("heading", { name: "請注意" }).closest(".print-only")!;
    expect(printed).toHaveTextContent("不是法律意見");
    expect(printed).toHaveTextContent("和解、撤回");
  });

  it("錯誤時提示重新載入，可以重試", async () => {
    mockApi({ "POST /civil/report": { status: 500 } });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("伺服器發生錯誤");
    expect(alert).toHaveTextContent("請重新載入結果");
    expect(within(alert).getByRole("button", { name: "再試一次" })).toBeInTheDocument();
  });

  it("載入中顯示骨架和說明", () => {
    mockApi({ "POST /civil/report": () => new Promise(() => {}) });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    expect(screen.getByText("正在比對相似判決…")).toBeInTheDocument();
  });

  it("沒有內容就回到第一步", () => {
    renderApp("/result/civil");
    expect(screen.getByRole("heading", { name: /選擇案件類型/ })).toBeInTheDocument();
  });
});

describe("刑事結果", () => {
  const intake = { caseType: "criminal" as const, text: "x", maskedText: "開車撞到人" };
  const show = async (over: Partial<typeof CRIMINAL_REPORT> = {}, extra: Partial<typeof intake & { searchText: string }> = {}, route = "/result/criminal") => {
    const api = mockApi({ "POST /criminal/predict": () => ({ ...CRIMINAL_REPORT, ...over }) });
    renderAt("/result/criminal", <CriminalResult />, route, { ...intake, ...extra });
    await screen.findByRole("tab", { name: "可能的罪名" });
    return api;
  };
  const openTab = async (name: string) => {
    await userEvent.setup().click(screen.getByRole("tab", { name }));
    return screen.getByRole("tabpanel");
  };

  it("三個分頁；解說員的話和民事一樣；刑期範圍也可以切換罪名", async () => {
    await show({ mock: false });
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["可能的罪名", "刑期範圍", "相似判決"]);
    const scene = screen.getByRole("region", { name: "CasEY 角色說明" });
    expect(scene).toHaveTextContent("你可以參考模型給出的結果，也可以在相似判決中查找前10件最相似的判決書資訊，並參考導讀內容。");
    const panel = await openTab("刑期範圍");
    const [, second] = CRIMINAL_REPORT.charges;
    await userEvent.setup().click(within(panel).getByRole("button", { name: second.name }));
    expect(within(panel).getByRole("heading", { name: `刑期範圍：${second.name}` }).closest("section")).not.toHaveClass("screen-hidden");
    expect(panel).toHaveTextContent("模型推估的是整個案件的刑度，切換罪名時這一組不會變；實際刑期還是會依其他因素而不同。");
    expect(screen.getAllByRole("tabpanel", { hidden: true })).toHaveLength(3);
  });

  it("可能的罪名：模型判定整個框起來，罪名直接列名稱、法條和機率條（50% 畫線），不用選", async () => {
    await show();
    const verdict = screen.getByRole("region", { name: "模型判定" });
    expect(within(verdict).getByRole("heading", { name: "可能的罪名" })).toBeInTheDocument();
    expect(within(verdict).queryByRole("radio")).not.toBeInTheDocument();
    for (const c of CRIMINAL_REPORT.charges) {
      expect(within(verdict).getByText(c.name)).toBeInTheDocument();
      expect(within(verdict).getByRole("img", { name: new RegExp(`^${c.name}：.*門檻是 50%`) })).toBeInTheDocument();
    }
  });

  it("刑期範圍分頁可以切換罪名；列印時每個罪名都印", async () => {
    await show();
    const user = userEvent.setup();
    const panel = await openTab("刑期範圍");
    await user.click(within(panel).getByRole("button", { name: "肇事逃逸罪" }));
    const section = (name: string) => within(panel).getByText(name).closest("section");
    expect(section("刑期範圍：肇事逃逸罪")).not.toHaveClass("screen-hidden");
    expect(section("刑期範圍：過失傷害罪")).toHaveClass("screen-hidden");
    expect(within(panel).getByText("98%")).toBeInTheDocument();
    expect(within(panel).queryByText("可能的刑期範圍（有期徒刑）")).not.toBeInTheDocument();
  });

  it("說明罪名機率是分開估的", async () => {
    await show();
    expect(screen.getByText(/加起來不一定是 100%/)).toBeInTheDocument();
  });

  it("有確認過的整理文字時，用它推估，並說明可以回第 6 關改用原文", async () => {
    const { calls } = await show({ mock: false }, { maskedText: "他打我", searchText: "被告徒手毆打被害人" });
    expect(screen.getByText(/這次比對用的是：整理成判決書寫法的文字/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回第 6 關" })).toHaveAttribute("href", "/confirm?stage=6");
    expect(calls[0].body).toEqual({ text: "被告徒手毆打被害人" });
  });

  it("沒有整理時說明用的是原本的描述", async () => {
    await show({ mock: false });
    expect(screen.getByText(/這次比對用的是：你原本的描述/)).toBeInTheDocument();
  });

  it("示例資料要標示；真的模型就不標", async () => {
    await show({ mock: true });
    expect(screen.getByText("這一頁是示例資料")).toBeInTheDocument();
    expect(screen.getAllByText("示例資料").length).toBeGreaterThanOrEqual(3);
  });

  it("每個罪名各一組相似判決，在相似判決分頁切換", async () => {
    const [hurt, flee] = CRIMINAL_REPORT.charges;
    const base = CRIMINAL_REPORT.similar[0];
    const charges = [
      { ...hurt, similar: [{ ...base, case_id: 1, case_number: "過失傷害的判決" }], search_scope: { n: 3200, charge: hurt.name } },
      { ...flee, similar: [{ ...base, case_id: 2, case_number: "肇事逃逸的判決" }], search_scope: { n: 410, charge: flee.name } },
    ];
    await show({ mock: false, charges, similar: charges[0].similar, search_scope: charges[0].search_scope });
    const user = userEvent.setup();
    const panel = await openTab("相似判決");
    await user.click(within(panel).getByRole("button", { name: "肇事逃逸罪" }));
    const fleeSection = within(panel).getByRole("region", { name: "肇事逃逸罪的相似判決" });
    const hurtSection = within(panel).getByRole("region", { name: "過失傷害罪的相似判決" });
    expect(fleeSection).not.toHaveClass("screen-hidden");
    expect(hurtSection).toHaveClass("screen-hidden");
    // 只放這個罪名檢索範圍的總數（在罪名切換同一列最右邊）
    expect(panel).toHaveTextContent("共 410 件");
    expect(fleeSection).toHaveTextContent("肇事逃逸的判決");
    expect(within(panel).getByRole("button", { name: "肇事逃逸罪" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(panel).getByRole("button", { name: "過失傷害罪" }));
    expect(hurtSection).not.toHaveClass("screen-hidden");
    expect(fleeSection).toHaveClass("screen-hidden");
    expect(panel).toHaveTextContent("共 3,200 件");
  });

  it("後端沒有分罪名的相似判決時，不顯示切換，用頂層的那組", async () => {
    await show({ mock: false });
    const panel = await openTab("相似判決");
    expect(within(panel).queryByRole("group", { name: "看哪個罪名的相似判決" })).not.toBeInTheDocument();
    expect(within(panel).getByRole("table")).toHaveTextContent(CRIMINAL_REPORT.similar[0].case_number);
  });

  it("只有一個罪名時不顯示切換提示", async () => {
    await show({ mock: false, charges: [CRIMINAL_REPORT.charges[0]] });
    expect(screen.queryByText(/點一個罪名/)).not.toBeInTheDocument();
  });

  it("真的模型不標示例", async () => {
    await show({ mock: false });
    expect(screen.queryByText(/示例資料/)).not.toBeInTheDocument();
  });

  it("修法提示、模型推估與實際宣告刑並列、模型測試結果", async () => {
    const [first, ...rest] = CRIMINAL_REPORT.charges;
    await show({ mock: false,
      charges: [{ ...first, law_note: "修法前為洗錢防制法第 14 條", n_similar: 50,
        similar_sentence: [{ label: "拘役、罰金", share: 0.2 }, { label: "1～6 個月", share: 0.8 }] }, ...rest],
      model: { name: "criminal_v1", description: "TF-IDF ＋ SVM", n_test: 10000, charge_top1: 0.93, bucket_accuracy: 0.7, bucket_within_one: 0.95 } });
    expect(screen.getByText("修法前為洗錢防制法第 14 條")).toBeInTheDocument();
    // 模型與測試成績不在結果頁顯示
    expect(screen.queryByText(/第一個罪名猜中/)).not.toBeInTheDocument();
    const panel = await openTab("刑期範圍");
    expect(panel).toHaveTextContent("最相似的 50 件「過失傷害罪」有罪判決，實際宣告刑多數落在「1～6 個月」");
    expect(within(panel).getByText("最相似 50 件的實際宣告刑")).toBeInTheDocument();
    expect(within(panel).getByText("實際 80%")).toBeInTheDocument();
    expect(within(panel).getByRole("img", { name: "1～6 個月：模型推估 62%，最相似 50 件實際宣告刑 80%" })).toBeInTheDocument();
  });

  it("手機上相似判決表格改排成卡片：罪名、應執行刑用 data-label", async () => {
    await show();
    const table = within(await openTab("相似判決")).getByRole("table");
    expect(table).toHaveClass("table-stack");
    const cells = within(within(table).getAllByRole("row")[1]).getAllByRole("cell");
    expect(cells.map((c) => c.getAttribute("data-label"))).toEqual([null, "罪名", "應執行刑", null]);
  });

  it("真模型沒有相似判決時說明，不出現表格", async () => {
    await show({ similar: [], mock: false });
    const panel = await openTab("相似判決");
    expect(within(panel).getByText("刑事相似判決檢索尚未開放")).toBeInTheDocument();
    expect(within(panel).queryByRole("table")).not.toBeInTheDocument();
  });

  it("真的刑事判決同時提供導讀與司法院原文", async () => {
    const url = "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDM";
    await show({ mock: false, similar: [{ ...CRIMINAL_REPORT.similar[0], url }] });
    const panel = await openTab("相似判決");
    // 整個字號就是原文連結
    expect(within(panel).getByRole("link", { name: /司法院判決原文/ })).toHaveAttribute("href", url);
    expect(within(panel).queryByRole("link", { name: "判決原文" })).not.toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "判決導讀" })).toHaveAttribute("href", `/judgment/criminal/${CRIMINAL_REPORT.similar[0].case_id}`);
    expect(within(panel).queryByRole("columnheader", { name: /相似度/ })).not.toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: /相似判決怎麼找的說明/ })).toBeInTheDocument();
  });

  it("刑事相似判決說明是從含哪個罪名的判決裡找的", async () => {
    await show({ mock: false, n_corpus: 88376, search_scope: { n: 12034, charge: "詐欺罪" }, similar: [CRIMINAL_REPORT.similar[0]] });
    const panel = await openTab("相似判決");
    expect(panel).toHaveTextContent("共 12,034 件");
    expect(panel).not.toHaveTextContent("找出和你的描述用字最接近");
    expect(panel).not.toHaveTextContent("相同點");
    expect(panel).not.toHaveTextContent("選了糾紛類型");
  });

  it("頁尾的請注意是刑事的條列", async () => {
    await show();
    const printed = screen.getByRole("heading", { name: "請注意" }).closest(".print-only")!;
    expect(printed).toHaveTextContent("檢察官不起訴");
    expect(printed).toHaveTextContent("告訴乃論");
  });

  it("看不出罪名時說明原因", async () => {
    mockApi({ "POST /criminal/predict": () => ({ ...CRIMINAL_REPORT, charges: [] }) });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", intake);
    expect(await screen.findByText("看不出可能的罪名")).toBeInTheDocument();
  });

  it("錯誤時提示重新載入，可以重試", async () => {
    mockApi({ "POST /criminal/predict": { status: 500 } });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", intake);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("請重新載入結果");
    expect(within(alert).getByRole("button", { name: "再試一次" })).toBeInTheDocument();
  });
});

describe("判決導讀", () => {
  it("五類預設都上色，可以關掉；每段都有文字標籤", async () => {
    const { calls } = mockApi({ "GET /judgments/civil/11/guide": () => GUIDE });
    const user = userEvent.setup();
    const { container } = renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    expect(await screen.findByRole("heading", { name: "臺灣臺北地方法院 113 年度訴字第 1 號" })).toBeInTheDocument();
    expect(calls[0].key).toBe("GET /judgments/civil/11/guide");
    const claim = container.querySelector(".para[data-fn=claim]")!;
    expect(claim).toHaveAttribute("data-on", "true");
    expect(claim).toHaveTextContent("原告主張");
    const toggle = screen.getByRole("button", { name: /原告主張/ });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(claim).toHaveAttribute("data-on", "false");
    expect(claim).toHaveTextContent("原告主張");   // 關掉也還有文字標籤
    expect(screen.getByText(/依文字規則標示/)).toBeInTheDocument();
  });

  it("基本資料、判准比例與回結果", async () => {
    mockApi({ "GET /judgments/civil/11/guide": () => GUIDE });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    await screen.findByRole("heading", { name: "判決資料" });
    expect(screen.getByText("一部勝訴")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "判准金額約占請求金額的 65%" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回結果" })).toHaveAttribute("href", "/result/civil?tab=cases");
    expect(screen.getByRole("region", { name: "CasEY 角色說明" })).toHaveTextContent("解說員");
  });

  it("請求金額沒抽到時，判准金額照樣顯示，並說明算不出比例", async () => {
    mockApi({ "GET /judgments/civil/11/guide": () => ({ ...GUIDE, case: { ...GUIDE.case, claimed_amount: null, awarded_amount: 14540 } }) });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    await screen.findByRole("heading", { name: "判決資料" });
    expect(screen.getByText("判准")).toBeInTheDocument();
    expect(screen.getByText("14,540 元")).toBeInTheDocument();
    expect(screen.getByText(/請求金額沒有抽取到/)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /判准金額約占請求金額/ })).not.toBeInTheDocument();
  });

  it("有原文網址時連到這件判決，沒有時連到司法院查詢系統", async () => {
    const url = "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDV";
    mockApi({ "GET /judgments/civil/11/guide": () => ({ ...GUIDE, case: { ...GUIDE.case, url } }) });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    // 原文連結是標題旁的圖示，頁面最下面不再另寫一行
    expect(await screen.findByRole("link", { name: /司法院判決原文/ })).toHaveAttribute("href", url);
    expect(screen.queryByText(/想看完整、正式的判決/)).not.toBeInTheDocument();
  });

  it("找不到判決", async () => {
    mockApi({});
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/999");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("沒有標註時不顯示「法院怎麼認定」", async () => {
    mockApi({ "GET /judgments/civil/11/guide": () => GUIDE });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    await screen.findByRole("heading", { name: "判決資料" });
    expect(screen.queryByRole("heading", { name: "法院怎麼認定" })).not.toBeInTheDocument();
  });

  it("法院怎麼認定：依標籤分組，點了捲到那一段並標出引文；沒抽查過的標籤不顯示", async () => {
    const reasoning = {
      labeler: "llm-p6.0", manual_version: "v0.6", items: [
        { label: "EV", polarity: "有利原告", basis: "明示評價", quote: "診斷證明書", paragraph: 2, start: 4, end: 9 },
        { label: "CONCL", polarity: "有理由", quote: "原告之請求有理由", paragraph: 3, start: 3, end: 11 },
        { label: "BOP", quote: "本件爭點為被告有無過失", paragraph: 1, start: 0, end: 11 },
        { label: "CONCL", polarity: "有理由", quote: "綜上〔略〕有理由", paragraph: 3, start: 0, end: 11 },
      ] };
    mockApi({ "GET /judgments/civil/11/guide": () => ({ ...GUIDE, reasoning }) });
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const user = userEvent.setup();
    const { container } = renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    const card = (await screen.findByRole("heading", { name: "法院怎麼認定" })).closest("[aria-labelledby=reasoning-title]")!;
    // 分組順序：結論在前；BOP 還沒抽查過，不顯示
    const groups = within(card as HTMLElement).getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(groups).toEqual(["法院的結論", "證據怎麼評價"]);
    expect(card).not.toHaveTextContent("本件爭點為被告有無過失");
    expect(card).toHaveTextContent("「綜上⋯⋯有理由」");          // 〔略〕顯示成刪節號
    expect(card).toHaveTextContent("請特別對照原文");             // EV 是 note
    expect(container.querySelector("mark")).toBeNull();
    expect(screen.queryByRole("button", { name: "回到法院怎麼認定" })).not.toBeInTheDocument();   // 還沒點過
    const ev = within(card as HTMLElement).getByRole("button", { name: /診斷證明書/ });
    await user.click(ev);
    expect(ev).toHaveAttribute("aria-pressed", "true");
    const mark = container.querySelector("#para-2 mark");
    expect(mark).toHaveTextContent("診斷證明書");
    expect(scroll).toHaveBeenCalled();
    // 換一項：舊的標示移除，只標新的那段
    await user.click(within(card as HTMLElement).getByRole("button", { name: /原告之請求有理由/ }));
    expect(container.querySelector("#para-2 mark")).toBeNull();
    expect(container.querySelector("#para-3 mark")).toHaveTextContent("原告之請求有理由");
    expect(ev).toHaveAttribute("aria-pressed", "false");
    // 點過一項之後，有回到卡片的按鈕（窄螢幕用；寬螢幕卡片黏在畫面上，按鈕用 CSS 藏起來）
    scroll.mockClear();
    await user.click(screen.getByRole("button", { name: "回到法院怎麼認定" }));
    expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  });

  it("法院怎麼認定：回到卡片後再點同一句，仍會捲到原文", async () => {
    const reasoning = { labeler: "llm-p6.0", manual_version: "v0.6", items: [
      { label: "CONCL", polarity: "有理由", quote: "原告之請求有理由", paragraph: 3, start: 3, end: 11 },
    ] };
    mockApi({ "GET /judgments/civil/11/guide": () => ({ ...GUIDE, reasoning }) });
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const user = userEvent.setup();
    const { container } = renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    const quote = await screen.findByRole("button", { name: /原告之請求有理由/ });
    await user.click(quote);
    await user.click(quote);
    const toPara = scroll.mock.contexts.filter((el) => el === container.querySelector("#para-3"));
    expect(toPara).toHaveLength(2);
  });

  it("手機捷徑：有法院怎麼認定時，只有一顆跳到卡片的按鈕", async () => {
    const reasoning = { labeler: "llm-p6.0", manual_version: "v0.6", items: [
      { label: "CONCL", polarity: "有理由", quote: "原告之請求有理由", paragraph: 3, start: 3, end: 11 },
    ] };
    mockApi({ "GET /judgments/civil/11/guide": () => ({ ...GUIDE, reasoning }) });
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    const nav = await screen.findByRole("navigation", { name: "跳到" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["法院怎麼認定"]);
    expect(within(nav).getByRole("link", { name: "法院怎麼認定" })).toHaveAttribute("href", "#reasoning-card");
    await userEvent.setup().click(within(nav).getByRole("link", { name: "法院怎麼認定" }));
    expect(scroll.mock.contexts.at(-1)).toBe(document.getElementById("reasoning-card"));
  });

  it("手機捷徑：沒有法院怎麼認定時不顯示", async () => {
    mockApi({ "GET /judgments/civil/11/guide": () => GUIDE });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    expect(await screen.findByRole("heading", { name: "判決全文" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "跳到" })).not.toBeInTheDocument();
  });

  it("法院怎麼認定：引文跨兩段時，兩段都標出來", async () => {
    const reasoning = { labeler: "llm-p6.0", manual_version: "v0.6", items: [
      { label: "CONCL", polarity: "有理由", quote: "跨段的引文", paragraph: 2, start: 4, end: 9,
        parts: [{ paragraph: 2, start: 4, end: 9 }, { paragraph: 3, start: 0, end: 3 }] },
    ] };
    mockApi({ "GET /judgments/civil/11/guide": () => ({ ...GUIDE, reasoning }) });
    const user = userEvent.setup();
    const { container } = renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    const card = (await screen.findByRole("heading", { name: "法院怎麼認定" })).closest("[aria-labelledby=reasoning-title]") as HTMLElement;
    await user.click(within(card).getByRole("button", { name: /跨段的引文/ }));
    expect(container.querySelector("#para-2 mark")).not.toBeNull();
    expect(container.querySelector("#para-3 mark")).toHaveTextContent(GUIDE.paragraphs[3].text.slice(0, 3));
  });

  it("法院怎麼認定：一組超過 3 處時先收起，按鈕展開、收起", async () => {
    const items = Array.from({ length: 5 }, (_, i) => (
      { label: "CONCL", polarity: "有理由", quote: `第${i + 1}項請求有理由`, paragraph: 3, start: 0, end: 3 }));
    mockApi({ "GET /judgments/civil/11/guide": () => ({ ...GUIDE, reasoning: { labeler: "llm-p6.0", manual_version: "v0.6", items } }) });
    const user = userEvent.setup();
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    const card = (await screen.findByRole("heading", { name: "法院怎麼認定" })).closest("[aria-labelledby=reasoning-title]") as HTMLElement;
    expect(card).toHaveTextContent("5 處");
    expect(within(card).getAllByRole("button", { pressed: false })).toHaveLength(3);
    const fourth = within(card).getByText(/第4項/);
    expect(fourth).not.toBeVisible();                         // 收起來（列印時仍會印出）
    await user.click(within(card).getByRole("button", { name: "顯示全部 5 處" }));
    expect(fourth).toBeVisible();
    expect(within(card).getByText(/第5項/)).toBeVisible();
    await user.click(within(card).getByRole("button", { name: "收起" }));
    expect(fourth).not.toBeVisible();
  });
});


describe("刑事判決導讀", () => {
  const url = "https://judgment.judicial.gov.tw/FJUD/data.aspx?id=TPDM";
  const para = (fn: string, label: string, text: string, extra = {}) => ({ function: fn, label, text, pre: false, part: null, ...extra });
  const guide = { case: { ...CRIMINAL_REPORT.similar[0], url }, paragraphs: [], mock: false, labeler: "criminal-rule-v1",
    criminal: { source: "judgment", judgment_date: "2024-05-01", paragraphs: [
      para("info", "案件資訊", "臺灣臺北地方法院刑事簡易判決\n上列被告因過失傷害案件", { pre: true }),
      para("verdict", "主文", "被告犯過失傷害罪，處拘役參拾日。"),
      para("facts", "犯罪事實", "一、本件犯罪事實及證據，均引用檢察官起訴書（如附件）之記載。"),
      para("court", "論罪科刑", "二、核被告所為，係犯刑法第284條前段之過失傷害罪。"),
      para("other", "其他", "中華民國113年5月1日\n刑事第二十庭法官○○○", { pre: true }),
      para("laws", "法條", "附錄本案論罪科刑法條全文：\n中華民國刑法第284條", { pre: true }),
      para("facts", "犯罪事實", "一、被告駕車未注意車前狀況，致被害人受傷。", { part: "附件：起訴書" }),
      para("evidence", "證據", "一、證據清單及待證事實：被告之自白。", { part: "附件：起訴書" }),
    ] } };
  it("判決資料只列應執行刑（一罪時就是那一罪的刑），抽不到時留空", async () => {
    const one = { ...guide, case: { ...guide.case, sentence: "有期徒刑 7 月" } };
    mockApi({ "GET /judgments/criminal/11/guide": () => one });
    const { unmount } = renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/criminal/11");
    const card = (await screen.findByRole("heading", { name: "判決資料" })).closest("[data-slot=card]") as HTMLElement;
    expect(within(card).getByText("有期徒刑 7 月")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /應執行刑說明/ })).toBeInTheDocument();
    expect(within(card).queryByText("宣告刑")).not.toBeInTheDocument();
    unmount();

    const none = { ...guide, case: { ...guide.case, sentence: null } };
    mockApi({ "GET /judgments/criminal/11/guide": () => none });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/criminal/11");
    const card2 = (await screen.findByRole("heading", { name: "判決資料" })).closest("[data-slot=card]") as HTMLElement;
    expect(within(card2).getByText("—")).toBeInTheDocument();
  });

  it("依原文順序顯示全文分段，標出段落功能，附件另起標題", async () => {
    mockApi({ "GET /judgments/criminal/11/guide": () => guide });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/criminal/11");
    expect(await screen.findByRole("heading", { name: "判決全文" })).toBeInTheDocument();
    const texts = [...document.querySelectorAll(".para p")].map((n) => n.textContent);
    expect(texts).toEqual(guide.criminal.paragraphs.map((p) => p.text));
    expect(document.querySelector('.para[data-fn="verdict"]')).toHaveTextContent("主文被告犯過失傷害罪");
    expect(screen.getByRole("heading", { name: "附件：起訴書" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /犯罪事實\s*2 段/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /附表/ })).not.toBeInTheDocument();   // 沒有附表就不列
    expect(screen.queryByRole("button", { name: /原告主張/ })).not.toBeInTheDocument();
    expect(screen.getByText("2024-05-01")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /司法院判決原文/ })).toHaveAttribute("href", url);
    expect(screen.getByRole("link", { name: /應執行刑說明/ })).toHaveAttribute("href", "/guide#%E6%87%89%E5%9F%B7%E8%A1%8C%E5%88%91");
    expect(screen.queryByText(/宣告刑是系統整理的結果/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回結果" })).toHaveAttribute("href", "/result/criminal?tab=cases");
  });
  it("取消上色後保留文字標籤", async () => {
    mockApi({ "GET /judgments/criminal/11/guide": () => guide });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/criminal/11");
    const button = await screen.findByRole("button", { name: /論罪科刑/ });
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-pressed", "false");
    const section = document.querySelector('.para[data-fn="court"]')!;
    expect(section).toHaveAttribute("data-on", "false");
    expect(section).toHaveTextContent("論罪科刑");
  });
  it("沒有全文時說明只有資料集的犯罪事實", async () => {
    mockApi({ "GET /judgments/criminal/11/guide": () => ({ ...guide, criminal: { source: "dataset", judgment_date: "",
      paragraphs: [para("facts", "犯罪事實", "被告基於××之犯意取走商品。", { part: "資料集節錄" })] } }) });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/criminal/11");
    expect(await screen.findByRole("heading", { name: "犯罪事實" })).toBeInTheDocument();
    expect(screen.getByText(/這件判決沒有收錄全文，以下只有資料集裡的犯罪事實/)).toBeInTheDocument();
    expect(screen.getByText("被告基於××之犯意取走商品。")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "資料集節錄" })).not.toBeInTheDocument();
  });
  it("連資料集都沒有時只顯示摘要", async () => {
    mockApi({ "GET /judgments/criminal/11/guide": () => ({ ...guide, criminal: null, labeler: "summary-only" }) });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/criminal/11");
    expect(await screen.findByText("這件判決沒有收錄全文")).toBeInTheDocument();
    expect(screen.getByText(`摘要：${guide.case.summary}`)).toBeInTheDocument();
    expect(document.querySelectorAll(".para")).toHaveLength(0);
  });
  it("無法載入時可重試，並可返回刑事結果", async () => {
    mockApi({});
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/criminal/999");
    expect(await screen.findByRole("alert")).toHaveTextContent("重新載入判決");
    expect(screen.getByRole("button", { name: "再試一次" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回結果" })).toHaveAttribute("href", "/result/criminal?tab=cases");
  });
});

describe("民事被告端", () => {
  it("第 1 關選民事後可以選原告或被告；選被告，第 2 關改問對方告你什麼，並可寫你的說法", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start", { caseType: "" });
    expect(screen.queryByRole("button", { name: "被告：我被告了" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "民事" }));
    expect(screen.getByRole("button", { name: "原告：我要告對方" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "被告：我被告了" }));
    expect(screen.getByRole("button", { name: "被告：我被告了" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("如果輸了，可能要賠的金額範圍")).toBeInTheDocument();
    // 再點一次已選的不會取消（一定要有一個角色）
    await user.click(screen.getByRole("button", { name: "被告：我被告了" }));
    expect(screen.getByRole("button", { name: "被告：我被告了" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "下一關" }));
    expect(screen.getByRole("heading", { name: /對方告你什麼/ })).toBeInTheDocument();
    expect(screen.getByLabelText("對方的主張")).toBeInTheDocument();
    expect(screen.getByLabelText(/你的說法/)).toBeInTheDocument();
  });

  it("第 1 關選不確定也可以選原告或被告；選被告，第 2 關一樣問對方告你什麼", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start", { caseType: "" });
    await user.click(screen.getByRole("radio", { name: "不確定" }));
    expect(screen.getByText(/收到法院寄來的起訴狀/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "被告：我被告了" }));
    await user.click(screen.getByRole("button", { name: "下一關" }));
    expect(screen.getByRole("heading", { name: /對方告你什麼/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/你的說法/)).toBeInTheDocument();
  });

  it("不確定選被告：整理時民事、刑事各送一份，都只送對方的主張", async () => {
    const sent: { text: string; case_type: string; role: string }[] = [];
    mockApi({
      "POST /intake/followup": () => ({ questions: [], source: "rules", llm_available: true }),
      "POST /intake/rewrite": (b: { text: string; case_type: string; role: string }) => {
        sent.push(b);
        return { text: b.case_type === "criminal" ? "被告甲推擠被害人乙。" : "原告主張被告推擠原告。", source: "llm", added_numbers: b.case_type === "criminal" ? ["3"] : [] };
      },
    });
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm?stage=6", { caseType: "unsure", role: "defendant", text: "朋友說我推他", defenseText: "我只是擋開他" });
    await user.click(await screen.findByRole("button", { name: "請 AI 整理敘述" }));
    expect(await screen.findByLabelText("民事用的寫法（可以直接修改）")).toHaveValue("原告主張被告推擠原告。");
    expect(screen.getByLabelText("刑事用的寫法（可以直接修改）")).toHaveValue("被告甲推擠被害人乙。");
    expect(screen.getByText(/整理後出現了原文沒有的數字：「3」/)).toBeInTheDocument();
    expect(sent.map((b) => b.case_type).sort()).toEqual(["criminal", "unsure"]);
    for (const b of sent) {
      expect(b.text).toBe("朋友說我推他");
      expect(b.role).toBe("defendant");
    }
  });

  it("不確定選被告：民事用被告的角度，刑事只送對方的主張並說明假設指控成立", async () => {
    const report = { ...CIVIL_REPORT, role: "defendant" as const };
    const masked = "朋友說我推他。\n【我的答辯】\n我只是擋開他。";
    const { calls } = mockApi({ "POST /civil/report": () => report, "POST /criminal/predict": () => CRIMINAL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { caseType: "unsure", role: "defendant", text: "朋友說我推他。", maskedText: masked });
    expect(await screen.findByRole("heading", { level: 2, name: /^民事參考結果（你是被告）/ })).toBeInTheDocument();
    expect(await screen.findByText("這裡假設對方指控的事都成立")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /civil/report")!.body).toMatchObject({ role: "defendant", text: masked });
    expect(calls.find((c) => c.key === "POST /criminal/predict")!.body).toEqual({ text: "朋友說我推他。" });
    expect(screen.getByText("刑事推估用的描述")).toBeInTheDocument();
  });

  it("整理過後回第 1 關改角色或案件類型，舊的整理會清掉（寫法跟著角色、類型變）", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    const saved = () => JSON.parse(window.sessionStorage.getItem(STORAGE_KEY)!);
    const rewritten = { rewriteFor: "x", rewriteDraft: "原告主張", searchText: "原告主張", criminalDraft: "被告甲", criminalSearchText: "被告甲" };
    renderApp("/start", { caseType: "unsure", text: "x", maskedText: "x", ...rewritten });
    await user.click(screen.getByRole("button", { name: "原告：我要告對方" }));   // 點已選的：不變
    expect(saved()).toMatchObject(rewritten);
    await user.click(screen.getByRole("button", { name: "被告：我被告了" }));
    expect(saved()).toMatchObject({ role: "defendant", rewriteFor: "", searchText: "", criminalSearchText: "", criminalDraft: "" });
  });

  it("整理過後改案件類型，舊的整理也會清掉", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start", { caseType: "criminal", text: "x", maskedText: "x", rewriteFor: "x", rewriteDraft: "被告甲毆打被害人乙", searchText: "被告甲毆打被害人乙" });
    await user.click(screen.getByRole("radio", { name: "不確定" }));
    expect(JSON.parse(window.sessionStorage.getItem(STORAGE_KEY)!)).toMatchObject({ caseType: "unsure", rewriteFor: "", searchText: "", rewriteDraft: "" });
  });

  it("不確定：刑事那份整理失敗時民事照用，刑事留空；選「我的原文」兩份都不用", async () => {
    mockApi({
      "POST /intake/followup": () => ({ questions: [], source: "rules", llm_available: true }),
      "POST /intake/rewrite": (b: { case_type: string }) => (b.case_type === "criminal"
        ? { source: "none", fallback: "limited", added_numbers: [] }
        : { text: "原告主張被告未還款。", source: "llm", added_numbers: [] }),
    });
    const user = userEvent.setup();
    const saved = () => JSON.parse(window.sessionStorage.getItem(STORAGE_KEY)!);
    renderAt("/confirm", <Confirm />, "/confirm?stage=6", { caseType: "unsure", text: "他欠我錢" });
    await user.click(await screen.findByRole("button", { name: "請 AI 整理敘述" }));
    expect(await screen.findByLabelText("民事用的寫法（可以直接修改）")).toHaveValue("原告主張被告未還款。");
    expect(screen.getByLabelText("刑事用的寫法（可以直接修改）")).toHaveValue("");
    expect(saved()).toMatchObject({ searchText: "原告主張被告未還款。", criminalSearchText: "" });
    await user.type(screen.getByLabelText("刑事用的寫法（可以直接修改）"), "被告甲未還款");
    expect(saved()).toMatchObject({ criminalSearchText: "被告甲未還款" });
    await user.click(screen.getByRole("radio", { name: "我的原文" }));
    expect(saved()).toMatchObject({ useRewrite: "original", searchText: "", criminalSearchText: "" });
  });

  it("被告的主張太短只提醒、不擋；空白才不能下一關", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderApp("/start?stage=2", { caseType: "civil", role: "defendant" });
    const next = screen.getByRole("button", { name: "下一關" });
    expect(next).toBeDisabled();
    expect(screen.getByText("請先寫對方告你什麼。")).toBeInTheDocument();
    await user.type(screen.getByLabelText("對方的主張"), "朋友告我欠他五萬元。");
    expect(next).toBeEnabled();
    expect(screen.getByText(/字數偏少，可以先進下一關/)).toBeInTheDocument();
    await user.click(next);
    expect(screen.getByRole("heading", { name: /第 3 關/ })).toBeInTheDocument();
  });

  it("結果頁換成被告的角度：對方勝訴的機率、你不用賠的機率、你有提到的說法", async () => {
    const report = {
      ...CIVIL_REPORT, role: "defendant" as const,
      defenses: [{ ...CIVIL_REPORT.defenses[0], user_has: true, lose_share: 0.4, n_raised: 12 }],
    };
    const { calls } = mockApi({ "POST /civil/report": () => report });
    const user = userEvent.setup();
    renderAt("/result/civil", <CivilResult />, "/result/civil", {
      caseType: "civil", role: "defendant", text: TRAFFIC, maskedText: TRAFFIC, mids: ["侵權：交通事故"], lawyer: "yes",
    });
    await screen.findByRole("tab", { name: "整體結果" });
    expect(calls[0].body).toMatchObject({ role: "defendant", defendant_has_lawyer: true, plaintiff_has_lawyer: null });
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["整體結果", "可能要賠的金額", "相似判決", "證據對照", "被告的說法"]);
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("對方（原告）勝訴的機率");
    expect(panel).toHaveTextContent("38%");
    await user.click(screen.getByRole("tab", { name: "被告的說法" }));
    const defense = screen.getByRole("tabpanel");
    expect(defense).toHaveTextContent("原告也有過失");
    expect(defense).toHaveTextContent("你有提到");
  });
});
