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
const loadPrimavera = document.getElementById("load-primavera");
const saveFacts = document.getElementById("save-facts");
const PRIMAVERA_SAMPLE_URL =
  "/static/samples/napoli_pisa_primavera2_2026-10-10_facts.json";
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
const analyzeBtn = document.getElementById("analyze-btn");
const reconcileBtn = document.getElementById("reconcile-btn");
const phase3Btn = document.getElementById("phase3-btn");
const phase4Btn = document.getElementById("phase4-btn");
const phase5Btn = document.getElementById("phase5-btn");
const phase6Btn = document.getElementById("phase6-btn");
const phase7Btn = document.getElementById("phase7-btn");
const analyzeCancel = document.getElementById("analyze-cancel");
const analyzeStatusEl = document.getElementById("analyze-status");
const analyzeProgressWrap = document.getElementById("analyze-progress-wrap");
const analyzeProgressFill = document.getElementById("analyze-progress-fill");
const analyzeProgressText = document.getElementById("analyze-progress-text");
const statusEl = document.getElementById("status");
const factsStatusEl = document.getElementById("facts-status");
const results = document.getElementById("results");
const scoreline = document.getElementById("scoreline");
const matchMeta = document.getElementById("match-meta");
const coverageBanner = document.getElementById("coverage-banner");
const teamBoard = document.getElementById("team-board");
const filmPanel = document.getElementById("film-panel");
const eventsBody = document.querySelector("#events-table tbody");
const lineupBody = document.querySelector("#lineup-table tbody");
const packsBody = document.querySelector("#packs-table tbody");

