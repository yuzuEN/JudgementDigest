import { CheckIcon, CircleMinusIcon } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "../api/client";
import type { AmountRange, CivilReport, SimilarCase } from "../api/types";
import { Bar, MiniBarRow } from "../components/casey/Bars";
import { Disclosure } from "../components/casey/Disclosure";
import { EmptyState } from "../components/casey/EmptyState";
import { OutcomeBar } from "../components/casey/OutcomeBar";
import { OutcomeChip } from "../components/casey/OutcomeChip";
import { RangeBar } from "../components/casey/RangeBar";
import { DamageReasons, ReasoningBrief } from "../components/casey/Reasoning";
import { InfoNote as Note, LoadingPanel, PanelTitle, ResultTabs, useResultTab } from "../components/casey/ResultTabs";
import { CaseNumber, CommonPoints, ErrorBox, InfoLink, LAF_URL } from "../components/Common";
import { LinkButton } from "../components/LinkButton";
import { midName } from "../components/casey/MidLabels";
import { PdfButton, ResultFrame, ResultHeading } from "../components/ResultFrame";
import { CRIMINAL_NOTICE, CRIMINAL_TABS, CriminalSection, useCriminalReport, type CriminalTabKey } from "./CriminalResult";
import { outcomeLabel, outcomeTone, percent } from "../format";
import { civilInput, civilRole, criminalText, useIntake } from "../state";

// 刑事結果頁也用這個長條
export { Bar };

