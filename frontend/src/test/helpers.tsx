import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import App from "../App";
import type { CivilReport, CriminalReport, Guide, Options } from "../api/types";
import { EMPTY_INTAKE, IntakeProvider, type Intake } from "../state";

// body 是畫面送出的 JSON，各個假回應自己知道它的格式
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Handler = (body: any) => unknown;

/** 攔截 fetch：依「方法 路徑」回傳假的 API 回應，並記下每次呼叫的內容。 */
export function mockApi(handlers: Record<string, Handler | { status: number }>) {
  const calls: { key: string; body: unknown }[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    const key = `${init?.method ?? "GET"} ${url.replace(/^\/api/, "")}`;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ key, body });
    const handler = handlers[key];
    if (!handler) return new Response("not found", { status: 404 });
    if (typeof handler === "object") return new Response("error", { status: handler.status });
    return new Response(JSON.stringify(handler(body)), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return { calls, spy };
}

export function renderApp(route: string, intake: Partial<Intake> = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <IntakeProvider initial={{ ...EMPTY_INTAKE, ...intake }}>
        <App />
      </IntakeProvider>
    </MemoryRouter>,
  );
}

export function renderAt(path: string, element: ReactElement, route = path, intake: Partial<Intake> = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <IntakeProvider initial={{ ...EMPTY_INTAKE, ...intake }}>
        <Routes><Route path={path} element={element} /></Routes>
      </IntakeProvider>
    </MemoryRouter>,
  );
}

export const OPTIONS: Options = {
  mid_groups: [
    { category: "侵權", mids: [{ value: "侵權：交通事故", n: 692 }, { value: "侵權：其他", n: 3465 }] },
    { category: "民間借貸", mids: [{ value: "民間借貸", n: 3421 }] },
  ],
  courts: ["臺北", "新北"],
  evidence: [
    { key: "medical", label: "診斷證明、病歷" },
    { key: "receipt", label: "收據、發票、估價單" },
  ],
  mock: false,
};

export const CIVIL_REPORT: CivilReport = {
  prediction: {
    win_probability: 0.62,
    signal: "strong",
    model: { name: "civil_winloss_v1", description: "TF-IDF（只用原告主張）＋案由中類、法院、律師、對方是否為法人", win_precision: 0.73, win_recall: 0.81, lose_precision: 0.66, lose_recall: 0.55, ece: 0.01 },
    warnings: [],
    mock: false,
  },
  amount_range: {
    n_cases: 18, ratio_low: 0.36, ratio_median: 0.6, ratio_high: 0.84, coverage: 0.8,
    claimed: 500000, amount_low: 180000, amount_median: 300000, amount_high: 420000,
  },
  similar: [
    { source: "civil", case_id: 11, case_number: "臺灣臺北地方法院 113 年度訴字第 1 號", court: "臺灣臺北地方法院", year: "2024",
      mid: "侵權：交通事故", outcome: "一部勝訴一部敗訴", similarity: 0.62, summary: "機車直行遭右轉汽車撞擊",
      claimed_amount: 480000, awarded_amount: 310000 },
    { source: "civil", case_id: 12, case_number: "臺灣臺北地方法院 112 年度訴字第 2 號", court: "臺灣臺北地方法院", year: "2023",
      mid: "侵權：交通事故", outcome: "敗訴", similarity: 0.51, summary: "未能證明薪資損失",
      claimed_amount: 300000, awarded_amount: 0 },
  ],
  evidence: [
    { key: "medical", label: "診斷證明、病歷", share: 0.82, user_has: true },
    { key: "receipt", label: "收據、發票、估價單", share: 0.74, user_has: false },
  ],
  defenses: [{ key: "contributory", label: "你也有過失（與有過失）", description: "主張你對損害的發生也有責任，要求減少賠償", share: 0.46 }],
  outcomes: { total: 30, win: 8, partial: 13, lose: 9 },
  n_compared: 30,
  mock: false,
};

export const CRIMINAL_REPORT: CriminalReport = {
  charges: [
    { name: "過失傷害罪", law: "刑法第 284 條", probability: 0.71,
      sentence: [{ label: "拘役、罰金", share: 0.38 }, { label: "1～6 個月", share: 0.62 }] },
    { name: "肇事逃逸罪", law: "刑法第 185 條之 4", probability: 0.06,
      sentence: [{ label: "拘役、罰金", share: 0.02 }, { label: "1～6 個月", share: 0.98 }] },
  ],
  similar: [{ source: "criminal", case_id: -1, case_number: "臺灣○○地方法院 ○○○ 年度交簡字第 ○○○ 號", court: "臺灣○○地方法院",
    year: "○○○", mid: "過失傷害", outcome: "有罪", similarity: 0.64, summary: "（示例）", sentence: "拘役 30 日" }],
  mock: true,
};

export const GUIDE: Guide = {
  case: CIVIL_REPORT.similar[0],
  paragraphs: [
    { function: "claim", label: "原告主張", text: "原告【原告】主張被告撞傷原告。" },
    { function: "issue", label: "爭點", text: "本件爭點為被告有無過失。" },
    { function: "evidence", label: "證據", text: "原告提出診斷證明書為證。" },
    { function: "court", label: "法院判斷", text: "綜上，原告之請求有理由。" },
  ],
  labeler: "rule-v0",
  mock: false,
};

export const TRAFFIC = "去年三月我騎機車在路口直行，被右轉的汽車撞到，右手骨折住院五天，之後三個月沒辦法工作。".repeat(3);
