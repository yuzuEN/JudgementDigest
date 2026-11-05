import { useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api } from "../api/client";
import type { AmountRange, CivilReport, SimilarCase } from "../api/types";
import { ErrorBox, LAF_URL, Loading, ResultNotes } from "../components/Common";
import { ResultFrame } from "../components/ResultFrame";
import { money, outcomeLabel, outcomeTone, percent } from "../format";
import { civilInput, useIntake } from "../state";

export default function CivilResult() {
  const { intake } = useIntake();
  const [report, setReport] = useState<CivilReport | null>(null);
  const [error, setError] = useState("");
  const [onlyWin, setOnlyWin] = useState(false);

  const load = useCallback(() => {
    setError("");
    setReport(null);
    api.civilReport(civilInput(intake)).then(setReport).catch((e: Error) => setError(e.message));
    // 只在進入頁面時算一次；intake 在結果頁不會再改，所以不放進依賴
  }, []);
  useEffect(load, [load]);

  if (!intake.maskedText) return <Navigate to={intake.text ? "/confirm" : "/start"} replace />;

  const title = `民事參考結果${intake.mid ? `：${intake.mid}` : ""}`;
  const lead = report
    ? `以下是「類似案件如果打到判決」的統計，比對了 ${report.n_compared} 件${intake.mid ? "案由相同" : ""}的真實判決。`
    : "正在比對相似的真實判決……";

  return (
    <ResultFrame active="civil" title={title} lead={lead} mock={report?.mock ?? false} maskedText={intake.maskedText}>
      {error && <ErrorBox message={error} onRetry={load} />}
      {!report && !error && <Loading>正在計算，約需幾秒鐘……</Loading>}
      {report && (
        <>
          <div className="grid-2">
            <Probability report={report} />
            <Amount range={report.amount_range} />
          </div>
          <SimilarCases cases={report.similar} onlyWin={onlyWin} setOnlyWin={setOnlyWin} />
          <div className="grid-2">
            <section className="card" aria-labelledby="ev-title">
              <h2 id="ev-title">證據對照</h2>
              <p className="hint">相似的勝訴判決裡「提到」這項證據的比例。提到不代表法院一定採信。</p>
              {report.evidence.length === 0 && <p className="hint">相似的勝訴判決不夠多，無法整理。</p>}
              {report.evidence.map((e) => (
                <div key={e.key} className="ev-row">
                  <div className="top">
                    <span>{e.label}</span>
                    <span className={e.user_has ? "good-text" : "warn-text"}>{e.user_has ? "✓ 你有" : "✗ 你沒有"}</span>
                  </div>
                  <div className="line">
                    <div className="bar thin soft" role="img" aria-label={`${percent(e.share)} 的相似勝訴判決提到`}>
                      <span style={{ width: percent(e.share) }} />
                    </div>
                    <span className="pct">{percent(e.share)}</span>
                  </div>
                </div>
              ))}
            </section>
            <section className="card" aria-labelledby="def-title">
              <h2 id="def-title">對方可能會怎麼說</h2>
              <p className="hint">相似案件中，被告最常提出的抗辯。</p>
              {report.defenses.length === 0 && <p className="hint">相似案件中沒有整理出常見的抗辯。</p>}
              <ol style={{ margin: 0, paddingLeft: 22, display: "flex", flexDirection: "column", gap: 10 }}>
                {report.defenses.map((d) => (
                  <li key={d.key}><strong>{d.label}</strong><br />
                    <span className="hint">{d.description}。出現在 {percent(d.share)} 的相似案件。</span></li>
                ))}
              </ol>
            </section>
          </div>
          <ResultNotes items={[
            "這是「類似案件如果打到判決」的統計，不代表你的案件一定會這樣判，也不是法律意見。",
            "約四分之一的民事案件以和解、撤回結束，沒有判決書，不在比較範圍內。",
            <>需要進一步協助，可以聯絡<a href={LAF_URL}>法律扶助基金會</a>或律師。</>,
          ]} />
        </>
      )}
    </ResultFrame>
  );
}

