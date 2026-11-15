import { CheckIcon, InfoIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseAmount } from "../../format";

export type AmountState = "empty" | "ok" | "bad";

export function amountState(text: string): AmountState {
  if (!text.trim()) return "empty";
  return parseAmount(text) === null ? "bad" : "ok";
}

const QUICK = [
  { label: "50 萬", value: "50萬" },
  { label: "648,000", value: "648000" },
  { label: "還不確定", value: "" },
];

/** 請求金額：即時告訴使用者「我讀成多少」，看不懂時說明怎麼寫。 */
export function AmountInput({ id, value, onChange }: { id: string; value: string; onChange: (value: string) => void }) {
  const state = amountState(value);
  const parsed = parseAmount(value);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2.5">
        <Input id={id} inputMode="numeric" autoComplete="off" value={value} onChange={(e) => onChange(e.target.value)}
          aria-invalid={state === "bad"} aria-describedby={`${id}-status`} className="max-w-[260px] tabular-nums" />
        <span className="font-bold">元</span>
      </div>
      <p id={`${id}-status`} role="status" className="flex items-start gap-1.5 text-[15px]">
        {state === "empty" && <span className="text-muted-foreground">沒填也可以，但就看不到金額範圍，只會顯示比例。</span>}
        {state === "bad" && (
          <><InfoIcon className="mt-1 size-4 flex-none" aria-hidden="true" /><span className="font-bold">看不懂這個金額。請輸入數字，例如 50萬 或 648000。</span></>
        )}
        {state === "ok" && (
          <><CheckIcon className="mt-1 size-4 flex-none text-secondary-foreground" aria-hidden="true" />
            <span className="font-bold text-secondary-foreground">我讀成：{parsed!.toLocaleString("en-US")} 元</span></>
        )}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">快速填入：</span>
        {QUICK.map((q) => (
          <Button key={q.label} type="button" variant="outline" size="sm" className="rounded-full border-[1.5px] border-input text-foreground"
            onClick={() => onChange(q.value)}>{q.label}</Button>
        ))}
      </div>
    </div>
  );
}