let activePackId = null;
let analyzePollTimer = null;

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
    syncAnalyzeUi(pack);
    if (pack.sheet) {
      renderSheet(pack);
      setStatus(
        pack.sheet.film
          ? `Loaded pack ${packId} (facts + Phase 2 film tags).`
          : `Loaded pack ${packId} (sheet ready).`
      );
    } else {
      results.hidden = true;
      if (filmPanel) {
        filmPanel.hidden = true;
        filmPanel.innerHTML = "";
      }
      setStatus(`Loaded pack ${packId} — save facts and compute when ready.`);
    }
    if (
      ["queued", "running", "cancelling"].includes(pack.analyze?.status) ||
      ["queued", "running", "cancelling"].includes(pack.phase3?.status) ||
      ["queued", "running"].includes(pack.phase4?.status) ||
      ["queued", "running"].includes(pack.phase5?.status) ||
      ["queued", "running"].includes(pack.phase6?.status) ||
      ["queued", "running"].includes(pack.phase7?.status)
    ) {
      pollAnalyze(packId);
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
  const filmCounts = cov.film_event_counts || sheet.film?.totals || {};
  const hasFilm = Boolean(sheet.film?.totals);
  const p3 = cov.phase3 || sheet.tracking?.possession || null;
  const p4 = cov.phase4 || null;
  const p5 = cov.phase5 || null;
  const p6 = cov.phase6 || null;
  const p7 = cov.phase7 || null;
  const hasP3 = Boolean(sheet.tracking?.possession);
  const hasP4 = Boolean(sheet.shots?.totals || p4);
  const hasP5 = Boolean(p5 || sheet.source?.phase === "match-pack-phase5");
  const hasP6 = Boolean(p6 || sheet.source?.phase === "match-pack-phase6");
  const hasP7 = Boolean(p7 || sheet.source?.phase === "match-pack-phase7");
  coverageBanner.innerHTML = `
    <strong>Phase 1 — filled from your JSON:</strong> ${factList}
    (${counts.goals ?? 0} goals, ${counts.cards ?? 0} cards, ${counts.substitutions ?? 0} subs).
    <br /><strong>Still blank / pending:</strong>
    ${missing ? `optional set pieces (${missing}); ` : ""}
    ${pending || "—"}.
    ${
      hasFilm
        ? `<br /><strong>Phase 2 — match-level film tags:</strong> ${filmCounts.events ?? "—"} events · ${filmCounts.shots ?? "—"} shot tags · ${filmCounts.passes ?? "—"} pass tags.`
        : `<br /><strong>Phase 2:</strong> Analyze video / import film tags.`
    }
    ${
      hasP3
        ? `<br /><strong>Phase 3 — tracking:</strong> possession ${p3.possession_home_pct ?? sheet.tracking.possession.home_pct}% – ${p3.possession_away_pct ?? sheet.tracking.possession.away_pct}% · pass tags ${p3.passes_home ?? "—"}–${p3.passes_away ?? "—"}.`
        : `<br /><strong>Phase 3:</strong> Run Phase 3 tracking after correcting film.`
    }
    ${
      hasP4
        ? `<br /><strong>Phase 4 — shots:</strong> ${p4?.shots_home ?? sheet.shots?.totals?.home?.shots ?? "—"}–${p4?.shots_away ?? sheet.shots?.totals?.away?.shots ?? "—"}.`
        : `<br /><strong>Phase 4:</strong> Score shots after Phase 3.`
    }
    ${
      hasP5
        ? `<br /><strong>Phase 5 — SoT:</strong> ${p5?.sot_home ?? sheet.shots?.totals?.home?.shots_on_target ?? "—"}–${p5?.sot_away ?? sheet.shots?.totals?.away?.shots_on_target ?? "—"} (saves + deflections, approximate).`
        : `<br /><strong>Phase 5:</strong> Score SoT after Phase 4.`
    }
    ${
      hasP6
        ? `<br /><strong>Phase 6 — GK:</strong> saves ${p6?.saves_home ?? sheet.teams?.[0]?.saves ?? "—"}–${p6?.saves_away ?? sheet.teams?.[1]?.saves ?? "—"} (faced ${p6?.faced_home ?? "—"}–${p6?.faced_away ?? "—"}, approximate).`
        : `<br /><strong>Phase 6:</strong> Fill GK after Phase 5.`
    }
    ${
      hasP7
        ? `<br /><strong>Phase 7 — passes/tackles:</strong> pass acc ${p7?.pass_acc_home ?? sheet.teams?.[0]?.pass_accuracy ?? "—"}%–${p7?.pass_acc_away ?? sheet.teams?.[1]?.pass_accuracy ?? "—"}% · tackles ${p7?.tackles_home ?? sheet.teams?.[0]?.tackles ?? "—"}–${p7?.tackles_away ?? sheet.teams?.[1]?.tackles ?? "—"} (approximate).`
        : `<br /><strong>Phase 7:</strong> Pass completion + tackles after Phase 6.`
    }
  `;

  const teams = sheet.teams || [];
  const home = teams[0];
  const away = teams[1];
  const vsLabel = hasP7
    ? "facts + track + shots + SoT + GK + actions"
    : hasP6
      ? "facts + track + shots + SoT + GK"
      : hasP5
        ? "facts + track + shots + SoT"
        : hasP4
          ? "facts + track + shots"
          : hasP3
            ? "facts + film + track"
            : hasFilm
              ? "facts + film"
              : "fact sheet";
  teamBoard.innerHTML = `
    ${home ? renderTeamCatalogHtml(home, "Home", { showFormation: true }) : ""}
    <div class="score-stack">
      <div class="score">${m.home_score}–${m.away_score}</div>
      <div class="vs">${vsLabel}</div>
    </div>
    ${away ? renderTeamCatalogHtml(away, "Away", { showFormation: true }) : ""}
  `;

  renderFilmPanel(
    sheet.film,
    sheet.tracking,
    sheet.shots,
    sheet.goalkeeper,
    sheet.actions
  );

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
  syncAnalyzeUi(pack);
}

