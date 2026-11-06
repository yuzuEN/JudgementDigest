import { useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api } from "../api/client";
import type { AmountRange, CivilReport, SimilarCase } from "../api/types";
import { ErrorBox, InfoLink, LAF_URL, Loading, ResultNotes, SIMILARITY_NOTE } from "../components/Common";
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
    <ResultFrame active="civil" title={title} lead={lead} mock={report?.mock ?? false} maskedText={intake.maskedText} searchText={intake.searchText}>
      {error && <ErrorBox message={error} onRetry={load} />}
      {!report && !error && <Loading>正在計算，約需幾秒鐘……</Loading>}
      {report && (
        <>
          <div className="grid-2">
            <Outcomes report={report} />
            <Amount range={report.amount_range} />
          </div>
          <SimilarCases cases={report.similar} onlyWin={onlyWin} setOnlyWin={setOnlyWin} rewritten={Boolean(intake.searchText)} />
          <div className="grid-2">
            <section className="card" aria-labelledby="ev-title">
              <h2 id="ev-title">證據對照</h2>
              <p className="hint">相似的勝訴判決裡「提到」這項證據的比例。提到不代表法院一定採信。</p>
              {report.evidence.length === 0 && <p className="hint">相似的勝訴判決不夠多，無法整理。</p>}
              {report.evidence.map((e) => (
                <div key={e.key} className="ev-row">
                  <div className="top">
                    <span>{e.label}</span>
                    <span className={e.user_has ? "good-text" : "hint"}>{e.user_has ? "✓ 你有提到" : "沒有提到"}</span>
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

const MIN_OUTCOME_CASES = 10;   // 比這少時比例沒有代表性，不畫圖

const SIGNAL_TEXT: Record<CivilReport["prediction"]["signal"], string> = {
  strong: "這段描述的勝訴訊號較強，但不代表一定會勝訴。",
  weak: "這段描述的勝訴訊號較弱。可能是案件較不利，也可能是資訊還不夠；補充證據和經過後再看一次。",
  insufficient: "資訊不足，還看不出訊號強弱。請補充發生的經過、損害和手上的證據。",
};

function Outcomes({ report }: { report: CivilReport }) {
  const { total, win, partial, lose } = report.outcomes;
  const { signal } = report.prediction;
  const parts = [
    { key: "win", label: "全部勝訴", count: win },
    { key: "partial", label: "部分勝訴", count: partial },
    { key: "lose", label: "敗訴", count: lose },
  ];
  const enough = total >= MIN_OUTCOME_CASES;
  const share = total ? (win + partial) / total : 0;
  const mixed = enough && ((signal === "strong" && share < 0.4) || (signal === "weak" && share >= 0.7));
  return (
    <section className="card" aria-labelledby="p-title">
      <h2 id="p-title">相似判決的結果</h2>
      {enough ? (
        <>
          <p style={{ margin: 0 }}>{total} 件相似判決中</p>
          <div className="outcome-bar" role="img" aria-label={parts.map((x) => `${x.label} ${x.count} 件`).join("、")}>
            {parts.filter((x) => x.count > 0).map((x) => (
              <span key={x.key} className={x.key} title={`${x.label} ${x.count} 件`} style={{ flexGrow: x.count }} />
            ))}
          </div>
          <ul className="outcome-legend">
            {parts.map((x) => <li key={x.key}><span className={`swatch ${x.key}`} />{x.label} <strong>{x.count}</strong> 件</li>)}
          </ul>
          <p className="hint" style={{ fontSize: 14 }}>只統計雙方都有攻防的判決。這是過去判決的統計，不代表你的案件會有相同結果。</p>
          {report.default_cases > 0 && (
            <p className="hint" style={{ fontSize: 14 }}>
              另外，最相似的 30 件判決裡有 {report.default_cases} 件被告未到庭。這類案件原告幾乎都贏，但沒有經過雙方攻防，所以不算進上面的比例。
            </p>
          )}
        </>
      ) : <p className="hint">有被告答辯的相似判決不夠多，這次不顯示比例。</p>}
      <p style={{ margin: 0 }}><strong>模型參考：</strong>{SIGNAL_TEXT[signal]}</p>
      {mixed && <p className="hint" style={{ fontSize: 14 }}>相似判決和模型參考不完全一致，請先看判決內容。</p>}
      {report.prediction.warnings.map((w) => <p key={w} className="warn-text" style={{ margin: 0, fontSize: 14 }}>{w}</p>)}
      <ModelDetail report={report} />
    </section>
  );
}

function ModelDetail({ report }: { report: CivilReport }) {
  const { win_probability: p, model } = report.prediction;
  return (
    <details className="amount-detail">
      <summary>模型細節</summary>
      <p style={{ margin: "8px 0 0" }}>勝訴機率 <strong>{percent(p)}</strong>（勝訴或一部勝訴）<InfoLink to="勝訴機率" label="勝訴機率說明" /></p>
      <p className="hint" style={{ fontSize: 14 }}>模型是用判決書的文字訓練的。初步測試中，一般口語描述算出來的機率常常偏低，也比較分不出輸贏，請當成粗略的參考。</p>
      <p className="hint" style={{ fontSize: 13 }}>模型：{model.description}。你的描述越完整，結果越可靠。</p>
      <ModelScore model={model} />
    </details>
  );
}

function ModelScore({ model }: { model: CivilReport["prediction"]["model"] }) {
  const { win_precision: wp, win_recall: wr, lose_precision: lp, lose_recall: lr } = model;
  if (wp == null || wr == null || lp == null || lr == null) return null;
  return (
    <p className="hint" style={{ fontSize: 13 }}>
      用判決文字測試時，模型判勝訴的案件有 {percent(wp)} 真的勝訴，實際勝訴的案件有 {percent(wr)} 被判出來；
      判敗訴的案件有 {percent(lp)} 真的敗訴，實際敗訴的案件有 {percent(lr)} 被判出來。
      <InfoLink to="Precision、Recall" label="Precision、Recall 說明" />
    </p>
  );
}

function AmountDetail({ range }: { range: AmountRange }) {
  const buckets = range.buckets ?? [];
  if (buckets.length === 0) return null;
  const most = Math.max(...buckets.map((b) => b.count), 1);
  const label = (low: number, high: number) => (range.claimed
    ? `${money(range.claimed * low)}～${money(range.claimed * high)}`
    : `${percent(low)}～${percent(high)}`);
  return (
    <details className="amount-detail">
      <summary>看各金額範圍有幾件</summary>
      <ul>
        {buckets.map((b) => (
          <li key={b.low}>
            <span>{label(b.low, b.high)}</span>
            <span className="bar soft" aria-hidden="true"><span style={{ width: `${(b.count / most) * 100}%` }} /></span>
            <span className="count">{b.count} 件</span>
          </li>
        ))}
      </ul>
      <p className="hint" style={{ fontSize: 13 }}>相似的勝訴判決判准了請求金額的幾成，換算成你的金額。不是每件都和你的案情一樣。</p>
    </details>
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
        <AmountDetail range={range} />
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
      <AmountDetail range={range} />
    </section>
  );
}

function SimilarCases({ cases, onlyWin, setOnlyWin, rewritten }: { cases: SimilarCase[]; onlyWin: boolean; setOnlyWin: (v: boolean) => void; rewritten: boolean }) {
  const visible = (c: SimilarCase) => !onlyWin || outcomeTone(c.outcome) !== "lose";
  const shown = cases.filter(visible);
  return (
    <section className="card" aria-labelledby="sim-title">
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <h2 id="sim-title">相似的真實判決</h2>
        <label className="check no-print"><input type="checkbox" checked={onlyWin} onChange={(e) => setOnlyWin(e.target.checked)} /> 只看原告勝訴的</label>
      </div>
      <p className="hint" style={{ fontSize: 14 }}>{rewritten ? "用你確認過的整理文字搜尋。" : "用你原本的描述搜尋。"}</p>
      <div className="table-wrap">
        <table className="cases">
          <thead><tr><th scope="col">字號</th><th scope="col">結果</th><th scope="col">判准／請求</th><th scope="col">相似度 <InfoLink to="相似度" label="相似度說明" /></th><th scope="col" className="no-print"><span className="sr-only">動作</span></th></tr></thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.case_id} className={visible(c) ? undefined : "screen-hidden"}>
                <td>{c.case_number}<br /><span className="hint">{c.summary}</span></td>
                <td data-label="結果"><span className={`tag ${outcomeTone(c.outcome)}`}>{outcomeLabel(c.outcome)}</span>{c.default_judgment && <><br /><span className="tag neutral">被告未到庭</span></>}</td>
                <td data-label="判准／請求">{c.claimed_amount ? `${money(c.awarded_amount ?? 0)}／${money(c.claimed_amount)}` : "—"}</td>
                <td data-label="相似度">{c.similarity.toFixed(2)}</td>
                <td className="no-print"><Link to={`/judgment/civil/${c.case_id}`} style={{ whiteSpace: "nowrap" }}>判決導讀</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length === 0 && <p className="hint no-print">沒有符合的判決。</p>}
      <p className={`hint${shown.length ? "" : " screen-hidden"}`}>{SIMILARITY_NOTE}</p>
      {cases.some((c) => c.default_judgment) && <p className={`hint${shown.some((c) => c.default_judgment) ? "" : " screen-hidden"}`}>「被告未到庭」的判決沒有經過雙方攻防，原告幾乎都會贏，不代表你的案件也會這樣。上面的金額範圍、證據與抗辯統計不包含這些判決。</p>}
    </section>
  );
}
