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
  /** 民事：和使用者的情況相同的地方（同類糾紛、請求金額相近、都有的證據、同一法院）；示例資料與舊版後端沒有 */
  common?: string[];
  /** 民事：有標註的判決才有「法院怎麼認定」；沒有標註、舊版後端時是 null 或不存在 */
  reasoning?: ReasoningQuote[] | null;
}

/** 相似判決列表用的「法院怎麼認定」：引文與它在判決裡的完整原文（不對段落） */
export interface ReasoningQuote {
  label: string;
  polarity?: string | null;
  basis?: string | null;
  /** 標註的引文（太長時是「開頭〔略〕結尾」） */
  quote: string;
  /** 引文在判決裡的完整原文 */
  text: string;
}

/** 相似判決是在哪個範圍裡找的 */
export interface SearchScope {
  n: number;
  /** 民事：限定的案由 */
  mid?: string | null;
  /** 民事：案由是系統從描述判斷的（使用者沒選） */
  mid_inferred?: boolean;
  /** 刑事：限定的罪名 */
  charge?: string | null;
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
  /** 檢索語料的總件數 */
  n_corpus?: number | null;
  search_scope?: SearchScope | null;
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
  /** 含這個罪名的相似判決；舊版後端與示例資料沒有，改用頂層的 similar */
  similar?: SimilarCase[];
  search_scope?: SearchScope | null;
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
  /** 刑事檢索語料的總件數 */
  n_corpus?: number | null;
  search_scope?: SearchScope | null;
  mock: boolean;
}

export type GuideFunction = "claim" | "defense" | "issue" | "evidence" | "court";
export type CriminalGuideFunction = "info" | "verdict" | "facts" | "evidence" | "court" | "laws" | "table" | "other";

/** 「法院怎麼認定」的一項：標註手冊的標籤與引文；paragraph 是 paragraphs 的序號，start/end 是在該段文字裡的位置 */
export interface ReasoningItem {
  label: string;
  polarity?: string | null;
  basis?: string | null;
  quote: string;
  paragraph: number;
  start: number;
  end: number;
  /** 引文跨段時，每一段要標的範圍；舊版後端沒有，就只標 paragraph 那一段 */
  parts?: ReasoningPart[];
}

export interface ReasoningPart {
  paragraph: number;
  start: number;
  end: number;
}

export interface Reasoning {
  labeler: string;
  manual_version: string;
  items: ReasoningItem[];
}

export interface Guide {
  case: SimilarCase;
  paragraphs: { function: GuideFunction; label: string; text: string }[];
  /** 民事「法院怎麼認定」：有標註的判決才有，沒有時是 null 或不存在 */
  reasoning?: Reasoning | null;
  /** 刑事導讀：全文依原本順序分段；沒有全文時是 null（只顯示摘要與原文連結） */
  criminal?: {
    source: "judgment" | "dataset";
    judgment_date?: string;
    paragraphs: { function: CriminalGuideFunction; label: string; text: string; pre?: boolean; part?: string | null }[];
  } | null;
  labeler: string;
  mock: boolean;
}
