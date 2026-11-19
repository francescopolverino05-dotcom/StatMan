import { Hourglass } from "lucide-react";
import { tx, type Locale } from "../content/i18n";
import { site } from "../content/profile";
import { ui } from "../content/ui";

/** Opens a coaching tab on the light page, with the pitch reserved for the work itself. */
export function PageIntro({
  locale,
  title,
  intro,
  aside,
}: {
  locale: Locale;
  title: string;
  intro: string;
  aside?: React.ReactNode;
}) {
  return (
    <section className="border-b border-line bg-white">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-14">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="rise max-w-3xl">
            <p className="font-heading text-sm tracking-[0.22em] text-gold-deep uppercase">
              {site.name}
            </p>
            <h1 className="mt-3 text-5xl text-ink sm:text-6xl">{title}</h1>
            <p className="mt-4 max-w-2xl text-[17px] leading-relaxed text-muted-foreground">
              {intro}
            </p>
          </div>
          {aside ? <div className="rise rise-2 shrink-0">{aside}</div> : null}
        </div>
        {site.inPreparation ? (
          <p className="rise rise-3 mt-8 inline-flex items-start gap-2.5 rounded-lg border border-gold-deep/25 bg-muted px-3.5 py-2.5 text-sm text-foreground">
            <Hourglass className="mt-0.5 size-4 shrink-0 text-gold-deep" aria-hidden="true" />
            <span>
              <strong className="font-medium text-gold-deep">
                {tx(ui.inPreparationTitle, locale)}.
              </strong>{" "}
              {tx(ui.inPreparationBody, locale)}
            </span>
          </p>
        ) : null}
      </div>
    </section>
  );
}
