// SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
// SPDX-License-Identifier: MIT

// Metriplane Command Center (live). Reads the runner's read-only /operator/* endpoints,
// auto-refreshes the latest run, animates the run as a replay on the 2D map (highlighting
// incidents as they happen), and answers grounded questions. No CLI needed.

const RUNNER =
  new URLSearchParams(location.search).get("runner") || "http://localhost:9000";
document.getElementById("runner-url").textContent = RUNNER;

// theme-aligned colors (mirror style.css --mp tokens)
const TYPE_COLORS = {
  cart: "#40CCC4", pallet: "#F7DE3F", human_proxy: "#FF6B6B",
  robot: "#3EDD8C", robot_proxy: "#3EDD8C", unknown: "#8EA3A8",
};
const SVG_NS = "http://www.w3.org/2000/svg";
const W = 480, H = 360, PAD = 34;

let replay = { frames: [], incidents: [], workspace: null, bounds: null, i: 0, playing: false, timer: null };
let runnerSessionToken = null;

async function getJSON(p) {
  const r = await fetch(RUNNER + p);
  if (!r.ok) throw new Error(p + " " + r.status);
  const data = await r.json();
  if (data.session_token) runnerSessionToken = data.session_token;
  return data;
}
async function postJSON(p, b) {
  if (!runnerSessionToken) await getJSON("/status");
  const r = await fetch(RUNNER + p, { method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Metriplane-Token": runnerSessionToken || "",
    }, body: JSON.stringify(b || {}) });
  return r.json();
}

async function refresh() {
  try {
    const [summary, incidents, trust, frames, traces] = await Promise.all([
      getJSON("/operator/live-summary"),
      getJSON("/operator/incidents"),
      getJSON("/operator/camera-trust"),
      getJSON("/operator/frames"),
      getJSON("/operator/traces"),
    ]);
    renderStats(summary);
    renderIncidents(incidents.incidents || []);
    renderTimeline(incidents.incidents || []);
    renderTraces(traces.traces || []);
    renderCameraTrust(trust.camera_trust);
    loadReplay(frames);
  } catch (e) {
    document.getElementById("stats").innerHTML =
      `<span class="cc-stat"><span class="k">runner</span><span class="v warn">offline</span></span>`;
    document.getElementById("map-sub").textContent =
      "Runner offline";
    drawEmptyMap("Runner offline");
  }
}

function stat(k, v, cls) {
  return `<div class="cc-stat"><span class="k">${k}</span><span class="v ${cls || ""}">${v}</span></div>`;
}
function renderStats(s) {
  const has = s && (s.run_dir || s.latest_run_dir || s.run_id);
  document.getElementById("stats").innerHTML = has
    ? stat("run", s.run_id || "--") + stat("objects", s.objects_count ?? 0) +
      stat("alerts", s.alerts_count ?? 0, (s.alerts_count ? "warn" : "ok")) +
      stat("health", (s.health && s.health.overall) || "--",
           (s.health && s.health.overall) === "OK" ? "ok" : "warn")
    : stat("status", "no run yet");
}

// ---- replay -------------------------------------------------------------
function computeBounds(frames, workspace) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const f of frames) for (const o of f.objects) {
    if (o.x_m == null || o.y_m == null) continue;
    minX = Math.min(minX, o.x_m); maxX = Math.max(maxX, o.x_m);
    minY = Math.min(minY, o.y_m); maxY = Math.max(maxY, o.y_m);
  }
  for (const z of ((workspace && workspace.zones) || [])) {
    for (const pt of z.polygon || []) {
      if (!Array.isArray(pt) || pt.length < 2) continue;
      const x = Number(pt[0]), y = Number(pt[1]);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
  }
  if (!isFinite(minX)) return null;
  const px = (maxX - minX) * 0.15 || 1, py = (maxY - minY) * 0.15 || 1;
  return { minX: minX - px, maxX: maxX + px, minY: minY - py, maxY: maxY + py };
}
function sx(x, b) { return PAD + ((x - b.minX) / (b.maxX - b.minX)) * (W - 2 * PAD); }
function sy(y, b) { return H - PAD - ((y - b.minY) / (b.maxY - b.minY)) * (H - 2 * PAD); }

