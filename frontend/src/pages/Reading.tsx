import { ArrowLeftIcon, CheckIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { api } from "../api/client";
import type { Guide, GuideFunction } from "../api/types";
import { Bar } from "../components/casey/Bars";
import { OutcomeChip } from "../components/casey/OutcomeChip";
import { MarkedText, ReasoningCard } from "../components/casey/Reasoning";
import { MidLabels } from "../components/casey/MidLabels";
import { InfoRow, OriginalLink } from "../components/casey/ReadingParts";
import { LoadingPanel } from "../components/casey/ResultTabs";
import { SampleTag } from "../components/casey/Sample";
import { ErrorBox } from "../components/Common";
import { Layout, PAGE } from "../components/Layout";
import { LinkButton } from "../components/LinkButton";
import CriminalReading from "./CriminalReading";
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
  const [active, setActive] = useState<number | null>(null);   // 「法院怎麼認定」選到的項目

  const load = useCallback(() => {
    setError("");
    api.guide(source, Number(caseId)).then(setGuide).catch((e: Error) => setError(e.message));
  }, [source, caseId]);
  useEffect(load, [load]);
  useEffect(() => setActive(null), [guide]);
  const activeItem = active === null ? null : guide?.reasoning?.items[active] ?? null;
  useEffect(() => {
    if (activeItem) document.getElementById(`para-${activeItem.paragraph}`)?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [activeItem]);

  const counts = (guide?.paragraphs ?? []).reduce<Record<string, number>>((acc, p) => ({ ...acc, [p.function]: (acc[p.function] ?? 0) + 1 }), {});
  const style = (fn: GuideFunction) => FUNCTIONS.find((f) => f.id === fn)!;
  const resultPath = `/result/${source === "criminal" ? "criminal" : "civil"}?tab=cases`;

  if (source === "criminal") return <CriminalReading guide={guide} error={error} onRetry={load} />;

  return (
    <Layout stage={7} scene={{ who: "explainer", line: "在導讀中，判決書會根據不同功能段落做顏色區分。" }}>
      <main className={cn(PAGE, "flex flex-col gap-7 pt-7 pb-14")}>
        <div className="flex flex-col gap-3">
          <LinkButton variant="outline" to={resultPath} className="no-print w-fit border-input text-foreground"><ArrowLeftIcon data-icon="inline-start" />回結果</LinkButton>
          {guide && (
            <div className="flex items-start justify-between gap-4">
              <h1 className="text-[26px] leading-[1.4] font-extrabold text-balance sm:text-[32px]">{guide.case.case_number}</h1>
              <OriginalLink url={guide.case.url} caseNumber={guide.case.case_number} />
            </div>
          )}
        </div>

        {error && <ErrorBox message={error} onRetry={load} hint="請重新載入判決，或返回結果頁查看其他判決。" />}
        {!guide && !error && <LoadingPanel>正在整理這件判決…</LoadingPanel>}
        {guide && (
          <div className="flex flex-wrap items-start gap-7">
            <aside className="flex w-full min-w-0 flex-[1_1_280px] flex-col gap-4 sm:max-w-[360px]">
              <Card className="gap-4 px-6.5" aria-labelledby="basic-title">
                <h2 id="basic-title" className="text-xl font-bold">判決資料</h2>
                {/* 和「你填的資料」一樣：名稱在左、內容在右；金額的長條和說明在下面各自一列 */}
                <dl className="m-0 flex flex-col gap-2.5 text-[15px]">
                  <InfoRow label="案由"><MidLabels mids={[guide.case.mid]} vertical /></InfoRow>
                  <InfoRow label="結果"><OutcomeChip tone={outcomeTone(guide.case.outcome)}>{outcomeLabel(guide.case.outcome)}</OutcomeChip></InfoRow>
                  {guide.case.claimed_amount ? (
                    <InfoRow label="判准／請求" nowrap><span className="font-normal tabular-nums"><b>{yuan(guide.case.awarded_amount ?? 0)}</b> ／ {yuan(guide.case.claimed_amount)} 元</span></InfoRow>
                  ) : guide.case.awarded_amount ? (
                    // 請求金額沒抽到時（例如小額判決只寫「共計…等語」，沒有聲明），判准金額照樣顯示
                    <>
                      <InfoRow label="判准" nowrap><span className="tabular-nums">{yuan(guide.case.awarded_amount)} 元</span></InfoRow>
                      <p className="text-sm text-muted-foreground">這件判決的請求金額沒有抽取到，無法算出判准的比例。</p>
                    </>
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

              <ReasoningCard reasoning={guide.reasoning} active={active} onSelect={setActive} />

              <Card className="gap-2 px-6.5 shadow-none" aria-labelledby="about-title">
                <h2 id="about-title" className="text-xl font-bold">關於這些標示</h2>
                <p className="text-[15px] text-muted-foreground">
                  段落標示由系統判斷，可能有誤，請以判決原文為準。
                  {guide.labeler === "rule-v0" ? "目前依文字規則標示。" : "段落功能依標註手冊，由 LLM 輔助標註、法律系學生抽查驗證。"}
                </p>
                <p className="text-sm text-muted-foreground">判決中的當事人姓名已換成【原告】【被告】，證人、訴外人與其他人名換成【關係人】，車牌、地址等也已遮蔽；同一角色有多人時加上編號（【被告1】【被告2】），同一件判決裡同一個編號是同一個人。這是自動處理，可能有遺漏。</p>
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
                  <section key={i} id={`para-${i}`} data-fn={p.function} data-on={on[p.function]}
                    className={cn("para flex flex-col gap-1.5 rounded-[12px] px-4 py-3.5 transition-colors motion-reduce:transition-none",
                      on[p.function] ? f.on : "border border-dashed border-input bg-transparent")}>
                    <span className="text-[13px] font-extrabold tracking-[.06em]">{f.label}</span>
                    <p className="leading-loose"><MarkedText text={p.text} item={activeItem?.paragraph === i ? activeItem : null} /></p>
                  </section>
                );
              })}
            </Card>
          </div>
        )}
      </main>
    </Layout>
  );
}
