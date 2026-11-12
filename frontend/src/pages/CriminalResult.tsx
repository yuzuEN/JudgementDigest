import { ExternalLinkIcon, FileTextIcon } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "../api/client";
import type { Charge, CriminalModelInfo, CriminalReport } from "../api/types";
import { Bar } from "../components/casey/Bars";
import { Disclosure } from "../components/casey/Disclosure";
import { EmptyState } from "../components/casey/EmptyState";
import { InfoNote, LoadingPanel, PanelTitle, ResultTabs, useResultTab } from "../components/casey/ResultTabs";
import { ErrorBox, InfoLink, LAF_URL, SIMILARITY_NOTE } from "../components/Common";
import { LinkButton } from "../components/LinkButton";
import { ResultFrame } from "../components/ResultFrame";
import { percent } from "../format";
import { useIntake } from "../state";

const TABS = [
  { key: "charges", label: "可能的罪名", line: "我是解說員。選擇罪名後，可以到「刑期範圍」查看推估結果與相似判決。" },
  { key: "sentence", label: "刑期範圍", line: "這裡並列模型推估與相似判決的實際宣告刑，方便比較。" },
  { key: "cases", label: "相似判決", line: "可以開啟判決原文，查看案件經過和法院判斷。" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

/** 頁尾「請注意」的條列（設計稿 C2-Criminal）。 */
const NOTICE: ReactNode[] = [
  <>這份結果<b>不是法律意見</b>，也不是對你案子的預測。</>,
  "檢察官不起訴、告訴人撤回的案件，不在資料裡。",
  "告訴乃論的案件（例如過失傷害），雙方和解後通常就沒有判決，所以看不到這類結果。",
  <>需要專業協助，可以洽詢<a href={LAF_URL} target="_blank" rel="noreferrer">法律扶助基金會</a>或律師。</>,
];

export default function CriminalResult() {
  const { intake } = useIntake();
  const [report, setReport] = useState<CriminalReport | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(0);
  const [tab, setTab] = useResultTab<TabKey>(TABS.map((t) => t.key));
  const text = intake.searchText || intake.maskedText;

  const load = useCallback(() => {
    if (!intake.caseType || intake.caseType === "civil") return;
    setError("");
    setReport(null);
    api.criminalReport(text).then(setReport).catch((e: Error) => setError(e.message));
    // 只在進入頁面時算一次
  }, []);
  useEffect(load, [load]);

  if (!intake.caseType) return <Navigate to="/start?stage=1" replace />;
  if (intake.caseType === "civil") return <Navigate to="/result/civil" replace />;
  if (!intake.maskedText) return <Navigate to={intake.text ? "/confirm" : "/start"} replace />;

  const mock = report?.mock ?? false;
  return (
    <ResultFrame active="criminal" title="刑事參考結果" mock={mock} maskedText={intake.maskedText} searchText={intake.searchText}
      sceneLine={TABS.find((t) => t.key === tab)!.line} notice={NOTICE}
      lead="根據案情推估可能的罪名與刑期，並提供相似判決供參考。">
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
        <ResultTabs value={tab} onChange={setTab} mock={mock} tabs={TABS.map((t) => ({
          key: t.key,
          label: t.label,
          content: {
            charges: <ChargesPanel report={report} selected={selected} onSelect={(i) => setSelected(i)} rewritten={Boolean(intake.searchText)} />,
            sentence: <SentencePanel report={report} selected={selected} />,
            cases: <CasesPanel report={report} />,
          }[t.key],
        }))} />
      )}
    </ResultFrame>
  );
}

/* ── 可能的罪名 ── */

function ChargesPanel({ report, selected, onSelect, rewritten }: {
  report: CriminalReport; selected: number; onSelect: (i: number) => void; rewritten: boolean;
}) {
  return (
    <>
      <PanelTitle mock={report.mock}>可能的罪名</PanelTitle>
      <p className="no-print text-muted-foreground">點一個罪名，「刑期範圍」分頁會跟著切換。</p>
      <RadioGroup aria-label="可能的罪名" value={String(selected)} onValueChange={(v) => onSelect(Number(v))} className="grid max-w-[820px] gap-2.5">
        {report.charges.map((c, i) => {
          const on = i === selected;
          return (
            <label key={c.name} className={cn(
              "flex cursor-pointer flex-wrap items-center gap-x-6 gap-y-2 rounded-[14px] border-2 bg-card px-4 py-3 has-focus-visible:outline-3 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring",
              on ? "border-foreground bg-secondary" : "border-input hover:border-primary",
            )}>
              <RadioGroupItem value={String(i)} aria-label={`${c.name}，機率 ${percent(c.probability)}`} className="sr-only" />
              <span className="flex min-w-0 flex-[1_1_260px] flex-col">
                <b>{c.name}</b>
                <span className="text-[15px] text-muted-foreground">{c.law}</span>
                {c.law_note && <span className="text-sm text-muted-foreground">{c.law_note}</span>}
              </span>
              <span className="flex min-w-[180px] flex-[1_1_200px] flex-col gap-1">
                <span className="flex justify-between text-[15px]"><span className="text-muted-foreground">機率</span><b className="tabular-nums">{percent(c.probability)}</b></span>
                <Bar value={c.probability} label={`${c.name}：${percent(c.probability)}`} />
              </span>
            </label>
          );
        })}
      </RadioGroup>
      <p className="text-[15px] text-muted-foreground">每個罪名的機率是分開估的，一件案子可能同時涉及好幾個罪名，所以加起來不一定是 100%。</p>
      {!report.mock && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px]">
          <span className="inline-flex items-center gap-1.5 rounded-full border-[1.5px] border-input bg-card px-3 font-semibold">
            <FileTextIcon className="size-4" aria-hidden="true" />這次比對用的是：{rewritten ? "整理成判決書寫法的文字" : "你原本的描述"}
          </span>
          {rewritten && <span className="text-muted-foreground">想改用原文？<Link to="/confirm?stage=6">回第 6 關</Link></span>}
        </p>
      )}
      {report.model && <ModelDetail model={report.model} />}
    </>
  );
}

