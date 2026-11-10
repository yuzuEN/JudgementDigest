import { useEffect } from "react";
import { ArrowRightIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { LinkButton } from "../components/LinkButton";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LAF_URL, PageTitle } from "../components/Common";
import { Layout, PAGE, SiteNav } from "../components/Layout";
import { scrollToSection } from "../scroll";
import { DISPUTE_GROUPS, LEGAL_TERMS, RESULT_TERMS, type Term } from "../knowledge";

const SECTIONS = [
  ["basics", "民事和刑事的差別"],
  ["dispute-types", "糾紛類型說明"],
  ["results", "怎麼看結果"],
  ["terms", "常見名詞"],
  ["next", "下一步可以怎麼做"],
];

function TermList({ terms }: { terms: Term[] }) {
  return (
    <dl className="grid gap-3">
      {terms.map((t) => (
        <div key={t.term} id={t.term} className="scroll-mt-24"><dt className="font-semibold">{t.term}</dt><dd className="text-[15px]">{t.meaning}</dd></div>
      ))}
    </dl>
  );
}

function Section({ id, title, description, children }: { id: string; title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <Card id={id} className="scroll-mt-24" aria-labelledby={`${id}-title`}>
      <CardHeader>
        <CardTitle id={`${id}-title`} className="text-xl font-bold">{title}</CardTitle>
        {description && <CardDescription className="text-[15px]">{description}</CardDescription>}
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-[15px] leading-relaxed">{children}</CardContent>
    </Card>
  );
}

export default function Guide() {
  const { hash } = useLocation();

  useEffect(() => {
    if (!hash) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
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
    <Layout nav={<SiteNav />}>
      <main className={cn(PAGE, "grid gap-6 py-8 pb-16 lg:grid-cols-[220px_minmax(0,1fr)] lg:gap-8")}>
        <nav aria-label="本頁目錄" className="lg:sticky lg:top-24 lg:self-start">
          <p className="mb-2 text-sm font-semibold text-muted-foreground">本頁目錄</p>
          <ul className="flex flex-wrap gap-1 lg:flex-col">
            {SECTIONS.map(([id, label]) => (
              <li key={id}><LinkButton variant="ghost" className="justify-start" href={`#${id}`}
                onClick={(e) => { if (scrollToSection(id)) e.preventDefault(); }}>{label}</LinkButton></li>
            ))}
          </ul>
        </nav>
        <div className="flex min-w-0 flex-col gap-6">
          <PageTitle title="說明與法律小知識" lead="用白話整理使用平台時會遇到的名詞。這些是一般性的說明，不是法律意見。" />

          <Section id="basics" title="民事和刑事的差別">
            <p><strong>民事</strong>是人與人之間的糾紛，例如要求賠償、還錢、履行契約，由當事人自己提告。</p>
            <p><strong>刑事</strong>是有沒有犯罪，由檢察官偵查起訴，法院決定有罪與否和刑期。</p>
            <p className="text-muted-foreground">同一件事可能兩邊都有。例如車禍受傷，刑事上可能是過失傷害，民事上可以請求賠償。</p>
          </Section>

          <Section id="dispute-types" title="糾紛類型說明" description="選最接近的一類就好。不確定時可以留空，系統會試著判斷。分類依判決的案由和內容整理，不是法律上的正式分類。">
            <div className="flex flex-col gap-8 pt-2">
              {DISPUTE_GROUPS.map((group, gi) => (
                <section key={group.title} aria-labelledby={`group-${gi}`} className="flex flex-col gap-3">
                  {/* 大類：主色標題＋左側色條；底下的類型縮排成卡片，一眼分得出層級 */}
                  <h3 id={`group-${gi}`} className="flex items-center gap-2.5 text-lg font-bold text-primary">
                    <span className="h-5 w-1 rounded-full bg-primary" aria-hidden="true" />
                    {group.title}
                    <span className="text-sm font-normal text-muted-foreground">{group.types.length} 類</span>
                  </h3>
                  <dl className="grid gap-3 border-l-2 border-primary/15 pl-4 sm:ml-1 md:grid-cols-2">
                    {group.types.map((t) => (
                      <div key={t.id} id={t.id} className="flex scroll-mt-24 flex-col gap-1 rounded-lg bg-muted/40 px-4 py-3 ring-1 ring-border">
                        <dt className="flex items-center gap-2 font-bold">
                          <span className="size-1.5 flex-none rounded-full bg-primary" aria-hidden="true" />
                          {t.id.includes("：") ? <><span className="sr-only">{t.id.split("：")[0]}：</span>{t.id.split("：")[1]}</> : t.id}
                        </dt>
                        <dd className="flex flex-col gap-1 pl-3.5">
                          <span>{t.summary}</span>
                          <span className="text-sm text-muted-foreground"><span className="font-medium text-foreground/70">例如</span>　{t.example}</span>
                        </dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ))}
            </div>
          </Section>

          <Section id="results" title="怎麼看結果"><TermList terms={RESULT_TERMS} /></Section>
          <Section id="terms" title="常見名詞"><TermList terms={LEGAL_TERMS} /></Section>

          <Section id="next" title="下一步可以怎麼做">
            <ul className="flex list-disc flex-col gap-1.5 pl-5">
              <li>整理證據：把契約、對話紀錄、收據、照片依時間排好。</li>
              <li>先試著協商或調解：很多糾紛不用走到判決。</li>
              <li>諮詢專業：<a href={LAF_URL}>法律扶助基金會</a>或律師可以看你的實際情況。</li>
            </ul>
            <div><LinkButton size="lg" to="/start">開始描述案情<ArrowRightIcon data-icon="inline-end" /></LinkButton></div>
          </Section>
        </div>
      </main>
    </Layout>
  );
}
