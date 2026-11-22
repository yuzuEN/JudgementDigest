import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { CaseType, CivilInput, CivilRole, DefendantType } from "./api/types";
import { parseAmount } from "./format";
import { clearReportCache } from "./api/client";

// 使用者填的內容放在這個分頁的 sessionStorage：重新整理還在，關掉分頁就清掉；
// 不用 localStorage（會一直留在電腦上），也不送去保存。
export const STORAGE_KEY = "casey-intake-v1";

export interface Intake {
  caseType: CaseType | "";   // 空字串＝還沒選（第 1 關必選）
  role: CivilRole;       // 民事：你是原告（要告對方）還是被告（被告了）；選「民事」或「不確定」時用得到（刑事不分）
  text: string;          // 原告：事情經過；被告：對方告你什麼
  defenseText: string;   // 被告：你的說法（選填）
  mids: string[];        // 糾紛類型，可以多選
  court: string;
  lawyer: "yes" | "no" | "";
  defendantType: DefendantType | "";
  claimedAmount: string;
  evidence: string[];
  criminalEvidence: string[];   // 刑事案件手上的證據（標籤文字）
  followupAnswers: Record<string, { question: string; answer: string }>;
  names: string[];
  maskedText: string;
  sensitiveConsent: boolean;
  searchText: string;    // 使用者選用的改寫（已遮名）；民事只用來搜尋相似判決，刑事也用來推估罪名
  rewriteFor: string;    // 改寫時的遮名描述；描述改了，改寫就不能再用
  rewriteDraft: string;  // AI 整理的草稿（使用者可以直接改），在關卡之間來回時保留，不用重新呼叫 AI
  rewriteAdded: string[];   // 草稿裡有、描述裡沒有的數字
  useRewrite: "rewrite" | "original";
  // 「不確定」另外整理一份刑事寫法（犯罪事實），只給刑事用；被告時只整理對方的主張
  criminalDraft: string;
  criminalAdded: string[];
  criminalSearchText: string;
}

export const EMPTY_INTAKE: Intake = {
  caseType: "",
  role: "plaintiff",
  text: "",
  defenseText: "",
  mids: [],
  court: "",
  lawyer: "",
  defendantType: "",
  claimedAmount: "",
  evidence: [],
  criminalEvidence: [],
  followupAnswers: {},
  names: [],
  maskedText: "",
  sensitiveConsent: false,
  searchText: "",
  rewriteFor: "",
  rewriteDraft: "",
  rewriteAdded: [],
  useRewrite: "rewrite",
  criminalDraft: "",
  criminalAdded: [],
  criminalSearchText: "",
};

/**
 * 送給 API 的案由中類。API 只收一個：只選一類就送那一類；
 * 沒選或選了好幾類就不送，讓系統從描述判斷。
 */
export function primaryMid(intake: Intake): string | null {
  return intake.mids.length === 1 ? intake.mids[0] : null;
}

/** 後端用這一行切開對方的主張和你的答辯（civil/insights.py 的 DEFENSE_MARKER），兩邊要一樣。 */
export const DEFENSE_MARKER = "【我的答辯】";

/**
 * 民事這次用哪個角色：「民事」和「不確定」都可以選被告，刑事不分原告被告。
 * 「不確定」選被告時，民事照被告的方式送（對方的主張＋你的答辯），刑事只送對方的主張（見 criminalText）。
 */
export function civilRole(intake: Pick<Intake, "caseType" | "role">): CivilRole {
  return (intake.caseType === "civil" || intake.caseType === "unsure") && intake.role === "defendant" ? "defendant" : "plaintiff";
}

/**
 * 清掉 AI 整理的結果。描述或姓名改了要清；案件類型、角色改了也要清：
 * 整理的寫法跟著它們變（民事原告、民事被告、刑事各一種），留著舊的會用錯寫法去比對。
 */
export const REWRITE_RESET: Partial<Intake> = {
  searchText: "", rewriteFor: "", rewriteDraft: "", rewriteAdded: [], useRewrite: "rewrite",
  criminalDraft: "", criminalAdded: [], criminalSearchText: "",
};

/**
 * 送給刑事 API 的文字。
 * 刑事：整理後的寫法，或遮名後的原文。
 * 不確定：刑事寫法的整理（criminalSearchText），沒有就用遮名後的原文；被告時都只取對方的主張，
 * 不送你的答辯：判決的犯罪事實段寫的是被指控的事實（答辯在理由段），刑事模型也只估「指控成立時」的罪名與刑度。
 */
export function criminalText(intake: Pick<Intake, "caseType" | "searchText" | "maskedText" | "criminalSearchText">): string {
  if (intake.caseType === "unsure") return intake.criminalSearchText || claimPart(intake.maskedText);
  return intake.searchText || intake.maskedText;
}

