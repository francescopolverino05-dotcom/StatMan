import Image from "next/image";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, FileText, Mail, Phone } from "lucide-react";
import { SectionHeading } from "../../components/section-heading";
import { tx, type Locale } from "../../content/i18n";
import {
  career,
  contact,
  heroFacts,
  method,
  playing,
  profile,
  site,
} from "../../content/profile";
import { tabs, ui } from "../../content/ui";
import { monthYear, timeInRole } from "../../lib/format";
import { readLocale, type LocaleParams } from "../../lib/params";

export default async function ProfilePage({ params }: LocaleParams) {
  const locale = await readLocale(params);
  const coachingTabs = tabs.filter(
    (tab): tab is Exclude<(typeof tabs)[number], { id: "profile" }> => tab.id !== "profile",
  );

  return (
    <>
      <Hero locale={locale} />

      <section id="profile" className="border-b border-line">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
          <SectionHeading kicker={tx(profile.kicker, locale)} title={tx(profile.title, locale)} />
          <div className="mt-8 max-w-3xl">
            <p className="text-xl leading-relaxed text-foreground">
              {tx(profile.lead, locale)}
            </p>
            <div className="mt-6 space-y-4 text-[15px] leading-relaxed text-muted-foreground">
              {profile.paragraphs.map((paragraph) => (
                <p key={paragraph.en}>{tx(paragraph, locale)}</p>
              ))}
            </div>
            <dl className="mt-8 grid gap-3 sm:grid-cols-3">
              {profile.facts.map((fact) => (
                <div key={fact.label.en} className="rounded-lg border border-line bg-card p-4">
                  <dt className="text-[10px] font-medium tracking-[0.16em] text-gold-deep uppercase">
                    {tx(fact.label, locale)}
                  </dt>
                  <dd className="mt-1.5 text-sm text-foreground">{tx(fact.value, locale)}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </section>

      <section id="method" className="border-b border-line">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
          <SectionHeading
            kicker={tx(method.kicker, locale)}
            title={tx(method.title, locale)}
            intro={tx(method.intro, locale)}
          />
          <div className="mt-10 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {coachingTabs.map((tab, index) => (
              <Link
                key={tab.id}
                href={`/${locale}${tab.path}`}
                className="group flex min-h-56 flex-col rounded-xl bg-ink p-5 text-white transition-colors hover:bg-navy"
              >
                <span className="font-heading text-4xl leading-none text-gold">0{index + 1}</span>
                <span className="font-heading mt-auto pt-8 text-2xl leading-none tracking-wide text-white uppercase">
                  {tx(tab.label, locale)}
                </span>
                <span className="mt-3 text-sm leading-relaxed text-white/70">
                  {tx(method.cards[tab.id], locale)}
                </span>
                <ArrowRight
                  className="mt-4 size-4 text-gold transition-transform group-hover:translate-x-1"
                  aria-hidden="true"
                />
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section id="career" className="border-b border-line">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
          <SectionHeading
            kicker={tx(career.kicker, locale)}
            title={tx(career.title, locale)}
            intro={tx(career.intro, locale)}
          />
          <ol className="scrollbar-none mt-10 flex gap-4 overflow-x-auto pb-2">
            {career.entries.map((entry) => {
              const today = new Date().toISOString().slice(0, 10);
              return (
                <li
                  key={entry.club}
                  className={`flex w-72 shrink-0 flex-col rounded-xl border bg-card p-5 ${
                    entry.end ? "border-line" : "border-gold-deep"
                  }`}
                >
                  <p className="font-heading text-3xl leading-none tracking-wide text-gold-deep uppercase">
                    {entry.span
                      ? tx(entry.span, locale)
                      : timeInRole(entry.start, entry.end ?? today, locale)}
                  </p>
                  <p className="mt-3 text-[11px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
                    {monthYear(entry.start, locale)} —{" "}
                    {entry.end ? monthYear(entry.end, locale) : tx(ui.present, locale)}
                  </p>
                  <h3 className="mt-4 text-2xl leading-none tracking-wide text-foreground uppercase">
                    {entry.club}
                  </h3>
                  <p className="mt-2 text-sm text-foreground">
                    {tx(entry.role, locale)}
                    <span className="text-muted-foreground"> · {tx(entry.place, locale)}</span>
                  </p>
                  <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                    {tx(entry.note, locale)}
                  </p>
                </li>
              );
            })}
          </ol>
        </div>
      </section>

      <section id="playing" className="border-b border-line">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
          <SectionHeading
            kicker={tx(playing.kicker, locale)}
            title={tx(playing.title, locale)}
            intro={tx(playing.intro, locale)}
          />
          <div className="mt-10">
            <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {playing.honours.map((honour) => (
                <div key={honour.figure} className="rounded-lg border border-line bg-card p-5">
                  <dt className="font-heading text-3xl text-foreground">{honour.figure}</dt>
                  <dd className="mt-1 text-sm text-muted-foreground">
                    {tx(honour.label, locale)}
                  </dd>
                </div>
              ))}
            </dl>
            <h3 className="mt-8 text-[11px] font-medium tracking-[0.16em] text-gold-deep uppercase [font-family:var(--font-sans)]">
              {tx(playing.clubsLabel, locale)}
            </h3>
            <ul className="mt-3 flex flex-wrap gap-2">
              {playing.clubs.map((club) => (
                <li
                  key={`${club.name}-${club.years}`}
                  className="rounded-full border border-line bg-card px-3 py-1.5 text-sm text-foreground"
                >
                  {club.name}
                  <span className="ml-1.5 text-[12px] text-muted-foreground">{club.years}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <ContactSection locale={locale} />
    </>
  );
}

function Hero({ locale }: { locale: Locale }) {
  return (
    <section className="bg-ink text-white">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
        <div className="flex items-start justify-between gap-5">
          <div className="max-w-2xl">
            <p className="rise text-[11px] font-medium tracking-[0.18em] text-gold uppercase">
              {tx(site.kicker, locale)}
            </p>
            <h1 className="rise rise-2 mt-4 text-5xl sm:text-7xl">{site.name}</h1>
            <p className="rise rise-2 mt-4 text-lg text-white/70">{tx(site.role, locale)}</p>
          </div>
          {site.photo ? (
            <Image
              src={site.photo}
              alt={site.name}
              width={200}
              height={200}
              priority
              className="rise rise-2 size-24 shrink-0 rounded-2xl object-cover ring-1 ring-white/20 sm:size-40 lg:size-52"
            />
          ) : null}
        </div>
        <p className="rise rise-3 mt-6 max-w-xl text-[17px] leading-relaxed text-white/80">
          {tx(site.lede, locale)}
        </p>
        <div className="rise rise-3 mt-8 flex flex-wrap items-center gap-3">
          <Link
            href={`/${locale}/match-interpretation`}
            className="inline-flex h-11 items-center gap-2 rounded-full bg-white px-5 text-sm font-medium text-ink transition-colors hover:bg-gold"
          >
            {tx(tabs[1].label, locale)}
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
          <Link
            href={`/${locale}/player-identity`}
            className="inline-flex h-11 items-center rounded-full border border-white/25 px-5 text-sm font-medium text-white transition-colors hover:bg-white/10"
          >
            {tx(tabs[4].label, locale)}
          </Link>
        </div>
      </div>

      <dl className="mx-auto grid max-w-6xl grid-cols-2 gap-x-8 gap-y-5 border-t border-white/10 px-4 py-5 sm:grid-cols-4 sm:px-6">
        {heroFacts.map((fact) => (
          <div key={fact.label.en}>
            <dt className="text-[10px] font-medium tracking-[0.16em] text-gold uppercase">
              {tx(fact.label, locale)}
            </dt>
            <dd className="mt-1 text-sm leading-snug text-white/85">{tx(fact.value, locale)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ContactSection({ locale }: { locale: Locale }) {
  const { email, phone, linkedin, representation } = site.contact;
  const hasDetails = Boolean(email || phone || linkedin || representation);

  return (
    <section id="contact" className="bg-ink text-white">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 sm:py-20 lg:grid-cols-[2fr_3fr]">
        <div>
          <p className="text-[11px] font-medium tracking-[0.18em] text-gold uppercase">
            {tx(contact.kicker, locale)}
          </p>
          <h2 className="mt-2 text-3xl leading-tight sm:text-4xl">{tx(contact.title, locale)}</h2>
          <p className="mt-3 max-w-md text-[15px] leading-relaxed text-white/70">
            {tx(contact.body, locale)}
          </p>
        </div>
        <div className="flex flex-col gap-3">
          {email ? (
            <a
              href={`mailto:${email}`}
              className="flex items-center gap-3 rounded-xl border border-white/10 bg-ink-raised p-4 transition-colors hover:border-gold"
            >
              <Mail className="size-5 text-gold" aria-hidden="true" />
              <span>
                <span className="block text-[10px] tracking-[0.16em] text-white/50 uppercase">
                  {tx(contact.emailLabel, locale)}
                </span>
                <span className="text-[15px]">{email}</span>
              </span>
            </a>
          ) : null}
          {phone ? (
            <a
              href={`tel:${phone.replace(/[^+\d]/g, "")}`}
              className="flex items-center gap-3 rounded-xl border border-white/10 bg-ink-raised p-4 transition-colors hover:border-gold"
            >
              <Phone className="size-5 text-gold" aria-hidden="true" />
              <span>
                <span className="block text-[10px] tracking-[0.16em] text-white/50 uppercase">
                  {tx(contact.phoneLabel, locale)}
                </span>
                <span className="text-[15px]">{phone}</span>
              </span>
            </a>
          ) : null}
          {linkedin ? (
            <a
              href={linkedin}
              className="flex items-center gap-3 rounded-xl border border-white/10 bg-ink-raised p-4 transition-colors hover:border-gold"
            >
              <ArrowUpRight className="size-5 text-gold" aria-hidden="true" />
              <span className="text-[15px]">{tx(contact.linkedinLabel, locale)}</span>
            </a>
          ) : null}
          {representation ? (
            <p className="rounded-xl border border-white/10 bg-ink-raised p-4">
              <span className="block text-[10px] tracking-[0.16em] text-white/50 uppercase">
                {tx(contact.representationLabel, locale)}
              </span>
              <span className="text-[15px]">{representation}</span>
            </p>
          ) : null}
          {!hasDetails ? (
            <p className="rounded-xl border border-dashed border-white/20 p-5 text-[15px] text-white/70">
              {tx(contact.pending, locale)}
            </p>
          ) : null}
          <Link
            href={`/${locale}/cv`}
            className="inline-flex h-11 items-center gap-2 self-start rounded-full border border-white/25 px-5 text-sm font-medium text-white transition-colors hover:bg-white/10"
          >
            <FileText className="size-4" aria-hidden="true" />
            {tx(ui.cv, locale)}
          </Link>
        </div>
      </div>
    </section>
  );
}
