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

  it("有敏感個資時，整理前要先同意；不同意就用原本的描述", async () => {
    const { sent } = setup(llm);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at6, { text: "我骨折住院，對方不賠" });
    const button = await screen.findByRole("button", { name: BUTTON });
    expect(button).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "不同意，不用 AI" }));
    expect(screen.getByText(/這次不用 AI，會用你原本的描述/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "看參考結果" })).toBeEnabled();
    await user.click(screen.getByRole("radio", { name: "我同意傳給 AI" }));
    await user.click(screen.getByRole("button", { name: BUTTON }));
    await screen.findByLabelText("整理後的寫法（可以直接修改）");
    expect(sent).toHaveLength(1);
  });

  it("結果頁送出確認過的文字", async () => {
    const { calls } = mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { text: "內容", maskedText: "內容", searchText: "原告主張" });
    expect(await screen.findByText(/用你確認過的整理文字搜尋。/)).toBeInTheDocument();
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

  it("不確定時可以切到刑事，並說明兩邊都看", async () => {
    mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", { ...intake, caseType: "unsure" });
    await screen.findByText("62%");
    const nav = screen.getByRole("navigation", { name: "結果類型" });
    expect(within(nav).getByRole("link", { name: "刑事" })).toHaveAttribute("href", "/result/criminal");
    expect(within(nav).getByText("民事")).toHaveAttribute("aria-current", "page");
    expect(nav).toHaveTextContent("你選了「不確定」，兩邊都幫你看。");
  });

  it("選民事時，直接開刑事網址會回到民事，也不查刑事", async () => {
    const { calls } = mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderApp("/result/criminal", { ...intake, caseType: "civil" });
    expect(await screen.findByText("62%")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).not.toContain("POST /criminal/predict");
  });
});

