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

/**
 * 個人資料保護法第 6 條的特種個資。法律沒有「健康資料」這個分類，
 * 醫療資料指醫事人員診察、治療、處方、施術產生的資料（施行細則第 4 條），所以「受傷」「傷害」這類日常用語不算。
 * 這是關鍵字比對，一定有漏網的說法；界定方式公開前要請律師確認。
 */
export const SENSITIVE_KINDS: { label: string; pattern: RegExp }[] = [
  { label: "病歷、醫療", pattern: /病歷|診斷|住院|手術|開刀|鋼釘|縫合|縫了|醫院|診所|就醫|看診|門診|急診|驗傷|復健|用藥|處方|骨折|癌症|中風|憂鬱症|精神科|身心障礙/ },
  { label: "健康檢查", pattern: /健康檢查|體檢/ },
  { label: "基因", pattern: /基因|遺傳疾病/ },
  { label: "性生活", pattern: /性取向|性傾向|性行為|性關係|同性戀|雙性戀/ },
  { label: "犯罪前科", pattern: /前科|緩起訴|有罪確定|判刑確定|服刑|假釋|入監|坐牢/ },
];

export function sensitiveKinds(text: string): string[] {
  return SENSITIVE_KINDS.filter((k) => k.pattern.test(text)).map((k) => k.label);
}

/** 把遮名後的文字切成一般文字與【標記】，給預覽畫面上色。 */
export function splitMasked(text: string): { text: string; masked: boolean }[] {
  return text
    .split(/(【[^】]{1,10}】)/)
    .filter((part) => part !== "")
    .map((part) => ({ text: part, masked: /^【[^】]{1,10}】$/.test(part) }));
}

/**
 * 金額輸入：允許「648000」「648,000」「50萬」「1.5萬」「64萬8千」「64萬8000」「8千」，
 * 前後可以有「NT$」「新臺幣」「元」，數字可以是全形。看不懂就回傳 null；中文數字（五十萬）不認。
 */
export function parseAmount(input: string): number | null {
  const s = input
    .replace(/[０-９]/g, (d) => String.fromCharCode(d.charCodeAt(0) - 0xfee0))
    .replace(/[．]/g, ".")
    .replace(/[,，\s]/g, "")
    .replace(/^(?:NT\$|NTD|\$|新臺幣|新台幣)/i, "")
    .replace(/元$/, "");
  if (!s) return null;
  let n: number;
  const wan = s.match(/^(\d+(?:\.\d+)?)萬(?:(\d+(?:\.\d+)?)(千)?)?$/);
  const qian = s.match(/^(\d+(?:\.\d+)?)千$/);
  if (wan) {
    const rest = wan[2] ? parseFloat(wan[2]) * (wan[3] ? 1000 : 1) : 0;
    if (!wan[3] && rest >= 10000) return null;          // 「5萬20000」看不懂
    n = parseFloat(wan[1]) * 10000 + rest;
  } else if (qian) {
    n = parseFloat(qian[1]) * 1000;
  } else if (/^\d+(?:\.\d+)?$/.test(s)) {
    n = parseFloat(s);
  } else {
    return null;
  }
  return Number.isFinite(n) ? Math.round(n) : null;
}
