import {
  ArrowLeftIcon, ArrowRightIcon, CheckIcon, ChevronDownIcon, ClockIcon, InfoIcon, LoaderCircleIcon, PencilIcon, PlusIcon,
  RotateCwIcon, ShieldCheckIcon, SparklesIcon, TriangleAlertIcon, XIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api } from "../api/client";
import type { Question } from "../api/types";
import { MaskedText } from "../components/casey/MaskedText";
import { RadioCards } from "../components/casey/RadioCards";
import { Layout, PAGE } from "../components/Layout";
import { LinkButton } from "../components/LinkButton";
import { parseAmount, sensitiveKinds } from "../format";
import { maskText } from "../mask";
import { fullText, primaryMid, useIntake, type Intake } from "../state";

const MAX_QUESTIONS = 4;

const SCENE_LINES: Record<number, string> = {
  4: "請檢查預覽中的個資。若有未遮蔽的姓名或公司名稱，可以在下方加入。",
  5: "你可以回答固定題目，或請 AI 根據案情提問。不想補充也可以略過。",
  6: "你可以請 AI 將描述整理成判決書的寫法。整理後請檢查內容，尤其是新增的數字。",
};

const NO_LLM_LINE = "請確認資料是否正確，再按「看參考結果」。";

type AiState = "idle" | "asking" | "done" | "failed" | "limited" | "unrelated";
type RewriteState = "idle" | "loading" | "failed" | "limited" | "unrelated";

function readStage(raw: string | null): 4 | 5 | 6 {
  return raw === "5" ? 5 : raw === "6" ? 6 : 4;
}

