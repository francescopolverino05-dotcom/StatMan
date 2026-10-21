import { fetchJson, qs } from "./common.js";

// Mirrors statman/autotag/taxonomy.py TAXONOMY (attribute -> "bool" | "float" | [choices]).
const TAXONOMY = {
  goal: { own_goal: "bool", headed: "bool" },
  pass: {
    completed: "bool", key_pass: "bool", progressive: "bool",
    line_broken: ["midfield", "defence", "attack", "multiple"], cross: "bool", box_entry: "bool",
  },
  shot: { xg: "float", on_target: "bool", outcome: ["goal", "saved", "blocked", "missed", "post"], headed: "bool", inside_box: "bool" },
  corner: {},
  foul: {},
  card: { color: ["yellow", "red"] },
  free_kick: { distance_m: "float", outcome: ["direct_shot", "crossed_played"] },
  tackle: { won: "bool" },
  interception: {},
  ball_lost: { reason: ["miscontrol", "dispossessed"] },
  aerial_duel: { won: "bool", source: ["goal_kick", "long_ball"] },
  save: {},
  goal_conceded: {},
  gk_pass: { length: ["short", "long"], lane: ["middle", "flank"], completed: "bool" },
};

const $ = (id) => document.getElementById(id);
const state = { match: null, events: [], threshold: 0.75, editing: null };

function clock(sec) {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}'${String(s % 60).padStart(2, "0")}`;
}

function esc(v) {
  return String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function attrText(attrs) {
  return Object.entries(attrs || {})
    .map(([k, v]) => (v === true ? k : v === false ? `!${k}` : `${k}=${v}`))
    .join(" · ");
}

function base() {
  return `/api/autotag/matches/${encodeURIComponent(state.match)}`;
}

function filtered() {
  const type = $("f-type").value;
  const team = $("f-team").value;
  const status = $("f-status").value;
  return state.events.filter(
    (e) =>
      (!type || e.type === type) &&
      (!team || e.team === team) &&
      (!status || status.split(",").includes(e.review_status))
  );
}

function seek(ev) {
  const v = $("video");
  const t = ev.video_ts_seconds ?? ev.t_match_seconds;
  v.currentTime = Math.max(0, t - 3);
  v.play().catch(() => {});
}

function renderTrack() {
  const track = $("track");
  const dur = $("video").duration || Math.max(1, ...state.events.map((e) => e.video_ts_seconds ?? e.t_match_seconds));
  track.innerHTML = filtered()
    .map((e) => {
      const t = e.video_ts_seconds ?? e.t_match_seconds;
      const low = e.review_status === "pending";
      return `<button class="review-tick review-tick--${esc(e.team)}${low ? " is-low" : ""}" data-id="${e.id}"
        style="left:${(100 * t) / dur}%" title="${esc(clock(e.t_match_seconds))} ${esc(e.type)} (${esc(e.team)})"></button>`;
    })
    .join("");
}

function renderList() {
  const rows = filtered();
  const pending = state.events.filter((e) => e.review_status === "pending").length;
  $("counts").textContent = `${rows.length} shown · ${pending} need review · ${state.events.length} total`;
  $("list").innerHTML = rows
    .map((e) => {
      const low = e.review_status === "pending";
      const reasons = (e.review_reason || []).join(", ");
      return `<li class="review-item${low ? " is-low" : ""}" data-id="${e.id}">
        <button class="review-item__seek" data-seek="${e.id}">
          <strong>${clock(e.t_match_seconds)}</strong> ${esc(e.type)} · ${esc(e.team || "?")}
          ${e.shirt ? `#${esc(e.shirt)}` : ""} <span class="review-conf">${Math.round((e.confidence ?? 0) * 100)}%</span>
        </button>
        <div class="review-item__attrs">${esc(attrText(e.attributes))}</div>
        ${low && reasons ? `<div class="review-item__why">${esc(reasons)}</div>` : ""}
        <div class="review-item__status">${esc(e.review_status)}</div>
        <div class="review-item__actions">
          ${low ? `<button class="btn btn--primary" data-act="accept" data-id="${e.id}">Accept</button>` : ""}
          <button class="btn btn--ghost" data-act="edit" data-id="${e.id}">Edit</button>
          <button class="btn btn--ghost" data-act="delete" data-id="${e.id}">Delete</button>
        </div>
      </li>`;
    })
    .join("");
}

function render() {
  renderTrack();
  renderList();
}

async function load(matchId) {
  state.match = matchId;
  $("status").textContent = "Loading…";
  try {
    const [job, data] = await Promise.all([
      fetchJson(base()).catch(() => null),
      fetchJson(`${base()}/events`),
    ]);
    state.events = data.events;
    state.threshold = data.review_threshold;
    $("threshold").textContent = state.threshold.toFixed(2);
    $("video").src = `${base()}/video`;
    $("csv-team").href = `${base()}/stats/team.csv`;
    $("csv-players").href = `${base()}/stats/players.csv`;
    $("review").hidden = false;
    $("status").textContent = job ? `Job: ${job.status} — ${job.stage || ""}${job.error ? ` (${job.error})` : ""}` : "";
    render();
  } catch (err) {
    $("status").textContent = `Could not load: ${err.message}`;
  }
}

async function review(id, action, changes, note) {
  const res = await fetchJson(`${base()}/events/${id}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, changes, note }),
  });
  const i = state.events.findIndex((e) => e.id === id);
  if (action === "delete") state.events.splice(i, 1);
  else state.events[i] = res.event;
  render();
}

