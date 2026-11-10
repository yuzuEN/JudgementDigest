import { ArrowLeftIcon, ArrowRightIcon, PenLineIcon, PlusIcon, SparklesIcon, XIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { LinkButton } from "../components/LinkButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "../api/client";
import type { Question } from "../api/types";
import { CARD_TITLE, Loading, PageTitle } from "../components/Common";
import { Layout, PAGE } from "../components/Layout";
import { MaskedText, RewriteCard } from "../components/RewriteCard";
import { money, parseAmount, sensitiveKinds } from "../format";
import { maskText } from "../mask";
import { fullText, primaryMid, useIntake } from "../state";

const DEFENDANT_LABEL = { person: "個人", company: "公司、行號", government: "政府機關、學校、醫院" } as const;
const CASE_LABEL = { civil: "民事", criminal: "刑事", unsure: "不確定（民事、刑事都查）" } as const;

const MAX_QUESTIONS = 4;

export default function Confirm() {
  const { intake, update } = useIntake();
  const navigate = useNavigate();
  const [questions, setQuestions] = useState<Question[]>([]);
  const [aiQuestions, setAiQuestions] = useState<Question[]>([]);
  const [llmAvailable, setLlmAvailable] = useState(false);
  const [vendor, setVendor] = useState("AI 服務");
  const [aiState, setAiState] = useState<"idle" | "asking" | "done" | "failed" | "unrelated" | "limited" | "declined">("idle");
  const [nameInput, setNameInput] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const text = useMemo(() => fullText(intake), [intake]);
  const mid = primaryMid(intake);

  // 打開頁面時只用固定題庫，描述不離開瀏覽器。傳給 LLM 要等使用者加好姓名、同意之後自己按按鈕（askLlm）
  useEffect(() => {
    if (!intake.text.trim()) return;
    let stale = false;
    // 這時使用者還沒加好姓名，所以不送描述：只拿題庫，在瀏覽器篩掉已經回答的問題
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
    // 描述或姓名改了，之前確認的改寫就對不上了
    update(intake.rewriteFor && intake.rewriteFor !== maskedText ? { maskedText, searchText: "", rewriteFor: "" } : { maskedText });
    // 不把 update 放進依賴：它會隨 intake 變動，放進去會一直重跑
  }, [text, intake.names]);

  if (!intake.text.trim()) return <Navigate to="/start" replace />;

  const kinds = sensitiveKinds(text);
  const sensitive = kinds.length > 0;
  const ready = intake.maskedText !== "" && (!sensitive || intake.sensitiveConsent);
  const addName = () => {
    const n = nameInput.trim();
    if (n && !intake.names.includes(n)) update({ names: [...intake.names, n] });
    setNameInput("");
  };
  const askLlm = () => {
    setAiState("asking");
    api.followup(intake.caseType, mid, maskText(intake.text, intake.names), true)
      .then((r) => { if (r.source === "llm") setAiQuestions(r.questions); setAiState(r.source === "llm" ? "done" : r.fallback === "not_dispute" ? "unrelated" : r.fallback === "limited" ? "limited" : "failed"); })
      .catch(() => setAiState("failed"));
  };
  const answer = (q: Question, value: string) =>
    update({ followupAnswers: { ...intake.followupAnswers, [q.id]: { question: q.text, answer: value } } });
  const choosing = llmAvailable && (aiState === "idle" || aiState === "asking");
  const shown = aiState === "done" ? aiQuestions : questions;
  // 已經問過 AI 就直接切回去，不用再傳一次
  const useAi = () => setAiState(aiQuestions.length > 0 ? "done" : "idle");
  const questionHint = aiState === "done"
    ? "這些問題由 AI 依你的案情產生，只用來補充事實，不是法律意見。可以跳過；回答會加在你的描述後面。"
    : "這類案件常缺的細節，是固定的問題，不會傳給 AI。可以跳過；回答會加在你的描述後面。";
  const resultPath = intake.caseType === "criminal" ? "/result/criminal" : "/result/civil";
  const backButton = (
    <LinkButton variant="outline" to="/start"><ArrowLeftIcon data-icon="inline-start" />不同意，回上一步刪掉這些描述</LinkButton>
  );

  return (
    <Layout step={2}>
      <main className={cn(PAGE, "grid gap-6 py-8 pb-16 lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-8")}>
        <div className="flex min-w-0 flex-col gap-6">
          <PageTitle title="確認內容" lead="補上幾個缺少的細節，並確認哪些資料會被送出。" />

          <Card aria-labelledby="mask-title">
            <CardHeader>
              <CardTitle id="mask-title" className={CARD_TITLE}>會送出的內容（已遮名）</CardTitle>
              <CardDescription className="text-[15px]">身分證字號、電話、電子郵件、地址已自動遮掉，標成<mark className="masked">橘色</mark>。姓名請在下面加上，送出前會一起遮掉。</CardDescription>
              <CardAction>
                <LinkButton variant="outline" to="/start"><PenLineIcon data-icon="inline-start" />回上一步修改描述</LinkButton>
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              <MaskedText text={intake.maskedText} live />
              <Field>
                <FieldLabel htmlFor="mask-name" className="text-base">要遮掉的名字（你、對方、其他人）</FieldLabel>
                <div className="flex gap-2">
                  <Input id="mask-name" type="text" value={nameInput} placeholder="例如：王小明" onChange={(e) => setNameInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addName(); } }} />
                  <Button type="button" variant="outline" className="h-11" onClick={addName}><PlusIcon data-icon="inline-start" />加入</Button>
                </div>
              </Field>
              {intake.names.length > 0 && (
                <ul aria-label="要遮掉的名字" className="flex flex-wrap gap-2">
                  {intake.names.map((n) => (
                    <li key={n}>
                      <Badge variant="secondary" className="h-8 gap-1 rounded-full pr-1 pl-3 text-sm">
                        {n}
                        <Button type="button" variant="ghost" size="icon-xs" className="rounded-full" aria-label={`不遮「${n}」`}
                          onClick={() => update({ names: intake.names.filter((x) => x !== n) })}>
                          <XIcon />
                        </Button>
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {sensitive && (
            <Card aria-labelledby="consent-title" className="bg-warn text-warn-foreground ring-warn-border">
              <CardHeader>
                <CardTitle id="consent-title" className="text-lg font-bold text-warn-title">需要你同意：敏感個人資料</CardTitle>
                <CardDescription className="text-[15px] text-warn-foreground">你可以不提供：不同意的話，回上一步刪掉這些描述就能繼續，只是參考結果可能比較不準。</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <Label className="flex cursor-pointer items-start gap-3 rounded-lg bg-surface p-4 text-[15px] leading-relaxed font-normal text-foreground ring-1 ring-warn-border">
                  <Checkbox className="mt-0.5 size-5" checked={intake.sensitiveConsent} onCheckedChange={(v) => update({ sensitiveConsent: Boolean(v) })} />
                  <span><strong>我同意</strong>本平台處理我提供的敏感個人資料（偵測到：{kinds.join("、")}），只用於產生這次的參考結果。{llmAvailable && `如果你選擇請 AI 提問或整理敘述，這些內容也會傳給 ${vendor}。`}</span>
                </Label>
                {!intake.sensitiveConsent && <div>{backButton}</div>}
              </CardContent>
            </Card>
          )}

          {choosing && (
            <Card aria-labelledby="ai-title">
              <CardHeader>
                <CardTitle id="ai-title" className={CARD_TITLE}>要補充更多細節嗎？（可略過）</CardTitle>
                <CardDescription className="text-[15px]">按下按鈕後，上面遮名後的內容（包含你同意處理的資料）會傳給 {vendor}，由 AI 依你的案情提問。請先確認姓名都已遮掉。不按就不會傳。</CardDescription>
              </CardHeader>
              <CardContent>
                {aiState === "asking" ? <Loading>正在請 AI 看還需要補充哪些細節……</Loading> :
                  <div className="flex flex-wrap gap-3">
                    <Button type="button" variant="outline" disabled={!ready} onClick={askLlm}><SparklesIcon data-icon="inline-start" />請 AI 幫我看還缺什麼</Button>
                    <Button type="button" variant="outline" onClick={() => setAiState("declined")}>不用 AI，回答一般問題</Button>
                  </div>}
              </CardContent>
            </Card>
          )}

          {!choosing && shown.length > 0 && (
            <Card aria-labelledby="q-title">
              <CardHeader>
                <CardTitle id="q-title" className={CARD_TITLE}>還想問你幾件事</CardTitle>
                <CardDescription className="text-[15px]">{questionHint}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {aiState === "failed" && <p className="text-sm font-medium text-caution">AI 暫時無法使用，先回答下面的一般問題就好。</p>}
                {aiState === "limited" && <p className="text-sm font-medium text-caution">AI 提問的次數暫時用完了，先回答下面的一般問題就好。</p>}
                {aiState === "unrelated" && <p className="text-sm font-medium text-caution">這段描述看起來不像法律糾紛，所以沒有傳給 AI。可以回上一步補充，或先回答下面的一般問題。</p>}
                {shown.map((q, i) => (
                  <Card key={q.id} size="sm" className="bg-muted/50 shadow-none">
                    <CardHeader>
                      <CardTitle className="flex gap-2 text-base font-semibold">
                        <span className="text-primary" aria-hidden="true">{i + 1}.</span>
                        <Label htmlFor={`q-${q.id}`} className="text-base leading-snug font-semibold">{q.text}</Label>
                      </CardTitle>
                      <CardDescription>{q.why}</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <Input id={`q-${q.id}`} type="text" placeholder="你的回答（可留空）"
                        value={intake.followupAnswers[q.id]?.answer ?? ""} onChange={(e) => answer(q, e.target.value)} />
                    </CardContent>
                  </Card>
                ))}
                <div className="flex flex-wrap items-center gap-3">
                  {llmAvailable && aiState === "done" &&
                    <Button type="button" variant="outline" size="sm" onClick={() => setAiState("declined")}>改回答一般問題</Button>}
                  {llmAvailable && aiState === "declined" &&
                    <Button type="button" variant="outline" size="sm" onClick={useAi}><SparklesIcon data-icon="inline-start" />改請 AI 提問</Button>}
                  {llmAvailable && aiState === "failed" &&
                    <Button type="button" variant="outline" size="sm" onClick={useAi}>再試一次 AI</Button>}
                </div>
                {llmAvailable && (aiState === "done" || aiState === "declined") &&
                  <p className="text-[13px] text-muted-foreground">切換問題時，已經回答的內容會保留，可以在上面的預覽看到。</p>}
              </CardContent>
            </Card>
          )}

          {llmAvailable && <RewriteCard ready={ready} vendor={vendor} onReviewing={setReviewing} />}

          <div className="flex flex-wrap items-center gap-4">
            <Button type="button" size="lg" disabled={!ready || reviewing} onClick={() => navigate(resultPath)}>看參考結果<ArrowRightIcon data-icon="inline-end" /></Button>
            {reviewing && <span className="font-medium text-caution">請先確認整理後的內容，或改用原本的描述。</span>}
            {sensitive && !intake.sensitiveConsent && <span className="font-medium text-caution">內容包含敏感個人資料，請先在上面選擇同意或不同意。</span>}
          </div>
        </div>

        <aside className="flex min-w-0 flex-col gap-4">
          <Card size="sm">
            <CardHeader><CardTitle className="text-base font-bold">你提供的資料</CardTitle></CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-[15px]">
                <dt className="text-muted-foreground">類型</dt><dd>{CASE_LABEL[intake.caseType]}</dd>
                {intake.caseType !== "criminal" && <>
                  <dt className="text-muted-foreground">糾紛</dt><dd>{intake.mids.length ? intake.mids.join("、") : "不確定"}</dd>
                  <dt className="text-muted-foreground">請求金額</dt><dd>{money(parseAmount(intake.claimedAmount))}</dd>
                  <dt className="text-muted-foreground">對方</dt><dd>{intake.defendantType ? DEFENDANT_LABEL[intake.defendantType] : "不確定"}</dd>
                  <dt className="text-muted-foreground">律師</dt><dd>{intake.lawyer === "yes" ? "有" : intake.lawyer === "no" ? "還沒有" : "未填"}</dd>
                  <dt className="text-muted-foreground">證據</dt><dd>{intake.evidence.length ? `${intake.evidence.length} 項` : "未勾選"}</dd>
                </>}
                {intake.caseType === "criminal" && <>
                  <dt className="text-muted-foreground">證據</dt><dd>{intake.criminalEvidence.length ? intake.criminalEvidence.join("、") : "未勾選"}</dd>
                </>}
              </dl>
            </CardContent>
          </Card>
          <Card size="sm" className="bg-info text-info-foreground ring-info-border">
            <CardHeader><CardTitle className="text-base font-bold">同一件事可能有民事也有刑事</CardTitle></CardHeader>
            <CardContent className="text-[15px] leading-relaxed">例如車禍受傷：刑事上可能是過失傷害，民事上可以請求損害賠償。兩種結果會分開顯示。</CardContent>
          </Card>
          <Card size="sm" aria-labelledby="notice-title">
            <CardHeader><CardTitle id="notice-title" className="text-base font-bold">資料使用說明</CardTitle></CardHeader>
            <CardContent>
              <ul className="flex list-disc flex-col gap-2 pl-5 text-sm leading-relaxed">
                <li>蒐集者：JudgementDigest 專題團隊；目的：產生類案判決參考結果。</li>
                <li>遮名在你的瀏覽器裡完成，原文和你加入的姓名不會傳到我們的伺服器。送出的是遮名後的內容；本平台不保存你的描述，結果只顯示在你的瀏覽器裡。</li>
                {llmAvailable && <li>只有在你按下「請 AI 幫我看還缺什麼」或「請 AI 整理敘述」時，遮名後的內容才會傳給 {vendor} 的付費 API，不會被用來訓練或改善它的模型。</li>}
                <li>病歷、醫療、健康檢查、基因、性生活、犯罪前科是法律特別保護的資料。你可以不提供：不同意的話，回上一步刪掉這些描述就能繼續，只是參考結果可能比較不準。</li>
              </ul>
            </CardContent>
          </Card>
        </aside>
      </main>
    </Layout>
  );
}
