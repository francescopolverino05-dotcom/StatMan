import type { Metadata } from "next";
import { Barlow_Condensed, Outfit } from "next/font/google";
import { notFound } from "next/navigation";
import { SiteFooter } from "../../components/site-footer";
import { SiteHeader } from "../../components/site-header";
import { isLocale, locales, tx } from "../../content/i18n";
import { site } from "../../content/profile";
import "../globals.css";

const display = Barlow_Condensed({
  variable: "--font-display",
  subsets: ["latin", "latin-ext"],
  weight: ["500", "600"],
});

const sans = Outfit({
  variable: "--font-outfit",
  subsets: ["latin", "latin-ext"],
});

export function generateStaticParams() {
  return locales.map((item) => ({ locale: item.code }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: {
      default: `${site.name} — ${tx(site.role, locale)}`,
      template: `%s · ${site.name}`,
    },
    description: tx(site.role, locale),
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  return (
    <html lang={locale} className={`${display.variable} ${sans.variable} h-full`}>
      <body className="flex min-h-full flex-col">
        <SiteHeader locale={locale} />
        <main id="content" className="flex-1">
          {children}
        </main>
        <SiteFooter locale={locale} />
      </body>
    </html>
  );
}
