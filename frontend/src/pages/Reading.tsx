import { ArrowLeftIcon, HomeIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { LinkButton } from "../components/LinkButton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { api } from "../api/client";
import type { Guide, GuideFunction } from "../api/types";
import { ErrorBox, Loading, MockBadge } from "../components/Common";
import { Layout, PAGE } from "../components/Layout";
import { money, outcomeLabel } from "../format";

const FUNCTIONS: { id: GuideFunction; label: string; swatch: string }[] = [
  { id: "issue", label: "爭點", swatch: "var(--p-issue)" },
  { id: "claim", label: "原告主張", swatch: "var(--p-claim)" },
  { id: "defense", label: "被告答辯", swatch: "var(--p-defense)" },
  { id: "evidence", label: "證據", swatch: "var(--p-evidence)" },
  { id: "court", label: "法院判斷", swatch: "var(--p-court)" },
];

export default function Reading() {
  const { source = "civil", caseId = "" } = useParams();
  const navigate = useNavigate();
  const [guide, setGuide] = useState<Guide | null>(null);
  const [error, setError] = useState("");
  const [on, setOn] = useState<Record<GuideFunction, boolean>>({ issue: true, claim: false, defense: false, evidence: true, court: true });

  const load = useCallback(() => {
    setError("");
    api.guide(source, Number(caseId)).then(setGuide).catch((e: Error) => setError(e.message));
  }, [source, caseId]);
  useEffect(load, [load]);

  const counts = (guide?.paragraphs ?? []).reduce<Record<string, number>>((acc, p) => ({ ...acc, [p.function]: (acc[p.function] ?? 0) + 1 }), {});
  const back = <Button variant="outline" onClick={() => navigate(-1)}><ArrowLeftIcon data-icon="inline-start" />回到參考結果</Button>;

  return (
    <Layout nav={back}>
      <main className={cn(PAGE, "grid gap-6 py-8 pb-16 lg:grid-cols-[300px_minmax(0,1fr)] lg:gap-8")}>
        <aside className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-24 lg:self-start">
          <Card size="sm" aria-labelledby="legend-title">
            <CardHeader>
              <CardTitle id="legend-title" className="text-base font-bold">標示段落</CardTitle>
              <CardDescription>勾選要標色的段落類型。</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col">
              {FUNCTIONS.map((f) => (
                <Label key={f.id} className="flex min-h-11 cursor-pointer items-center gap-3 text-[15px] font-normal">
                  <Checkbox checked={on[f.id]} onCheckedChange={() => setOn({ ...on, [f.id]: !on[f.id] })} className="size-5" />
                  <span className="size-3.5 rounded-sm ring-1 ring-input" style={{ background: f.swatch }} aria-hidden="true" />
                  <span>{f.label}</span>
                  <span className="ml-auto text-[13px] text-muted-foreground">{counts[f.id] ?? 0} 段</span>
                </Label>
              ))}
            </CardContent>
          </Card>
          <Card size="sm">
            <CardHeader><CardTitle className="text-base font-bold">關於這些標示</CardTitle></CardHeader>
            <CardContent className="text-sm leading-relaxed text-muted-foreground">
              {guide?.labeler === "rule-v0"
                ? "段落用規則初步標示（第一版），之後改用段落功能標註模型。"
                : "段落功能依標註手冊，由 LLM 輔助標註、法律系學生抽查驗證。"}
              標示只說明「這段在做什麼」，不代表法院最看重哪一段。判決中的當事人姓名已換成【原告】【被告】，證人、訴外人等換成【關係人】；這是自動處理，可能有遺漏。
            </CardContent>
          </Card>
        </aside>

        <article className="flex min-w-0 flex-col gap-6">
          {error && <ErrorBox message={error} onRetry={load} />}
          {!guide && !error && <Loading />}
          {guide && (
            <>
              <Card>
                <CardHeader className="gap-3">
                  <MockBadge show={guide.mock}>示例判決（內容為示意，非真實判決）</MockBadge>
                  <h1 className="text-2xl font-bold">{guide.case.case_number}</h1>
                  <dl className="flex flex-wrap gap-x-6 gap-y-1.5 text-[15px]">
                    <div className="flex gap-1.5"><dt className="text-muted-foreground">案由</dt><dd>{guide.case.mid}</dd></div>
                    <div className="flex gap-1.5"><dt className="text-muted-foreground">結果</dt><dd>{outcomeLabel(guide.case.outcome)}</dd></div>
                    {guide.case.claimed_amount ? (
                      <div className="flex gap-1.5"><dt className="text-muted-foreground">判准／請求</dt>
                        <dd>{money(guide.case.awarded_amount ?? 0)}／{money(guide.case.claimed_amount)}</dd></div>
                    ) : null}
                  </dl>
                </CardHeader>
              </Card>
              <Card aria-label="判決內容">
                <CardContent className="flex flex-col gap-3">
                  {guide.paragraphs.map((p, i) => (
                    <section key={i} className="para rounded-lg bg-card px-4 py-3.5 transition-colors" data-fn={p.function} data-on={on[p.function]}>
                      <span className="mb-1.5 inline-block rounded px-2 py-px text-xs font-bold" style={{ background: "var(--chip-bg, var(--muted))", color: "var(--chip-ink, var(--muted-foreground))" }}>{p.label}</span>
                      <p className="text-[15px] leading-loose">{p.text}</p>
                    </section>
                  ))}
                </CardContent>
              </Card>
              <p className="text-sm text-muted-foreground">字號可到<a href="https://judgment.judicial.gov.tw/FJUD/default.aspx">司法院裁判書查詢系統</a>查詢全文。</p>
              <div><LinkButton variant="outline" to="/"><HomeIcon data-icon="inline-start" />回首頁</LinkButton></div>
            </>
          )}
        </article>
      </main>
    </Layout>
  );
}
