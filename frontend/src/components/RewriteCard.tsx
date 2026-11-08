import { CheckCircle2Icon, SparklesIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { api } from "../api/client";
import { splitMasked } from "../format";
import { maskText } from "../mask";
import { primaryMid, useIntake } from "../state";
import { CARD_TITLE, Loading } from "./Common";

type Status = "idle" | "loading" | "review" | "failed" | "limited" | "unrelated";

const NOTICE: Partial<Record<Status, string>> = {
  failed: "AI 暫時無法使用，會改用你原本的描述。",
  limited: "AI 的使用次數暫時用完了，會改用你原本的描述。",
  unrelated: "這段描述看起來不像法律糾紛，所以沒有傳給 AI，會改用你原本的描述。",
};

/** 遮名後的文字，【標記】標成橘色。 */
export function MaskedText({ text, live = false }: { text: string; live?: boolean }) {
  return (
    <div aria-live={live ? "polite" : undefined} className="masked-preview rounded-lg bg-muted/50 p-4 text-[15px] leading-loose whitespace-pre-wrap ring-1 ring-border">
      {splitMasked(text).map((part, i) =>
        part.masked ? <mark key={i} className="masked">{part.text}</mark> : <span key={i}>{part.text}</span>)}
    </div>
  );
}

/** 把描述整理成判決書的寫法，使用者確認後才用來搜尋相似判決。 */
export function RewriteCard({ ready, vendor, onReviewing }: { ready: boolean; vendor: string; onReviewing: (reviewing: boolean) => void }) {
  const { intake, update } = useIntake();
  const [status, setStatus] = useState<Status>("idle");
  const [draft, setDraft] = useState("");
  const [added, setAdded] = useState<string[]>([]);
  const [source, setSource] = useState("");

  const criminal = intake.caseType === "criminal";
  const usedFor = criminal ? "估計刑期" : "搜尋相似判決";
  useEffect(() => onReviewing(status === "review"), [status]);
  // 整理之後描述又改了：內容對不上，要重新整理
  useEffect(() => {
    if (status === "review" && source !== intake.maskedText) setStatus("idle");
  }, [intake.maskedText]);

  const start = () => {
    const text = intake.maskedText;
    setStatus("loading");
    setSource(text);
    api.rewrite(intake.caseType, primaryMid(intake), text)
      .then((r) => {
        if (r.source === "llm" && r.text) {
          setDraft(r.text);
          setAdded(r.added_numbers);
          setStatus("review");
        } else {
          setStatus(r.fallback === "limited" ? "limited" : r.fallback === "not_dispute" ? "unrelated" : "failed");
        }
      })
      .catch(() => setStatus("failed"));
  };
  const confirm = () => {
    update({ searchText: maskText(draft.trim(), intake.names), rewriteFor: source });
    setStatus("idle");
  };
  const clear = () => {
    update({ searchText: "", rewriteFor: "" });
    setStatus("idle");
  };

  return (
    <Card aria-labelledby="rewrite-title">
      <CardHeader>
        <CardTitle id="rewrite-title" className={CARD_TITLE}>整理成判決書的寫法（建議）</CardTitle>
        <CardDescription className="text-[15px]">判決用語和日常說法不同，{criminal ? "刑期模型是讀判決書的「犯罪事實」學的，整理後估得比較準" : "整理後比較容易找到相似的判決"}。按下按鈕後，上面遮名後的內容會傳給 {vendor}；不按就用你原本的描述。</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {NOTICE[status] && <p className="text-sm font-medium text-caution">{NOTICE[status]}</p>}

        {status === "loading" && <Loading>正在整理敘述……</Loading>}

        {status === "review" && (
          <>
            <Field>
              <FieldLabel htmlFor="rewrite-draft" className="text-base">請確認整理後的內容，可以直接修改</FieldLabel>
              <Textarea id="rewrite-draft" rows={7} className="text-base" value={draft} onChange={(e) => setDraft(e.target.value)} />
            </Field>
            <p className="text-sm text-muted-foreground">請檢查有沒有多出你沒說過的事，例如{criminal ? "日期、傷勢、前科、和解" : "日期、金額、簽約或書面文件"}。這段只用來{usedFor}，不是法律文件。</p>
            {added.length > 0 && <p className="text-sm font-medium text-caution">這些數字沒有出現在你的描述裡，請確認是否正確：{added.join("、")}</p>}
            <div className="flex flex-wrap gap-3">
              <Button type="button" disabled={!draft.trim()} onClick={confirm}>確認用這段{criminal ? "估計" : "搜尋"}</Button>
              <Button type="button" variant="outline" onClick={clear}>不用，改用原本的描述</Button>
            </div>
          </>
        )}

        {status !== "review" && status !== "loading" && intake.searchText && (
          <>
            <p className="flex items-center gap-2 font-medium text-success"><CheckCircle2Icon className="size-4" aria-hidden="true" />已確認，會用這段文字{usedFor}：</p>
            <MaskedText text={intake.searchText} />
            <div className="flex flex-wrap gap-3">
              <Button type="button" variant="outline" size="sm" onClick={() => { setDraft(intake.searchText); setAdded([]); setSource(intake.rewriteFor); setStatus("review"); }}>修改</Button>
              <Button type="button" variant="outline" size="sm" onClick={clear}>改用原本的描述</Button>
            </div>
          </>
        )}

        {status !== "review" && status !== "loading" && !intake.searchText && (
          <div>
            <Button type="button" variant="outline" disabled={!ready} onClick={start}><SparklesIcon data-icon="inline-start" />請 AI 整理敘述</Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
