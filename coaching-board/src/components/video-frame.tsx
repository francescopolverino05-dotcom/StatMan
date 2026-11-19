"use client";

import { Clapperboard, Play } from "lucide-react";
import { useState } from "react";
import { resolveVideo } from "../lib/video";

/**
 * One 16:9 video slot. With no link it shows an empty frame; with a Vimeo or
 * YouTube link the player loads only after the visitor presses play.
 */
export function VideoFrame({
  link,
  title,
  emptyLabel,
  playLabel,
}: {
  link: string | null;
  title: string;
  emptyLabel: string;
  playLabel: string;
}) {
  const [playing, setPlaying] = useState(false);
  const video = resolveVideo(link);

  if (!video) {
    return (
      <div className="pitch-grid flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-white/20 bg-ink text-white/60">
        <Clapperboard className="size-6 text-gold/80" aria-hidden="true" />
        <p className="text-[13px] tracking-wide">{emptyLabel}</p>
      </div>
    );
  }

  if (video.kind === "file") {
    return (
      <video
        className="aspect-video w-full rounded-lg bg-ink"
        controls
        playsInline
        preload="metadata"
        aria-label={title}
      >
        <source src={video.src} />
      </video>
    );
  }

  if (!playing) {
    return (
      <button
        type="button"
        onClick={() => setPlaying(true)}
        className="pitch-grid group flex aspect-video w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-lg bg-ink text-white"
      >
        <span className="flex size-14 items-center justify-center rounded-full bg-gold text-ink transition-transform group-hover:scale-105">
          <Play className="size-6 translate-x-0.5" aria-hidden="true" />
        </span>
        <span className="text-[13px] tracking-wide text-white/80">
          {playLabel}
          <span className="sr-only">: {title}</span>
        </span>
      </button>
    );
  }

  const separator = video.src.includes("?") ? "&" : "?";
  return (
    <iframe
      className="aspect-video w-full rounded-lg bg-ink"
      src={`${video.src}${separator}autoplay=1`}
      title={title}
      allow="autoplay; fullscreen; picture-in-picture"
      allowFullScreen
      referrerPolicy="strict-origin-when-cross-origin"
    />
  );
}
