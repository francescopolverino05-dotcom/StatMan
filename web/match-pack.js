import { fetchJson, fmt, renderTeamCatalogHtml } from "./common.js";

const createForm = document.getElementById("create-form");
const homeTeam = document.getElementById("home-team");
const awayTeam = document.getElementById("away-team");
const packIdLine = document.getElementById("pack-id-line");
const packIdEl = document.getElementById("pack-id");
const factsJson = document.getElementById("facts-json");
const factsFile = document.getElementById("facts-file");
const uploadFactsFile = document.getElementById("upload-facts-file");
const loadExample = document.getElementById("load-example");
const saveFacts = document.getElementById("save-facts");
const formationHome = document.getElementById("formation-home");
const formationAway = document.getElementById("formation-away");
const uploadFormations = document.getElementById("upload-formations");
const videoForm = document.getElementById("video-form");
const videoInput = document.getElementById("video-input");
const videoLabel = document.getElementById("video-label");
const videoProgressWrap = document.getElementById("video-progress-wrap");
const videoProgressFill = document.getElementById("video-progress-fill");
const videoProgressText = document.getElementById("video-progress-text");
const computeBtn = document.getElementById("compute-btn");
const statusEl = document.getElementById("status");
const factsStatusEl = document.getElementById("facts-status");
const results = document.getElementById("results");
const scoreline = document.getElementById("scoreline");
const matchMeta = document.getElementById("match-meta");
const coverageBanner = document.getElementById("coverage-banner");
const teamBoard = document.getElementById("team-board");
const eventsBody = document.querySelector("#events-table tbody");
const lineupBody = document.querySelector("#lineup-table tbody");
const packsBody = document.querySelector("#packs-table tbody");

let activePackId = null;

function setStatus(text, { error = false, loading = false, near = "both" } = {}) {
  const targets = [];
  if (near === "facts" || near === "both") {
    if (factsStatusEl) targets.push(factsStatusEl);
  }
  if (near === "compute" || near === "both") {
    if (statusEl) targets.push(statusEl);
  }
  // Always keep the compute-area status in sync for screen readers / scroll.
  if (!targets.length && statusEl) targets.push(statusEl);
  for (const el of targets) {
    el.textContent = text;
    el.classList.toggle("is-error", error);
    el.classList.toggle("is-loading", loading);
  }
}

async function computeSheet(id) {
  const pack = await fetchJson(`/api/match-packs/${id}/compute`, { method: "POST" });
  renderSheet(pack);
  return pack;
}

function setPackId(id) {
  activePackId = id;
  packIdEl.textContent = id;
  packIdLine.hidden = !id;
}

