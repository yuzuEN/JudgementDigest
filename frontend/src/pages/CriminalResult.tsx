import { FileTextIcon } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "../api/client";
import type { Charge, CriminalReport, SimilarCase } from "../api/types";
import { Bar } from "../components/casey/Bars";
import { EmptyState } from "../components/casey/EmptyState";
import { InfoNote, LoadingPanel, PanelTitle, ResultTabs, useResultTab } from "../components/casey/ResultTabs";
import { CaseNumber, ErrorBox, InfoLink, LAF_URL } from "../components/Common";
import { LinkButton } from "../components/LinkButton";
import { PdfButton, ResultFrame, ResultHeading } from "../components/ResultFrame";
import { percent } from "../format";
import { useIntake } from "../state";

export const CRIMINAL_TABS = [
  { key: "charges", label: "可能的罪名" },
  { key: "sentence", label: "刑期範圍" },
  { key: "cases", label: "相似判決" },
] as const;
export type CriminalTabKey = (typeof CRIMINAL_TABS)[number]["key"];
const TABS = CRIMINAL_TABS;
type TabKey = CriminalTabKey;

/** 頁尾「請注意」的條列（設計稿 C2-Criminal）。 */
export const CRIMINAL_NOTICE: ReactNode[] = [
  <>這份結果<b>不是法律意見</b>，也不是對你案子的預測。</>,
  "檢察官不起訴、告訴人撤回的案件，不在資料裡。",
  "告訴乃論的案件（例如過失傷害），雙方和解後通常就沒有判決，所以看不到這類結果。",
  <>需要專業協助，可以洽詢<a href={LAF_URL} target="_blank" rel="noreferrer">法律扶助基金會</a>或律師。</>,
];