function renderFilmPanel(film, tracking, shots, goalkeeper, actions) {
  if (!filmPanel) return;
  if (
    !film?.totals &&
    !tracking?.possession &&
    !shots?.totals &&
    !goalkeeper?.totals &&
    !actions?.passes
  ) {
    filmPanel.hidden = true;
    filmPanel.innerHTML = "";
    return;
  }
  const t = film?.totals || {};
  const c = film?.corrected || {};
  const rows = [
    ["Events", t.events],
    ["Shots (match)", c.shots ?? t.shots],
    ["Passes (match)", c.passes ?? t.passes],
    ["Crosses", t.crosses],
    ["Drives", t.drives],
    ["Headers", t.headers],
    ["Tackles", t.tackles],
    ["Throw-ins", c.throw_ins ?? t.throw_ins],
    ["Goals (corrected)", c.goals ?? "—"],
    ["Goal tags raw*", t.goal_tags],
  ];
  const anchors = (c.anchored_goals || [])
    .map((a) => {
      const filmBit = a.matched
        ? `film ${a.film_minute}'`
        : "no film match";
      return `${a.player_name || "?"} ${a.fact_minute}' (${a.team}) ← ${filmBit}`;
    })
    .join(" · ");
  const poss = tracking?.possession || {};
  const splits = tracking?.team_splits || {};
  const trackRows = tracking
    ? [
        ["Poss. home %", poss.home_pct],
        ["Poss. away %", poss.away_pct],
        ["Pass tags home", splits.home?.passes],
        ["Pass tags away", splits.away?.passes],
        ["Shot tags home*", splits.home?.shot_tags ?? splits.home?.shots],
        ["Shot tags away*", splits.away?.shot_tags ?? splits.away?.shots],
        ["Tagged (debounced)", splits.events_after_debounce ?? splits.events_tagged],
      ]
    : [];
  filmPanel.hidden = false;
  filmPanel.innerHTML = `
    <h3>Film + tracking</h3>
    <p class="film-warn">${
      tracking?.warning ||
      film?.warning ||
      "Approximate broadcast spotting / tracking — not a provider feed."
    }</p>
    ${
      anchors
        ? `<p class="film-warn"><strong>Anchored goals:</strong> ${anchors}</p>`
        : ""
    }
    ${
      film?.totals
        ? `<h4 class="stat-section__title">Phase 2 film (match-level)</h4>
    <ul class="film-grid">
      ${rows
        .map(
          ([label, value]) => `
        <li>
          <span class="label">${label}</span>
          <span class="value">${fmt(value, 0)}</span>
        </li>`
        )
        .join("")}
    </ul>`
        : ""
    }
    ${
      tracking
        ? `<h4 class="stat-section__title" style="margin-top:1.25rem">Phase 3 tracking (home/away)</h4>
    <ul class="film-grid">
      ${trackRows
        .map(
          ([label, value]) => `
        <li>
          <span class="label">${label}</span>
          <span class="value">${fmt(value, 0)}</span>
        </li>`
        )
        .join("")}
    </ul>`
        : ""
    }
    ${
      shots?.totals
        ? `<h4 class="stat-section__title" style="margin-top:1.25rem">Phase 4–5 shots / SoT</h4>
    <p class="film-warn">${shots.warning || ""}</p>
    <ul class="film-grid">
      <li><span class="label">Shots home</span><span class="value">${fmt(shots.totals.home?.shots, 0)}</span></li>
      <li><span class="label">Shots away</span><span class="value">${fmt(shots.totals.away?.shots, 0)}</span></li>
      <li><span class="label">SoT home</span><span class="value">${fmt(shots.totals.home?.shots_on_target, 0)}</span></li>
      <li><span class="label">SoT away</span><span class="value">${fmt(shots.totals.away?.shots_on_target, 0)}</span></li>
      <li><span class="label">Selected</span><span class="value">${fmt((shots.selected || []).length, 0)}</span></li>
      <li><span class="label">Budget</span><span class="value">${fmt(shots.budget, 0)}</span></li>
    </ul>`
        : ""
    }
    ${
      goalkeeper?.totals
        ? `<h4 class="stat-section__title" style="margin-top:1.25rem">Phase 6 goalkeeper</h4>
    <p class="film-warn">${goalkeeper.warning || ""}</p>
    <ul class="film-grid">
      <li><span class="label">Faced home</span><span class="value">${fmt(goalkeeper.totals.home?.shots_faced, 0)}</span></li>
      <li><span class="label">Faced away</span><span class="value">${fmt(goalkeeper.totals.away?.shots_faced, 0)}</span></li>
      <li><span class="label">Saves home</span><span class="value">${fmt(goalkeeper.totals.home?.saves, 0)}</span></li>
      <li><span class="label">Saves away</span><span class="value">${fmt(goalkeeper.totals.away?.saves, 0)}</span></li>
      <li><span class="label">Save % home</span><span class="value">${fmt(goalkeeper.totals.home?.save_pct)}</span></li>
      <li><span class="label">Save % away</span><span class="value">${fmt(goalkeeper.totals.away?.save_pct)}</span></li>
    </ul>`
        : ""
    }
    ${
      actions?.passes
        ? `<h4 class="stat-section__title" style="margin-top:1.25rem">Phase 7 passes + tackles</h4>
    <p class="film-warn">${actions.warning || ""}</p>
    <ul class="film-grid">
      <li><span class="label">Pass att home</span><span class="value">${fmt(actions.passes.home?.passes_attempted, 0)}</span></li>
      <li><span class="label">Pass att away</span><span class="value">${fmt(actions.passes.away?.passes_attempted, 0)}</span></li>
      <li><span class="label">Pass acc home %</span><span class="value">${fmt(actions.passes.home?.pass_accuracy)}</span></li>
      <li><span class="label">Pass acc away %</span><span class="value">${fmt(actions.passes.away?.pass_accuracy)}</span></li>
      <li><span class="label">Tackles home</span><span class="value">${fmt(actions.tackles?.totals?.home?.tackles, 0)}</span></li>
      <li><span class="label">Tackles away</span><span class="value">${fmt(actions.tackles?.totals?.away?.tackles, 0)}</span></li>
    </ul>`
        : ""
    }
  `;
}

