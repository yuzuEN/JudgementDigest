import { ChevronDownIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { usePhone } from "@/lib/usePhone";

/**
 * 手機上預設收起來的說明：電腦版原樣顯示（標題＋內容，DOM 和沒包之前一樣）；
 * 手機版標題裡多一顆展開按鈕，內容點了才出現。列印一律展開。
 *
 * heading：把標題文字包成原本的標題元素，例如 (c) => <h2 className="…">{c}</h2>。
 * 沒有 heading 時（只是一段說明、沒有標題）：電腦版只顯示內容；手機版是一顆「label ⌄」小按鈕。
 */
export function PhoneCollapse({ label, phoneLabel, heading, children, className }: {
  label: ReactNode;
  /** 手機上按鈕用的文字（例如加上「已寫到 3／6」），沒給就用 label */
  phoneLabel?: ReactNode;
  heading?: (content: ReactNode) => ReactNode;
  children: ReactNode;
  /** 手機版內容外層的 class（電腦版沒有外層） */
  className?: string;
}) {
  const phone = usePhone();
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!phone) return <>{heading?.(label)}{children}</>;
  const button = (
    <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}
      className={cn("flex min-h-11 items-center gap-2 text-left", heading ? "w-full justify-between" : "w-fit text-hint font-semibold text-link")}>
      <span>{phoneLabel ?? label}</span>
      <ChevronDownIcon className={cn("size-5 flex-none transition-transform motion-reduce:transition-none", open && "rotate-180")} aria-hidden="true" />
    </button>
  );
  return (
    <>
      {heading ? heading(button) : button}
      <div id={id} hidden={!open} className={cn("print:!block", className)}>{children}</div>
    </>
  );
}
