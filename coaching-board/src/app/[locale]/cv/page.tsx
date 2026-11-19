import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Pending } from "../../../components/pending";
import { PrintButton } from "../../../components/print-button";
import { tx } from "../../../content/i18n";
import { career, contact, heroFacts, playing, profile, site } from "../../../content/profile";
import { ui } from "../../../content/ui";
import { monthYear, timeInRole } from "../../../lib/format";
import { readLocale, type LocaleParams } from "../../../lib/params";

export async function generateMetadata({ params }: LocaleParams): Promise<Metadata> {
  const locale = await readLocale(params);
  return { title: "CV", description: tx(site.role, locale) };
}

export default async function CvPage({ params }: LocaleParams) {
  const locale = await readLocale(params);
  const { email, phone, linkedin, representation } = site.contact;
  const contactLine = [email, phone, representation].filter(Boolean);

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 print:max-w-none print:p-0">
      <div className="no-print mb-8 flex items-center justify-between gap-4">
        <Link
          href={`/${locale}`}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          {tx(ui.backToSite, locale)}
        </Link>
        <PrintButton label={tx(ui.print, locale)} />
      </div>

      <article className="rounded-2xl border border-line bg-card p-7 sm:p-10 print:rounded-none print:border-0 print:bg-white print:p-0">
        <p className="text-[11px] font-medium tracking-[0.18em] text-gold-deep uppercase">
          {tx(site.kicker, locale)}
        </p>
        <h1 className="mt-2 text-4xl leading-tight sm:text-5xl">{site.name}</h1>
        <p className="mt-1 text-lg text-muted-foreground">{tx(site.role, locale)}</p>
        <div className="mt-4">
          <Pending locale={locale} />
        </div>
        {contactLine.length > 0 || linkedin ? (
          <p className="mt-3 text-sm text-muted-foreground">
            {contactLine.join(" · ")}
            {linkedin ? (
              <>
                {contactLine.length > 0 ? " · " : ""}
                <a href={linkedin} className="underline underline-offset-4">
                  {tx(contact.linkedinLabel, locale)}
                </a>
              </>
            ) : null}
          </p>
        ) : null}

        <dl className="mt-6 grid gap-x-8 gap-y-2 border-y border-line py-4 text-sm sm:grid-cols-2">
          {heroFacts.map((fact) => (
            <div key={fact.label.en} className="flex gap-2">
              <dt className="shrink-0 text-muted-foreground">{tx(fact.label, locale)}:</dt>
              <dd>{tx(fact.value, locale)}</dd>
            </div>
          ))}
          {profile.facts
            .filter((fact) => fact.label.en !== "Licence")
            .map((fact) => (
              <div key={fact.label.en} className="flex gap-2">
                <dt className="shrink-0 text-muted-foreground">{tx(fact.label, locale)}:</dt>
                <dd>{tx(fact.value, locale)}</dd>
              </div>
            ))}
        </dl>

        <h2 className="mt-8 text-2xl">{tx(career.title, locale)}</h2>
        <ol className="mt-4 space-y-4">
          {career.entries.map((entry) => (
            <li key={entry.club} className="grid gap-1 sm:grid-cols-[11rem_1fr] sm:gap-4">
              <p className="text-[12px] tracking-wide text-muted-foreground uppercase">
                {monthYear(entry.start, locale)} —{" "}
                {entry.end ? monthYear(entry.end, locale) : tx(ui.present, locale)}
                {entry.end ? (
                  <span className="block normal-case">
                    {entry.span
                      ? tx(entry.span, locale)
                      : timeInRole(entry.start, entry.end, locale)}
                  </span>
                ) : null}
              </p>
              <div>
                <h3 className="text-lg leading-snug">{entry.club}</h3>
                <p className="text-sm">
                  {tx(entry.role, locale)}
                  <span className="text-muted-foreground"> · {tx(entry.place, locale)}</span>
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground">{tx(entry.note, locale)}</p>
              </div>
            </li>
          ))}
        </ol>

        <h2 className="mt-8 text-2xl">{tx(playing.title, locale)}</h2>
        <p className="mt-2 text-sm text-muted-foreground">{tx(playing.intro, locale)}</p>
        <ul className="mt-3 grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
          {playing.honours.map((honour) => (
            <li key={honour.figure}>
              <span className="font-medium">{honour.figure}</span>{" "}
              <span className="text-muted-foreground">{tx(honour.label, locale)}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm leading-relaxed">
          <span className="text-muted-foreground">{tx(playing.clubsLabel, locale)}: </span>
          {playing.clubs.map((club) => `${club.name} (${club.years})`).join(", ")}
        </p>
      </article>
    </div>
  );
}
