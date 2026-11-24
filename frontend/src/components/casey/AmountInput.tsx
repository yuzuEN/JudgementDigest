import { CheckIcon, InfoIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseAmount } from "../../format";

export type AmountState = "empty" | "ok" | "bad";

export function amountState(text: string): AmountState {
  if (!text.trim()) return "empty";
  return parseAmount(text) === null ? "bad" : "ok";
}

/** 常用金額。5 萬約是民事請求金額的第 5 百分位，50 萬接近中位數（retrieval_civil_v6）。 */
const PRESETS = [
  { label: "5萬", value: 50_000 },
  { label: "50萬", value: 500_000 },
];

type Mode = "preset" | "custom" | "unsure" | "";

function initialMode(value: string): Mode {
  if (!value.trim()) return "";
  return PRESETS.some((p) => p.value === parseAmount(value)) ? "preset" : "custom";
}

/**
 * 請求金額：一列按鈕（5萬、50萬、自訂、不確定），單位「元」在同一列最右邊。
 * 「自訂」按下去直接變成輸入框；讀得懂的金額在「元」右邊滑入「✓ 金額」，看不懂時在下面說明怎麼寫。
 * 手機：輸入框自己一列、「元」緊接在後面；「✓ 金額」改在下面的說明列顯示。
 */
export function AmountInput({ id, value, onChange }: { id: string; value: string; onChange: (value: string) => void }) {
  const [mode, setMode] = useState<Mode>(() => initialMode(value));
  const input = useRef<HTMLInputElement>(null);
  const state = amountState(value);
  const parsed = parseAmount(value);

  // 按「自訂」之後焦點直接進輸入框
  useEffect(() => { if (mode === "custom") input.current?.focus(); }, [mode]);

  const choice = "h-11 rounded-full border-[1.5px] px-4 text-base font-bold";
  const pressed = (on: boolean) => on ? "border-primary bg-primary text-primary-foreground hover:bg-primary" : "border-input bg-card text-foreground";

  return (
    <div className="flex flex-col gap-2">
      <div role="group" aria-labelledby={`${id}-label`} className="flex flex-wrap items-center gap-2">
        {PRESETS.map((p) => {
          const on = mode === "preset" && parsed === p.value;
          return (
            <Button key={p.label} type="button" variant="outline" aria-pressed={on} className={cn(choice, pressed(on))}
              onClick={() => { setMode("preset"); onChange(String(p.value)); }}>{p.label}</Button>
          );
        })}
        {mode === "custom" ? (
          <span className="inline-flex items-center gap-2 phone:order-last phone:w-full">
            <Input ref={input} id={id} inputMode="numeric" autoComplete="off" value={value} placeholder="輸入金額"
              onChange={(e) => onChange(e.target.value)} aria-label="自訂金額" aria-invalid={state === "bad"} aria-describedby={`${id}-status`}
              className="h-11 w-[180px] rounded-full tabular-nums phone:w-auto phone:min-w-0 phone:flex-1" />
            <span aria-hidden="true" className="hidden font-bold phone:inline">元</span>
          </span>
        ) : (
          <Button type="button" variant="outline" aria-pressed={false} className={cn(choice, pressed(false))}
            onClick={() => { setMode("custom"); if (mode === "preset") onChange(""); }}>自訂</Button>
        )}
        <Button type="button" variant="outline" aria-pressed={mode === "unsure"} className={cn(choice, pressed(mode === "unsure"))}
          onClick={() => { setMode("unsure"); onChange(""); }}>不確定</Button>
        <span className="ml-auto flex items-center gap-3 phone:hidden">
          <span className="font-bold">元</span>
          {state === "ok" && (
            <span key={parsed} className="flex items-center gap-1 font-bold text-secondary-foreground tabular-nums animate-in fade-in slide-in-from-right-4 duration-300 motion-reduce:animate-none">
              <CheckIcon className="size-4" aria-hidden="true" />{parsed!.toLocaleString("en-US")} 元
            </span>
          )}
        </span>
      </div>
      <p id={`${id}-status`} role="status" className="flex items-start gap-1.5 text-hint">
        {state === "empty" && <span className="text-muted-foreground">未填入時，結果僅會顯示求償比例</span>}
        {state === "bad" && (
          <><InfoIcon className="mt-1 size-4 flex-none" aria-hidden="true" /><span className="font-bold">看不懂這個金額。請輸入數字，例如 50萬 或 648000。</span></>
        )}
        {state === "ok" && <CheckIcon className="mt-1 hidden size-4 flex-none text-secondary-foreground phone:block" aria-hidden="true" />}
        {state === "ok" && <span className="sr-only phone:not-sr-only phone:font-bold phone:text-secondary-foreground phone:tabular-nums">我讀成：{parsed!.toLocaleString("en-US")} 元</span>}
      </p>
    </div>
  );
}
