"use client";

import { Printer } from "lucide-react";

export function PrintButton({ label }: { label: string }) {
  return (
    <button
      type="button"
      onClick={() => window.print()}
      className="inline-flex h-10 cursor-pointer items-center gap-2 rounded-full bg-ink px-4 text-sm font-medium text-paper transition-colors hover:bg-navy"
    >
      <Printer className="size-4" aria-hidden="true" />
      {label}
    </button>
  );
}
