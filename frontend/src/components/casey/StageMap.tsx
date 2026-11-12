import { CheckIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

/** 七關，分三章。 */
export const STAGES = ["類型", "案情", "資料", "遮名", "補充", "改寫", "結果"] as const;

const CHAPTERS = [
  { label: "描述案情", from: 1, to: 3 },
  { label: "確認內容", from: 4, to: 6 },
  { label: "參考結果", from: 7, to: 7 },
];

/** 已完成的關卡可以點回去。 */
export function stageHref(n: number): string | null {
  if (n <= 3) return `/start?stage=${n}`;
  if (n <= 6) return `/confirm?stage=${n}`;
  return null;
}

/**
 * 進度圖：7 個節點、分三章。目前節點 aria-current="step"，已完成的打勾並可以點回去。
 * 窄螢幕只顯示目前節點的名稱（其他的名稱留給螢幕報讀）。
 */
export function StageMap({ at }: { at: number }) {
  const chapter = CHAPTERS.find((c) => at >= c.from && at <= c.to);
  return (
    <nav aria-label="進度" data-slot="stepper" className="no-print">
      <div className="mb-1.5 grid grid-cols-7" aria-hidden="true">
        {CHAPTERS.map((c) => (
          <p key={c.label} style={{ gridColumn: `span ${c.to - c.from + 1}` }}
            className={cn("text-center text-sm font-bold whitespace-nowrap", c === chapter ? "text-foreground" : "text-muted-foreground max-sm:invisible")}>
            {c.label}
          </p>
        ))}
      </div>
      <ol className="m-0 flex list-none items-start p-0">
        {STAGES.map((name, i) => {
          const n = i + 1;
          const done = at > n;
          const now = at === n;
          const href = done ? stageHref(n) : null;
          const dot = (
            <span aria-hidden="true" className={cn(
              "relative z-10 grid size-[38px] place-items-center rounded-full border-3 bg-card text-[15px] font-bold sm:size-11",
              done && "border-primary bg-primary text-primary-foreground",
              now && "border-foreground bg-secondary text-secondary-foreground ring-4 ring-secondary",
              !done && !now && "border-input text-muted-foreground",
            )}>
              {done ? <CheckIcon className="size-5" strokeWidth={2.6} /> : n}
            </span>
          );
          const label = (
            <span className={cn("text-sm leading-snug", now ? "font-extrabold text-foreground" : "text-muted-foreground", !now && "max-sm:sr-only")}>
              <span className="sr-only">第 {n} 關 </span>{name}{done && <span className="sr-only">（已完成）</span>}
            </span>
          );
          return (
            <li key={name} aria-current={now ? "step" : undefined} className="relative flex min-w-0 flex-1 flex-col items-center gap-1 text-center">
              {i > 0 && (
                <span aria-hidden="true" className={cn(
                  "absolute top-[18px] right-1/2 h-[3px] w-full sm:top-[21px]",
                  done || now ? "bg-primary" : "bg-input",
                )} />
              )}
              {href
                ? <Link to={href} aria-label={`第 ${n} 關 ${name}（已完成）`} className="flex flex-col items-center gap-1 rounded-lg no-underline">{dot}{label}</Link>
                : <>{dot}{label}</>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
