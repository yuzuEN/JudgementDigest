import { Link } from "react-router-dom";
import { LAF_URL } from "../components/Common";
import { Layout } from "../components/Layout";

const FAQ = [
  ["我的描述會被保存嗎？", "不會。結果只在你的瀏覽器裡顯示，重新整理就會清空；要留存可以下載成 PDF。我們只記錄你何時同意了哪一版資料使用說明。"],
  ["和直接問 AI 聊天機器人有什麼不同？", "聊天機器人可能編造不存在的判決。這裡的每一件相似判決都是真的、附字號；機率是從真實判決統計出來的。"],
  ["結果有多準？", "勝敗的推估在測試資料上明顯優於隨機猜測，但仍會出錯；金額只能給範圍。描述越完整，結果越可靠。"],
];

export default function Home() {
  return (
    <Layout nav={
      <nav aria-label="主選單" style={{ display: "flex", gap: 20, fontSize: 15 }}>
        <a href="#how">怎麼使用</a><a href="#data">資料來源</a><a href="#faq">常見問題</a>
      </nav>
    }>
      <main>
        <section className="hero">
          <div className="container">
            <div className="copy">
              <h1>遇到法律糾紛，<br />先看看類似的案件怎麼判</h1>
              <p>描述你遇到的事，我們從全國地方法院的真實判決中，找出和你相似的案件，告訴你這類案件打到判決時通常的結果，作為規劃下一步的參考。</p>
              <div className="actions">
                <Link to="/start" className="btn">開始描述案情</Link>
                <span className="hint">免費・不用註冊・約 5 分鐘</span>
              </div>
            </div>
            <div className="sample" aria-label="結果示意">
              <span className="hint">結果示意</span>
              <div className="card" style={{ padding: 16, gap: 4 }}>
                <span className="hint">類似案件原告勝訴的比例</span>
                <span style={{ fontSize: 32, fontWeight: 700, color: "var(--accent-ink)" }}>62%</span>
                <div className="bar thin" role="img" aria-label="62%"><span style={{ width: "62%" }} /></div>
              </div>
              <div className="card" style={{ padding: 16, gap: 2 }}>
                <span className="hint">相似的真實判決</span>
                <span>臺灣○○地方法院 ○○○ 年度訴字第 ○○○ 號</span>
                <span className="hint">一部勝訴・判准 31 萬／請求 48 萬</span>
              </div>
            </div>
          </div>
        </section>

        <div className="page stack">
          <section id="how" className="stack" aria-labelledby="get-title">
            <h2 id="get-title" style={{ margin: 0, fontSize: 28 }}>你會得到什麼</h2>
            <div className="grid-3">
              <div className="card"><h3 style={{ margin: 0 }}>相似的真實判決</h3><p className="hint">每一件都附字號，可以到司法院網站查證，不會是編造的判決。</p></div>
              <div className="card"><h3 style={{ margin: 0 }}>可能的結果範圍</h3><p className="hint">民事：勝訴機率、判准金額範圍。刑事：可能的罪名、法條、刑期範圍。</p></div>
              <div className="card"><h3 style={{ margin: 0 }}>準備的方向</h3><p className="hint">相似案件常提到哪些證據、對方常怎麼抗辯，以及標好重點的判決導讀。</p></div>
            </div>
            <h2 style={{ margin: "16px 0 0", fontSize: 28 }}>怎麼使用</h2>
            <ol className="how grid-3">
              <li><span className="num">1</span><span><strong>描述案情</strong><br /><span className="hint">寫下經過，回答幾個基本問題。</span></span></li>
              <li><span className="num">2</span><span><strong>確認與遮名</strong><br /><span className="hint">補充細節，預覽遮掉姓名後送出的內容。</span></span></li>
              <li><span className="num">3</span><span><strong>看參考結果</strong><br /><span className="hint">可以下載成 PDF，帶去和律師或家人討論。</span></span></li>
            </ol>
          </section>

          <section id="data" className="grid-2">
            <div className="card"><h2>資料來源</h2><p className="hint">司法院公開的全國地方法院判決。以規則切分段落、擷取事實與判決結果，建立結構化資料集；判決書中的當事人姓名在顯示時會遮掉。</p></div>
            <div className="card warn"><h2>這不是法律意見</h2><p style={{ margin: 0 }}>結果是統計參考，不預測你的案件一定會怎麼判。和解、撤回的案件沒有判決書，不在資料裡。重要決定請諮詢律師或<a href={LAF_URL}>法律扶助基金會</a>。</p></div>
          </section>

          <section id="faq" className="stack" style={{ gap: 12 }} aria-labelledby="faq-title">
            <h2 id="faq-title" style={{ margin: 0, fontSize: 28 }}>常見問題</h2>
            {FAQ.map(([q, a]) => (
              <details key={q} className="faq"><summary>{q}</summary><p className="hint" style={{ marginTop: 10 }}>{a}</p></details>
            ))}
          </section>
        </div>
      </main>
    </Layout>
  );
}
