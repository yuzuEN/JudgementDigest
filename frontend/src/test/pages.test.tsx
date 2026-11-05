import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import CivilResult from "../pages/CivilResult";
import Confirm from "../pages/Confirm";
import CriminalResult from "../pages/CriminalResult";
import Intake from "../pages/Intake";
import Reading from "../pages/Reading";
import { CIVIL_REPORT, CRIMINAL_REPORT, GUIDE, mockApi, OPTIONS, renderApp, renderAt, TRAFFIC } from "./helpers";

describe("首頁", () => {
  it("有開始的按鈕與免責說明", () => {
    renderApp("/");
    expect(screen.getByRole("link", { name: "開始描述案情" })).toHaveAttribute("href", "/start");
    expect(screen.getByText("這不是法律意見")).toBeInTheDocument();
  });
});

describe("描述案情", () => {
  it("選項從 API 來，選刑事時不問民事的問題", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderAt("/start", <Intake />);
    expect(await screen.findByRole("option", { name: "侵權：交通事故" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "臺北地方法院" })).toBeInTheDocument();
    expect(screen.getByLabelText("診斷證明、病歷")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /被警察、檢察官調查，或想告對方犯罪/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /刑事/ }));
    expect(screen.getByRole("button", { name: /刑事/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("幾個基本問題")).not.toBeInTheDocument();
    expect(screen.getByText("刑事案件")).toBeInTheDocument();
  });

  it("字數提示與送出條件", async () => {
    mockApi({ "GET /meta/options": () => OPTIONS });
    const user = userEvent.setup();
    renderAt("/start", <Intake />);
    const next = screen.getByRole("button", { name: "下一步：確認內容" });
    expect(next).toBeDisabled();
    await user.type(screen.getByLabelText("發生了什麼事？"), "被車撞了");
    expect(screen.getByText("再多寫一些，結果會比較準")).toBeInTheDocument();
    expect(next).toBeEnabled();

    await user.type(screen.getByLabelText("想請求的金額（新臺幣）"), "五十萬");
    expect(screen.getByText(/看不懂這個金額/)).toBeInTheDocument();
    expect(next).toBeDisabled();
  });

  it("選項載入失敗可以重試", async () => {
    mockApi({ "GET /meta/options": { status: 500 } });
    renderAt("/start", <Intake />);
    expect(await screen.findByRole("alert")).toHaveTextContent("選項載入失敗");
    expect(screen.getByRole("button", { name: "再試一次" })).toBeInTheDocument();
  });
});

describe("確認與遮名：敏感個人資料", () => {
  it("日常用語不需要同意，同意時會列出偵測到的類別", async () => {
    mockApi({ "POST /intake/mask": (b: { text: string }) => ({ masked_text: b.text, spans: [] }),
      "POST /intake/followup": () => ({ questions: [], source: "rules" }) });
    renderAt("/confirm", <Confirm />, "/confirm", { text: "我受傷了，對方有前科，後來去住院" });
    expect(await screen.findByText(/偵測到：病歷、醫療、犯罪前科/)).toBeInTheDocument();
  });

  it("不同意時可以回上一步，同意後這個選項消失", async () => {
    mockApi({ "POST /intake/mask": (b: { text: string }) => ({ masked_text: b.text, spans: [] }),
      "POST /intake/followup": () => ({ questions: [], source: "rules" }) });
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "我開刀後休養三個月" });
    const decline = await screen.findByRole("link", { name: "不同意，回上一步刪掉這些描述" });
    expect(decline).toHaveAttribute("href", "/start");
    expect(screen.getByRole("button", { name: "看參考結果" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /我同意/ }));
    expect(screen.queryByRole("link", { name: "不同意，回上一步刪掉這些描述" })).not.toBeInTheDocument();
  });

  it("沒有敏感個資就不用選", async () => {
    mockApi({ "POST /intake/mask": (b: { text: string }) => ({ masked_text: b.text, spans: [] }),
      "POST /intake/followup": () => ({ questions: [], source: "rules" }) });
    renderAt("/confirm", <Confirm />, "/confirm", { text: "朋友借錢沒還" });
    await screen.findByText("朋友借錢沒還");
    expect(screen.queryByRole("link", { name: /不同意/ })).not.toBeInTheDocument();
  });
});

