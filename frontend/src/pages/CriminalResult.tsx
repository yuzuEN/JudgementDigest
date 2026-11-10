import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "../api/client";
import type { CriminalModelInfo, CriminalReport, SentenceDistribution } from "../api/types";
import { ErrorBox, InfoLink, LAF_URL, Loading, MockBadge } from "../components/Common";
import { ResultFrame } from "../components/ResultFrame";
import { percent } from "../format";
import { Bar } from "../components/casey/Bars";
import { useIntake } from "../state";

type Bucket = { label: string; share: number };

/** 刑度各區間的長條；最大的一格標成主色。 */
function Buckets({ items }: { items: Bucket[] }) {
  const top = items.reduce((best, b, i, all) => (b.share > all[best].share ? i : best), 0);
  return (
    <div className="flex flex-col gap-3">
      {items.map((b, i) => (
        <div key={b.label} className={cn("grid grid-cols-[96px_minmax(0,1fr)_48px] items-center gap-2.5 text-[15px]", i === top && "font-bold")}>
          <span>{b.label}</span>
          <Bar value={b.share} className="h-3.5 rounded" fill={cn("rounded", i === top ? "bg-primary" : "bg-primary/35")} label={`${b.label} ${percent(b.share)}`} />
          <span className={cn("text-right", i !== top && "text-muted-foreground")}>{percent(b.share)}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * ELECTRA 刑期模型（只估有期徒刑）的卡片。後端目前停用 ELECTRA，不回傳 report.sentence，這張卡不會出現；
 * 之後在 backend/main.py 打開 ELECTRA 就會顯示。
 */
function ElectraSentenceCard({ sentence }: { sentence: SentenceDistribution }) {
  return (
    <Card aria-labelledby="electra-title">
      <CardHeader>
        <CardTitle id="electra-title" className="text-lg font-bold">可能的刑期範圍（有期徒刑）</CardTitle>
        <CardDescription className="text-[15px]">AI 模型讀了你的描述後，估計判有期徒刑時刑期落在各區間的機會。</CardDescription>
        {sentence.mock && <CardAction><MockBadge show>示例資料</MockBadge></CardAction>}
      </CardHeader>
      <CardContent><Buckets items={sentence.buckets} /></CardContent>
    </Card>
  );
}

function ModelScore({ model }: { model: CriminalModelInfo }) {
  const { n_test: n, charge_top1: top1, bucket_accuracy: acc, bucket_within_one: near } = model;
  if (n == null || top1 == null || acc == null || near == null) return null;
  return (
    <p className="text-[13px] text-muted-foreground">
      模型：{model.description}。用 {n.toLocaleString()} 件沒參與訓練的判決測試時，第一個罪名猜中 {percent(top1)}；
      刑期區間猜中 {percent(acc)}，差一格以內 {percent(near)}。測試用的是判決書的文字，一般口語描述的準確度可能較低。
    </p>
  );
}

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

  return (
    <ResultFrame active="criminal" title="刑事參考結果" mock={report?.mock ?? false} maskedText={intake.maskedText} searchText={intake.searchText}
      sceneLine="資料整理好了。我是解說員，只負責說明過去類似判決的統計，不會預測你這件的結果。" notice={NOTICE}
      lead="依你描述的事實，推估可能涉及的罪名、法條與刑期範圍。">
      {report?.mock && <p className="no-print text-sm text-muted-foreground">刑事模型由刑事組開發中，目前顯示的是示例資料。</p>}
      {error && <ErrorBox message={error} onRetry={load} />}
      {!report && !error && <Loading />}
      {report && report.charges.length > 0 && (
        <>
          <div className="grid gap-6 md:grid-cols-2" data-print-grid="2">
            <Card aria-labelledby="charge-title">
              <CardHeader>
                <CardTitle id="charge-title" className="text-lg font-bold">可能的罪名</CardTitle>
                <CardDescription className="no-print text-[15px]">
                  點選罪名，查看刑期分布。{!report.mock && (intake.searchText ? "使用你確認過的整理文字。" : "使用你原本的描述。")}
                </CardDescription>
                {report.mock && <CardAction><MockBadge show>示例資料</MockBadge></CardAction>}
              </CardHeader>
              <CardContent>
                <div role="group" aria-labelledby="charge-title" className="flex flex-col gap-2.5">
                  {report.charges.map((c, i) => (
                    <button key={c.name} type="button" aria-pressed={i === selected} onClick={() => setSelected(i)}
                      className="flex min-h-11 flex-col gap-1.5 rounded-lg border border-input px-4 py-3 text-left transition-colors outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:border-primary aria-pressed:bg-primary/5">
                      <span className="flex justify-between gap-2"><strong>{c.name}</strong><span>{percent(c.probability)}</span></span>
                      <span className="text-sm text-muted-foreground">{c.law}</span>
                      {c.law_note && <span className="text-[13px] text-muted-foreground">{c.law_note}</span>}
                      <Bar value={c.probability} className="w-full" />
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
            {/* 畫面上只顯示選到的罪名；列印時每個罪名都要印出來 */}
            {report.charges.map((c, i) => (
              <Card key={c.name} className={cn(i !== selected && "screen-hidden")} aria-labelledby={`sentence-title-${i}`}>
                <CardHeader>
                  <CardTitle id={`sentence-title-${i}`} className="text-lg font-bold">刑期範圍：{c.name}</CardTitle>
                  <CardDescription className="text-[15px]">
                    {report.mock ? "相似的有罪判決中，宣告刑落在各區間的比例。"
                      : "模型依類似的有罪判決推估，宣告刑落在各區間的機率（整個案件的刑度，各罪名相同）。"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-5">
                  <Buckets items={c.sentence} />
                  {c.similar_sentence && c.n_similar ? (
                    <div className="flex flex-col gap-3">
                      <div>
                        <h3 className="text-base font-bold">相似判決的實際宣告刑</h3>
                        <p className="text-sm text-muted-foreground">最相似的 {c.n_similar} 件「{c.name}」有罪判決中，宣告刑落在各區間的比例。</p>
                      </div>
                      <Buckets items={c.similar_sentence} />
                    </div>
                  ) : null}
                  <p className="text-sm text-muted-foreground">實際刑期還會受到是否和解、有無前科、犯後態度等影響。</p>
                </CardContent>
              </Card>
            ))}
          </div>
          {report.sentence && <ElectraSentenceCard sentence={report.sentence} />}
          <Card aria-labelledby="crim-sim-title">
            <CardHeader>
              <CardTitle id="crim-sim-title" className="text-lg font-bold">相似的真實判決</CardTitle>
              {report.mock && <CardAction><MockBadge show>示例資料</MockBadge></CardAction>}
            </CardHeader>
            <CardContent>
              {report.similar.length === 0 ? <p className="text-[15px] text-muted-foreground">刑事的相似判決檢索開發中。</p> : (
                <Table className="cases min-w-[680px] text-[15px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col">字號</TableHead><TableHead scope="col">罪名</TableHead><TableHead scope="col">宣告刑</TableHead>
                      <TableHead scope="col"><span className="inline-flex items-center gap-1">相似度 <InfoLink to="相似度" label="相似度說明" /></span></TableHead>
                      <TableHead scope="col" className="no-print"><span className="sr-only">動作</span></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {report.similar.map((c) => (
                      <TableRow key={c.case_id}>
                        <TableCell className="whitespace-normal">{c.case_number}<br /><span className="text-sm text-muted-foreground">{c.summary}</span></TableCell>
                        <TableCell data-label="罪名">{c.mid}</TableCell>
                        <TableCell data-label="宣告刑">{c.sentence ?? "—"}</TableCell>
                        <TableCell data-label="相似度">{c.similarity.toFixed(2)}</TableCell>
                        <TableCell className="no-print">{c.url
                          ? <a href={c.url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center">判決原文</a>
                          : <Link to={`/judgment/criminal/${c.case_id}`} className="inline-flex min-h-11 items-center">判決導讀</Link>}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
          {report.model && <ModelScore model={report.model} />}
        </>
      )}
    </ResultFrame>
  );
}
