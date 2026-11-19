"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export type TabLink = { id: string; href: string; label: string };

export function TabNav({ tabs, label }: { tabs: TabLink[]; label: string }) {
  const pathname = usePathname();
  const current = pathname.replace(/\/$/, "");

  return (
    <nav aria-label={label} className="scrollbar-none flex gap-2 overflow-x-auto pb-3">
      {tabs.map((tab, index) => {
        const active = index === 0 ? current === tab.href : current.startsWith(tab.href);
        return (
          <Link
            key={tab.id}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`shrink-0 rounded-full px-3.5 py-1.5 text-[13px] font-medium whitespace-nowrap transition-colors ${
              active
                ? "bg-ink text-white"
                : "bg-muted text-foreground hover:bg-line"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
