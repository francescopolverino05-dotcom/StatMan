/** Shared helpers for StatMan pages. */

export const DEFAULT_COMPETITION_ID = 43;
export const DEFAULT_SEASON_ID = 3;
export const DEFAULT_GAME_ID = 8657;

export function fmt(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(digits);
  }
  return String(value);
}

export async function fetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

export function qs(name, fallback = null) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name) ?? fallback;
}

export function seasonBase(competitionId = DEFAULT_COMPETITION_ID, seasonId = DEFAULT_SEASON_ID) {
  return `/api/seasons/${competitionId}/${seasonId}`;
}
