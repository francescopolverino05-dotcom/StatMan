"use client";

import { useState } from "react";

export type RoleView = {
  id: string;
  title: string;
  spots: { x: number; y: number }[];
  facets: { label: string; text: string | null }[];
};

const PITCH = { width: 300, height: 420 };

export function IdentityBoard({
  roles,
  labels,
}: {
  roles: RoleView[];
  labels: { pick: string; textToCome: string; formation: string };
}) {
  const [selected, setSelected] = useState(roles[0].id);
  const role = roles.find((item) => item.id === selected) ?? roles[0];
  const roleNumber = roles.indexOf(role) + 1;

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,22rem)_1fr] lg:gap-12">
      <div>
        <div className="rounded-2xl bg-ink p-4">
          <p className="mb-3 flex items-center justify-between text-[11px] font-medium tracking-[0.18em] text-gold uppercase">
            <span>{labels.pick}</span>
            <span className="text-white/60">{labels.formation}</span>
          </p>
          <svg
            viewBox={`0 0 ${PITCH.width} ${PITCH.height}`}
            className="w-full"
            role="group"
            aria-label={labels.pick}
          >
            <g fill="none" stroke="rgb(255 255 255 / 0.22)" strokeWidth="1.2">
              <rect x="8" y="8" width="284" height="404" rx="3" />
              <path d="M8 210h284" />
              <circle cx="150" cy="210" r="34" />
              <rect x="80" y="8" width="140" height="58" />
              <rect x="115" y="8" width="70" height="22" />
              <rect x="80" y="354" width="140" height="58" />
              <rect x="115" y="390" width="70" height="22" />
              <path d="M122 66a30 30 0 0 0 56 0M122 354a30 30 0 0 1 56 0" />
            </g>
            {roles.map((item, index) =>
              item.spots.map((spot, spotIndex) => {
                const active = item.id === selected;
                const cx = (spot.x / 100) * PITCH.width;
                const cy = (spot.y / 100) * PITCH.height;
                return (
                  <g
                    key={`${item.id}-${spotIndex}`}
                    role="button"
                    tabIndex={spotIndex === 0 ? 0 : -1}
                    aria-label={item.title}
                    aria-pressed={active}
                    className="cursor-pointer outline-none"
                    onClick={() => setSelected(item.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelected(item.id);
                      }
                    }}
                  >
                    <circle cx={cx} cy={cy} r="24" fill="transparent" />
                    {active ? (
                      <circle cx={cx} cy={cy} r="22" fill="#ffe14a" opacity="0.35" />
                    ) : null}
                    <circle
                      cx={cx}
                      cy={cy}
                      r={active ? 16 : 12}
                      fill={active ? "#ffe14a" : "rgb(255 255 255 / 0.14)"}
                      stroke={active ? "#fff6c2" : "rgb(255 255 255 / 0.55)"}
                      strokeWidth={active ? 2.5 : 1.25}
                    />
                    <text
                      x={cx}
                      y={cy + 4}
                      textAnchor="middle"
                      fontSize="12"
                      fontWeight="700"
                      fill={active ? "#071522" : "rgb(255 255 255 / 0.9)"}
                      style={{ pointerEvents: "none" }}
                    >
                      {index + 1}
                    </text>
                  </g>
                );
              }),
            )}
          </svg>
        </div>

        <ul className="mt-4 flex flex-wrap gap-2">
          {roles.map((item, index) => {
            const active = item.id === selected;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => setSelected(item.id)}
                  className={`flex cursor-pointer items-baseline gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors ${
                    active
                      ? "border-[#e6c200] bg-[#ffe14a] text-ink"
                      : "border-line bg-card text-foreground hover:border-[#e6c200]"
                  }`}
                >
                  <span className={`text-[11px] ${active ? "text-ink" : "text-gold-deep"}`}>
                    {index + 1}
                  </span>
                  {item.title}
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <div aria-live="polite">
        <div className="dossier-rule pt-5">
          <p className="text-[11px] font-medium tracking-[0.18em] text-gold-deep uppercase">
            0{roleNumber}
          </p>
          <h2 className="mt-2 text-3xl leading-tight text-foreground sm:text-4xl">{role.title}</h2>
        </div>
        <dl className="mt-8 space-y-4">
          {role.facets.map((facet) => (
            <div key={facet.label} className="rounded-xl border border-line bg-card p-5">
              <dt className="text-[11px] font-medium tracking-[0.16em] text-gold-deep uppercase">
                {facet.label}
              </dt>
              <dd className="mt-2">
                {facet.text ? (
                  <p className="text-[15px] leading-relaxed whitespace-pre-line text-foreground">
                    {facet.text}
                  </p>
                ) : (
                  <p className="inline-flex rounded-md border border-dashed border-line px-2.5 py-1.5 text-[13px] text-muted-foreground">
                    {labels.textToCome}
                  </p>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
