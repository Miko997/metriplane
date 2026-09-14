// SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
// SPDX-License-Identifier: MIT

// Metriplane Operator Setup Wizard - operator.js
// Vanilla JS, no dependencies. Talks to runner :9000 via fetch.

'use strict';

// ── Config ────────────────────────────────────────────────────────────────────
const RUNNER = 'http://localhost:9000';
let runnerSessionToken = null;

// ── Embedded Runbook Data ─────────────────────────────────────────────────────
// Shown in the right panel; one entry per step number.
// Keep concise — full narrative is in docs/operator_ui_runbook.md.
const RUNBOOK_STEPS = {
  1: {
    title: 'Environment',
    purpose: 'Verify Python, git commit, GPU availability, and that the runner service is reachable on :9000.',
    prerequisites: ['venv activated: source .venv/bin/activate', 'Runner started: ./tools/dashboard_runner.sh'],
    happens: ['Refresh Info fetches /operator/env', 'Run Doctor checks 8 system components', 'Run Preflight checks Python deps and GPU'],
    success: 'Doctor and Preflight both show PASS. GPU listed if CUDA is available.',
    tip: 'If the runner dot is red, start it first. All other buttons depend on the runner.',
    troubleshooting: [
      { q: 'Runner shows "not connected"', a: 'Run: ./tools/dashboard_runner.sh — it must stay open in a terminal.' },
      { q: 'Doctor fails for GPU', a: 'GPU is optional. CPU mode works for all steps 3–10.' },
    ],
  },
  2: {
    title: 'Cameras',
    purpose: 'Discover USB/v4l2 camera devices and assign cam0 (required) and cam1 (optional for multi-camera mode).',
    prerequisites: ['Cameras physically connected', 'Runner connected (Step 1)'],
    happens: ['Scan calls tools/list_cameras.py and shows /dev/video* devices', 'Each row shows open/read status and resolution', 'Click cam0/cam1 buttons or type paths manually'],
    success: 'cam0 path set. cam1 path set if using multi-camera. Both show green in the scan table.',
    tip: '/dev/videoN paths are preferred. Integer indexes (0, 2) also work. /dev/v4l/by-id/ paths require manual conversion.',
    troubleshooting: [
      { q: 'Camera shows cv2_read ✗', a: 'Try another /dev/video* index — some are metadata-only nodes (no frames).' },
      { q: 'No cameras found', a: 'Check USB connections. Run: ls /dev/video*' },
    ],
  },
  3: {
    title: 'Profile',
    purpose: 'Create a named calibration profile that stores anchors, homography maps, and zones for your physical board.',
    prerequisites: ['Board dimensions known (width × height in meters)'],
    happens: ['Profile dir created at calib/profiles/local_<name>/', 'cam0/ and cam1/ subdirs added', 'Default anchors written to anchors.yaml', 'Existing profiles listed with their completeness'],
    success: 'Profile name shown in the sidebar banner. "done" badge on Step 3.',
    tip: 'Local profiles always get the "local_" prefix — shipped profiles are never overwritten.',
    troubleshooting: [
      { q: 'Profile already exists error', a: 'Click "Yes" to overwrite, or choose a different name.' },
    ],
  },
  4: {
    title: 'Anchors',
    purpose: 'Define which ArUco marker IDs are placed on the board and their exact world-space coordinates.',
    prerequisites: ['Profile created (Step 3)', 'ArUco markers physically placed at known positions'],
    happens: ['Fill defaults populates corners based on board dimensions', 'Each row: ArUco ID + X + Y in meters', 'Save writes anchors.yaml to the profile directory'],
    success: 'anchors.yaml saved with ≥ 4 entries. Badge shows "done".',
    tip: 'Corner anchors (IDs 0–3) give the most stable homography. More anchors = better accuracy.',
    troubleshooting: [
      { q: 'Calibration fails with "not enough markers"', a: 'Ensure the marker IDs here match the printed ArUco IDs on the board.' },
    ],
  },
  5: {
    title: 'Calibrate',
    purpose: 'Compute the planar homography for each camera — the mapping from pixel coordinates to world-space meters.',
    prerequisites: ['Anchors saved (Step 4)', 'All anchor markers visible in camera frame', 'Camera readable (green in Step 2)'],
    happens: ['Runs tools/calibrate_planar_homography.py for each camera', 'Camera index is converted: /dev/video0 → 0', 'Captures frames until timeout or max-frames reached', 'Writes mapping_raw.yaml to profile/cam0/ and profile/cam1/'],
    success: 'mapping_raw.yaml written for each camera. Output log shows "PASS".',
    tip: 'Increase timeout if the board is cluttered. Reduce max-frames for faster calibration. Keep all markers visible.',
    troubleshooting: [
      { q: 'Calibration times out', a: 'Ensure all anchor markers are in frame, unobstructed, and IDs match anchors.yaml.' },
      { q: 'OpenCV index error', a: 'Use /dev/videoN or an integer (0, 2) — /dev/v4l/by-id/ paths are not supported here.' },
    ],
  },
  6: {
    title: 'Validate',
    purpose: 'Verify that cam0 and cam1 agree on world-space positions for the same markers. Detects miscalibration.',
    prerequisites: ['Both cameras calibrated (Step 5)', 'Multi-camera mode selected'],
    happens: ['Planar alignment runs tools/report_alignment.py (no intrinsics needed)', 'Computes per-marker position delta between cameras', 'Result tiles show mean and max distance in cm'],
    success: 'Mean distance < 1 cm. Max distance < 2 cm. Result tiles show green "Good".',
    tip: 'Single-camera setups can skip this step. Full Diagnostic requires intrinsics.yaml (run calibrate_intrinsics_chessboard.py first).',
    troubleshooting: [
      { q: 'Mean distance > 2 cm', a: 'Re-run calibration for one or both cameras. Check board is flat and markers are at correct positions.' },
      { q: '"Full Diagnostic" requires intrinsics', a: 'Run tools/calibrate_intrinsics_chessboard.py for each camera first, or use the planar-only path.' },
    ],
  },
  7: {
    title: 'Zones',
    purpose: 'Define named spatial zones as polygons in world-space meters. Used for dwell time and transition analytics.',
    prerequisites: ['Profile created (Step 3)', 'Board dimensions known'],
    happens: ['Presets auto-fill polygon vertices from board dimensions', 'Each zone: name + polygon [[x1,y1],[x2,y2],…]', 'Save writes zones.yaml to the profile directory'],
    success: 'zones.yaml saved with ≥ 1 zone. Badge shows "done".',
    tip: 'Use "Left / Right split" preset for the standard 2-zone workflow. Polygon coordinates must stay within board bounds.',
    troubleshooting: [
      { q: 'Zone events not generated', a: 'Ensure record_jsonl is enabled in the config (Step 8). Zones only appear in session JSONL.' },
    ],
  },
  8: {
    title: 'Config',
    purpose: 'Generate a YAML runtime config validated against the metriplane.config.Config schema. Save to configs/local/.',
    prerequisites: ['Profile with mapping_raw.yaml for each camera', 'Zones.yaml written (Step 7)'],
    happens: ['Config builder produces name/device/mapping_file fields (not id/source/mapping)', 'YAML preview updates live', 'Save validates camera schema before writing — rejects bad field names', 'Config hash logged for reproducibility'],
    success: 'Config saved to configs/local/<name>.yaml. Hash shown in log. Badge "done".',
    tip: 'Use CPU backend unless you have CuPy + CUDA set up. The config preview shows exactly what will be written.',
    troubleshooting: [
      { q: '"Config camera schema invalid"', a: 'Regenerate via the UI (Step 8). Manual edits must use name/device/mapping_file — not id/source/mapping.' },
      { q: '"mapping_file not found on disk"', a: 'Complete Step 5 (Calibrate) for both cameras before saving the config.' },
    ],
  },
  9: {
    title: 'Run',
    purpose: 'Start the live fusion pipeline using the saved config. Monitor job output and run directory.',
    prerequisites: ['Config saved (Step 8)', 'Cameras connected', 'Runner connected'],
    happens: ['Runs: python -m metriplane.run_fusion --config … --runs-dir <platform-runs-dir> --run-id …', 'Output streamed to the Job Output log', 'Session JSONL written to the platform runs directory', 'Latest Run Directory updates after completion'],
    success: 'session.jsonl is non-zero. Job output shows no errors. "Latest Run Directory" shows correct size.',
    tip: 'Set duration to 0 for unlimited run. Click Stop to cancel early. Session JSONL is not tracked in git (use checksum in Step 10).',
    troubleshooting: [
      { q: '"cam0 skipped: missing both device and index"', a: 'Re-generate config in Step 8. The saved config has wrong camera field names.' },
      { q: '"No usable cameras"', a: 'Check mapping_raw.yaml exists for each camera. Re-run Step 5.' },
    ],
  },
  10: {
    title: 'Export',
    purpose: 'Generate zone analytics CSVs and ID stability report from the session JSONL. Compute SHA256 for evidence.',
    prerequisites: ['Session JSONL from Step 9 (non-zero size)'],
    happens: ['Zone Report: tools/zones_report_jsonl.py → dwell, events, transitions CSVs', 'ID Stability: tools/analyze_id_stability_jsonl.py → coverage and gaps per object', 'SHA256: streams file checksum for evidence/manifest.csv'],
    success: 'CSVs written to evidence/experiments/. SHA256 shown in log. Evidence manifest can be updated.',
    tip: 'Export buttons are disabled if the session is empty (0 bytes). Re-run Step 9 if no data appears.',
    troubleshooting: [
      { q: 'Export buttons disabled', a: 'Session is empty — run failed before writing frames. Check Step 9 logs and fix config.' },
      { q: '"session must be under the platform runs directory"', a: 'Only sessions in the active platform runs directory are accepted. Do not manually move the session file.' },
    ],
  },
};
const POLL_INTERVAL_MS = 1500;

