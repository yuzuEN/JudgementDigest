import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Question } from "../api/types";
import { ErrorBox, Loading } from "../components/Common";
import { Layout } from "../components/Layout";
import { money, needsHealthConsent, parseAmount, splitMasked } from "../format";
import { fullText, useIntake } from "../state";

const DEFENDANT_LABEL = { person: "個人", company: "公司、行號", government: "政府機關、學校、醫院" } as const;
const CASE_LABEL = { civil: "民事", criminal: "刑事", unsure: "不確定（民事、刑事都查）" } as const;

export default function Confirm() {
  const { intake, update } = useIntake();
  const navigate = useNavigate();
  const [questions, setQuestions] = useState<Question[]>([]);
  const [masking, setMasking] = useState(false);
  const [error, setError] = useState("");
  const [nameInput, setNameInput] = useState("");
  const text = useMemo(() => fullText(intake), [intake]);

  useEffect(() => {
    if (!intake.text.trim()) return;
    let stale = false;
    // 追問可能傳給外部的 LLM，一定要先遮名
    api.mask(intake.text, intake.names)
      .then((r) => api.followup(intake.caseType, intake.mid || null, r.masked_text))
      .then((r) => { if (!stale) setQuestions(r.questions); })
      .catch(() => { if (!stale) setQuestions([]); });   // 追問失敗不影響後面的流程
    return () => { stale = true; };
  }, [intake.caseType, intake.mid, intake.text, intake.names]);

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

  const health = needsHealthConsent(text);
  const ready = !masking && !error && intake.maskedText !== "" && (!health || intake.healthConsent);
  const addName = () => {
    const n = nameInput.trim();
    if (n.length >= 2 && !intake.names.includes(n)) update({ names: [...intake.names, n] });
    setNameInput("");
  };
  const answer = (q: Question, value: string) =>
    update({ followupAnswers: { ...intake.followupAnswers, [q.id]: { question: q.text, answer: value } } });
  const resultPath = intake.caseType === "criminal" ? "/result/criminal" : "/result/civil";

  return (
    <Layout step={2}>
      <main className="page two-col">
        <div className="main">
          <div>
            <h1 className="page-title">確認內容</h1>
            <p className="lead">補上幾個缺少的細節，並確認哪些資料會被送出。</p>
          </div>

          {questions.length > 0 && (
            <section className="card" aria-labelledby="q-title">
              <h2 id="q-title">還想問你幾件事</h2>
              <p className="hint">可以跳過；回答會加在你的描述後面，一起遮名後送出。</p>
              {questions.map((q) => (
                <div key={q.id} className="qa">
                  <div className="bubble q">
                    <label htmlFor={`q-${q.id}`}>{q.text}</label>
                    <div className="hint" style={{ fontSize: 13 }}>{q.why}</div>
                  </div>
                  <input id={`q-${q.id}`} type="text" placeholder="你的回答（可留空）"
                    value={intake.followupAnswers[q.id]?.answer ?? ""} onChange={(e) => answer(q, e.target.value)} />
                </div>
              ))}
            </section>
          )}

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
              <li>追問功能之後改用 LLM 時，遮名後的內容會傳給付費 LLM API 處理（依其政策保留、不用於訓練），屆時會另外說明。</li>
              <li>你可以不提供健康相關資料，只是參考結果可能比較不準。</li>
            </ul>
            {health && (
              <label className="consent">
                <input type="checkbox" checked={intake.healthConsent} onChange={(e) => update({ healthConsent: e.target.checked })} />
                <span><strong>我同意</strong>本平台處理我提供的健康、醫療相關資料（例如受傷、住院的描述），只用於產生這次的參考結果。</span>
              </label>
            )}
          </section>

          <div className="actions">
            <button type="button" className="btn" disabled={!ready} onClick={() => navigate(resultPath)}>看參考結果</button>
            {health && !intake.healthConsent && <span className="warn-text">內容包含健康資料，請先勾選同意，或回上一步刪掉相關描述。</span>}
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
