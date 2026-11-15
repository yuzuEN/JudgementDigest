import { CircleHelpIcon, ScaleIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { CharacterScene, type Speaker } from "./casey/CharacterScene";
import { StageMap } from "./casey/StageMap";
import { ThemeToggle } from "./casey/ThemeToggle";
import { LAF_URL } from "./Common";

export const BRAND = "CasEY";
export const JUDICIAL_URL = "https://judgment.judicial.gov.tw/FJUD/default.aspx";

/** 頁面內容的寬度與左右留白，各頁共用。 */
export const PAGE = "mx-auto w-full max-w-[1120px] px-4 sm:px-6";

function Brand() {
  return (
    <Link to="/" className="flex min-h-11 items-center gap-2.5 text-lg leading-tight font-extrabold text-foreground no-underline hover:text-foreground">
      <span className="grid size-10 place-items-center rounded-[11px] bg-primary text-primary-foreground">
        <ScaleIcon className="size-6" aria-hidden="true" />
      </span>
      <span className="flex flex-col">
        {BRAND}
        <small className="text-xs font-medium tracking-[.06em] text-muted-foreground">類案判決參考</small>
      </span>
    </Link>
  );
}

function SiteFooter({ note }: { note?: ReactNode }) {
  return (
    <footer data-slot="site-footer" className="mt-auto border-t bg-muted pt-8 pb-10 text-[15px] text-muted-foreground">
      <div className={cn(PAGE, "flex flex-col gap-2")}>
        {note ?? <p>本服務提供的是過去判決的統計參考，不是法律意見。</p>}
        <p className="flex flex-wrap gap-x-4 gap-y-1">
          <a href={LAF_URL} target="_blank" rel="noreferrer">法律扶助基金會</a>
          <Link to="/guide" className="text-link underline underline-offset-3">說明與法律小知識</Link>
          <a href={JUDICIAL_URL} target="_blank" rel="noreferrer">司法院裁判書查詢系統</a>
        </p>
      </div>
    </footer>
  );
}

/** 舊的三步驟（確認頁、結果頁還沒拆關卡）對到七關的進度圖。 */
const STEP_TO_STAGE = { 1: 1, 2: 4, 3: 7 } as const;

export interface SceneProps {
  who?: Speaker;
  line: ReactNode;
  note?: boolean;
}

/**
 * stage：目前在第幾關（1–7），內容上方顯示進度圖；step 是改版前的三步驟，會換算成關卡。
 * scene：頁首的角色場景。nav：頁首右側另外放的連結或按鈕。footer：換掉頁尾第一行（結果頁放「請注意」）。
 */
export function Layout({ stage, step, scene, nav, footer, children }: {
  stage?: number; step?: 1 | 2 | 3; scene?: SceneProps; nav?: ReactNode; footer?: ReactNode; children: ReactNode;
}) {
  const at = stage ?? (step ? STEP_TO_STAGE[step] : 0);
  return (
    <div className="flex min-h-svh flex-col">
      <header data-slot="site-header" className="border-b bg-card">
        <div className={cn(PAGE, "flex min-h-[68px] flex-wrap items-center gap-x-5 gap-y-3 py-2")}>
          <Brand />
          <span className="flex-1" />
          {nav}
          <Link to="/guide" aria-label="說明與法律小知識"
            className="inline-flex min-h-11 items-center gap-1.5 px-1.5 font-semibold text-link no-underline hover:underline">
            <CircleHelpIcon className="size-5" aria-hidden="true" />
            <span className="max-sm:hidden">說明與法律小知識</span>
          </Link>
          <ThemeToggle />
        </div>
      </header>
      {at > 0 && <div className={cn(PAGE, "pt-5.5")}><StageMap at={at} /></div>}
      {scene && (
        <div className={cn(PAGE, "pt-5.5")}>
          <CharacterScene who={scene.who} note={scene.note}>{scene.line}</CharacterScene>
        </div>
      )}
      {children}
      <SiteFooter note={footer} />
    </div>
  );
}
