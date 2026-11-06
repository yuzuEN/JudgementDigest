import { useEffect, useState } from "react";
import { api } from "../api/client";
import { splitMasked } from "../format";
import { maskText } from "../mask";
import { useIntake } from "../state";
import { Loading } from "./Common";

type Status = "idle" | "loading" | "review" | "failed" | "limited" | "unrelated";

const NOTICE: Partial<Record<Status, string>> = {
  failed: "AI 暫時無法使用，會用你原本的描述搜尋。",
  limited: "AI 的使用次數暫時用完了，會用你原本的描述搜尋。",
  unrelated: "這段描述看起來不像法律糾紛，所以沒有傳給 AI，會用你原本的描述搜尋。",
};

/** 把描述整理成判決書的寫法，使用者確認後才用來搜尋相似判決。 */
export function RewriteCard({ ready, onReviewing }: { ready: boolean; onReviewing: (reviewing: boolean) => void }) {
  const { intake, update } = useIntake();
  const [status, setStatus] = useState<Status>("idle");
  const [draft, setDraft] = useState("");
  const [added, setAdded] = useState<string[]>([]);
  const [source, setSource] = useState("");

  useEffect(() => onReviewing(status === "review"), [status]);
  // 整理之後描述又改了：內容對不上，要重新整理
  useEffect(() => {
    if (status === "review" && source !== intake.maskedText) setStatus("idle");
  }, [intake.maskedText]);

  const start = () => {
    const text = intake.maskedText;
    setStatus("loading");
    setSource(text);
    api.rewrite(intake.mid || null, text)
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
    <section className="card" aria-labelledby="rewrite-title">
      <h2 id="rewrite-title">整理成判決書的寫法（建議）</h2>
      <p className="hint">判決用語和日常說法不同，整理後比較容易找到相似的判決。按下按鈕後，上面遮名後的內容會傳給 Google Gemini；不按就用你原本的描述搜尋。</p>
      {NOTICE[status] && <p className="warn-text" style={{ fontSize: 14 }}>{NOTICE[status]}</p>}

      {status === "loading" && <Loading>正在整理敘述……</Loading>}

      {status === "review" && (
        <>
          <label className="field">請確認整理後的內容，可以直接修改
            <textarea rows={7} value={draft} onChange={(e) => setDraft(e.target.value)} />
          </label>
          <p className="hint" style={{ fontSize: 14 }}>請檢查有沒有多出你沒說過的事，例如日期、金額、簽約或書面文件。這段只用來搜尋相似判決，不是法律文件。</p>
          {added.length > 0 && <p className="warn-text" style={{ fontSize: 14 }}>這些數字沒有出現在你的描述裡，請確認是否正確：{added.join("、")}</p>}
          <div className="actions">
            <button type="button" className="btn" disabled={!draft.trim()} onClick={confirm}>確認用這段搜尋</button>
            <button type="button" className="btn secondary" onClick={clear}>不用，改用原本的描述</button>
          </div>
        </>
      )}

      {status !== "review" && status !== "loading" && intake.searchText && (
        <>
          <p className="good-text" style={{ margin: 0 }}>已確認，相似判決會用這段文字搜尋：</p>
          <div className="masked-preview">
            {splitMasked(intake.searchText).map((part, i) =>
              part.masked ? <mark key={i} className="masked">{part.text}</mark> : <span key={i}>{part.text}</span>)}
          </div>
          <div className="actions">
            <button type="button" className="btn secondary small" onClick={() => { setDraft(intake.searchText); setAdded([]); setSource(intake.rewriteFor); setStatus("review"); }}>修改</button>
            <button type="button" className="btn secondary small" onClick={clear}>改用原本的描述</button>
          </div>
        </>
      )}

      {status !== "review" && status !== "loading" && !intake.searchText && (
        <div className="actions">
          <button type="button" className="btn secondary" disabled={!ready} onClick={start}>請 AI 整理敘述</button>
        </div>
      )}
    </section>
  );
}
