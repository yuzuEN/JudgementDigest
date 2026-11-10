import { ArrowRightIcon, ExternalLinkIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Disclosure } from "../components/casey/Disclosure";
import { LAF_URL } from "../components/Common";
import { Layout, PAGE } from "../components/Layout";
import { LinkButton } from "../components/LinkButton";
import { DISPUTE_GROUPS, LEGAL_TERMS, RESULT_TERMS, type Term } from "../knowledge";
import { scrollToSection } from "../scroll";

const SECTIONS = [
  ["basics", "民事和刑事的差別"],
  ["dispute-types", "糾紛類型說明"],
  ["results", "怎麼看結果"],
  ["terms", "常見名詞"],
  ["next", "接下來可以怎麼做"],
] as const;

const READING_TIPS: [string, string][] = [
  ["看件數，不看保證。", "CasEY 告訴你「相似判決有幾件、結果怎麼樣」。範圍一定搭配「10 件約有 8 件」這類說明。"],
  ["範圍很寬時，請保守看待。", "相似判決不多、金額落差大時，結果只能當粗略的參考。"],
  ["勝訴、一部勝訴、敗訴不分好壞。", "用深靛、淺藍、斜線區分，都附文字。「敗訴」只是結果的一種，不是警告。"],
  ["模型的機率收在「模型細節」。", "它是輔助，不是你會贏的機率。"],
  ["相似度是 0 到 1 之間的小數，不是百分比。", "數字越大越相似；大多數判決的數字不會很高，這是正常的。"],
];

function Section({ id, n, title, children }: { id: string; n: number; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-6 flex-col gap-4">
      <div className="flex items-center gap-3">
        <span aria-hidden="true" className="grid size-10 flex-none place-items-center rounded-full bg-primary text-lg font-extrabold text-primary-foreground">{n}</span>
        <h2 id={`${id}-title`} className="text-[22px] leading-[1.45] font-extrabold sm:text-[26px]">{title}</h2>
      </div>
      {children}
    </section>
  );
}

