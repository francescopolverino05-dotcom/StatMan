export type VideoSource =
  | { kind: "embed"; src: string }
  | { kind: "file"; src: string };

/**
 * Turns the link written in the content file into something playable.
 * Accepts Vimeo and YouTube page links, and files under /public (mp4, webm, mov).
 */
export function resolveVideo(link: string | null | undefined): VideoSource | null {
  const value = link?.trim();
  if (!value) return null;

  if (value.startsWith("/")) {
    return /\.(mp4|webm|mov|m4v)$/i.test(value) ? { kind: "file", src: value } : null;
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== "https:") return null;

  const host = url.hostname.replace(/^www\./, "");
  const parts = url.pathname.split("/").filter(Boolean);

  if (host === "vimeo.com") {
    const index = parts.findIndex((part) => /^\d+$/.test(part));
    if (index === -1) return null;
    const id = parts[index];
    const hash = parts[index + 1] ?? url.searchParams.get("h");
    const query = new URLSearchParams({ dnt: "1", title: "0", byline: "0", portrait: "0" });
    if (hash && /^[a-z0-9]+$/i.test(hash)) query.set("h", hash);
    return { kind: "embed", src: `https://player.vimeo.com/video/${id}?${query}` };
  }

  if (host === "player.vimeo.com" && parts[0] === "video" && /^\d+$/.test(parts[1] ?? "")) {
    const query = new URLSearchParams({ dnt: "1", title: "0", byline: "0", portrait: "0" });
    const hash = url.searchParams.get("h");
    if (hash && /^[a-z0-9]+$/i.test(hash)) query.set("h", hash);
    return { kind: "embed", src: `https://player.vimeo.com/video/${parts[1]}?${query}` };
  }

  let youtubeId: string | null = null;
  if (host === "youtu.be") {
    youtubeId = parts[0] ?? null;
  } else if (host === "youtube.com" || host === "m.youtube.com" || host === "youtube-nocookie.com") {
    if (parts[0] === "watch") youtubeId = url.searchParams.get("v");
    else if (parts[0] === "embed" || parts[0] === "shorts" || parts[0] === "live") {
      youtubeId = parts[1] ?? null;
    }
  }
  if (youtubeId && /^[\w-]{6,}$/.test(youtubeId)) {
    return {
      kind: "embed",
      src: `https://www.youtube-nocookie.com/embed/${youtubeId}?rel=0`,
    };
  }

  return null;
}