function svgEl(name, attrs) {
  const el = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  return el;
}

function drawEmptyMap(label) {
  const svg = document.getElementById("map");
  svg.innerHTML = "";
  svg.appendChild(svgEl("text", {
    x: W / 2,
    y: H / 2,
    "text-anchor": "middle",
    class: "cc-map-empty",
  })).textContent = label;
  document.getElementById("legend").innerHTML = "";
  document.getElementById("time").textContent = "--";
}

function safeClass(value) {
  return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "_");
}

function typeChip(type) {
  const cls = safeClass(type);
  return { html: `<span class="cc-type type-${cls}">${type || "unknown"}</span>` };
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function overlaps(a, b) {
  return !(a.r < b.l || a.l > b.r || a.b < b.t || a.t > b.b);
}

function drawLabel(svg, label, x, y, used) {
  const candidates = [
    [0, 18], [38, 4], [-38, 4], [0, -15], [44, 20], [-44, 20],
  ];
  const width = Math.max(34, label.length * 6);
  const height = 12;
  let choice = null;

  for (const [dx, dy] of candidates) {
    const lx = Math.min(Math.max(x + dx, PAD + width / 2), W - PAD - width / 2);
    const ly = Math.min(Math.max(y + dy, PAD + height), H - PAD);
    const box = { l: lx - width / 2, r: lx + width / 2, t: ly - height, b: ly + 3 };
    if (!used.some((u) => overlaps(box, u))) {
      choice = { lx, ly, box };
      break;
    }
  }

  if (!choice) {
    const ly = Math.min(y + 18, H - PAD);
    choice = { lx: x, ly, box: { l: x - width / 2, r: x + width / 2, t: ly - height, b: ly + 3 } };
  }

  used.push(choice.box);
  svg.appendChild(svgEl("text", {
    x: choice.lx,
    y: choice.ly,
    fill: "#D1D6D8",
    "font-size": "9",
    "text-anchor": "middle",
    "font-family": "JetBrains Mono, monospace",
  })).textContent = label;
}

function zoneColor(zone, idx) {
  const palette = ["#40CCC4", "#F7DE3F", "#3EDD8C", "#219FC0", "#FF6B6B"];
  const key = String((zone && zone.zone_type) || (zone && zone.zone_id) || "").toLowerCase();
  if (key.includes("exit") || key.includes("buffer")) return "#F7DE3F";
  if (key.includes("tool")) return "#3EDD8C";
  if (key.includes("station") || key.includes("work")) return "#40CCC4";
  return palette[idx % palette.length];
}

function polygonCentroid(points) {
  if (!points.length) return [W / 2, H / 2];
  const sum = points.reduce((acc, pt) => [acc[0] + pt[0], acc[1] + pt[1]], [0, 0]);
  return [sum[0] / points.length, sum[1] / points.length];
}

function drawControlZones(svg, b) {
  const zones = ((replay.workspace && replay.workspace.zones) || [])
    .filter((z) => Array.isArray(z.polygon) && z.polygon.length >= 3);
  if (!zones.length) {
    svg.appendChild(svgEl("text", {
      x: W / 2,
      y: PAD + 22,
      "text-anchor": "middle",
      class: "cc-zone-label",
    })).textContent = "ILLUSTRATIVE COORDINATES ONLY - NO WORKSPACE ZONES LOADED";
    return;
  }

  zones.forEach((zone, idx) => {
    const color = zoneColor(zone, idx);
    const points = zone.polygon
      .map((pt) => [Number(pt[0]), Number(pt[1])])
      .filter((pt) => Number.isFinite(pt[0]) && Number.isFinite(pt[1]))
      .map((pt) => [sx(pt[0], b), sy(pt[1], b)]);
    if (points.length < 3) return;
    svg.appendChild(svgEl("polygon", {
      points: points.map((p) => p.join(",")).join(" "),
      fill: color,
      opacity: "0.045",
      stroke: color,
      "stroke-width": "0.8",
      "stroke-opacity": "0.22",
    }));
    const [x, y] = polygonCentroid(points);
    svg.appendChild(svgEl("text", {
      x,
      y,
      "text-anchor": "middle",
      class: "cc-zone-label",
    })).textContent = String(zone.label || zone.zone_id || "zone").toUpperCase();
  });
}

function drawMapChrome(svg) {
  if (replay.bounds) drawControlZones(svg, replay.bounds);
  svg.appendChild(svgEl("rect", {
    x: PAD,
    y: PAD,
    width: W - 2 * PAD,
    height: H - 2 * PAD,
    fill: "none",
    stroke: "rgba(100,222,214,0.18)",
    "stroke-width": "1",
  }));
  svg.appendChild(svgEl("line", {
    x1: PAD,
    y1: H - PAD,
    x2: W - PAD,
    y2: H - PAD,
    stroke: "rgba(100,222,214,0.18)",
    "stroke-width": "1",
  }));
  svg.appendChild(svgEl("line", {
    x1: PAD,
    y1: PAD,
    x2: PAD,
    y2: H - PAD,
    stroke: "rgba(100,222,214,0.18)",
    "stroke-width": "1",
  }));
  svg.appendChild(svgEl("text", {
    x: W - PAD,
    y: H - PAD + 12,
    "text-anchor": "end",
    class: "cc-axis-label",
  })).textContent = "X METERS";
  svg.appendChild(svgEl("text", {
    x: PAD - 8,
    y: PAD + 3,
    "text-anchor": "end",
    class: "cc-axis-label",
  })).textContent = "Y";
}

function drawTrails(svg, idx, b) {
  const trails = new Map();
  for (let fIdx = 0; fIdx <= idx; fIdx++) {
    const frame = replay.frames[fIdx];
    if (!frame) continue;
    for (const o of frame.objects) {
      if (o.x_m == null || o.y_m == null) continue;
      if (!trails.has(o.object_id)) trails.set(o.object_id, { type: o.type, pts: [] });
      trails.get(o.object_id).pts.push([sx(o.x_m, b), sy(o.y_m, b)]);
    }
  }
  for (const trail of trails.values()) {
    if (trail.pts.length < 2) continue;
    svg.appendChild(svgEl("polyline", {
      points: trail.pts.map((p) => p.join(",")).join(" "),
      fill: "none",
      stroke: TYPE_COLORS[trail.type] || TYPE_COLORS.unknown,
      "stroke-width": "1.25",
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      opacity: "0.42",
    }));
  }
}

function loadReplay(payload) {
  const frames = (payload && payload.frames) || [];
  replay.frames = frames;
  replay.incidents = (payload && payload.incidents) || [];
  replay.workspace = (payload && payload.workspace) || null;
  replay.bounds = computeBounds(frames, replay.workspace);
  const scrub = document.getElementById("scrub");
  scrub.max = Math.max(0, frames.length - 1);
  if (replay.i > frames.length - 1) replay.i = Math.max(0, frames.length - 1);
  drawFrame(replay.i);
}

function activeIncidents(ts) {
  // small hold so an instantaneous incident stays visible for ~1 frame during playback
  const HOLD = 1.2;
  return replay.incidents.filter((inc) =>
    inc.opened_ts != null && ts >= inc.opened_ts - 0.01 &&
    ts <= (inc.closed_ts == null ? inc.opened_ts : inc.closed_ts) + HOLD);
}

function drawFrame(idx) {
  const svg = document.getElementById("map");
  svg.innerHTML = "";
  const b = replay.bounds;
  const frame = replay.frames[idx];
  if (!b || !frame) {
    drawEmptyMap("No replay frames");
    document.getElementById("map-sub").textContent = "Waiting for run data";
    return;
  }

  drawMapChrome(svg);
  drawTrails(svg, idx, b);

  const pos = {};
  for (const o of frame.objects) if (o.x_m != null && o.y_m != null) pos[o.object_id] = o;

  // incident highlights (drawn under the dots): connect involved objects, red glow
  const active = activeIncidents(frame.ts);
  for (const inc of active) {
    const involved = inc.object_ids.map((id) => pos[id]).filter(Boolean);
    if (involved.length >= 2) {
      svg.appendChild(svgEl("line", {
        x1: sx(involved[0].x_m, b),
        y1: sy(involved[0].y_m, b),
        x2: sx(involved[1].x_m, b),
        y2: sy(involved[1].y_m, b),
        stroke: "#FF6B6B",
        "stroke-width": "1.5",
        "stroke-dasharray": "4 3",
      }));
    }
    for (const o of involved) {
      svg.appendChild(svgEl("circle", {
        cx: sx(o.x_m, b),
        cy: sy(o.y_m, b),
        r: 13,
        fill: "none",
        stroke: "#FF6B6B",
        "stroke-width": "1.5",
        opacity: "0.8",
      }));
    }
  }

  // objects
  const usedLabels = [];
  for (const o of frame.objects) {
    if (o.x_m == null || o.y_m == null) continue;
    const cx = sx(o.x_m, b), cy = sy(o.y_m, b);
    const color = TYPE_COLORS[o.type] || TYPE_COLORS.unknown;
    svg.appendChild(svgEl("circle", {
      cx, cy, r: 10, fill: color, opacity: "0.14",
    }));
    svg.appendChild(svgEl("circle", {
      cx, cy, r: 5.5, fill: color,
    }));
    drawLabel(svg, o.object_id, cx, cy, usedLabels);
  }

  // banner for the active incident
  const sub = document.getElementById("map-sub");
  if (active.length) {
    sub.textContent = active.map((i) =>
      i.rule_id + " (" + i.object_ids.join(" / ") + ")").join(" | ");
    sub.style.color = "#FF6B6B";
  } else {
    sub.textContent = "Frame replay";
    sub.style.color = "";
  }

  document.getElementById("time").textContent =
    `t=${frame.ts.toFixed(1)}s  (${idx + 1}/${replay.frames.length})`;
  document.getElementById("scrub").value = idx;

  // legend
  const types = new Set(frame.objects.map((o) => o.type || "unknown"));
  const legend = document.getElementById("legend"); legend.innerHTML = "";
  for (const ty of types) {
    const s = document.createElement("span");
    s.style.setProperty("--dot", TYPE_COLORS[ty] || TYPE_COLORS.unknown);
    s.textContent = ty; legend.appendChild(s);
  }
}

function step() {
  if (!replay.frames.length) return;
  replay.i = (replay.i + 1) % replay.frames.length;
  drawFrame(replay.i);
}
function setPlaying(on) {
  replay.playing = on;
  document.getElementById("play-btn").textContent = on ? "Pause" : "Play";
  if (replay.timer) { clearInterval(replay.timer); replay.timer = null; }
  if (on) replay.timer = setInterval(step, 650);
}
document.getElementById("play-btn").addEventListener("click", () => setPlaying(!replay.playing));
document.getElementById("scrub").addEventListener("input", (e) => {
  setPlaying(false); replay.i = parseInt(e.target.value, 10) || 0; drawFrame(replay.i);
});

// ---- tables -------------------------------------------------------------
function fillTable(id, rows) {
  const tb = document.querySelector(`#${id} tbody`); tb.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.className = "empty-state";
    td.colSpan = document.querySelectorAll(`#${id} thead th`).length || 1;
    td.textContent = "No records";
    tr.appendChild(td);
    tb.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const cells = Array.isArray(row) ? row : row.cells;
    const tr = document.createElement("tr");
    if (!Array.isArray(row) && row.rowClass) tr.className = row.rowClass;
    for (const c of cells) {
      const td = document.createElement("td");
      if (c && c.html) td.innerHTML = c.html; else td.textContent = c == null ? "--" : c;
      tr.appendChild(td);
    }
    tb.appendChild(tr);
  }
}
function renderIncidents(incidents) {
  fillTable("incidents", incidents.map((i) => ({
    rowClass: `cc-row-${safeClass(i.severity)}`,
    cells: [
      i.incident_id, i.rule_id,
      { html: `<span class="sev-${safeClass(i.severity)}">${i.severity}</span>` },
      (i.object_ids || []).join(", "),
    ],
  })));
}
function renderObjects(objects) {
  fillTable("objects", objects.map((o) => [
    o.object_id, typeChip(o.type), o.zone,
    o.x_m != null ? o.x_m.toFixed(2) : null,
    o.y_m != null ? o.y_m.toFixed(2) : null,
  ]));
}
function renderTraces(traces) {
  fillTable("traces", traces.map((t) => [
    t.object_id,
    t.marker_id,
    t.duration_s != null ? `${Number(t.duration_s).toFixed(1)}s` : "--",
    t.total_distance_m != null ? `${Number(t.total_distance_m).toFixed(2)} m` : "--",
  ]));
}
function renderTimeline(incidents) {
  const el = document.getElementById("timeline");
  if (!el) return;
  const rows = [...incidents]
    .sort((a, b) => (a.opened_ts ?? 0) - (b.opened_ts ?? 0))
    .slice(0, 8);
  if (!rows.length) {
    el.innerHTML = `<div class="cc-timeline-empty">No timeline events</div>`;
    return;
  }
  el.innerHTML = rows.map((i) => {
    const sev = safeClass(i.severity);
    const color = sev === "critical" ? "#FF6B6B" :
      sev === "warning" ? "#F7DE3F" : "#64DED6";
    const ts = i.opened_ts != null ? `t=${Number(i.opened_ts).toFixed(1)}s` : "t=--";
    return `<div class="cc-timeline-item" style="--tl-color:${color}">` +
      `<div class="cc-timeline-time">${escapeHtml(ts)}</div>` +
      `<div class="cc-timeline-rule">${escapeHtml(i.rule_id || "unknown_rule")}</div>` +
      `<div class="cc-timeline-objects">${escapeHtml((i.object_ids || []).join(", "))}</div>` +
      `</div>`;
  }).join("");
}
function renderCameraTrust(ct) {
  if (!ct) { fillTable("camera-trust", []); document.getElementById("ct-recs").textContent = ""; return; }
  fillTable("camera-trust", Object.values(ct.camera_scores || {}).map((s) => [
    s.camera_id, { html: `<span class="st-${s.status}">${s.status}</span>` }, s.score,
    s.dropout_rate != null ? s.dropout_rate : "--",
    s.mean_disagreement_m != null ? s.mean_disagreement_m : "--",
  ]));
  document.getElementById("ct-recs").textContent = (ct.recommendations || []).join(" | ");
}

