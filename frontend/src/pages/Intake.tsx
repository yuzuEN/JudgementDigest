import {
  ArrowLeftIcon, ArrowLeftRightIcon, ArrowRightIcon, CameraIcon, CheckIcon, ClipboardListIcon, FilePenLineIcon, InfoIcon,
  MessageSquareQuoteIcon, MessagesSquareIcon, ReceiptTextIcon, SearchIcon, ShieldCheckIcon, StethoscopeIcon, UsersIcon, VideoIcon,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api } from "../api/client";
import type { CaseType, DefendantType, Options } from "../api/types";
import { AmountInput, amountState } from "../components/casey/AmountInput";
import { EvidenceSlot } from "../components/casey/EvidenceSlot";
import { RadioCards } from "../components/casey/RadioCards";
import { ErrorBox } from "../components/Common";
import { Layout, PAGE } from "../components/Layout";
import { parseAmount } from "../format";
import { DISPUTE_GROUPS } from "../knowledge";
import { useIntake, type Intake as IntakeState } from "../state";

export const MIN_STORY = 30;
export const MAX_STORY = 3000;

const CASE_TYPES: { value: CaseType; title: string; hint: string }[] = [
  { value: "civil", title: "民事", hint: "要求賠償、還錢、履行契約" },
  { value: "criminal", title: "刑事", hint: "被警察、檢察官調查，或想告對方犯罪" },
  { value: "unsure", title: "不確定", hint: "兩邊都幫我看，結果會有民事、刑事兩個分頁" },
];

const TYPE_LABEL: Record<CaseType, string> = { civil: "民事", criminal: "刑事", unsure: "不確定" };

/** 選了類型之後，告訴使用者會得到什麼。 */
const YOU_GET: Record<CaseType, string[]> = {
  civil: ["相似判決裡，原告贏的比例", "可能判准的金額範圍", "相似的真實判決、證據對照、對方常見的說法"],
  criminal: ["可能的罪名與法條", "刑期落在哪個範圍", "相似的真實判決"],
  unsure: ["結果頁有民事、刑事兩個分頁", "兩邊都幫你看"],
};

const SCENE_LINES: Record<number, string> = {
  1: "你好，我是 CasEY 的整理員。接下來一次只問一件事。先告訴我，你遇到的事比較像哪一種？",
  2: "請說說發生了什麼事：時間、地點、對方做了什麼、你的損失。寫不完整也沒關係，下面的提示會亮起來。",
  3: "最後幾項資料。證物欄點一下就是「有」，不用上傳任何東西。",
};

/** 寫作提示：寫到就亮起來，只是提示，不擋下一關。 */
const WRITING_HINTS: [string, RegExp][] = [
  ["時間", /\d+\s*(年|月|日|號|點)|今天|昨天|前天|去年|今年|前年|上個?月|上午|下午|晚上|早上|凌晨/],
  ["地點", /路|街|店|公司|學校|醫院|路口|家|市|縣|區|鄉|鎮|超商|停車場/],
  ["對方做了什麼", /對方|被告|他|她|公司|房東|老闆|撞|說|打|借|騙/],
  ["損失（金額或傷勢）", /\d+\s*(元|萬|千)|[一二三四五六七八九十兩幾]+\s*[萬千]|受傷|骨折|住院|全毀|損失|醫藥費/],
];

const DEFENDANT_TYPES: { value: DefendantType; label: string }[] = [
  { value: "person", label: "個人" },
  { value: "company", label: "公司" },
  { value: "government", label: "政府機關、學校、醫院" },
];

/** 民事證據的圖示，key 對應 /meta/options 的 evidence。 */
const CIVIL_EVIDENCE_ICON: Record<string, LucideIcon> = {
  medical: StethoscopeIcon,
  receipt: ReceiptTextIcon,
  transfer: ArrowLeftRightIcon,
  chat: MessagesSquareIcon,
  contract: FilePenLineIcon,
  video: CameraIcon,
};

/** 刑事沒有基本問題，只問律師和手上的證據；會加在描述後面一起送出（刑事 API 只收文字）。 */
const CRIMINAL_EVIDENCE: { label: string; icon: LucideIcon }[] = [
  { label: "驗傷單、診斷證明", icon: StethoscopeIcon },
  { label: "監視器、行車紀錄器畫面", icon: VideoIcon },
  { label: "照片、影片", icon: CameraIcon },
  { label: "LINE、簡訊、錄音", icon: MessagesSquareIcon },
  { label: "報案紀錄（報案三聯單）", icon: ClipboardListIcon },
  { label: "證人", icon: UsersIcon },
  { label: "轉帳、匯款紀錄", icon: ArrowLeftRightIcon },
  { label: "對方承認的對話或文字", icon: MessageSquareQuoteIcon },
];

