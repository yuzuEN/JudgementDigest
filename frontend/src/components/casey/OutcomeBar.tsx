import { cn } from "@/lib/utils";

export interface OutcomeCountsLike {
  win: number;
  partial: number;
  lose: number;
}

const SEGMENTS = [
  { key: "win", label: "全部勝訴", bar: "bg-outcome-full", swatch: "bg-outcome-full border-outcome-full" },
  { key: "partial", label: "一部勝訴", bar: "bg-outcome-part", swatch: "bg-outcome-part border-outcome-part" },
  { key: "lose", label: "敗訴", bar: "bg-outcome-lose-pattern", swatch: "bg-outcome-lose-pattern border-outcome-lose-line" },
] as const;

export function outcomeSummary(c: OutcomeCountsLike): string {
  return SEGMENTS.map((s) => `${s.label} ${c[s.key]} 件`).join("、");
}

/**
 * 全部勝訴／一部勝訴／敗訴的比例條。顏色不分好壞（深靛、淺藍、沙灰斜線），一律附文字。
 * 0 件的區段不畫，但圖例永遠都在。
 */
export function OutcomeBar({ counts, legend = true, className }: { counts: OutcomeCountsLike; legend?: boolean; className?: string }) {
  const total = counts.win + counts.partial + counts.lose;
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {/* 區段之間留 2px 底色間隔，相鄰兩色不會黏在一起；滑鼠移上去顯示件數 */}
      <div role="img" aria-label={outcomeSummary(counts)}
        className={cn("flex h-[22px] gap-[2px] overflow-hidden rounded-[11px] border-[1.5px] border-input", total > 0 ? "bg-card" : "bg-muted")}>
        {total > 0 && SEGMENTS.filter((s) => counts[s.key] > 0).map((s) => (
          <div key={s.key} title={`${s.label} ${counts[s.key]} 件`} className={s.bar} style={{ flexBasis: 0, flexGrow: counts[s.key] }} />
        ))}
      </div>
      {legend && (
        <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-[15px]" aria-hidden="true">
          {SEGMENTS.map((s) => (
            <li key={s.key} className="flex items-center gap-2">
              <span className={cn("size-[18px] flex-none rounded-[5px] border-[1.5px]", s.swatch)} />
              {s.label}<b className="tabular-nums">{counts[s.key]} 件</b>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
