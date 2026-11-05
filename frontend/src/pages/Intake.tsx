import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { CaseType, DefendantType, Options } from "../api/types";
import { ErrorBox, LAF_URL } from "../components/Common";
import { Layout } from "../components/Layout";
import { parseAmount } from "../format";
import { useIntake } from "../state";

export const SHORT_TEXT = 150;
const RECOMMENDED = 300;

const CASE_TYPES: { id: CaseType; label: string; hint: string }[] = [
  { id: "civil", label: "民事", hint: "要求賠償、還錢、履行契約" },
  { id: "criminal", label: "刑事", hint: "被警察、檢察官調查，或想告對方犯罪" },
  { id: "unsure", label: "不確定", hint: "由系統幫你判斷，兩種都查" },
];

const DEFENDANT_TYPES: { id: DefendantType; label: string }[] = [
  { id: "person", label: "個人" },
  { id: "company", label: "公司、行號" },
  { id: "government", label: "政府機關、學校、醫院" },
];

export default function Intake() {
  const { intake, update } = useIntake();
  const navigate = useNavigate();
  const [options, setOptions] = useState<Options | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    setError("");
    api.options().then(setOptions).catch((e: Error) => setError(e.message));
  };
  useEffect(load, []);

  const len = intake.text.trim().length;
  const lenHint = len === 0 ? `建議 ${RECOMMENDED} 字以上` : len < SHORT_TEXT ? "再多寫一些，結果會比較準" : "長度足夠";
  const lenClass = len === 0 ? "hint" : len < SHORT_TEXT ? "warn-text" : "good-text";
  const showCivil = intake.caseType !== "criminal";
  const amountInvalid = intake.claimedAmount.trim() !== "" && parseAmount(intake.claimedAmount) === null;

  const toggleEvidence = (key: string) =>
    update({ evidence: intake.evidence.includes(key) ? intake.evidence.filter((k) => k !== key) : [...intake.evidence, key] });

  return (
    <Layout step={1}>
      <main className="page two-col">
        <form className="main" onSubmit={(e) => { e.preventDefault(); navigate("/confirm"); }}>
          <div>
            <h1 className="page-title">描述你遇到的糾紛</h1>
            <p className="lead">我們會從全國地方法院的真實判決中，找出和你的情況相似的案件，告訴你這類案件打到判決時通常怎麼判。</p>
          </div>

          <section className="card" aria-labelledby="type-title">
            <h2 id="type-title">這是哪一類的事情？</h2>
            <div className="choice-row" role="group" aria-labelledby="type-title">
              {CASE_TYPES.map((t) => (
                <button key={t.id} type="button" className="choice" aria-pressed={intake.caseType === t.id}
                  onClick={() => update({ caseType: t.id })}>
                  {t.label}<small>{t.hint}</small>
                </button>
              ))}
            </div>
          </section>

          <section className="card">
            <label htmlFor="facts" style={{ fontSize: 18, fontWeight: 700 }}>發生了什麼事？</label>
            <p className="hint" id="facts-help">
              依時間順序寫下經過、你受到的損害、你想要求什麼。不用寫法律用語，但請盡量完整：描述太短時，參考結果會比較不準。
            </p>
            <textarea id="facts" rows={9} aria-describedby="facts-help facts-count" value={intake.text}
              onChange={(e) => update({ text: e.target.value })}
              placeholder="例如：去年三月我騎機車在路口被一輛右轉的汽車撞到，右手骨折住院五天，之後復健三個月沒辦法工作……" />
            <div id="facts-count" style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 8, fontSize: 14 }}>
              <span className="hint">已輸入 {len} 字</span>
              <span className={lenClass}>{lenHint}</span>
            </div>
            <p className="hint">有起訴書或起訴狀？可以直接把「犯罪事實」或「事實及理由」那一段貼上來。</p>
          </section>

          {showCivil && (
            <section className="card" aria-labelledby="civil-title">
              <div>
                <h2 id="civil-title">幾個基本問題</h2>
                <p className="hint">這些資料會和你的描述一起用來推估結果。不確定的可以跳過。</p>
              </div>
              {error && <ErrorBox message={`選項載入失敗：${error}`} onRetry={load} />}
              <div className="form-grid">
                <div className="field">
                  <span className="label-row"><label htmlFor="mid">糾紛類型</label>
                    <a className="info" href={`/guide#${intake.mid ? encodeURIComponent(intake.mid) : "dispute-types"}`} target="_blank"
                      rel="noreferrer" aria-label="糾紛類型說明（開新分頁）" title="糾紛類型說明">i</a>
                  </span>
                  <select id="mid" value={intake.mid} onChange={(e) => update({ mid: e.target.value })}>
                    <option value="">不確定</option>
                    {options?.mid_groups.map((g) => (
                      <optgroup key={g.category} label={g.category}>
                        {g.mids.map((m) => <option key={m.value} value={m.value}>{m.value}</option>)}
                      </optgroup>
                    ))}
                  </select>
                </div>
                <label className="field">想請求的金額（新臺幣）
                  <input type="text" inputMode="numeric" placeholder="例如 500000 或 50萬" value={intake.claimedAmount}
                    aria-invalid={amountInvalid} onChange={(e) => update({ claimedAmount: e.target.value })} />
                  {amountInvalid && <span className="warn-text" style={{ fontSize: 14 }}>看不懂這個金額，請只填數字，例如 500000 或 50萬</span>}
                </label>
                <label className="field">對方是
                  <select value={intake.defendantType} onChange={(e) => update({ defendantType: e.target.value as DefendantType | "" })}>
                    <option value="">不確定</option>
                    {DEFENDANT_TYPES.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
                  </select>
                </label>
                <label className="field">打算在哪個法院（可不選）
                  <select value={intake.court} onChange={(e) => update({ court: e.target.value })}>
                    <option value="">還不知道</option>
                    {options?.courts.map((c) => <option key={c} value={c}>{c}地方法院</option>)}
                  </select>
                </label>
              </div>
              <fieldset>
                <legend>你有請律師嗎？</legend>
                <div className="choice-row">
                  {([["yes", "有"], ["no", "還沒有"]] as const).map(([v, label]) => (
                    <label key={v} className="check">
                      <input type="radio" name="lawyer" checked={intake.lawyer === v} onChange={() => update({ lawyer: v })} /> {label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend>你手上有哪些證據？</legend>
                <p className="hint">只要勾「有沒有」，不用上傳任何文件。</p>
                <div className="check-grid">
                  {options?.evidence.map((e) => (
                    <label key={e.key} className="check">
                      <input type="checkbox" checked={intake.evidence.includes(e.key)} onChange={() => toggleEvidence(e.key)} /> {e.label}
                    </label>
                  ))}
                </div>
              </fieldset>
            </section>
          )}

          {intake.caseType !== "civil" && (
            <section className="card">
              <h2>刑事案件</h2>
              <p className="hint">請盡量寫出行為的經過（時間、地點、做了什麼、造成什麼結果）。系統會以這段事實推估可能的罪名、法條與刑期範圍。</p>
            </section>
          )}

          <div className="actions">
            <button type="submit" className="btn" disabled={len === 0 || amountInvalid}>下一步：確認內容</button>
            <span className="hint">送出前會先讓你預覽，並遮掉姓名、身分證字號、電話。</span>
          </div>
        </form>

        <aside className="side">
          <div className="card">
            <h2 style={{ fontSize: 16 }}>你會得到</h2>
            <ul className="plain" style={{ fontSize: 15 }}>
              <li>相似的真實判決（附字號，可自行查證）</li>
              <li>民事：勝訴機率、可能判准的金額範圍</li>
              <li>刑事：可能的罪名、法條、刑期範圍</li>
              <li>相似案件常提到的證據、對方常見的說法</li>
              <li>判決導讀：標出爭點、證據、法院判斷</li>
            </ul>
          </div>
          <div className="card warn">
            <h2 style={{ fontSize: 16 }}>這不是法律意見</h2>
            <p style={{ margin: 0, fontSize: 15 }}>結果是「類似案件如果打到判決，通常怎麼判」的統計參考，不代表你的案件一定會這樣判。和解、撤回的案件沒有判決書，不在資料裡。重要決定請諮詢律師或<a href={LAF_URL}>法律扶助基金會</a>。</p>
          </div>
          <div className="card"><p className="hint">不上傳文件、不保存你的描述。送出前會遮名並讓你預覽；需要用到健康資料時，會另外請你同意。</p></div>
        </aside>
      </main>
    </Layout>
  );
}
