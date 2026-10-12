import { fetchJson, fmt } from "./common.js";

const form = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const fileLabel = document.getElementById("file-label");
const sampleFps = document.getElementById("sample-fps");
const statusEl = document.getElementById("status");
const progressWrap = document.getElementById("progress-wrap");
const progressFill = document.getElementById("progress-fill");
const progressText = document.getElementById("progress-text");
const etaText = document.getElementById("eta-text");
const cancelBtn = document.getElementById("cancel-btn");
const detectorStatus = document.getElementById("detector-status");
const results = document.getElementById("results");
const qualityBanner = document.getElementById("quality-banner");
const totalsEl = document.getElementById("totals");
const labelBody = document.querySelector("#label-table tbody");
const timelineBody = document.querySelector("#timeline-table tbody");
const jobsBody = document.querySelector("#jobs-table tbody");
const resultTitle = document.getElementById("result-title");
const resultMeta = document.getElementById("result-meta");

let pollTimer = null;
let activeJobId = null;

function setStatus(text, { error = false, loading = false } = {}) {
  statusEl.textContent = text;
  statusEl.classList.toggle("is-error", error);
  statusEl.classList.toggle("is-loading", loading);
}

function fmtDuration(sec) {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function fmtEta(sec) {
  if (sec == null) return "ETA unknown";
  if (sec < 60) return `~${Math.round(sec)}s left`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `~${m}m ${String(s).padStart(2, "0")}s left`;
}

function fmtClock(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}'${String(s).padStart(2, "0")}`;
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  fileLabel.textContent = file ? `${file.name} (${(file.size / 1e9).toFixed(2)} GB)` : "Choose full-match video…";
});

async function refreshDetector() {
  try {
    const d = await fetchJson("/api/video/detector");
    detectorStatus.textContent = d.available
      ? "YOLO (yolov8n person + sports ball)"
      : `OpenCV HOG fallback${d.error ? ` — ${d.error}` : ""}`;
  } catch {
    detectorStatus.textContent = "unknown";
  }
}

async function refreshJobs() {
  const data = await fetchJson("/api/video/jobs?limit=12");
  jobsBody.innerHTML = (data.jobs || [])
    .map(
      (j) => `
    <tr data-job="${j.job_id}" class="job-row">
      <td><code>${j.job_id}</code></td>
      <td>${j.filename || "—"}</td>
      <td>${fmtDuration(j.duration_sec)}</td>
      <td>${j.status}${j.approximate ? " · approx" : ""}</td>
      <td>${j.event_count ?? "—"}</td>
      <td>${j.status === "running" || j.status === "queued" ? fmtEta(j.eta_sec) : "—"}</td>
    </tr>`
    )
    .join("");
  for (const row of jobsBody.querySelectorAll(".job-row")) {
    row.addEventListener("click", () => openJob(row.dataset.job));
  }
}