const SUMMARY: Record<string, string> = Object.fromEntries(DISPUTE_GROUPS.flatMap((g) => g.types.map((t) => [t.id, t.summary])));

function toggle(list: string[], key: string) {
  return list.includes(key) ? list.filter((k) => k !== key) : [...list, key];
}

function storyLength(text: string) {
  return text.trim().length;
}

function readStage(raw: string | null): 1 | 2 | 3 {
  return raw === "2" ? 2 : raw === "3" ? 3 : 1;
}

/** 這一關為什麼還不能往下；可以就回傳 null。 */
function blocker(stage: number, intake: IntakeState): string | null {
  if (stage === 2 && storyLength(intake.text) < MIN_STORY) return `案情至少要 ${MIN_STORY} 字。`;
  if (stage === 3 && amountState(intake.claimedAmount) === "bad") return "金額格式不對，請修改。";
  return null;
}

export default function Intake() {
  const { intake, update } = useIntake();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const stage = readStage(params.get("stage"));
  const [options, setOptions] = useState<Options | null>(null);
  const [error, setError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);

  const load = () => {
    setError("");
    api.options().then(setOptions).catch((e: Error) => setError(e.message));
  };
  useEffect(load, []);

  // 換關時把焦點移到這一關的標題（螢幕報讀會念出來，畫面也會捲過去）
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    heading.current?.focus();
  }, [stage]);

  // 直接開第 3 關、但案情還不夠時，回到第 2 關
  if (stage === 3 && storyLength(intake.text) < MIN_STORY) return <Navigate to="/start?stage=2" replace />;

  const go = (n: number) => setParams({ stage: String(n) });
  const why = blocker(stage, intake);
  const civil = intake.caseType !== "criminal";
  const titleProps = { ref: heading, tabIndex: -1, className: "text-[22px] leading-[1.45] font-extrabold text-balance outline-none sm:text-[26px]" };

  return (
    <Layout stage={stage} scene={{ who: "organizer", line: SCENE_LINES[stage], note: stage === 1 }}>
      <div className={cn(PAGE, "pt-7 pb-16")}>
        <div className="flex flex-wrap items-start gap-7">
          <main className="flex min-w-0 flex-[999_1_560px] flex-col gap-6">
            {stage === 1 && (
              <StageCard>
                <h1 {...titleProps}>第 1 關　這是哪一類的事情？</h1>
                <RadioCards label="案件類型" value={intake.caseType} options={CASE_TYPES} onChange={(caseType) => update({ caseType })} />
                <Note>
                  <p className="font-bold">選{TYPE_LABEL[intake.caseType]}，你會得到：</p>
                  <ul className="m-0 list-disc pl-5 text-[15px]">
                    {YOU_GET[intake.caseType].map((g) => <li key={g}>{g}</li>)}
                  </ul>
                </Note>
              </StageCard>
            )}

            {stage === 2 && (
              <StageCard>
                <h1 {...titleProps}>第 2 關　發生了什麼事？</h1>
                <StoryField value={intake.text} onChange={(text) => update({ text })} />
                {intake.caseType === "criminal" ? <CriminalTips /> : (
                  <>
                    {error && <ErrorBox message={`選項載入失敗：${error}`} onRetry={load} />}
                    <DisputeKinds options={options} mids={intake.mids} onChange={(mids) => update({ mids })} />
                  </>
                )}
              </StageCard>
            )}

            {stage === 3 && (
              <StageCard>
                <h1 {...titleProps}>第 3 關　補幾項資料</h1>
                {error && <ErrorBox message={`選項載入失敗：${error}`} onRetry={load} />}
                {civil && (
                  <>
                    <CourtField courts={options?.courts ?? []} value={intake.court} onChange={(court) => update({ court })} />
                    <FieldBlock label={<label htmlFor="amount">想請求的金額</label>}>
                      <AmountInput id="amount" value={intake.claimedAmount} onChange={(claimedAmount) => update({ claimedAmount })} />
                    </FieldBlock>
                    <FieldBlock label={<span id="party-label">對方是</span>}>
                      <Segmented labelledBy="party-label" value={intake.defendantType} items={DEFENDANT_TYPES}
                        onChange={(v) => update({ defendantType: v as DefendantType | "" })} />
                    </FieldBlock>
                  </>
                )}
                <FieldBlock label={<span id="lawyer-label">有沒有請律師</span>}>
                  <Segmented labelledBy="lawyer-label" value={intake.lawyer} className="max-w-[320px]"
                    items={[{ value: "yes", label: "有" }, { value: "no", label: "沒有" }]}
                    onChange={(v) => update({ lawyer: v as IntakeState["lawyer"] })} />
                </FieldBlock>
                <FieldBlock label={<span id="evidence-label">證物欄</span>} hint="點一下＝手上有。只要勾選，不用上傳。">
                  <div role="group" aria-labelledby="evidence-label" className="grid grid-cols-[repeat(auto-fill,minmax(min(130px,100%),1fr))] gap-2.5">
                    {civil
                      ? (options?.evidence ?? []).map((e) => (
                          <EvidenceSlot key={e.key} label={e.label} icon={CIVIL_EVIDENCE_ICON[e.key] ?? FilePenLineIcon}
                            pressed={intake.evidence.includes(e.key)} onPressedChange={() => update({ evidence: toggle(intake.evidence, e.key) })} />
                        ))
                      : CRIMINAL_EVIDENCE.map((e) => (
                          <EvidenceSlot key={e.label} label={e.label} icon={e.icon}
                            pressed={intake.criminalEvidence.includes(e.label)}
                            onPressedChange={() => update({ criminalEvidence: toggle(intake.criminalEvidence, e.label) })} />
                        ))}
                  </div>
                </FieldBlock>
              </StageCard>
            )}

            <nav aria-label="關卡" className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center justify-between gap-3">
                {stage > 1 ? <Button type="button" variant="outline" onClick={() => go(stage - 1)}><ArrowLeftIcon data-icon="inline-start" />上一關</Button> : <span />}
                {stage < 3
                  ? <Button type="button" size="lg" disabled={!!why} onClick={() => go(stage + 1)}>下一關<ArrowRightIcon data-icon="inline-end" /></Button>
                  : <Button type="button" size="lg" disabled={!!why} onClick={() => navigate("/confirm")}>下一章：確認內容<ArrowRightIcon data-icon="inline-end" /></Button>}
              </div>
              {why && <p role="status" className="flex items-start gap-1.5 text-[15px]"><InfoIcon className="mt-1 size-4 flex-none" aria-hidden="true" />{why}</p>}
              {stage === 3 && (
                <p className="flex items-start gap-1.5 text-[15px] text-muted-foreground">
                  <ShieldCheckIcon className="mt-1 size-4 flex-none" aria-hidden="true" />下一章會先讓你預覽，並遮掉姓名、身分證字號、電話。
                </p>
              )}
            </nav>
          </main>

          <Summary intake={intake} />
        </div>
      </div>
    </Layout>
  );
}