/** 讀刑事報告：只在進入頁面時算一次。民事頁在「不確定」時也用這個。 */
export function useCriminalReport(enabled: boolean) {
  const { intake } = useIntake();
  const [report, setReport] = useState<CriminalReport | null>(null);
  const [error, setError] = useState("");
  const text = intake.searchText || intake.maskedText;
  const load = useCallback(() => {
    if (!enabled) return;
    setError("");
    setReport(null);
    api.criminalReport(text).then(setReport).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  return { report, error, load };
}

/** 刑事結果區塊：標題、分頁（分頁列最右邊是下載 PDF）。level 2 用在「不確定」的合併頁。 */
export function CriminalSection({ state, tab, setTab, level = 1 }: {
  state: ReturnType<typeof useCriminalReport>; tab: TabKey; setTab: (k: TabKey) => void; level?: 1 | 2;
}) {
  const { intake } = useIntake();
  const [selected, setSelected] = useState(0);
  const { report, error, load } = state;
  const mock = report?.mock ?? false;
  return (
    <section id="criminal" aria-labelledby="criminal-result" className="flex scroll-mt-4 flex-col gap-6">
      <ResultHeading id="criminal-result" level={level} title="刑事參考結果" lead="根據案情推估可能的罪名與刑期，並提供相似判決供參考。" />
      {error && (
        <ErrorBox message={error} onRetry={load} hint="請重新載入結果，或回上一步檢查描述。">
          <LinkButton variant="outline" to="/confirm?stage=6">回上一步</LinkButton>
        </ErrorBox>
      )}
      {!report && !error && <LoadingPanel />}
      {report && report.charges.length === 0 && (
        <EmptyState title="看不出可能的罪名">描述裡的事實不夠，模型找不出可能的罪名。可以回上一步補充發生的經過，或直接看相似判決。</EmptyState>
      )}
      {report && report.charges.length > 0 && (
        <ResultTabs value={tab} onChange={setTab} mock={mock} action={<PdfButton />} tabs={TABS.map((t) => ({
          key: t.key,
          label: t.label,
          content: {
            charges: <ChargesPanel report={report} rewritten={Boolean(intake.searchText)} />,
            sentence: <SentencePanel report={report} selected={selected} onSelect={(i) => setSelected(i)} />,
            cases: <CasesPanel report={report} selected={selected} onSelect={(i) => setSelected(i)} />,
          }[t.key],
        }))} />
      )}
    </section>
  );
}

export default function CriminalResult() {
  const { intake } = useIntake();
  const [params] = useSearchParams();
  const state = useCriminalReport(intake.caseType === "criminal");
  const [tab, setTab] = useResultTab<TabKey>(TABS.map((t) => t.key));

  if (!intake.caseType) return <Navigate to="/start?stage=1" replace />;
  if (intake.caseType === "civil") return <Navigate to="/result/civil" replace />;
  // 不確定：民事、刑事在同一頁（民事頁），刑事的分頁改用 ?ctab=
  if (intake.caseType === "unsure") return <Navigate to={`/result/civil?ctab=${params.get("tab") ?? "charges"}#criminal`} replace />;
  if (!intake.maskedText) return <Navigate to={intake.text ? "/confirm" : "/start"} replace />;

  return (
    <ResultFrame label="刑事" mock={state.report?.mock ?? false} maskedText={intake.maskedText} searchText={intake.searchText} notice={CRIMINAL_NOTICE}>
      <CriminalSection state={state} tab={tab} setTab={setTab} />
    </ResultFrame>
  );
}

/* ── 可能的罪名 ── */

function ChargesPanel({ report, rewritten }: { report: CriminalReport; rewritten: boolean }) {
  return (
    <>
      {/* 和民事「整體結果」一樣，模型判定整個框起來；罪名不再各自框起、也不在這裡切換（刑期範圍、相似判決分頁各有切換） */}
      <section aria-labelledby="charges-verdict-title" className="flex flex-col gap-3 rounded-[14px] border-2 border-primary bg-card px-4 py-4 sm:px-5">
        <PanelTitle mock={report.mock}><span id="charges-verdict-title">模型判定</span></PanelTitle>
        <h3 className="text-lg font-bold">可能的罪名</h3>
        <ul className="m-0 flex list-none flex-col divide-y p-0">
          {report.charges.map((c) => (
            <li key={c.name} className="flex flex-wrap items-center gap-x-6 gap-y-2 py-3 first:pt-0 last:pb-0">
              <span className="flex min-w-0 flex-[1_1_260px] flex-col">
                <b>{c.name}</b>
                <span className="text-[15px] text-muted-foreground">{c.law}</span>
                {c.law_note && <span className="text-sm text-muted-foreground">{c.law_note}</span>}
              </span>
              <span className="flex min-w-[180px] flex-[1_1_200px] flex-col gap-1">
                <span className="flex justify-between text-[15px]"><span className="text-muted-foreground">機率</span><b className="tabular-nums">{percent(c.probability)}</b></span>
                <span className="relative">
                  <Bar value={c.probability} label={`${c.name}：${percent(c.probability)}，模型判定的門檻是 50%`} />
                  {/* 50% 是模型判定的門檻：和民事勝訴機率一樣畫一條直線 */}
                  <span aria-hidden="true" className="absolute -top-1 -bottom-1 left-1/2 w-0.5 -translate-x-1/2 rounded-full bg-foreground" />
                </span>
              </span>
            </li>
          ))}
        </ul>
        <ul className="m-0 flex list-disc flex-col gap-1 border-t pt-3 pl-5 text-[15px] text-muted-foreground">
          <li>通常超過 50% 的機率之罪名，模型才會更加確信其成立。</li>
          <li>每個罪名的機率是分開估的，一件案子可能同時涉及好幾個罪名，所以加起來不一定是 100%。</li>
        </ul>
      </section>
      {!report.mock && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px]">
          <span className="inline-flex items-center gap-1.5 rounded-full border-[1.5px] border-input bg-card px-3 font-semibold">
            <FileTextIcon className="size-4" aria-hidden="true" />這次比對用的是：{rewritten ? "整理成判決書寫法的文字" : "你原本的描述"}
          </span>
          {rewritten && <span className="text-muted-foreground">想改用原文？<Link to="/confirm?stage=6">回第 6 關</Link></span>}
        </p>
      )}
    </>
  );
}

/* ── 刑期範圍 ── */

const MODEL_FILL = "bg-[repeating-linear-gradient(90deg,var(--outcome-part)_0_6px,transparent_6px_10px)]";
const ACTUAL_FILL = "bg-outcome-full";

