import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { CaseType, CivilInput, DefendantType } from "./api/types";
import { parseAmount } from "./format";

// 使用者填的內容只放在記憶體裡（重新整理就會清空），不寫進瀏覽器的儲存空間，也不送去保存。
export interface Intake {
  caseType: CaseType;
  text: string;
  mid: string;
  court: string;
  lawyer: "yes" | "no" | "";
  defendantType: DefendantType | "";
  claimedAmount: string;
  evidence: string[];
  followupAnswers: Record<string, { question: string; answer: string }>;
  names: string[];
  maskedText: string;
  healthConsent: boolean;
}

export const EMPTY_INTAKE: Intake = {
  caseType: "civil",
  text: "",
  mid: "",
  court: "",
  lawyer: "",
  defendantType: "",
  claimedAmount: "",
  evidence: [],
  followupAnswers: {},
  names: [],
  maskedText: "",
  healthConsent: false,
};

/** 描述加上追問的回答，作為遮名與送出的全文。 */
export function fullText(intake: Intake): string {
  const extra = Object.values(intake.followupAnswers)
    .filter((a) => a.answer.trim())
    .map((a) => `追問：${a.question}\n回答：${a.answer.trim()}`);   // 後端靠這兩個開頭分辨問題和回答
  return [intake.text.trim(), ...extra].filter(Boolean).join("\n");
}

/** 送給民事 API 的內容：一律用遮名後的文字。 */
export function civilInput(intake: Intake): CivilInput {
  return {
    text: intake.maskedText || fullText(intake),
    mid: intake.mid || null,
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