function StageCard({ children }: { children: ReactNode }) {
  return <Card className="gap-6 px-[18px] sm:px-6.5">{children}</Card>;
}

function Note({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-[14px] border border-info-line bg-info px-4 py-3.5">
      <InfoIcon className="mt-1 size-5 flex-none text-secondary-foreground" aria-hidden="true" />
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

function FieldBlock({ label, hint, children }: { label: ReactNode; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="font-bold">{label}{hint && <span className="text-[15px] font-medium text-muted-foreground">　{hint}</span>}</p>
      {children}
    </div>
  );
}

function StoryField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const len = storyLength(value);
  const ok = len >= MIN_STORY;
  return (
    <>
      <div className="flex flex-col gap-2">
        <label htmlFor="story" className="font-bold">用自己的話寫就好</label>
        <p id="story-hint" className="text-[15px] text-muted-foreground">也可以直接貼起訴書的「犯罪事實」或「事實及理由」。</p>
        <Textarea id="story" value={value} maxLength={MAX_STORY} aria-describedby="story-hint story-status"
          onChange={(e) => onChange(e.target.value)} className="min-h-[200px] resize-y"
          placeholder="例如：去年三月我騎機車在路口被一輛右轉的汽車撞到，右手骨折住院五天，之後復健三個月沒辦法工作……" />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span id="story-status" role="status" className={cn("text-[15px]", ok && "font-bold text-secondary-foreground")}>
            {ok ? "字數夠了，可以進下一關。" : `再多寫一點：至少 ${MIN_STORY} 字，才找得到相似判決。`}
          </span>
          <span className="text-sm text-muted-foreground tabular-nums">{value.length} / {MAX_STORY} 字</span>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <p className="text-[15px] font-bold">寫作提示（寫到就會亮起來）</p>
        <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
          {WRITING_HINTS.map(([name, re]) => {
            const hit = re.test(value);
            return (
              <li key={name} className={cn(
                "inline-flex min-h-9 items-center gap-1.5 rounded-full border-[1.5px] px-3 text-[15px] font-semibold",
                hit ? "border-primary bg-secondary text-secondary-foreground" : "border-input bg-card",
              )}>
                {hit && <CheckIcon className="size-4" aria-hidden="true" />}{name}<span className="sr-only">{hit ? "（已寫到）" : "（還沒寫到）"}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}

function CriminalTips() {
  return (
    <div className="flex flex-col gap-2 rounded-[18px] border border-dashed bg-card p-5">
      <h2 className="font-bold">刑事案件怎麼寫</h2>
      <ul className="m-0 flex list-disc flex-col gap-2 pl-5 text-[15px] text-muted-foreground">
        <li>寫清楚時間、地點、發生了什麼，以及你被指控（或想指控）什麼事。</li>
        <li>有起訴書或傳票，可以直接貼「犯罪事實」那一段。</li>
        <li>不用寫你認為的罪名，系統會從相似判決找出可能的罪名。</li>
      </ul>
    </div>
  );
}

type KindGroup = { category: string; items: { value: string; label: string }[] };

/** API 的分組裡同一類可能出現在好幾組，只在第一次出現的組顯示；組名開頭的「侵權：」這種前綴省略。 */
function kindGroups(options: Options | null, query: string): KindGroup[] {
  const seen = new Set<string>();
  const q = query.trim();
  return (options?.mid_groups ?? []).map((g) => ({
    category: g.category,
    items: g.mids.map((m) => m.value)
      .filter((v) => (seen.has(v) ? false : (seen.add(v), true)))
      .filter((v) => !q || v.includes(q) || (SUMMARY[v] ?? "").includes(q))
      .map((v) => ({ value: v, label: v.startsWith(`${g.category}：`) ? v.slice(g.category.length + 1) : v })),
  })).filter((g) => g.items.length > 0);
}

/** 糾紛類型：可搜尋、可多選；右邊顯示已選類型的說明。 */
function DisputeKinds({ options, mids, onChange }: { options: Options | null; mids: string[]; onChange: (mids: string[]) => void }) {
  const [query, setQuery] = useState("");
  const groups = kindGroups(options, query);
  return (
    <section aria-labelledby="kinds-title" className="flex flex-col gap-3">
      <h2 id="kinds-title" className="font-bold">糾紛類型<span className="text-[15px] font-medium text-muted-foreground">　可以選好幾個，不確定可以不選</span></h2>
      <div className="flex flex-wrap items-start gap-6">
        <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-3">
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input type="search" aria-label="搜尋糾紛類型" placeholder="打字找，例如：車禍、借錢、租金" value={query}
              onChange={(e) => setQuery(e.target.value)} className="pl-11" />
          </div>
          <div className="flex max-h-[420px] flex-col gap-3 overflow-y-auto pr-1">
            {options && groups.length === 0 && <p className="text-[15px] text-muted-foreground">找不到「{query}」。換個說法，或先不選也可以。</p>}
            {groups.map((g) => (
              <div key={g.category} className="flex flex-col gap-1.5">
                <p className="text-[15px] font-bold text-muted-foreground">{g.category}</p>
                <div className="flex flex-wrap gap-2">
                  {g.items.map((item) => {
                    const on = mids.includes(item.value);
                    return (
                      <Toggle key={item.value} pressed={on} onPressedChange={() => onChange(toggle(mids, item.value))} aria-label={item.value}
                        className={cn(
                          "h-auto min-h-11 gap-1.5 rounded-full border-[1.5px] px-3.5 text-[15px] font-semibold whitespace-normal",
                          "hover:border-primary hover:bg-card aria-pressed:bg-secondary aria-pressed:text-secondary-foreground aria-pressed:hover:bg-secondary",
                          on ? "border-primary" : "border-input bg-card",
                        )}>
                        {on && <CheckIcon className="size-4" aria-hidden="true" />}{item.label}
                      </Toggle>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
        <aside aria-label="已選類型的說明" className="flex min-w-0 flex-[1_1_260px] flex-col gap-2 rounded-[18px] border bg-muted p-5">
          <p className="font-bold">糾紛類型說明</p>
          {mids.length === 0 && <p className="text-[15px] text-muted-foreground">還沒選。選到的類型，說明會出現在這裡。</p>}
          {mids.map((m) => (
            <div key={m} className="flex flex-col gap-0.5 rounded-[12px] border-[1.5px] border-primary bg-card px-3 py-2.5">
              <p className="text-[15px] font-bold">
                <span className="mr-1.5 inline-flex items-center gap-1 text-sm text-secondary-foreground"><CheckIcon className="size-4" aria-hidden="true" />已選</span>{m}
              </p>
              <p className="text-[15px] text-muted-foreground">{SUMMARY[m] ?? "這一類的白話說明還在整理。"}</p>
            </div>
          ))}
          <p className="text-sm text-muted-foreground">分類依判決的案由和內容整理，不是法律上的正式分類。</p>
        </aside>
      </div>
    </section>
  );
}

function CourtField({ courts, value, onChange }: { courts: string[]; value: string; onChange: (court: string) => void }) {
  const items = [{ value: null as string | null, label: "不指定" }, ...courts.map((c) => ({ value: c as string | null, label: `${c}地方法院` }))];
  return (
    <FieldBlock label={<label htmlFor="court">打算在哪個法院？</label>} hint="可以不選">
      <Select items={items} value={value || null} onValueChange={(v) => onChange((v as string | null) ?? "")}>
        <SelectTrigger id="court" className="w-full max-w-[360px]"><SelectValue /></SelectTrigger>
        <SelectContent>
          {items.map((c) => <SelectItem key={c.label} value={c.value}>{c.label}</SelectItem>)}
        </SelectContent>
      </Select>
    </FieldBlock>
  );
}

/** 二選一、三選一：ToggleGroup 單選，再點一次可以取消（等於不確定）。 */
function Segmented({ labelledBy, value, items, onChange, className }: {
  labelledBy: string;
  value: string;
  items: { value: string; label: string }[];
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <ToggleGroup aria-labelledby={labelledBy} spacing={0} value={value ? [value] : []}
      onValueChange={(v: string[]) => onChange(v[0] ?? "")}
      className={cn("w-full overflow-hidden rounded-[12px] border-2 border-input bg-card", className)}>
      {items.map((it) => (
        <ToggleGroupItem key={it.value} value={it.value}
          className="h-auto min-h-[50px] flex-1 rounded-none border-l-2 border-input px-2 text-base font-bold whitespace-normal text-foreground first:border-l-0 hover:bg-secondary aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:hover:bg-primary">
          {it.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/** 右側「你填的資料」：每一關填的內容都看得到。 */
function Summary({ intake }: { intake: IntakeState }) {
  const civil = intake.caseType !== "criminal";
  const amount = parseAmount(intake.claimedAmount);
  const evidenceCount = civil ? intake.evidence.length : intake.criminalEvidence.length;
  const rows: [string, string][] = [
    ["案件類型", TYPE_LABEL[intake.caseType]],
    ["案情", intake.text.trim() ? `${intake.text.length} 字` : "還沒寫"],
    ...(civil ? [
      ["糾紛類型", intake.mids.length ? intake.mids.join("、") : "未選"],
      ["請求金額", amount !== null ? `${amount.toLocaleString("en-US")} 元` : amountState(intake.claimedAmount) === "bad" ? "格式錯誤" : "未填"],
      ["對方", DEFENDANT_TYPES.find((d) => d.value === intake.defendantType)?.label ?? "未選"],
    ] as [string, string][] : []),
    ["律師", intake.lawyer === "yes" ? "有" : intake.lawyer === "no" ? "沒有" : "未選"],
    ["證物", `${evidenceCount} 項`],
  ];
  return (
    <aside aria-labelledby="summary-title" className="w-full min-w-0 flex-[1_1_260px] sm:max-w-[340px]">
      <Card className="gap-4 px-6.5">
        <div className="flex items-center justify-between gap-2">
          <h2 id="summary-title" className="text-xl font-bold">你填的資料</h2>
          <span className="text-sm text-muted-foreground">目前進度</span>
        </div>
        <dl className="m-0 flex flex-col gap-2 text-[15px]">
          {rows.map(([k, v]) => (
            <div key={k} className="flex items-start justify-between gap-3">
              <dt className="flex-none text-muted-foreground">{k}</dt>
              <dd className="m-0 text-right font-bold tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </aside>
  );
}