/** 名詞卡：id 是名詞本身，結果頁的「i」用 /guide#名詞 連過來。 */
function TermList({ terms }: { terms: Term[] }) {
  return (
    <dl className="m-0 grid gap-3">
      {terms.map((t) => (
        <div key={t.term} id={t.term} className="flex scroll-mt-6 flex-col gap-1 rounded-[18px] border bg-card px-[18px] py-4">
          <div className="flex items-center justify-between gap-2">
            <dt className="font-bold">{t.term}</dt>
            <span className="rounded-full border-[1.5px] border-input px-2.5 text-[13px] leading-[1.9] font-semibold">{t.group}</span>
          </div>
          <dd className="m-0 text-[15px] text-muted-foreground">{t.meaning}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function Guide() {
  const { hash } = useLocation();

  useEffect(() => {
    if (!hash) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    // 名詞或糾紛類型在收起來的區塊裡時，先打開
    target?.closest("details")?.setAttribute("open", "");
    target?.scrollIntoView?.();
    // 標出要看的標題，像反白一樣，點別的地方就消失
    const title = target?.querySelector("h2, dt");
    if (!title) return;
    title.classList.add("jump-target");
    const clear = () => title.classList.remove("jump-target");
    document.addEventListener("click", clear, { once: true });
    return () => {
      document.removeEventListener("click", clear);
      clear();
    };
  }, [hash]);

  return (
    <Layout scene={{ who: "explainer", line: "這裡是說明與法律小知識。我用白話解釋常見的名詞，也告訴你怎麼看結果。看不懂的地方，可以從結果頁的「i」連到這裡。" }}>
      <div className={cn(PAGE, "pt-8 pb-16")}>
        <div className="flex flex-wrap items-start gap-9">
          <nav aria-label="本頁目錄" className="w-full min-w-0 flex-[1_1_240px] sm:sticky sm:top-5 sm:max-w-[300px]">
            <Card className="gap-2 px-5">
              <p className="font-bold">目錄</p>
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {SECTIONS.map(([id, label]) => (
                  <li key={id}>
                    <a href={`#${id}`} onClick={(e) => { if (scrollToSection(id)) e.preventDefault(); }}
                      className="flex min-h-12 items-center rounded-[14px] border-2 border-input bg-card px-4 font-bold text-foreground no-underline hover:border-foreground hover:bg-secondary">
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </Card>
          </nav>

          <article className="flex min-w-0 max-w-[760px] flex-[999_1_520px] flex-col gap-12">
            <header className="flex flex-col gap-2">
              <h1 className="text-[26px] leading-[1.4] font-extrabold sm:text-[32px]">說明與法律小知識</h1>
              <p className="text-lg leading-[1.8] text-muted-foreground">幾分鐘讀完。你不需要懂法律，也能看懂 CasEY 的結果。這些是一般性的說明，不是法律意見。</p>
            </header>

            <Section id="basics" n={1} title="民事和刑事有什麼不一樣？">
              <div className="grid gap-4 md:grid-cols-2">
                <Card className="gap-2 px-6"><h3 className="text-xl font-bold">民事</h3>
                  <p className="text-[15px] text-muted-foreground">私人之間的糾紛，例如要求賠償、還錢、履行契約，由當事人自己提告。主要是「要不要賠、賠多少」。</p></Card>
                <Card className="gap-2 px-6"><h3 className="text-xl font-bold">刑事</h3>
                  <p className="text-[15px] text-muted-foreground">有沒有犯罪。由檢察官偵查起訴，法院判斷有沒有罪、判多重。</p></Card>
              </div>
              <p className="text-[15px] text-muted-foreground">同一件事有時兩邊都會發生，例如車禍可能同時有賠償問題（民事）和過失傷害問題（刑事）。分不清楚時，在第 1 關選「不確定」。</p>
            </Section>

            <Section id="dispute-types" n={2} title="糾紛類型說明">
              <p className="text-muted-foreground">選最接近的一類就好，不確定時可以不選。分類依判決的案由和內容整理，不是法律上的正式分類。</p>
              <div className="flex flex-col gap-2">
                {DISPUTE_GROUPS.map((group) => (
                  <Disclosure key={group.title} defaultOpen summary={<h3 className="text-lg font-bold">{group.title}<span className="ml-2 text-sm font-normal text-muted-foreground">{group.types.length} 類</span></h3>}>
                    <dl className="m-0 grid gap-2.5 md:grid-cols-2">
                      {group.types.map((t) => (
                        <div key={t.id} id={t.id} className="flex scroll-mt-6 flex-col gap-1 rounded-[12px] bg-muted px-4 py-3">
                          <dt className="font-bold">
                            {t.id.includes("：") ? <><span className="sr-only">{t.id.split("：")[0]}：</span>{t.id.split("：")[1]}</> : t.id}
                          </dt>
                          <dd className="m-0 flex flex-col gap-1 text-[15px]">
                            <span>{t.summary}</span>
                            <span className="text-sm text-muted-foreground">例如　{t.example}</span>
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </Disclosure>
                ))}
              </div>
            </Section>

            <Section id="results" n={3} title="怎麼看結果">
              <ul className="m-0 flex list-disc flex-col gap-2 pl-5">
                {READING_TIPS.map(([title, text]) => <li key={title}><b>{title}</b>{text}</li>)}
              </ul>
              <TermList terms={RESULT_TERMS} />
            </Section>

            <Section id="terms" n={4} title="常見名詞">
              <TermList terms={LEGAL_TERMS} />
            </Section>

            <Section id="next" n={5} title="接下來可以怎麼做？">
              <ol className="m-0 flex list-decimal flex-col gap-2 pl-5">
                <li><b>下載 PDF，帶去給專業人士看。</b>律師或法律扶助基金會可以根據你的實際情況給意見。</li>
                <li><b>先把手上的證物整理好。</b>診斷證明、收據、轉帳紀錄、對話紀錄、照片，依時間排好並備份。</li>
                <li><b>先試著協商或調解。</b>很多糾紛不用走到判決。</li>
                <li><b>有些事情有期限。</b>建議儘早詢問專業人士，不要等到最後。</li>
              </ol>
              <p className="text-[15px] text-muted-foreground">
                需要協助可以洽詢<a href={LAF_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5">法律扶助基金會<ExternalLinkIcon className="size-4" aria-hidden="true" /></a>。
              </p>
              <div className="flex flex-wrap gap-3">
                <LinkButton size="lg" to="/start">開始查詢<ArrowRightIcon data-icon="inline-end" /></LinkButton>
                <LinkButton variant="outline" size="lg" to="/" className="border-input text-foreground">回首頁</LinkButton>
              </div>
            </Section>
          </article>
        </div>
      </div>
    </Layout>
  );
}
