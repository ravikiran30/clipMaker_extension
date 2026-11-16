const HELPER = "http://127.0.0.1:5005";
const POLL_MS = 800;

const $ = (id) => document.getElementById(id);
const urlEl = $("url");
const startEl = $("start");
const endEl = $("end");
const durEl = $("duration");
const qualEl = $("quality");
const goEl = $("go");
const statusEl = $("status");
const pathEl = $("path");
const dotEl = $("helper-dot");
const warnEl = $("helper-warning");
const warnDetail = $("helper-detail");
const progWrap = $("progress-wrap");
const progFill = $("progress-fill");

const cancelEl = $("cancel");

let pollTimer = null;
let helperUp = false;
let currentJob = null;

/* ------------------------------------------------------- time helpers */

function parseTime(raw) {
  let s = (raw || "").trim();
  if (!s) return null;

  // People type 1.30 meaning 1:30. Treat a dot as a separator when there is no
  // colon and exactly two digits follow it (1.30, 12.05). A single digit after
  // the dot stays a decimal fraction (90.5 = ninety and a half seconds).
  if (!s.includes(":") && /^\d+\.\d{2}$/.test(s)) s = s.replace(".", ":");

  const parts = s.split(":");
  if (parts.length > 3) return null;
  let total = 0;
  for (let i = 0; i < parts.length; i++) {
    const p = parts[parts.length - 1 - i].trim();
    if (!/^\d+(\.\d+)?$/.test(p)) return null;
    total += parseFloat(p) * Math.pow(60, i);
  }
  return total;
}

function fmt(seconds) {
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

function isYouTube(u) {
  return /^https?:\/\/((www\.|m\.|music\.)?youtube\.com\/(watch\?[^ ]*\bv=[\w-]{11}|shorts\/[\w-]{11}|live\/[\w-]{11}|embed\/[\w-]{11})|youtu\.be\/[\w-]{11})/i.test(
    (u || "").trim()
  );
}

/* ------------------------------------------------------- ui helpers */

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = "status" + (kind ? " " + kind : "");
  statusEl.classList.remove("hidden");
}

function clearStatus() {
  statusEl.classList.add("hidden");
  pathEl.classList.add("hidden");
  progWrap.classList.add("hidden");
}

function setProgress(pct) {
  progWrap.classList.remove("hidden");
  progFill.style.width = Math.max(0, Math.min(100, pct || 0)) + "%";
}

function updateDuration() {
  const a = parseTime(startEl.value);
  const b = parseTime(endEl.value);
  startEl.classList.toggle("invalid", startEl.value.trim() !== "" && a === null);
  endEl.classList.toggle("invalid", endEl.value.trim() !== "" && b === null);

  if (a === null || b === null) {
    durEl.textContent = "--:--";
    durEl.className = "duration-box";
    return;
  }
  if (b <= a) {
    durEl.textContent = "invalid";
    durEl.className = "duration-box bad";
    return;
  }
  durEl.textContent = fmt(b - a);
  durEl.className = "duration-box good";
}

function setBusy(busy) {
  goEl.disabled = busy || !helperUp;
  goEl.textContent = busy ? "Working..." : "Download Clip";
  cancelEl.classList.toggle("hidden", !busy);
  if (busy) {
    cancelEl.disabled = false;
    cancelEl.textContent = "Cancel";
  } else {
    currentJob = null;
  }
}

/* ------------------------------------------------------- helper check */

// Ask Chrome to launch the helper for us (install_ondemand.bat registers it).
function launchHelper() {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendNativeMessage("com.clipmaker.launcher", { start: true }, (resp) => {
        // "missing" = the launcher isn't registered, so don't sit there waiting.
        if (chrome.runtime.lastError) return resolve("missing");
        resolve(resp && resp.ok ? true : "slow");
      });
    } catch (e) {
      resolve("missing");
    }
  });
}

async function checkHelper(allowLaunch = true) {
  try {
    const r = await fetch(HELPER + "/health", { cache: "no-store" });
    const j = await r.json();
    helperUp = true;
    dotEl.className = "dot " + (j.ok ? "up" : "down");
    if (!j.ffmpeg) {
      warnEl.classList.remove("hidden");
      warnEl.querySelector("strong").textContent = "ffmpeg is missing.";
      $("helper-cmd").textContent = "winget install Gyan.FFmpeg";
      warnDetail.textContent = "Install it, then restart the helper.";
      goEl.disabled = true;
      return;
    }
    warnEl.classList.add("hidden");
    goEl.disabled = false;
    dotEl.title = "Helper running — yt-dlp " + (j.ytdlp || "?");
  } catch (e) {
    helperUp = false;
    dotEl.className = "dot checking";
    goEl.disabled = true;

    if (allowLaunch) {
      // Try to start it before complaining at the user.
      warnEl.classList.add("hidden");
      setStatus("Starting helper...", "working");
      const launched = await launchHelper();
      // Even on a reported timeout the server is usually seconds away from
      // being up, so poll /health for a while before giving up.
      if (launched !== "missing") {
        for (let i = 0; i < 12; i++) {
          try {
            await fetch(HELPER + "/health", { cache: "no-store" });
            clearStatus();
            return checkHelper(false);
          } catch (err) {
            await new Promise((r) => setTimeout(r, 1000));
          }
        }
      }
      clearStatus();
    }

    dotEl.className = "dot down";
    dotEl.title = "Helper not running";
    warnEl.classList.remove("hidden");
    warnEl.querySelector("strong").textContent = "Helper isn't running.";
    $("helper-cmd").textContent = "CLIPMAKER\\install_ondemand.bat";
    warnDetail.textContent =
      "Run that once to let Chrome start it automatically, or start it now with start_helper.bat";
    goEl.disabled = true;
  }
}