describe("確認與遮名：AI 追問", () => {
  const AI_BUTTON = "請 AI 幫我看還缺什麼";
  type Body = { text: string; allow_llm: boolean };
  const setup = (reply: (b: Body) => unknown) => {
    const sent: Body[] = [];
    mockApi({
      "POST /intake/mask": (b: { text: string; names: string[] }) => ({ masked_text: b.names.reduce((t, n) => t.split(n).join("【姓名】"), b.text.replace("0912345678", "【電話】")), spans: [] }),
      "POST /intake/followup": (b: Body) => { sent.push(b); return reply(b); },
    });
    return sent;
  };
  const rulesReply = { questions: [{ id: "when", text: "什麼時候發生的？", why: "時效" }], source: "rules", llm_available: true };
  const aiReply = { questions: [{ id: "llm1", text: "對方怎麼說？", why: "爭點" }], source: "llm", llm_available: true };

  it("打開頁面時不會把內容傳給 LLM", async () => {
    const sent = setup(() => rulesReply);
    renderAt("/confirm", <Confirm />, "/confirm", { text: "王小明的電話是0912345678" });
    await screen.findByRole("button", { name: AI_BUTTON });
    expect(screen.queryByText("什麼時候發生的？")).not.toBeInTheDocument();
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ allow_llm: false, text: "王小明的電話是【電話】" });
  });

  it("沒有設定 LLM 時不顯示按鈕", async () => {
    setup(() => ({ ...rulesReply, llm_available: false }));
    renderAt("/confirm", <Confirm />, "/confirm", { text: "內容" });
    await screen.findByText("什麼時候發生的？");
    expect(screen.getByText(/這類案件常缺的細節/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: AI_BUTTON })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "不用 AI，回答一般問題" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Google Gemini/)).not.toBeInTheDocument();
  });

  it("敏感個資沒有同意前不能傳給 LLM", async () => {
    setup(() => rulesReply);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "我骨折住院" });
    const button = await screen.findByRole("button", { name: AI_BUTTON });
    await screen.findByText("我骨折住院");
    expect(button).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /我同意/ }));
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("按下按鈕才傳，而且加入的姓名已經遮掉", async () => {
    const sent = setup((b) => (b.allow_llm ? aiReply : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "王小明的電話是0912345678" });
    await screen.findByRole("button", { name: AI_BUTTON });
    await user.type(screen.getByPlaceholderText("例如：王小明"), "王小明");
    await user.click(screen.getByRole("button", { name: "加入" }));
    await screen.findByText("【姓名】");
    await waitFor(() => expect(screen.getByRole("button", { name: AI_BUTTON })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: AI_BUTTON }));
    expect(await screen.findByText("對方怎麼說？")).toBeInTheDocument();
    expect(screen.getByText(/由 AI 依你的案情產生/)).toBeInTheDocument();
    const toLlm = sent.filter((b) => b.allow_llm);
    expect(toLlm).toHaveLength(1);
    expect(toLlm[0].text).toBe("【姓名】的電話是【電話】");
    expect(screen.queryByRole("button", { name: AI_BUTTON })).not.toBeInTheDocument();
  });

  it("不用 AI 時顯示一般問題，而且不會傳給 LLM", async () => {
    const sent = setup(() => rulesReply);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "我骨折住院" });
    await user.click(await screen.findByRole("button", { name: "不用 AI，回答一般問題" }));
    expect(screen.getByText("什麼時候發生的？")).toBeInTheDocument();
    expect(screen.getByText(/不會傳給 AI/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: AI_BUTTON })).not.toBeInTheDocument();
    expect(sent.every((b) => !b.allow_llm)).toBe(true);
  });

  it("選了不用 AI 之後可以反悔", async () => {
    const sent = setup((b) => (b.allow_llm ? aiReply : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "內容" });
    await user.click(await screen.findByRole("button", { name: "不用 AI，回答一般問題" }));
    await user.click(screen.getByRole("button", { name: "改請 AI 提問" }));
    const button = screen.getByRole("button", { name: AI_BUTTON });
    await waitFor(() => expect(button).toBeEnabled());
    expect(sent.filter((b) => b.allow_llm)).toHaveLength(0);
    await user.click(button);
    expect(await screen.findByText("對方怎麼說？")).toBeInTheDocument();
  });

  it("AI 和一般問題可以來回切換，不會重複傳，回答也保留", async () => {
    const sent = setup((b) => (b.allow_llm ? aiReply : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "內容" });
    const button = await screen.findByRole("button", { name: AI_BUTTON });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    await user.type(await screen.findByLabelText("對方怎麼說？"), "他不承認");
    await user.click(screen.getByRole("button", { name: "改回答一般問題" }));
    expect(screen.getByText("什麼時候發生的？")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "改請 AI 提問" }));
    expect(screen.getByLabelText("對方怎麼說？")).toHaveValue("他不承認");
    expect(sent.filter((b) => b.allow_llm)).toHaveLength(1);
  });

  it("AI 失敗後可以重試", async () => {
    let fail = true;
    setup((b) => {
      if (!b.allow_llm) return rulesReply;
      if (fail) { fail = false; return { ...rulesReply, fallback: "error" }; }
      return aiReply;
    });
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "內容" });
    const first = await screen.findByRole("button", { name: AI_BUTTON });
    await waitFor(() => expect(first).toBeEnabled());
    await user.click(first);
    await user.click(await screen.findByRole("button", { name: "再試一次 AI" }));
    await user.click(await screen.findByRole("button", { name: AI_BUTTON }));
    expect(await screen.findByText("對方怎麼說？")).toBeInTheDocument();
  });

  it("內容不像法律糾紛時說明原因，不說 AI 壞了", async () => {
    setup((b) => (b.allow_llm ? { ...rulesReply, fallback: "not_dispute" } : rulesReply));
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "今天天氣很好" });
    const button = await screen.findByRole("button", { name: AI_BUTTON });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(await screen.findByText(/看起來不像法律糾紛/)).toBeInTheDocument();
    expect(screen.queryByText(/AI 暫時無法使用/)).not.toBeInTheDocument();
  });

  it("同意文字說明會傳給 Gemini", async () => {
    setup(() => rulesReply);
    renderAt("/confirm", <Confirm />, "/confirm", { text: "我骨折住院" });
    expect(await screen.findByText(/這些內容也會傳給 Google Gemini/)).toBeInTheDocument();
  });

  it("AI 失敗時說明，並保留固定題庫", async () => {
    setup(() => rulesReply);
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "內容" });
    const button = await screen.findByRole("button", { name: AI_BUTTON });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(await screen.findByText(/AI 暫時無法使用/)).toBeInTheDocument();
    expect(screen.getByText("什麼時候發生的？")).toBeInTheDocument();
  });
});

