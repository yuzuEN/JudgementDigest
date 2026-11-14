import { ArrowLeftIcon, CheckIcon, ExternalLinkIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { api } from "../api/client";
import type { Guide, GuideFunction } from "../api/types";
import { Bar } from "../components/casey/Bars";
import { OutcomeChip } from "../components/casey/OutcomeChip";
import { InfoNote, LoadingPanel } from "../components/casey/ResultTabs";
import { SampleTag } from "../components/casey/Sample";
import { ErrorBox } from "../components/Common";
import { JUDICIAL_URL, Layout, PAGE } from "../components/Layout";
import { LinkButton } from "../components/LinkButton";
import { outcomeLabel, outcomeTone, percent } from "../format";

/** 五類段落：各有底色，但每段開頭一定有文字標籤，不只靠顏色。法院判斷用白底加粗框。 */
const FUNCTIONS: { id: GuideFunction; label: string; on: string; swatch: string }[] = [
  { id: "claim", label: "原告主張", on: "bg-passage-claim", swatch: "bg-passage-claim" },
  { id: "defense", label: "被告抗辯", on: "bg-passage-defense", swatch: "bg-passage-defense" },
  { id: "issue", label: "爭點", on: "bg-passage-issue", swatch: "bg-passage-issue" },
  { id: "evidence", label: "證據", on: "bg-passage-evidence", swatch: "bg-passage-evidence" },
  { id: "court", label: "法院判斷", on: "bg-passage-court border-2 border-foreground", swatch: "bg-passage-court" },
];

const yuan = (n: number) => Math.round(n).toLocaleString("en-US");

export default function Reading() {
  const { source = "civil", caseId = "" } = useParams();
  const [guide, setGuide] = useState<Guide | null>(null);
  const [error, setError] = useState("");
  const [on, setOn] = useState<Record<GuideFunction, boolean>>({ claim: true, defense: true, issue: true, evidence: true, court: true });

  const load = useCallback(() => {
    setError("");
    api.guide(source, Number(caseId)).then(setGuide).catch((e: Error) => setError(e.message));
  }, [source, caseId]);
  useEffect(load, [load]);

  const counts = (guide?.paragraphs ?? []).reduce<Record<string, number>>((acc, p) => ({ ...acc, [p.function]: (acc[p.function] ?? 0) + 1 }), {});
  const style = (fn: GuideFunction) => FUNCTIONS.find((f) => f.id === fn)!;
  const resultPath = `/result/${source === "criminal" ? "criminal" : "civil"}?tab=cases`;

  return (
    <Layout stage={7} scene={{ who: "explainer", line: "全文已標出主張、抗辯、爭點、證據與法院判斷。你可以選擇要上色的類別，方便找出相關段落。" }}>
      <main className={cn(PAGE, "flex flex-col gap-7 pt-7 pb-14")}>
        <div className="flex flex-col gap-3">
          <LinkButton variant="outline" to={resultPath} className="no-print w-fit border-input text-foreground"><ArrowLeftIcon data-icon="inline-start" />回結果</LinkButton>
          <p className="text-[15px] font-bold tracking-[.04em] text-secondary-foreground">判決導讀</p>
          {guide && <h1 className="text-[26px] leading-[1.4] font-extrabold text-balance sm:text-[32px]">{guide.case.case_number}</h1>}
        </div>

        {error && <ErrorBox message={error} onRetry={load} hint="請重新載入判決，或返回結果頁查看其他判決。" />}
        {!guide && !error && <LoadingPanel>正在整理這件判決…</LoadingPanel>}
        {guide && (
          <div className="flex flex-wrap items-start gap-7">
            <aside className="flex w-full min-w-0 flex-[1_1_280px] flex-col gap-4 sm:max-w-[360px]">
              <Card className="gap-4 px-6.5" aria-labelledby="basic-title">
                <h2 id="basic-title" className="text-xl font-bold">判決資料</h2>
                <dl className="m-0 flex flex-col gap-2.5 text-[15px]">
                  <div><dt className="text-muted-foreground">{source === "criminal" ? "罪名" : "案由"}</dt><dd className="m-0 font-bold">{guide.case.mid}</dd></div>
                  <div className="flex flex-col gap-1"><dt className="text-muted-foreground">結果</dt>
                    <dd className="m-0"><OutcomeChip tone={outcomeTone(guide.case.outcome)}>{outcomeLabel(guide.case.outcome)}</OutcomeChip></dd></div>
                  {guide.case.claimed_amount ? (
                    <div><dt className="text-muted-foreground">判准／請求</dt>
                      <dd className="m-0 tabular-nums"><b>{yuan(guide.case.awarded_amount ?? 0)}</b> ／ {yuan(guide.case.claimed_amount)} 元</dd></div>
                  ) : null}
                </dl>
                {guide.case.claimed_amount ? (() => {
                  const share = (guide.case.awarded_amount ?? 0) / guide.case.claimed_amount;
                  return (
                    <div className="flex flex-col gap-1.5">
                      <Bar value={share} fill="bg-outcome-part" label={`判准金額約占請求金額的 ${percent(share)}`} />
                      <p className="text-sm text-muted-foreground">判准的金額，約占請求的 {percent(share)}。</p>
                    </div>
                  );
                })() : null}
              </Card>

              <Card className="gap-3 px-6.5" aria-labelledby="legend-title">
                <h2 id="legend-title" className="text-xl font-bold">段落標色</h2>
                <p className="text-[15px] text-muted-foreground">選擇要上色的類別。取消後仍會保留文字標籤。</p>
                <div className="flex flex-col gap-2">
                  {FUNCTIONS.map((f) => (
                    <button key={f.id} type="button" aria-pressed={on[f.id]} onClick={() => setOn({ ...on, [f.id]: !on[f.id] })}
                      className={cn("flex min-h-12 items-center gap-3 rounded-[14px] border-2 bg-card px-3.5 py-2 text-left",
                        on[f.id] ? "border-primary" : "border-input")}>
                      <span aria-hidden="true" className={cn("grid size-6 flex-none place-items-center rounded-[7px] border-2",
                        on[f.id] ? "border-primary bg-primary text-primary-foreground" : "border-input bg-card")}>
                        {on[f.id] && <CheckIcon className="size-4" strokeWidth={3} />}
                      </span>
                      <span aria-hidden="true" className={cn("size-[18px] flex-none rounded-[5px] border-[1.5px] border-foreground", on[f.id] ? f.swatch : "bg-transparent")} />
                      <span className="font-bold">{f.label}</span>
                      <span className="ml-auto text-sm text-muted-foreground">{counts[f.id] ?? 0} 段</span>
                    </button>
                  ))}
                </div>
              </Card>

              <Card className="gap-2 px-6.5 shadow-none" aria-labelledby="about-title">
                <h2 id="about-title" className="text-xl font-bold">關於這些標示</h2>
                <p className="text-[15px] text-muted-foreground">
                  段落標示由系統判斷，可能有誤，請以判決原文為準。
                  {guide.labeler === "rule-v0" ? "目前依文字規則標示。" : "段落功能依標註手冊，由 LLM 輔助標註、法律系學生抽查驗證。"}
                </p>
                <p className="text-sm text-muted-foreground">判決中的當事人姓名已換成【原告】【被告】，證人、訴外人與其他人名換成【關係人】，車牌、地址等也已遮蔽；同一角色有多人時加上編號（【被告1】【被告2】），同一件判決裡同一個編號是同一個人。這是自動處理，可能有遺漏。</p>
                <a href={guide.case.url || JUDICIAL_URL} target="_blank" rel="noreferrer" className="inline-flex w-fit items-center gap-1 text-[15px] font-semibold">
                  {guide.case.url ? "在司法院網站看這件判決的原文" : "司法院裁判書查詢系統"}<ExternalLinkIcon className="size-4" aria-hidden="true" />
                </a>
              </Card>
            </aside>

            <Card className="min-w-0 flex-[999_1_500px] gap-4 px-[18px] sm:px-6.5" aria-labelledby="full-title">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 id="full-title" className="text-xl font-bold">判決全文</h2>
                {guide.mock && <SampleTag />}
              </div>
              {guide.mock && <p className="text-[15px] text-sample-fg">這是示例判決，內容為示意，不是真實判決。</p>}
              {guide.paragraphs.map((p, i) => {
                const f = style(p.function);
                return (
                  <section key={i} data-fn={p.function} data-on={on[p.function]}
                    className={cn("para flex flex-col gap-1.5 rounded-[12px] px-4 py-3.5 transition-colors motion-reduce:transition-none",
                      on[p.function] ? f.on : "border border-dashed border-input bg-transparent")}>
                    <span className="text-[13px] font-extrabold tracking-[.06em]">{f.label}</span>
                    <p className="leading-loose">{p.text}</p>
                  </section>
                );
              })}
              <InfoNote>
                {guide.case.url
                  ? <>想看完整、正式的判決，請看<a href={guide.case.url} target="_blank" rel="noreferrer">司法院網站上的原文</a>。</>
                  : <>想看完整、正式的判決，請到<a href={JUDICIAL_URL} target="_blank" rel="noreferrer">司法院裁判書查詢系統</a>用字號查詢。</>}
                本頁不是法律意見。
              </InfoNote>
            </Card>
          </div>
        )}
      </main>
    </Layout>
  );
}
