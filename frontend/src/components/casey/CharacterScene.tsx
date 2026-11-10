import type { ReactNode } from "react";
import explainer from "@/assets/casey/assistant-explainer.png";
import organizer from "@/assets/casey/assistant-organizer.png";
import { cn } from "@/lib/utils";

export type Speaker = "organizer" | "explainer";

const NAME: Record<Speaker, string> = { organizer: "整理員", explainer: "解說員" };

/** 角色說明只出現在首頁和關卡 1。 */
export const ROLE_NOTE = "整理員和解說員只是 CasEY 的輔助角色：幫你整理資料、說明統計。他們不是律師或法官，也不提供法律意見。";

function Figure({ src, active }: { src: string; active: boolean }) {
  return (
    <div className={cn("relative z-10 w-[92px] flex-none sm:w-[150px]", !active && "opacity-50 grayscale-[.4] max-sm:hidden")}>
      <img src={src} alt="" className="block w-full" />
    </div>
  );
}

/**
 * 頁首場景：整理員（左）、解說員（右）、中間對話框。只有說話的那一位是正常亮度。
 * 兩位是輔助角色，不叫律師或法官。
 */
export function CharacterScene({ who = "organizer", children, note = false }: { who?: Speaker; children: ReactNode; note?: boolean }) {
  return (
    <section aria-label="CasEY 角色說明" data-slot="character-scene"
      className="no-print relative flex items-end gap-2.5 overflow-hidden rounded-[20px] border bg-secondary px-3.5 pt-6 sm:gap-4 sm:px-5 sm:pt-6.5">
      <Figure src={organizer} active={who === "organizer"} />
      <div role="status" className="relative z-10 mb-7 min-w-0 flex-1 rounded-2xl border-3 border-foreground bg-card px-3.5 pt-5.5 pb-3.5 sm:mb-[34px] sm:px-5 sm:pt-6 sm:pb-4">
        <span className="absolute -top-[18px] left-4 rounded-[10px] border-3 border-foreground bg-primary px-3.5 text-[15px] leading-[1.9] font-extrabold text-primary-foreground">
          {NAME[who]}
        </span>
        <p className="text-base leading-[1.8] sm:text-lg">{children}</p>
        {note && <p className="mt-2 text-sm text-muted-foreground">{ROLE_NOTE}</p>}
        <span aria-hidden="true" className="absolute right-3.5 bottom-2 size-0 border-x-8 border-t-10 border-x-transparent border-t-foreground" />
      </div>
      <Figure src={explainer} active={who === "explainer"} />
      <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-4 bg-(--scene-floor) opacity-90" />
    </section>
  );
}
