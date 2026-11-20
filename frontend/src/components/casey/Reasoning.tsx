import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import type { Reasoning, ReasoningItem } from "../../api/types";

/**
 * 判決導讀「法院怎麼認定」（D3）。
 * 依《論點標註手冊》由 LLM 標出法院在判決理由裡做了哪些動作，每項附原文；點一下捲到那一段並標出引文。
 * 新元件：shadcn 沒有「可點的引文清單」，用 Card ＋ 原生 button 組成，顏色只用既有 token。
 */

/** 卡片上的分組與順序（標籤代碼見 annotation/論點標註手冊）。 */
export const REASONING_GROUPS: { label: string; title: string; hint: string }[] = [
  { label: "CONCL", title: "法院的結論", hint: "每項請求准不准" },
  { label: "SUB", title: "法律上怎麼認定", hint: "把事實套進法律要件" },
  { label: "EV", title: "證據怎麼評價", hint: "採信或不採信哪些證據" },
  { label: "DAM", title: "金額怎麼決定", hint: "賠償或給付金額的斟酌" },
  { label: "EXP", title: "依常理怎麼判斷", hint: "法院用一般經驗、常情或社會通念判斷" },
  { label: "BOP", title: "舉證責任", hint: "應該由誰證明" },
];

/**
 * 哪些標籤顯示在卡片上，由人工抽查決定（手冊 v0.6 第七節）：
 *   ok    95% CI 下界 ≥ 0.80（25 個裡最多錯 1 個）→ 顯示
 *   note  下界約 0.75（錯 2 個）→ 顯示，但附註「請特別對照原文」
 *   沒列出 → 不顯示（包括還沒抽查過的標籤，例如 BOP）
 * v0.6 抽查（290 個論點單位 × 3 次）：DAM 25/25、SUB 24/25、EXP 23/24；CONCL 沿用 v0.5 的 25/25（v0.6 回歸 10/10）。
 * EV 整體 21/25；匯出時只留引文通過規則十的（annotation/guide_batch.py），這部分是 19/20 → note。
 * BOP 沒有抽查過，不顯示。
 */
export const REASONING_SHOWN: Record<string, "ok" | "note"> = {
  CONCL: "ok",
  SUB: "ok",
  DAM: "ok",
  EXP: "ok",
  EV: "note",
};

/** 引文太長時是「開頭〔略〕結尾」，畫面上改成刪節號 */
export const displayQuote = (q: string) => q.replace("〔略〕", "⋯⋯");

/** 卡片要顯示的項目：只留 REASONING_SHOWN 裡的標籤，依 REASONING_GROUPS 分組 */
export function shownGroups(reasoning: Reasoning | null | undefined) {
  const items = (reasoning?.items ?? []).map((item, index) => ({ item, index }));
  return REASONING_GROUPS
    .filter((g) => REASONING_SHOWN[g.label])
    .map((g) => ({ ...g, status: REASONING_SHOWN[g.label], items: items.filter((x) => x.item.label === g.label) }))
    .filter((g) => g.items.length > 0);
}

function Tag({ item }: { item: ReasoningItem }) {
  if (!item.polarity) return null;
  return (
    <span className="inline-flex w-fit flex-none items-center rounded-full border-[1.5px] border-input bg-muted px-2.5 text-sm leading-[1.8] font-bold whitespace-nowrap text-foreground">
      {item.polarity}
    </span>
  );
}

export function ReasoningCard({ reasoning, active, onSelect }: {
  reasoning: Reasoning | null | undefined;
  active: number | null;
  onSelect: (index: number) => void;
}) {
  const groups = shownGroups(reasoning);
  if (!reasoning || groups.length === 0) return null;
  return (
    <Card className="gap-4 px-6.5" aria-labelledby="reasoning-title">
      <div className="flex flex-col gap-1.5">
        <h2 id="reasoning-title" className="text-xl font-bold">法院怎麼認定</h2>
        <p className="text-[15px] text-muted-foreground">點一下，右邊的全文會捲到那一段，並標出這句原文。</p>
      </div>
      {groups.map((g) => (
        <section key={g.label} aria-labelledby={`reasoning-${g.label}`} className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <h3 id={`reasoning-${g.label}`} className="text-base font-bold">{g.title}</h3>
            <span className="text-sm text-muted-foreground">{g.items.length} 處</span>
          </div>
          <p className="text-sm text-muted-foreground">{g.hint}</p>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {g.items.map(({ item, index }) => (
              <li key={index}>
                <button type="button" aria-pressed={active === index} onClick={() => onSelect(index)}
                  className={cn("flex w-full min-h-11 flex-col gap-1.5 rounded-[12px] border-2 bg-card px-3.5 py-2.5 text-left",
                    active === index ? "border-primary" : "border-input")}>
                  <Tag item={item} />
                  <span className="text-[15px] leading-relaxed">「{displayQuote(item.quote)}」</span>
                </button>
              </li>
            ))}
          </ul>
          {g.status === "note" && <p className="text-sm text-muted-foreground">這類標示的抽查正確率較低，請特別對照原文。</p>}
        </section>
      ))}
      <p className="text-sm text-muted-foreground">
        依標註手冊 {reasoning.manual_version} 由 AI 標註、人工抽查，可能有誤，請以判決原文為準。
      </p>
    </Card>
  );
}

/** 段落文字：選到的引文用 mark 標出（只標在這一段裡的部分） */
export function MarkedText({ text, item }: { text: string; item: ReasoningItem | null }) {
  if (!item || item.start < 0 || item.end <= item.start || item.end > text.length) return <>{text}</>;
  return (
    <>
      {text.slice(0, item.start)}
      <mark className="rounded-[4px] bg-info px-0.5 text-foreground ring-2 ring-primary">{text.slice(item.start, item.end)}</mark>
      {text.slice(item.end)}
    </>
  );
}