/* ------------------------------------------------------- job polling */

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

function startPolling(jobId) {
  stopPolling();
  currentJob = jobId;
  chrome.storage.local.set({ lastJob: jobId });
  setBusy(true);
  setProgress(0);
  setStatus("Starting...", "working");

  pollTimer = setInterval(async () => {
    let j;
    try {
      const r = await fetch(`${HELPER}/status/${jobId}`, { cache: "no-store" });
      if (r.status === 404) {
        stopPolling();
        setBusy(false);
        chrome.storage.local.remove("lastJob");
        return;
      }
      j = await r.json();
    } catch (e) {
      stopPolling();
      setBusy(false);
      setStatus("Lost connection to the helper.", "error");
      return;
    }

    if (j.state === "done") {
      stopPolling();
      setProgress(100);
      chrome.storage.local.remove("lastJob");
      saveToDownloads(jobId, j);
    } else if (j.state === "cancelled") {
      stopPolling();
      setBusy(false);
      progWrap.classList.add("hidden");
      pathEl.classList.add("hidden");
      setStatus("Cancelled.", null);
      chrome.storage.local.remove("lastJob");
    } else if (j.state === "error") {
      stopPolling();
      setBusy(false);
      progWrap.classList.add("hidden");
      setStatus(j.message || "Failed.", "error");
      chrome.storage.local.remove("lastJob");
    } else if (j.state === "queued") {
      setProgress(0);
      setStatus("Queued...", "working");
    } else if (j.state === "processing") {
      setProgress(99);
      setStatus("Processing with ffmpeg (trimming to exact cut)...", "working");
    } else if (j.state === "downloading") {
      setProgress(j.pct);
      setStatus(
        j.pct > 0
          ? `Downloading ${Math.round(j.pct)}%${j.range ? "  ·  " + j.range : ""}`
          : "Contacting YouTube...",
        "working"
      );
    } else {
      setProgress(j.pct);
      setStatus(j.message || j.state, "working");
    }
  }, POLL_MS);
}

/* ------------------------------------------------------- grab video time */

// Find the YouTube tab this clip refers to: prefer one whose URL matches the
// field, else any YouTube tab in a normal window.
async function findYouTubeTab() {
  const wanted = urlEl.value.trim();
  const id = (wanted.match(/[\w-]{11}/) || [])[0];
  const tabs = await chrome.tabs.query({ windowType: "normal" });
  const yts = tabs.filter((t) => isYouTube(t.url));
  if (!yts.length) return null;
  return (id && yts.find((t) => t.url.includes(id))) || yts.find((t) => t.active) || yts[0];
}

async function grabTime(targetEl) {
  const tab = await findYouTubeTab();
  if (!tab) {
    setStatus("No YouTube tab open to read the time from.", "error");
    return;
  }
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const v = document.querySelector("video");
        return v ? v.currentTime : null;
      },
    });
    const t = res && res.result;
    if (t === null || t === undefined) {
      setStatus("Couldn't find a video player in that tab.", "error");
      return;
    }
    targetEl.value = fmt(t);
    // Keep the URL in sync with the tab we just read from.
    if (!isYouTube(urlEl.value)) urlEl.value = tab.url.split("&list=")[0];
    updateDuration();
    clearStatus();
  } catch (e) {
    setStatus("Couldn't read the player: " + e.message, "error");
  }
}

/* ------------------------------------------------------- cancel */

async function cancelJob() {
  if (!currentJob) return;
  cancelEl.disabled = true;
  cancelEl.textContent = "Cancelling...";
  try {
    await fetch(`${HELPER}/cancel/${currentJob}`, { method: "POST" });
  } catch (e) {
    /* the poll loop will report it */
  }
}

/* ------------------------------------------------------- saving */

// Chrome rejects the whole download if the filename has anything path-like in
// it, so strip those. Unicode (｜ etc.) is fine and is left alone.
function safeName(name) {
  return (name || "clip.mp4")
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, "-")
    .replace(/^[.\s]+|[.\s]+$/g, "")
    .slice(0, 150);
}

