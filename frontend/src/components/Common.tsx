import type { ReactNode } from "react";

export const LAF_URL = "https://www.laf.org.tw/";

export function MockBadge({ show, children = "示例資料：數字與判決都不是真的" }: { show: boolean; children?: ReactNode }) {
  return show ? <span className="badge mock">{children}</span> : null;
}

/** 欄位名稱旁的 i，開新分頁到說明頁，不會中斷目前的流程。 */
export function InfoLink({ to, label }: { to: string; label: string }) {
  return <a className="info-link" href={`/guide#${encodeURIComponent(to)}`} target="_blank" rel="noreferrer"
    aria-label={`${label}（開新分頁）`} title={label}>i</a>;
}

export const SIMILARITY_NOTE = "相似度是用字接近的程度（0 到 1），只用來排列結果，不是百分比，也不代表案情或結果相同。";

export function Loading({ children = "載入中……" }: { children?: ReactNode }) {
  return <p role="status" className="hint loading"><span className="spinner" aria-hidden="true" />{children}</p>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="card warn">
      <h2>出了點問題</h2>
      <p style={{ margin: 0 }}>{message}</p>
      {onRetry && <div><button type="button" className="btn secondary small" onClick={onRetry}>再試一次</button></div>}
    </div>
  );
}

/** 結果頁底下的「怎麼看這些結果」。 */
export function ResultNotes({ items }: { items: ReactNode[] }) {
  return (
    <section className="card warn" aria-labelledby="notes-title">
      <h2 id="notes-title">怎麼看這些結果</h2>
      <ul className="plain">
        {items.map((item, i) => <li key={i}>{item}</li>)}
      </ul>
    </section>
  );
}

export function DownloadIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 4v11" /><path d="M7 10l5 5 5-5" /><path d="M5 20h14" />
    </svg>
  );
}
