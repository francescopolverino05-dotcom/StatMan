"use client";

import { useId, useState } from "react";
import { VideoFrame } from "./video-frame";

export type PhaseView = {
  id: string;
  title: string;
  video: string | null;
  videoCaption: string | null;
  moments: { id: string; title: string; notes: string | null }[];
};

export function PhaseTabs({
  phases,
  labels,
}: {
  phases: PhaseView[];
  labels: { clip: string; textToCome: string; videoToCome: string; playVideo: string };
}) {
  const [selected, setSelected] = useState(phases[0].id);
  const baseId = useId();

  return (
    <div>
      <div
        role="tablist"
        className="scrollbar-none flex gap-2 overflow-x-auto pb-1"
        onKeyDown={(event) => {
          if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
          const index = phases.findIndex((phase) => phase.id === selected);
          const step = event.key === "ArrowRight" ? 1 : -1;
          const next = phases[(index + step + phases.length) % phases.length];
          setSelected(next.id);
          document.getElementById(`${baseId}-tab-${next.id}`)?.focus();
        }}
      >
        {phases.map((phase, index) => {
          const active = phase.id === selected;
          return (
            <button
              key={phase.id}
              id={`${baseId}-tab-${phase.id}`}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls={`${baseId}-panel-${phase.id}`}
              tabIndex={active ? 0 : -1}
              onClick={() => setSelected(phase.id)}
              className={`flex shrink-0 cursor-pointer items-baseline gap-2 rounded-full border px-4 py-2 text-sm whitespace-nowrap transition-colors ${
                active
                  ? "border-ink bg-ink text-paper"
                  : "border-line bg-card text-foreground hover:border-gold"
              }`}
            >
              <span className={`text-[11px] ${active ? "text-gold" : "text-gold-deep"}`}>
                0{index + 1}
              </span>
              {phase.title}
            </button>
          );
        })}
      </div>

      {phases.map((phase) => (
        <div
          key={phase.id}
          id={`${baseId}-panel-${phase.id}`}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${phase.id}`}
          hidden={phase.id !== selected}
          className="mt-8 grid gap-8 lg:grid-cols-[5fr_6fr]"
        >
          <div>
            <h2 className="text-3xl text-foreground">{phase.title}</h2>
            <ol className="mt-6 space-y-3">
              {phase.moments.map((moment, index) => (
                <li key={moment.id} className="rounded-xl border border-line bg-card p-5">
                  <p className="text-[11px] font-medium tracking-[0.18em] text-gold-deep">
                    0{index + 1}
                  </p>
                  <h3 className="mt-1.5 text-xl text-foreground">{moment.title}</h3>
                  {moment.notes ? (
                    <p className="mt-2 text-[15px] leading-relaxed whitespace-pre-line text-muted-foreground">
                      {moment.notes}
                    </p>
                  ) : (
                    <p className="mt-3 inline-flex rounded-md border border-dashed border-line px-2.5 py-1.5 text-[13px] text-muted-foreground">
                      {labels.textToCome}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </div>
          <figure className="lg:sticky lg:top-32 lg:self-start">
            <p className="mb-3 text-[11px] font-medium tracking-[0.18em] text-gold-deep uppercase">
              {labels.clip} · {phase.title}
            </p>
            <VideoFrame
              link={phase.video}
              title={`${labels.clip}: ${phase.title}`}
              emptyLabel={labels.videoToCome}
              playLabel={labels.playVideo}
            />
            {phase.videoCaption ? (
              <figcaption className="mt-3 text-sm leading-relaxed text-muted-foreground">
                {phase.videoCaption}
              </figcaption>
            ) : null}
          </figure>
        </div>
      ))}
    </div>
  );
}
