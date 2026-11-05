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

  it("有健康資料時要先同意", async () => {
    maskApi();
    const user = userEvent.setup();
    renderAt("/confirm", <Confirm />, "/confirm", { text: TRAFFIC });
    const go = screen.getByRole("button", { name: "看參考結果" });
    await screen.findByText(/去年三月/);
    expect(go).toBeDisabled();
    expect(screen.getByText(/內容包含健康資料/)).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /我同意/ }));
    await waitFor(() => expect(go).toBeEnabled());
  });

  it("沒有健康資料就不必勾", async () => {
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
      .toMatchObject({ text: "朋友借錢沒還\n當時是什麼燈？綠燈" }));
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
    expect(screen.getByText("臺灣臺北地方法院 113 年度訴字第 1 號")).toBeInTheDocument();
    expect(screen.getByText("31 萬／48 萬")).toBeInTheDocument();
    expect(screen.getByText("✓ 你有")).toBeInTheDocument();
    expect(screen.getByText("✗ 你沒有")).toBeInTheDocument();
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