function topLabel(items: { label: string; share: number }[]) {
  return items.reduce((best, b) => (b.share > best.share ? b : best), items[0]).label;
}

function Legend({ children, fill }: { children: ReactNode; fill: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[15px]">
      <span className={cn("size-[18px] flex-none rounded-[5px] border-[1.5px] border-outcome-part-fg", fill)} aria-hidden="true" />{children}
    </span>
  );
}

/** 一個罪名的刑期分布：模型推估（虛線）和最相似判決的實際宣告刑（實線）並列。 */
function SentenceRows({ charge, mock }: { charge: Charge; mock: boolean }) {
  const actual = charge.similar_sentence && charge.n_similar ? charge.similar_sentence : null;
  const actualOf = (label: string) => actual?.find((a) => a.label === label)?.share ?? 0;
  const modelTop = topLabel(charge.sentence);
  return (
    <>
      <p>
        {mock ? "相似的有罪判決中，" : "模型推估"}多數落在<b>「{modelTop}」</b>
        {actual && <>；最相似的 {charge.n_similar} 件「{charge.name}」有罪判決，實際宣告刑多數落在<b>「{topLabel(actual)}」</b></>}。
      </p>
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        <Legend fill={MODEL_FILL}>{mock ? "相似的有罪判決" : "模型推估"}</Legend>
        {actual && <Legend fill={ACTUAL_FILL}>最相似 {charge.n_similar} 件的實際宣告刑</Legend>}
      </div>
      <ul className="m-0 flex list-none flex-col p-0">
        {charge.sentence.map((b) => (
          <li key={b.label} className="grid grid-cols-[minmax(0,1fr)_96px] items-center gap-x-3 gap-y-1.5 border-b py-2.5 sm:grid-cols-[150px_minmax(0,1fr)_96px]">
            <b className="max-sm:col-span-2">{b.label}</b>
            <div className="flex flex-col gap-1.5">
              <Bar value={b.share} className="h-4" fill={MODEL_FILL}
                label={`${b.label}：${mock ? "相似的有罪判決" : "模型推估"} ${percent(b.share)}${actual ? `，最相似 ${charge.n_similar} 件實際宣告刑 ${percent(actualOf(b.label))}` : ""}`} />
              {actual && <Bar value={actualOf(b.label)} className="h-4" fill={ACTUAL_FILL} />}
            </div>
            <span className="flex flex-col text-[15px] tabular-nums">
              <span>{mock ? "" : "模型 "}{percent(b.share)}</span>
              {actual && <span>實際 {percent(actualOf(b.label))}</span>}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

/** 罪名切換：「刑期範圍」和「相似判決」共用，選的罪名三個分頁同步。 */
function ChargeSwitch({ report, selected, onSelect, label }: {
  report: CriminalReport; selected: number; onSelect: (i: number) => void; label: string;
}) {
  return (
    <div className="no-print flex flex-wrap items-center gap-2" role="group" aria-label={label}>
      <span className="text-[15px] text-muted-foreground">罪名</span>
      {report.charges.map((c, i) => (
        <button key={c.name} type="button" aria-pressed={i === selected} onClick={() => onSelect(i)}
          className={cn("min-h-11 rounded-full border-2 px-4 text-[15px] font-semibold",
            i === selected ? "border-foreground bg-secondary" : "border-input bg-card hover:border-primary")}>
          {c.name}
        </button>
      ))}
    </div>
  );
}

function SentencePanel({ report, selected, onSelect }: { report: CriminalReport; selected: number; onSelect: (i: number) => void }) {
  return (
    <>
      {report.charges.length > 1 && <ChargeSwitch report={report} selected={selected} onSelect={onSelect} label="看哪個罪名的刑期範圍" />}
      {/* 畫面上只顯示選到的罪名；列印時每個罪名都要印出來 */}
      {report.charges.map((c, i) => (
        <section key={c.name} aria-labelledby={`sentence-${i}`} className={cn("flex flex-col gap-4", i !== selected && "screen-hidden")}>
          <PanelTitle mock={report.mock}><span id={`sentence-${i}`}>刑期範圍：{c.name}</span></PanelTitle>
          <SentenceRows charge={c} mock={report.mock} />
        </section>
      ))}
      <InfoNote>{report.mock ? "實際刑期還是會依其他因素而不同。" : "模型推估的是整個案件的刑度，切換罪名時這一組不會變；實際刑期還是會依其他因素而不同。"}</InfoNote>
    </>
  );
}

/* ── 相似判決 ── */

/** 這個罪名的相似判決；舊版後端或示例資料沒有分罪名時，用頂層的那組（第一個罪名）。 */
function chargeCases(report: CriminalReport, i: number) {
  const c = report.charges[i];
  return c?.similar?.length ? { cases: c.similar, scope: c.search_scope } : { cases: report.similar, scope: report.search_scope };
}

function CasesPanel({ report, selected, onSelect }: {
  report: CriminalReport; selected: number; onSelect: (i: number) => void;
}) {
  // 後端每個罪名各給一組時，才有東西可以切換
  const perCharge = report.charges.length > 1 && report.charges.every((c) => c.similar?.length);
  const sections = perCharge ? report.charges.map((_, i) => i) : [0];
  const scopeOf = (i: number) => chargeCases(report, perCharge ? i : 0).scope;
  return (
    <>
      <PanelTitle mock={report.mock}>相似的真實判決</PanelTitle>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {perCharge ? <ChargeSwitch report={report} selected={selected} onSelect={onSelect} label="看哪個罪名的相似判決" /> : <span />}
        {/* 只放檢索範圍的總數；「怎麼找的」說明連結一直都在 */}
        <p className="ml-auto flex items-center gap-1 text-[15px] text-muted-foreground tabular-nums">
          {!report.mock && scopeOf(selected) && <>共 {scopeOf(selected)!.n.toLocaleString("en-US")} 件</>}
          <InfoLink to="相似判決怎麼找" label="相似判決怎麼找的說明" />
        </p>
      </div>
      {sections.map((i) => {
        const { cases } = chargeCases(report, i);
        return (
          // 印出來時每個罪名都印（和刑期範圍一樣），畫面上只顯示選的那個
          <section key={i} aria-label={perCharge ? `${report.charges[i].name}的相似判決` : undefined}
            className={cn("flex flex-col gap-4", perCharge && i !== selected && "screen-hidden")}>
            {perCharge && <h3 className="print-only text-lg font-bold">「{report.charges[i].name}」的相似判決</h3>}
            {cases.length === 0 ? (
              <EmptyState title="刑事相似判決檢索尚未開放">目前可查看罪名與刑期範圍。</EmptyState>
            ) : (
              <CriminalCasesTable cases={cases} />
            )}
          </section>
        );
      })}
    </>
  );
}

function CriminalCasesTable({ cases }: { cases: SimilarCase[] }) {
  return (
    <Table className="min-w-[680px] text-[15px]">
      <TableHeader>
        <TableRow>
          <TableHead scope="col">字號</TableHead>
          <TableHead scope="col">罪名</TableHead>
          <TableHead scope="col">應執行刑</TableHead>
          <TableHead scope="col" className="no-print"><span className="sr-only">動作</span></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {cases.map((c) => (
          <TableRow key={c.case_id}>
            <TableCell className="py-3.5 align-top whitespace-normal">
              <CaseNumber c={c} /><br />
              <span className="line-clamp-3 text-sm text-muted-foreground print:line-clamp-none">{c.summary}</span>
            </TableCell>
            <TableCell className="py-3.5 align-top">
              <ul className="m-0 flex list-none flex-col items-start gap-1 p-0">
                {c.mid.split("、").filter(Boolean).map((m) => <li key={m} className="rounded-full bg-secondary px-2.5 text-sm leading-[1.7] font-bold whitespace-nowrap text-secondary-foreground">{m}</li>)}
              </ul>
            </TableCell>
            <TableCell className="py-3.5 align-top whitespace-nowrap">{c.sentence ?? "—"}</TableCell>
            <TableCell className="no-print py-3.5 align-top">
              {/* 原文連結在字號上 */}
              <LinkButton variant="outline" size="sm" to={`/judgment/criminal/${c.case_id}`}>判決導讀</LinkButton>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