function mbOf(bytes) {
  return bytes ? ` (${(bytes / 1048576).toFixed(1)} MB)` : "";
}

function saveToDownloads(jobId, j) {
  const size = mbOf(j.size);
  setStatus("Saving to Downloads...", "working");
  pathEl.textContent = "Helper copy: " + (j.path || "");
  pathEl.classList.remove("hidden");

  const url = `${HELPER}/file/${jobId}`;

  const start = (opts, isRetry) =>
    chrome.downloads.download(opts, (id) => {
      if (chrome.runtime.lastError || id === undefined) {
        // A rejected filename is the usual cause — let Chrome name it itself.
        if (!isRetry) return start({ url }, true);
        setBusy(false);
        setStatus(
          "Clip is ready, but the browser download was blocked. Open the helper path below.",
          "done"
        );
        return;
      }
      watchDownload(id, size);
    });

  start({ url, filename: safeName(j.filename) }, false);
}

function watchDownload(id, size) {
  const finish = (delta) => {
    if (delta.id !== id) return;
    if (delta.state && delta.state.current === "complete") {
      chrome.downloads.onChanged.removeListener(finish);
      setBusy(false);
      chrome.downloads.search({ id }, (items) => {
        const f = items && items[0];
        setStatus("Saved to Downloads" + size, "done");
        if (f && f.filename) pathEl.textContent = f.filename;
      });
    } else if (delta.state && delta.state.current === "interrupted") {
      chrome.downloads.onChanged.removeListener(finish);
      setBusy(false);
      const why = delta.error ? ` (${delta.error.current})` : "";
      setStatus("Browser download failed" + why + " — clip is still in the helper's clips folder.", "error");
    }
  };
  chrome.downloads.onChanged.addListener(finish);
}

/* ------------------------------------------------------- submit */

async function submit() {
  clearStatus();

  const url = urlEl.value.trim();
  if (!isYouTube(url)) {
    urlEl.classList.add("invalid");
    setStatus("Enter a valid youtube.com or youtu.be video URL.", "error");
    return;
  }
  urlEl.classList.remove("invalid");

  const a = parseTime(startEl.value);
  const b = parseTime(endEl.value);
  if (a === null) return setStatus("Start time is not valid (use 90, 1:30 or 1:02:03).", "error");
  if (b === null) return setStatus("End time is not valid (use 90, 1:30 or 1:02:03).", "error");
  if (b <= a) return setStatus("End time must be after start time.", "error");
  if (b - a > 2 * 3600) return setStatus("Clip is longer than the 2 hour limit.", "error");

  setBusy(true);
  setStatus("Sending to helper...", "working");

  try {
    const r = await fetch(HELPER + "/clip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, start: a, end: b, quality: qualEl.value }),
    });
    const j = await r.json();
    if (!r.ok || j.error) {
      setBusy(false);
      return setStatus(j.error || "Helper rejected the request.", "error");
    }
    startPolling(j.job_id);
  } catch (e) {
    setBusy(false);
    setStatus("Could not reach the helper. Is it running?", "error");
  }
}

/* ------------------------------------------------------- init */

async function init() {
  [startEl, endEl].forEach((el) => {
    el.addEventListener("input", updateDuration);
    // Rewrite the field in canonical form when you leave it, so the way it was
    // understood is always visible (1.30 -> 1:30, 90 -> 1:30).
    el.addEventListener("blur", () => {
      const v = parseTime(el.value);
      if (v !== null) {
        el.value = fmt(v);
        updateDuration();
      }
    });
  });
  urlEl.addEventListener("input", () => urlEl.classList.remove("invalid"));
  goEl.addEventListener("click", submit);
  cancelEl.addEventListener("click", cancelJob);
  $("grab-start").addEventListener("click", () => grabTime(startEl));
  $("grab-end").addEventListener("click", () => grabTime(endEl));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !goEl.disabled) submit();
  });

  await checkHelper();

  // Prefill: the URL the background page handed us, else the active tab of a
  // normal browser window (we're our own window now, so "currentWindow" is us).
  try {
    const passed = new URLSearchParams(location.search).get("u");
    if (passed && isYouTube(passed)) {
      urlEl.value = passed.split("&list=")[0];
    } else {
      const tabs = await chrome.tabs.query({ active: true, windowType: "normal" });
      const yt = tabs.find((t) => isYouTube(t.url));
      if (yt) urlEl.value = yt.url.split("&list=")[0];
    }
  } catch (e) {
    /* ignore */
  }

  // Restore last used quality.
  chrome.storage.local.get(["quality", "lastJob"], (s) => {
    if (s.quality) qualEl.value = s.quality;
    if (s.lastJob && helperUp) startPolling(s.lastJob);
  });
  qualEl.addEventListener("change", () =>
    chrome.storage.local.set({ quality: qualEl.value })
  );

  updateDuration();
}

init();
