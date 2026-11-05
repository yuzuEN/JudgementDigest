// 顯示用的小工具：金額、比例、判決結果的標籤。

/** 新臺幣金額：1 萬以上寫成「31 萬」「1.2 萬」，以下寫成「8,000 元」。 */
export function money(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (Math.abs(n) >= 10000) {
    const wan = n / 10000;
    return `${wan >= 100 ? Math.round(wan).toLocaleString("zh-TW") : Number(wan.toFixed(1)).toLocaleString("zh-TW")} 萬`;
  }
  return `${Math.round(n).toLocaleString("zh-TW")} 元`;
}

export function percent(p: number, digits = 0): string {
  return `${(p * 100).toFixed(digits)}%`;
}

export type Tone = "win" | "partial" | "lose" | "neutral";

export function outcomeTone(outcome: string): Tone {
  if (outcome === "勝訴" || outcome === "確認勝訴") return "win";
  if (outcome.startsWith("一部勝訴")) return "partial";
  if (outcome === "敗訴") return "lose";
  return "neutral";
}

export function outcomeLabel(outcome: string): string {
  return outcome === "一部勝訴一部敗訴" ? "一部勝訴" : outcome;
}

/** 描述裡有健康、醫療相關的內容時，送出前要另外取得同意（個資法第 6 條的特種個資）。 */
export const HEALTH_RE = /受傷|傷害|傷口|骨折|住院|手術|開刀|鋼釘|縫合|縫了|診斷|病歷|醫院|診所|就醫|看診|驗傷|復健|休養|看護|疾病|生病|懷孕|中風|癌症|精神科|憂鬱|失眠|身心障礙/;

export function needsHealthConsent(text: string): boolean {
  return HEALTH_RE.test(text);
}

/** 把遮名後的文字切成一般文字與【標記】，給預覽畫面上色。 */
export function splitMasked(text: string): { text: string; masked: boolean }[] {
  return text
    .split(/(【[^】]{1,10}】)/)
    .filter((part) => part !== "")
    .map((part) => ({ text: part, masked: /^【[^】]{1,10}】$/.test(part) }));
}

/** 金額輸入：允許「50萬」「500,000」「500000元」。看不懂就回傳 null。 */
export function parseAmount(input: string): number | null {
  const s = input.replace(/[,，\s元]/g, "");
  if (!s) return null;
  const m = s.match(/^(\d+(?:\.\d+)?)(萬)?$/);
  if (!m) return null;
  const n = parseFloat(m[1]) * (m[2] ? 10000 : 1);
  return Number.isFinite(n) ? Math.round(n) : null;
}
