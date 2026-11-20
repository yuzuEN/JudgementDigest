import { useState } from "react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import type { Reasoning, ReasoningItem, ReasoningQuote, SimilarCase } from "../../api/types";
import { outcomeLabel, outcomeTone } from "../../format";
import { InfoLink } from "../Common";
import { LinkButton } from "../LinkButton";
import { OutcomeChip } from "./OutcomeChip";

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

function Tag({ item }: { item: { polarity?: string | null } }) {
  if (!item.polarity) return null;
  return (
    <span className="inline-flex w-fit flex-none items-center rounded-full border-[1.5px] border-input bg-muted px-2.5 text-sm leading-[1.8] font-bold whitespace-nowrap text-foreground">
      {item.polarity}
    </span>
  );
}

/** 每組先顯示幾處；長判決（例如結論 17 處）其餘收起來，才不會把後面的分組擠到很下面 */
export const GROUP_PREVIEW = 3;

function ReasoningGroup({ group: g, active, onSelect }: {
  group: ReturnType<typeof shownGroups>[number];
  active: number | null;
  onSelect: (index: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const hidden = g.items.length - GROUP_PREVIEW;
  // 選到的項目在收起的部分時（例如從段落標示回來），整組展開
  const expanded = open || hidden <= 0 || g.items.slice(GROUP_PREVIEW).some((x) => x.index === active);
  const items = expanded ? g.items : g.items.slice(0, GROUP_PREVIEW);
  return (
    <section aria-labelledby={`reasoning-${g.label}`} className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 id={`reasoning-${g.label}`} className="text-base font-bold">{g.title}</h3>
        <span className="text-sm text-muted-foreground">{g.items.length} 處</span>
      </div>
      <p className="text-sm text-muted-foreground">{g.hint}</p>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {items.map(({ item, index }) => (
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
      {hidden > 0 && (
        <button type="button" aria-expanded={expanded} onClick={() => setOpen(!expanded)}
          className="no-print min-h-11 w-fit rounded-[10px] px-2 text-[15px] font-bold text-primary hover:bg-accent">
          {expanded ? "收起" : `顯示全部 ${g.items.length} 處`}
        </button>
      )}
      {g.status === "note" && <p className="text-sm text-muted-foreground">這類標示的抽查正確率較低，請特別對照原文。</p>}
    </section>
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
      {groups.map((g) => <ReasoningGroup key={g.label} group={g} active={active} onSelect={onSelect} />)}
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

/* ── 相似判決列表與「可能的金額」分頁（B、C）── */

/** 只留抽查後可以顯示的標籤（和導讀頁同一套 REASONING_SHOWN） */
const shownQuotes = (items: ReasoningQuote[] | null | undefined) => (items ?? []).filter((x) => REASONING_SHOWN[x.label]);

/** 列表摘要挑哪一句：金額怎麼決定 → 法律上怎麼認定 → 依常理怎麼判斷（EV 抽查正確率較低，不放在摘要） */
const BRIEF_ORDER = ["DAM", "SUB", "EXP"];

/** 結論方向固定這個順序顯示，不照判決裡出現的順序 */
const DIRECTION_ORDER = ["有理由", "一部有理由", "無理由"];

/**
 * 金額的斟酌：慰撫金（精神上損害）最需要法院裁量，排在前面；其餘照判決裡的順序。
 * 引文不一定寫出「慰撫金」（例如「認原告分別請求227,400元⋯尚屬過高，應分別以33,045元為宜」），
 * 所以「過高」「一切情狀」這種酌定慰撫金的典型寫法也算。
 */
const SOLATIUM = /慰撫金|慰藉金|精神|過高|一切情狀/;
export const damFirst = (items: ReasoningQuote[]) =>
  [...items.filter((x) => SOLATIUM.test(x.text)), ...items.filter((x) => !SOLATIUM.test(x.text))];

/**
 * 相似判決列表每件下面的一行：「法院怎麼認定」＋結論方向，以及一句原文。
 * 沒有標註的判決不顯示（目前只有部分判決有標註）。
 */
export function ReasoningBrief({ items }: { items?: ReasoningQuote[] | null }) {
  const shown = shownQuotes(items);
  if (shown.length === 0) return null;
  const found = new Set(shown.filter((x) => x.label === "CONCL" && x.polarity).map((x) => x.polarity!));
  const directions = [...DIRECTION_ORDER.filter((d) => found.has(d)), ...[...found].filter((d) => !DIRECTION_ORDER.includes(d))];
  const pick = BRIEF_ORDER.map((label) => damFirst(shown.filter((x) => x.label === label))[0]).find(Boolean);
  const title = pick && REASONING_GROUPS.find((g) => g.label === pick.label)?.title;
  if (directions.length === 0 && !pick) return null;
  return (
    <span className="mt-1.5 flex flex-col gap-1 text-sm">
      <span className="flex flex-wrap items-center gap-1.5">
        <span className="text-muted-foreground">法院怎麼認定</span>
        {directions.map((d) => (
          <span key={d} className="rounded-full border border-input bg-secondary px-2 leading-6 text-secondary-foreground">{d}</span>
        ))}
        {directions.length > 0 && <InfoLink to="有理由、一部有理由、無理由" label="有理由、一部有理由、無理由的說明" />}
      </span>
      {pick && (
        <span className="line-clamp-2 leading-relaxed text-foreground print:line-clamp-none">
          <b>{title}：</b>「{displayQuote(pick.quote)}」
        </span>
      )}
    </span>
  );
}

/**
 * 先顯示引文：太長的引文是「開頭⋯⋯結尾」，結尾通常就是法院定的金額（例如「以15萬元為適當」），
 * 直接截斷全文反而會把結論切掉。需要時再展開完整原文。
 */
function DamQuote({ item }: { item: ReasoningQuote }) {
  const [full, setFull] = useState(false);
  const short = displayQuote(item.quote);
  const long = item.text !== item.quote;
  return (
    <>
      <span className={cn("text-[15px] leading-relaxed", !full && "line-clamp-4 print:line-clamp-none")}>「{full ? item.text : short}」</span>
      {long && (
        <button type="button" aria-expanded={full} onClick={() => setFull(!full)}
          className="no-print min-h-11 w-fit rounded-[10px] px-2 text-sm font-bold text-primary hover:bg-accent">
          {full ? "收起原文" : "看完整原文"}
        </button>
      )}
    </>
  );
}

const MAX_DAM_QUOTES = 2;   // 每件判決最多列幾處金額的斟酌（慰撫金優先），其餘到判決導讀看
export const DAM_CASES_PREVIEW = 5;   // 先列幾件判決，其餘按「顯示其他 N 件」
const yuan = (n: number | null | undefined) => (n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-US"));

/**
 * 「可能的金額」分頁下面：相似判決的法院怎麼決定金額（DAM 的原文並排）。
 * 金額範圍只告訴你「判多少」，這裡讓你看到「為什麼判這麼多」：法院斟酌了哪些因素。
 */
export function DamageReasons({ cases }: { cases: SimilarCase[] }) {
  const [open, setOpen] = useState(false);
  const rows = cases
    .map((c) => ({ c, items: damFirst(shownQuotes(c.reasoning).filter((x) => x.label === "DAM")) }))
    .filter((r) => r.items.length > 0);
  if (rows.length === 0) return null;
  const hidden = rows.length - DAM_CASES_PREVIEW;
  return (
    <section aria-labelledby="damage-reasons-title" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <h3 className="flex items-center gap-1 text-lg font-bold">
          <span id="damage-reasons-title">相似判決的法院怎麼決定金額</span><InfoLink to="法院怎麼認定" label="法院怎麼認定的說明" />
        </h3>
        <p className="text-[15px] text-muted-foreground">
          範圍只說明判多少；下面是 {rows.length} 件相似判決裡，法院斟酌金額的原文，可以看出法院考量了哪些因素。
          「酌減」是判准的比請求的少。<InfoLink to="酌減" label="酌減的說明" />
        </p>
      </div>
      <ul className="m-0 flex list-none flex-col gap-3 p-0">
        {(open || hidden <= 0 ? rows : rows.slice(0, DAM_CASES_PREVIEW)).map(({ c, items }) => (
          <li key={c.case_id} className="flex flex-col gap-2 rounded-[12px] border-2 border-input bg-card px-3.5 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <b className="text-[15px]">{c.case_number}</b>
              <OutcomeChip tone={outcomeTone(c.outcome)}>{outcomeLabel(c.outcome)}</OutcomeChip>
              {c.claimed_amount ? (
                <span className="text-sm text-muted-foreground tabular-nums">判准 <b className="text-foreground">{yuan(c.awarded_amount ?? 0)}</b> ／ 請求 {yuan(c.claimed_amount)} 元</span>
              ) : null}
            </div>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {items.slice(0, MAX_DAM_QUOTES).map((it, i) => (
                <li key={i} className="flex flex-col gap-1">
                  <Tag item={it} />
                  <DamQuote item={it} />
                </li>
              ))}
            </ul>
            <span className="flex flex-wrap items-center gap-3">
              {items.length > MAX_DAM_QUOTES && <span className="text-sm text-muted-foreground">還有 {items.length - MAX_DAM_QUOTES} 處</span>}
              <LinkButton variant="outline" size="sm" to={`/judgment/civil/${c.case_id}`} className="no-print"
                aria-label={`${c.case_number} 判決導讀`}>判決導讀</LinkButton>
            </span>
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
          className="no-print min-h-11 w-fit rounded-[10px] px-2 text-[15px] font-bold text-primary hover:bg-accent">
          {open ? "收起" : `顯示其他 ${hidden} 件`}
        </button>
      )}
      <p className="text-sm text-muted-foreground">由 AI 依標註手冊標註、人工抽查，可能有誤，請以判決原文為準。只有部分判決有標註。</p>
    </section>
  );
}
