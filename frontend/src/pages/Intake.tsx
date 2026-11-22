import {
  ArrowLeftIcon, ArrowLeftRightIcon, ArrowRightIcon, CameraIcon, CheckIcon, ChevronDownIcon, ClipboardListIcon, FilePenLineIcon, InfoIcon,
  ListChecksIcon, MessageSquareQuoteIcon, MessagesSquareIcon, ReceiptTextIcon, SearchIcon, ShieldCheckIcon, StethoscopeIcon, UsersIcon, VideoIcon,
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
import { api } from "../api/client";
import type { CaseType, CivilRole, DefendantType, Options } from "../api/types";
import { AmountInput, amountState } from "../components/casey/AmountInput";
import { EvidenceSlot } from "../components/casey/EvidenceSlot";
import { MidLabels } from "../components/casey/MidLabels";
import { RadioCards } from "../components/casey/RadioCards";
import { Segmented } from "../components/casey/Segmented";
import { ErrorBox } from "../components/Common";
import { Layout, PAGE } from "../components/Layout";
import { parseAmount } from "../format";
import { DISPUTE_GROUPS } from "../knowledge";
import { civilRole, lawyerQuestion, REWRITE_RESET, useIntake, type Intake as IntakeState } from "../state";

export const MIN_STORY = 30;
export const MAX_STORY = 3000;
export const MAX_DEFENSE = 2000;

const ROLES: { value: CivilRole; label: string }[] = [
  { value: "plaintiff", label: "原告：我要告對方" },
  { value: "defendant", label: "被告：我被告了" },
];
const ROLE_LABEL: Record<CivilRole, string> = { plaintiff: "原告", defendant: "被告" };

/** 角色的說明：「不確定」的人多半分不清楚，用收到什麼、誰要誰賠錢來判斷；刑事不分原告被告，選的是民事那邊。 */
const ROLE_HINT = {
  civil: "原告是提告的人，被告是被告的人。",
  unsure: "對方要你賠錢，或你收到法院寄來的起訴狀、開庭通知、支付命令，就選被告。刑事不分原告被告，這裡選的是民事那一邊。",
} as const;

/** 選了民事被告，會得到什麼（和 YOU_GET.civil 對照）。 */
const YOU_GET_DEFENDANT = ["相似判決裡，原告（告你的人）贏的比例", "如果輸了，可能要賠的金額範圍", "被告常見的說法，以及提出這些說法時原告輸的比例"];

const CASE_TYPES: { value: CaseType; title: string; hint: string }[] = [
  { value: "civil", title: "民事", hint: "要求賠償、還錢、履行契約" },
  { value: "criminal", title: "刑事", hint: "被警察、檢察官調查，或想告對方犯罪" },
  { value: "unsure", title: "不確定", hint: "同時查詢民事與刑事" },
];

const TYPE_LABEL: Record<CaseType | "", string> = { "": "還沒選", civil: "民事", criminal: "刑事", unsure: "不確定" };

/** 選了類型之後，告訴使用者會得到什麼。 */
const YOU_GET: Record<Exclude<CaseType, "unsure">, string[]> = {
  civil: ["相似判決裡，原告贏的比例", "可能判准的金額範圍", "相似的真實判決、證據對照、對方常見的說法"],
  criminal: ["可能的罪名與法條", "刑期落在哪個範圍", "相似的真實判決"],
};

const SCENE_LINES: Record<number, string> = {
  1: "如果分不清楚民事和刑事，選「不確定」就能同時查詢。",
  2: "請描述時間、地點、對方做了什麼，以及你的損失。不必使用法律用語。",
  3: "接著填寫案件資料，並勾選手上的證據，不需要上傳檔案。",
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

/**
 * 第 2 關的字數夠不夠往下：原告至少 MIN_STORY 字；被告只要不是空白就好
 * （被告常常只拿到開庭通知、沒有起訴狀，寫不出對方完整的主張；太短只提醒、不擋）。
 */
function storyEnough(intake: IntakeState): boolean {
  const len = storyLength(intake.text);
  return civilRole(intake) === "defendant" ? len > 0 : len >= MIN_STORY;
}

/** 這一關為什麼還不能往下；可以就回傳 null。 */
function blocker(stage: number, intake: IntakeState): string | null {
  if (stage === 1 && !intake.caseType) return "請先選一種案件類型。";
  if (stage === 2 && !storyEnough(intake)) {
    return civilRole(intake) === "defendant" ? "請先寫對方告你什麼。" : `案情至少要 ${MIN_STORY} 字。`;
  }
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

  // 還沒選類型就直接開第 2、3 關：回第 1 關；直接開第 3 關、但案情還不夠時，回到第 2 關
  if (stage > 1 && !intake.caseType) return <Navigate to="/start?stage=1" replace />;
  if (stage === 3 && !storyEnough(intake)) return <Navigate to="/start?stage=2" replace />;

  const go = (n: number) => setParams({ stage: String(n) });
  const why = blocker(stage, intake);
  const civil = intake.caseType !== "criminal";
  const role = civilRole(intake);
  const defendant = role === "defendant";
  const titleProps = { ref: heading, tabIndex: -1, className: "text-[22px] leading-[1.45] font-extrabold text-balance outline-none sm:text-[26px]" };

  return (
    <Layout stage={stage} scene={{ who: "organizer", line: SCENE_LINES[stage] }}>
      <div className={cn(PAGE, "pt-7 pb-16")}>
        <div className="flex flex-wrap items-start gap-7">
          <main className="flex min-w-0 flex-[999_1_560px] flex-col gap-6">
            {stage === 1 && (
              <StageCard>
                <h1 {...titleProps}>第 1 關　選擇案件類型</h1>
                <RadioCards label="案件類型" value={intake.caseType} options={CASE_TYPES}
                  onChange={(caseType) => update(caseType === intake.caseType ? { caseType } : { caseType, ...REWRITE_RESET })} />
                {(intake.caseType === "civil" || intake.caseType === "unsure") && (
                  <FieldBlock label={<span id="role-label">你是原告還是被告？</span>} hint={ROLE_HINT[intake.caseType]}>
                    <Segmented labelledBy="role-label" value={intake.role} items={ROLES} className="max-w-[520px]" required
                      onChange={(v) => update(v === intake.role ? { role: v as CivilRole } : { role: v as CivilRole, ...REWRITE_RESET })} />
                  </FieldBlock>
                )}
                {intake.caseType && intake.caseType !== "unsure" && (
                  <Note>
                    <p className="font-bold">選{TYPE_LABEL[intake.caseType]}{intake.caseType === "civil" ? `（${ROLE_LABEL[role]}）` : ""}，你會得到：</p>
                    <ul className="m-0 list-disc pl-5 text-[15px]">
                      {(defendant ? YOU_GET_DEFENDANT : YOU_GET[intake.caseType]).map((g) => <li key={g}>{g}</li>)}
                    </ul>
                  </Note>
                )}
              </StageCard>
            )}

            {stage === 2 && (
              <StageCard>
                <h1 {...titleProps}>{defendant ? "第 2 關　對方告你什麼？" : "第 2 關　發生了什麼事？"}</h1>
                <StoryField value={intake.text} onChange={(text) => update({ text })} defendant={defendant} />
                {defendant && <DefenseField value={intake.defenseText} onChange={(defenseText) => update({ defenseText })} />}
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
                <h1 {...titleProps}>第 3 關　填寫案件資料</h1>
                {error && <ErrorBox message={`選項載入失敗：${error}`} onRetry={load} />}
                {civil && (
                  <>
                    <CourtField courts={options?.courts ?? []} value={intake.court} onChange={(court) => update({ court })} defendant={defendant} />
                    <FieldBlock label={<span id="amount-label">{defendant ? "對方請求的金額" : "想請求的金額"}</span>}
                      hint={defendant ? "起訴狀「訴之聲明」寫的金額" : undefined}>
                      <AmountInput id="amount" value={intake.claimedAmount} onChange={(claimedAmount) => update({ claimedAmount })} />
                    </FieldBlock>
                    <FieldBlock label={<span id="party-label">{defendant ? "你（被告）是" : "對方是"}</span>}>
                      <Segmented labelledBy="party-label" value={intake.defendantType} items={DEFENDANT_TYPES}
                        onChange={(v) => update({ defendantType: v as DefendantType | "" })} />
                    </FieldBlock>
                  </>
                )}
                <FieldBlock label={<span id="lawyer-label">{intake.caseType === "criminal" ? lawyerQuestion("criminal").label : <><b className="font-extrabold">你</b>{defendant ? "（被告）" : ""}是否有請律師</>}</span>}
                  hint={intake.caseType === "criminal" || defendant ? lawyerQuestion(intake.caseType, role).hint : undefined}>
                  <Segmented labelledBy="lawyer-label" value={intake.lawyer} className="max-w-[320px]"
                    items={[{ value: "yes", label: "有" }, { value: "no", label: "沒有" }]}
                    onChange={(v) => update({ lawyer: v as IntakeState["lawyer"] })} />
                </FieldBlock>
                <FieldBlock label={<span id="evidence-label">證物欄</span>} hint="勾選手上有的證據，不需要上傳檔案。">
                  <div role="group" aria-labelledby="evidence-label" className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
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

function StoryField({ value, onChange, defendant = false }: { value: string; onChange: (v: string) => void; defendant?: boolean }) {
  const len = storyLength(value);
  const ok = len >= MIN_STORY;
  return (
    <>
      <div className="flex flex-col gap-2">
        <label htmlFor="story" className="text-lg font-bold">{defendant ? "對方的主張" : "事情經過"}</label>
        {defendant && <p id="story-hint" className="text-[15px] text-muted-foreground">寫對方說發生了什麼事、要你賠什麼。收到起訴狀的話，可以直接貼「事實及理由」。</p>}
        <Textarea id="story" value={value} maxLength={MAX_STORY} aria-describedby={defendant ? "story-hint story-status" : "story-status"}
          onChange={(e) => onChange(e.target.value)} className="min-h-[200px] resize-y"
          placeholder={defendant
            ? "例如：對方說去年三月我開車右轉時撞到他的機車，害他右手骨折住院五天，要我賠醫藥費和三個月不能工作的薪水，一共 50 萬……"
            : "例如：去年三月我騎機車在路口被一輛右轉的汽車撞到，右手骨折住院五天，之後復健三個月沒辦法工作……"} />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span id="story-status" role="status" className={cn("text-[15px]", ok && "font-bold text-secondary-foreground")}>
            {ok ? "字數夠了，可以進下一關。"
              : !defendant ? `還需 ${MIN_STORY - len} 字`
              : len === 0 ? "寫下對方告你什麼、要你賠多少。"
              : "字數偏少，可以先進下一關，但結果可能比較不準。有起訴狀的話，貼「事實及理由」會更準。"}
          </span>
          <span className="text-sm text-muted-foreground tabular-nums">{value.length} / {MAX_STORY} 字</span>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <p className="text-[15px] font-bold">可補充的細節（寫到時會標記）</p>
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

/** 民事被告：你的說法（選填）。會接在對方的主張後面一起遮名、送出，模型用它估計勝負，也會對照常見的抗辯。 */
function DefenseField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="defense" className="font-bold">你的說法<span className="text-[15px] font-medium text-muted-foreground">　選填</span></label>
      <p id="defense-hint" className="text-[15px] text-muted-foreground">
        你不同意哪些地方？例如事情不是這樣、金額太高、對方也有責任、已經還過錢。寫了會用來估計結果，並對照相似判決裡被告常見的說法。
      </p>
      <Textarea id="defense" value={value} maxLength={MAX_DEFENSE} aria-describedby="defense-hint"
        onChange={(e) => onChange(e.target.value)} className="min-h-[140px] resize-y"
        placeholder="例如：當時是對方闖紅燈，我是綠燈右轉；而且他請的看護費一天 3,000 元太高……" />
      <span className="self-end text-sm text-muted-foreground tabular-nums">{value.length} / {MAX_DEFENSE} 字</span>
    </div>
  );
}

function CriminalTips() {
  return (
    <div className="flex flex-col gap-2 rounded-[18px] border border-dashed bg-card p-5">
      <h2 className="font-bold">刑事案件怎麼寫</h2>
      <ul className="m-0 flex list-disc flex-col gap-2 pl-5 text-[15px] text-muted-foreground">
        <li>寫清楚時間、地點、發生了什麼，以及你被指控（或想指控）什麼事。</li>
        <li>有起訴書或傳票，可以直接貼「犯罪事實」那一段。</li>
        <li>不用寫你認為的罪名，系統會從你描述的事情推估可能的罪名。</li>
      </ul>
    </div>
  );
}

type KindGroup = { title: string; items: { value: string; label: string; summary: string }[] };

/**
 * 依說明頁的大類分組（knowledge.ts 的 DISPUTE_GROUPS，和後端的案由中類一一對應）。
 * 後端新增、說明頁還沒寫到的類型，放在最後一組，不會選不到。
 */
function kindGroups(options: Options | null): KindGroup[] {
  const label = (v: string) => (v.includes("：") ? v.split("：")[1] : v);
  const groups: KindGroup[] = DISPUTE_GROUPS.map((g) => ({
    title: g.title,
    items: g.types.map((t) => ({ value: t.id, label: label(t.id), summary: t.summary })),
  }));
  const known = new Set(groups.flatMap((g) => g.items.map((i) => i.value)));
  const extra = (options?.mid_groups ?? []).flatMap((g) => g.mids.map((m) => m.value)).filter((v, i, all) => !known.has(v) && all.indexOf(v) === i);
  if (extra.length) groups.push({ title: "其他類型", items: extra.map((v) => ({ value: v, label: v, summary: "" })) });
  return groups;
}

function matches(item: KindGroup["items"][number], q: string) {
  return !q || item.value.includes(q) || item.summary.includes(q);
}

/**
 * 糾紛類型：大類可以收合，展開就能直接點每一個類型；也可以打字搜尋（有結果的大類自動打開）。
 * 可以多選；右邊顯示已選類型的說明。
 */
function DisputeKinds({ options, mids, onChange }: { options: Options | null; mids: string[]; onChange: (mids: string[]) => void }) {
  const [query, setQuery] = useState("");
  const groups = kindGroups(options);
  // 一開始打開有已選類型的大類；之後由使用者自己開關
  const [open, setOpen] = useState<Set<string>>(() => new Set(groups.filter((g) => g.items.some((i) => mids.includes(i.value))).map((g) => g.title)));
  const q = query.trim();
  const shown = groups.map((g) => ({ ...g, items: g.items.filter((i) => matches(i, q)) })).filter((g) => g.items.length > 0);
  const setGroup = (title: string, isOpen: boolean) => setOpen((prev) => {
    const next = new Set(prev);
    if (isOpen) next.add(title); else next.delete(title);
    return next;
  });
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
          {shown.length === 0 && <p className="text-[15px] text-muted-foreground">找不到「{query}」。換個說法，或先不選也可以。</p>}
          <div className="flex flex-col gap-2">
            {shown.map((g) => {
              const picked = g.items.filter((i) => mids.includes(i.value)).length;
              const isOpen = Boolean(q) || open.has(g.title);
              return (
                <details key={g.title} open={isOpen}
                  onToggle={(e) => { if (!q) setGroup(g.title, (e.currentTarget as HTMLDetailsElement).open); }}
                  className="group/kind rounded-[12px] border bg-card">
                  <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 px-4 py-2 [&::-webkit-details-marker]:hidden">
                    <span className="font-bold">{g.title}</span>
                    <span className="text-sm text-muted-foreground">{g.items.length} 類</span>
                    {picked > 0 && <span className="rounded-full bg-secondary px-2 text-sm font-bold text-secondary-foreground">已選 {picked}</span>}
                    <ChevronDownIcon className="ml-auto size-5 flex-none transition-transform group-open/kind:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
                  </summary>
                  <div className="flex flex-wrap gap-2 px-4 pt-1 pb-4">
                    {g.items.map((item) => {
                      const on = mids.includes(item.value);
                      return (
                        <Toggle key={item.value} pressed={on} onPressedChange={() => onChange(toggle(mids, item.value))}
                          aria-label={item.value} title={item.summary || undefined}
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
                </details>
              );
            })}
          </div>
        </div>
        <aside aria-label="已選類型的說明" className="flex min-w-0 flex-[1_1_260px] flex-col gap-2 rounded-[18px] border bg-muted p-5">
          <p className="font-bold">糾紛類型說明</p>
          {mids.length === 0 && (
            <p className="flex flex-col items-center gap-2 py-6 text-center text-[15px] text-muted-foreground">
              <ListChecksIcon className="size-7" aria-hidden="true" />尚未選擇
            </p>
          )}
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

function CourtField({ courts, value, onChange, defendant = false }: {
  courts: string[]; value: string; onChange: (court: string) => void; defendant?: boolean;
}) {
  const items = [{ value: null as string | null, label: "不指定" }, ...courts.map((c) => ({ value: c as string | null, label: `${c}地方法院` }))];
  return (
    <FieldBlock label={<label htmlFor="court">{defendant ? "案子在哪個法院？" : "打算在哪個法院？"}</label>}
      hint={defendant ? "起訴狀或開庭通知上的法院，可以不選" : undefined}>
      <Select items={items} value={value || null} onValueChange={(v) => onChange((v as string | null) ?? "")}>
        <SelectTrigger id="court" className="w-full max-w-[360px]"><SelectValue /></SelectTrigger>
        <SelectContent>
          {items.map((c) => <SelectItem key={c.label} value={c.value}>{c.label}</SelectItem>)}
        </SelectContent>
      </Select>
    </FieldBlock>
  );
}

/** 右側「你填的資料」：每一關填的內容都看得到。 */
function Summary({ intake }: { intake: IntakeState }) {
  const civil = intake.caseType !== "criminal";
  const role = civilRole(intake);
  const defendant = role === "defendant";
  const amount = parseAmount(intake.claimedAmount);
  const evidenceCount = civil ? intake.evidence.length : intake.criminalEvidence.length;
  const rows: [string, string][] = [
    ["案件類型", TYPE_LABEL[intake.caseType]],
    ...(civil && intake.caseType ? [["你是", ROLE_LABEL[role]]] as [string, string][] : []),
    [defendant ? "對方的主張" : "案情", intake.text.trim() ? `${intake.text.length} 字` : "還沒寫"],
    ...(defendant ? [["你的說法", intake.defenseText.trim() ? `${intake.defenseText.length} 字` : "未填"]] as [string, string][] : []),
    ...(civil ? [
      ["請求金額", amount !== null ? `${amount.toLocaleString("en-US")} 元` : amountState(intake.claimedAmount) === "bad" ? "格式錯誤" : "未填"],
      [defendant ? "你（被告）" : "對方", DEFENDANT_TYPES.find((d) => d.value === intake.defendantType)?.label ?? "未選"],
    ] as [string, string][] : []),
    [lawyerQuestion(intake.caseType, role).short, intake.lawyer === "yes" ? "有" : intake.lawyer === "no" ? "沒有" : "未選"],
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
          {rows.map(([k, v], i) => (
            <div key={k} className="contents">
              <div className="flex items-start justify-between gap-3">
                <dt className="flex-none text-muted-foreground">{k}</dt>
                <dd className="m-0 text-right font-bold tabular-nums">{v}</dd>
              </div>
              {civil && i === 1 && (
                <div className="flex items-start justify-between gap-3">
                  <dt className="flex-none text-muted-foreground">糾紛類型</dt>
                  <dd className="m-0">{intake.mids.length ? <MidLabels mids={intake.mids} vertical /> : <span className="font-bold">未選</span>}</dd>
                </div>
              )}
            </div>
          ))}
        </dl>
      </Card>
    </aside>
  );
}
