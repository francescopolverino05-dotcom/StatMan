import { tx, type Locale } from "../content/i18n";
import { site } from "../content/profile";

export function SiteFooter({ locale }: { locale: Locale }) {
  return (
    <footer className="no-print border-t border-line bg-background">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-8 text-[13px] text-muted-foreground sm:flex-row sm:items-start sm:justify-between sm:px-6">
        <div>
          <p className="font-heading text-base text-foreground">{site.name}</p>
        </div>
        <div className="sm:text-right">
          <p>© {new Date().getFullYear()} {site.name}</p>
          <p className="mt-1">
            <a
              href={site.credit.href}
              className="underline decoration-line underline-offset-4 hover:text-foreground"
            >
              {tx(site.credit.label, locale)}
            </a>
          </p>
        </div>
      </div>
    </footer>
  );
}