function fmtBytes(n) {
  if (n == null) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${Math.round(n / 1e3)} KB`;
}

function requirePack() {
  if (!activePackId) {
    throw new Error("Create a match pack first.");
  }
  return activePackId;
}

async function refreshPacks() {
  const data = await fetchJson("/api/match-packs?limit=12");
  packsBody.innerHTML = (data.packs || [])
    .map((p) => {
      const vid = p.video?.status || "—";
      return `
      <tr data-pack="${p.pack_id}" class="job-row">
        <td><code>${p.pack_id}</code></td>
        <td>${p.title || "—"}</td>
        <td>${p.status || "—"}</td>
        <td>${vid}</td>
      </tr>`;
    })
    .join("");
  for (const row of packsBody.querySelectorAll(".job-row")) {
    row.addEventListener("click", () => openPack(row.dataset.pack));
  }
}

async function openPack(packId) {
  setStatus(`Loading pack ${packId}…`, { loading: true });
  try {
    const pack = await fetchJson(`/api/match-packs/${packId}`);
    setPackId(pack.pack_id);
    if (pack.facts) {
      factsJson.value = JSON.stringify(pack.facts, null, 2);
    }
    if (pack.sheet) {
      renderSheet(pack);
      setStatus(`Loaded pack ${packId} (sheet ready).`);
    } else {
      results.hidden = true;
      setStatus(`Loaded pack ${packId} — save facts and compute when ready.`);
    }
  } catch (err) {
    setStatus(err.message, { error: true });
  }
}

function renderSheet(pack) {
  const sheet = pack.sheet;
  if (!sheet) return;
  results.hidden = false;
  const m = sheet.match || {};
  scoreline.textContent = `${m.home_team} ${m.home_score}–${m.away_score} ${m.away_team}`;
  matchMeta.textContent = [
    m.competition,
    m.kickoff,
    m.home_formation && m.away_formation
      ? `${m.home_formation} vs ${m.away_formation}`
      : null,
    sheet.source?.phase,
  ]
    .filter(Boolean)
    .join(" · ");

  const cov = sheet.source?.coverage || pack.coverage || {};
  const factList = (cov.fact || []).join(", ") || "—";
  const missing = (cov.missing_optional || []).join(", ");
  const pending = (cov.pending_later_phases || []).slice(0, 8).join(", ");
  const counts = cov.fact_event_counts || {};
  coverageBanner.innerHTML = `
    <strong>Phase 1 — filled from your JSON:</strong> ${factList}
    (${counts.goals ?? 0} goals, ${counts.cards ?? 0} cards, ${counts.substitutions ?? 0} subs).
    Scroll to <em>Fact events</em> and <em>Lineups</em> below for the full list.
    <br /><strong>Blank (—) on purpose:</strong>
    ${missing ? `not in your JSON yet (${missing}); ` : ""}
    later video phases (${pending}${
      (cov.pending_later_phases || []).length > 8 ? "…" : ""
    }).
  `;

  const teams = sheet.teams || [];
  const home = teams[0];
  const away = teams[1];
  teamBoard.innerHTML = `
    ${home ? renderTeamCatalogHtml(home, "Home", { showFormation: true }) : ""}
    <div class="score-stack">
      <div class="score">${m.home_score}–${m.away_score}</div>
      <div class="vs">fact sheet</div>
    </div>
    ${away ? renderTeamCatalogHtml(away, "Away", { showFormation: true }) : ""}
  `;

  const events = sheet.events || [];
  eventsBody.innerHTML = events
    .map((e) => {
      let detail = e.player_name || "";
      if (e.type === "substitution") {
        detail = `${e.player_out} → ${e.player_in}`;
      } else if (e.assist_name) {
        detail = `${detail} (A: ${e.assist_name})`;
      }
      return `
      <tr>
        <td>${fmt(e.minute, 0)}'</td>
        <td>${e.type}</td>
        <td>${e.team}</td>
        <td>${detail || "—"}</td>
      </tr>`;
    })
    .join("");

  lineupBody.innerHTML = (sheet.players || [])
    .map(
      (p) => `
    <tr>
      <td>${p.player_name}</td>
      <td>${p.team_name}</td>
      <td>${p.jersey ?? "—"}</td>
      <td>${p.position || "—"}</td>
      <td>${fmt(p.goals, 0)}</td>
      <td>${fmt(p.yellow_cards, 0)}</td>
      <td>${fmt(p.red_cards, 0)}</td>
    </tr>`
    )
    .join("");

  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

createForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  setStatus("Creating pack…", { loading: true });
  try {
    const body = new FormData();
    if (homeTeam.value) body.append("home_team", homeTeam.value);
    if (awayTeam.value) body.append("away_team", awayTeam.value);
    const pack = await fetchJson("/api/match-packs", { method: "POST", body });
    setPackId(pack.pack_id);
    // Do not clobber an example / draft already in the editor.
    if (pack.facts && !factsJson.value.trim()) {
      factsJson.value = JSON.stringify(pack.facts, null, 2);
    }
    setStatus(`Created pack ${pack.pack_id}. Save facts next.`);
    await refreshPacks();
  } catch (err) {
    setStatus(err.message, { error: true });
  }
});

loadExample.addEventListener("click", async () => {
  setStatus("Loading example facts…", { loading: true });
  try {
    const ex = await fetchJson("/api/match-packs/example-facts");
    factsJson.value = JSON.stringify(ex, null, 2);
    homeTeam.value = ex.home?.team_name || "";
    awayTeam.value = ex.away?.team_name || "";
    setStatus("Example loaded — create a pack (if needed) then Save facts.");
  } catch (err) {
    setStatus(err.message, { error: true });
  }
});

function stripBom(text) {
  return text.replace(/^\uFEFF/, "");
}

async function readFactsFileAsText(file) {
  const buf = await file.arrayBuffer();
  // Prefer UTF-8 with BOM strip; fall back if decode throws.
  try {
    return stripBom(new TextDecoder("utf-8").decode(buf));
  } catch {
    return stripBom(await file.text());
  }
}

factsFile?.addEventListener("change", async () => {
  const file = factsFile.files?.[0];
  if (!file) return;
  try {
    const text = await readFactsFileAsText(file);
    // Preview in editor only — does not save until Upload / Save.
    JSON.parse(stripBom(text));
    factsJson.value = JSON.stringify(JSON.parse(stripBom(text)), null, 2);
    setStatus(`Loaded ${file.name} into the editor. Click “Upload JSON file” or Save facts.`);
  } catch (err) {
    setStatus(`Could not read ${file.name}: ${err.message}`, { error: true });
    // Clear the broken selection so the same file can be re-chosen after a fix.
    factsFile.value = "";
  }
});

uploadFactsFile?.addEventListener("click", async () => {
  setStatus("Uploading facts JSON…", { loading: true });
  try {
    const id = requirePack();
    const file = factsFile.files?.[0];
    if (!file) {
      // Allow upload from editor contents as a synthetic file.
      if (!factsJson.value.trim()) {
        throw new Error("Choose a .json facts file, or paste JSON then Save facts.");
      }
      // Validate locally first so we never POST garbage that looks like a drop.
      JSON.parse(stripBom(factsJson.value));
      const pack = await fetchJson(`/api/match-packs/${id}/facts`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: stripBom(factsJson.value),
      });
      factsJson.value = JSON.stringify(pack.facts, null, 2);
      homeTeam.value = pack.facts?.home?.team_name || homeTeam.value;
      awayTeam.value = pack.facts?.away?.team_name || awayTeam.value;
      setStatus("Facts saved from editor.");
      await refreshPacks();
      return;
    }
    const body = new FormData();
    body.append("file", file, file.name.endsWith(".json") ? file.name : `${file.name}.json`);
    const pack = await fetchJson(`/api/match-packs/${id}/facts/file`, {
      method: "POST",
      body,
    });
    factsJson.value = JSON.stringify(pack.facts, null, 2);
    homeTeam.value = pack.facts?.home?.team_name || homeTeam.value;
    awayTeam.value = pack.facts?.away?.team_name || awayTeam.value;
    setStatus(`Uploaded ${file.name} — facts ready (score ${pack.facts?.home?.team_name} facts saved).`);
    await refreshPacks();
  } catch (err) {
    setStatus(err.message, { error: true });
  }
});

saveFacts.addEventListener("click", async () => {
  setStatus("Saving facts…", { loading: true, near: "facts" });
  try {
    const id = requirePack();
    let payload;
    try {
      payload = JSON.parse(stripBom(factsJson.value));
    } catch (err) {
      throw new Error(`Facts JSON is invalid: ${err.message}`);
    }
    const pack = await fetchJson(`/api/match-packs/${id}/facts`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    factsJson.value = JSON.stringify(pack.facts, null, 2);
    homeTeam.value = pack.facts?.home?.team_name || homeTeam.value;
    awayTeam.value = pack.facts?.away?.team_name || awayTeam.value;
    setStatus("Facts saved — computing sheet…", { loading: true, near: "facts" });
    const computed = await computeSheet(id);
    const m = computed.sheet?.match || {};
    setStatus(
      `Facts saved. Sheet ready: ${m.home_team || "Home"} ${m.home_score ?? "?"}–${m.away_score ?? "?"} ${m.away_team || "Away"}.`,
      { near: "both" }
    );
    await refreshPacks();
  } catch (err) {
    setStatus(err.message, { error: true, near: "facts" });
  }
});

uploadFormations.addEventListener("click", async () => {
  setStatus("Uploading formation PDFs…", { loading: true });
  try {
    const id = requirePack();
    for (const [side, input] of [
      ["home", formationHome],
      ["away", formationAway],
    ]) {
      const file = input.files?.[0];
      if (!file) continue;
      const body = new FormData();
      body.append("side", side);
      body.append("file", file);
      await fetchJson(`/api/match-packs/${id}/formation`, { method: "POST", body });
    }
    setStatus("Formation PDF(s) stored (text extracted when possible).");
    await refreshPacks();
  } catch (err) {
    setStatus(err.message, { error: true });
  }
});

videoInput.addEventListener("change", () => {
  const file = videoInput.files?.[0];
  if (!file) {
    videoLabel.textContent = "Choose full-match video (optional in Phase 1)…";
    return;
  }
  videoLabel.textContent = `${file.name} (${fmtBytes(file.size)})`;
});

async function putChunk(packId, offset, blob, attempt = 1) {
  const res = await fetch(
    `/api/match-packs/${packId}/video/chunk?offset=${offset}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/octet-stream" },
      body: blob,
    }
  );
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    if (attempt < 5 && res.status >= 500) {
      await new Promise((r) => setTimeout(r, 400 * attempt));
      return putChunk(packId, offset, blob, attempt + 1);
    }
    throw new Error(detail);
  }
  return res.json();
}

videoForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = videoInput.files?.[0];
  if (!file) {
    setStatus("Choose a video file first (or skip — facts-only works in Phase 1).", {
      error: true,
    });
    return;
  }
  if (file.size > 4 * 1024 * 1024 * 1024) {
    setStatus("File exceeds 4 GB. Use 720p H.264 (~1–2 GB).", { error: true });
    return;
  }
  setStatus("Uploading video in chunks…", { loading: true });
  videoProgressWrap.hidden = false;
  try {
    const id = requirePack();
    const initBody = new FormData();
    initBody.append("filename", file.name);
    initBody.append("size_bytes", String(file.size));
    const init = await fetchJson(`/api/match-packs/${id}/video/init`, {
      method: "POST",
      body: initBody,
    });
    const chunkSize = init.video?.chunk_bytes || 8 * 1024 * 1024;
    let offset = init.video?.bytes_received || 0;
    while (offset < file.size) {
      const end = Math.min(offset + chunkSize, file.size);
      const meta = await putChunk(id, offset, file.slice(offset, end));
      offset = meta.video?.bytes_received || end;
      const pct = meta.video?.upload_pct ?? Math.round((100 * offset) / file.size);
      videoProgressFill.style.width = `${pct}%`;
      videoProgressText.textContent = `uploading · ${pct}% · ${fmtBytes(offset)} / ${fmtBytes(file.size)}`;
      setStatus(`Uploading video… ${pct}%`, { loading: true });
    }
    await fetchJson(`/api/match-packs/${id}/video/finish`, { method: "POST" });
    videoProgressText.textContent = "video ready";
    setStatus("Video attached to pack.");
    await refreshPacks();
  } catch (err) {
    setStatus(err.message, { error: true });
  }
});

computeBtn.addEventListener("click", async () => {
  setStatus("Computing fact-sourced sheet…", { loading: true, near: "compute" });
  try {
    const id = requirePack();
    // Auto-save facts from editor if present.
    if (factsJson.value.trim()) {
      const payload = JSON.parse(stripBom(factsJson.value));
      await fetchJson(`/api/match-packs/${id}/facts`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    const pack = await computeSheet(id);
    const m = pack.sheet?.match || {};
    setStatus(
      `Fact-sourced sheet ready: ${m.home_score ?? "?"}–${m.away_score ?? "?"}. Dashes (—) for possession/xG/shots are normal in Phase 1.`,
      { near: "both" }
    );
    await refreshPacks();
  } catch (err) {
    setStatus(err.message, { error: true, near: "compute" });
  }
});

refreshPacks().catch((err) => setStatus(err.message, { error: true }));