function renderStats(job) {
  const stats = job.stats;
  if (!stats) return;
  results.hidden = false;
  const match = stats.match || {};
  resultTitle.textContent = match.filename || job.filename || "Full match";
  resultMeta.textContent = [
    match.duration_min != null ? `${match.duration_min} minutes` : null,
    match.width && match.height ? `${match.width}×${match.height}` : null,
    stats.source?.method,
    "approximate",
  ]
    .filter(Boolean)
    .join(" · ");

  qualityBanner.textContent =
    stats.source?.warning ||
    job.warning ||
    "This is approximate. Do not trust these counts.";
  const t = stats.totals || {};
  const cells = [
    ["Events", t.events],
    ["Goals", t.goals],
    ["Shots", t.shots],
    ["Passes", t.passes],
    ["Drives", t.drives],
    ["Headers", t.headers],
    ["Tackles", t.tackles],
    ["Blocks", t.blocks],
    ["Crosses", t.crosses],
    ["Outs", t.outs],
  ];
  totalsEl.innerHTML = cells
    .map(
      ([label, value]) => `
    <div class="stat-tile">
      <span class="stat-tile__label">${label}</span>
      <span class="stat-tile__value">${fmt(value, 0)}</span>
    </div>`
    )
    .join("");

  labelBody.innerHTML = Object.entries(stats.label_counts || {})
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`)
    .join("");

  const timeline = (stats.timeline || []).slice(0, 80);
  timelineBody.innerHTML = timeline
    .map(
      (e) => `
    <tr>
      <td>${fmtClock(e.time_sec)}</td>
      <td>${e.label}</td>
      <td>${fmt(e.confidence, 2)}</td>
      <td>${fmt(e.people_count, 0)}</td>
    </tr>`
    )
    .join("");
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

function showProgress(job) {
  const p = job.progress || {};
  progressWrap.hidden = false;
  progressFill.style.width = `${p.pct ?? 0}%`;
  const clock =
    p.duration_sec != null
      ? `${fmtDuration(p.time_sec || 0)} / ${fmtDuration(p.duration_sec)}`
      : fmtDuration(p.time_sec || 0);
  progressText.textContent =
    `${p.stage || "…"} · ${p.pct ?? 0}% · ${clock}` +
    (p.events_so_far != null ? ` · ${p.events_so_far} events` : "") +
    " · approximate";
  etaText.textContent =
    p.eta_sec != null
      ? `${fmtEta(p.eta_sec)} · elapsed ${fmtDuration(p.elapsed_sec || 0)}`
      : p.elapsed_sec != null
        ? `elapsed ${fmtDuration(p.elapsed_sec)} · ETA updating…`
        : "ETA updating…";
}

function setCancelVisible(show) {
  cancelBtn.hidden = !show;
}

async function openJob(jobId) {
  activeJobId = jobId;
  setStatus(`Loading job ${jobId}…`, { loading: true });
  try {
    const job = await fetchJson(`/api/video/jobs/${jobId}`);
    if (job.status === "done") {
      progressWrap.hidden = true;
      setCancelVisible(false);
      renderStats(job);
      setStatus(`Loaded full-match job ${jobId} (approximate).`);
      stopPoll();
    } else if (job.status === "error") {
      showProgress(job);
      setCancelVisible(false);
      setStatus(job.error || "Job failed", { error: true });
      stopPoll();
    } else if (job.status === "cancelled") {
      showProgress(job);
      setCancelVisible(false);
      setStatus(job.error || "Job cancelled");
      stopPoll();
    } else {
      showProgress(job);
      setCancelVisible(true);
      setStatus(`Spotting full match… (${job.status}) — approximate`, { loading: true });
      startPoll(jobId);
    }
  } catch (err) {
    setStatus(err.message, { error: true });
  }
}

function startPoll(jobId) {
  stopPoll();
  pollTimer = setInterval(() => openJob(jobId), 4000);
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

cancelBtn.addEventListener("click", async () => {
  if (!activeJobId) return;
  cancelBtn.disabled = true;
  try {
    await fetchJson(`/api/video/jobs/${activeJobId}/cancel`, { method: "POST" });
    setStatus(`Cancelling job ${activeJobId}…`, { loading: true });
    await openJob(activeJobId);
    await refreshJobs();
  } catch (err) {
    setStatus(err.message, { error: true });
  } finally {
    cancelBtn.disabled = false;
  }
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = fileInput.files?.[0];
  if (!file) {
    setStatus("Choose a full-match video first.", { error: true });
    return;
  }
  const body = new FormData();
  body.append("file", file);
  const fps = sampleFps.value || "0.5";
  setStatus(`Uploading full match (${(file.size / 1e9).toFixed(2)} GB)…`, { loading: true });
  progressWrap.hidden = false;
  progressFill.style.width = "2%";
  progressText.textContent = "upload · approximate";
  etaText.textContent = "ETA after spotting starts";
  setCancelVisible(false);
  try {
    const res = await fetch(`/api/video/jobs?sample_fps=${encodeURIComponent(fps)}&auto_start=true`, {
      method: "POST",
      body,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    const job = await res.json();
    activeJobId = job.job_id;
    setCancelVisible(true);
    setStatus(`Uploaded. Spotting full match ${job.job_id} (approximate)…`, { loading: true });
    await refreshJobs();
    startPoll(job.job_id);
    openJob(job.job_id);
  } catch (err) {
    setStatus(err.message, { error: true });
  }
});

refreshDetector();
refreshJobs().catch((err) => setStatus(err.message, { error: true }));
