/**
 * Timeline player: dual-lane UI — scrub playhead (top), export IN/OUT (bottom).
 */
(function () {
  const root = document.getElementById("timeline-root");
  if (!root) return;

  const dataEl = document.getElementById("segments-data");
  const segments = dataEl ? JSON.parse(dataEl.textContent) : [];
  const segmentDuration = parseInt(root.dataset.segmentDuration || "30", 10);
  const cameraId = root.dataset.cameraId;

  const video = document.getElementById("preview-video");
  const scrubTrack = document.getElementById("timeline-scrub");
  const exportTrack = document.getElementById("timeline-export");
  const segmentLayer = document.getElementById("timeline-segments");
  const playhead = document.getElementById("timeline-playhead");
  const rangeHighlight = document.getElementById("timeline-range");
  const markerStart = document.getElementById("marker-start");
  const markerEnd = document.getElementById("marker-end");
  const timeCurrent = document.getElementById("time-current");
  const timeStart = document.getElementById("time-start");
  const timeEnd = document.getElementById("time-end");
  const inputFrom = document.getElementById("export-from");
  const inputTo = document.getElementById("export-to");
  const exportCount = document.getElementById("export-count");
  const exportBtn = document.getElementById("export-btn");
  const loadBtn = document.getElementById("load-timeline");
  const rangeFrom = document.getElementById("range-from");
  const rangeTo = document.getElementById("range-to");
  const btnSetIn = document.getElementById("btn-set-in");
  const btnSetOut = document.getElementById("btn-set-out");

  if (!segments.length || !scrubTrack || !exportTrack) return;

  let rangeStartMs = parseIso(root.dataset.rangeStart);
  let rangeEndMs = parseIso(root.dataset.rangeEnd);
  let selectionStartMs = parseIso(root.dataset.selectionStart) ?? rangeStartMs;
  let selectionEndMs = parseIso(root.dataset.selectionEnd) ?? rangeEndMs;
  let playheadMs = selectionStartMs;
  let activeSegment = null;
  let dragging = null;

  function parseIso(iso) {
    if (!iso) return null;
    const t = Date.parse(iso);
    return Number.isNaN(t) ? null : t;
  }

  function msToLocalInput(ms) {
    const d = new Date(ms);
    const pad = (n) => String(n).padStart(2, "0");
    return (
      d.getFullYear() +
      "-" +
      pad(d.getMonth() + 1) +
      "-" +
      pad(d.getDate()) +
      "T" +
      pad(d.getHours()) +
      ":" +
      pad(d.getMinutes())
    );
  }

  function formatClock(ms) {
    const d = new Date(ms);
    const pad = (n) => String(n).padStart(2, "0");
    return (
      d.getFullYear() +
      "-" +
      pad(d.getMonth() + 1) +
      "-" +
      pad(d.getDate()) +
      " " +
      pad(d.getHours()) +
      ":" +
      pad(d.getMinutes()) +
      ":" +
      pad(d.getSeconds())
    );
  }

  function pct(ms) {
    const span = rangeEndMs - rangeStartMs;
    if (span <= 0) return 0;
    return ((ms - rangeStartMs) / span) * 100;
  }

  function msFromPct(p) {
    return rangeStartMs + (p / 100) * (rangeEndMs - rangeStartMs);
  }

  function pctFromEvent(ev, track) {
    const rect = track.getBoundingClientRect();
    const p = ((ev.clientX - rect.left) / rect.width) * 100;
    return Math.max(0, Math.min(100, p));
  }

  function segmentAt(ms) {
    for (const seg of segments) {
      const s = parseIso(seg.start);
      const e = parseIso(seg.end);
      if (ms >= s && ms < e) return { seg, offsetSec: (ms - s) / 1000 };
    }
    const last = segments[segments.length - 1];
    const s = parseIso(last.start);
    return { seg: last, offsetSec: Math.max(0, (ms - s) / 1000) };
  }

  function segmentsInSelection() {
    return segments.filter((seg) => {
      const s = parseIso(seg.start);
      const e = parseIso(seg.end);
      return s < selectionEndMs && e > selectionStartMs;
    });
  }

  function renderSegments() {
    segmentLayer.innerHTML = "";
    segments.forEach((seg) => {
      const s = parseIso(seg.start);
      const e = parseIso(seg.end);
      const el = document.createElement("div");
      el.className = "timeline-seg-block";
      el.style.left = pct(s) + "%";
      el.style.width = Math.max(0.15, pct(e) - pct(s)) + "%";
      el.title = formatClock(s);
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        seekTo(s);
      });
      segmentLayer.appendChild(el);
    });
  }

  function updateMarkers() {
    if (selectionStartMs < rangeStartMs) selectionStartMs = rangeStartMs;
    if (selectionEndMs > rangeEndMs) selectionEndMs = rangeEndMs;
    if (selectionEndMs <= selectionStartMs) {
      selectionEndMs = Math.min(rangeEndMs, selectionStartMs + segmentDuration * 1000);
    }

    markerStart.style.left = pct(selectionStartMs) + "%";
    markerEnd.style.left = pct(selectionEndMs) + "%";
    rangeHighlight.style.left = pct(selectionStartMs) + "%";
    rangeHighlight.style.width = pct(selectionEndMs) - pct(selectionStartMs) + "%";
    playhead.style.left = pct(playheadMs) + "%";

    timeStart.textContent = formatClock(selectionStartMs);
    timeEnd.textContent = formatClock(selectionEndMs);
    if (inputFrom) inputFrom.value = msToLocalInput(selectionStartMs);
    if (inputTo) inputTo.value = msToLocalInput(selectionEndMs);

    const count = segmentsInSelection().length;
    if (exportCount) exportCount.textContent = String(count);
    if (exportBtn) exportBtn.disabled = count === 0;
  }

  function seekTo(ms) {
    playheadMs = Math.max(rangeStartMs, Math.min(rangeEndMs, ms));
    if (timeCurrent) timeCurrent.textContent = formatClock(playheadMs);
    const hit = segmentAt(playheadMs);
    if (!hit) return;
    const { seg, offsetSec } = hit;

    if (!activeSegment || activeSegment.id !== seg.id) {
      activeSegment = seg;
      video.src = seg.url;
      const onMeta = () => {
        video.currentTime = Math.min(offsetSec, video.duration || offsetSec);
        video.play().catch(() => {});
        video.removeEventListener("loadedmetadata", onMeta);
      };
      video.addEventListener("loadedmetadata", onMeta);
    } else {
      video.currentTime = Math.min(offsetSec, video.duration || offsetSec);
    }
    playhead.style.left = pct(playheadMs) + "%";
  }

  function setSelectionIn(ms) {
    selectionStartMs = Math.max(rangeStartMs, Math.min(ms, selectionEndMs - 1000));
    updateMarkers();
  }

  function setSelectionOut(ms) {
    selectionEndMs = Math.min(rangeEndMs, Math.max(ms, selectionStartMs + 1000));
    updateMarkers();
  }

  window.seekTo = seekTo;

  function onScrubClick(ev) {
    if (ev.target.closest(".timeline-playhead")) return;
    seekTo(msFromPct(pctFromEvent(ev, scrubTrack)));
  }

  function startDrag(kind, el) {
    return (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      dragging = kind;
      if (el) el.classList.add("dragging");
    };
  }

  function onDragMove(ev) {
    if (!dragging) return;

    if (dragging === "start" || dragging === "end") {
      const ms = msFromPct(pctFromEvent(ev, exportTrack));
      if (dragging === "start") {
        setSelectionIn(ms);
      } else {
        setSelectionOut(ms);
      }
      return;
    }

    if (dragging === "playhead") {
      seekTo(msFromPct(pctFromEvent(ev, scrubTrack)));
    }
  }

  function endDrag() {
    markerStart?.classList.remove("dragging");
    markerEnd?.classList.remove("dragging");
    playhead?.classList.remove("dragging");
    dragging = null;
  }

  markerStart.addEventListener("mousedown", startDrag("start", markerStart));
  markerEnd.addEventListener("mousedown", startDrag("end", markerEnd));
  playhead.querySelector(".playhead-knob")?.addEventListener("mousedown", startDrag("playhead", playhead));
  playhead.querySelector(".playhead-hit")?.addEventListener("mousedown", startDrag("playhead", playhead));
  scrubTrack.addEventListener("click", onScrubClick);
  document.addEventListener("mousemove", onDragMove);
  document.addEventListener("mouseup", endDrag);

  btnSetIn?.addEventListener("click", () => setSelectionIn(playheadMs));
  btnSetOut?.addEventListener("click", () => setSelectionOut(playheadMs));

  video.addEventListener("timeupdate", () => {
    if (!activeSegment) return;
    const base = parseIso(activeSegment.start);
    playheadMs = base + video.currentTime * 1000;
    if (playheadMs > rangeEndMs) playheadMs = rangeEndMs;
    if (timeCurrent) timeCurrent.textContent = formatClock(playheadMs);
    playhead.style.left = pct(playheadMs) + "%";
  });

  /* Range form uses GET submit; presets are plain links. */

  document.querySelectorAll(".segment-row").forEach((row) => {
    row.addEventListener("click", () => {
      const start = row.dataset.start;
      if (start) seekTo(parseIso(start));
    });
  });

  renderSegments();
  updateMarkers();
  seekTo(selectionStartMs);
})();