function setAnalyzeStatus(text, { error = false, loading = false } = {}) {
  if (!analyzeStatusEl) return;
  analyzeStatusEl.textContent = text;
  analyzeStatusEl.classList.toggle("is-error", error);
  analyzeStatusEl.classList.toggle("is-loading", loading);
}

function stopAnalyzePoll() {
  if (analyzePollTimer) {
    clearInterval(analyzePollTimer);
    analyzePollTimer = null;
  }
}

function syncAnalyzeUi(pack) {
  const a = pack?.analyze;
  const p3 = pack?.phase3;
  const p4 = pack?.phase4;
  const p5 = pack?.phase5;
  const p6 = pack?.phase6;
  const p7 = pack?.phase7;
  const busyA = a && ["queued", "running", "cancelling"].includes(a.status);
  const busy3 = p3 && ["queued", "running", "cancelling"].includes(p3.status);
  const busy4 = p4 && ["queued", "running"].includes(p4.status);
  const busy5 = p5 && ["queued", "running"].includes(p5.status);
  const busy6 = p6 && ["queued", "running"].includes(p6.status);
  const busy7 = p7 && ["queued", "running"].includes(p7.status);
  const prog =
    (busy7
      ? p7?.progress
      : busy6
        ? p6?.progress
        : busy5
          ? p5?.progress
          : busy4
            ? p4?.progress
            : busy3
              ? p3?.progress
              : a?.progress) || {};
  const pct = prog.pct ?? 0;
  if (analyzeProgressWrap) {
    analyzeProgressWrap.hidden =
      !busyA &&
      !busy3 &&
      !busy4 &&
      !busy5 &&
      !busy6 &&
      !busy7 &&
      !(
        a?.status === "done" ||
        p3?.status === "done" ||
        p4?.status === "done" ||
        p5?.status === "done" ||
        p6?.status === "done" ||
        p7?.status === "done"
      );
    if (analyzeProgressFill) analyzeProgressFill.style.width = `${pct}%`;
    if (analyzeProgressText) {
      if (busy7) {
        analyzeProgressText.textContent = `phase7 ${p7.status} · ${pct}% · passes/tackles`;
      } else if (busy6) {
        analyzeProgressText.textContent = `phase6 ${p6.status} · ${pct}% · GK`;
      } else if (busy5) {
        analyzeProgressText.textContent = `phase5 ${p5.status} · ${pct}% · SoT`;
      } else if (busy4) {
        analyzeProgressText.textContent = `phase4 ${p4.status} · ${pct}% · ${prog.done ?? 0}/${prog.total ?? "?"} candidates`;
      } else if (busy3) {
        analyzeProgressText.textContent = `phase3 ${p3.status} · ${pct}% · ${prog.stage || ""} · ${prog.samples ?? ""} samples`;
      } else if (busyA) {
        analyzeProgressText.textContent = `phase2 ${a.status} · ${pct}% · ${prog.events_so_far ?? a.event_count ?? 0} events`;
      } else if (p7?.status === "done") {
        const tk = p7.tackles || {};
        analyzeProgressText.textContent = `phase7 done · tackles ${(tk.home && tk.home.tackles) ?? "—"}–${(tk.away && tk.away.tackles) ?? "—"}`;
      } else if (p6?.status === "done") {
        const tot = p6.totals || {};
        analyzeProgressText.textContent = `phase6 done · saves ${(tot.home && tot.home.saves) ?? "—"}–${(tot.away && tot.away.saves) ?? "—"}`;
      } else if (p5?.status === "done") {
        const tot = p5.totals || {};
        analyzeProgressText.textContent = `phase5 done · SoT ${(tot.home && tot.home.shots_on_target) ?? "—"}–${(tot.away && tot.away.shots_on_target) ?? "—"}`;
      } else if (p4?.status === "done") {
        const tot = p4.totals || {};
        analyzeProgressText.textContent = `phase4 done · shots ${(tot.home && tot.home.shots) ?? "—"}–${(tot.away && tot.away.shots) ?? "—"}`;
      } else if (p3?.status === "done") {
        const poss = p3.possession || {};
        analyzeProgressText.textContent = `phase3 done · possession ${poss.home_pct ?? "—"}%–${poss.away_pct ?? "—"}%`;
      } else if (a?.status === "done") {
        analyzeProgressText.textContent = `phase2 done · ${a.event_count ?? 0} film events`;
      } else {
        analyzeProgressText.textContent = "";
      }
    }
  }
  if (busy7) {
    setAnalyzeStatus(`Phase 7 passes + tackles… ${pct}%`, { loading: true });
  } else if (p7?.status === "done") {
    const tk = p7.tackles || {};
    const pa = p7.passes || {};
    setAnalyzeStatus(
      `Phase 7 ready — pass acc ${pa.home?.pass_accuracy ?? "—"}%–${pa.away?.pass_accuracy ?? "—"}% · tackles ${tk.home?.tackles ?? "—"}–${tk.away?.tackles ?? "—"}.`
    );
    stopAnalyzePoll();
  } else if (p7?.status === "error") {
    setAnalyzeStatus(p7.error || "Phase 7 failed", { error: true });
    stopAnalyzePoll();
  } else if (busy6) {
    setAnalyzeStatus(`Phase 6 filling GK… ${pct}%`, { loading: true });
  } else if (p6?.status === "done" && !p7) {
    const tot = p6.totals || {};
    setAnalyzeStatus(
      `Phase 6 ready — saves ${tot.home?.saves ?? "—"}–${tot.away?.saves ?? "—"}. Run Phase 7 for passes/tackles.`
    );
    stopAnalyzePoll();
  } else if (p6?.status === "error") {
    setAnalyzeStatus(p6.error || "Phase 6 failed", { error: true });
    stopAnalyzePoll();
  } else if (busy5) {
    setAnalyzeStatus(`Phase 5 scoring SoT… ${pct}%`, { loading: true });
  } else if (p5?.status === "done" && !p6) {
    const tot = p5.totals || {};
    setAnalyzeStatus(
      `Phase 5 ready — SoT ${tot.home?.shots_on_target ?? "—"}–${tot.away?.shots_on_target ?? "—"}. Run Phase 6 for GK.`
    );
    stopAnalyzePoll();
  } else if (p5?.status === "error") {
    setAnalyzeStatus(p5.error || "Phase 5 failed", { error: true });
    stopAnalyzePoll();
  } else if (busy4) {
    setAnalyzeStatus(`Phase 4 scoring shots… ${pct}%`, { loading: true });
  } else if (p4?.status === "done" && !p5) {
    const tot = p4.totals || {};
    setAnalyzeStatus(
      `Phase 4 ready — shots ${tot.home?.shots ?? "—"}–${tot.away?.shots ?? "—"}. Run Phase 5 for SoT.`
    );
    stopAnalyzePoll();
  } else if (p4?.status === "error") {
    setAnalyzeStatus(p4.error || "Phase 4 failed", { error: true });
    stopAnalyzePoll();
  } else if (busy3) {
    setAnalyzeStatus(`Phase 3 tracking… ${pct}% (${prog.stage || "running"})`, {
      loading: true,
    });
  } else if (p3?.status === "done" && !p4) {
    const poss = p3.possession || {};
    setAnalyzeStatus(
      `Phase 3 ready — possession ${poss.home_pct ?? "—"}%–${poss.away_pct ?? "—"}%. Team board updated.`
    );
  } else if (p3?.status === "error") {
    setAnalyzeStatus(p3.error || "Phase 3 failed", { error: true });
    stopAnalyzePoll();
  } else if (busyA) {
    setAnalyzeStatus(`Analyzing video… ${pct}%`, { loading: true });
  } else if (a?.status === "done") {
    setAnalyzeStatus(
      `Phase 2 ready — ${a.event_count ?? 0} film events${
        a.video_job_id ? ` (imported job ${a.video_job_id})` : ""
      }.`
    );
  } else if (a?.status === "error") {
    setAnalyzeStatus(a.error || "Analyze failed", { error: true });
    stopAnalyzePoll();
  }
}

