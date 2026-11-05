// API 的輸入輸出格式，和 backend/schemas.py 一一對應；改了要一起改。

export type CaseType = "civil" | "criminal" | "unsure";
export type DefendantType = "person" | "company" | "government";

export interface Health {
  status: string;
  civil: "model" | "mock";
  criminal: "mock";
  followup: "rules" | "llm";
  model: string | null;
}

export interface MidOption {
  value: string;
  n: number;
}

export interface Options {
  mid_groups: { category: string; mids: MidOption[] }[];
  courts: string[];
  evidence: { key: string; label: string }[];
  mock: boolean;
}

export interface MaskedSpan {
  start: number;
  end: number;
  kind: string;
  label: string;
}

export interface MaskResponse {
  masked_text: string;
  spans: MaskedSpan[];
}

export interface Question {
  id: string;
  text: string;
  why: string;
}

export interface FollowupResponse {
  questions: Question[];
  source: "rules" | "llm";
  llm_available?: boolean;
  fallback?: "not_dispute" | "error" | "limited" | null;
}

export interface CivilInput {
  text: string;
  mid?: string | null;
  court?: string | null;
  plaintiff_has_lawyer?: boolean | null;
  defendant_type?: DefendantType | null;
  claimed_amount?: number | null;
  evidence: string[];
}

export interface ModelInfo {
  name: string;
  description: string;
  auc?: number | null;
  ece?: number | null;
}

export interface CivilPrediction {
  win_probability: number;
  model: ModelInfo;
  warnings: string[];
  mock: boolean;
}

export interface AmountRange {
  n_cases: number;
  ratio_low: number;
  ratio_median: number;
  ratio_high: number;
  coverage: number;
  claimed?: number | null;
  amount_low?: number | null;
  amount_median?: number | null;
  amount_high?: number | null;
}

export interface SimilarCase {
  source: "civil" | "criminal";
  case_id: number;
  case_number: string;
  court: string;
  year: string;
  mid: string;
  outcome: string;
  similarity: number;
  summary: string;
  claimed_amount?: number | null;
  awarded_amount?: number | null;
  sentence?: string | null;
  default_judgment?: boolean;
}

export interface EvidenceRow {
  key: string;
  label: string;
  share: number;
  user_has: boolean;
}

export interface DefenseRow {
  key: string;
  label: string;
  description: string;
  share: number;
}

export interface CivilReport {
  prediction: CivilPrediction;
  amount_range: AmountRange | null;
  similar: SimilarCase[];
  evidence: EvidenceRow[];
  defenses: DefenseRow[];
  n_compared: number;
  mock: boolean;
}

export interface Charge {
  name: string;
  law: string;
  probability: number;
  sentence: { label: string; share: number }[];
}

export interface CriminalReport {
  charges: Charge[];
  similar: SimilarCase[];
  mock: boolean;
}

export type GuideFunction = "claim" | "defense" | "issue" | "evidence" | "court";

export interface Guide {
  case: SimilarCase;
  paragraphs: { function: GuideFunction; label: string; text: string }[];
  labeler: string;
  mock: boolean;
}
