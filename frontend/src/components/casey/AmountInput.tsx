import { CheckIcon, InfoIcon } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseAmount } from "../../format";

export type AmountState = "empty" | "ok" | "bad";

export function amountState(text: string): AmountState {
  if (!text.trim()) return "empty";
  return parseAmount(text) === null ? "bad" : "ok";
}

/**
 * 請求金額：一進來就是輸入框（後面接「元」），旁邊一顆「不確定」。
 * 讀得懂的金額在下面說明列顯示「✓ 648,000 元」，看不懂時說明怎麼寫。
 * 「不確定」會清空金額，再按一次取消；開始打字也會取消。
 */
export function AmountInput({ id, value, onChange }: { id: string; value: string; onChange: (value: string) => void }) {
  const [unsure, setUnsure] = useState(false);
  const state = amountState(value);
  const parsed = parseAmount(value);
  const pressed = unsure ? "border-primary bg-primary text-primary-foreground hover:bg-primary" : "border-input bg-card text-foreground";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-3">
          <Input id={id} inputMode="numeric" autoComplete="off" value={value} placeholder="例如 50萬"
            onChange={(e) => { setUnsure(false); onChange(e.target.value); }}
            aria-labelledby={`${id}-label`} aria-invalid={state === "bad"} aria-describedby={`${id}-status`}
            className="h-11 w-36 tabular-nums sm:h-[50px] sm:w-60" />
          <span aria-hidden="true" className="font-bold">元</span>
        </span>
        <Button type="button" variant="outline" aria-pressed={unsure} className={cn("ml-auto h-11 border-2 px-4 text-base font-bold sm:h-[50px]", pressed)}
          onClick={() => { setUnsure(!unsure); if (!unsure) onChange(""); }}>不確定</Button>
      </div>
      <p id={`${id}-status`} role="status" className="flex items-start gap-1.5 text-hint">
        {state === "empty" && <span className="text-muted-foreground">未填入時，結果僅會顯示求償比例</span>}
        {state === "bad" && (
          <><InfoIcon className="mt-1 size-4 flex-none" aria-hidden="true" /><span className="font-bold">看不懂這個金額。請輸入數字，例如 50萬 或 648000。</span></>
        )}
        {state === "ok" && (
          <><CheckIcon className="mt-1 size-4 flex-none text-secondary-foreground" aria-hidden="true" />
            <span className="font-bold text-secondary-foreground tabular-nums">{parsed!.toLocaleString("en-US")} 元</span></>
        )}
      </p>
    </div>
  );
}
