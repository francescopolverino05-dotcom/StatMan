export const locales = [
  { code: "en", label: "English" },
  { code: "it", label: "Italiano" },
  { code: "es", label: "Español" },
  { code: "pt", label: "Português" },
  { code: "fr", label: "Français" },
] as const;

export type Locale = (typeof locales)[number]["code"];

export const defaultLocale: Locale = "en";

export type Copy = Record<Locale, string>;

/** One string in every site language, always in this order: en, it, es, pt, fr. */
export function c(en: string, it: string, es: string, pt: string, fr: string): Copy {
  return { en, it, es, pt, fr };
}

export function tx(copy: Copy, locale: Locale): string {
  return copy[locale] ?? copy[defaultLocale];
}

export function isLocale(value: unknown): value is Locale {
  return (
    typeof value === "string" && locales.some((item) => item.code === value)
  );
}

/** Picks the first site language named in an Accept-Language header. */
export function negotiateLocale(header: string | null): Locale {
  if (!header) return defaultLocale;
  const wanted = header
    .split(",")
    .map((part) => {
      const [tag, q] = part.trim().split(";q=");
      return { tag: tag.toLowerCase().split("-")[0], q: q ? Number(q) : 1 };
    })
    .filter((item) => !Number.isNaN(item.q))
    .sort((a, b) => b.q - a.q);
  for (const item of wanted) {
    if (isLocale(item.tag)) return item.tag;
  }
  return defaultLocale;
}
