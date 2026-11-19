import Link from "next/link";
import { LanguageMenu } from "./language-menu";
import { TabNav } from "./tab-nav";
import { tx, type Locale } from "../content/i18n";
import { site } from "../content/profile";
import { tabs, ui } from "../content/ui";

export function SiteHeader({ locale }: { locale: Locale }) {
  const links = tabs.map((tab) => ({
    id: tab.id,
    href: `/${locale}${tab.path}`,
    label: tx(tab.label, locale),
  }));

  return (
    <div className="no-print sticky top-0 z-50 border-b border-line bg-white/95 text-foreground backdrop-blur-md">
      <div className="h-1 bg-gold-deep" />
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-white"
      >
        {tx(ui.skip, locale)}
      </a>
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="flex h-16 items-center justify-between gap-4">
          <Link href={`/${locale}`} className="flex min-w-0 items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-md bg-ink font-heading text-lg leading-none tracking-wide text-white">
              {site.initials}
            </span>
            <span className="min-w-0">
              <span className="block truncate font-heading text-[1.35rem] leading-none tracking-wide text-ink uppercase">
                {site.name}
              </span>
              <span className="mt-1 block truncate text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
                {tx(site.role, locale)}
              </span>
            </span>
          </Link>
          <LanguageMenu locale={locale} label={tx(ui.language, locale)} />
        </div>
        <TabNav tabs={links} label={tx(ui.sections, locale)} />
      </div>
    </div>
  );
}
