import { ArrowRightIcon, CheckIcon, ScaleIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { LinkButton } from "./LinkButton";
import { scrollToSection } from "../scroll";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";
import { LAF_URL } from "./Common";

export const BRAND = "CasEY";

const STEPS = [
  { label: "描述案情", path: "/start" },
  { label: "確認與遮名", path: "/confirm" },
  { label: "參考結果", path: "" },
];

/** 頁面內容的寬度與左右留白，各頁共用。 */
export const PAGE = "mx-auto w-full max-w-6xl px-4 sm:px-6";

function Brand() {
  return (
    <Link to="/" className="flex min-h-11 items-center gap-2.5 text-lg font-bold text-foreground no-underline hover:text-foreground">
      <span className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <ScaleIcon className="size-5" aria-hidden="true" />
      </span>
      {BRAND}
    </Link>
  );
}

/** 進度條加圓點：做完的打勾、目前的有圓心、還沒到的空心。做完的步驟可以點回去。 */
export function Stepper({ step }: { step: 1 | 2 | 3 }) {
  return (
    <nav aria-label="步驟" data-slot="stepper" className="rounded-xl bg-card px-4 py-4 ring-1 ring-foreground/10 sm:px-8">
      <ol className="flex items-start">
        {STEPS.map(({ label, path }, i) => {
          const n = i + 1;
          const done = n < step;
          const current = n === step;
          const dot = (
            <span
              className={cn(
                "relative z-10 flex size-9 items-center justify-center rounded-full border-2 bg-card transition-colors",
                done && "border-primary bg-primary text-primary-foreground",
                current && "border-primary",
                !done && !current && "border-border",
              )}
              aria-hidden="true"
            >
              {done ? <CheckIcon className="size-4" strokeWidth={3} /> : current ? <span className="size-3 rounded-full bg-primary" /> : null}
            </span>
          );
          const text = (
            <span className={cn("text-sm", current ? "font-semibold text-foreground" : done ? "text-foreground" : "text-muted-foreground")}>
              <span className="sr-only">第 {n} 步 </span>{label}
            </span>
          );
          return (
            <li key={label} className="relative flex flex-1 flex-col items-center gap-2" aria-current={current ? "step" : undefined}>
              {i > 0 && (
                <span
                  aria-hidden="true"
                  className={cn("absolute top-[17px] right-[calc(50%+22px)] left-[calc(-50%+22px)] h-0.5 rounded-full", n <= step ? "bg-primary" : "bg-border")}
                />
              )}
              {done ? (
                <Link to={path} className="flex flex-col items-center gap-2 rounded-lg no-underline hover:text-primary focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none">
                  {dot}{text}
                </Link>
              ) : <>{dot}{text}</>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function FooterColumn({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      <ul className="flex flex-col gap-2 text-sm [&_a]:text-muted-foreground [&_a]:no-underline [&_a:hover]:text-foreground">{children}</ul>
    </div>
  );
}

function SiteFooter() {
  return (
    <footer data-slot="site-footer" className="mt-auto border-t bg-card">
      <div className={cn(PAGE, "grid gap-8 py-10 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr]")}>
        <div className="flex flex-col gap-3">
          <Brand />
          <p className="max-w-sm text-sm text-muted-foreground">用全國地方法院的真實判決，幫你看看類似的案件通常怎麼判。</p>
        </div>
        <FooterColumn title="服務">
          <li><Link to="/start">開始查詢</Link></li>
          <li><Link to="/guide">說明與法律小知識</Link></li>
          <li><Link to="/guide#dispute-types">糾紛類型說明</Link></li>
        </FooterColumn>
        <FooterColumn title="關於">
          <li><a href="/#how">怎麼使用</a></li>
          <li><a href="/#data">資料來源</a></li>
          <li><a href="/#faq">常見問題</a></li>
        </FooterColumn>
        <FooterColumn title="外部資源">
          <li><a href="https://judgment.judicial.gov.tw/FJUD/default.aspx" target="_blank" rel="noreferrer">司法院裁判書查詢系統</a></li>
          <li><a href={LAF_URL} target="_blank" rel="noreferrer">法律扶助基金會</a></li>
        </FooterColumn>
      </div>
      <Separator />
      <div className={cn(PAGE, "flex flex-col gap-1 py-5 text-sm text-muted-foreground sm:flex-row sm:justify-between")}>
        <p>© 2026 {BRAND}／JudgementDigest 專題團隊</p>
        <p>結果僅供參考，不是法律意見</p>
      </div>
    </footer>
  );
}

const HOME_SECTIONS = [["how", "怎麼使用"], ["data", "資料來源"], ["faq", "常見問題"]];

/** 首頁、說明頁共用的導覽列。在首頁時平滑捲到該段；在其他頁時回首頁再捲過去。 */
export function SiteNav() {
  const { pathname } = useLocation();
  const onHome = pathname === "/";
  return (
    <nav aria-label="主選單" className="flex flex-wrap items-center gap-1">
      {HOME_SECTIONS.map(([id, label]) => onHome
        ? <LinkButton key={id} variant="ghost" href={`#${id}`} className="hidden sm:inline-flex"
            onClick={(e) => { if (scrollToSection(id)) e.preventDefault(); }}>{label}</LinkButton>
        : <LinkButton key={id} variant="ghost" to={`/#${id}`} className="hidden sm:inline-flex">{label}</LinkButton>)}
      <LinkButton variant="ghost" to="/guide" aria-current={pathname === "/guide" ? "page" : undefined}
        className="aria-[current=page]:bg-muted aria-[current=page]:text-foreground">說明</LinkButton>
      {!onHome && <LinkButton to="/start" className="ml-1">開始查詢<ArrowRightIcon data-icon="inline-end" /></LinkButton>}
    </nav>
  );
}

/** step：目前在第幾步（1–3），會在內容上方顯示步驟條。nav：頁首右側的連結或按鈕。 */
export function Layout({ step, nav, children }: { step?: 1 | 2 | 3; nav?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col">
      <header data-slot="site-header" className="sticky top-0 z-40 border-b bg-card/90 backdrop-blur supports-[backdrop-filter]:bg-card/75">
        <div className={cn(PAGE, "flex min-h-16 flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2")}>
          <Brand />
          {nav}
        </div>
      </header>
      {step && <div className={cn(PAGE, "pt-8")}><Stepper step={step} /></div>}
      {children}
      <SiteFooter />
    </div>
  );
}
