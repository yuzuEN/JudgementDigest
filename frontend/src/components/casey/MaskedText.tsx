import { splitMasked } from "../../format";

/** 遮名後的文字：【電話】這類標記用橘色 <mark> 標出（橘色只用在遮名）。 */
export function MaskedText({ text, live = false }: { text: string; live?: boolean }) {
  return (
    <div aria-live={live ? "polite" : undefined}
      className="masked-preview rounded-[12px] border bg-background p-[18px] leading-loose whitespace-pre-wrap">
      {splitMasked(text).map((part, i) =>
        part.masked ? <mark key={i} className="masked">{part.text}</mark> : <span key={i}>{part.text}</span>)}
    </div>
  );
}
