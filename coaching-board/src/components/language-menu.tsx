"use client";

import { Globe } from "lucide-react";
import { usePathname } from "next/navigation";
import { locales, type Locale } from "../content/i18n";

export function LanguageMenu({ locale, label }: { locale: Locale; label: string }) {
  const pathname = usePathname();
  const rest = pathname.split("/").slice(2).join("/");

  return (
    <details className="language-menu relative">
      <summary
        aria-label={label}
        className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-full border border-line bg-white px-3 text-[11px] font-medium tracking-wide text-foreground hover:bg-muted"
      >
        <Globe className="size-3.5" aria-hidden="true" />
        <span className="uppercase">{locale}</span>
      </summary>
      <div className="absolute right-0 z-[80] mt-2 w-52 overflow-hidden rounded-lg border border-line bg-card py-1 text-foreground shadow-lg">
        <p className="px-3 py-1.5 text-[11px] tracking-wide text-muted-foreground uppercase">
          {label}
        </p>
        {locales.map((item) => (
          <a
            key={item.code}
            href={`/${item.code}${rest ? `/${rest}` : ""}`}
            hrefLang={item.code}
            lang={item.code}
            aria-current={item.code === locale ? "true" : undefined}
            className={`flex items-center justify-between gap-4 px-3 py-2 text-sm hover:bg-muted ${
              item.code === locale ? "bg-muted" : ""
            }`}
          >
            <span>{item.label}</span>
            <span className="text-[10px] tracking-wider text-muted-foreground uppercase">
              {item.code}
            </span>
          </a>
        ))}
      </div>
    </details>
  );
}
