import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { LAF_URL } from "../components/Common";
import { Layout } from "../components/Layout";
import { DISPUTE_GROUPS, LEGAL_TERMS, RESULT_TERMS, type Term } from "../knowledge";

const SECTIONS = [
  ["basics", "民事和刑事的差別"],
  ["dispute-types", "糾紛類型說明"],
  ["results", "怎麼看結果"],
  ["terms", "常見名詞"],
  ["next", "下一步可以怎麼做"],
];

function TermList({ terms }: { terms: Term[] }) {
  return (
    <dl className="terms">
      {terms.map((t) => (
        <div key={t.term}><dt>{t.term}</dt><dd>{t.meaning}</dd></div>
      ))}
    </dl>
  );
}

export default function Guide() {
  const { hash } = useLocation();

  useEffect(() => {
    if (!hash) return;
    document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView?.();
  }, [hash]);

  return (
    <Layout>
      <main className="container page">
        <h1 className="page-title">說明與法律小知識</h1>
        <p className="lead">用白話整理使用平台時會遇到的名詞。這些是一般性的說明，不是法律意見。</p>

        <nav className="card" aria-label="本頁目錄">
          <ul className="plain">
            {SECTIONS.map(([id, label]) => <li key={id}><a href={`#${id}`}>{label}</a></li>)}
          </ul>
        </nav>

        <section className="card" id="basics" aria-labelledby="basics-title">
          <h2 id="basics-title">民事和刑事的差別</h2>
          <p><strong>民事</strong>是人與人之間的糾紛，例如要求賠償、還錢、履行契約，由當事人自己提告。</p>
          <p><strong>刑事</strong>是有沒有犯罪，由檢察官偵查起訴，法院決定有罪與否和刑期。</p>
          <p className="hint">同一件事可能兩邊都有。例如車禍受傷，刑事上可能是過失傷害，民事上可以請求賠償。</p>
        </section>

        <section className="card" id="dispute-types" aria-labelledby="types-title">
          <h2 id="types-title">糾紛類型說明</h2>
          <p className="hint">選最接近的一類就好。不確定時可以留空，系統會試著判斷。分類依判決的案由和內容整理，不是法律上的正式分類。</p>
          {DISPUTE_GROUPS.map((group) => (
            <div key={group.title}>
              <h3>{group.title}</h3>
              <dl className="terms">
                {group.types.map((t) => (
                  <div key={t.id} id={t.id}>
                    <dt>{t.id}</dt>
                    <dd>{t.summary}<span className="hint">例如：{t.example}</span></dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </section>

        <section className="card" id="results" aria-labelledby="results-title">
          <h2 id="results-title">怎麼看結果</h2>
          <TermList terms={RESULT_TERMS} />
        </section>

        <section className="card" id="terms" aria-labelledby="terms-title">
          <h2 id="terms-title">常見名詞</h2>
          <TermList terms={LEGAL_TERMS} />
        </section>

        <section className="card" id="next" aria-labelledby="next-title">
          <h2 id="next-title">下一步可以怎麼做</h2>
          <ul className="plain">
            <li>整理證據：把契約、對話紀錄、收據、照片依時間排好。</li>
            <li>先試著協商或調解：很多糾紛不用走到判決。</li>
            <li>諮詢專業：<a href={LAF_URL}>法律扶助基金會</a>或律師可以看你的實際情況。</li>
          </ul>
          <div className="actions"><Link to="/start" className="btn">開始描述案情</Link></div>
        </section>
      </main>
    </Layout>
  );
}