async function pollAnalyze(packId) {
  stopAnalyzePoll();
  analyzePollTimer = setInterval(async () => {
    try {
      const pack = await fetchJson(`/api/match-packs/${packId}`);
      if (pack.pack_id === activePackId) {
        syncAnalyzeUi(pack);
        if (pack.sheet?.film || pack.sheet?.tracking) {
          renderSheet(pack);
        }
      }
      const st2 = pack.analyze?.status;
      const st3 = pack.phase3?.status;
      const st4 = pack.phase4?.status;
      const st5 = pack.phase5?.status;
      const st6 = pack.phase6?.status;
      const st7 = pack.phase7?.status;
      const busy2 = st2 && ["queued", "running", "cancelling"].includes(st2);
      const busy3 = st3 && ["queued", "running", "cancelling"].includes(st3);
      const busy4 = st4 && ["queued", "running"].includes(st4);
      const busy5 = st5 && ["queued", "running"].includes(st5);
      const busy6 = st6 && ["queued", "running"].includes(st6);
      const busy7 = st7 && ["queued", "running"].includes(st7);
      if (!busy2 && !busy3 && !busy4 && !busy5 && !busy6 && !busy7) {
        stopAnalyzePoll();
        await refreshPacks();
      }
    } catch (err) {
      setAnalyzeStatus(err.message, { error: true });
      stopAnalyzePoll();
    }
  }, 2500);
}