function ModelDetail({ model }: { model: CriminalModelInfo }) {
  const { n_test: n, charge_top1: top1, bucket_accuracy: acc, bucket_within_one: near } = model;
  if (n == null || top1 == null || acc == null || near == null) return null;
  return (
    <Disclosure summary="模型細節">
      {model.sentence_description && model.sentence_n_test != null ? <>
        <p className="text-[15px]">
          罪名模型：{model.description}，用 {n.toLocaleString()} 件沒參與訓練的判決測試時，第一個罪名猜中 {percent(top1)}。
        </p>
        <p className="text-[15px]">
          刑期模型：{model.sentence_description}，用 {model.sentence_n_test.toLocaleString()} 件{model.sentence_test ? ` ${model.sentence_test}` : "沒參與訓練的判決"}測試時，
          刑期區間猜中 {percent(acc)}，差一格以內 {percent(near)}。
        </p>
      </> : (
        <p className="text-[15px]">
          模型：{model.description}。用 {n.toLocaleString()} 件沒參與訓練的判決測試時，第一個罪名猜中 {percent(top1)}；
          刑期區間猜中 {percent(acc)}，差一格以內 {percent(near)}。
        </p>
      )}
      <p className="text-[15px] text-muted-foreground">測試用的是判決書的文字，一般口語描述的準確度可能較低。</p>
    </Disclosure>
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
      <ul className="m-0 flex max-w-[820px] list-none flex-col p-0">
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

function SentencePanel({ report, selected }: { report: CriminalReport; selected: number }) {
  return (
    <>
      {/* 畫面上只顯示選到的罪名；列印時每個罪名都要印出來 */}
      {report.charges.map((c, i) => (
        <section key={c.name} aria-labelledby={`sentence-${i}`} className={cn("flex flex-col gap-4", i !== selected && "screen-hidden")}>
          <PanelTitle mock={report.mock}><span id={`sentence-${i}`}>刑期範圍：{c.name}</span></PanelTitle>
          <SentenceRows charge={c} mock={report.mock} />
        </section>
      ))}
      {!report.mock && <p className="text-[15px] text-muted-foreground">模型推估的是整個案件的刑度，切換罪名時這一組不會變；實際宣告刑則是含這個罪名的相似判決。</p>}
      <InfoNote>實際刑期還是會依前科、損害多寡、有沒有賠償與認罪而不同。這裡是過去類似案件的分布，不是你這件的結果。</InfoNote>
    </>
  );
}

/* ── 相似判決 ── */

function CasesPanel({ report }: { report: CriminalReport }) {
  return (
    <>
      <PanelTitle mock={report.mock}>相似的真實判決</PanelTitle>
      <p className="text-[15px] text-muted-foreground">依相似度排序。相似度不是百分比，是 0 到 1 之間的小數。</p>
      {report.similar.length === 0 ? (
        <EmptyState title="刑事相似判決檢索尚未開放">目前可查看罪名與刑期範圍。</EmptyState>
      ) : (
        <>
          <Table className="min-w-[680px] text-[15px]">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">字號</TableHead>
                <TableHead scope="col">罪名</TableHead>
                <TableHead scope="col">宣告刑</TableHead>
                <TableHead scope="col" className="text-right"><span className="inline-flex items-center gap-1">相似度<InfoLink to="相似度" label="相似度說明" /></span></TableHead>
                <TableHead scope="col" className="no-print">判決原文</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.similar.map((c) => (
                <TableRow key={c.case_id}>
                  <TableCell className="py-3.5 align-top whitespace-normal">
                    <b>{c.case_number}</b><br />
                    <span className="line-clamp-3 text-sm text-muted-foreground print:line-clamp-none">{c.summary}</span>
                  </TableCell>
                  <TableCell className="py-3.5 align-top whitespace-nowrap">{c.mid}</TableCell>
                  <TableCell className="py-3.5 align-top whitespace-nowrap">{c.sentence ?? "—"}</TableCell>
                  <TableCell className="py-3.5 text-right align-top font-bold tabular-nums">{c.similarity.toFixed(2)}</TableCell>
                  <TableCell className="no-print py-3.5 align-top">
                    {c.url
                      ? <a href={c.url} target="_blank" rel="noreferrer" aria-label="判決原文" className="inline-flex min-h-11 items-center gap-1 font-semibold">原文<ExternalLinkIcon className="size-4" aria-hidden="true" /></a>
                      : <LinkButton variant="outline" size="sm" to={`/judgment/criminal/${c.case_id}`}>判決導讀</LinkButton>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="text-[15px] text-muted-foreground">{SIMILARITY_NOTE}</p>
        </>
      )}
    </>
  );
}
