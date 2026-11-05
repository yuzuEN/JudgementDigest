import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Guide, GuideFunction } from "../api/types";
import { ErrorBox, Loading, MockBadge } from "../components/Common";
import { Layout } from "../components/Layout";
import { money, outcomeLabel } from "../format";

const FUNCTIONS: { id: GuideFunction; label: string; swatch: string }[] = [
  { id: "issue", label: "爭點", swatch: "#fff1d6" },
  { id: "claim", label: "原告主張", swatch: "#eef2f7" },
  { id: "defense", label: "被告答辯", swatch: "#f3eff8" },
  { id: "evidence", label: "證據", swatch: "#e3f0ff" },
  { id: "court", label: "法院判斷", swatch: "#e6f4ea" },
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
  const back = <button type="button" className="btn secondary small" onClick={() => navigate(-1)}>← 回到參考結果</button>;

  return (
    <Layout nav={back}>
      <main className="page two-col">
        <aside className="side">
          <section className="card" aria-labelledby="legend-title">
            <h2 id="legend-title" style={{ fontSize: 16 }}>標示段落</h2>
            <p className="hint">勾選要標色的段落類型。</p>
            {FUNCTIONS.map((f) => (
              <label key={f.id} className="check">
                <input type="checkbox" checked={on[f.id]} onChange={() => setOn({ ...on, [f.id]: !on[f.id] })} />
                <span className="swatch" style={{ background: f.swatch }} />
                <span>{f.label}</span>
                <span className="hint" style={{ marginLeft: "auto", fontSize: 13 }}>{counts[f.id] ?? 0} 段</span>
              </label>
            ))}
          </section>
          <section className="card">
            <h2 style={{ fontSize: 16 }}>關於這些標示</h2>
            <p className="hint">
              {guide?.labeler === "rule-v0"
                ? "段落用規則初步標示（第一版），之後改用段落功能標註模型。"
                : "段落功能依標註手冊，由 LLM 輔助標註、法律系學生抽查驗證。"}
              標示只說明「這段在做什麼」，不代表法院最看重哪一段。判決中的當事人姓名已換成【原告】【被告】。
            </p>
          </section>
        </aside>

        <article className="main">
          {error && <ErrorBox message={error} onRetry={load} />}
          {!guide && !error && <Loading />}
          {guide && (
            <>
              <section className="card">
                <MockBadge show={guide.mock}>示例判決（內容為示意，非真實判決）</MockBadge>
                <h1 style={{ margin: 0, fontSize: 24 }}>{guide.case.case_number}</h1>
                <dl style={{ margin: 0, display: "flex", flexWrap: "wrap", gap: "6px 24px", fontSize: 15 }}>
                  <div style={{ display: "flex", gap: 6 }}><dt className="hint">案由</dt><dd style={{ margin: 0 }}>{guide.case.mid}</dd></div>
                  <div style={{ display: "flex", gap: 6 }}><dt className="hint">結果</dt><dd style={{ margin: 0 }}>{outcomeLabel(guide.case.outcome)}</dd></div>
                  {guide.case.claimed_amount ? (
                    <div style={{ display: "flex", gap: 6 }}><dt className="hint">判准／請求</dt>
                      <dd style={{ margin: 0 }}>{money(guide.case.awarded_amount ?? 0)}／{money(guide.case.claimed_amount)}</dd></div>
                  ) : null}
                </dl>
              </section>
              <section className="card" aria-label="判決內容" style={{ gap: 12 }}>
                {guide.paragraphs.map((p, i) => (
                  <section key={i} className={`para ${p.function}${on[p.function] ? " on" : ""}`}>
                    <span className="chip">{p.label}</span>
                    <p>{p.text}</p>
                  </section>
                ))}
              </section>
              <p className="hint">字號可到<a href="https://judgment.judicial.gov.tw/FJUD/default.aspx">司法院裁判書查詢系統</a>查詢全文。</p>
              <div><Link to="/" className="btn secondary small">回首頁</Link></div>
            </>
          )}
        </article>
      </main>
    </Layout>
  );
}