function attrInputs(type, attrs) {
  const spec = TAXONOMY[type] || {};
  const box = $("e-attrs");
  box.innerHTML = "<legend>Attributes</legend>";
  for (const [key, kind] of Object.entries(spec)) {
    const v = attrs?.[key];
    let input;
    if (Array.isArray(kind)) {
      input = `<select data-attr="${key}" data-kind="enum"><option value="">—</option>${kind
        .map((c) => `<option ${c === v ? "selected" : ""}>${c}</option>`)
        .join("")}</select>`;
    } else if (kind === "bool") {
      input = `<select data-attr="${key}" data-kind="bool"><option value="">—</option>
        <option value="true" ${v === true ? "selected" : ""}>yes</option>
        <option value="false" ${v === false ? "selected" : ""}>no</option></select>`;
    } else {
      input = `<input data-attr="${key}" data-kind="float" type="number" step="0.01" value="${v ?? ""}" />`;
    }
    box.insertAdjacentHTML("beforeend", `<label class="field"><span>${key}</span>${input}</label>`);
  }
}

function openEditor(ev) {
  state.editing = ev;
  $("edit-id").textContent = `#${ev.id} at ${clock(ev.t_match_seconds)}`;
  $("e-type").value = ev.type;
  $("e-team").value = ev.team || "home";
  $("e-shirt").value = ev.shirt ?? "";
  $("e-player").value = ev.player ?? "";
  $("e-note").value = "";
  attrInputs(ev.type, ev.attributes);
  $("editor").showModal();
}

function readEditor() {
  const attributes = {};
  for (const el of $("e-attrs").querySelectorAll("[data-attr]")) {
    if (el.value === "") continue;
    const kind = el.dataset.kind;
    attributes[el.dataset.attr] = kind === "bool" ? el.value === "true" : kind === "float" ? Number(el.value) : el.value;
  }
  return {
    type: $("e-type").value,
    team: $("e-team").value,
    shirt: $("e-shirt").value ? Number($("e-shirt").value) : null,
    player: $("e-player").value || null,
    attributes,
  };
}

function init() {
  for (const t of Object.keys(TAXONOMY)) {
    $("f-type").insertAdjacentHTML("beforeend", `<option>${t}</option>`);
    $("e-type").insertAdjacentHTML("beforeend", `<option>${t}</option>`);
  }
  for (const id of ["f-type", "f-team", "f-status"]) $(id).addEventListener("change", render);
  $("video").addEventListener("loadedmetadata", renderTrack);
  $("e-type").addEventListener("change", () => attrInputs($("e-type").value, {}));

  $("match-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const id = $("match-id").value.trim();
    history.replaceState(null, "", `/review?match=${encodeURIComponent(id)}`);
    load(id);
  });

  const byId = (id) => state.events.find((e) => e.id === Number(id));
  $("track").addEventListener("click", (e) => {
    const ev = byId(e.target.dataset.id);
    if (ev) seek(ev);
  });
  $("list").addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const ev = byId(btn.dataset.seek || btn.dataset.id);
    if (!ev) return;
    if (btn.dataset.seek) return seek(ev);
    try {
      if (btn.dataset.act === "edit") return openEditor(ev);
      if (btn.dataset.act === "delete" && !confirm(`Delete ${ev.type} at ${clock(ev.t_match_seconds)}?`)) return;
      await review(ev.id, btn.dataset.act);
    } catch (err) {
      $("status").textContent = `Review failed: ${err.message}`;
    }
  });
  $("editor").addEventListener("close", async () => {
    if ($("editor").returnValue !== "save" || !state.editing) return;
    try {
      await review(state.editing.id, "edit", readEditor(), $("e-note").value || null);
    } catch (err) {
      $("status").textContent = `Correction failed: ${err.message}`;
    }
    state.editing = null;
  });

  const match = qs("match");
  if (match) {
    $("match-id").value = match;
    load(match);
  }
}

init();
