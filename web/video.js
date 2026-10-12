import { fetchJson, fmt } from "./common.js";

const form = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const fileLabel = document.getElementById("file-label");
const sampleFps = document.getElementById("sample-fps");
const uploadBtn = document.getElementById("upload-btn");
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
let uploadAbort = null; // AbortController for in-flight chunk
let uploadCancelled = false;
let uploading = false;
/** Partial upload that can be resumed if the same file is chosen again. */
let resumeState = null; // { jobId, filename, size, offset }

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

function fmtBytes(n) {
  if (n == null) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${Math.round(n / 1e3)} KB`;
}

function fmtClock(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}'${String(s).padStart(2, "0")}`;
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (!file) {
    fileLabel.textContent = "Choose full-match video…";
    return;
  }
  const gb = file.size / 1e9;
  fileLabel.textContent = `${file.name} (${gb.toFixed(2)} GB)`;
  if (gb > 4) {
    setStatus("File is over 4 GB — compress to 720p H.264 before uploading.", { error: true });
  } else if (
    resumeState &&
    resumeState.filename === file.name &&
    resumeState.size === file.size &&
    resumeState.offset > 0
  ) {
    setStatus(
      `Ready to resume — ${fmtBytes(resumeState.offset)} already on server. Click upload to continue.`,
      { loading: false }
    );
  } else if (gb > 0.5) {
    setStatus(
      "Large file — uploads in 8 MB chunks with live progress. Keep this tab open; failed chunks retry automatically.",
      { loading: false }
    );
  }
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
      <td>${j.status === "running" || j.status === "queued" || j.status === "uploading" ? fmtEta(j.eta_sec) : "—"}</td>
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
  if (p.stage === "uploading" || p.bytes_received != null) {
    progressText.textContent =
      `uploading · ${p.upload_pct ?? 0}% · ${fmtBytes(p.bytes_received)} / ${fmtBytes(p.size_bytes)}`;
    etaText.textContent = "Keep this tab open — chunks retry automatically";
    return;
  }
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
    } else if (job.status === "uploading") {
      showProgress(job);
      setCancelVisible(true);
      setStatus(`Upload in progress for ${jobId}…`, { loading: true });
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

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function putChunk(jobId, offset, blob, signal, attempt = 1) {
  let res;
  try {
    res = await fetch(`/api/video/uploads/${jobId}/chunk?offset=${offset}`, {
      method: "PUT",
      headers: { "Content-Type": "application/octet-stream" },
      body: blob,
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    // Network blip — retry without restarting the whole multi-GB upload.
    if (attempt < 6) {
      await sleep(400 * attempt);
      return putChunk(jobId, offset, blob, signal, attempt + 1);
    }
    throw new Error(`Network error while uploading chunk at ${fmtBytes(offset)}: ${err.message}`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    // Retry transient server / gateway failures.
    if (attempt < 6 && (res.status >= 500 || res.status === 408 || res.status === 429)) {
      await sleep(400 * attempt);
      return putChunk(jobId, offset, blob, signal, attempt + 1);
    }
    // Offset mismatch: ask caller to re-sync from server.
    if (res.status === 400 && String(detail).includes("offset mismatch")) {
      const err = new Error(detail);
      err.code = "OFFSET_MISMATCH";
      throw err;
    }
    throw new Error(detail);
  }
  return res.json();
}

async function syncResumeOffset(jobId) {
  try {
    const job = await fetchJson(`/api/video/jobs/${jobId}`);
    if (job.status === "uploading" || job.status === "queued") {
      return Number(job.bytes_received || 0);
    }
  } catch {
    /* ignore */
  }
  return null;
}

async function uploadFileChunked(file, fps) {
  uploading = true;
  uploadCancelled = false;
  uploadBtn.disabled = true;
  setCancelVisible(true);
  progressWrap.hidden = false;
  progressFill.style.width = "0%";
  progressText.textContent = "starting chunked upload…";
  etaText.textContent = `${fmtBytes(file.size)} · keep this tab open`;
  setStatus(`Preparing upload of ${file.name} (${fmtBytes(file.size)})…`, { loading: true });

  let jobId;
  let chunkSize = 8 * 1024 * 1024;
  let offset = 0;
  const canResume =
    resumeState &&
    resumeState.filename === file.name &&
    resumeState.size === file.size &&
    resumeState.jobId &&
    resumeState.offset > 0;

  try {
    if (canResume) {
      jobId = resumeState.jobId;
      const synced = await syncResumeOffset(jobId);
      if (synced == null) {
        resumeState = null;
      } else {
        offset = synced;
        setStatus(
          `Resuming upload from ${fmtBytes(offset)} / ${fmtBytes(file.size)}…`,
          { loading: true }
        );
      }
    }

    if (!jobId || !resumeState) {
      const initBody = new FormData();
      initBody.append("filename", file.name);
      initBody.append("size_bytes", String(file.size));
      const init = await fetchJson("/api/video/uploads", { method: "POST", body: initBody });
      jobId = init.job_id;
      chunkSize = init.chunk_bytes || chunkSize;
      offset = init.bytes_received || 0;
    }

    activeJobId = jobId;
    resumeState = { jobId, filename: file.name, size: file.size, offset };
    // Account for already-uploaded bytes when estimating rate after resume.
    const baselineBytes = offset;
    const baselineAt = Date.now();

    while (offset < file.size) {
      if (uploadCancelled) {
        throw new DOMException("Upload aborted", "AbortError");
      }
      const end = Math.min(offset + chunkSize, file.size);
      const blob = file.slice(offset, end);
      uploadAbort = new AbortController();
      let meta;
      try {
        meta = await putChunk(jobId, offset, blob, uploadAbort.signal);
      } catch (err) {
        if (err.code === "OFFSET_MISMATCH") {
          const synced = await syncResumeOffset(jobId);
          if (synced != null && synced !== offset) {
            offset = synced;
            resumeState = { jobId, filename: file.name, size: file.size, offset };
            continue;
          }
        }
        throw err;
      }
      offset = meta.bytes_received || end;
      resumeState = { jobId, filename: file.name, size: file.size, offset };
      const uploadPct = meta.progress?.upload_pct ?? Math.round((100 * offset) / file.size);
      const barPct = meta.progress?.pct ?? Math.round(uploadPct * 0.4);
      progressFill.style.width = `${barPct}%`;
      progressText.textContent = `uploading · ${uploadPct}% · ${fmtBytes(offset)} / ${fmtBytes(file.size)}`;
      const elapsed = (Date.now() - baselineAt) / 1000;
      const sent = Math.max(offset - baselineBytes, 0);
      const rate = sent / Math.max(elapsed, 0.5);
      const remain = (file.size - offset) / Math.max(rate, 1);
      etaText.textContent = `${fmtEta(remain)} · ${fmtBytes(rate)}/s`;
      setStatus(`Uploading full match… ${uploadPct}%`, { loading: true });
    }

    setStatus("Upload complete — starting spotting…", { loading: true });
    progressText.textContent = "upload done · starting spotting";
    const job = await fetchJson(
      `/api/video/uploads/${jobId}/finish?sample_fps=${encodeURIComponent(fps)}&auto_start=true`,
      { method: "POST" }
    );
    resumeState = null;
    activeJobId = job.job_id;
    setStatus(`Uploaded. Spotting full match ${job.job_id} (approximate)…`, { loading: true });
    await refreshJobs();
    startPoll(job.job_id);
    openJob(job.job_id);
  } catch (err) {
    if (err.name === "AbortError" || uploadCancelled) {
      setStatus("Upload cancelled.", { error: false });
      try {
        if (jobId) await fetchJson(`/api/video/uploads/${jobId}`, { method: "DELETE" });
      } catch {
        /* ignore */
      }
      resumeState = null;
      progressText.textContent = "cancelled";
      setCancelVisible(false);
    } else {
      if (jobId) {
        resumeState = { jobId, filename: file.name, size: file.size, offset };
      }
      setStatus(
        `${err.message}. Click “Upload & spot” again with the same file to resume from ${fmtBytes(offset)}.`,
        { error: true }
      );
      setCancelVisible(true);
      uploadBtn.textContent = "Resume upload";
    }
  } finally {
    uploading = false;
    uploadBtn.disabled = false;
    uploadAbort = null;
    if (!resumeState) {
      uploadBtn.textContent = "Upload & spot full match";
    }
  }
}

cancelBtn.addEventListener("click", async () => {
  cancelBtn.disabled = true;
  try {
    if (uploading && activeJobId) {
      uploadCancelled = true;
      uploadAbort?.abort();
      await fetchJson(`/api/video/uploads/${activeJobId}`, { method: "DELETE" });
      resumeState = null;
      setStatus("Upload cancelled.");
      setCancelVisible(false);
      uploadBtn.textContent = "Upload & spot full match";
      await refreshJobs();
      return;
    }
    if (!activeJobId) return;
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
  if (file.size > 4 * 1024 * 1024 * 1024) {
    setStatus("File exceeds 4 GB. Compress to 720p H.264 MP4 and try again.", { error: true });
    return;
  }
  const fps = sampleFps.value || "0.5";
  stopPoll();
  results.hidden = true;
  await uploadFileChunked(file, fps);
});

refreshDetector();
refreshJobs().catch((err) => setStatus(err.message, { error: true }));
