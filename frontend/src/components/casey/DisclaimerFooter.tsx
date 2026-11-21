import type { ReactNode } from "react";

function NoticeList({ items }: { items: ReactNode[] }) {
  return <ul className="m-0 grid list-disc gap-1.5 pl-5">{items.map((it, i) => <li key={i}>{it}</li>)}</ul>;
}

/** 列印版：請注意的條列直接印在報告裡。 */
export function PrintNotice({ items }: { items: ReactNode[] }) {
  return (
    <section className="print-only text-sm">
      <h2 className="font-bold">請注意</h2>
      <NoticeList items={items} />
    </section>
  );
}
