import { useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api } from "../api/client";
import type { CriminalReport } from "../api/types";
import { ErrorBox, InfoLink, LAF_URL, Loading, ResultNotes } from "../components/Common";
import { ResultFrame } from "../components/ResultFrame";
import { percent } from "../format";
import { useIntake } from "../state";

export default function CriminalResult() {
  const { intake } = useIntake();
  const [report, setReport] = useState<CriminalReport | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(0);

  const load = useCallback(() => {
    setError("");
    setReport(null);
    api.criminalReport(intake.maskedText).then(setReport).catch((e: Error) => setError(e.message));
    // 只在進入頁面時算一次
  }, []);
  useEffect(load, [load]);

  if (!intake.maskedText) return <Navigate to={intake.text ? "/confirm" : "/start"} replace />;

  return (
    <ResultFrame active="criminal" title="刑事參考結果" mock={report?.mock ?? false} maskedText={intake.maskedText}
      lead="依你描述的事實，推估可能涉及的罪名、法條與刑期範圍。">
      {report?.mock && <p className="hint no-print">刑事模型由刑事組開發中，目前顯示的是示例資料。</p>}
      {error && <ErrorBox message={error} onRetry={load} />}
      {!report && !error && <Loading />}
      {report && report.charges.length > 0 && (
        <>
          <div className="grid-2">
            <section className="card" aria-labelledby="charge-title">
              <h2 id="charge-title">可能的罪名</h2>
              <p className="hint no-print">點選罪名，查看相似案件的刑期分布。</p>
              <div role="group" aria-labelledby="charge-title" className="stack" style={{ gap: 10 }}>
                {report.charges.map((c, i) => (
                  <button key={c.name} type="button" className="charge" aria-pressed={i === selected} onClick={() => setSelected(i)}>
                    <span className="row"><strong>{c.name}</strong><span>{percent(c.probability)}</span></span>
                    <span className="hint">{c.law}</span>
                    <span className="bar thin" style={{ width: "100%" }}><span style={{ width: percent(c.probability) }} /></span>
                  </button>
                ))}
              </div>
            </section>
            {/* 畫面上只顯示選到的罪名；列印時每個罪名都要印出來 */}
            {report.charges.map((c, i) => (
              <section key={c.name} className={`card${i === selected ? "" : " screen-hidden"}`} aria-labelledby={`sentence-title-${i}`}>
                <h2 id={`sentence-title-${i}`}>刑期範圍：{c.name}</h2>
                <p className="hint">{report.mock ? "相似的有罪判決中，宣告刑落在各區間的比例。"
                  : "模型依類似的有罪判決推估，宣告刑落在各區間的機率（整個案件的刑度，各罪名相同）。"}</p>
                {c.sentence.map((b) => (
                  <div key={b.label} className="bucket">
                    <span>{b.label}</span>
                    <div className="bar warm" role="img" aria-label={`${b.label} ${percent(b.share)}`}><span style={{ width: percent(b.share) }} /></div>
                    <span className="pct">{percent(b.share)}</span>
                  </div>
                ))}
                <p className="hint">實際刑期還會受到是否和解、有無前科、犯後態度等影響。</p>
              </section>
            ))}
          </div>
          <section className="card" aria-labelledby="crim-sim-title">
            <h2 id="crim-sim-title">相似的真實判決</h2>
            {report.similar.length === 0 ? <p className="hint">刑事的相似判決檢索開發中。</p> : (
            <div className="table-wrap">
              <table className="cases">
                <thead><tr><th scope="col">字號</th><th scope="col">罪名</th><th scope="col">宣告刑</th><th scope="col">相似度 <InfoLink to="相似度" label="相似度說明" /></th><th scope="col" className="no-print"><span className="sr-only">動作</span></th></tr></thead>
                <tbody>
                  {report.similar.map((c) => (
                    <tr key={c.case_id}>
                      <td>{c.case_number}<br /><span className="hint">{c.summary}</span></td>
                      <td data-label="罪名">{c.mid}</td>
                      <td data-label="宣告刑">{c.sentence ?? "—"}</td>
                      <td data-label="相似度">{c.similarity.toFixed(2)}</td>
                      <td className="no-print">{c.url
                        ? <a href={c.url} target="_blank" rel="noreferrer">判決原文</a>
                        : <Link to={`/judgment/criminal/${c.case_id}`}>判決導讀</Link>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            )}
          </section>
          <ResultNotes items={[
            "結果只代表「有判決書的案件」的統計；不起訴、撤回告訴的案件不在資料裡。",
            "告訴乃論之罪（例如過失傷害）和解並撤回告訴後，通常不會有判決。",
            <>不是法律意見；被提告或想提告，請諮詢律師或<a href={LAF_URL}>法律扶助基金會</a>。</>,
          ]} />
        </>
      )}
    </ResultFrame>
  );
}