export default function Confirm() {
  const { intake, update } = useIntake();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const stage = readStage(params.get("stage"));
  const [questions, setQuestions] = useState<Question[]>([]);
  const [aiQuestions, setAiQuestions] = useState<Question[]>([]);
  const [llmAvailable, setLlmAvailable] = useState(false);
  const [vendor, setVendor] = useState("AI 服務");
  const [mode, setMode] = useState<"fixed" | "ai">("fixed");
  const [aiState, setAiState] = useState<AiState>("idle");
  const [rewriteState, setRewriteState] = useState<RewriteState>("idle");
  const [declined, setDeclined] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);
  const text = useMemo(() => fullText(intake), [intake]);
  const mid = primaryMid(intake);

  // 打開頁面時只拿固定題庫，描述不離開瀏覽器。傳給 LLM 要等使用者加好姓名、同意之後自己按按鈕
  useEffect(() => {
    if (!intake.text.trim() || !intake.caseType) return;
    let stale = false;
    api.followup(intake.caseType, mid, "")
      .then((r) => {
        if (stale) return;
        setQuestions(r.questions.filter((q) => !q.skip_if || !new RegExp(q.skip_if).test(intake.text)).slice(0, MAX_QUESTIONS));
        setLlmAvailable(Boolean(r.llm_available));
        if (r.llm_vendor) setVendor(r.llm_vendor);
      })
      .catch(() => { if (!stale) setQuestions([]); });   // 追問失敗不影響後面的流程
    return () => { stale = true; };
    // 不放 names：加名字不用重問，也不能蓋掉 AI 問過的問題
  }, [intake.caseType, mid, intake.text]);

  useEffect(() => {
    const maskedText = maskText(text, intake.names);
    // 描述或姓名改了，之前的整理就對不上了
    const stale = intake.rewriteFor && intake.rewriteFor !== maskedText;
    update(stale ? { maskedText, searchText: "", rewriteFor: "", rewriteDraft: "", rewriteAdded: [], useRewrite: "rewrite" } : { maskedText });
    // 不把 update 放進依賴：它會隨 intake 變動，放進去會一直重跑
  }, [text, intake.names]);

  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    heading.current?.focus();
  }, [stage]);

  if (!intake.caseType) return <Navigate to="/start?stage=1" replace />;
  if (!intake.text.trim()) return <Navigate to="/start?stage=2" replace />;
  const caseType = intake.caseType;

  const kinds = sensitiveKinds(text);
  const sensitive = kinds.length > 0;
  // 病歷、前科這類特種個資：平台自己比對時不用同意（已遮名、不保存），傳給外部 AI 前才要同意
  const aiAllowed = !sensitive || intake.sensitiveConsent;
  const consent = { kinds, given: intake.sensitiveConsent, declined,
    onChange: (yes: boolean) => { update({ sensitiveConsent: yes }); setDeclined(!yes); } };

  const ready = intake.maskedText !== "";
  const go = (n: number) => setParams({ stage: String(n) });
  const resultPath = intake.caseType === "criminal" ? "/result/criminal" : "/result/civil";

  const askAi = () => {
    setAiState("asking");
    api.followup(caseType, mid, maskText(intake.text, intake.names), true)
      .then((r) => {
        if (r.source === "llm") setAiQuestions(r.questions);
        setAiState(r.source === "llm" ? "done" : r.fallback === "not_dispute" ? "unrelated" : r.fallback === "limited" ? "limited" : "failed");
      })
      .catch(() => setAiState("failed"));
  };

  const startRewrite = () => {
    const source = intake.maskedText;
    setRewriteState("loading");
    api.rewrite(caseType, mid, source)
      .then((r) => {
        if (r.source === "llm" && r.text) {
          update({ rewriteDraft: r.text, rewriteAdded: r.added_numbers, rewriteFor: source, useRewrite: "rewrite", searchText: maskText(r.text.trim(), intake.names) });
          setRewriteState("idle");
        } else {
          setRewriteState(r.fallback === "limited" ? "limited" : r.fallback === "not_dispute" ? "unrelated" : "failed");
        }
      })
      .catch(() => setRewriteState("failed"));
  };

  const answered = Object.values(intake.followupAnswers).some((a) => a.answer.trim());
  const why = stage === 6 && rewriteState === "loading" ? "正在整理敘述，請稍等。" : null;
  const titleClass = "text-[22px] leading-[1.45] font-extrabold text-balance outline-none sm:text-[26px]";

  return (
    <Layout stage={stage} scene={{ who: "organizer", line: stage === 6 && !llmAvailable ? NO_LLM_LINE : SCENE_LINES[stage] }}>
      <div className={cn(PAGE, "pt-7 pb-16")}>
        <div className="flex flex-wrap items-start gap-7">
          <main className="flex min-w-0 flex-[999_1_560px] flex-col gap-6">
            {stage === 4 && (
              <MaskStage heading={<h1 ref={heading} tabIndex={-1} className={titleClass}>第 4 關　確認遮名</h1>}
                intake={intake} update={update} kinds={kinds} llm={llmAvailable} />
            )}
            {stage === 5 && (
              <DetailStage heading={<h1 ref={heading} tabIndex={-1} className={titleClass}>第 5 關　補充細節<span className="text-[15px] font-medium text-muted-foreground">　可以略過</span></h1>}
                llm={llmAvailable} vendor={vendor} mode={mode} setMode={setMode} aiState={aiState} askAi={askAi}
                consent={consent} aiAllowed={aiAllowed}
                questions={mode === "ai" && aiState === "done" ? aiQuestions : questions}
                answers={intake.followupAnswers}
                onAnswer={(q, value) => update({ followupAnswers: { ...intake.followupAnswers, [q.id]: { question: q.text, answer: value } } })} />
            )}
            {stage === 6 && (
              <RewriteStage heading={<h1 ref={heading} tabIndex={-1} className={titleClass}>{llmAvailable ? "第 6 關　整理成判決書的寫法" : "第 6 關　最後確認"}</h1>}
                llm={llmAvailable} vendor={vendor} intake={intake} update={update} state={rewriteState} onStart={startRewrite}
                consent={consent} aiAllowed={aiAllowed} />
            )}

            <nav aria-label="關卡" className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center justify-between gap-3">
                {stage === 4
                  ? <LinkButton variant="outline" to="/start?stage=3"><ArrowLeftIcon data-icon="inline-start" />回上一章</LinkButton>
                  : <Button type="button" variant="outline" onClick={() => go(stage - 1)}><ArrowLeftIcon data-icon="inline-start" />上一關</Button>}
                {stage < 6
                  ? <Button type="button" size="lg" disabled={!!why} onClick={() => go(stage + 1)}>
                      {stage === 5 && !answered ? "略過，下一關" : "下一關"}<ArrowRightIcon data-icon="inline-end" />
                    </Button>
                  : <Button type="button" size="lg" disabled={!ready || !!why} onClick={() => navigate(resultPath)}>看參考結果<ArrowRightIcon data-icon="inline-end" /></Button>}
              </div>
              {why && <p role="status" className="flex items-start gap-1.5 text-[15px]"><InfoIcon className="mt-1 size-4 flex-none" aria-hidden="true" />{why}</p>}
            </nav>
          </main>

          <Checklist stage={stage} vendor={llmAvailable ? vendor : null} />
        </div>
      </div>
    </Layout>
  );
}

