import { ArrowLeftIcon, CheckIcon, ExternalLinkIcon } from "lucide-react";
import { Fragment, useState } from "react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import type { CriminalGuideFunction, Guide } from "../api/types";
import { InfoNote, LoadingPanel } from "../components/casey/ResultTabs";
import { SampleTag } from "../components/casey/Sample";
import { ErrorBox } from "../components/Common";
import { JUDICIAL_URL, Layout, PAGE } from "../components/Layout";
import { LinkButton } from "../components/LinkButton";

type Marked = Exclude<CriminalGuideFunction, "info" | "other">;

/** 可以上色的段落；案件資訊、署名與上訴說明不上色。和民事一樣，每段開頭一定有文字標籤，不只靠顏色。 */
const FUNCTIONS: { id: Marked; label: string; on: string; swatch: string }[] = [
  { id: "verdict", label: "主文", on: "bg-passage-issue", swatch: "bg-passage-issue" },
  { id: "facts", label: "犯罪事實", on: "bg-passage-claim", swatch: "bg-passage-claim" },
  { id: "evidence", label: "證據", on: "bg-passage-evidence", swatch: "bg-passage-evidence" },
  { id: "court", label: "論罪科刑", on: "bg-passage-court border-2 border-foreground", swatch: "bg-passage-court" },
  { id: "laws", label: "法條", on: "bg-passage-defense", swatch: "bg-passage-defense" },
  { id: "table", label: "附表", on: "bg-muted", swatch: "bg-muted" },
];
const isMarked = (fn: CriminalGuideFunction): fn is Marked => fn !== "info" && fn !== "other";