/**
 * 「有沒有請律師」問的是誰：民事問使用者自己（原告或被告，看選的角色）；
 * 刑事問被告有沒有辯護人（使用者可能是被告，也可能是被害人）。「不確定」兩邊都查，用民事原告的問法。
 */
export function lawyerQuestion(caseType: Intake["caseType"], role: CivilRole = "plaintiff"): { label: string; hint: string; short: string } {
  if (caseType === "criminal") {
    return { label: "被告有沒有請辯護律師", hint: "被告的律師叫辯護人。你是被害人的話，填對方的情況；不知道可以不選。", short: "被告的辯護律師" };
  }
  return role === "defendant"
    ? { label: "你（被告）有沒有請律師", hint: "問的是你這一方，不是告你的人。", short: "你（被告）的律師" }
    : { label: "你（原告）有沒有請律師", hint: "問的是你這一方，不是對方。", short: "你（原告）的律師" };
}

/**
 * 描述加上追問的回答，作為遮名與送出的全文。
 * 刑事 API 只收文字，所以刑事的律師、手上的證據也接在最後。
 * 民事被告：對方的主張在前；你的說法和追問的回答（問的都是你這一方）接在 DEFENSE_MARKER 那一行後面。
 */
export function fullText(intake: Intake): string {
  const extra = Object.values(intake.followupAnswers)
    .filter((a) => a.answer.trim())
    .map((a) => `追問：${a.question}\n回答：${a.answer.trim()}`);   // 後端靠這兩個開頭分辨問題和回答
  if (civilRole(intake) === "defendant") {
    const defense = [intake.defenseText.trim(), ...extra].filter(Boolean);
    return [intake.text.trim(), ...(defense.length ? [DEFENSE_MARKER, ...defense] : [])].filter(Boolean).join("\n");
  }
  const criminal = intake.caseType === "criminal";
  const lawyer = criminal && intake.lawyer ? [`${lawyerQuestion("criminal").label}：${intake.lawyer === "yes" ? "有" : "沒有"}`] : [];
  const evidence = criminal && intake.criminalEvidence.length
    ? [`手上的證據：${intake.criminalEvidence.join("、")}`] : [];
  return [intake.text.trim(), ...extra, ...lawyer, ...evidence].filter(Boolean).join("\n");
}

/** 遮名後的全文裡，對方的主張那一段（被告時拿掉你的答辯；原告時就是全文）：AI 整理成判決書寫法時只整理這段。 */
export function claimPart(text: string): string {
  const i = text.indexOf(DEFENSE_MARKER);
  return (i < 0 ? text : text.slice(0, i)).trim();
}

/** 送給民事 API 的內容：一律用遮名後的文字。 */
export function civilInput(intake: Intake): CivilInput {
  const role = civilRole(intake);
  const lawyer = intake.lawyer === "" ? null : intake.lawyer === "yes";
  return {
    text: intake.maskedText || fullText(intake),
    role,
    search_text: intake.searchText || null,
    mid: primaryMid(intake),
    court: intake.court || null,
    plaintiff_has_lawyer: role === "plaintiff" ? lawyer : null,
    defendant_has_lawyer: role === "defendant" ? lawyer : null,
    defendant_type: intake.defendantType || null,
    claimed_amount: parseAmount(intake.claimedAmount),
    evidence: intake.evidence,
  };
}

interface IntakeContextValue {
  intake: Intake;
  update: (patch: Partial<Intake>) => void;
  reset: () => void;
}

const IntakeContext = createContext<IntakeContextValue | null>(null);

/** 讀回這個分頁先前填的內容；沒有、壞掉或瀏覽器不讓讀時，從空白開始。 */
export function loadIntake(): Intake {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_INTAKE;
    const saved = JSON.parse(raw);
    return saved && typeof saved === "object" ? { ...EMPTY_INTAKE, ...saved } : EMPTY_INTAKE;
  } catch {
    return EMPTY_INTAKE;
  }
}

function saveIntake(intake: Intake) {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(intake));
  } catch {
    // 無痕模式或儲存空間被封鎖：只是重新整理後不會還原
  }
}

/** initial：測試用的起始內容；沒給時從 sessionStorage 還原。 */
export function IntakeProvider({ children, initial }: { children: ReactNode; initial?: Intake }) {
  const [intake, setIntake] = useState<Intake>(() => initial ?? loadIntake());
  useEffect(() => saveIntake(intake), [intake]);
  const value = useMemo(
    () => ({
      intake,
      update: (patch: Partial<Intake>) => setIntake((prev) => ({ ...prev, ...patch })),
      reset: () => { clearReportCache(); setIntake(EMPTY_INTAKE); },
    }),
    [intake],
  );
  return <IntakeContext.Provider value={value}>{children}</IntakeContext.Provider>;
}

export function useIntake(): IntakeContextValue {
  const ctx = useContext(IntakeContext);
  if (!ctx) throw new Error("useIntake 要在 IntakeProvider 裡使用");
  return ctx;
}