analyzeBtn?.addEventListener("click", async () => {
  setAnalyzeStatus("Starting Phase 2 analyze…", { loading: true });
  try {
    const id = requirePack();
    const pack = await fetchJson(
      `/api/match-packs/${id}/analyze?reuse_matching_job=true`,
      { method: "POST" }
    );
    setPackId(pack.pack_id);
    if (pack.sheet) {
      renderSheet(pack);
      setAnalyzeStatus(
        pack.analyze?.source === "imported_video_job"
          ? `Imported film tags from job ${pack.analyze.video_job_id}.`
          : "Phase 2 sheet updated."
      );
    } else {
      syncAnalyzeUi(pack);
      pollAnalyze(id);
    }
    await refreshPacks();
  } catch (err) {
    setAnalyzeStatus(err.message, { error: true });
  }
});

analyzeCancel?.addEventListener("click", async () => {
  try {
    const id = requirePack();
    let pack = await fetchJson(`/api/match-packs/${id}/analyze/cancel`, {
      method: "POST",
    }).catch(() => null);
    pack = await fetchJson(`/api/match-packs/${id}/phase3/cancel`, {
      method: "POST",
    });
    syncAnalyzeUi(pack);
    setAnalyzeStatus("Cancel requested.");
  } catch (err) {
    setAnalyzeStatus(err.message, { error: true });
  }
});

phase3Btn?.addEventListener("click", async () => {
  setAnalyzeStatus("Starting Phase 3 tracking (kit colours + possession)…", {
    loading: true,
  });
  try {
    const id = requirePack();
    const pack = await fetchJson(`/api/match-packs/${id}/phase3?sample_fps=0.25`, {
      method: "POST",
    });
    setPackId(pack.pack_id);
    syncAnalyzeUi(pack);
    if (pack.phase3?.status === "done" && pack.sheet) {
      renderSheet(pack);
    } else {
      pollAnalyze(id);
    }
    await refreshPacks();
  } catch (err) {
    setAnalyzeStatus(err.message, { error: true });
  }
});