function Probability({ report }: { report: CivilReport }) {
  const p = report.prediction.win_probability;
  const n = Math.round(p * 100);
  return (
    <section className="card" aria-labelledby="p-title">
      <h2 id="p-title">原告勝訴的機率</h2>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span className="big-number">{percent(p)}</span><span className="hint">勝訴或一部勝訴</span>
      </div>
      <div className="bar" role="img" aria-label={`勝訴機率 ${percent(p)}`}><span style={{ width: percent(p) }} /></div>
      <p className="hint" style={{ fontSize: 15 }}>在 100 件和你類似、打到判決的案件中，大約 {n} 件原告至少拿到一部分。</p>
      {report.prediction.warnings.map((w) => <p key={w} className="warn-text" style={{ margin: 0, fontSize: 14 }}>{w}</p>)}
      <p className="hint" style={{ fontSize: 13 }}>
        模型：{report.prediction.model.description}
        {report.prediction.model.auc ? `（測試資料 AUC ${report.prediction.model.auc.toFixed(3)}）` : ""}。你的描述越完整，結果越可靠。
      </p>
    </section>
  );
}

function Amount({ range }: { range: AmountRange | null }) {
  if (!range) {
    return (
      <section className="card" aria-labelledby="a-title">
        <h2 id="a-title">如果勝訴，可能判准的金額</h2>
        <p className="hint">相似的勝訴判決不夠多，這次無法估出金額範圍。</p>
      </section>
    );
  }
  const pct = `相似案件中，10 件有 ${Math.round(range.coverage * 10)} 件落在這個範圍`;
  if (!range.claimed) {
    return (
      <section className="card" aria-labelledby="a-title">
        <h2 id="a-title">如果勝訴，可能拿到請求金額的</h2>
        <span className="mid-number">{percent(range.ratio_low)}～{percent(range.ratio_high)}</span>
        <p className="hint" style={{ fontSize: 15 }}>{pct}。回上一步填寫想請求的金額，就會換算成金額。</p>
      </section>
    );
  }
  return (
    <section className="card" aria-labelledby="a-title">
      <h2 id="a-title">如果勝訴，可能判准的金額</h2>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <span className="mid-number">{money(range.amount_low)}～{money(range.amount_high)}</span>
        <span className="hint">你請求 {money(range.claimed)}</span>
      </div>
      <div className="range" role="img" aria-label={`80% 範圍 ${money(range.amount_low)} 到 ${money(range.amount_high)}，請求 ${money(range.claimed)}`}>
        <div className="track" />
        <div className="fill" style={{ left: percent(range.ratio_low), width: percent(range.ratio_high - range.ratio_low) }} />
        <span className="tick" style={{ left: 0 }}>0</span>
        <span className="tick" style={{ right: 0 }}>請求 {money(range.claimed)}</span>
      </div>
      <p className="hint" style={{ fontSize: 15 }}>{pct}（依 {range.n_cases} 件相似的勝訴判決）。金額只能給範圍，不能給單一數字。</p>
    </section>
  );
}

function SimilarCases({ cases, onlyWin, setOnlyWin }: { cases: SimilarCase[]; onlyWin: boolean; setOnlyWin: (v: boolean) => void }) {
  const shown = onlyWin ? cases.filter((c) => outcomeTone(c.outcome) !== "lose") : cases;
  return (
    <section className="card" aria-labelledby="sim-title">
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <h2 id="sim-title">相似的真實判決</h2>
        <label className="check no-print"><input type="checkbox" checked={onlyWin} onChange={(e) => setOnlyWin(e.target.checked)} /> 只看原告勝訴的</label>
      </div>
      <div className="table-wrap">
        <table className="cases">
          <thead><tr><th scope="col">字號</th><th scope="col">結果</th><th scope="col">判准／請求</th><th scope="col">相似度</th><th scope="col"><span className="sr-only">動作</span></th></tr></thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.case_id}>
                <td>{c.case_number}<br /><span className="hint">{c.summary}</span></td>
                <td><span className={`tag ${outcomeTone(c.outcome)}`}>{outcomeLabel(c.outcome)}</span></td>
                <td>{c.claimed_amount ? `${money(c.awarded_amount ?? 0)}／${money(c.claimed_amount)}` : "—"}</td>
                <td>{c.similarity.toFixed(2)}</td>
                <td className="no-print"><Link to={`/judgment/civil/${c.case_id}`} style={{ whiteSpace: "nowrap" }}>判決導讀</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length === 0 && <p className="hint">沒有符合的判決。</p>}
    </section>
  );
}
