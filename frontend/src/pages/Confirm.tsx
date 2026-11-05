import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Question } from "../api/types";
import { ErrorBox, Loading } from "../components/Common";
import { Layout } from "../components/Layout";
import { money, parseAmount, sensitiveKinds, splitMasked } from "../format";
import { fullText, useIntake } from "../state";

const DEFENDANT_LABEL = { person: "個人", company: "公司、行號", government: "政府機關、學校、醫院" } as const;
const CASE_LABEL = { civil: "民事", criminal: "刑事", unsure: "不確定（民事、刑事都查）" } as const;

export default function Confirm() {
  const { intake, update } = useIntake();
  const navigate = useNavigate();
  const [questions, setQuestions] = useState<Question[]>([]);
  const [masking, setMasking] = useState(false);
  const [aiQuestions, setAiQuestions] = useState<Question[]>([]);
  const [llmAvailable, setLlmAvailable] = useState(false);
  const [aiState, setAiState] = useState<"idle" | "asking" | "done" | "failed" | "unrelated" | "declined">("idle");
  const [error, setError] = useState("");
  const [nameInput, setNameInput] = useState("");
  const text = useMemo(() => fullText(intake), [intake]);

  // 打開頁面時只用固定題庫，文字不離開伺服器。傳給 LLM 要等使用者加好姓名、同意之後自己按按鈕（askLlm）
  useEffect(() => {
    if (!intake.text.trim()) return;
    let stale = false;
    api.mask(intake.text, intake.names)
      .then((r) => api.followup(intake.caseType, intake.mid || null, r.masked_text))
      .then((r) => { if (!stale) { setQuestions(r.questions); setLlmAvailable(Boolean(r.llm_available)); } })
      .catch(() => { if (!stale) setQuestions([]); });   // 追問失敗不影響後面的流程
    return () => { stale = true; };
    // 不放 names：加名字不用重問，也不能蓋掉 AI 問過的問題
  }, [intake.caseType, intake.mid, intake.text]);

  useEffect(() => {
    if (!text) return;
    setMasking(true);
    const timer = setTimeout(() => {
      api.mask(text, intake.names)
        .then((r) => { update({ maskedText: r.masked_text }); setError(""); })
        .catch((e: Error) => setError(e.message))
        .finally(() => setMasking(false));
    }, 300);
    return () => clearTimeout(timer);
    // 不把 update 放進依賴：它會隨 intake 變動，放進去會一直重跑
  }, [text, intake.names]);

  if (!intake.text.trim()) return <Navigate to="/start" replace />;

  const kinds = sensitiveKinds(text);
  const sensitive = kinds.length > 0;
  const ready = !masking && !error && intake.maskedText !== "" && (!sensitive || intake.sensitiveConsent);
  const addName = () => {
    const n = nameInput.trim();
    if (n.length >= 2 && !intake.names.includes(n)) update({ names: [...intake.names, n] });
    setNameInput("");
  };
  const askLlm = () => {
    setAiState("asking");
    api.mask(intake.text, intake.names)
      .then((r) => api.followup(intake.caseType, intake.mid || null, r.masked_text, true))
      .then((r) => { if (r.source === "llm") setAiQuestions(r.questions); setAiState(r.source === "llm" ? "done" : r.fallback === "not_dispute" ? "unrelated" : "failed"); })
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

  return (
    <Layout step={2}>
      <main className="page two-col">
        <div className="main">
          <div>
            <h1 className="page-title">確認內容</h1>
            <p className="lead">補上幾個缺少的細節，並確認哪些資料會被送出。</p>
          </div>

          <section className="card" aria-labelledby="mask-title">
            <h2 id="mask-title">會送出的內容（已遮名）</h2>
            <p className="hint">身分證字號、電話、電子郵件、地址已自動遮掉，標成<mark className="masked">橘色</mark>。姓名請在下面加上，送出前會一起遮掉。</p>
            {error && <ErrorBox message={error} />}
            <div className="masked-preview" aria-live="polite">
              {masking && !intake.maskedText ? <Loading>遮名中……</Loading> :
                splitMasked(intake.maskedText).map((part, i) =>
                  part.masked ? <mark key={i} className="masked">{part.text}</mark> : <span key={i}>{part.text}</span>)}
            </div>
            <div className="actions" style={{ alignItems: "flex-end" }}>
              <label className="field" style={{ flex: "1 1 220px" }}>要遮掉的名字（你、對方、其他人）
                <input type="text" value={nameInput} placeholder="例如：王小明" onChange={(e) => setNameInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addName(); } }} />
              </label>
              <button type="button" className="btn secondary small" onClick={addName}>加入</button>
            </div>
            {intake.names.length > 0 && (
              <ul className="name-chips" aria-label="要遮掉的名字" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {intake.names.map((n) => (
                  <li key={n} className="name-chip">{n}
                    <button type="button" aria-label={`不遮「${n}」`}
                      onClick={() => update({ names: intake.names.filter((x) => x !== n) })}>×</button>
                  </li>
                ))}
              </ul>
            )}
            <div><Link to="/start" className="btn secondary small">回上一步修改描述</Link></div>
          </section>

          <section className="card" aria-labelledby="notice-title">
            <h2 id="notice-title">資料使用說明</h2>
            <ul className="plain" style={{ fontSize: 15 }}>
              <li>蒐集者：JudgementDigest 專題團隊；目的：產生類案判決參考結果。</li>
              <li>送出的是上面遮名後的內容；本平台不保存你的描述，結果只顯示在你的瀏覽器裡。</li>
              {llmAvailable && <li>只有在你按下「請 AI 幫我看還缺什麼」時，遮名後的內容才會傳給 Google Gemini 付費 API，不用於改善 Google 的產品。</li>}
              <li>病歷、醫療、健康檢查、基因、性生活、犯罪前科是法律特別保護的資料。你可以不提供：不同意的話，回上一步刪掉這些描述就能繼續，只是參考結果可能比較不準。</li>
            </ul>
            {sensitive && (
              <label className="consent">
                <input type="checkbox" checked={intake.sensitiveConsent} onChange={(e) => update({ sensitiveConsent: e.target.checked })} />
                <span><strong>我同意</strong>本平台處理我提供的敏感個人資料（偵測到：{kinds.join("、")}），只用於產生這次的參考結果。{llmAvailable && "如果你選擇請 AI 提問，這些內容也會傳給 Google Gemini。"}</span>
              </label>
            )}
            {sensitive && !intake.sensitiveConsent && <div><Link to="/start" className="btn secondary small">不同意，回上一步刪掉這些描述</Link></div>}
          </section>

          {choosing && (
            <section className="card" aria-labelledby="ai-title">
              <h2 id="ai-title">要補充更多細節嗎？（可略過）</h2>
              <p className="hint">按下按鈕後，上面遮名後的內容（包含你同意處理的資料）會傳給 Google Gemini，由 AI 依你的案情提問。請先確認姓名都已遮掉。不按就不會傳。</p>
              {aiState === "asking" ? <Loading>正在請 AI 看還需要補充哪些細節……</Loading> :
                <div className="actions">
                  <button type="button" className="btn secondary" disabled={!ready} onClick={askLlm}>請 AI 幫我看還缺什麼</button>
                  <button type="button" className="btn secondary" onClick={() => setAiState("declined")}>不用 AI，回答一般問題</button>
                </div>}
            </section>
          )}

          {!choosing && shown.length > 0 && (
            <section className="card" aria-labelledby="q-title">
              <h2 id="q-title">還想問你幾件事</h2>
              {aiState === "failed" && <p className="warn-text" style={{ fontSize: 14 }}>AI 暫時無法使用，先回答下面的一般問題就好。</p>}
              {aiState === "unrelated" && <p className="warn-text" style={{ fontSize: 14 }}>這段描述看起來不像法律糾紛，所以沒有傳給 AI。可以回上一步補充，或先回答下面的一般問題。</p>}
              <p className="hint">{questionHint}</p>
              {shown.map((q) => (
                <div key={q.id} className="qa">
                  <div className="bubble q">
                    <label htmlFor={`q-${q.id}`}>{q.text}</label>
                    <div className="hint" style={{ fontSize: 13 }}>{q.why}</div>
                  </div>
                  <input id={`q-${q.id}`} type="text" placeholder="你的回答（可留空）"
                    value={intake.followupAnswers[q.id]?.answer ?? ""} onChange={(e) => answer(q, e.target.value)} />
                </div>
              ))}
              {llmAvailable && aiState === "done" &&
                <button type="button" className="btn secondary small" onClick={() => setAiState("declined")}>改回答一般問題</button>}
              {llmAvailable && aiState === "declined" &&
                <button type="button" className="btn secondary small" onClick={useAi}>改請 AI 提問</button>}
              {llmAvailable && aiState === "failed" &&
                <button type="button" className="btn secondary small" onClick={useAi}>再試一次 AI</button>}
              {llmAvailable && (aiState === "done" || aiState === "declined") &&
                <p className="hint" style={{ fontSize: 13 }}>切換問題時，已經回答的內容會保留，可以在上面的預覽看到。</p>}
            </section>
          )}

          <div className="actions">
            <button type="button" className="btn" disabled={!ready} onClick={() => navigate(resultPath)}>看參考結果</button>
            {sensitive && !intake.sensitiveConsent && <span className="warn-text">內容包含敏感個人資料，請先在上面選擇同意或不同意。</span>}
          </div>
        </div>

        <aside className="side">
          <div className="card">
            <h2 style={{ fontSize: 16 }}>你提供的資料</h2>
            <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", fontSize: 15 }}>
              <dt className="hint">類型</dt><dd style={{ margin: 0 }}>{CASE_LABEL[intake.caseType]}</dd>
              {intake.caseType !== "criminal" && <>
                <dt className="hint">糾紛</dt><dd style={{ margin: 0 }}>{intake.mid || "不確定"}</dd>
                <dt className="hint">請求金額</dt><dd style={{ margin: 0 }}>{money(parseAmount(intake.claimedAmount))}</dd>
                <dt className="hint">對方</dt><dd style={{ margin: 0 }}>{intake.defendantType ? DEFENDANT_LABEL[intake.defendantType] : "不確定"}</dd>
                <dt className="hint">律師</dt><dd style={{ margin: 0 }}>{intake.lawyer === "yes" ? "有" : intake.lawyer === "no" ? "還沒有" : "未填"}</dd>
                <dt className="hint">證據</dt><dd style={{ margin: 0 }}>{intake.evidence.length ? `${intake.evidence.length} 項` : "未勾選"}</dd>
              </>}
            </dl>
          </div>
          <div className="card info">
            <h2 style={{ fontSize: 16 }}>同一件事可能有民事也有刑事</h2>
            <p style={{ margin: 0, fontSize: 15 }}>例如車禍受傷：刑事上可能是過失傷害，民事上可以請求損害賠償。兩種結果會分開顯示。</p>
          </div>
        </aside>
      </main>
    </Layout>
  );
}
