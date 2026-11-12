// API 的輸入輸出格式，和 backend/schemas.py 一一對應；改了要一起改。

export type CaseType = "civil" | "criminal" | "unsure";
export type DefendantType = "person" | "company" | "government";

export interface Health {
  status: string;
  civil: "model" | "mock";
  criminal: "model" | "mock";
  followup: "rules" | "llm";
  model: string | null;
  /** 民事金額範圍：有可用的獲償比例模型，或只用相似判決 */
  amount?: "model" | "similar" | "mock";
  /** 刑事的刑期用哪個模型；刑事是示例資料時為 null */
  criminal_sentence?: "electra" | "svm" | null;
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

export interface Question {
  id: string;
  text: string;
  skip_if?: string | null;
  why: string;
}

export interface FollowupResponse {
  questions: Question[];
  source: "rules" | "llm";
  llm_available?: boolean;
  llm_vendor?: string | null;
  fallback?: "not_dispute" | "error" | "limited" | null;
}

export interface CivilInput {
  text: string;
  search_text?: string | null;
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
  win_precision?: number | null;
  win_recall?: number | null;
  lose_precision?: number | null;
  lose_recall?: number | null;
  ece?: number | null;
}

export interface CivilPrediction {
  win_probability: number;
  signal: "strong" | "weak" | "insufficient";
  model: ModelInfo;
  warnings: string[];
  mock: boolean;
}

export interface AmountRange {
  /** model＝獲償比例模型推估；similar＝相似判決的分位數（沒有模型檔時）。舊版後端沒有這個欄位，視為 similar */
  source?: "model" | "similar";
  /** partial_win＝只針對「一部勝訴」；win＝勝訴與一部勝訴 */
  scope?: "win" | "partial_win";
  /** buckets 背後的相似判決件數；沒有相似判決時是 null */
  n_cases?: number | null;
  ratio_low: number;
  ratio_median: number;
  ratio_high: number;
  coverage: number;
  claimed?: number | null;
  amount_low?: number | null;
  amount_median?: number | null;
  amount_high?: number | null;
  buckets?: { low: number; high: number; count: number }[];
  /** 相似判決（對審、最多 30 件）裡勝訴與一部勝訴的件數，以及其中全部勝訴的件數 */
  n_wins?: number | null;
  n_full_wins?: number | null;
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
  url?: string | null;
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

export interface OutcomeCounts {
  total: number;
  win: number;
  partial: number;
  lose: number;
}

export interface RewriteResponse {
  text?: string | null;
  source: "llm" | "none";
  added_numbers: string[];
  fallback?: "no_llm" | "not_dispute" | "error" | "limited" | null;
}

export interface CivilReport {
  prediction: CivilPrediction;
  outcomes: OutcomeCounts;
  default_cases: number;
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
  law_note?: string | null;
  probability: number;
  sentence: { label: string; share: number }[];
  similar_sentence?: { label: string; share: number }[] | null;
  n_similar?: number | null;
}

export interface CriminalModelInfo {
  name: string;
  description: string;
  n_test?: number | null;
  charge_top1?: number | null;
  bucket_accuracy?: number | null;
  bucket_within_one?: number | null;
  /** 刑期另外用 ELECTRA 時才有；這時 bucket_* 是 ELECTRA 的分數 */
  sentence_description?: string | null;
  sentence_n_test?: number | null;
  sentence_test?: string | null;
}

export interface CriminalReport {
  charges: Charge[];
  similar: SimilarCase[];
  model?: CriminalModelInfo | null;
  mock: boolean;
}

export type GuideFunction = "claim" | "defense" | "issue" | "evidence" | "court";

export interface Guide {
  case: SimilarCase;
  paragraphs: { function: GuideFunction; label: string; text: string }[];
  labeler: string;
  mock: boolean;
}