const TABS = [
  { key: "overview", label: "整體結果" },
  { key: "amount", label: "可能的金額" },
  { key: "evidence", label: "證據對照" },
  { key: "defense", label: "對方的說法" },
  { key: "cases", label: "相似判決" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

/** 被告：分頁名稱換成被告的角度（key 不變）。 */
const DEFENDANT_TABS: Record<TabKey, { label: string }> = {
  overview: { label: "整體結果" },
  amount: { label: "可能要賠的金額" },
  evidence: { label: "證據對照" },
  defense: { label: "被告的說法" },
  cases: { label: "相似判決" },
};

function tabsFor(defendant: boolean) {
  return TABS.map((t) => (defendant ? { key: t.key, ...DEFENDANT_TABS[t.key] } : t));
}

const DEFENDANT_NOTICE: ReactNode = "你是被告：下面的「勝訴」都是指原告（告你的人）勝訴；原告敗訴，就是你不用賠。";

const NOTICE: ReactNode[] = [
  <>這份結果<b>不是法律意見</b>，也不是對你案子的預測。</>,
  "最後會不會判、判多少，要看每個案子的細節和法院的認定。",
  "約四分之一的民事案件以和解、撤回結束，沒有判決書，不在統計裡，所以看到的只是「進到判決」的那一部分。",
  <>需要專業協助，可以洽詢<a href={LAF_URL} target="_blank" rel="noreferrer">法律扶助基金會</a>或律師。</>,
];

/** 元：完整數字（648,000），不換算成萬。 */
const yuan = (n: number | null | undefined) => (n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-US"));

/** 讀民事報告：只在進入頁面時算一次（intake 在結果頁不會再改）。 */
function useCivilReport(enabled: boolean) {
  const { intake } = useIntake();
  const [report, setReport] = useState<CivilReport | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    if (!enabled) return;
    setError("");
    setReport(null);
    api.civilReport(civilInput(intake)).then(setReport).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  return { report, error, load };
}

/** 民事結果區塊：標題、分頁（分頁列最右邊是下載 PDF）。level 2 用在「不確定」的合併頁。 */
function CivilSection({ state, tab, setTab, level = 1 }: {
  state: ReturnType<typeof useCivilReport>; tab: TabKey; setTab: (k: TabKey) => void; level?: 1 | 2;
}) {
  const { intake } = useIntake();
  const [onlyWin, setOnlyWin] = useState(false);
  const { report, error, load } = state;
  const mid = intake.mids.length === 1 ? intake.mids[0] : "";
  // 角色以回應為準（舊版後端沒有 role，視為原告）；還沒拿到結果時看自己填的
  const defendant = (report ? report.role ?? "plaintiff" : civilRole(intake)) === "defendant";
  // 「不確定」選原告（預設值）：提醒真正的被告回第 1 關改，不然會以為是自己的勝率
  const unsure = intake.caseType === "unsure" && !defendant;
  const tabs = tabsFor(defendant);
  const title = `民事參考結果${defendant ? "（你是被告）" : ""}${intake.mids.length ? `：${intake.mids.map(midName).join("、")}` : ""}`;
  const lead = report ? `比對了 ${report.n_compared} 件${mid ? "案由相同的" : ""}真實判決。` : "正在比對相似的真實判決……";
  const mock = report?.mock ?? false;
  return (
    <section aria-labelledby="civil-result" className="flex flex-col gap-6 phone:gap-3">
      <ResultHeading id="civil-result" level={level} title={title} lead={lead} />
      {error && (
        <ErrorBox message={error} onRetry={load} hint="請重新載入結果，或回上一步檢查描述。">
          <LinkButton variant="outline" to="/confirm?stage=6">回上一步</LinkButton>
        </ErrorBox>
      )}
      {!report && !error && <LoadingPanel />}
      {report && (
        <ResultTabs value={tab} onChange={setTab} mock={mock} action={<PdfButton />} tabs={tabs.map((t) => ({
          key: t.key,
          label: t.label,
          content: {
            overview: <Overview report={report} defendant={defendant} unsure={unsure} />,
            amount: <AmountPanel range={report.amount_range} mock={mock} cases={report.similar} defendant={defendant} />,
            evidence: <EvidencePanel report={report} defendant={defendant} />,
            defense: <DefensePanel report={report} defendant={defendant} />,
            cases: <CasesPanel report={report} onlyWin={onlyWin} setOnlyWin={setOnlyWin} defendant={defendant} />,
          }[t.key],
        }))} />
      )}
    </section>
  );
}

export default function CivilResult() {
  const { intake } = useIntake();
  const unsure = intake.caseType === "unsure";
  const civil = useCivilReport(Boolean(intake.caseType) && intake.caseType !== "criminal");
  const criminal = useCriminalReport(unsure);
  const [tab, setTab] = useResultTab<TabKey>(TABS.map((t) => t.key));
  const [ctab, setCtab] = useResultTab<CriminalTabKey>(CRIMINAL_TABS.map((t) => t.key), "ctab");

  if (!intake.caseType) return <Navigate to="/start?stage=1" replace />;
  if (intake.caseType === "criminal") return <Navigate to="/result/criminal" replace />;
  if (!intake.maskedText) return <Navigate to={intake.text ? "/confirm" : "/start"} replace />;

  const mock = Boolean(civil.report?.mock || (unsure && criminal.report?.mock));
  // 不確定：同一頁上面民事、下面刑事，不用切換；請注意合併兩邊（重複的開頭結尾只留一次）
  const defendant = (civil.report ? civil.report.role ?? "plaintiff" : civilRole(intake)) === "defendant";
  const merged = unsure ? [...NOTICE.slice(0, -1), ...CRIMINAL_NOTICE.slice(1)] : NOTICE;
  const notice = defendant ? [DEFENDANT_NOTICE, ...merged] : merged;
  return (
    <ResultFrame label={unsure ? "民事與刑事" : "民事"} mock={mock} maskedText={intake.maskedText} searchText={intake.searchText}
      criminalText={unsure ? criminalText(intake) : undefined} notice={notice}>
      {unsure && <h1 className="sr-only">民事與刑事參考結果</h1>}
      <CivilSection state={civil} tab={tab} setTab={setTab} level={unsure ? 2 : 1} />
      {unsure && (
        <div className="mt-6 border-t pt-8">
          <CriminalSection state={criminal} tab={ctab} setTab={setCtab} level={2} />
        </div>
      )}
    </ResultFrame>
  );
}

/* ── 整體結果 ── */

const MIN_OUTCOME_CASES = 10;   // 比這少時比例沒有代表性，不畫圖

/** 參考訊號來自模型的勝訴機率（50% 為界）；描述太短或看不出是糾紛時是「資訊不足」。 */
const SIGNAL: Record<CivilReport["prediction"]["signal"], { label: string; text: string }> = {
  strong: { label: "較強", text: "以過去的案件來說，模型估計你的案件與過去案件比較時，勝訴機會較高。" },
  weak: { label: "較弱", text: "以過去的案件來說，模型估計你的案件與過去案件比較時，勝訴機會較低。可能是案件較不利，也可能是資訊還不夠；補充證據和經過後再看一次。" },
  insufficient: { label: "資訊不足", text: "描述太短，或看不出是哪一種糾紛，模型的參考訊號不可靠。建議回上一步補充細節，或直接看相似判決。" },
};

/**
 * 整體結果：最上面是模型判定（勝訴機率；模型怎麼算的放在說明頁），下面才是相似判決的勝敗當對照。
 * 模型是這個專案的技術重點，所以放在第一眼看到的位置；機率旁邊一定附「不是你會贏的機率」的說明。
 */
/** 被告看的參考訊號：機率一樣是原告勝訴的機率，「較強」是對方的訊號較強。 */
const DEFENDANT_SIGNAL: Record<CivilReport["prediction"]["signal"], { label: string; text: string }> = {
  strong: { label: "對方較強", text: "依描述，模型估計原告（告你的人）的勝訴訊號較強。這只是過去判決的傾向，不是你這件的結果；可以參考「被告的說法」準備答辯。" },
  weak: { label: "對方較弱", text: "依描述，模型估計原告的勝訴訊號較弱。可能是對方的主張較不利，也可能是資訊還不夠；這不代表你一定不用賠。" },
  insufficient: { label: "資訊不足", text: "對方主張的描述太短，或看不出是哪一種糾紛，模型的參考訊號不可靠。建議回上一步補充起訴狀的內容，或直接看相似判決。" },
};

function Overview({ report, defendant = false, unsure = false }: { report: CivilReport; defendant?: boolean; unsure?: boolean }) {
  const { total, win, partial, lose } = report.outcomes;
  const { signal } = report.prediction;
  const enough = total >= MIN_OUTCOME_CASES;
  const share = total ? (win + partial) / total : 0;
  const mixed = enough && ((signal === "strong" && share < 0.4) || (signal === "weak" && share >= 0.7));
  return (
    <>
      <ModelVerdict report={report} defendant={defendant} unsure={unsure} />
      <h3 className="mt-2 text-lg font-bold">對照：相似案件的判決結果</h3>
      {enough && defendant && <p className="text-muted-foreground">「敗訴」是原告輸，也就是被告不用賠，共 {lose} 件。</p>}
      {enough ? <OutcomeBar counts={{ win, partial, lose }} /> : (
        <EmptyState title={`有被告答辯的相似判決不多（只找到 ${total} 件）`}>
          數量太少，統計不可靠，所以這次不顯示比例。可以到「相似判決」分頁逐件看。
        </EmptyState>
      )}
      {mixed && <p className="text-hint text-muted-foreground">相似案件的判決結果和模型的判定不完全一致，請先看判決內容。</p>}
      {/* 統計只用對審（in_stats）的案件，一造辯論只出現在「相似判決」列表：見 backend/civil_service.py */}
      <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-hint text-muted-foreground">
        <li>僅列出雙方皆有到庭的案件。</li>
        {report.amount_range?.n_wins ? (
          <li>相似的勝訴判決 {report.amount_range.n_wins} 件中，<b>{report.amount_range.n_full_wins ?? 0} 件是全部勝訴</b>（判准請求的全部金額）。</li>
        ) : null}
        {report.default_cases > 0 && (
          <li>最相似的 30 件判決裡有 {report.default_cases} 件被告沒有到庭（一造辯論）。法院只聽到原告一方的說法，原告幾乎都贏，所以不算進上面的比例。</li>
        )}
      </ul>
    </>
  );
}

function ModelVerdict({ report, defendant = false, unsure = false }: { report: CivilReport; defendant?: boolean; unsure?: boolean }) {
  const { win_probability: p, signal, warnings } = report.prediction;
  const signals = defendant ? DEFENDANT_SIGNAL : SIGNAL;
  const probLabel = defendant ? "對方（原告）勝訴的機率（勝訴或一部勝訴）" : "勝訴機率（勝訴或一部勝訴）";
  // 系統代選的糾紛類型在提醒裡加粗
  const inferred = report.search_scope?.mid_inferred ? report.search_scope.mid ?? null : null;
  return (
    <section aria-labelledby="model-verdict-title" className="flex flex-col gap-3 rounded-[14px] border-2 border-primary bg-card px-4 py-4 sm:px-5">
      <PanelTitle mock={report.mock}><span id="model-verdict-title">模型判定</span></PanelTitle>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <p className="flex flex-col">
          <span className="flex items-center gap-1 text-hint text-muted-foreground"><InfoLink to="勝訴機率" label="勝訴機率說明" />{probLabel}</span>
          <b className="text-[40px] leading-[1.2] font-extrabold tabular-nums">{percent(p)}</b>
        </p>
        <p className="pb-1.5 text-lg font-bold">參考訊號：{signals[signal].label}</p>
      </div>
      <div className="flex flex-col gap-1">
        <div className="relative">
          <Bar value={p} className="h-3.5" label={`${probLabel} ${percent(p)}，判${defendant ? "原告" : ""}勝訴的界線是 50%`} />
          {/* 50% 是判勝訴的界線：在長條上畫一條直線 */}
          <span aria-hidden="true" className="absolute -top-1 -bottom-1 left-1/2 w-0.5 -translate-x-1/2 rounded-full bg-foreground" />
        </div>
        <div className="relative flex justify-between text-sm text-muted-foreground tabular-nums">
          <span>0%</span>
          <span className="absolute left-1/2 -translate-x-1/2">50%</span>
          <span>100%</span>
        </div>
      </div>
      <ul className="m-0 flex list-disc flex-col gap-1.5 pl-5 text-hint">
        {defendant && <li>換成你的角度：模型估計原告<b>敗訴（你不用賠）</b>的機率約 <b className="tabular-nums">{percent(1 - p)}</b>。</li>}
        {unsure && <li>這是以你為<b>原告（提告的一方）</b>估計的。如果其實是對方要你賠錢、或你收到法院寄來的起訴狀，你是<b>被告</b>，這就變成對方贏的機率；請回<Link to="/start?stage=1">第 1 關</Link>把「你是原告還是被告」改成被告。</li>}
        <li>{signals[signal].text}</li>
        <li className="text-muted-foreground">{defendant
          ? "這是模型以過去判決來預估的數值，請當作參考；模型根據對方的主張和你的說法來估，口語描述會降低模型判定的準確性。"
          : "這是模型以過去判決來預估的數值，請當作參考；通常來說口語描述會降低模型判定的準確性，因此會比較分不出輸贏。"}</li>
        {warnings.map((w) => <li key={w}><Emphasize text={w} part={inferred} /></li>)}
      </ul>
      <p className="flex flex-wrap items-center gap-1 border-t pt-3 text-hint text-muted-foreground">
        對模型如何處理感到好奇？點擊可以參考<InfoLink to="勝敗模型怎麼算" label="勝敗模型怎麼算的說明" />
      </p>
    </section>
  );
}

/** 把提醒裡的某一段（系統代選的糾紛類型）加粗。 */
function Emphasize({ text, part }: { text: string; part: string | null }) {
  const at = part ? text.indexOf(part) : -1;
  if (!part || at < 0) return <>{text}</>;
  return <>{text.slice(0, at)}<b>{part}</b>{text.slice(at + part.length)}</>;
}

/* ── 可能的金額 ── */

function SourceChip({ tone, children }: { tone: "win" | "partial" | "lose"; children: ReactNode }) {
  return <OutcomeChip tone={tone}>{children}</OutcomeChip>;
}

/**
 * 四種情況，標題和說明都不同：模型推估（若為一部勝訴，虛線）、相似判決（實線）、
 * 沒填請求金額（只給比例）、相似判決不夠（不給範圍）。
 */
function AmountPanel({ range, mock, cases = [], defendant = false }: {
  range: AmountRange | null; mock: boolean; cases?: SimilarCase[]; defendant?: boolean;
}) {
  const verb = defendant ? "你可能要賠" : "可能判准";
  if (!range) {
    return (
      <>
        <PanelTitle mock={mock}>{defendant ? "可能要賠的金額" : "可能判准的金額"}</PanelTitle>
        <EmptyState title="無法估出金額範圍" icon={<CircleMinusIcon className="size-7 text-ink-3" aria-hidden="true" />}>
          相似的勝訴判決太少，或描述看不出是哪一種糾紛，估出來的範圍不可靠，所以不顯示。你可以參考「相似判決」分頁，或回上一步補充細節。
        </EmptyState>
        <DamageReasons cases={cases} />
      </>
    );
  }
  // 模型推估的是「若為一部勝訴」：全部勝訴通常就是請求的全部金額，不在這個範圍裡
  const isModel = range.source === "model";
  const when = defendant
    ? (isModel ? "如果判決是原告「一部勝訴」，" : "如果原告勝訴，")
    : (isModel ? "如果判決是「一部勝訴」，" : "如果勝訴，");
  const hits = Math.round(range.coverage * 10);
  const claimed = range.claimed;
  const coverage = isModel
    ? <>用過去的一部勝訴判決測試，<b>10 件約有 {hits} 件</b>落在這個範圍。</>
    : <>相似的勝訴判決裡，<b>10 件約有 {hits} 件</b>落在這個範圍（依 {range.n_cases} 件相似的勝訴判決）。</>;

  return (
    <>
      <PanelTitle mock={mock}>{claimed ? `${when}${verb}的金額` : `${when}${verb}的比例`}</PanelTitle>
      <div className="flex flex-wrap items-center gap-3">
        {claimed
          ? isModel
            ? <SourceChip tone="partial">來源：模型推估</SourceChip>
            : <SourceChip tone="win">來源：相似判決</SourceChip>
          : <SourceChip tone="lose">沒有填請求金額</SourceChip>}
        <span className="text-hint text-muted-foreground">
          {isModel ? "用過去的一部勝訴判決訓練的模型估計" : `依 ${range.n_cases ?? 0} 件相似的勝訴判決`}
        </span>
      </div>

      {claimed ? (
        <>
          <div>
            <p className="text-[30px] leading-[1.3] font-extrabold tabular-nums sm:text-[40px]">{yuan(range.amount_low)} ～ {yuan(range.amount_high)} 元</p>
            <p className="text-muted-foreground">{defendant ? "對方請求" : "你請求"} <b className="text-foreground tabular-nums">{yuan(claimed)} 元</b></p>
          </div>
          <RangeBar low={range.ratio_low} median={range.ratio_median} high={range.ratio_high} dashed={isModel}
            medianLabel={`中位數 ${yuan(range.amount_median)}`} startLabel="0 元" endLabel={`請求 ${yuan(claimed)} 元`}
            label={`金額範圍：${yuan(range.amount_low)} 元到 ${yuan(range.amount_high)} 元，中位數 ${yuan(range.amount_median)} 元，請求金額 ${yuan(claimed)} 元`} />
        </>
      ) : (
        <>
          <div>
            <p className="text-[30px] leading-[1.3] font-extrabold tabular-nums sm:text-[40px]">請求金額的 {percent(range.ratio_low)}～{percent(range.ratio_high)}</p>
            <p className="text-muted-foreground">因為沒有填金額，這裡改用「占請求金額的比例」。</p>
          </div>
          <RangeBar low={range.ratio_low} median={range.ratio_median} high={range.ratio_high} dashed={isModel}
            medianLabel={`中位數 ${percent(range.ratio_median)}`} startLabel="0%" endLabel="請求金額 100%"
            label={`判准比例：請求金額的 ${percent(range.ratio_low)} 到 ${percent(range.ratio_high)}，中位數 ${percent(range.ratio_median)}`} />
        </>
      )}
      <ul className="m-0 flex list-disc flex-col gap-1.5 pl-5">
        <li>{coverage}金額只有範圍，無法給予單一數字。</li>
        {!isModel && <li className="text-muted-foreground"><b>金額模型</b>：要選一個糾紛類型，並填法院或{defendant ? "對方請求的" : "請求"}金額才會使用；這次改用相似判決的判准比例。</li>}
      </ul>
      {isModel && <Note>模型推估的範圍<b>很寬</b>，因為同樣的案情，法院判准的比例落差很大，只能看個大概。如果判決是全部勝訴，通常就是請求的全部金額。</Note>}
      {defendant && <p className="text-hint text-muted-foreground">原告敗訴時你不用賠；這裡的範圍只在原告勝訴（全部或一部分）時才有意義，勝負的機率見「整體結果」。</p>}
      {!claimed && <Note>想看到實際的金額範圍？<Link to="/start?stage=3">{defendant ? "回上一步填寫對方請求的金額" : "回上一步填寫想請求的金額"}</Link>，資料會保留。</Note>}
      <AmountDetail range={range} />
      <DamageReasons cases={cases} />
    </>
  );
}

function AmountDetail({ range }: { range: AmountRange }) {
  const buckets = range.buckets ?? [];
  if (buckets.length === 0) return null;
  const most = Math.max(...buckets.map((b) => b.count), 1);
  const total = buckets.reduce((n, b) => n + b.count, 0);
  const label = (b: { low: number; high: number }) => `${Math.round(b.low * 100)}–${Math.round(b.high * 100)}%`;
  return (
    <Disclosure summary="看各金額範圍有幾件">
      <p className="text-hint text-muted-foreground">
        {range.source === "model" ? "上面的範圍是模型推估的；這裡是相似的勝訴判決實際" : "相似的勝訴判決"}判准了請求金額的幾成（當作對照，不是每件都和你的案情一樣）：
      </p>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {buckets.map((b) => (
          <li key={b.low} className="grid grid-cols-[78px_minmax(0,1fr)_48px] items-center gap-2.5 text-hint">
            <span className="tabular-nums">{label(b)}</span>
            <Bar value={b.count / most} className="h-3.5" fill="bg-outcome-part" />
            <b className="text-right tabular-nums">{b.count} 件</b>
          </li>
        ))}
      </ul>
      <p className="text-sm text-muted-foreground">共 {total} 件。{buckets.map((b) => `${label(b)} ${b.count} 件`).join("、")}。</p>
    </Disclosure>
  );
}

/* ── 證據對照 ── */

function EvidencePanel({ report, defendant = false }: { report: CivilReport; defendant?: boolean }) {
  const cases = defendant ? "原告敗訴（被告贏）的相似判決" : "相似的勝訴判決";
  return (
    <>
      <PanelTitle mock={report.mock}>證據對照</PanelTitle>
      <p className="text-muted-foreground">以{cases}中，統計了這項證據出現的案件比例。</p>
      {report.evidence.length === 0 ? (
        <EmptyState title="沒有可以對照的證據資料">這類案子的判決很少寫明用了哪些證據。可以直接看「相似判決」分頁。</EmptyState>
      ) : (
        <div className="flex flex-col">
          {report.evidence.map((e) => (
            <MiniBarRow key={e.key} label={e.label} value={e.share} valueText={percent(e.share)}
              alt={`${e.label}：${percent(e.share)} 的${defendant ? cases : "相似勝訴判決"}有提到`}
              className="grid-cols-[minmax(0,1fr)_6.5rem] border-b py-3 last:border-b-0 phone:py-2.5 sm:grid-cols-[150px_minmax(0,1fr)_56px_120px]">
              <span className="order-2 justify-self-end sm:order-none sm:justify-self-auto">
                {e.user_has
                  ? <span className="inline-flex items-center gap-1.5 text-sm font-bold text-secondary-foreground"><CheckIcon className="size-4" aria-hidden="true" />你有提到</span>
                  : <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-faint"><CircleMinusIcon className="size-4" aria-hidden="true" />你沒有提到</span>}
              </span>
            </MiniBarRow>
          ))}
        </div>
      )}
    </>
  );
}

/* ── 對方的說法／被告的說法 ── */

/** 被告的說法：抗辯標籤是寫給原告看的（「你也有過失」），被告看時把「你」換成「原告」。 */
function defenseLabel(label: string, defendant: boolean) {
  return defendant ? label.replace(/^你/, "原告") : label;
}

function DefensePanel({ report, defendant = false }: { report: CivilReport; defendant?: boolean }) {
  return (
    <>
      <PanelTitle mock={report.mock}>{defendant ? "相似判決中被告常見的說法" : "相似判決中的被告抗辯"}</PanelTitle>
      <p className="text-muted-foreground">
        數字表示各項說法在相似判決中出現的比例。{defendant && "展開可以看提出這個說法的判決裡，原告輸的比例；標上「你有提到」的是你寫過的說法。"}
      </p>
      {report.defenses.length === 0 ? (
        <EmptyState title="未整理出常見的抗辯">
          {defendant ? "這些判決中沒有整理出常見說法。可以到「相似判決」分頁，看被告實際怎麼答辯。" : "這些判決中沒有整理出常見說法，對方仍可能提出反駁。"}
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-2">
          {report.defenses.map((d) => (
            <Disclosure key={d.key} summary={<>
              <span className="flex-1">{defenseLabel(d.label, defendant)}</span>
              {defendant && d.user_has && <span className="inline-flex items-center gap-1 text-sm font-bold text-secondary-foreground"><CheckIcon className="size-4" aria-hidden="true" />你有提到</span>}
              <span className="tabular-nums">{percent(d.share)}</span>
            </>}>
              <Bar value={d.share} label={`${defenseLabel(d.label, defendant)}：出現在 ${percent(d.share)} 的相似判決`} />
              <p className="text-hint text-muted-foreground">{d.description}。</p>
              {defendant && (d.lose_share != null
                ? <p className="text-hint">提出這個說法的 {d.n_raised ?? 0} 件相似判決中，<b className="tabular-nums">{percent(d.lose_share)}</b> 原告敗訴。這是相關、不是因果：說法有沒有用，要看證據和個案。</p>
                : <p className="text-hint text-muted-foreground">提出這個說法的相似判決太少（{d.n_raised ?? 0} 件），不計算原告敗訴的比例。</p>)}
              {d.label.includes("與有過失") && (
                <a href={`/guide#${encodeURIComponent("與有過失")}`} target="_blank" rel="noreferrer" className="w-fit text-hint font-semibold decoration-dotted">什麼是「與有過失」？</a>
              )}
            </Disclosure>
          ))}
        </div>
      )}
    </>
  );
}

/* ── 相似判決 ── */

function CasesPanel({ report, onlyWin, setOnlyWin, defendant = false }: {
  report: CivilReport; onlyWin: boolean; setOnlyWin: (v: boolean) => void; defendant?: boolean;
}) {
  const cases = report.similar;
  // 被告想看的是自己這一方贏的判決（原告敗訴）
  const filterLabel = defendant ? "只看被告贏的（原告敗訴）" : "只看原告勝訴的";
  const visible = (c: SimilarCase) => !onlyWin || (defendant ? outcomeTone(c.outcome) === "lose" : outcomeTone(c.outcome) !== "lose");
  const shown = cases.filter(visible);
  const scope = report.mock ? null : report.search_scope;
  return (
    <>
      <PanelTitle mock={report.mock} action={<>
        {/* 和刑事一樣：檢索範圍的總數＋「怎麼找的」說明連結 */}
        <p className="flex items-center gap-1 text-hint text-muted-foreground tabular-nums">
          {scope && <>共 {scope.n.toLocaleString("en-US")} 件</>}
          <InfoLink to="相似判決怎麼找" label="相似判決怎麼找的說明" />
        </p>
        <label className="no-print inline-flex min-h-11 cursor-pointer items-center gap-2.5 font-semibold">
          <Switch size="lg" checked={onlyWin} onCheckedChange={(v) => setOnlyWin(Boolean(v))} aria-label={filterLabel} />{filterLabel}
        </label>
      </>}>{scope?.mid ? `相似的真實判決——${scope.mid}` : "相似的真實判決"}</PanelTitle>
      <Table className="table-stack min-w-[680px] text-hint">
        <TableHeader>
          <TableRow>
            <TableHead scope="col">字號</TableHead>
            <TableHead scope="col">結果</TableHead>
            <TableHead scope="col" className="text-right">判准／請求（元）</TableHead>
            <TableHead scope="col" className="no-print"><span className="sr-only">動作</span></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {cases.map((c) => (
            <TableRow key={c.case_id} className={visible(c) ? undefined : "screen-hidden"}>
              <TableCell className="py-3.5 align-top whitespace-normal"><CaseNumber c={c} /><br /><span className="line-clamp-3 text-sm text-muted-foreground print:line-clamp-none">{c.summary}</span><CommonPoints points={c.common} /><ReasoningBrief items={c.reasoning} /></TableCell>
              <TableCell data-label="結果" className="py-3.5 align-top">
                <span className="flex flex-col gap-1 phone:flex-row phone:flex-wrap">
                  <OutcomeChip tone={outcomeTone(c.outcome)}>{outcomeLabel(c.outcome)}</OutcomeChip>
                  {c.default_judgment && <OutcomeChip tone="neutral">被告未到庭</OutcomeChip>}
                </span>
              </TableCell>
              <TableCell data-label="判准／請求（元）" className="py-3.5 text-right align-top tabular-nums">
                <span>{c.claimed_amount ? <><b>{yuan(c.awarded_amount ?? 0)}</b> ／ {yuan(c.claimed_amount)}</>
                  : c.awarded_amount ? <><b>{yuan(c.awarded_amount)}</b> ／ —</> : "—"}</span>
              </TableCell>
              <TableCell className="no-print py-3.5 align-top">
                <LinkButton variant="outline" size="sm" to={`/judgment/civil/${c.case_id}`}>判決導讀</LinkButton>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {shown.length === 0 && (
        <EmptyState title="沒有符合的判決" className="no-print">
          這 {cases.length} 件相似判決都不是{defendant ? "原告敗訴" : "原告勝訴"}的。關掉「{filterLabel}」就能看到。
        </EmptyState>
      )}
      {cases.some((c) => (c.reasoning ?? []).length > 0) && (
        <p className="text-hint text-muted-foreground">
          「法院怎麼認定」由 AI 依標註手冊標註、人工抽查，可能有誤；只有部分判決有標註。點「判決導讀」可以看完整的認定和原文。<InfoLink to="法院怎麼認定" label="法院怎麼認定的說明" />
        </p>
      )}
      {cases.some((c) => c.default_judgment) && (
        <p className={cn("flex items-start gap-1 text-hint text-muted-foreground", !shown.some((c) => c.default_judgment) && "screen-hidden")}>
          <InfoLink to="被告未到庭（一造辯論）" label="被告未到庭說明" />
          <span>「被告未到庭」的判決沒有經過雙方攻防，原告幾乎都會贏（僅作參考）。金額範圍、證據與抗辯的統計不包含這些判決。</span>
        </p>
      )}
    </>
  );
}