describe("確認與遮名", () => {
  const maskApi = () => mockApi({
    "POST /intake/followup": () => ({ questions: [{ id: "signal", text: "當時是什麼燈？", why: "會影響過失比例。" }], source: "rules" }),
    "POST /intake/mask": (b) => ({
      masked_text: b.names.reduce((t: string, n: string) => t.split(n).join("【姓名】"), b.text).replace(/09\d{8}/, "【電話】"),
      spans: [],
    }),
  });

  it("預覽遮名後的內容，可以加名字", async () => {
    const { calls } = maskApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "王小明撞到我，他的電話0912345678" });
    expect(await screen.findByText("【電話】")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/要遮掉的名字/), "王小明");
    await user.click(screen.getByRole("button", { name: "加入" }));
    await waitFor(() => expect(screen.getAllByText("【姓名】").length).toBeGreaterThan(0));
    expect(calls.filter((c) => c.key === "POST /intake/mask").at(-1)?.body).toMatchObject({ names: ["王小明"] });
    expect(screen.getByRole("button", { name: "不遮「王小明」" })).toBeInTheDocument();
  });

  it("有敏感個資時要先同意", async () => {
    maskApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: TRAFFIC });
    const go = screen.getByRole("button", { name: "看參考結果" });
    await screen.findByText(/去年三月/);
    expect(go).toBeDisabled();
    expect(screen.getByText(/內容包含敏感個人資料/)).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /我同意/ }));
    await waitFor(() => expect(go).toBeEnabled());
  });

  it("沒有敏感個資就不必勾", async () => {
    maskApi();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "朋友借了五十萬一直沒還" });
    await waitFor(() => expect(screen.getByRole("button", { name: "看參考結果" })).toBeEnabled());
    expect(screen.queryByRole("checkbox", { name: /我同意/ })).not.toBeInTheDocument();
  });

  it("追問的回答會加進送出的內容", async () => {
    const { calls } = maskApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: "朋友借錢沒還" });
    await user.type(await screen.findByLabelText("當時是什麼燈？"), "綠燈");
    await waitFor(() => expect(calls.filter((c) => c.key === "POST /intake/mask").at(-1)?.body)
      .toMatchObject({ text: "朋友借錢沒還\n追問：當時是什麼燈？\n回答：綠燈" }));
  });
});