phase4Btn?.addEventListener("click", async () => {
  setAnalyzeStatus("Starting Phase 4 shot scoring…", { loading: true });
  try {
    const id = requirePack();
    const pack = await fetchJson(`/api/match-packs/${id}/phase4`, { method: "POST" });
    setPackId(pack.pack_id);
    syncAnalyzeUi(pack);
    if (pack.phase4?.status === "done" && pack.sheet) {
      renderSheet(pack);
    } else {
      pollAnalyze(id);
    }
    await refreshPacks();
  } catch (err) {
    setAnalyzeStatus(err.message, { error: true });
  }
});

phase5Btn?.addEventListener("click", async () => {
  setAnalyzeStatus("Starting Phase 5 SoT (saves + deflections)…", {
    loading: true,
  });
  try {
    const id = requirePack();
    const pack = await fetchJson(`/api/match-packs/${id}/phase5`, { method: "POST" });
    setPackId(pack.pack_id);
    syncAnalyzeUi(pack);
    if (pack.phase5?.status === "done" && pack.sheet) {
      renderSheet(pack);
    } else {
      pollAnalyze(id);
    }
    await refreshPacks();
  } catch (err) {
    setAnalyzeStatus(err.message, { error: true });
  }
});

phase6Btn?.addEventListener("click", async () => {
  setAnalyzeStatus("Starting Phase 6 GK (shots faced / saves)…", {
    loading: true,
  });
  try {
    const id = requirePack();
    const pack = await fetchJson(`/api/match-packs/${id}/phase6`, { method: "POST" });
    setPackId(pack.pack_id);
    syncAnalyzeUi(pack);
    if (pack.phase6?.status === "done" && pack.sheet) {
      renderSheet(pack);
    } else {
      pollAnalyze(id);
    }
    await refreshPacks();
  } catch (err) {
    setAnalyzeStatus(err.message, { error: true });
  }
});

phase7Btn?.addEventListener("click", async () => {
  setAnalyzeStatus("Starting Phase 7 passes + tackles…", { loading: true });
  try {
    const id = requirePack();
    const pack = await fetchJson(`/api/match-packs/${id}/phase7`, { method: "POST" });
    setPackId(pack.pack_id);
    syncAnalyzeUi(pack);
    if (pack.phase7?.status === "done" && pack.sheet) {
      renderSheet(pack);
    } else {
      pollAnalyze(id);
    }
    await refreshPacks();
  } catch (err) {
    setAnalyzeStatus(err.message, { error: true });
  }
});

reconcileBtn?.addEventListener("click", async () => {
  setAnalyzeStatus("Correcting film tags against match facts…", { loading: true });
  try {
    const id = requirePack();
    const pack = await fetchJson(`/api/match-packs/${id}/reconcile?promote=true`, {
      method: "POST",
    });
    setPackId(pack.pack_id);
    if (pack.facts) {
      factsJson.value = JSON.stringify(pack.facts, null, 2);
    }
    if (pack.sheet) {
      renderSheet(pack);
    }
    const r = pack.reconcile || {};
    setAnalyzeStatus(
      `Corrected: ${r.goal_tags_matched ?? 0}/${r.fact_goals ?? 0} fact goals anchored to film. ` +
        `Summary saved in facts.film_corrected (events list unchanged — still fact truth).`
    );
    await refreshPacks();
  } catch (err) {
    setAnalyzeStatus(err.message, { error: true });
  }
});

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

/** Normalize paste/download artifacts that break JSON.parse (curly quotes, trailing commas). */
function normalizeFactsText(text) {
  return stripBom(String(text || ""))
    .replace(/^\uFEFF/, "")
    .replace(/[\u201C\u201D\u00AB\u00BB]/g, '"')
    .replace(/[\u2018\u2019\u2032]/g, "'")
    .replace(/\u00A0/g, " ")
    .trim();
}

function formatJsonParseError(raw, err) {
  const msg = err && err.message ? err.message : String(err);
  const m = /position\s+(\d+)/i.exec(msg);
  if (!m) return `Facts JSON is invalid: ${msg}`;
  const pos = Number(m[1]);
  const before = raw.slice(0, pos);
  const line = before.split("\n").length;
  const col = pos - before.lastIndexOf("\n");
  const lines = raw.split("\n");
  const from = Math.max(0, line - 2);
  const to = Math.min(lines.length, line + 1);
  const snippet = lines
    .slice(from, to)
    .map((l, i) => `${from + i + 1}: ${l}`)
    .join("\n");
  return (
    `Facts JSON is invalid near line ${line}, column ${col}: ${msg}. ` +
    `Use “Load Napoli–Pisa Primavera 2 into editor” for a clean copy.\n${snippet}`
  );
}

