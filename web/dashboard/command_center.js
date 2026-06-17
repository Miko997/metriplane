// SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
// SPDX-License-Identifier: MIT

// Static Command Center snapshot - renders command_center_data.json (produced by
// `metriplane command-center export`). Themed to match the site; for the live version
// with replay use command_center_live.html.

const TYPE_COLORS = {
  cart: "#40CCC4", pallet: "#F7DE3F", human_proxy: "#FF6B6B",
  robot: "#3EDD8C", robot_proxy: "#3EDD8C", unknown: "#8EA3A8",
};
const SVG_NS = "http://www.w3.org/2000/svg";
const W = 480, H = 360, PAD = 34;
const DATA_URL =
  new URLSearchParams(location.search).get("data") || "command_center_data.json";

async function main() {
  document.getElementById("src").textContent = DATA_URL;
  let data;
  try { data = await (await fetch(DATA_URL)).json(); }
  catch (e) {
    document.getElementById("stats").innerHTML =
      `<div class="cc-stat"><span class="k">data</span><span class="v warn">missing</span></div>`;
    drawEmptyMap("No snapshot data");
    return;
  }
  renderStats(data.summary || {});
  renderMap(data.objects || []);
  renderObjects(data.objects || []);
  renderIncidents(data.incidents || []);
  renderTimeline(data.incidents || []);
  renderTraces(data.traces || []);
}

function stat(k, v, cls) {
  return `<div class="cc-stat"><span class="k">${k}</span><span class="v ${cls || ""}">${v}</span></div>`;
}
function renderStats(s) {
  document.getElementById("stats").innerHTML =
    stat("run", s.run_id || "--") + stat("objects", s.objects_count ?? 0) +
    stat("alerts", s.alerts_count ?? 0, s.alerts_count ? "warn" : "ok") +
    stat("health", (s.health && s.health.overall) || "--", "ok");
}

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

function drawControlZones(svg) {
  const iw = W - 2 * PAD;
  const ih = H - 2 * PAD;
  const zones = [
    ["main", PAD + iw * 0.08, PAD + ih * 0.21, iw * 0.62, ih * 0.60, "#40CCC4"],
    ["exit lane", PAD + iw * 0.70, PAD + ih * 0.21, iw * 0.22, ih * 0.60, "#F7DE3F"],
    ["office", PAD + iw * 0.08, PAD + ih * 0.08, iw * 0.30, ih * 0.10, "#219FC0"],
  ];

  for (const [label, x, y, width, height, color] of zones) {
    svg.appendChild(svgEl("rect", {
      x, y, width, height,
      fill: color,
      opacity: "0.045",
      stroke: color,
      "stroke-width": "0.8",
      "stroke-opacity": "0.22",
    }));
    svg.appendChild(svgEl("text", {
      x: x + 8,
      y: y + 14,
      class: "cc-zone-label",
    })).textContent = label.toUpperCase();
  }
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

function renderMap(objects) {
  const svg = document.getElementById("map"); svg.innerHTML = "";
  const pts = objects.filter((o) => o.x_m != null && o.y_m != null);
  if (!pts.length) { drawEmptyMap("No object positions"); return; }
  const xs = pts.map((o) => o.x_m), ys = pts.map((o) => o.y_m);
  let minX = Math.min(...xs), maxX = Math.max(...xs);
  let minY = Math.min(...ys), maxY = Math.max(...ys);
  const px = (maxX - minX) * 0.15 || 1, py = (maxY - minY) * 0.15 || 1;
  minX -= px; maxX += px; minY -= py; maxY += py;
  const sx = (x) => PAD + ((x - minX) / (maxX - minX)) * (W - 2 * PAD);
  const sy = (y) => H - PAD - ((y - minY) / (maxY - minY)) * (H - 2 * PAD);
  const types = new Set();

  drawControlZones(svg);
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
  svg.appendChild(svgEl("line", {
    x1: PAD,
    y1: PAD,
    x2: PAD,
    y2: H - PAD,
    stroke: "rgba(100,222,214,0.18)",
    "stroke-width": "1",
  }));

  const usedLabels = [];
  for (const o of pts) {
    types.add(o.type || "unknown");
    const color = TYPE_COLORS[o.type] || TYPE_COLORS.unknown;
    const x = sx(o.x_m), y = sy(o.y_m);
    svg.appendChild(svgEl("circle", {
      cx: x, cy: y, r: 10, fill: color, opacity: "0.14",
    }));
    svg.appendChild(svgEl("circle", {
      cx: x, cy: y, r: 5.5, fill: color,
    }));
    drawLabel(svg, o.object_id, x, y, usedLabels);
  }
  const legend = document.getElementById("legend"); legend.innerHTML = "";
  for (const ty of types) {
    const s = document.createElement("span");
    s.style.setProperty("--dot", TYPE_COLORS[ty] || TYPE_COLORS.unknown);
    s.textContent = ty; legend.appendChild(s);
  }
}

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
function renderObjects(o) {
  fillTable("objects", o.map((x) => [
    x.object_id, typeChip(x.type), x.zone,
    x.x_m != null ? x.x_m.toFixed(2) : null, x.y_m != null ? x.y_m.toFixed(2) : null]));
}
function renderIncidents(inc) {
  fillTable("incidents", inc.map((i) => ({
    rowClass: `cc-row-${safeClass(i.severity)}`,
    cells: [
      i.incident_id, i.rule_id,
      { html: `<span class="sev-${safeClass(i.severity)}">${i.severity}</span>` },
      i.status, i.summary,
    ],
  })));
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
function renderTraces(tr) {
  fillTable("traces", tr.map((t) => [
    t.object_id, t.duration_s != null ? t.duration_s + "s" : null,
    t.total_distance_m != null ? t.total_distance_m + "m" : null,
    (t.zones_visited || []).join(", "), t.gap_count]));
}

main();
