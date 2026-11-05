import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { DownloadIcon, MockBadge } from "./Common";
import { Layout } from "./Layout";

/** 列印或存成 PDF 時展開所有摺疊內容，印完恢復。按瀏覽器的列印也有效。 */
function useOpenDetailsForPrint() {
  useEffect(() => {
    let opened: HTMLDetailsElement[] = [];
    const open = () => {
      const closed = Array.from(document.querySelectorAll<HTMLDetailsElement>("details:not([open])"));
      closed.forEach((d) => { d.open = true; });
      opened.push(...closed);   // 事件可能連續觸發兩次，不能蓋掉前一次的清單
    };
    const restore = () => {
      opened.forEach((d) => { d.open = false; });
      opened = [];
    };
    window.addEventListener("beforeprint", open);
    window.addEventListener("afterprint", restore);
    return () => {
      window.removeEventListener("beforeprint", open);
      window.removeEventListener("afterprint", restore);
    };
  }, []);
}

/** 民事、刑事結果頁共用的外框：分頁、標題、下載 PDF，以及只在列印時出現的報告抬頭。 */
export function ResultFrame({ active, title, lead, mock, maskedText, children }: {
  active: "civil" | "criminal";
  title: string;
  lead: ReactNode;
  mock: boolean;
  maskedText: string;
  children: ReactNode;
}) {
  useOpenDetailsForPrint();
  return (
    <Layout step={3}>
      <main className="page stack">
        <div className="print-only">
          <h1 style={{ margin: "0 0 4px", fontSize: 22 }}>類案判決參考報告（{active === "civil" ? "民事" : "刑事"}）</h1>
          <p className="hint">產生時間：{new Date().toLocaleString("zh-TW")}・刑事及民事類案判決參考平台・結果僅供參考，不是法律意見</p>
          {mock && <p><strong>本報告是示例資料：數字與判決都不是真的，請勿作為判斷依據。</strong></p>}
          <h2 style={{ fontSize: 16 }}>案情描述（已遮名）</h2>
          <p style={{ whiteSpace: "pre-wrap", fontSize: 14 }}>{maskedText}</p>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between", gap: 12 }}>
          <div>
            <nav className="tabs" aria-label="結果類型">
              <Link to="/result/civil" className="tab" aria-current={active === "civil" ? "page" : undefined}>民事</Link>
              <Link to="/result/criminal" className="tab" aria-current={active === "criminal" ? "page" : undefined}>刑事</Link>
            </nav>
            <h1 className="page-title" style={{ margin: 0 }}>{title}</h1>
            <p className="lead" style={{ marginTop: 4 }}>{lead}</p>
          </div>
          <div className="actions no-print">
            <MockBadge show={mock} />
            <button type="button" className="btn secondary small" onClick={() => window.print()}>
              <DownloadIcon />下載 PDF
            </button>
          </div>
        </div>
        {children}
        <div className="actions no-print">
          <Link to="/confirm" className="btn secondary small">回上一步</Link>
          <Link to="/start" className="btn secondary small">修改描述</Link>
        </div>
      </main>
    </Layout>
  );
}