describe("民事結果", () => {
  const intake = { text: TRAFFIC, maskedText: TRAFFIC, mid: "侵權：交通事故", claimedAmount: "50萬", evidence: ["medical"] };

  it("顯示機率、金額、相似判決、證據與抗辯", async () => {
    const { calls } = mockApi({ "POST /civil/report": () => CIVIL_REPORT });
    renderAt("/result/civil", <CivilResult />, "/result/civil", intake);
    expect(await screen.findByText("62%")).toBeInTheDocument();
    expect(screen.getByText("18 萬～42 萬")).toBeInTheDocument();
    expect(screen.getByText(/比對了 30 件/)).toBeInTheDocument();
    expect(screen.getByText(/口語描述算出來的機率常常偏低/)).toBeInTheDocument();
    expect(screen.getByText("臺灣臺北地方法院 113 年度訴字第 1 號")).toBeInTheDocument();
    expect(screen.getByText("31 萬／48 萬")).toBeInTheDocument();
    expect(screen.getByText("✓ 你有提到")).toBeInTheDocument();
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
    await user.click(screen.getByLabelText("只看原告勝訴的"));
    expect(within(table).getAllByRole("row")).toHaveLength(2);
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
    expect(screen.getByRole("heading", { name: "描述你遇到的糾紛" })).toBeInTheDocument();
  });
});

describe("刑事結果", () => {
  it("點罪名切換刑期分布", async () => {
    mockApi({ "POST /criminal/predict": () => CRIMINAL_REPORT });
    const user = userEvent.setup();
    renderAt("/result/criminal", <CriminalResult />, "/result/criminal", { text: "x", maskedText: "開車撞到人" });
    expect(await screen.findByRole("heading", { name: "刑期範圍：過失傷害罪" })).toBeInTheDocument();
    expect(screen.getByText(/刑事組開發中/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /肇事逃逸罪/ }));
    expect(screen.getByRole("heading", { name: "刑期範圍：肇事逃逸罪" })).toBeInTheDocument();
    expect(screen.getByText("98%")).toBeInTheDocument();
  });
});

describe("判決導讀", () => {
  it("段落與標示切換", async () => {
    const { calls } = mockApi({ "GET /judgments/civil/11/guide": () => GUIDE });
    const user = userEvent.setup();
    const { container } = renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/11");
    expect(await screen.findByRole("heading", { name: "臺灣臺北地方法院 113 年度訴字第 1 號" })).toBeInTheDocument();
    expect(calls[0].key).toBe("GET /judgments/civil/11/guide");
    expect(container.querySelector(".para.issue")).toHaveClass("on");
    expect(container.querySelector(".para.claim")).not.toHaveClass("on");
    await user.click(screen.getByRole("checkbox", { name: /原告主張/ }));
    expect(container.querySelector(".para.claim")).toHaveClass("on");
    expect(screen.getByText(/規則初步標示/)).toBeInTheDocument();
  });

  it("找不到判決", async () => {
    mockApi({});
    renderAt("/judgment/:source/:caseId", <Reading />, "/judgment/civil/999");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
