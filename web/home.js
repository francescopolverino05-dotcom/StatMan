import { fetchJson } from "./common.js";
import { mountAppNav } from "./app-shell.js";

mountAppNav({ active: "home" });

const listEl = document.getElementById("match-list");
const emptyEl = document.getElementById("match-empty");
const statusEl = document.getElementById("home-status");

function setStatus(text, { error = false } = {}) {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.classList.toggle("is-error", error);
}

function phaseLabel(pack) {
  const phase = pack.phase || pack.status || "";
  if (String(phase).includes("phase10") || pack.status === "phase10_ready") {
    return "Board ready";
  }
  if (pack.pipeline?.status === "running" || pack.pipeline?.status === "queued") {
    return "Analyzing…";
  }
  if (pack.sheet) return pack.status || "In progress";
  if (pack.video?.status === "ready") return "Video ready";
  if (pack.facts) return "Facts saved";
  return pack.status || "Draft";
}

function renderPacks(packs) {
  if (!listEl || !emptyEl) return;
  if (!packs.length) {
    listEl.hidden = true;
    listEl.innerHTML = "";
    emptyEl.hidden = false;
    return;
  }
  emptyEl.hidden = true;
  listEl.hidden = false;
  listEl.innerHTML = packs
    .map((p) => {
      const title = p.title || "Untitled match";
      const vid = p.video?.status === "ready" ? "Video" : "No video";
      const when = p.updated_at
        ? new Date(p.updated_at * 1000).toLocaleString(undefined, {
            dateStyle: "medium",
            timeStyle: "short",
          })
        : "";
      return `
        <li>
          <a class="match-list__row" href="/match?pack=${encodeURIComponent(p.pack_id)}">
            <span class="match-list__title">${title}</span>
            <span class="match-list__meta">${phaseLabel(p)} · ${vid}${when ? ` · ${when}` : ""}</span>
          </a>
        </li>`;
    })
    .join("");
}

async function load() {
  setStatus("Loading matches…");
  try {
    const data = await fetchJson("/api/match-packs?limit=24");
    renderPacks(data.packs || []);
    setStatus("");
  } catch (err) {
    setStatus(err.message || "Could not load matches", { error: true });
    renderPacks([]);
  }
}

load();