// objects table reflects the current replay frame's last position; refresh fills it too
async function refreshObjects() {
  try { const d = await getJSON("/operator/objects"); renderObjects(d.objects || []); }
  catch (e) { /* ignore */ }
}

// ---- ask ----------------------------------------------------------------
async function ask() {
  const q = document.getElementById("ask-input").value.trim();
  if (!q) return;
  const out = document.getElementById("ask-answer"); out.textContent = "...";
  try {
    const a = await postJSON("/operator/ask", { question: q });
    let html = (a.answer || "(no answer)").replace(/</g, "&lt;");
    if (a.citations && a.citations.length) {
      html += `\n<span class="cite">Evidence: ` +
        a.citations.map((c) => c.source_path + (c.record_id ? ` [${c.record_id}]` : "")).join(", ") +
        `</span>`;
    }
    out.innerHTML = html;
  } catch (e) { out.textContent = "Ask failed: " + e; }
}
document.getElementById("ask-btn").addEventListener("click", ask);
document.getElementById("ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });

// ---- run demo -----------------------------------------------------------
async function runDemo() {
  const status = document.getElementById("run-demo-status");
  const btn = document.getElementById("build-command-center-sample-btn");
  btn.disabled = true; status.textContent = "starting...";
  try {
    const start = await postJSON("/execute", { command_id: "sentinel-demo" });
    if (!start.job_id) { status.textContent = "could not start: " + (start.error || "?"); btn.disabled = false; return; }
    status.textContent = "running...";
    const poll = setInterval(async () => {
      const job = await getJSON("/jobs/" + start.job_id);
      if (job.status && job.status !== "running") {
        clearInterval(poll); btn.disabled = false;
        const ok = job.status === "completed" || job.status === "succeeded";
        status.textContent = ok ? "demo complete - press Play" : ("demo " + job.status);
        await refresh(); await refreshObjects();
        if (ok) setPlaying(true);
        setTimeout(() => (status.textContent = ""), 9000);
      }
    }, 1000);
  } catch (e) { status.textContent = "run failed: " + e; btn.disabled = false; }
}
document.getElementById("build-command-center-sample-btn").addEventListener("click", runDemo);

refresh(); refreshObjects();
setInterval(() => { refresh(); refreshObjects(); }, 5000);
