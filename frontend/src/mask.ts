/**
 * 遮名在瀏覽器完成，原文和使用者輸入的姓名不會傳到伺服器。
 * 規則要和 retrieval/masking.py 一致，兩邊用同一份測試案例 test/masking_cases.json。
 * Python 的 \d、\w 會比對 Unicode，這裡要明確寫 \p{Nd}、\p{L}，否則行為不同。
 */
const TAGS = { id: "身分證字號", phone: "電話", email: "電子郵件", address: "地址", name: "姓名" } as const;
type Kind = keyof typeof TAGS;

const NUM = "[0-9０-９一二三四五六七八九十百之-]";
const CITY = "(?:[臺台](?:北|中|南|東)|新北|桃園|高雄|基隆|新竹|嘉義|苗栗|彰化|南投|雲林|屏東|宜蘭|花蓮|澎湖|金門|連江)[市縣]";
const WORD = "\\p{L}\\p{N}_";

const PATTERNS: [Kind, RegExp][] = [
  ["id", /(?<![A-Za-z0-9])[A-Z][12489]\p{Nd}{8}(?![0-9])/gu],
  ["email", new RegExp(`[${WORD}.+\\-]+@[${WORD}\\-]+(?:\\.[${WORD}\\-]+)+`, "gu")],
  ["phone", /(?<!\p{Nd})(?:\+886[-\s]?9|09)\p{Nd}{2}[-\s]?\p{Nd}{3}[-\s]?\p{Nd}{3}(?!\p{Nd})|(?<!\p{Nd})\(?0[2-8]\p{Nd}?\)?[-\s]?\p{Nd}{3,4}[-\s]?\p{Nd}{4}(?!\p{Nd})/gu],
  ["address", new RegExp(`${CITY}(?:[一-鿿]{1,3}?[區鄉鎮市])?[一-鿿]{1,6}?[路街道大道](?:${NUM}+段)?(?:${NUM}+巷)?(?:${NUM}+弄)?${NUM}+號(?:之${NUM}+)?(?:${NUM}+樓)?`, "gu")],
];

interface Span { start: number; end: number; kind: Kind }

/** 全形轉半形，長度不變，位置可以直接對回原文。 */
function halfWidth(text: string): string {
  return text.replace(/[！-～]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
}

function namePattern(names: string[]): RegExp | null {
  // 長的名字先比對：「王小明」不會先被「王小」吃掉
  const unique = [...new Set(names.map((n) => n.trim()).filter((n) => n.length > 0))];
  if (unique.length === 0) return null;
  unique.sort((a, b) => b.length - a.length);
  return new RegExp(unique.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "gu");
}

function findSpans(text: string, names: string[]): Span[] {
  const found: Span[] = [];
  const half = halfWidth(text);
  for (const [kind, rx] of PATTERNS) {
    for (const m of half.matchAll(rx)) found.push({ start: m.index, end: m.index + m[0].length, kind });
  }
  const pattern = namePattern(names);
  if (pattern) {
    for (const m of text.matchAll(pattern)) found.push({ start: m.index, end: m.index + m[0].length, kind: "name" });
  }
  found.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));
  const spans: Span[] = [];
  let last = -1;
  for (const s of found) {
    if (s.start >= last) {
      spans.push(s);
      last = s.end;
    }
  }
  return spans;
}

export function maskText(text: string, names: string[] = []): string {
  let out = "";
  let pos = 0;
  for (const s of findSpans(text, names)) {
    out += `${text.slice(pos, s.start)}【${TAGS[s.kind]}】`;
    pos = s.end;
  }
  return out + text.slice(pos);
}
