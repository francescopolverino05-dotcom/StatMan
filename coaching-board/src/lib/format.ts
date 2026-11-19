import { tx, type Locale } from "../content/i18n";
import { ui } from "../content/ui";

const intlLocale: Record<Locale, string> = {
  en: "en-GB",
  it: "it-IT",
  es: "es-ES",
  pt: "pt-PT",
  fr: "fr-FR",
};

function parse(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

export function monthYear(iso: string, locale: Locale): string {
  return new Intl.DateTimeFormat(intlLocale[locale], {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(parse(iso));
}

/** Time in a role, rounded to the nearest month: "2 years 5 months". */
export function timeInRole(start: string, end: string, locale: Locale): string {
  const days = (parse(end).getTime() - parse(start).getTime()) / 86_400_000;
  const total = Math.max(1, Math.round(days / 30.4375));
  const years = Math.floor(total / 12);
  const months = total % 12;
  const parts: string[] = [];
  if (years > 0) {
    parts.push(`${years} ${tx(years === 1 ? ui.year : ui.years, locale)}`);
  }
  if (months > 0) {
    parts.push(`${months} ${tx(months === 1 ? ui.month : ui.months, locale)}`);
  }
  return parts.join(" ");
}
