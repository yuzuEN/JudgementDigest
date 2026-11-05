import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { applyTheme, initialTheme, type Theme } from "../theme";

const STEPS = ["描述案情", "確認與遮名", "參考結果"];

function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--link)" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v18" /><path d="M5 7h14" /><path d="M5 7l-3 7a4 4 0 0 0 6 0z" />
      <path d="M19 7l-3 7a4 4 0 0 0 6 0z" /><path d="M8 21h8" />
    </svg>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const dark = theme === "dark";
  const toggle = () => {
    const next: Theme = dark ? "light" : "dark";
    setTheme(next);
    applyTheme(next, true);
  };
  return (
    <button type="button" className="theme-toggle" onClick={toggle} aria-label={dark ? "切換成日間模式" : "切換成夜間模式"}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {dark ? (
          <><circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>
        ) : <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />}
      </svg>
    </button>
  );
}

/** step：目前在第幾步（1–3）；首頁與判決導讀不顯示步驟。nav：右上角改放其他連結。 */
export function Layout({ step, nav, children }: { step?: 1 | 2 | 3; nav?: ReactNode; children: ReactNode }) {
  return (
    <>
      <header className="site-header">
        <div className="container">
          <Link to="/" className="brand"><Logo />類案判決參考</Link>
          {step ? (
            <nav aria-label="步驟">
              <ol className="steps">
                {STEPS.map((label, i) => (
                  <li key={label} aria-current={i + 1 === step ? "step" : undefined}>{i + 1} {label}</li>
                ))}
              </ol>
            </nav>
          ) : nav}
          <ThemeToggle />
        </div>
      </header>
      {children}
      <footer className="site-footer">
        <div className="container">JudgementDigest 專題團隊・刑事及民事類案判決參考平台・結果僅供參考，不是法律意見</div>
      </footer>
    </>
  );
}
