import type { Metadata } from "next";
import { Quote } from "lucide-react";
import { PageIntro } from "../../../components/page-intro";
import { Pending } from "../../../components/pending";
import { beliefs } from "../../../content/coaching";
import { tx } from "../../../content/i18n";
import { site } from "../../../content/profile";
import { readLocale, type LocaleParams } from "../../../lib/params";

export async function generateMetadata({ params }: LocaleParams): Promise<Metadata> {
  const locale = await readLocale(params);
  return { title: tx(beliefs.title, locale), description: tx(beliefs.intro, locale) };
}

export default async function BeliefsPage({ params }: LocaleParams) {
  const locale = await readLocale(params);

  return (
    <>
      <PageIntro locale={locale} title={tx(beliefs.title, locale)} intro={tx(beliefs.intro, locale)} />

      <section className="border-b border-line">
        <figure className="mx-auto max-w-4xl px-4 py-14 sm:px-6 sm:py-20">
          <Quote className="size-8 text-gold" aria-hidden="true" />
          {beliefs.openingStatement ? (
            <blockquote className="font-heading mt-5 text-3xl leading-snug text-foreground sm:text-4xl">
              {tx(beliefs.openingStatement, locale)}
            </blockquote>
          ) : (
            <div className="mt-5">
              <p className="font-heading text-3xl leading-snug text-foreground/35 sm:text-4xl">
                {tx(beliefs.openingLabel, locale)}
              </p>
              <Pending locale={locale} className="mt-4" />
            </div>
          )}
          <figcaption className="mt-6 text-sm tracking-wide text-muted-foreground">
            — {site.name}
          </figcaption>
        </figure>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
        <ol className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {beliefs.items.map((item, index) => (
            <li key={item.id} className="flex flex-col rounded-xl border border-line bg-card p-6">
              <p className="flex items-baseline justify-between text-[11px] font-medium tracking-[0.18em] text-gold-deep uppercase">
                <span>{tx(item.theme, locale)}</span>
                <span>0{index + 1}</span>
              </p>
              {item.statement ? (
                <h2 className="mt-4 text-2xl leading-snug text-foreground">
                  {tx(item.statement, locale)}
                </h2>
              ) : (
                <div className="mt-4 space-y-2" aria-hidden="true">
                  <div className="h-3 w-4/5 rounded-full bg-muted" />
                  <div className="h-3 w-3/5 rounded-full bg-muted" />
                </div>
              )}
              {item.body ? (
                <p className="mt-3 text-[15px] leading-relaxed whitespace-pre-line text-muted-foreground">
                  {tx(item.body, locale)}
                </p>
              ) : (
                <Pending locale={locale} className="mt-5 self-start" />
              )}
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