function parseFactsJson(text) {
  const normalized = normalizeFactsText(text);
  if (!normalized) {
    throw new Error("Facts editor is empty.");
  }
  try {
    return JSON.parse(normalized);
  } catch (err) {
    // Common Mac/editor artifact: trailing comma before ] or }.
    const repaired = normalized.replace(/,\s*([\]}])/g, "$1");
    if (repaired !== normalized) {
      try {
        return JSON.parse(repaired);
      } catch {
        /* fall through */
      }
    }
    throw new Error(formatJsonParseError(normalized, err));
  }
}

async function readFactsFileAsText(file) {
  const buf = await file.arrayBuffer();
  // Prefer UTF-8 with BOM strip; fall back if decode throws.
  try {
    return normalizeFactsText(new TextDecoder("utf-8").decode(buf));
  } catch {
    return normalizeFactsText(await file.text());
  }
}

async function loadPrimaveraSampleIntoEditor() {
  setStatus("Loading Napoli–Pisa Primavera 2 facts…", { loading: true, near: "facts" });
  const res = await fetch(PRIMAVERA_SAMPLE_URL);
  if (!res.ok) {
    throw new Error(`Could not fetch sample JSON (${res.status})`);
  }
  const payload = parseFactsJson(await res.text());
  factsJson.value = JSON.stringify(payload, null, 2);
  homeTeam.value = payload.home?.team_name || homeTeam.value;
  awayTeam.value = payload.away?.team_name || awayTeam.value;
  setStatus(
    "Primavera 2 facts loaded into the editor. Click Save facts (creates sheet automatically).",
    { near: "facts" }
  );
}

loadPrimavera?.addEventListener("click", async () => {
  try {
    await loadPrimaveraSampleIntoEditor();
  } catch (err) {
    setStatus(err.message, { error: true, near: "facts" });
  }
});

factsFile?.addEventListener("change", async () => {
  const file = factsFile.files?.[0];
  if (!file) return;
  try {
    const text = await readFactsFileAsText(file);
    // Preview in editor only — does not save until Upload / Save.
    const payload = parseFactsJson(text);
    factsJson.value = JSON.stringify(payload, null, 2);
    setStatus(
      `Loaded ${file.name} into the editor. Click “Upload JSON file” or Save facts.`,
      { near: "facts" }
    );
  } catch (err) {
    setStatus(`Could not read ${file.name}: ${err.message}`, {
      error: true,
      near: "facts",
    });
    // Clear the broken selection so the same file can be re-chosen after a fix.
    factsFile.value = "";
  }
});

uploadFactsFile?.addEventListener("click", async () => {
  setStatus("Uploading facts JSON…", { loading: true, near: "facts" });
  try {
    const id = requirePack();
    const file = factsFile.files?.[0];
    if (!file) {
      // Allow upload from editor contents as a synthetic file.
      if (!factsJson.value.trim()) {
        throw new Error("Choose a .json facts file, or paste JSON then Save facts.");
      }
      // Validate locally first so we never POST garbage that looks like a drop.
      const payload = parseFactsJson(factsJson.value);
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
        `Facts saved. Sheet ready: ${m.home_score ?? "?"}–${m.away_score ?? "?"}.`,
        { near: "both" }
      );
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
    setStatus(`Uploaded ${file.name} — computing sheet…`, { loading: true, near: "facts" });
    const computed = await computeSheet(id);
    const m = computed.sheet?.match || {};
    setStatus(
      `Uploaded ${file.name}. Sheet ready: ${m.home_score ?? "?"}–${m.away_score ?? "?"}.`,
      { near: "both" }
    );
    await refreshPacks();
  } catch (err) {
    setStatus(err.message, { error: true, near: "facts" });
  }
});

saveFacts.addEventListener("click", async () => {
  setStatus("Saving facts…", { loading: true, near: "facts" });
  try {
    const id = requirePack();
    const payload = parseFactsJson(factsJson.value);
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
      const payload = parseFactsJson(factsJson.value);
      await fetchJson(`/api/match-packs/${id}/facts`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      factsJson.value = JSON.stringify(payload, null, 2);
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
