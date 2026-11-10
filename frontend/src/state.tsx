import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { CaseType, CivilInput, DefendantType } from "./api/types";
import { parseAmount } from "./format";

// 使用者填的內容只放在記憶體裡（重新整理就會清空），不寫進瀏覽器的儲存空間，也不送去保存。
export interface Intake {
  caseType: CaseType;
  text: string;
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
  searchText: string;    // 使用者確認過的改寫，只用來搜尋相似判決
  rewriteFor: string;    // 改寫時的遮名描述；描述改了，改寫就不能再用
}

export const EMPTY_INTAKE: Intake = {
  caseType: "civil",
  text: "",
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
};

/**
 * 送給 API 的案由中類。API 只收一個：只選一類就送那一類；
 * 沒選或選了好幾類就不送，讓系統從描述判斷。
 */
export function primaryMid(intake: Intake): string | null {
  return intake.mids.length === 1 ? intake.mids[0] : null;
}

/** 描述加上追問的回答（刑事再加上手上的證據），作為遮名與送出的全文。 */
export function fullText(intake: Intake): string {
  const extra = Object.values(intake.followupAnswers)
    .filter((a) => a.answer.trim())
    .map((a) => `追問：${a.question}\n回答：${a.answer.trim()}`);   // 後端靠這兩個開頭分辨問題和回答
  const evidence = intake.caseType === "criminal" && intake.criminalEvidence.length
    ? [`手上的證據：${intake.criminalEvidence.join("、")}`] : [];
  return [intake.text.trim(), ...extra, ...evidence].filter(Boolean).join("\n");
}

/** 送給民事 API 的內容：一律用遮名後的文字。 */
export function civilInput(intake: Intake): CivilInput {
  return {
    text: intake.maskedText || fullText(intake),
    search_text: intake.searchText || null,
    mid: primaryMid(intake),
    court: intake.court || null,
    plaintiff_has_lawyer: intake.lawyer === "" ? null : intake.lawyer === "yes",
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

export function IntakeProvider({ children, initial = EMPTY_INTAKE }: { children: ReactNode; initial?: Intake }) {
  const [intake, setIntake] = useState<Intake>(initial);
  const value = useMemo(
    () => ({
      intake,
      update: (patch: Partial<Intake>) => setIntake((prev) => ({ ...prev, ...patch })),
      reset: () => setIntake(EMPTY_INTAKE),
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
