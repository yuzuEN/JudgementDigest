import { CheckIcon, CircleMinusIcon, InfoIcon } from "lucide-react";
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
import { InfoNote as Note, LoadingPanel, PanelTitle, ResultTabs, useResultTab } from "../components/casey/ResultTabs";
import { ErrorBox, InfoLink, LAF_URL, SIMILARITY_NOTE } from "../components/Common";
import { LinkButton } from "../components/LinkButton";
import { ResultFrame } from "../components/ResultFrame";
import { outcomeLabel, outcomeTone, percent } from "../format";
import { civilInput, useIntake } from "../state";

// 刑事結果頁也用這個長條
export { Bar };

const TABS = [
  { key: "overview", label: "整體結果", line: "資料整理好了。我是解說員，只負責說明過去類似判決的統計，不會預測你這件的結果。先看整體。" },
  { key: "amount", label: "可能的金額", line: "這是相似判決的判准金額。範圍通常很寬，請當作粗略參考。" },
  { key: "evidence", label: "證據對照", line: "這是勝訴的相似判決常提到的證據。你有的我幫你標出來。" },
  { key: "defense", label: "對方的說法", line: "這些是對方在相似判決裡常說的話。先看過，到時比較不會慌。" },
  { key: "cases", label: "相似判決", line: "這些是最相似的判決。每一件都可以點「判決導讀」，我會把主張、抗辯和法院的判斷分顏色給你看。" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const NOTICE: ReactNode[] = [
  <>這份結果<b>不是法律意見</b>，也不是對你案子的預測。</>,
  "最後會不會判、判多少，要看每個案子的細節和法院的認定。",
  "約四分之一的民事案件以和解、撤回結束，沒有判決書，不在統計裡，所以看到的只是「進到判決」的那一部分。",
  <>需要專業協助，可以洽詢<a href={LAF_URL} target="_blank" rel="noreferrer">法律扶助基金會</a>或律師。</>,
];

/** 元：完整數字（648,000），不換算成萬。 */
const yuan = (n: number | null | undefined) => (n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-US"));

export default function CivilResult() {
  const { intake } = useIntake();
  const [report, setReport] = useState<CivilReport | null>(null);
  const [error, setError] = useState("");
  const [onlyWin, setOnlyWin] = useState(false);
  const [tab, setTab] = useResultTab<TabKey>(TABS.map((t) => t.key));

  const load = useCallback(() => {
    if (!intake.caseType || intake.caseType === "criminal") return;
    setError("");
    setReport(null);
    api.civilReport(civilInput(intake)).then(setReport).catch((e: Error) => setError(e.message));
    // 只在進入頁面時算一次；intake 在結果頁不會再改，所以不放進依賴
  }, []);
  useEffect(load, [load]);

  if (!intake.caseType) return <Navigate to="/start?stage=1" replace />;
  if (intake.caseType === "criminal") return <Navigate to="/result/criminal" replace />;
  if (!intake.maskedText) return <Navigate to={intake.text ? "/confirm" : "/start"} replace />;

  const mid = intake.mids.length === 1 ? intake.mids[0] : "";
  const title = `民事參考結果${intake.mids.length ? `：${intake.mids.join("、")}` : ""}`;
  const lead = report ? `比對了 ${report.n_compared} 件${mid ? "案由相同的" : ""}真實判決。一次看一個分頁。` : "正在比對相似的真實判決……";
  const mock = report?.mock ?? false;

  return (
    <ResultFrame active="civil" title={title} lead={lead} mock={mock} maskedText={intake.maskedText} searchText={intake.searchText}
      sceneLine={TABS.find((t) => t.key === tab)!.line} notice={NOTICE}>
      {error && (
        <ErrorBox message={error} onRetry={load} hint="結果暫時沒有載入成功，不是你填錯了什麼。">
          <LinkButton variant="outline" to="/confirm?stage=6">回上一步</LinkButton>
        </ErrorBox>
      )}
      {!report && !error && <LoadingPanel />}
      {report && (
        <ResultTabs value={tab} onChange={setTab} mock={mock} tabs={TABS.map((t) => ({
          key: t.key,
          label: t.label,
          content: {
            overview: <Overview report={report} />,
            amount: <AmountPanel range={report.amount_range} mock={mock} />,
            evidence: <EvidencePanel report={report} />,
            defense: <DefensePanel report={report} />,
            cases: <CasesPanel report={report} onlyWin={onlyWin} setOnlyWin={setOnlyWin} rewritten={Boolean(intake.searchText)} />,
          }[t.key],
        }))} />
      )}
    </ResultFrame>
  );
}

/* ── 整體結果 ── */

const MIN_OUTCOME_CASES = 10;   // 比這少時比例沒有代表性，不畫圖

/** 參考訊號來自模型的勝訴機率（50% 為界）；描述太短或看不出是糾紛時是「資訊不足」。 */
const SIGNAL: Record<CivilReport["prediction"]["signal"], { label: string; text: string }> = {
  strong: { label: "較強", text: "依你的描述，模型估計的勝訴訊號較強。這只是過去判決的傾向，不是你這件的結果。" },
  weak: { label: "較弱", text: "依你的描述，模型估計的勝訴訊號較弱。可能是案件較不利，也可能是資訊還不夠；補充證據和經過後再看一次。" },
  insufficient: { label: "資訊不足", text: "描述太短，或看不出是哪一種糾紛，模型的參考訊號不可靠。建議回上一步補充細節，或直接看相似判決。" },
};

function Overview({ report }: { report: CivilReport }) {
  const { total, win, partial, lose } = report.outcomes;
  const { signal } = report.prediction;
  const enough = total >= MIN_OUTCOME_CASES;
  const share = total ? (win + partial) / total : 0;
  const mixed = enough && ((signal === "strong" && share < 0.4) || (signal === "weak" && share >= 0.7));
  return (
    <>
      <PanelTitle mock={report.mock}>相似判決的結果</PanelTitle>
      {enough ? (
        <>
          <p className="text-muted-foreground">{total} 件雙方都有攻防的相似判決，結果是：</p>
          <OutcomeBar counts={{ win, partial, lose }} />
        </>
      ) : (
        <EmptyState title={`有被告答辯的相似判決不多（只找到 ${total} 件）`}>
          數量太少，統計不可靠，所以這次不顯示比例。可以到「相似判決」分頁逐件看。
        </EmptyState>
      )}
      <Note title={`參考訊號：${SIGNAL[signal].label}`}>{SIGNAL[signal].text}</Note>
      {mixed && <p className="text-[15px] text-muted-foreground">相似判決的結果和模型的參考訊號不完全一致，請先看判決內容。</p>}
      {report.prediction.warnings.map((w) => <p key={w} className="text-[15px] font-bold">{w}</p>)}
      {report.default_cases > 0 && (
        <p className="flex items-start gap-1.5 text-[15px] text-muted-foreground">
          <InfoIcon className="mt-1 size-4 flex-none" aria-hidden="true" />
          <span>另外，最相似的 30 件判決裡有 {report.default_cases} 件被告沒有到庭（一造辯論）。法院只聽到原告一方的說法，原告幾乎都贏，所以不算進上面的比例。</span>
        </p>
      )}
      <ModelDetail report={report} />
    </>
  );
}

function ModelDetail({ report }: { report: CivilReport }) {
  const { win_probability: p, model } = report.prediction;
  return (
    <Disclosure summary="模型細節">
      <p className="flex flex-wrap items-center gap-1">模型參考：勝訴機率 <b className="tabular-nums">{percent(p)}</b>（勝訴或一部勝訴）<InfoLink to="勝訴機率" label="勝訴機率說明" /></p>
      <p className="text-[15px] text-muted-foreground">這是模型根據文字估出來的數字，不是你會贏的機率，只在判斷方向時當輔助。模型是用判決書的文字訓練的，一般口語描述算出來的機率常常偏低，也比較分不出輸贏。</p>
      <p className="text-sm text-muted-foreground">模型：{model.description}。你的描述越完整，結果越可靠。</p>
      <ModelScore model={model} />
    </Disclosure>
  );
}

function ModelScore({ model }: { model: CivilReport["prediction"]["model"] }) {
  const { win_precision: wp, win_recall: wr, lose_precision: lp, lose_recall: lr } = model;
  if (wp == null || wr == null || lp == null || lr == null) return null;
  return (
    <p className="text-sm text-muted-foreground">
      用判決文字測試時，模型判勝訴的案件有 {percent(wp)} 真的勝訴，實際勝訴的案件有 {percent(wr)} 被判出來；
      判敗訴的案件有 {percent(lp)} 真的敗訴，實際敗訴的案件有 {percent(lr)} 被判出來。
      <InfoLink to="Precision、Recall" label="Precision、Recall 說明" />
    </p>
  );
}

/* ── 可能的金額 ── */

function SourceChip({ tone, children }: { tone: "win" | "partial" | "lose"; children: ReactNode }) {
  return <OutcomeChip tone={tone}>{children}</OutcomeChip>;
}

/**
 * 四種情況，標題和說明都不同：模型推估（若為一部勝訴，虛線）、相似判決（實線）、
 * 沒填請求金額（只給比例）、相似判決不夠（不給範圍）。
 */
function AmountPanel({ range, mock }: { range: AmountRange | null; mock: boolean }) {
  if (!range) {
    return (
      <>
        <PanelTitle mock={mock}>可能判准的金額</PanelTitle>
        <EmptyState title="無法估出金額範圍" icon={<CircleMinusIcon className="size-7 text-ink-3" aria-hidden="true" />}>
          相似的勝訴判決太少，或描述看不出是哪一種糾紛，估出來的範圍不可靠，所以不顯示。你可以參考「相似判決」分頁，或回上一步補充細節。
        </EmptyState>
      </>
    );
  }
  // 模型推估的是「若為一部勝訴」：全部勝訴通常就是請求的全部金額，不在這個範圍裡
  const isModel = range.source === "model";
  const when = isModel ? "如果判決是「一部勝訴」，" : "如果勝訴，";
  const hits = Math.round(range.coverage * 10);
  const claimed = range.claimed;
  const coverage = isModel
    ? <>用過去的一部勝訴判決測試，<b>10 件約有 {hits} 件</b>落在這個範圍。</>
    : <>相似的勝訴判決裡，<b>10 件約有 {hits} 件</b>落在這個範圍（依 {range.n_cases} 件相似的勝訴判決）。</>;

  return (
    <>
      <PanelTitle mock={mock}>{claimed ? `${when}可能判准的金額` : `${when}可能判准的比例`}</PanelTitle>
      <div className="flex flex-wrap items-center gap-3">
        {claimed
          ? isModel
            ? <SourceChip tone="partial">來源：模型推估</SourceChip>
            : <SourceChip tone="win">來源：相似判決</SourceChip>
          : <SourceChip tone="lose">沒有填請求金額</SourceChip>}
        <span className="text-[15px] text-muted-foreground">
          {isModel ? "用過去的一部勝訴判決訓練的模型估計" : `依 ${range.n_cases ?? 0} 件相似的勝訴判決`}
        </span>
      </div>

      {claimed ? (
        <>
          <div>
            <p className="text-[30px] leading-[1.3] font-extrabold tabular-nums sm:text-[40px]">{yuan(range.amount_low)} ～ {yuan(range.amount_high)} 元</p>
            <p className="text-muted-foreground">你請求 <b className="text-foreground tabular-nums">{yuan(claimed)} 元</b></p>
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
      <p>{coverage}金額只能給範圍，不能給單一數字。</p>
      {range.n_wins ? (
        <p>相似的勝訴判決 {range.n_wins} 件中，<b>{range.n_full_wins ?? 0} 件是全部勝訴</b>（判准請求的全部金額）。</p>
      ) : null}
      {isModel && <Note>模型推估的範圍<b>很寬</b>，因為同樣的案情，法院判准的比例落差很大，只能看個大概。如果判決是全部勝訴，通常就是請求的全部金額。</Note>}
      {!claimed && <Note>想看到實際的金額範圍？<Link to="/start?stage=3">回上一步填寫想請求的金額</Link>，資料會保留。</Note>}
      <AmountDetail range={range} />
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
      <p className="text-[15px] text-muted-foreground">
        {range.source === "model" ? "上面的範圍是模型推估的；這裡是相似的勝訴判決實際" : "相似的勝訴判決"}判准了請求金額的幾成（當作對照，不是每件都和你的案情一樣）：
      </p>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {buckets.map((b) => (
          <li key={b.low} className="grid grid-cols-[78px_minmax(0,1fr)_48px] items-center gap-2.5 text-[15px]">
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

function EvidencePanel({ report }: { report: CivilReport }) {
  return (
    <>
      <PanelTitle mock={report.mock}>證據對照</PanelTitle>
      <p className="text-muted-foreground">相似的勝訴判決裡，有多少比例提到這項證據；右邊是你勾選或在描述裡提到的證據。</p>
      {report.evidence.length === 0 ? (
        <EmptyState title="沒有可以對照的證據資料">這類案子的判決很少寫明用了哪些證據。可以直接看「相似判決」分頁。</EmptyState>
      ) : (
        <div className="flex max-w-[760px] flex-col">
          {report.evidence.map((e) => (
            <MiniBarRow key={e.key} label={e.label} value={e.share} valueText={percent(e.share)}
              alt={`${e.label}：${percent(e.share)} 的相似勝訴判決有提到`}
              className="border-b py-3 last:border-b-0 sm:grid-cols-[150px_minmax(0,1fr)_56px_120px]">
              <span className="max-sm:col-span-2">
                {e.user_has
                  ? <span className="inline-flex items-center gap-1.5 text-sm font-bold text-secondary-foreground"><CheckIcon className="size-4" aria-hidden="true" />你有提到</span>
                  : <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><CircleMinusIcon className="size-4" aria-hidden="true" />你沒有提到</span>}
              </span>
            </MiniBarRow>
          ))}
        </div>
      )}
      <p className="text-[15px] text-muted-foreground">沒提到不代表會輸，只是勝訴的案子比較常拿出這些；提到也不代表法院一定採信。</p>
    </>
  );
}

/* ── 對方的說法 ── */

function DefensePanel({ report }: { report: CivilReport }) {
  return (
    <>
      <PanelTitle mock={report.mock}>對方可能會怎麼說</PanelTitle>
      <p className="text-muted-foreground">相似判決裡，被告常提出的說法（抗辯）。數字是出現的比例。</p>
      {report.defenses.length === 0 ? (
        <EmptyState title="相似判決裡沒有看到明顯的抗辯">不代表對方不會反駁，只是這些判決裡沒有整理出常見的說法。</EmptyState>
      ) : (
        <div className="flex max-w-[760px] flex-col gap-2">
          {report.defenses.map((d) => (
            <Disclosure key={d.key} summary={<><span className="flex-1">{d.label}</span><span className="tabular-nums">{percent(d.share)}</span></>}>
              <Bar value={d.share} label={`${d.label}：出現在 ${percent(d.share)} 的相似判決`} />
              <p className="text-[15px] text-muted-foreground">{d.description}。</p>
              {d.label.includes("與有過失") && (
                <a href={`/guide#${encodeURIComponent("與有過失")}`} target="_blank" rel="noreferrer" className="w-fit text-[15px] font-semibold decoration-dotted">什麼是「與有過失」？</a>
              )}
            </Disclosure>
          ))}
        </div>
      )}
    </>
  );
}

/* ── 相似判決 ── */

function CasesPanel({ report, onlyWin, setOnlyWin, rewritten }: {
  report: CivilReport; onlyWin: boolean; setOnlyWin: (v: boolean) => void; rewritten: boolean;
}) {
  const cases = report.similar;
  const visible = (c: SimilarCase) => !onlyWin || outcomeTone(c.outcome) !== "lose";
  const shown = cases.filter(visible);
  return (
    <>
      <PanelTitle mock={report.mock} action={
        <label className="no-print inline-flex min-h-11 cursor-pointer items-center gap-2.5 font-semibold">
          <Switch size="lg" checked={onlyWin} onCheckedChange={(v) => setOnlyWin(Boolean(v))} aria-label="只看原告勝訴的" />只看原告勝訴的
        </label>
      }>相似的真實判決</PanelTitle>
      <p className="text-[15px] text-muted-foreground">
        依相似度排序，{rewritten ? "用你確認過的整理文字搜尋。" : "用你原本的描述搜尋。"}「被告未到庭」代表一造辯論，只聽了原告一方的說法。
      </p>
      <Table className="min-w-[680px] text-[15px]">
        <TableHeader>
          <TableRow>
            <TableHead scope="col">字號</TableHead>
            <TableHead scope="col">結果</TableHead>
            <TableHead scope="col" className="text-right">判准／請求（元）</TableHead>
            <TableHead scope="col" className="text-right"><span className="inline-flex items-center gap-1">相似度<InfoLink to="相似度" label="相似度說明" /></span></TableHead>
            <TableHead scope="col" className="no-print"><span className="sr-only">動作</span></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {cases.map((c) => (
            <TableRow key={c.case_id} className={visible(c) ? undefined : "screen-hidden"}>
              <TableCell className="py-3.5 align-top whitespace-normal"><b>{c.case_number}</b><br /><span className="line-clamp-3 text-sm text-muted-foreground print:line-clamp-none">{c.summary}</span></TableCell>
              <TableCell className="py-3.5 align-top">
                <span className="flex flex-col gap-1">
                  <OutcomeChip tone={outcomeTone(c.outcome)}>{outcomeLabel(c.outcome)}</OutcomeChip>
                  {c.default_judgment && <OutcomeChip tone="neutral">被告未到庭</OutcomeChip>}
                </span>
              </TableCell>
              <TableCell className="py-3.5 text-right align-top tabular-nums">
                {c.claimed_amount ? <><b>{yuan(c.awarded_amount ?? 0)}</b> ／ {yuan(c.claimed_amount)}</> : "—"}
              </TableCell>
              <TableCell className="py-3.5 text-right align-top font-bold tabular-nums">{c.similarity.toFixed(2)}</TableCell>
              <TableCell className="no-print py-3.5 align-top">
                <LinkButton variant="outline" size="sm" to={`/judgment/civil/${c.case_id}`}>判決導讀</LinkButton>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {shown.length === 0 && (
        <EmptyState title="沒有符合的判決" className="no-print">
          這 {cases.length} 件相似判決都不是原告勝訴的。關掉「只看原告勝訴的」就能看到。
        </EmptyState>
      )}
      <p className={cn("text-[15px] text-muted-foreground", !shown.length && "screen-hidden")}>{SIMILARITY_NOTE}</p>
      {cases.some((c) => c.default_judgment) && (
        <p className={cn("text-[15px] text-muted-foreground", !shown.some((c) => c.default_judgment) && "screen-hidden")}>
          「被告未到庭」的判決沒有經過雙方攻防，原告幾乎都會贏，不代表你的案件也會這樣。金額範圍、證據與抗辯的統計不包含這些判決。
        </p>
      )}
    </>
  );
}
