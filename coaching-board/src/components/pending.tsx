import { PenLine } from "lucide-react";
import { tx, type Locale } from "../content/i18n";
import { ui } from "../content/ui";

/** Stands in for a paragraph Antonio has not written yet. */
export function Pending({ locale, className = "" }: { locale: Locale; className?: string }) {
  return (
    <p
      className={`inline-flex items-center gap-2 rounded-md border border-dashed border-line px-2.5 py-1.5 text-[13px] text-muted-foreground ${className}`}
    >
      <PenLine className="size-3.5 shrink-0 text-gold-deep" aria-hidden="true" />
      {tx(ui.textToCome, locale)}
    </p>
  );
}