// ── Operator State ────────────────────────────────────────────────────────────
const state = {
  runnerConnected: false,
  // Cameras
  cam0: '0',
  cam1: '',
  multiCam: true,
  // Profile
  profile: '',          // active profile name (after create/select)
  boardW: 0.55,
  boardH: 0.40,
  // Anchors (array of {id, x, y})
  anchors: [],
  // Run
  activeJobId: null,
  activeJobCmdId: null,
  runsDir: null,
  latestRunDir: null,
  latestSessionPath: null,
  // Config
  savedConfigPath: null,
  // Step statuses: 'idle' | 'running' | 'done' | 'error'
  stepStatus: {},
  // Run state
  lastRunOk: null,     // null=never ran, true=last run succeeded, false=last run failed
  exportEnabled: false, // true only when the session is non-empty and under the active run root
  // Calibration success tracking for Step 5 navigation guard
  calibDone: { cam0: false, cam1: false },
};

// ── Active profile helper ─────────────────────────────────────────────────────

function setActiveProfile(name) {
  state.profile = name;
  // Update sidebar profile banner (always visible)
  const el = document.getElementById('sidebar-profile-name');
  if (el) el.textContent = name || 'none selected';
  // Sync anchor input if visible
  syncAnchorProfileInput();
}

// ── Utility: runner API ───────────────────────────────────────────────────────

async function opApi(method, path, body) {
  try {
    if (method !== 'GET' && !runnerSessionToken) {
      const statusResp = await fetch(RUNNER + '/status', { cache: 'no-store' });
      const status = await statusResp.json();
      runnerSessionToken = status.session_token || null;
    }
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (method !== 'GET' && runnerSessionToken) {
      opts.headers['X-Metriplane-Token'] = runnerSessionToken;
    }
    if (body && method !== 'GET') opts.body = JSON.stringify(body);
    const resp = await fetch(RUNNER + path, opts);
    const data = await resp.json();
    if (data.session_token) runnerSessionToken = data.session_token;
    return data;
  } catch (e) {
    return { error: String(e) };
  }
}

async function runnerPost(path, body = {}) {
  return opApi('POST', path, body);
}

// ── Runner connection check ───────────────────────────────────────────────────

async function checkRunner() {
  const wasConnected = state.runnerConnected;
  const previousRunnerSessionToken = runnerSessionToken;
  try {
    const d = await opApi('GET', '/status');
    if (d && d.service) {
      const runnerRestarted = Boolean(
        wasConnected &&
        previousRunnerSessionToken &&
        d.session_token &&
        d.session_token !== previousRunnerSessionToken
      );
      state.runnerConnected = true;
      const pill = document.getElementById('runner-pill');
      const lbl = document.getElementById('runner-label');
      if (pill) { pill.classList.add('connected'); }
      if (lbl) lbl.textContent = 'runner :9000 ✓';
      if (!wasConnected || runnerRestarted) await refreshLatestRun();
    } else {
      setRunnerDisconnected();
    }
  } catch {
    setRunnerDisconnected();
  }
}

function setRunnerDisconnected() {
  state.runnerConnected = false;
  const pill = document.getElementById('runner-pill');
  if (pill) pill.classList.remove('connected');
  const lbl = document.getElementById('runner-label');
  if (lbl) lbl.textContent = 'runner :9000 — not connected';
}

// ── Step navigation ───────────────────────────────────────────────────────────

let currentStep = 1;

function goStep(n) {
  // Hide old
  const old = document.getElementById('step-' + currentStep);
  if (old) old.classList.remove('active');
  document.querySelectorAll('.step-item').forEach(el => el.classList.remove('active'));

  currentStep = n;

  // Show new
  const panel = document.getElementById('step-' + n);
  if (panel) panel.classList.add('active');
  const item = document.querySelector('.step-item[data-step="' + n + '"]');
  if (item) item.classList.add('active');

  // Panel-specific init
  if (n === 2) { /* cameras ready */ }
  if (n === 3) loadProfiles();
  if (n === 4) syncAnchorProfileInput();
  if (n === 5) updateCalibPreviews();
  if (n === 6) updateAlignPreview();
  if (n === 7) updateZonesYamlPreview();
  if (n === 8) { syncConfigFilename(); updateConfigPreview(); }
  if (n === 9) { loadConfigs(); updateRunPreview(); refreshLatestRun(); }
  if (n === 10) refreshLatestRunForExport();

  // Sync horizontal stepper and right runbook panel
  updateHStepper(n);
  updateRunbookPanel(n);
}

// ── Horizontal stepper sync ───────────────────────────────────────────────────

function updateHStepper(activeStep) {
  document.querySelectorAll('.h-step[data-step]').forEach(el => {
    el.classList.remove('active', 'done', 'error');
    const s = parseInt(el.dataset.step);
    const status = state.stepStatus[s];
    if (s === activeStep) {
      el.classList.add('active');
    } else if (status === 'done') {
      el.classList.add('done');
    } else if (status === 'error') {
      el.classList.add('error');
    }
  });
}

// ── Right runbook panel ───────────────────────────────────────────────────────

function updateRunbookPanel(step) {
  const data = RUNBOOK_STEPS[step];
  if (!data) return;

  const purpose  = document.getElementById('rb-purpose');
  const prereqEl = document.getElementById('rb-prerequisites');
  const happenEl = document.getElementById('rb-happens');
  const success  = document.getElementById('rb-success');
  const tip      = document.getElementById('rb-tip');
  const trouble  = document.getElementById('rb-trouble');
  const troubleBody = document.getElementById('rb-trouble-body');

  if (purpose)  purpose.textContent = data.purpose || '';
  if (success)  success.textContent = data.success || '';

  if (prereqEl) {
    prereqEl.innerHTML = (data.prerequisites || [])
      .map(p => `<li>${escHtml(p)}</li>`).join('');
  }
  if (happenEl) {
    happenEl.innerHTML = (data.happens || [])
      .map(h => `<li>${escHtml(h)}</li>`).join('');
  }
  if (tip) {
    if (data.tip) {
      tip.textContent = data.tip;
      tip.style.display = 'block';
    } else {
      tip.style.display = 'none';
    }
  }
  if (trouble && troubleBody) {
    if (data.troubleshooting && data.troubleshooting.length) {
      trouble.style.display = 'block';
      troubleBody.innerHTML = data.troubleshooting.map(t => `
        <div class="rb-trouble-item">
          <div class="rb-trouble-q">${escHtml(t.q)}</div>
          <div class="rb-trouble-a">${escHtml(t.a)}</div>
        </div>`).join('');
    } else {
      trouble.style.display = 'none';
    }
  }
}

function setStepStatus(step, status) {
  state.stepStatus[step] = status;
  const badge = document.getElementById('step-' + step + '-badge');
  if (badge) {
    badge.textContent = status;
    badge.className = 'step-status-badge ' + status;
  }
  const item = document.querySelector('.step-item[data-step="' + step + '"]');
  if (item) {
    item.classList.remove('done', 'error', 'running');
    if (status === 'done' || status === 'error' || status === 'running') {
      item.classList.add(status);
    }
  }
}

// ── Output log helpers ────────────────────────────────────────────────────────

function showLog(logId, html, cls) {
  const el = document.getElementById(logId);
  if (!el) return;
  el.classList.add('visible');
  el.innerHTML = html;
  if (cls) el.className = 'output-log visible';
  el.scrollTop = el.scrollHeight;
}

function appendLog(logId, text) {
  const el = document.getElementById(logId);
  if (!el) return;
  el.classList.add('visible');
  el.textContent += text;
  el.scrollTop = el.scrollHeight;
}