function StageCard({ children }: { children: ReactNode }) {
  return <Card className="gap-6 px-[18px] sm:px-6.5">{children}</Card>;
}

function Note({ icon: Icon = InfoIcon, children, className, role }: { icon?: typeof InfoIcon; children: ReactNode; className?: string; role?: string }) {
  return (
    <div role={role} className={cn("flex items-start gap-3 rounded-[14px] border border-info-line bg-info px-4 py-3.5", className)}>
      <Icon className="mt-1 size-5 flex-none text-secondary-foreground" aria-hidden="true" />
      <div className="flex min-w-0 flex-col gap-2">{children}</div>
    </div>
  );
}

/* ── 第 4 關：遮名與敏感資料同意 ── */

function MaskStage({ heading, intake, update, kinds, llm }: {
  heading: ReactNode;
  intake: Intake;
  update: (patch: Partial<Intake>) => void;
  kinds: string[];
  llm: boolean;
}) {
  const [name, setName] = useState("");
  const add = () => {
    const n = name.trim();
    if (n && !intake.names.includes(n)) update({ names: [...intake.names, n] });
    setName("");
  };
  return (
    <StageCard>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        {heading}
        <LinkButton variant="ghost" to="/start?stage=2" className="px-2 text-link"><PencilIcon data-icon="inline-start" />修改描述</LinkButton>
      </div>
      <div className="flex flex-col gap-2">
        <p className="font-bold">會送出的內容（已遮名）</p>
        <p className="flex flex-wrap items-center gap-2 text-[15px]">
          <mark className="masked">橘色</mark><span className="text-muted-foreground">標示已遮蔽的身分證字號、電話、email、地址、車牌、出生日期，以及你加入的名字</span>
        </p>
        <MaskedText text={intake.maskedText} live />
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="mask-name" className="font-bold">還有要遮的名字嗎？</label>
        <p id="mask-name-hint" className="text-[15px] text-muted-foreground">輸入後按「加入」。文字裡所有相同的字都會被遮掉。</p>
        <div className="flex flex-wrap gap-2.5">
          <Input id="mask-name" value={name} placeholder="例如：對方的姓名、公司名稱" aria-describedby="mask-name-hint"
            className="min-w-0 flex-[1_1_240px]" onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
          <Button type="button" variant="outline" onClick={add}><PlusIcon data-icon="inline-start" />加入</Button>
        </div>
        {intake.names.length > 0 && (
          <ul aria-label="要遮掉的名字" className="m-0 flex list-none flex-wrap gap-2 p-0">
            {intake.names.map((n) => (
              <li key={n} className="inline-flex min-h-9 items-center gap-1 rounded-full border-[1.5px] border-mask-line bg-mask pr-1 pl-3 text-[15px] font-semibold text-mask-fg">
                {n}
                <Button type="button" variant="ghost" size="icon-sm" className="size-8 rounded-full text-mask-fg hover:bg-transparent"
                  aria-label={`不遮「${n}」`} onClick={() => update({ names: intake.names.filter((x) => x !== n) })}>
                  <XIcon />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {kinds.length > 0 && (
        <Note icon={ShieldCheckIcon}>
          <p className="font-bold">描述裡有法律特別保護的資料（偵測到：{kinds.join("、")}）</p>
          <p className="text-[15px]">
            這段文字只用來比對相似判決，不會保存。{llm && "之後如果你選擇用 AI 補充或整理，傳給 AI 服務前會先問你同意。"}
            不想提供的話，可以<LinkButton variant="link" to="/start?stage=2" className="h-auto p-0 text-[15px]">回描述案情</LinkButton>刪掉這些內容。
          </p>
        </Note>
      )}
    </StageCard>
  );
}

/* ── 傳給 AI 前的同意（只有描述裡有病歷、前科這類特種個資時才問） ── */

type Consent = { kinds: string[]; given: boolean; declined: boolean; onChange: (yes: boolean) => void };

function AiConsent({ consent, vendor, use, fallback }: { consent: Consent; vendor: string; use: string; fallback: string }) {
  if (consent.kinds.length === 0) return null;
  const value = consent.given ? "yes" : consent.declined ? "no" : "";
  return (
    <section aria-labelledby="ai-consent-title" className="flex flex-col gap-3">
      <h2 id="ai-consent-title" className="flex items-center gap-2.5 font-bold">
        <ShieldCheckIcon className="size-6 text-secondary-foreground" aria-hidden="true" />傳給 AI 前，需要你同意
      </h2>
      <p className="text-[15px]">
        你的描述裡有法律特別保護的資料（偵測到：{consent.kinds.join("、")}）。按下按鈕後，遮名後的內容會傳給 {vendor}，{use}。若不同意，可以{fallback}。
      </p>
      <RadioCards label="傳給 AI 的同意" value={value}
        options={[
          { value: "yes", title: "我同意傳給 AI", hint: `只用於這次的${use.replace(/^用來/, "")}，不會被用來訓練它的模型。` },
          { value: "no", title: "不同意，不用 AI" },
        ]}
        onChange={(v) => consent.onChange(v === "yes")} />
    </section>
  );
}

/* ── 第 5 關：補充細節 ── */

function QuestionList({ questions, answers, onAnswer }: {
  questions: Question[];
  answers: Intake["followupAnswers"];
  onAnswer: (q: Question, value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-5">
      {questions.map((q) => (
        <div key={q.id} className="flex flex-col gap-2 border-t pt-4">
          <label htmlFor={`q-${q.id}`} className="font-bold">{q.text}</label>
          <p className="text-[15px] text-muted-foreground">為什麼要問：{q.why}</p>
          <Input id={`q-${q.id}`} placeholder="你的回答（可留空）" value={answers[q.id]?.answer ?? ""} onChange={(e) => onAnswer(q, e.target.value)} />
        </div>
      ))}
    </div>
  );
}

function DetailStage({ heading, llm, vendor, mode, setMode, aiState, askAi, consent, aiAllowed, questions, answers, onAnswer }: {
  heading: ReactNode;
  consent: Consent;
  aiAllowed: boolean;
  llm: boolean;
  vendor: string;
  mode: "fixed" | "ai";
  setMode: (m: "fixed" | "ai") => void;
  aiState: AiState;
  askAi: () => void;
  questions: Question[];
  answers: Intake["followupAnswers"];
  onAnswer: (q: Question, value: string) => void;
}) {
  const fixed = questions.length > 0
    ? <QuestionList questions={questions} answers={answers} onAnswer={onAnswer} />
    : <p className="text-[15px] text-muted-foreground">這類案件沒有固定題目，可以直接下一關。</p>;
  const backToFixed = <Button type="button" variant="outline" onClick={() => setMode("fixed")}>改用固定題目</Button>;

  return (
    <StageCard>
      <div className="flex flex-col gap-2">
        {heading}
        <p className="text-[15px] text-muted-foreground">補充細節有助於比對。回答會和案情一起送出，切換補充方式時也會保留。</p>
      </div>
      {!llm ? (
        <>
          <p className="text-[15px]">以下是這類案件常需要補充的資料。</p>
          {fixed}
        </>
      ) : (
        <Tabs value={mode} onValueChange={(v) => setMode(v as "fixed" | "ai")} className="gap-5">
          <TabsList aria-label="補充方式" className="h-auto w-full rounded-[12px] border-2 border-input bg-card p-0">
            <TabsTrigger value="fixed" className="min-h-[50px] rounded-none text-base font-bold whitespace-normal text-foreground data-active:bg-primary data-active:text-primary-foreground">
              固定題目（不用 AI）
            </TabsTrigger>
            <TabsTrigger value="ai" className="min-h-[50px] rounded-none border-l-2 border-l-input text-base font-bold whitespace-normal text-foreground data-active:bg-primary data-active:text-primary-foreground">
              <SparklesIcon aria-hidden="true" />請 AI 幫我看還缺什麼
            </TabsTrigger>
          </TabsList>
          <TabsContent value="fixed" className="flex flex-col gap-4 text-base">
            <p className="text-[15px]">以下是這類案件常需要補充的資料。</p>
            {fixed}
          </TabsContent>
          <TabsContent value="ai" className="flex flex-col gap-4 text-base">
            {aiState === "idle" && (
              <>
                <AiConsent consent={consent} vendor={vendor} use="用來產生補充問題" fallback="改用固定題目就好" />
                {consent.declined ? (
                  <Note><p className="text-[15px]">已選擇不使用 AI，可以改答固定題目。</p>{backToFixed}</Note>
                ) : (
                  <Note>
                    <p className="text-[15px]">按下按鈕後，上一關遮名後的內容會傳給 {vendor}，由 AI 依你的案情提問。不按就不會傳。</p>
                    <Button type="button" className="w-fit" disabled={!aiAllowed} onClick={askAi}><SparklesIcon data-icon="inline-start" />傳給 AI，開始提問</Button>
                  </Note>
                )}
              </>
            )}
            {aiState === "asking" && (
              <>
                <Note icon={LoaderCircleIcon} role="status">
                  <p className="font-bold">AI 正在產生補充問題…</p>
                  <p className="text-[15px] text-muted-foreground">大約需要幾秒。你也可以先略過，回頭再補。</p>
                </Note>
                <div className="flex flex-col gap-2" aria-hidden="true">
                  <Skeleton className="h-5 w-3/5" /><Skeleton className="h-12" /><Skeleton className="h-5 w-1/2" /><Skeleton className="h-12" />
                </div>
              </>
            )}
            {aiState === "done" && (
              <>
                <p className="text-[15px]">這些問題由 AI 依你的案情產生，只用來補充事實，不是法律意見。</p>
                {questions.length > 0 ? <QuestionList questions={questions} answers={answers} onAnswer={onAnswer} />
                  : <p className="text-[15px] text-muted-foreground">AI 沒有提出補充問題，可以繼續下一關。</p>}
              </>
            )}
            {aiState === "failed" && (
              <Note icon={TriangleAlertIcon}>
                <p className="font-bold">無法產生補充問題</p>
                <p className="text-[15px] text-muted-foreground">請再試一次，或改用固定題目。</p>
                <div className="flex flex-wrap gap-2.5">
                  <Button type="button" onClick={askAi}><RotateCwIcon data-icon="inline-start" />再試一次</Button>
                  {backToFixed}
                </div>
              </Note>
            )}
            {aiState === "limited" && (
              <Note icon={ClockIcon}>
                <p className="font-bold">今天的 AI 次數用完了</p>
                <p className="text-[15px] text-muted-foreground">還是可以用固定題目，不影響看結果。</p>
                {backToFixed}
              </Note>
            )}
            {aiState === "unrelated" && (
              <Note>
                <p className="font-bold">這看起來不像法律糾紛</p>
                <p className="text-[15px] text-muted-foreground">內容未傳給 AI。請回到案情描述，補充糾紛的經過。</p>
                <div className="flex flex-wrap gap-2.5">
                  <LinkButton variant="outline" to="/start?stage=2">回描述案情</LinkButton>
                  {backToFixed}
                </div>
              </Note>
            )}
          </TabsContent>
        </Tabs>
      )}
    </StageCard>
  );
}

/* ── 第 6 關：整理成判決書的寫法、最後確認 ── */

const DEFENDANT_LABEL = { person: "個人", company: "公司", government: "政府機關、學校、醫院" } as const;
const CASE_LABEL = { civil: "民事", criminal: "刑事", unsure: "不確定（民事、刑事都查）" } as const;

function FinalSummary({ intake }: { intake: Intake }) {
  const civil = intake.caseType !== "criminal";
  const amount = parseAmount(intake.claimedAmount);
  const rows: [string, string][] = [
    ["案件類型", intake.caseType ? CASE_LABEL[intake.caseType] : "還沒選"],
    ...(civil ? [
      ["糾紛類型", intake.mids.length ? intake.mids.join("、") : "未選"],
      ["請求金額", amount !== null ? `${amount.toLocaleString("en-US")} 元` : "未填"],
      ["對方", intake.defendantType ? DEFENDANT_LABEL[intake.defendantType] : "未選"],
    ] as [string, string][] : []),
    ["律師", intake.lawyer === "yes" ? "有" : intake.lawyer === "no" ? "沒有" : "未選"],
    ["證物", `${civil ? intake.evidence.length : intake.criminalEvidence.length} 項`],
  ];
  return (
    <section aria-labelledby="final-title" className="flex flex-col gap-2 border-t pt-5">
      <h2 id="final-title" className="font-bold">最後確認：你提供的資料</h2>
      <dl className="m-0 grid gap-x-6 gap-y-1.5 text-[15px] sm:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-start justify-between gap-3">
            <dt className="flex-none text-muted-foreground">{k}</dt>
            <dd className="m-0 text-right font-bold tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

const REWRITE_NOTICE: Partial<Record<RewriteState, string>> = {
  failed: "AI 暫時無法使用，會改用你原本的描述。",
  limited: "AI 的使用次數暫時用完了，會改用你原本的描述。",
  unrelated: "這段描述看起來不像法律糾紛，所以沒有傳給 AI，會改用你原本的描述。",
};

function RewriteStage({ heading, llm, vendor, intake, update, state, onStart, consent, aiAllowed }: {
  heading: ReactNode;
  consent: Consent;
  aiAllowed: boolean;
  llm: boolean;
  vendor: string;
  intake: Intake;
  update: (patch: Partial<Intake>) => void;
  state: RewriteState;
  onStart: () => void;
}) {
  const criminal = intake.caseType === "criminal";
  const usedFor = criminal ? "推估罪名與刑期" : "搜尋相似判決";
  const draft = intake.rewriteDraft;
  const reviewed = intake.rewriteFor !== "";   // 整理過了（草稿清空也還在編輯，不能讓文字框消失）
  const choose = (useRewrite: Intake["useRewrite"], text = draft) =>
    update({ useRewrite, rewriteDraft: text, searchText: useRewrite === "rewrite" && text.trim() ? maskText(text.trim(), intake.names) : "" });

  if (!llm) {
    return (
      <StageCard>
        {heading}
        <p className="text-[15px]">會用你遮名後的描述{usedFor}。</p>
        <FinalSummary intake={intake} />
      </StageCard>
    );
  }

  return (
    <StageCard>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          {heading}
          <span className="rounded-full border-[1.5px] border-outcome-part bg-outcome-part-bg px-3 text-sm leading-[1.9] font-bold text-outcome-part-fg">建議</span>
        </div>
        <p className="text-[15px] text-muted-foreground">
          判決書的用詞和口語不一樣。AI 把你的描述改成判決書的寫法，{criminal ? "罪名和刑期模型是讀判決書的「犯罪事實」學的，整理後估得比較準" : "比對會更準"}。你可以直接改、直接用，或改用原文。
        </p>
      </div>

      {REWRITE_NOTICE[state] && <Note icon={TriangleAlertIcon}><p className="text-[15px]">{REWRITE_NOTICE[state]}</p></Note>}

      {state === "loading" && (
        <>
          <Note icon={LoaderCircleIcon} role="status"><p className="font-bold">正在整理敘述……</p></Note>
          <div className="flex flex-col gap-2" aria-hidden="true"><Skeleton className="h-5 w-2/5" /><Skeleton className="h-40" /></div>
        </>
      )}

      {state !== "loading" && !reviewed && (
        <>
          <AiConsent consent={consent} vendor={vendor} use="用來整理成判決書的寫法" fallback={`直接用你原本的描述${usedFor}就好`} />
          {consent.declined ? (
            <Note><p className="text-[15px]">這次不用 AI，會用你原本的描述{usedFor}。</p></Note>
          ) : (
            <Note>
              <p className="text-[15px]">按下按鈕後，第 4 關遮名後的內容會傳給 {vendor}；不按就用你原本的描述{usedFor}。</p>
              <Button type="button" variant="outline" className="w-fit" disabled={!aiAllowed} onClick={onStart}><SparklesIcon data-icon="inline-start" />請 AI 整理敘述</Button>
            </Note>
          )}
        </>
      )}

      {state !== "loading" && reviewed && (
        <>
          {intake.rewriteAdded.length > 0 ? (
            <div role="alert" className="flex items-start gap-3 rounded-[14px] border-2 border-primary bg-card px-4 py-3.5">
              <TriangleAlertIcon className="mt-1 size-5 flex-none text-secondary-foreground" aria-hidden="true" />
              <div className="flex flex-col gap-1.5">
                <p className="font-bold">整理後出現了原文沒有的數字：{intake.rewriteAdded.map((n) => `「${n}」`).join("、")}</p>
                <p className="text-[15px]">請逐一確認這些數字是否正確。若有錯誤，可以直接修改，或改用原文。</p>
              </div>
            </div>
          ) : (
            <p className="flex items-center gap-1.5 text-[15px] font-bold text-secondary-foreground"><CheckIcon className="size-4" aria-hidden="true" />整理後的數字，都能在原文找到。</p>
          )}
          <div className="flex flex-col gap-2">
            <label htmlFor="rewrite-draft" className="font-bold">整理後的寫法（可以直接修改）</label>
            <p id="rewrite-hint" className="text-[15px] text-muted-foreground">
              請檢查有沒有多出你沒說過的事，例如{criminal ? "日期、傷勢、前科、和解" : "日期、金額、簽約或書面文件"}。這段只用來{usedFor}，不是法律文件。
            </p>
            <Textarea id="rewrite-draft" value={draft} aria-describedby="rewrite-hint" className="min-h-[200px] resize-y"
              onChange={(e) => choose(intake.useRewrite, e.target.value)} />
          </div>
          <RadioCards label="使用哪一種寫法" value={intake.useRewrite} onChange={(v) => choose(v)}
            options={[{ value: "rewrite", title: "使用整理後的寫法" }, { value: "original", title: "改用我的原文" }]} />
        </>
      )}

      <FinalSummary intake={intake} />
    </StageCard>
  );
}

/* ── 右側：送出前檢查、資料使用說明 ── */

function Checklist({ stage, vendor }: { stage: number; vendor: string | null }) {
  const items = [[4, "確認遮名"], [5, "補充細節（可略過）"], [6, vendor ? "判決書寫法" : "最後確認"]] as const;
  return (
    <aside aria-labelledby="check-title" className="w-full min-w-0 flex-[1_1_260px] sm:max-w-[340px]">
      <Card className="gap-4 px-6.5">
        <h2 id="check-title" className="text-xl font-bold">送出前檢查</h2>
        <ol className="m-0 flex list-none flex-col gap-1 p-0">
          {items.map(([n, label]) => {
            const done = stage > n;
            const now = stage === n;
            return (
              <li key={n} aria-current={now ? "step" : undefined} className={cn("flex min-h-10 items-center gap-2.5", now ? "font-bold" : done ? "" : "text-muted-foreground")}>
                <span aria-hidden="true" className={cn(
                  "grid size-6 flex-none place-items-center rounded-full border-2",
                  done ? "border-primary bg-primary text-primary-foreground" : now ? "border-primary ring-4 ring-secondary" : "border-input",
                )}>
                  {done && <CheckIcon className="size-3.5" strokeWidth={3} />}
                </span>
                {label}{done && <span className="sr-only">（已完成）</span>}
              </li>
            );
          })}
        </ol>
        <p className="text-sm text-muted-foreground">
          送去比對的是遮名後的內容（包含你補充的回答）。{vendor ? `只有你按下「傳給 AI」或「請 AI 整理敘述」時，這些內容才會傳給 ${vendor}。` : "不會傳給 AI 服務。"}
        </p>
        <details className="group rounded-[12px] border bg-card">
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 font-bold [&::-webkit-details-marker]:hidden">
            資料使用說明
            <ChevronDownIcon className="ml-auto size-5 transition-transform group-open:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
          </summary>
          <ul className="m-0 flex list-disc flex-col gap-2 px-3 pb-3 pl-8 text-sm">
            <li>蒐集者：JudgementDigest 專題團隊；目的：產生類案判決參考結果。</li>
            <li>遮名在你的瀏覽器裡完成，原文和你加入的姓名不會傳到我們的伺服器。送出的是遮名後的內容；本平台的伺服器不保存你的描述。</li>
            <li>你填的內容只暫存在這個瀏覽器分頁：重新整理還在，關掉分頁就清除；不會存在電腦上，也不會存到我們的伺服器。</li>
            {vendor && <li>只有在你按下「傳給 AI，開始提問」或「請 AI 整理敘述」時，遮名後的內容才會傳給 {vendor} 的付費 API，不會被用來訓練或改善它的模型。</li>}
            <li>病歷、醫療、健康檢查、基因、性生活、犯罪前科是法律特別保護的資料。描述裡有這些內容時，平台只用來產生這次的參考結果、不保存{vendor && "；要傳給 AI 服務前，會另外請你同意"}。不想提供的話，回上一步刪掉這些描述就好，只是參考結果可能比較不準。</li>
          </ul>
        </details>
      </Card>
    </aside>
  );
}
