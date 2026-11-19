"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { defaultLocale, isLocale, tx } from "../../content/i18n";
import { ui } from "../../content/ui";

export default function NotFound() {
  const params = useParams<{ locale?: string }>();
  const locale = isLocale(params.locale) ? params.locale : defaultLocale;

  return (
    <section className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
      <p className="text-[11px] font-medium tracking-[0.18em] text-gold-deep uppercase">404</p>
      <h1 className="mt-3 max-w-xl text-4xl leading-tight">{tx(ui.notFoundTitle, locale)}</h1>
      <p className="mt-4 max-w-md text-muted-foreground">{tx(ui.notFoundBody, locale)}</p>
      <Link
        href={`/${locale}`}
        className="mt-8 inline-flex h-10 items-center rounded-full bg-ink px-4 text-sm font-medium text-paper hover:bg-navy"
      >
        {tx(ui.notFoundAction, locale)}
      </Link>
    </section>
  );
}