function logStatus(logId, status, text) {
  const cls = { succeeded: 'log-pass', failed: 'log-fail', running: 'log-running', cancelled: 'log-fail', timed_out: 'log-fail' }[status] || 'log-info';
  const label = { succeeded: '✓ PASS', failed: '✗ FAIL', running: '● Running…', cancelled: '⊘ Cancelled', timed_out: '⏱ Timed out' }[status] || status;
  showLog(logId, `<span class="log-status ${cls}">${label}</span><br>${escHtml(text)}`);
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Job polling ───────────────────────────────────────────────────────────────

function pollJob(jobId, logId, stepId, onDone) {
  const timer = setInterval(async () => {
    const job = await opApi('GET', '/jobs/' + jobId);
    if (!job || job.error) {
      clearInterval(timer);
      showLog(logId, '<span class="log-fail">✗ Job poll failed: ' + escHtml(job ? job.error : 'unknown') + '</span>');
      setStepStatus(stepId, 'error');
      if (onDone) onDone(null);
      return;
    }
    const out = (job.stdout || '') + (job.stderr ? '\n--- STDERR ---\n' + job.stderr : '');
    logStatus(logId, job.status, out);

    if (job.status !== 'running') {
      clearInterval(timer);
      const ok = job.status === 'succeeded';
      setStepStatus(stepId, ok ? 'done' : 'error');
      if (onDone) onDone(job);
    }
  }, POLL_INTERVAL_MS);
}

// ── Run allowlisted command ───────────────────────────────────────────────────

async function runAllowlisted(commandId, stepId) {
  if (!state.runnerConnected) {
    alert('Runner not connected. Start it with: ./tools/dashboard_runner.sh');
    return;
  }
  setStepStatus(stepId, 'running');
  const logId = stepId + '-log';
  showLog(logId, '<span class="log-running">● Running...</span>');
  const resp = await opApi('POST', '/execute', { command_id: commandId });
  if (resp.error) {
    showLog(logId, '<span class="log-fail">✗ ' + escHtml(resp.error) + '</span>');
    setStepStatus(stepId, 'error');
    return;
  }
  pollJob(resp.job_id, logId, stepId);
}

// ── Step 1: Environment ───────────────────────────────────────────────────────

function renderEnv(d) {
  if (!d || d.error) { return; }
  document.getElementById('env-python').textContent = (d.python || '—').split('\n')[0];
  document.getElementById('env-git').textContent   = d.git_commit || '—';
  document.getElementById('env-gpu').textContent   = d.gpu || '—';
  document.getElementById('env-root').textContent  = d.repo_root || '—';

  // Python executable path
  const exeEl = document.getElementById('env-python-exe');
  if (exeEl) exeEl.textContent = d.python_executable || '—';

  // OpenCV status
  const cv2El = document.getElementById('env-cv2');
  if (cv2El) {
    if (d.cv2_available === true) {
      const arucoLabel = d.aruco_available ? ' + aruco ✓' : ' (aruco missing)';
      cv2El.textContent = 'cv2 ' + (d.cv2_version || '') + arucoLabel;
      cv2El.style.color = d.aruco_available ? 'var(--status-online)' : 'var(--status-warning)';
    } else if (d.cv2_available === false) {
      cv2El.textContent = 'NOT installed ✗';
      cv2El.style.color = 'var(--status-error)';
    } else {
      cv2El.textContent = '—';
      cv2El.style.color = '';
    }
  }

  // cv2 warning banner
  const warnEl = document.getElementById('env-cv2-warn');
  if (warnEl) {
    if (d.python_warning) {
      warnEl.textContent = '⚠ ' + d.python_warning;
      warnEl.style.display = 'block';
    } else {
      warnEl.style.display = 'none';
    }
  }
}

// ── Step 2: Cameras ───────────────────────────────────────────────────────────

async function discoverCameras() {
  const status  = document.getElementById('cam-scan-status');
  const wrapper = document.getElementById('camera-table-wrapper');
  if (status)  status.textContent = 'Scanning…';
  if (wrapper) wrapper.innerHTML  = '';

  const data = await opApi('GET', '/operator/cameras');
  if (data.error) {
    if (status) status.textContent = 'Error: ' + data.error;
    return;
  }

  const cams        = data.cameras       || [];
  const readable    = data.readable      || 0;
  const captureCap  = data.capture_capable || 0;
  const metaOnlyN   = data.metadata_only || 0;

  if (status) {
    status.textContent =
      `${cams.length} device(s) found — ${readable} readable, ${metaOnlyN} metadata-only`;
  }

  if (!cams.length) {
    if (wrapper) wrapper.innerHTML = '<div class="notice warn">No /dev/video* devices found. Check USB connections and run: ls /dev/video*</div>';
    return;
  }

  // Troubleshooting notice: capture nodes detected but OpenCV cannot produce frames
  let noticeHtml = '';
  if (readable === 0 && captureCap > 0) {
    noticeHtml = `<div class="notice warn">
      ⚠ Linux sees ${captureCap} capture device(s) but OpenCV could not read frames.<br>
      Check device ownership and video group:<br>
      <code>fuser -v /dev/video* 2>&amp;1 | head -20</code><br>
      <code>groups | grep video</code>
    </div>`;
  }

  // Table header includes Type column
  let html = `<table class="camera-table">
    <thead>
      <tr>
        <th>Device</th><th>Type</th>
        <th>Open(idx)</th><th>Read(idx)</th>
        <th>Resolution</th><th>by-id</th><th>Set as</th>
      </tr>
    </thead><tbody>`;

  cams.forEach((c, i) => {
    const recommended = c.recommended_for_operator === true;
    const metaRow     = c.is_metadata_only === true;

    // Row dot
    const dotCls = recommended ? 'cam-ok' : metaRow ? 'cam-fail' : 'cam-unknown';

    // Open / Read values — prefer index-based fields, fall back to legacy
    const openVal = c.cv2_open_index === true  ? '✓'
                  : c.cv2_open_index === false ? '✗'
                  : c.cv2_open === true        ? '✓'
                  : c.cv2_open === false       ? '✗' : '—';
    const readVal = c.cv2_read_index === true  ? '✓'
                  : c.cv2_read_index === false ? '✗'
                  : c.cv2_read === true        ? '✓'
                  : c.cv2_read === false       ? '✗' : '—';

    const res  = (c.width && c.height) ? c.width + '×' + c.height : '—';
    const byid = c.by_id
      ? `<span title="${escHtml(c.by_id)}">${escHtml(c.by_id.split('/').pop())}</span>`
      : '—';

    // Type label
    const typeLabel = metaRow
      ? '<span style="color:var(--text-muted);font-size:10px">metadata-only</span>'
      : c.is_capture_capable
        ? '<span style="color:var(--success);font-size:10px">capture</span>'
        : '<span style="color:var(--text-muted);font-size:10px">unknown</span>';

    // Reason tooltip on device name
    const reasonSpan = c.reason
      ? ` <span style="font-size:10px;color:var(--text-muted)" title="${escHtml(c.reason)}">ⓘ</span>`
      : '';

    // Assignment buttons — disabled for non-recommended (metadata-only or cv2 fail)
    const btnAttr    = recommended ? '' : 'disabled style="opacity:0.35;cursor:not-allowed"';
    const btnOnclick = recommended
      ? `onclick="assignCamera('${escHtml(c.path)}','ROLE',${i})"`
      : 'onclick="return false"';

    html += `<tr style="${metaRow ? 'opacity:0.6' : ''}">
      <td><span class="cam-dot ${dotCls}"></span>${escHtml(c.path)}${reasonSpan}</td>
      <td>${typeLabel}</td>
      <td>${openVal}</td><td>${readVal}</td><td>${res}</td><td>${byid}</td>
      <td>
        <button class="cam-select-btn" id="cam0-sel-${i}"
          ${btnAttr} ${btnOnclick.replace('ROLE', 'cam0')}>cam0</button>
        <button class="cam-select-btn" id="cam1-sel-${i}"
          ${btnAttr} ${btnOnclick.replace('ROLE', 'cam1')}>cam1</button>
      </td>
    </tr>`;
  });

  html += '</tbody></table>';
  if (wrapper) wrapper.innerHTML = noticeHtml + html;
}

function assignCamera(path, role, rowIdx) {
  if (role === 'cam0') {
    state.cam0 = path;
    document.getElementById('cam0-path').value = path;
  } else {
    state.cam1 = path;
    document.getElementById('cam1-path').value = path;
  }
}

function saveCamerasGoNext() {
  state.cam0 = document.getElementById('cam0-path').value.trim() || '0';
  state.cam1 = document.getElementById('cam1-path').value.trim() || '';
  state.multiCam = state.cam1 !== '';
  setStepStatus(2, state.cam0 ? 'done' : 'idle');
  goStep(3);
}

// ── Step 3: Profile ───────────────────────────────────────────────────────────

async function loadProfiles() {
  const el = document.getElementById('profile-list');
  if (!el) return;
  el.textContent = 'Loading…';
  const data = await opApi('GET', '/operator/profiles');
  if (data.error || !data.profiles) {
    el.textContent = 'Error: ' + (data.error || 'no profiles');
    return;
  }
  if (!data.profiles.length) {
    el.innerHTML = '<span style="color:var(--text-muted)">No profiles yet. Create one below.</span>';
    return;
  }
  let html = '<table class="camera-table"><thead><tr><th>Name</th><th>Anchors</th><th>cam0</th><th>cam1</th><th>Zones</th><th></th></tr></thead><tbody>';
  data.profiles.forEach(p => {
    const local = p.is_local ? '<span style="color:var(--accent-cyan);font-size:10px">local</span>' : '';
    html += `<tr>
      <td>${escHtml(p.name)} ${local}</td>
      <td>${p.has_anchors ? '✓' : '—'}</td>
      <td>${p.has_cam0_mapping ? '✓' : '—'}</td>
      <td>${p.has_cam1_mapping ? '✓' : '—'}</td>
      <td>${p.has_zones ? '✓' : '—'}</td>
      <td><button class="cam-select-btn" onclick="selectProfile('${escHtml(p.name)}')">Use</button></td>
    </tr>`;
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

function selectProfile(name) {
  setActiveProfile(name);
  document.getElementById('profile-name').value = name.replace(/^local_/, '');
  setStepStatus(3, 'done');
  showLog('step-3-log', '<span class="log-pass">✓ Profile selected: ' + escHtml(name) + '</span>');
}

async function createProfile() {
  const name = (document.getElementById('profile-name').value || '').trim();
  const width_m = parseFloat(document.getElementById('board-width').value) || 0.55;
  const height_m = parseFloat(document.getElementById('board-height').value) || 0.40;
  const camSel = document.getElementById('profile-cams').value;
  const cameras = camSel === 'single' ? ['cam0'] : ['cam0', 'cam1'];

  if (!name) { alert('Enter a profile name.'); return; }
  setStepStatus(3, 'running');
  showLog('step-3-log', '<span class="log-running">● Creating profile…</span>');

  const resp = await runnerPost('/operator/create-profile', { name, width_m, height_m, cameras });
  if (resp.error && resp.error.includes('already exists')) {
    const ok = confirm(resp.error + '\n\nOverwrite?');
    if (!ok) { setStepStatus(3, 'idle'); showLog('step-3-log', ''); return; }
    const r2 = await runnerPost('/operator/create-profile', { name, width_m, height_m, cameras, overwrite: true });
    handleProfileCreateResult(r2);
  } else {
    handleProfileCreateResult(resp);
  }
}

function handleProfileCreateResult(resp) {
  if (resp.error) {
    showLog('step-3-log', '<span class="log-fail">✗ ' + escHtml(resp.error) + '</span>');
    setStepStatus(3, 'error');
    return;
  }
  // Use setActiveProfile so sidebar banner + anchor input both update
  setActiveProfile(resp.profile);
  state.boardW = resp.board_size?.width_m || state.boardW;
  state.boardH = resp.board_size?.height_m || state.boardH;
  state.multiCam = (resp.cameras || []).includes('cam1');
  setStepStatus(3, 'done');
  showLog('step-3-log', '<span class="log-pass">✓ Profile created: ' + escHtml(resp.profile) + '\n  anchors path: ' + escHtml(resp.anchors_path) + '\n  dirs: ' + (resp.created_dirs || []).join(', ') + '</span>');
  loadProfiles();
  fillDefaultAnchors();
}

// ── Step 4: Anchors ───────────────────────────────────────────────────────────

function syncAnchorProfileInput() {
  const el = document.getElementById('anchor-profile');
  if (el && state.profile) el.value = state.profile;
}

function fillDefaultAnchors() {
  const w = state.boardW || 0.55;
  const h = state.boardH || 0.40;
  state.anchors = [
    { id: 0, x: 0.0, y: 0.0 },
    { id: 1, x: 0.0, y: h },
    { id: 2, x: w, y: 0.0 },
    { id: 3, x: w, y: h },
  ];
  renderAnchorTable();
}

function renderAnchorTable() {
  const tbody = document.getElementById('anchor-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  state.anchors.forEach((a, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="number" class="anchor-id" data-i="${i}" value="${a.id}" min="0" max="999" style="width:60px"></td>
      <td><input type="number" class="anchor-x"  data-i="${i}" value="${a.x}" step="0.01" style="width:80px"></td>
      <td><input type="number" class="anchor-y"  data-i="${i}" value="${a.y}" step="0.01" style="width:80px"></td>
      <td><button class="anchor-del" data-i="${i}" onclick="removeAnchorRow(${i})">✕</button></td>
    `;
    tbody.appendChild(tr);
  });
  // Bind live changes
  tbody.querySelectorAll('input').forEach(inp => {
    inp.addEventListener('change', readAnchorsFromTable);
  });
}

function readAnchorsFromTable() {
  const rows = document.querySelectorAll('#anchor-tbody tr');
  const anchors = [];
  rows.forEach(row => {
    const id = parseInt(row.querySelector('.anchor-id')?.value || '0');
    const x = parseFloat(row.querySelector('.anchor-x')?.value || '0');
    const y = parseFloat(row.querySelector('.anchor-y')?.value || '0');
    anchors.push({ id, x, y });
  });
  state.anchors = anchors;
}

function addAnchorRow() {
  readAnchorsFromTable();
  state.anchors.push({ id: state.anchors.length, x: 0.0, y: 0.0 });
  renderAnchorTable();
}

function removeAnchorRow(i) {
  readAnchorsFromTable();
  state.anchors.splice(i, 1);
  renderAnchorTable();
}

async function saveAnchors() {
  readAnchorsFromTable();
  const profile = state.profile || document.getElementById('anchor-profile')?.value?.trim();
  if (!profile) { alert('Select or create a profile first (Step 3).'); return; }
  if (state.anchors.length < 4) { alert('At least 4 anchors required.'); return; }

  setStepStatus(4, 'running');
  showLog('step-4-log', '<span class="log-running">● Saving anchors…</span>');

  const anchors = state.anchors.map(a => ({ id: a.id, world_xy: [a.x, a.y] }));
  const resp = await runnerPost('/operator/create-profile', {
    name: profile.replace(/^local_/, ''),
    width_m: state.boardW,
    height_m: state.boardH,
    anchors,
    cameras: state.multiCam ? ['cam0', 'cam1'] : ['cam0'],
    overwrite: true,
  });
  if (resp.error) {
    showLog('step-4-log', '<span class="log-fail">✗ ' + escHtml(resp.error) + '</span>');
    setStepStatus(4, 'error');
  } else {
    showLog('step-4-log', '<span class="log-pass">✓ Saved ' + resp.anchors_count + ' anchors to ' + escHtml(resp.anchors_path) + '</span>');
    setStepStatus(4, 'done');
  }
}

// ── Camera path → cv2 index conversion (mirrors operator_api._resolve_cv2_index) ──────

/**
 * Convert a camera path to a cv2-compatible integer index string.
 * calibrate_planar_homography.py passes --cam directly to cv2.VideoCapture()
 * which requires an integer, not a /dev/video* path.
 *
 * Returns the integer string, or null if conversion is not possible.
 * /dev/video0  → '0'
 * /dev/video2  → '2'
 * '0'          → '0'
 * /dev/v4l/... → null
 */
function toCv2Index(cam) {
  if (!cam) return null;
  // Already an integer index
  if (/^\d{1,2}$/.test(cam)) return cam;
  // /dev/videoN → N
  const m = cam.match(/^\/dev\/video(\d+)$/);
  if (m) return m[1];
  return null;  // by-id or other unsupported format
}

// ── Step 5: Calibrate ─────────────────────────────────────────────────────────

function updateCalibPreviews() {
  const profile = state.profile;
  const timeout = document.getElementById('calib-timeout')?.value || 30;
  const maxframes = document.getElementById('calib-maxframes')?.value || 600;
  const preview0 = document.getElementById('calib-cam0-preview');
  const preview1 = document.getElementById('calib-cam1-preview');
  const cam1sec = document.getElementById('calib-cam1-section');

  if (cam1sec) cam1sec.style.display = state.multiCam ? 'block' : 'none';

  const base = 'python tools/calibrate_planar_homography.py';
  // Show converted index (API will also convert, preview mirrors actual command)
  const idx0 = toCv2Index(state.cam0) ?? state.cam0;
  const idx1 = toCv2Index(state.cam1 || '2') ?? (state.cam1 || '2');

  if (preview0) {
    const warn = toCv2Index(state.cam0) === null ? ' ⚠ unsupported path — use /dev/videoN or integer' : '';
    preview0.innerHTML = '<span class="cmd-label">cam0 command preview' + escHtml(warn) + '</span>' +
      escHtml(`${base} --cam ${idx0} --anchors calib/profiles/${profile}/anchors.yaml --out calib/profiles/${profile}/cam0/mapping_raw.yaml --no-preview --timeout-s ${timeout} --max-frames ${maxframes}`);
  }
  if (preview1) {
    const warn1 = toCv2Index(state.cam1 || '2') === null ? ' ⚠ unsupported path — use /dev/videoN or integer' : '';
    preview1.innerHTML = '<span class="cmd-label">cam1 command preview' + escHtml(warn1) + '</span>' +
      escHtml(`${base} --cam ${idx1} --anchors calib/profiles/${profile}/anchors.yaml --out calib/profiles/${profile}/cam1/mapping_raw.yaml --no-preview --timeout-s ${timeout} --max-frames ${maxframes}`);
  }
}

// ── Step 5: calibration navigation guard ─────────────────────────────────────

function updateCalibNextButton() {
  const btn = document.getElementById('calib-next-btn');
  if (!btn) return;
  const cam0ok = state.calibDone.cam0;
  const cam1ok = state.calibDone.cam1;
  const required = !state.multiCam ? cam0ok : (cam0ok && cam1ok);
  btn.disabled = !required;
  btn.title = required ? '' : (
    state.multiCam ? 'Calibrate both cam0 and cam1 first' : 'Calibrate cam0 first'
  );
}

async function runCalibrate(camName) {
  const profile = state.profile;
  if (!profile) { alert('Create a profile first (Step 3).'); return; }
  const camPath = camName === 'cam0' ? state.cam0 : (state.cam1 || '2');
  const timeout_s = parseInt(document.getElementById('calib-timeout')?.value || '30');
  const max_frames = parseInt(document.getElementById('calib-maxframes')?.value || '600');
  const logId = 'step-5-' + camName + '-log';

  if (!state.runnerConnected) { alert('Runner not connected.'); return; }
  setStepStatus(5, 'running');
  showLog(logId, '<span class="log-running">● Running calibration for ' + camName + '…</span>');

  const resp = await runnerPost('/operator/calibrate', {
    profile, cam: camName, camera: camPath, timeout_s, max_frames, no_preview: true
  });

  if (resp.error) {
    // Build structured error message for cv2 / general errors
    let html = '<span class="log-fail">✗ ' + escHtml(resp.error) + '</span>';
    if (resp.python_executable) {
      html += '\n  Python: <code>' + escHtml(resp.python_executable) + '</code>';
    }
    if (resp.fix_command) {
      html += '\n  Fix: <code>' + escHtml(resp.fix_command) + '</code>';
    }
    if (resp.hint) {
      html += '\n  ℹ ' + escHtml(resp.hint);
    }
    showLog(logId, html);
    setStepStatus(5, 'error');
    state.calibDone[camName] = false;
    updateCalibNextButton();
    return;
  }

  pollJob(resp.job_id, logId, 5, (job) => {
    const ok = job && job.status === 'succeeded';
    state.calibDone[camName] = ok;
    if (!ok) {
      state.calibDone[camName] = false;
    }
    if (state.calibDone.cam0 && (!state.multiCam || state.calibDone.cam1)) {
      setStepStatus(5, 'done');
    } else if (!ok) {
      setStepStatus(5, 'error');
    }
    updateCalibNextButton();
  });
}

// ── Step 6: Validate Alignment ────────────────────────────────────────────────

function updateAlignPreview() {
  const profile = state.profile;
  // Show converted index in preview (mirrors what the API will use)
  const idx0 = toCv2Index(state.cam0 || '0') ?? (state.cam0 || '0');
  const idx1 = toCv2Index(state.cam1 || '2') ?? (state.cam1 || '2');
  const el = document.getElementById('align-preview');
  if (el) {
    el.innerHTML = '<span class="cmd-label">Command preview (planar-only — no intrinsics required)</span>' +
      escHtml(`python tools/report_alignment.py --cam0 ${idx0} --cam1 ${idx1} --mapping-cam0 calib/profiles/${profile}/cam0/mapping_raw.yaml --mapping-cam1 calib/profiles/${profile}/cam1/mapping_raw.yaml --anchors calib/profiles/${profile}/anchors.yaml`);
  }
}

/**
 * Format a structured 400 API error response into human-readable HTML.
 * Shows error message, missing files, hint, and generate_command if present.
 */
function formatApiError(resp) {
  let html = '<span class="log-fail">✗ ' + escHtml(resp.error || 'Unknown error') + '</span>';
  if (resp.missing_intrinsics && resp.missing_intrinsics.length) {
    html += '\n\n<span class="log-info">Missing files:</span>\n';
    resp.missing_intrinsics.forEach(p => { html += '  • ' + escHtml(p) + '\n'; });
  }
  if (resp.generate_command) {
    html += '\n<span class="log-info">Generate with:</span>\n  ' + escHtml(resp.generate_command) + '\n';
  }
  if (resp.hint) {
    html += '\n<span class="log-info">ℹ ' + escHtml(resp.hint) + '</span>';
  }
  if (resp.can_skip) {
    html += '\n\n<span class="log-pass">✓ This step is optional for the standard planar workflow.</span>';
  }
  return html;
}

async function runAlignment() {
  const profile = state.profile;
  if (!profile) { alert('Create a profile first (Step 3).'); return; }
  if (!state.runnerConnected) { alert('Runner not connected.'); return; }

  const notice = document.getElementById('align-intrinsics-notice');
  if (notice) notice.style.display = 'none';
  setStepStatus(6, 'running');
  showLog('step-6-log', '<span class="log-running">● Validating alignment (planar mode)…</span>');

  const resp = await runnerPost('/operator/validate-alignment', {
    profile, cam0: state.cam0 || '0', cam1: state.cam1 || '2'
  });
  if (resp.error) {
    showLog('step-6-log', formatApiError(resp));
    setStepStatus(6, 'error');
    return;
  }

  // Surface mode to the user
  if (notice && !resp.has_intrinsics) {
    notice.style.display = 'block';
    notice.innerHTML = (
      'ℹ <b>Planar-only mode</b> — intrinsics not found; running without undistort correction. ' +
      'This is sufficient for the standard planar workflow. ' +
      '<br>For full undistort diagnostics, run ' +
      '<code>calibrate_intrinsics_chessboard.py</code> then click ' +
      '<b>Full Diagnostic</b>.'
    );
    notice.className = 'notice';
  } else if (notice) {
    notice.style.display = 'block';
    notice.innerHTML = '✓ <b>Planar + intrinsics mode</b> — intrinsics found, undistort correction applied.';
    notice.className = 'notice';
  }

  pollJob(resp.job_id, 'step-6-log', 6, (job) => {
    if (job && job.status === 'succeeded') {
      parseAlignmentResult(job.stdout || '');
    }
  });
}

async function runFullAlignment() {
  const profile = state.profile;
  if (!profile) { alert('Create a profile first (Step 3).'); return; }
  if (!state.runnerConnected) { alert('Runner not connected.'); return; }

  const notice = document.getElementById('align-intrinsics-notice');
  if (notice) notice.style.display = 'none';
  setStepStatus(6, 'running');
  showLog('step-6-log', '<span class="log-running">● Running full undistort diagnostic…</span>');

  const resp = await runnerPost('/operator/validate-alignment-full', {
    profile, cam0: state.cam0 || '0', cam1: state.cam1 || '2'
  });
  if (resp.error) {
    showLog('step-6-log', formatApiError(resp));
    setStepStatus(6, 'error');
    // Specifically surface the missing-intrinsics panel
    if (resp.missing_intrinsics && notice) {
      notice.style.display = 'block';
      notice.className = 'notice warn';
      notice.innerHTML = (
        '⚠ <b>Intrinsics required for full diagnostic.</b><br>' +
        'Missing: <code>' + resp.missing_intrinsics.map(escHtml).join('</code>, <code>') + '</code><br>' +
        'Generate with:<br>' +
        '<code>' + escHtml(resp.generate_command || '') + '</code><br><br>' +
        '<b>You can skip this step</b> — "Validate Alignment (planar)" works without intrinsics.'
      );
    }
    return;
  }
  pollJob(resp.job_id, 'step-6-log', 6, (job) => {
    if (job && job.status === 'succeeded') {
      parseAlignmentResult(job.stdout || '');
    }
  });
}

function parseAlignmentResult(stdout) {
  // Try to extract mean/max distance from debug_alignment.py output
  const meanMatch = stdout.match(/mean[_\s]dis[a-z]*[:\s=]+([0-9.]+)/i);
  const maxMatch = stdout.match(/max[_\s]dis[a-z]*[:\s=]+([0-9.]+)/i);
  const grid = document.getElementById('align-result');
  if (!grid) return;
  if (meanMatch || maxMatch) {
    const meanM = parseFloat(meanMatch?.[1] || 0);
    const maxM = parseFloat(maxMatch?.[1] || 0);
    const meanCm = (meanM * 100).toFixed(1);
    const maxCm = (maxM * 100).toFixed(1);
    const ok = maxM < 0.02;
    grid.style.display = 'flex';
    grid.innerHTML = `
      <div class="result-tile"><div class="rt-label">Mean distance</div><div class="rt-value" style="color:${ok?'var(--status-online)':'var(--status-warning)'}">${meanCm} cm</div></div>
      <div class="result-tile"><div class="rt-label">Max distance</div><div class="rt-value" style="color:${ok?'var(--status-online)':'var(--status-error)'}">${maxCm} cm</div></div>
      <div class="result-tile"><div class="rt-label">Assessment</div><div class="rt-value" style="font-size:13px">${ok ? '✓ Good' : '⚠ > 2cm'}</div></div>
    `;
  }
}

// ── Step 7: Zones ─────────────────────────────────────────────────────────────

let zones = []; // [{name, polygon: [[x,y]...]}]

function applyZonePreset(preset) {
  const w = state.boardW || 0.55;
  const h = state.boardH || 0.40;
  const mid = w / 2;
  if (preset === 'lr') {
    zones = [
      { name: 'left',  polygon: [[0,0],[mid,0],[mid,h],[0,h]] },
      { name: 'right', polygon: [[mid,0],[w,0],[w,h],[mid,h]] },
    ];
  } else if (preset === 'quad') {
    zones = [
      { name: 'tl', polygon: [[0,0],[mid,0],[mid,h/2],[0,h/2]] },
      { name: 'tr', polygon: [[mid,0],[w,0],[w,h/2],[mid,h/2]] },
      { name: 'bl', polygon: [[0,h/2],[mid,h/2],[mid,h],[0,h]] },
      { name: 'br', polygon: [[mid,h/2],[w,h/2],[w,h],[mid,h]] },
    ];
  } else if (preset === 'full') {
    zones = [{ name: 'board', polygon: [[0,0],[w,0],[w,h],[0,h]] }];
  }
  renderZones();
  updateZonesYamlPreview();
}

function renderZones() {
  const el = document.getElementById('zones-list');
  if (!el) return;
  el.innerHTML = '';
  zones.forEach((z, i) => {
    const row = document.createElement('div');
    row.className = 'zone-row';
    const polyStr = JSON.stringify(z.polygon);
    row.innerHTML = `
      <input class="zone-name-input" placeholder="zone name" value="${escHtml(z.name)}" onchange="updateZoneName(${i},this.value)">
      <input class="zone-polygon-input" placeholder='[[x1,y1],[x2,y2],[x3,y3]]' value="${escHtml(polyStr)}" onchange="updateZonePolygon(${i},this.value)">
      <button class="zone-del" onclick="removeZone(${i})">✕</button>
    `;
    el.appendChild(row);
  });
  if (!zones.length) el.innerHTML = '<div style="font-size:11px;color:var(--text-muted);padding:6px 0">No zones. Add one below or use a preset.</div>';
}

function updateZoneName(i, name) { zones[i].name = name; updateZonesYamlPreview(); }
function updateZonePolygon(i, polyStr) {
  try { zones[i].polygon = JSON.parse(polyStr); updateZonesYamlPreview(); } catch {}
}
function removeZone(i) { zones.splice(i, 1); renderZones(); updateZonesYamlPreview(); }
function addZoneRow() {
  zones.push({ name: 'zone' + zones.length, polygon: [[0,0],[0.1,0],[0.1,0.1],[0,0.1]] });
  renderZones(); updateZonesYamlPreview();
}

function updateZonesYamlPreview() {
  const el = document.getElementById('zones-yaml-preview');
  if (!el) return;
  let yaml = 'zones:\n';
  zones.forEach(z => {
    yaml += `  - name: ${z.name}\n    polygon:\n`;
    (z.polygon || []).forEach(pt => { yaml += `      - [${pt[0]}, ${pt[1]}]\n`; });
  });
  el.textContent = yaml;
}

async function saveZones() {
  const profile = state.profile;
  if (!profile) { alert('Select a profile first (Step 3).'); return; }
  if (!zones.length) { alert('Add at least one zone.'); return; }
  setStepStatus(7, 'running');
  showLog('step-7-log', '<span class="log-running">● Saving zones…</span>');

  const resp = await runnerPost('/operator/write-zones', {
    profile, zones: zones.map(z => ({ name: z.name, polygon: z.polygon })), overwrite: true
  });
  if (resp.error) {
    showLog('step-7-log', '<span class="log-fail">✗ ' + escHtml(resp.error) + '</span>');
    setStepStatus(7, 'error');
  } else {
    showLog('step-7-log', '<span class="log-pass">✓ Saved ' + resp.zone_count + ' zone(s) to ' + escHtml(resp.zones_path) + '</span>');
    setStepStatus(7, 'done');
  }
}

// ── Step 8: Config Builder ────────────────────────────────────────────────────

function syncConfigFilename() {
  const el = document.getElementById('cfg-filename');
  if (el && !el.value && state.profile) {
    const mode = document.getElementById('cfg-mode')?.value || 'multi';
    el.value = state.profile + '_' + mode + '_local.yaml';
  }
}

/**
 * Convert cam path to the correct CameraSpec field.
 * Config.CameraSpec uses:
 *   index: int   — for bare integers ("0", "2")
 *   device: str  — for /dev/videoN or /dev/v4l/by-id/... paths
 * NOT "source" and NOT "id".
 */
function camSourceField(path) {
  const p = String(path ?? '0').trim();
  // Integer index
  if (/^\d{1,2}$/.test(p)) return { index: parseInt(p, 10) };
  // Device path
  return { device: p };
}

function buildConfigObject() {
  const mode = document.getElementById('cfg-mode')?.value || 'multi';
  const fps = parseInt(document.getElementById('cfg-fps')?.value || '30');
  const backend = document.getElementById('cfg-backend')?.value || 'cpu';
  const wsPort = parseInt(document.getElementById('cfg-wsport')?.value || '8765');
  const metricsPort = parseInt(document.getElementById('cfg-metricsport')?.value || '8000');
  const record = document.getElementById('cfg-record')?.value === 'true';
  const profile = state.profile || 'local_profile';

  // Build config matching metriplane.config.Config / CameraSpec dataclass field names exactly.
  // Wrong names are silently dropped by the config loader — always verify against config.py.
  const cfg = {
    profile: profile,
    target_fps: fps,
    // Flat ws/metrics keys (nested 'websocket:' key is NOT handled by loader)
    ws_host: '127.0.0.1',
    ws_port: wsPort,
    metrics_host: '127.0.0.1',
    metrics_port: metricsPort,
    // compute backend lives under 'compute: {backend: ...}' sub-dict
    compute: { backend },
  };

  // record_jsonl must be a path string (or null), never a bool
  if (record) {
    const runsDir = state.runsDir || '<platform-runs-dir>';
    cfg.record_jsonl = runsDir.replace(/\/$/, '') + '/' + profile + '_session.jsonl';
  }

  if (mode === 'single') {
    cfg.cameras = [
      Object.assign({ name: 'cam0', mapping_file: 'calib/profiles/' + profile + '/cam0/mapping_raw.yaml' },
                    camSourceField(state.cam0 || '0'))
    ];
    cfg.fusion_enable = false;
  } else {
    cfg.cameras = [
      Object.assign({ name: 'cam0', mapping_file: 'calib/profiles/' + profile + '/cam0/mapping_raw.yaml' },
                    camSourceField(state.cam0 || '0')),
      Object.assign({ name: 'cam1', mapping_file: 'calib/profiles/' + profile + '/cam1/mapping_raw.yaml' },
                    camSourceField(state.cam1 || '2')),
    ];
    cfg.fusion_enable = true;
    cfg.fusion = { method: 'kalman' };
  }

  cfg.zones_file = 'calib/profiles/' + profile + '/zones.yaml';
  return cfg;
}

function configToYaml(cfg) {
  // Simple recursive YAML serializer (no dependency)
  function toYaml(obj, indent) {
    const pad = ' '.repeat(indent);
    if (obj === null || obj === undefined) return 'null';
    if (typeof obj === 'boolean') return obj ? 'true' : 'false';
    if (typeof obj === 'number') return String(obj);
    if (typeof obj === 'string') {
      if (obj.match(/[:#\[\]{},|>&*!,]/)) return JSON.stringify(obj);
      return obj;
    }
    if (Array.isArray(obj)) {
      if (!obj.length) return '[]';
      return '\n' + obj.map(v => {
        if (typeof v === 'object' && !Array.isArray(v)) {
          const lines = Object.entries(v).map(([k,val]) => pad + '  ' + k + ': ' + toYaml(val, indent+4));
          return pad + '-\n' + lines.join('\n');
        }
        return pad + '- ' + toYaml(v, indent+2);
      }).join('\n');
    }
    if (typeof obj === 'object') {
      return '\n' + Object.entries(obj).map(([k,v]) => {
        const val = toYaml(v, indent+2);
        if (val.startsWith('\n')) return pad + k + ':' + val;
        return pad + k + ': ' + val;
      }).join('\n');
    }
    return String(obj);
  }
  return Object.entries(cfg).map(([k,v]) => {
    const val = toYaml(v, 2);
    if (val.startsWith('\n')) return k + ':' + val;
    return k + ': ' + val;
  }).join('\n') + '\n';
}

function updateConfigPreview() {
  const el = document.getElementById('cfg-yaml-preview');
  if (!el) return;
  try {
    const cfg = buildConfigObject();
    el.textContent = configToYaml(cfg);
  } catch (e) {
    el.textContent = 'Error: ' + e.message;
  }
}

async function saveConfig() {
  const filename = (document.getElementById('cfg-filename')?.value || '').trim();
  if (!filename) { alert('Enter a filename.'); return; }
  const record = document.getElementById('cfg-record')?.value === 'true';
  if (record && !state.runsDir) {
    alert('The platform runs directory is unavailable. Reconnect the runner and try again.');
    return;
  }
  setStepStatus(8, 'running');
  showLog('step-8-log', '<span class="log-running">● Saving config…</span>');

  const cfg = buildConfigObject();
  const resp = await runnerPost('/operator/save-config', { filename, config: cfg });
  if (resp.error && resp.error.includes('already exists')) {
    const ok = confirm(resp.error + '\n\nOverwrite?');
    if (!ok) { setStepStatus(8, 'idle'); showLog('step-8-log', ''); return; }
    const r2 = await runnerPost('/operator/save-config', { filename, config: cfg, overwrite: true });
    handleSaveConfigResult(r2);
  } else {
    handleSaveConfigResult(resp);
  }
}

function handleSaveConfigResult(resp) {
  if (resp.error) {
    showLog('step-8-log', '<span class="log-fail">✗ ' + escHtml(resp.error) + '</span>');
    setStepStatus(8, 'error');
  } else {
    state.savedConfigPath = resp.path;
    showLog('step-8-log', '<span class="log-pass">✓ Saved: ' + escHtml(resp.path) + '\n  hash: ' + escHtml(resp.config_hash || '') + '</span>');
    setStepStatus(8, 'done');
  }
}

// ── Step 9: Run ───────────────────────────────────────────────────────────────

async function loadConfigs() {
  const sel = document.getElementById('run-config');
  if (!sel) return;
  const data = await opApi('GET', '/operator/configs');
  if (data.error || !data.configs) return;
  const current = sel.value;
  sel.innerHTML = '<option value="">— select config —</option>';
  // Local configs first
  const local = data.configs.filter(c => c.is_local);
  const other = data.configs.filter(c => !c.is_local);
  if (local.length) {
    const og = document.createElement('optgroup');
    og.label = 'Local configs';
    local.forEach(c => {
      const o = document.createElement('option');
      o.value = c.path; o.textContent = c.path;
      if (c.path === current || c.path === state.savedConfigPath) o.selected = true;
      og.appendChild(o);
    });
    sel.appendChild(og);
  }
  if (other.length) {
    const og = document.createElement('optgroup');
    og.label = 'Other configs';
    other.forEach(c => {
      const o = document.createElement('option');
      o.value = c.path; o.textContent = c.path;
      og.appendChild(o);
    });
    sel.appendChild(og);
  }
  // Auto-select saved config
  if (state.savedConfigPath) sel.value = state.savedConfigPath;
  updateRunPreview();
}

function updateRunPreview() {
  const cfg = document.getElementById('run-config')?.value || '<config>';
  const dur = document.getElementById('run-duration')?.value || '60';
  const rid = document.getElementById('run-id')?.value?.trim() || '<auto>';
  const el = document.getElementById('run-cmd-preview');
  const runsDir = state.runsDir || '<platform-runs-dir>';
  if (el) {
    el.innerHTML = '<span class="cmd-label">Command preview</span>' +
      escHtml(`python -m metriplane.run_fusion --config ${cfg} --runs-dir ${runsDir} --run-id ${rid} --duration-s ${dur}`);
  }
}

async function startFusion() {
  const config = document.getElementById('run-config')?.value?.trim();
  if (!config) { alert('Select a config file.'); return; }
  const duration_s = parseInt(document.getElementById('run-duration')?.value || '60');
  const run_id = document.getElementById('run-id')?.value?.trim() || '';

  if (!state.runnerConnected) { alert('Runner not connected.'); return; }
  setStepStatus(9, 'running');
  document.getElementById('run-start-btn').disabled = true;
  document.getElementById('run-stop-btn').disabled = false;

  const logEl = document.getElementById('step-9-log');
  if (logEl) { logEl.className = 'output-log visible'; logEl.textContent = '● Starting…'; }

  const request = { config, duration_s };
  if (run_id) { request.run_id = run_id; }
  const resp = await runnerPost('/operator/start-fusion', request);
  if (resp.error) {
    showLog('step-9-log', '<span class="log-fail">✗ ' + escHtml(resp.error) + '</span>');
    setStepStatus(9, 'error');
    document.getElementById('run-start-btn').disabled = false;
    document.getElementById('run-stop-btn').disabled = true;
    return;
  }
  state.activeJobId = resp.job_id;
  state.activeJobCmdId = 'run-fusion-operator';
  showLog('step-9-log', '<span class="log-running">● Job ' + escHtml(resp.job_id) + ' started\n  run_id: ' + escHtml(resp.run_id) + '\n  config: ' + escHtml(resp.config) + '\n  duration: ' + resp.duration_s + 's</span>');
  pollJob(resp.job_id, 'step-9-log', 9, (job) => {
    document.getElementById('run-start-btn').disabled = false;
    document.getElementById('run-stop-btn').disabled = true;
    state.activeJobId = null;

    const ok = job && job.status === 'succeeded';
    state.lastRunOk = ok;

    // Show run-failed notice and disable/enable Export nav button
    const notice = document.getElementById('run-failed-notice');
    const exportBtn = document.getElementById('step-9-next-export');
    if (notice) notice.style.display = ok ? 'none' : 'block';
    if (exportBtn) exportBtn.disabled = !ok;

    refreshLatestRun();
  });
}

async function stopFusion() {
  if (!state.activeJobId) return;
  await opApi('POST', '/jobs/' + state.activeJobId + '/cancel');
  state.activeJobId = null;
  document.getElementById('run-start-btn').disabled = false;
  document.getElementById('run-stop-btn').disabled = true;
  appendLog('step-9-log', '\n⊘ Stop requested.');
  setStepStatus(9, 'idle');
  refreshLatestRun();
}

async function refreshLatestRun() {
  const data = await opApi('GET', '/operator/latest-run');
  if (!data.error && data.runs_dir) {
    state.runsDir = data.runs_dir;
    updateConfigPreview();
    updateRunPreview();
  }
  const el = document.getElementById('latest-run-info');
  if (!el) return;
  if (data.error || !data.latest_run) {
    el.textContent = data.error ? data.error : 'No runs found in ' + (data.runs_dir || 'the platform runs directory');
    return;
  }
  const r = data.latest_run;
  const session = r.dir + '/session.jsonl';
  state.latestRunDir = r.dir;
  state.latestSessionPath = r.session_exists ? session : null;
  el.innerHTML = `<b>${escHtml(r.name)}</b><br>
    dir: ${escHtml(r.dir)}<br>
    session.jsonl: ${r.session_exists ? '✓ ' + r.session_size_mb + ' MB' : 'not yet'}<br>
    ${r.meta ? 'run_id: ' + escHtml(r.meta.run_id || '') + ' | git: ' + escHtml((r.meta.git_commit || '').slice(0,12)) : ''}`;
}

// ── Step 10: Export ───────────────────────────────────────────────────────────

// ── Export enable/disable helpers ─────────────────────────────────────────────

function setExportEnabled(enabled) {
  state.exportEnabled = enabled;
  // Export buttons are identified by their onclick attributes — disable via DOM query
  document.querySelectorAll('#step-10 .btn-primary, #step-10 .btn-secondary').forEach(btn => {
    if (btn.textContent.includes('SHA256') || btn.textContent.includes('Zone') || btn.textContent.includes('ID')) {
      btn.disabled = !enabled;
      if (!enabled) btn.title = 'Session is empty or run failed — no data to export';
      else btn.title = '';
    }
  });
}

async function refreshLatestRunForExport() {
  const data = await opApi('GET', '/operator/latest-run');
  if (!data.error && data.runs_dir) state.runsDir = data.runs_dir;
  const el = document.getElementById('export-session-info');
  if (!el) return;
  if (data.error || !data.latest_run) {
    el.textContent = 'No runs found. Run Step 9 first.';
    setExportEnabled(false);
    return;
  }
  const r = data.latest_run;
  const session = r.dir + '/session.jsonl';
  const sizeMb = r.session_size_mb || 0;
  const hasContent = r.session_exists && sizeMb > 0;

  if (r.session_exists) {
    if (hasContent) {
      el.className = 'notice';
      el.innerHTML = `Latest session: <b>${escHtml(session)}</b><br>Size: ${sizeMb} MB`;
      // Always update path to latest session (overwrite stale 0-byte path)
      const inp = document.getElementById('export-session-path');
      if (inp) inp.value = session;
      const prefInp = document.getElementById('export-prefix');
      if (prefInp && !prefInp.value) prefInp.value = r.name.replace(/-\d+$/, '');
      setExportEnabled(true);
    } else {
      // File exists but is 0 bytes — run failed before writing data
      el.className = 'notice warn';
      el.innerHTML = `⚠ <b>Session is empty (0 MB)</b> — run failed before writing frames.<br>
        Dir: ${escHtml(r.dir)}<br>Fix config/camera issue in Step 8–9 and re-run.`;
      const inp = document.getElementById('export-session-path');
      if (inp) inp.value = '';  // Clear stale path
      setExportEnabled(false);
    }
  } else {
    el.className = 'notice';
    el.innerHTML = 'Latest run dir: ' + escHtml(r.dir) + ' — no session.jsonl yet.';
    setExportEnabled(false);
  }
}

async function generateReport(type) {
  const session = document.getElementById('export-session-path')?.value?.trim();
  const prefix = document.getElementById('export-prefix')?.value?.trim() || 'operator';
  if (!session) { alert('Enter session JSONL path.'); return; }
  if (!state.exportEnabled) { alert('Session is empty or run failed. Re-run Step 9 first.'); return; }
  if (!state.runnerConnected) { alert('Runner not connected.'); return; }
  setStepStatus(10, 'running');
  showLog('step-10-log', '<span class="log-running">● Generating ' + type + ' report…</span>');

  const resp = await runnerPost('/operator/generate-report', {
    type, session, prefix, profile: state.profile
  });
  if (resp.error) {
    showLog('step-10-log', '<span class="log-fail">✗ ' + escHtml(resp.error) + '</span>');
    setStepStatus(10, 'error');
    return;
  }
  appendLog('step-10-log', '\nCommand: ' + resp.command_preview + '\n');
  pollJob(resp.job_id, 'step-10-log', 10, (job) => {
    if (job && job.status === 'succeeded') {
      const el = document.getElementById('export-files-list');
      if (el) {
        el.innerHTML = '<b>Output dir:</b> ' + escHtml(resp.out_dir) + '<br>Check evidence/experiments/ for generated CSVs.';
      }
    }
  });
}

async function computeChecksum() {
  const path = document.getElementById('export-session-path')?.value?.trim();
  if (!path) { alert('Enter file path.'); return; }
  setStepStatus(10, 'running');
  showLog('step-10-log', '<span class="log-running">● Computing SHA256 (large files may take time)…</span>');
  const resp = await runnerPost('/operator/checksum', { path });
  if (resp.error) {
    showLog('step-10-log', '<span class="log-fail">✗ ' + escHtml(resp.error) + '</span>');
    setStepStatus(10, 'error');
  } else {
    showLog('step-10-log', '<span class="log-pass">✓ SHA256: ' + escHtml(resp.sha256) + '\n  Size: ' + resp.size_mb + ' MB (' + resp.size_bytes + ' bytes)\n  Path: ' + escHtml(resp.path) + '</span>');
    setStepStatus(10, 'done');
  }
}

// ── Sidebar step item click ───────────────────────────────────────────────────

document.getElementById('step-list')?.querySelectorAll('.step-item').forEach(item => {
  item.addEventListener('click', () => {
    const n = parseInt(item.dataset.step);
    if (n) goStep(n);
  });
});

// Config/run preview live update
['run-config','run-duration','run-id'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', updateRunPreview);
});

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  await checkRunner();
  // Load env info if connected
  if (state.runnerConnected) {
    const env = await opApi('GET', '/operator/env');
    renderEnv(env);
  }
  // Default anchor table render
  fillDefaultAnchors();
  updateZonesYamlPreview();
  updateConfigPreview();
  // Initialise horizontal stepper + runbook panel for Step 1
  updateHStepper(1);
  updateRunbookPanel(1);
  setInterval(checkRunner, 10000);
}

init();

// ── Preflight / Doctor Output Drawer ─────────────────────────────────────────

function togglePreflightDrawer() {
  const drawer = document.getElementById('preflight-drawer');
  if (!drawer) return;
  drawer.classList.toggle('collapsed');
}

function clearPreflightDrawer() {
  const output = document.getElementById('preflight-drawer-output');
  const badge  = document.getElementById('preflight-status-badge');
  if (output) output.textContent = 'No output yet — click Run Doctor or Run Preflight above.';
  if (badge)  { badge.textContent = 'idle'; badge.className = 'preflight-drawer-badge'; }
  hidePreflightSummary();
}

async function runPreflightDrawer(command) {
  if (!state.runnerConnected) {
    const output = document.getElementById('preflight-drawer-output');
    if (output) output.textContent = '⚠ Runner not connected.\nStart it with: ./tools/dashboard_runner.sh';
    hidePreflightSummary();
    return;
  }

  const output = document.getElementById('preflight-drawer-output');
  const badge  = document.getElementById('preflight-status-badge');
  const drawer = document.getElementById('preflight-drawer');

  // Expand the drawer so output is visible
  if (drawer) drawer.classList.remove('collapsed');

  if (output) output.textContent = `Running ${command}…`;
  if (badge)  { badge.textContent = 'running'; badge.className = 'preflight-drawer-badge running'; }
  hidePreflightSummary();

  try {
    if (!runnerSessionToken) await opApi('GET', '/status');
    const resp = await fetch(`${RUNNER}/execute`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Metriplane-Token': runnerSessionToken || '',
      },
      body: JSON.stringify({ command_id: command }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
      if (output) output.textContent = `Error: ${err.error || resp.statusText}`;
      if (badge)  { badge.textContent = 'fail'; badge.className = 'preflight-drawer-badge fail'; }
      hidePreflightSummary();
      return;
    }
    const job = await resp.json();
    pollPreflightJob(job.job_id);
  } catch (e) {
    if (output) output.textContent = `Error: ${e.message}`;
    if (badge)  { badge.textContent = 'fail'; badge.className = 'preflight-drawer-badge fail'; }
    hidePreflightSummary();
  }
}

function pollPreflightJob(jobId) {
  const output = document.getElementById('preflight-drawer-output');
  const badge  = document.getElementById('preflight-status-badge');

  const timer = setInterval(async () => {
    try {
      const resp = await fetch(`${RUNNER}/jobs/${jobId}`);
      if (!resp.ok) { clearInterval(timer); return; }
      const job = await resp.json();

      const text = [job.stdout, job.stderr ? `\n--- stderr ---\n${job.stderr}` : ''].join('').trim();
      if (output) output.textContent = text || `(running… status=${job.status})`;

      if (['succeeded','failed','timed_out','cancelled'].includes(job.status)) {
        clearInterval(timer);
        const passed = job.status === 'succeeded';
        if (badge) {
          badge.textContent = passed ? 'pass' : 'fail';
          badge.className   = `preflight-drawer-badge ${passed ? 'pass' : 'fail'}`;
        }
        // Auto-scroll output to bottom
        if (output) output.scrollTop = output.scrollHeight;
        // Parse pass/warn/fail counts from output and render summary chips
        renderPreflightSummary(job.stdout || '');
      }
    } catch { clearInterval(timer); }
  }, 1000);
}

function hidePreflightSummary() {
  const el = document.getElementById('preflight-summary');
  if (!el) return;
  el.innerHTML = '';
  el.style.display = 'none';
}

function parsePreflightSummaryCounts(stdout) {
  const summaryMatch = stdout.match(/Summary:\s*(\d+)\s+passed,\s*(\d+)\s+warnings?,\s*(\d+)\s+failed/i);
  if (summaryMatch) {
    return {
      passed: Number(summaryMatch[1]),
      warned: Number(summaryMatch[2]),
      failed: Number(summaryMatch[3]),
    };
  }

  const counts = { passed: 0, warned: 0, failed: 0 };
  stdout.split('\n').forEach(line => {
    const trimmed = line.trim();
    if (/^(✅\s*)?PASS\b/i.test(trimmed) || /^\[PASS\]/i.test(trimmed)) counts.passed++;
    if (/^(⚠️?\s*)?WARN(?:ING)?\b/i.test(trimmed) || /^\[WARN(?:ING)?\]/i.test(trimmed)) counts.warned++;
    if (/^(❌|✗)?\s*FAIL(?:ED)?\b/i.test(trimmed) || /^\[FAIL(?:ED)?\]/i.test(trimmed)) counts.failed++;
  });
  return counts;
}

/** Parse pass/warn/fail counts from Doctor or Preflight output and render summary chips. */
function renderPreflightSummary(stdout) {
  const el = document.getElementById('preflight-summary');
  if (!el) return;

  const { passed, warned, failed } = parsePreflightSummaryCounts(stdout);

  if (passed === 0 && warned === 0 && failed === 0) {
    hidePreflightSummary();
    return;
  }

  const chips = [];
  if (passed > 0) chips.push(`<span class="preflight-chip preflight-chip-pass">${passed} passed</span>`);
  if (warned > 0) chips.push(`<span class="preflight-chip preflight-chip-warn">${warned} warning${warned !== 1 ? 's' : ''}</span>`);
  if (failed > 0) chips.push(`<span class="preflight-chip preflight-chip-fail">${failed} failed</span>`);

  el.innerHTML = chips.join('');
  el.style.display = 'flex';
}

// Expose to HTML onclick
window.togglePreflightDrawer = togglePreflightDrawer;
window.clearPreflightDrawer  = clearPreflightDrawer;
window.runPreflightDrawer    = runPreflightDrawer;