describe("相似度說明", () => {
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

  it("有敏感個資時，傳給 AI 前要先同意；沒同意按鈕不能按", async () => {
    const sent = setup((b) => (b.allow_llm ? aiReply : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "我骨折住院" });
    const send = await openAi(user);
    expect(screen.getByRole("heading", { name: "傳給 AI 前，需要你同意" })).toBeInTheDocument();
    expect(send).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "我同意傳給 AI" }));
    expect(send).toBeEnabled();
    await user.click(send);
    expect(await screen.findByLabelText("對方怎麼說？")).toBeInTheDocument();
    expect(sent.filter((b) => b.allow_llm)).toHaveLength(1);
  });

  it("不同意就不用 AI，可以改用固定題目，也不會傳", async () => {
    const sent = setup((b) => (b.allow_llm ? aiReply : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "我骨折住院" });
    await openAi(user);
    await user.click(screen.getByRole("radio", { name: "不同意，不用 AI" }));
    expect(screen.queryByRole("button", { name: SEND })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "改用固定題目" }));
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

  it("資料使用說明寫出會傳給哪一家 AI", async () => {
    setup(() => ({ ...rulesReply, llm_vendor: "OpenAI" }));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, at5, { text: "我骨折住院" });
    await openAi(user);
    expect(screen.getAllByText(/遮名後的內容會傳給 OpenAI/).length).toBeGreaterThan(0);
    expect(screen.getByText(/才會傳給 OpenAI 的付費 API/)).toBeInTheDocument();
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
    it("五個分頁，預設整體結果；換分頁時解說員的話也換", async () => {
      const { calls } = await show();
      expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["整體結果", "可能的金額", "證據對照", "對方的說法", "相似判決"]);
      expect(screen.getByRole("tab", { name: "整體結果" })).toHaveAttribute("aria-selected", "true");
      const scene = screen.getByRole("region", { name: "CasEY 角色說明" });
      expect(scene).toHaveTextContent("解說員");
      expect(scene).toHaveTextContent("不會預測你這件的結果");
      await openTab("對方的說法");
      expect(scene).toHaveTextContent("先看過，到時比較不會慌");
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
  });

  describe("整體結果", () => {
    it("主畫面是判決件數，機率放在模型細節，而且說明不是你會贏的機率", async () => {
      await show();
      expect(screen.getByRole("img", { name: "全部勝訴 8 件、一部勝訴 13 件、敗訴 9 件" })).toBeInTheDocument();
      const detail = screen.getByText("62%").closest("details")!;
      expect(detail).toHaveTextContent("不是你會贏的機率");
      expect(detail).toHaveTextContent("口語描述算出來的機率常常偏低");
    });

    it.each([
      ["strong", "參考訊號：較強", "勝訴訊號較強"],
      ["weak", "參考訊號：較弱", "勝訴訊號較弱"],
      ["insufficient", "參考訊號：資訊不足", "描述太短"],
    ] as const)("參考訊號 %s 用固定文字", async (signal, title, text) => {
      await show({ prediction: prediction(signal) });
      expect(screen.getByText(title)).toBeInTheDocument();
      expect(screen.getByText(new RegExp(text))).toBeInTheDocument();
    });

    it("資訊不足時不說強弱", async () => {
      await show({ prediction: prediction("insufficient") });
      expect(screen.queryByText(/勝訴訊號較(強|弱)/)).not.toBeInTheDocument();
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

    it("模型表現用 precision、recall 說明，不顯示 AUC", async () => {
      await show();
      expect(screen.getByText(/判勝訴的案件有 73% 真的勝訴/)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Precision、Recall 說明/, hidden: true })).toBeInTheDocument();
      expect(screen.queryByText(/AUC/)).not.toBeInTheDocument();
    });

    it("舊的模型檔沒有這些數字時不顯示", async () => {
      const { win_precision: _, ...model } = CIVIL_REPORT.prediction.model;
      await show({ prediction: { ...CIVIL_REPORT.prediction, model } });
      expect(screen.queryByText(/真的勝訴/)).not.toBeInTheDocument();
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
    expect(within(panel).getByText("你沒有提到")).toBeInTheDocument();
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
    it("表格、相似度說明與判決導讀", async () => {
      await show();
      const panel = await openTab("相似判決");
      const table = within(panel).getByRole("table");
      expect(within(table).getByText("臺灣臺北地方法院 113 年度訴字第 1 號")).toBeInTheDocument();
      expect(within(table).getByText("310,000")).toBeInTheDocument();
      expect(within(table).getAllByRole("link", { name: "判決導讀" })[0]).toHaveAttribute("href", "/judgment/civil/11");
      expect(within(panel).getByRole("link", { name: /相似度說明/ }).getAttribute("href")).toBe(`/guide#${encodeURIComponent("相似度")}`);
      expect(within(panel).getByText(/只用來排列結果，不是百分比/)).toBeInTheDocument();
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
      expect(within(panel).getByText(/統計不包含這些判決/)).toBeInTheDocument();
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

  it("頁尾有「請注意」，列印時直接印出條列", async () => {
    await show();
    expect(screen.getByRole("button", { name: "請注意" })).toBeInTheDocument();
    const printed = screen.getByRole("heading", { name: "請注意" }).closest(".print-only")!;
    expect(printed).toHaveTextContent("不是法律意見");
    expect(printed).toHaveTextContent("和解、撤回");
  });

  it("錯誤時說不是你填錯，可以重試", async () => {
    mockApi({ "POST /civil/report": { status: 500 } });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("伺服器發生錯誤");
    expect(alert).toHaveTextContent("不是你填錯了什麼");
    expect(within(alert).getByRole("button", { name: "再試一次" })).toBeInTheDocument();
  });

  it("載入中顯示骨架和說明", () => {
    mockApi({ "POST /civil/report": () => new Promise(() => {}) });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    expect(screen.getByText("正在比對相似判決…")).toBeInTheDocument();
  });

  it("沒有內容就回到第一步", () => {
    renderApp("/result/civil");
    expect(screen.getByRole("heading", { name: /這是哪一類的事情/ })).toBeInTheDocument();
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

  it("三個分頁；換分頁時解說員的話也換", async () => {
    await show({ mock: false });
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["可能的罪名", "刑期範圍", "相似判決"]);
    const scene = screen.getByRole("region", { name: "CasEY 角色說明" });
    expect(scene).toHaveTextContent("可能的罪名是什麼");
    await openTab("刑期範圍");
    expect(scene).toHaveTextContent("放在一起比較");
    expect(screen.getAllByRole("tabpanel", { hidden: true })).toHaveLength(3);
  });

  it("選罪名後，刑期範圍分頁跟著切換；列印時每個罪名都印", async () => {
    await show();
    const user = userEvent.setup();
    expect(screen.getByRole("radio", { name: /過失傷害罪/ })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: /肇事逃逸罪/ }));
    expect(screen.getByRole("radio", { name: /肇事逃逸罪/ })).toBeChecked();
    const panel = await openTab("刑期範圍");
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
    expect(screen.getByText(/第一個罪名猜中 93%/)).toBeInTheDocument();
    const panel = await openTab("刑期範圍");
    expect(panel).toHaveTextContent("最相似的 50 件「過失傷害罪」有罪判決，實際宣告刑多數落在「1～6 個月」");
    expect(within(panel).getByText("最相似 50 件的實際宣告刑")).toBeInTheDocument();
    expect(within(panel).getByText("實際 80%")).toBeInTheDocument();
    expect(within(panel).getByRole("img", { name: "1～6 個月：模型推估 62%，最相似 50 件實際宣告刑 80%" })).toBeInTheDocument();
  });

  it("真模型沒有相似判決時說明，不出現表格", async () => {
    await show({ similar: [], mock: false });
    const panel = await openTab("相似判決");
    expect(within(panel).getByText("刑事的相似判決檢索開發中。")).toBeInTheDocument();
    expect(within(panel).queryByRole("table")).not.toBeInTheDocument();
  });

  it("真的刑事判決連到司法院原文，不連判決導讀", async () => {
    const url = "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDM";
    await show({ mock: false, similar: [{ ...CRIMINAL_REPORT.similar[0], url }] });
    const panel = await openTab("相似判決");
    expect(within(panel).getByRole("link", { name: "判決原文" })).toHaveAttribute("href", url);
    expect(within(panel).queryByRole("link", { name: "判決導讀" })).not.toBeInTheDocument();
    expect(within(panel).getByText(/只用來排列結果，不是百分比/)).toBeInTheDocument();
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

  it("錯誤時說不是你填錯，可以重試", async () => {
    mockApi({ "POST /criminal/predict": { status: 500 } });
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", intake);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("不是你填錯了什麼");
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
    expect(screen.getByText(/規則初步標示/)).toBeInTheDocument();
  });

  it("基本資料、判准比例與回結果", async () => {
    mockApi({ "GET /judgments/civil/11/guide": () => GUIDE });
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    await screen.findByRole("heading", { name: "判決的基本資料" });
    expect(screen.getByText("一部勝訴")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "判准金額約占請求金額的 65%" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "回結果" })).toHaveAttribute("href", "/result/civil?tab=cases");
    expect(screen.getByRole("region", { name: "CasEY 角色說明" })).toHaveTextContent("解說員");
  });

  it("找不到判決", async () => {
    mockApi({});
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/999");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