export default function CriminalReading({ guide, error, onRetry }: {
  guide: Guide | null; error: string; onRetry: () => void;
}) {
  const [on, setOn] = useState<Record<Marked, boolean>>({ verdict: true, facts: true, evidence: true, court: true, laws: true, table: true });
  const detail = guide?.criminal;
  const paragraphs = detail?.paragraphs ?? [];
  const counts = paragraphs.reduce<Record<string, number>>((acc, p) => ({ ...acc, [p.function]: (acc[p.function] ?? 0) + 1 }), {});
  const shown = FUNCTIONS.filter((f) => counts[f.id]);

  return (
    <Layout stage={7} scene={{ who: "explainer", line: "全文已標出主文、犯罪事實、證據、論罪科刑與法條。你可以選擇要上色的類別，方便找出相關段落。" }}>
      <main className={cn(PAGE, "flex flex-col gap-7 pt-7 pb-14")}>
        <div className="flex flex-col gap-3">
          <LinkButton variant="outline" to="/result/criminal?tab=cases" className="no-print w-fit border-input text-foreground">
            <ArrowLeftIcon data-icon="inline-start" />回結果
          </LinkButton>
          <p className="text-[15px] font-bold tracking-[.04em] text-secondary-foreground">刑事判決導讀</p>
          {guide && <h1 className="text-[26px] leading-[1.4] font-extrabold text-balance sm:text-[32px]">{guide.case.case_number}</h1>}
        </div>

        {error && <ErrorBox message={error} onRetry={onRetry} hint="請重新載入判決，或返回結果頁查看其他判決。" />}
        {!guide && !error && <LoadingPanel>正在整理這件判決…</LoadingPanel>}
        {guide && (
          <div className="flex flex-wrap items-start gap-7">
            <aside className="flex w-full min-w-0 flex-[1_1_280px] flex-col gap-4 sm:max-w-[360px]">
              <Card className="gap-4 px-6.5" aria-labelledby="criminal-basic-title">
                <h2 id="criminal-basic-title" className="text-xl font-bold">判決資料</h2>
                <dl className="m-0 flex flex-col gap-2.5 text-[15px]">
                  {[
                    ["法院", guide.case.court || "未提供"],
                    ["裁判日期", detail?.judgment_date || "未提供"],
                    ["罪名", guide.case.mid || "未提供"],
                    ["宣告刑", guide.case.sentence || "請看主文"],
                  ].map(([label, text]) => <div key={label}><dt className="text-muted-foreground">{label}</dt><dd className="m-0 font-bold">{text}</dd></div>)}
                </dl>
                <p className="text-sm text-muted-foreground">宣告刑是系統整理的結果；數罪、緩刑、易科罰金等細節以主文為準。</p>
                {guide.case.url && <a href={guide.case.url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 w-fit items-center gap-1 font-semibold">
                  司法院判決原文<ExternalLinkIcon className="size-4" aria-hidden="true" />
                </a>}
              </Card>

              {shown.length > 0 && (
                <Card className="gap-3 px-6.5" aria-labelledby="legend-title">
                  <h2 id="legend-title" className="text-xl font-bold">段落標色</h2>
                  <p className="text-[15px] text-muted-foreground">選擇要上色的類別。取消後仍會保留文字標籤。</p>
                  <div className="flex flex-col gap-2">
                    {shown.map((f) => (
                      <button key={f.id} type="button" aria-pressed={on[f.id]} onClick={() => setOn({ ...on, [f.id]: !on[f.id] })}
                        className={cn("flex min-h-12 items-center gap-3 rounded-[14px] border-2 bg-card px-3.5 py-2 text-left",
                          on[f.id] ? "border-primary" : "border-input")}>
                        <span aria-hidden="true" className={cn("grid size-6 flex-none place-items-center rounded-[7px] border-2",
                          on[f.id] ? "border-primary bg-primary text-primary-foreground" : "border-input bg-card")}>
                          {on[f.id] && <CheckIcon className="size-4" strokeWidth={3} />}
                        </span>
                        <span aria-hidden="true" className={cn("size-[18px] flex-none rounded-[5px] border-[1.5px] border-foreground", on[f.id] ? f.swatch : "bg-transparent")} />
                        <span className="font-bold">{f.label}</span>
                        <span className="ml-auto text-sm text-muted-foreground">{counts[f.id]} 段</span>
                      </button>
                    ))}
                  </div>
                </Card>
              )}

              <Card className="gap-2 px-6.5 shadow-none" aria-labelledby="about-title">
                <h2 id="about-title" className="text-xl font-bold">關於這些標示</h2>
                <p className="text-[15px] text-muted-foreground">段落依判決書的標題與編號自動切分、標示，可能有誤，請以判決原文為準。</p>
                <p className="text-sm text-muted-foreground">辨識到的被告姓名換成「被告」，其他人名換成【關係人】。自動遮名可能有遺漏。</p>
              </Card>
            </aside>

            <Card className="min-w-0 flex-[999_1_500px] gap-4 px-[18px] sm:px-6.5" aria-labelledby="full-title">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 id="full-title" className="text-xl font-bold">{detail?.source === "dataset" ? "犯罪事實" : "判決全文"}</h2>
                {guide.mock && <SampleTag />}
              </div>
              {guide.mock && <p className="text-[15px] text-sample-fg">這是示例判決，內容為示意，不是真實判決。</p>}
              {detail?.source === "dataset" && (
                <p className="rounded-[12px] border bg-muted p-4 text-[15px] leading-relaxed">
                  這件判決沒有收錄全文，以下只有資料集裡的犯罪事實；「××」是資料集原本遮掉的罪名、法條。主文與理由請看司法院原文。
                </p>
              )}
              {!detail && (
                <div role="status" className="rounded-[12px] border bg-muted p-4">
                  <p className="font-bold">這件判決沒有收錄全文</p>
                  <p className="mt-1 text-[15px] text-muted-foreground">目前只有摘要，完整內容請看司法院原文。</p>
                  {guide.case.summary && <p className="mt-3 leading-loose">摘要：{guide.case.summary}</p>}
                </div>
              )}
              {paragraphs.map((p, i) => {
                const f = isMarked(p.function) ? FUNCTIONS.find((x) => x.id === p.function)! : null;
                const lit = f ? on[f.id] : false;
                const newPart = p.part && p.part !== paragraphs[i - 1]?.part;
                return (
                  <Fragment key={i}>
                    {newPart && p.part !== "資料集節錄" && <h3 className="mt-4 border-t pt-5 text-lg font-bold">{p.part}</h3>}
                    <section data-fn={p.function} data-on={f ? lit : undefined}
                      className={cn("para flex flex-col gap-1.5 rounded-[12px] px-4 py-3.5 transition-colors motion-reduce:transition-none",
                        !f ? "text-muted-foreground" : lit ? f.on : "border border-dashed border-input bg-transparent")}>
                      <span className="text-[13px] font-extrabold tracking-[.06em]">{p.label}</span>
                      <p className={cn("leading-loose break-words", p.pre && "whitespace-pre-wrap", p.function === "table" && "overflow-x-auto text-[15px]")}>{p.text}</p>
                    </section>
                  </Fragment>
                );
              })}
              <InfoNote>正式的判決請到<a href={guide.case.url ?? JUDICIAL_URL} target="_blank" rel="noreferrer">司法院裁判書查詢系統</a>查詢。本頁不是法律意見，也不代表你的案件結果。</InfoNote>
            </Card>
          </div>
        )}
      </main>
    </Layout>
  );
}
