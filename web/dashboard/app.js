// SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
// SPDX-License-Identifier: MIT

// Metriplane Dashboard V1 - app.js
// Pure vanilla JavaScript - no dependencies

// Configuration
const CONFIG = {
    WS_URL: 'ws://localhost:8765',
    HEALTH_URL: 'http://127.0.0.1:8000/health',
    METRICS_URL: 'http://127.0.0.1:8000/metrics',
    MANIFEST_URLS: ['../../evidence/manifest.csv', 'evidence/manifest.csv'],
    HEALTH_POLL_INTERVAL: 2000,  // 2 seconds
    METRICS_POLL_INTERVAL: 5000, // 5 seconds
    WS_RECONNECT_INTERVAL: 2000,  // 2 seconds
};

// State
let ws = null;
let wsReconnectTimer = null;
let healthPollTimer = null;
let metricsPollTimer = null;
let lastFrameData = null;

// Trail tracking: Map<object_id, {points: [{x, y, ts}], lastSeen: timestamp}>
const objectTrails = new Map();
const MAX_TRAIL_POINTS = 50;
const TRAIL_TIMEOUT_MS = 2000;  // 2 seconds

// ========================================
// WebSocket Management
// ========================================

function connectWebSocket() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
        return; // Already connected or connecting
    }

    updateStatus('ws', 'connecting', 'Connecting...');
    console.log('[WS] Connecting to', CONFIG.WS_URL);

    try {
        ws = new WebSocket(CONFIG.WS_URL);

        ws.onopen = () => {
            console.log('[WS] Connected');
            updateStatus('ws', 'online', 'Connected');
            if (wsReconnectTimer) {
                clearTimeout(wsReconnectTimer);
                wsReconnectTimer = null;
            }
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleFrameData(data);
            } catch (err) {
                console.error('[WS] Parse error:', err);
            }
        };

        ws.onerror = (error) => {
            console.error('[WS] Error:', error);
            updateStatus('ws', 'standby', 'Standby');
        };

        ws.onclose = () => {
            console.log('[WS] Disconnected');
            updateStatus('ws', 'standby', 'Standby');
            scheduleReconnect();
        };
    } catch (err) {
        console.error('[WS] Connection failed:', err);
        updateStatus('ws', 'standby', 'Standby');
        scheduleReconnect();
    }
}

function scheduleReconnect() {
    if (wsReconnectTimer) return;
    updateStatus('ws', 'standby', 'Standby');
    wsReconnectTimer = setTimeout(() => {
        wsReconnectTimer = null;
        connectWebSocket();
    }, CONFIG.WS_RECONNECT_INTERVAL);
}

function handleFrameData(data) {
    lastFrameData = data;

    // Update frame info
    document.getElementById('frame-id').textContent = data.frame_id || '—';
    document.getElementById('schema-version').textContent = data.schema_version || '—';
    document.getElementById('run-id').textContent = data.run_id || '—';

    // Handle objects (support both objects[] and fused[])
    let objects = data.objects || data.fused || [];
    document.getElementById('object-count').textContent = objects.length;

    updateObjectsTable(objects);
    updateZoneEvents(data.zone_events || []);
    updateWorldCanvas(objects, data.raw_per_camera || []);
    updateCameraTelemetry(data.raw_per_camera || []);
}

function updateObjectsTable(objects) {
    const tbody = document.getElementById('objects-tbody');
    
    if (!objects || objects.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty">No objects</td></tr>';
        return;
    }

    // Take last 20 objects to avoid DOM bloat
    const recentObjects = objects.slice(-20);

    tbody.innerHTML = recentObjects.map(obj => {
        // Support different object shapes
        let x = '—', y = '—', conf = '—';
        
        // Try pos_world array
        if (obj.pos_world && Array.isArray(obj.pos_world) && obj.pos_world.length >= 2) {
            x = obj.pos_world[0].toFixed(3);
            y = obj.pos_world[1].toFixed(3);
        }
        // Try x_m/y_m fields
        else if (obj.x_m !== undefined && obj.y_m !== undefined) {
            x = obj.x_m.toFixed(3);
            y = obj.y_m.toFixed(3);
        }

        // Try confidence
        if (obj.confidence !== undefined) {
            conf = obj.confidence.toFixed(2);
        } else if (obj.conf !== undefined) {
            conf = obj.conf.toFixed(2);
        }

        const id = obj.id || obj.object_id || '?';

        return `
            <tr>
                <td>${id}</td>
                <td>${x}</td>
                <td>${y}</td>
                <td>${conf}</td>
            </tr>
        `;
    }).join('');
}

function updateZoneEvents(events) {
    const container = document.getElementById('zone-events');
    
    if (!events || events.length === 0) {
        container.innerHTML = '<p class="empty">No zone events</p>';
        return;
    }

    // Take last 10 events
    const recentEvents = events.slice(-10);

    container.innerHTML = recentEvents.map(event => {
        const type = event.event_type || event.type || '?';
        const zone = event.zone_id || '?';
        const obj = event.object_id || '?';
        return `<div class="event-item">• ${type}: obj ${obj} in zone ${zone}</div>`;
    }).join('');
}

// ========================================
// Health Polling
// ========================================

function startHealthPolling() {
    fetchHealth(); // Immediate first call
    healthPollTimer = setInterval(fetchHealth, CONFIG.HEALTH_POLL_INTERVAL);
}

async function fetchHealth() {
    try {
        const response = await fetch(CONFIG.HEALTH_URL);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const data = await response.json();
        updateHealth(data);
        updateStatus('health', 'online', 'Online');
    } catch (err) {
        console.error('[Health] Fetch error:', err);
        updateStatus('health', 'standby', 'Standby');
        updateHealth(null);
    }
}

function updateHealth(data) {
    const overallEl = document.getElementById('health-overall');
    const componentsEl = document.getElementById('health-components');
    const timestampEl = document.getElementById('health-timestamp');

    if (!data) {
        overallEl.textContent = '—';
        overallEl.className = 'badge';
        componentsEl.innerHTML = '<p class="empty">No runtime session active</p>';
        timestampEl.textContent = '—';
        return;
    }

    // Overall status
    const overall = data.overall || data.status || '—';
    overallEl.textContent = overall;
    overallEl.className = `badge badge-${overall.toLowerCase()}`;

    // Components
    if (data.components && typeof data.components === 'object') {
        const components = Object.entries(data.components);
        componentsEl.innerHTML = `
            <table>
                <thead>
                    <tr><th>Component</th><th>Status</th></tr>
                </thead>
                <tbody>
                    ${components.map(([name, comp]) => {
                        const status = comp.status || comp || '?';
                        return `
                            <tr>
                                <td>${name}</td>
                                <td><span class="badge badge-small badge-${status.toLowerCase()}">${status}</span></td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;
    } else {
        componentsEl.innerHTML = '<p class="empty">No component data</p>';
    }

    // Timestamp
    timestampEl.textContent = new Date().toLocaleTimeString();
}

// ========================================
// Metrics Polling
// ========================================

function startMetricsPolling() {
    fetchMetrics(); // Immediate first call
    metricsPollTimer = setInterval(fetchMetrics, CONFIG.METRICS_POLL_INTERVAL);
}

async function fetchMetrics() {
    try {
        const response = await fetch(CONFIG.METRICS_URL);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const text = await response.text();
        updateMetrics(text);
        updateStatus('metrics', 'online', 'Online');
    } catch (err) {
        console.error('[Metrics] Fetch error:', err);
        updateStatus('metrics', 'standby', 'Standby');
        updateMetrics(null);
    }
}

function updateMetrics(text) {
    const rawEl = document.getElementById('metrics-raw');
    const summaryEl = document.getElementById('metrics-summary');

    if (!text) {
        rawEl.textContent = 'No runtime session active';
        summaryEl.innerHTML = '<div class="empty-state">No runtime session active</div>';
        return;
    }

    rawEl.textContent = text;

    // Parse interesting metrics
    const metrics = parsePrometheusMetrics(text);
    summaryEl.innerHTML = `
        ${renderMetric('Queue Depth', metrics.queue_depth)}
        ${renderMetric('Dropped', metrics.dropped_frames)}
        ${renderMetric('Objects', metrics.object_count)}
        ${renderMetric('Latency', metrics.avg_latency)}
    `;
}

function parsePrometheusMetrics(text) {
    const result = {};
    const lines = text.split('\n');

    for (const line of lines) {
        if (line.startsWith('#') || !line.trim()) continue;

        // Simple regex for "metric_name{labels} value"
        const match = line.match(/^([a-zA-Z_][a-zA-Z0-9_]*)\{?([^}]*)\}?\s+([0-9.eE+-]+)/);
        if (!match) continue;

        const [, name, labels, value] = match;
        const numValue = parseFloat(value);

        // Extract interesting metrics
        if (name.includes('queue_depth')) {
            result.queue_depth = numValue;
        } else if (name.includes('dropped')) {
            result.dropped_frames = numValue;
        } else if (name.includes('object_count')) {
            result.object_count = numValue;
        } else if (name.includes('latency') && name.includes('mean')) {
            result.avg_latency = numValue.toFixed(2);
        }
    }

    return result;
}

function renderMetric(label, value) {
    const displayValue = value !== undefined ? value : '—';
    return `
        <div class="metric-item">
            <div class="metric-label">${label}</div>
            <div class="metric-value">${displayValue}</div>
        </div>
    `;
}

// ========================================
// Evidence Manifest Loading
// ========================================

async function loadManifest() {
    for (const url of CONFIG.MANIFEST_URLS) {
        try {
            console.log('[Manifest] Trying:', url);
            const response = await fetch(url);
            if (!response.ok) continue;

            const text = await response.text();
            parseManifest(text);
            updateStatus('manifest', 'online', 'Loaded');
            return;
        } catch (err) {
            console.log('[Manifest] Failed:', url, err.message);
        }
    }

    // All URLs failed
    console.error('[Manifest] All URLs failed');
    updateStatus('manifest', 'offline', 'Unavailable');
    showManifestHelp();
}

function parseManifest(csvText) {
    const lines = csvText.trim().split('\n');
    if (lines.length < 2) {
        showManifestHelp();
        return;
    }

    const tbody = document.getElementById('manifest-tbody');
    const rows = lines.slice(1); // Skip header

    tbody.innerHTML = rows.map(line => {
        const cols = line.split(',');
        if (cols.length < 4) return '';

        const demo_id = cols[0] || '—';
        const status = cols[2] || '—';
        const metric_key = cols[10] || '—';
        const metric_value = cols[11] || '—';

        const statusClass = status.toLowerCase();

        return `
            <tr>
                <td>${demo_id}</td>
                <td><span class="badge badge-small badge-${statusClass}">${status}</span></td>
                <td><code>${metric_key}</code></td>
                <td>${metric_value}</td>
            </tr>
        `;
    }).join('');

    document.getElementById('manifest-help').style.display = 'none';
}

function showManifestHelp() {
    document.getElementById('manifest-tbody').innerHTML = 
        '<tr><td colspan="4" class="empty">Manifest not found</td></tr>';
    document.getElementById('manifest-help').style.display = 'block';
}

// ========================================
// Status Indicators
// ========================================

function updateStatus(component, state, text) {
    const item = document.getElementById(`${component}-status-item`);
    const indicator = document.getElementById(`${component}-indicator`);
    const status = document.getElementById(`${component}-status`);

    if (!item || !indicator || !status) return;

    // Sync data-state so CSS chip-value color rules fire correctly.
    // 'online' → 'live' so the green chip-value rule applies.
    const chipState = state === 'online' ? 'live' : state;
    item.dataset.state = chipState;

    // Remove old state classes — preserve 'chip-dot' base class for topbar-chip layout
    const baseClass = indicator.classList.contains('chip-dot') ? 'chip-dot' : 'status-dot';
    indicator.className = baseClass;

    // Add new state class (works on both chip-dot and status-dot elements)
    indicator.classList.add(`status-${state}`);

    // Update text
    status.textContent = text;
}

// ========================================
// Command Helper
// ========================================

function copyCommand(command) {
    navigator.clipboard.writeText(command).then(() => {
        console.log('[Copy] Copied:', command);
        // Visual feedback
        const event = new CustomEvent('toast', { 
            detail: { message: `Copied: ${command.substring(0, 40)}...` }
        });
        window.dispatchEvent(event);
    }).catch(err => {
        console.error('[Copy] Failed:', err);
        alert('Copy failed. Please copy manually:\n\n' + command);
    });
}

// Make copyCommand available globally
window.copyCommand = copyCommand;

// ========================================
// Navigation Handling
// ========================================

function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item[data-section]');
    
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Update active state
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
            
            // Scroll to section
            const sectionId = item.getAttribute('data-section');
            const targetEl = document.getElementById(sectionId);
            
            if (targetEl) {
                targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });
}

// ========================================
// Manifest Refresh
// ========================================

function refreshManifest() {
    console.log('[Manifest] Refreshing...');
    updateStatus('manifest', 'connecting', 'Loading...');
    loadManifest();
}

// Make refreshManifest available globally
window.refreshManifest = refreshManifest;

// ========================================
// Manifest Search / Filter
// ========================================

function filterManifest(query) {
    const tbody = document.getElementById('manifest-tbody');
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    const q = query.trim().toLowerCase();
    let total = 0, visible = 0;
    rows.forEach(row => {
        // skip empty-state rows from count
        if (row.querySelector('.empty-state, .empty')) { row.style.display = ''; return; }
        total++;
        const show = !q || row.textContent.toLowerCase().includes(q);
        row.style.display = show ? '' : 'none';
        if (show) visible++;
    });
    // Update result count indicator
    const countEl = document.getElementById('manifest-result-count');
    if (countEl && total > 0) {
        countEl.textContent = q
            ? `${visible} of ${total} results`
            : `${total} results`;
        countEl.style.display = '';
    } else if (countEl) {
        countEl.textContent = '';
    }
}

// Make filterManifest available globally
window.filterManifest = filterManifest;

// ========================================
// Runner Service Integration (Dashboard V2)
// ========================================

const RUNNER_URL = 'http://localhost:9000';
let runnerAvailable = false;
let activeJobs = {}; // Track active jobs per command_id

async function checkRunnerStatus() {
    try {
        const response = await fetch(`${RUNNER_URL}/status`);
        const data = await response.json();
        runnerAvailable = (data.status === 'idle' || data.status === 'running');
        
        if (runnerAvailable) {
            updateRunnerBanner(data);
            enableRunButtons();
        } else {
            disableRunButtons();
        }
    } catch (err) {
        runnerAvailable = false;
        disableRunButtons();
    }
}

function updateRunnerBanner(status) {
    const banner = document.querySelector('.runner-status');
    if (!banner) return;
    
    const badge = banner.querySelector('.runner-badge');
    if (badge && status.status === 'idle') {
        badge.textContent = 'Connected';
        badge.style.background = 'rgba(16, 185, 129, 0.1)';
        badge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        badge.style.color = '#10b981';
    }
}

function enableRunButtons() {
    document.querySelectorAll('.run-btn').forEach(btn => {
        const card = btn.closest('.action-card');
        if (!card) return;
        
        const commandId = card.parentElement.id.replace('action-', '');
        // Check if this command is enabled in the runner
        // For now, enable all non-disabled buttons
        if (!btn.dataset.disabled) {
            btn.disabled = false;
            btn.style.opacity = '1';
            btn.style.cursor = 'pointer';
        }
    });
}

function disableRunButtons() {
    document.querySelectorAll('.run-btn').forEach(btn => {
        btn.disabled = true;
        btn.style.opacity = '0.5';
        btn.style.cursor = 'not-allowed';
    });
}

async function runCommand(commandId) {
    console.log('[Runner] Executing command:', commandId);
    
    if (!runnerAvailable) {
        showToast('Runner service not available');
        showCommandError(commandId, 'Runner service not available. Start with: ./tools/dashboard_runner.sh');
        return;
    }
    
    if (activeJobs[commandId]) {
        showToast('Command already running');
        return;
    }
    
    try {
        console.log('[Runner] Sending POST to', `${RUNNER_URL}/execute`);
        const response = await fetch(`${RUNNER_URL}/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command_id: commandId })
        });
        
        console.log('[Runner] Response status:', response.status);
        
        if (!response.ok) {
            let errorMsg = 'Failed to start command';
            try {
                const error = await response.json();
                errorMsg = error.error || errorMsg;
            } catch (e) {
                errorMsg = `HTTP ${response.status}: ${response.statusText}`;
            }
            console.error('[Runner] Error:', errorMsg);
            showToast(`Error: ${errorMsg}`);
            showCommandError(commandId, errorMsg);
            return;
        }
        
        const job = await response.json();
        console.log('[Runner] Job started:', job.job_id);
        activeJobs[commandId] = job.job_id;
        pollJobStatus(job.job_id, commandId);
        
    } catch (err) {
        console.error('[Runner] Fetch failed:', err);
        const errorMsg = `Failed to start command: ${err.message}`;
        showToast(errorMsg);
        showCommandError(commandId, errorMsg);
    }
}

function showCommandError(commandId, errorMessage) {
    const card = document.getElementById(`action-${commandId}`);
    if (!card) return;
    
    const outputDiv = card.querySelector('.action-output');
    const statusSpan = card.querySelector('.output-status');
    const textPre = card.querySelector('.output-text');
    
    if (outputDiv) outputDiv.style.display = 'block';
    if (statusSpan) {
        statusSpan.textContent = 'Status: ERROR';
        statusSpan.style.color = '#ef4444';
    }
    if (textPre) {
        textPre.textContent = errorMessage;
    }
}

async function pollJobStatus(jobId, commandId) {
    const card = document.getElementById(`action-${commandId}`);
    if (!card) return;
    
    const outputDiv = card.querySelector('.action-output');
    const statusSpan = card.querySelector('.output-status');
    const textPre = card.querySelector('.output-text');
    const runBtn = card.querySelector('.run-btn');
    const cancelBtn = card.querySelector('.cancel-btn');
    
    if (outputDiv) outputDiv.style.display = 'block';
    if (runBtn) runBtn.disabled = true;
    if (cancelBtn) cancelBtn.style.display = 'inline-block';
    
    const pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`${RUNNER_URL}/jobs/${jobId}`);
            if (!response.ok) {
                clearInterval(pollInterval);
                if (statusSpan) statusSpan.textContent = 'Status: Error fetching status';
                return;
            }
            
            const job = await response.json();
            
            if (statusSpan) {
                const statusText = job.status.toUpperCase();
                const elapsed = job.elapsed_s.toFixed(1);
                statusSpan.textContent = `Status: ${statusText} (${elapsed}s)`;
                
                // Color code status
                if (job.status === 'succeeded') {
                    statusSpan.style.color = '#10b981';
                } else if (job.status === 'failed' || job.status === 'timed_out') {
                    statusSpan.style.color = '#ef4444';
                } else if (job.status === 'cancelled') {
                    statusSpan.style.color = '#f59e0b';
                }
            }
            
            if (textPre) {
                const output = job.stdout + (job.stderr ? '\n--- stderr ---\n' + job.stderr : '');
                textPre.textContent = output || '(no output)';
            }
            
            // Stop polling if completed
            if (['succeeded', 'failed', 'timed_out', 'cancelled'].includes(job.status)) {
                clearInterval(pollInterval);
                delete activeJobs[commandId];
                if (runBtn) runBtn.disabled = false;
                if (cancelBtn) cancelBtn.style.display = 'none';
            }
        } catch (err) {
            clearInterval(pollInterval);
            if (statusSpan) statusSpan.textContent = `Status: Polling error: ${err.message}`;
            delete activeJobs[commandId];
            if (runBtn) runBtn.disabled = false;
            if (cancelBtn) cancelBtn.style.display = 'none';
        }
    }, 1000);  // Poll every second
}

async function cancelCommand(commandId) {
    const jobId = activeJobs[commandId];
    if (!jobId) return;
    
    try {
        const response = await fetch(`${RUNNER_URL}/jobs/${jobId}/cancel`, {
            method: 'POST'
        });
        
        if (response.ok) {
            showToast('Command cancelled');
        }
    } catch (err) {
        showToast(`Cancel failed: ${err.message}`);
    }
}

// Make runner functions available globally
window.runCommand = runCommand;
window.cancelCommand = cancelCommand;

// Check runner status periodically
setInterval(checkRunnerStatus, 5000);  // Every 5 seconds

// ========================================
// Toast Notifications (Simple)
// ========================================

function showToast(message) {
    const event = new CustomEvent('toast', { detail: { message } });
    window.dispatchEvent(event);
}

window.addEventListener('toast', (e) => {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = e.detail.message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-show');
    }, 10);

    setTimeout(() => {
        toast.classList.remove('toast-show');
        setTimeout(() => toast.remove(), 300);
    }, 2000);
});

// ========================================
// World State Visualization
// ========================================

// Detect and update fusion status indicator
function updateFusionStatus(fusedPositions, rawPerCamera) {
    const badge = document.getElementById('fusion-status-badge');
    if (!badge) return;
    
    // Check if multi-camera fusion is active
    let isMultiCamera = false;
    
    // Check 1: Any fused object has sensors >= 2
    if (fusedPositions.some(pos => pos.sensors && pos.sensors >= 2)) {
        isMultiCamera = true;
    }
    
    // Check 2: raw_per_camera has 2+ active non-stale cameras
    if (rawPerCamera && rawPerCamera.length >= 2) {
        const activeCameras = rawPerCamera.filter(cam => {
            const stale = cam.stale_for_fusion !== undefined ? cam.stale_for_fusion : false;
            return !stale;
        });
        if (activeCameras.length >= 2) {
            isMultiCamera = true;
        }
    }
    
    // Update badge
    badge.className = 'fusion-status-badge';
    if (fusedPositions.length === 0 && (!rawPerCamera || rawPerCamera.length === 0)) {
        badge.textContent = 'UNKNOWN';
        badge.classList.add('unknown');
    } else if (isMultiCamera) {
        badge.textContent = 'MULTI-CAMERA';
        badge.classList.add('multi-camera');
    } else {
        badge.textContent = 'SINGLE-CAMERA';
        badge.classList.add('single-camera');
    }
}

// Update object trails (motion history)
function updateObjectTrails(fusedPositions) {
    const now = Date.now();
    const seenIds = new Set();
    
    // Add new points and update lastSeen
    fusedPositions.forEach(pos => {
        const id = pos.id;
        seenIds.add(id);
        
        if (!objectTrails.has(id)) {
            objectTrails.set(id, { points: [], lastSeen: now });
        }
        
        const trail = objectTrails.get(id);
        trail.lastSeen = now;
        
        // Add point if it's significantly different from last point (> 1mm)
        const lastPoint = trail.points[trail.points.length - 1];
        if (!lastPoint || Math.hypot(pos.x - lastPoint.x, pos.y - lastPoint.y) > 0.001) {
            trail.points.push({ x: pos.x, y: pos.y, ts: now });
            
            // Keep max 50 points
            if (trail.points.length > MAX_TRAIL_POINTS) {
                trail.points.shift();
            }
        }
    });
    
    // Clean up stale trails (not seen for > 2 seconds)
    const toDelete = [];
    for (const [id, trail] of objectTrails.entries()) {
        if (!seenIds.has(id) && (now - trail.lastSeen) > TRAIL_TIMEOUT_MS) {
            toDelete.push(id);
        }
    }
    toDelete.forEach(id => objectTrails.delete(id));
}

// Helper to extract position from multiple formats
function extractPosition(obj) {
    let x, y;
    
    // Try pos_world array
    if (obj.pos_world && Array.isArray(obj.pos_world) && obj.pos_world.length >= 2) {
        x = obj.pos_world[0];
        y = obj.pos_world[1];
    }
    // Try position array
    else if (obj.position && Array.isArray(obj.position) && obj.position.length >= 2) {
        x = obj.position[0];
        y = obj.position[1];
    }
    // Try x/y fields
    else if (obj.x !== undefined && obj.y !== undefined) {
        x = obj.x;
        y = obj.y;
    }
    // Try x_m/y_m fields
    else if (obj.x_m !== undefined && obj.y_m !== undefined) {
        x = obj.x_m;
        y = obj.y_m;
    }
    else {
        return null;
    }
    
    return {
        x, y,
        id: obj.id || obj.object_id || '?',
        confidence: obj.confidence || obj.conf,
        status: obj.status
    };
}

function updateWorldCanvas(fusedObjects, rawPerCamera) {
    const canvas = document.getElementById('world-canvas');
    if (!canvas) return;

    // When live data arrives, show canvas and hide the empty-state placeholder
    const emptyState = document.getElementById('world-canvas-empty');
    const hasData = (fusedObjects && fusedObjects.length > 0) ||
                    (rawPerCamera && rawPerCamera.length > 0);
    if (hasData) {
        canvas.style.display = 'block';
        if (emptyState) emptyState.style.display = 'none';
    }
    
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    
    // Clear canvas
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, width, height);
    
    // Get layer toggles
    const showCam0 = document.getElementById('toggle-cam0')?.checked ?? true;
    const showCam1 = document.getElementById('toggle-cam1')?.checked ?? true;
    const showFused = document.getElementById('toggle-fused')?.checked ?? true;
    const autoFit = document.getElementById('toggle-autofit')?.checked ?? false;
    
    // Update info display
    const totalObjects = fusedObjects.length;
    const totalRaw = rawPerCamera.reduce((sum, cam) => sum + (cam.objects ? cam.objects.length : 0), 0);
    document.getElementById('world-update-time').textContent = `Last update: ${new Date().toLocaleTimeString()}`;
    document.getElementById('world-object-count').textContent = `Fused: ${totalObjects}, Raw: ${totalRaw}`;
    
    // Collect all positions for diagnostics
    let allPositions = [];
    
    // Extract raw camera positions with metadata
    const cam0Raw = [];
    const cam1Raw = [];
    const otherRaw = [];
    
    if (rawPerCamera && rawPerCamera.length > 0) {
        rawPerCamera.forEach(cam => {
            const camId = cam.camera_id || cam.cam_id;
            const camObjects = cam.objects || [];
            
            camObjects.forEach(obj => {
                const pos = extractPosition(obj);
                if (pos) {
                    pos.camera_id = camId;
                    pos.layer = 'raw';
                    allPositions.push(pos);
                    
                    if (camId === 'cam0') cam0Raw.push(pos);
                    else if (camId === 'cam1') cam1Raw.push(pos);
                    else otherRaw.push(pos);
                }
            });
        });
    }
    
    // Extract fused positions with sensor count
    const fusedPositions = (fusedObjects || []).map(obj => {
        const pos = extractPosition(obj);
        if (!pos) return null;
        
        pos.layer = 'fused';
        // Extract sensor count from extra.fusion.sensors
        if (obj.extra && obj.extra.fusion && obj.extra.fusion.sensors !== undefined) {
            pos.sensors = obj.extra.fusion.sensors;
        }
        return pos;
    }).filter(p => p !== null);
    
    // Add fused positions to all positions
    fusedPositions.forEach(pos => allPositions.push(pos));
    
    // Update trails for fused objects
    updateObjectTrails(fusedPositions);
    
    // Detect fusion status
    updateFusionStatus(fusedPositions, rawPerCamera);
    
    // Determine bounds: fixed board extent OR auto-fit to data
    let worldMinX, worldMaxX, worldMinY, worldMaxY, worldWidth, worldHeight;
    
    if (autoFit && allPositions.length > 0) {
        // Auto-fit mode: tight bounds around data
        const xs = allPositions.map(p => p.x);
        const ys = allPositions.map(p => p.y);
        const minX = Math.min(...xs);
        const maxX = Math.max(...xs);
        const minY = Math.min(...ys);
        const maxY = Math.max(...ys);
        
        const rangeX = maxX - minX || 1;
        const rangeY = maxY - minY || 1;
        const padX = rangeX * 0.1;
        const padY = rangeY * 0.1;
        
        worldMinX = minX - padX;
        worldMaxX = maxX + padX;
        worldMinY = minY - padY;
        worldMaxY = maxY + padY;
        
        worldWidth = worldMaxX - worldMinX;
        worldHeight = worldMaxY - worldMinY;
    } else {
        // Fixed board extent mode (default): stable calibration board coordinates
        // Board: 55cm x 40cm with 10% padding
        const boardWidth = 0.55;  // meters
        const boardHeight = 0.40; // meters
        const padding = 0.1;  // 10% padding
        
        worldMinX = 0.0 - boardWidth * padding;
        worldMaxX = boardWidth + boardWidth * padding;
        worldMinY = 0.0 - boardHeight * padding;
        worldMaxY = boardHeight + boardHeight * padding;
        
        worldWidth = worldMaxX - worldMinX;
        worldHeight = worldMaxY - worldMinY;
    }
    
    // Check if we have data to render
    if (allPositions.length === 0) {
        // Still draw the fixed board extent even without data
        if (!autoFit) {
            ctx.fillStyle = '#6b7280';
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Board extent: 0.55m × 0.40m (waiting for data)', width / 2, height / 2);
        } else {
            ctx.fillStyle = '#6b7280';
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('No position data available', width / 2, height / 2);
        }
        return;
    }
    
    // Transform world coords to canvas coords
    const margin = 40;
    const drawWidth = width - 2 * margin;
    const drawHeight = height - 2 * margin;
    
    const scale = Math.min(drawWidth / worldWidth, drawHeight / worldHeight);
    
    function worldToCanvas(x, y) {
        const canvasX = margin + (x - worldMinX) * scale;
        const canvasY = height - margin - (y - worldMinY) * scale;  // Flip Y
        return [canvasX, canvasY];
    }
    
    // Draw grid
    ctx.strokeStyle = '#1a202c';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 10; i++) {
        const x = margin + (drawWidth / 10) * i;
        const y = margin + (drawHeight / 10) * i;
        ctx.beginPath();
        ctx.moveTo(x, margin);
        ctx.lineTo(x, height - margin);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(margin, y);
        ctx.lineTo(width - margin, y);
        ctx.stroke();
    }
    
    // Draw axes
    const [originX, originY] = worldToCanvas(0, 0);
    ctx.strokeStyle = '#2d3748';
    ctx.lineWidth = 2;
    // X-axis
    ctx.beginPath();
    ctx.moveTo(margin, originY);
    ctx.lineTo(width - margin, originY);
    ctx.stroke();
    // Y-axis
    ctx.beginPath();
    ctx.moveTo(originX, margin);
    ctx.lineTo(originX, height - margin);
    ctx.stroke();
    
    // Draw axis labels
    ctx.fillStyle = '#6b7280';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('X (m)', width / 2, height - 5);
    ctx.save();
    ctx.translate(10, height / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Y (m)', 0, 0);
    ctx.restore();
    
    // Draw scale indicator
    ctx.fillStyle = '#9ca3af';
    ctx.font = '11px monospace';
    ctx.textAlign = 'left';
    const scaleText = autoFit 
        ? `Auto-fit: ${worldWidth.toFixed(2)}m × ${worldHeight.toFixed(2)}m`
        : `Board extent: 0.55m × 0.40m`;
    ctx.fillText(scaleText, margin + 5, margin + 15);
    
    // Draw cam0 raw (blue squares)
    if (showCam0) {
        cam0Raw.forEach(pos => {
            const [cx, cy] = worldToCanvas(pos.x, pos.y);
            ctx.strokeStyle = '#3b82f6';
            ctx.lineWidth = 2;
            ctx.strokeRect(cx - 5, cy - 5, 10, 10);
        });
    }
    
    // Draw cam1 raw (purple diamonds)
    if (showCam1) {
        cam1Raw.forEach(pos => {
            const [cx, cy] = worldToCanvas(pos.x, pos.y);
            ctx.strokeStyle = '#7c3aed';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(cx, cy - 7);
            ctx.lineTo(cx + 7, cy);
            ctx.lineTo(cx, cy + 7);
            ctx.lineTo(cx - 7, cy);
            ctx.closePath();
            ctx.stroke();
        });
    }
    
    // Draw other raw (amber triangles)
    otherRaw.forEach(pos => {
        const [cx, cy] = worldToCanvas(pos.x, pos.y);
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(cx, cy - 7);
        ctx.lineTo(cx + 7, cy + 5);
        ctx.lineTo(cx - 7, cy + 5);
        ctx.closePath();
        ctx.stroke();
    });
    
    // Draw object trails (motion history) - check toggle
    const showTrails = document.getElementById('toggle-trails')?.checked ?? false;
    if (showTrails) {
        for (const [id, trail] of objectTrails.entries()) {
            const points = trail.points;
            if (points.length < 2) continue;
            
            // Draw trail as fading polyline
            ctx.strokeStyle = '#06b6d4';
            ctx.lineWidth = 1;
            
            for (let i = 0; i < points.length - 1; i++) {
                const alpha = (i + 1) / points.length;  // Fade from old to new
                const [x1, y1] = worldToCanvas(points[i].x, points[i].y);
                const [x2, y2] = worldToCanvas(points[i + 1].x, points[i + 1].y);
                
                ctx.globalAlpha = alpha * 0.5;  // Max 50% opacity
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.stroke();
            }
            
            ctx.globalAlpha = 1.0;  // Reset opacity
        }
    }
    
    // Compute raw-delta diagnostics (cam0 vs cam1 distance for matching IDs)
    const rawDelta = new Map();
    fusedPositions.forEach(fused => {
        const id = fused.id;
        const cam0Match = cam0Raw.find(r => r.id === id);
        const cam1Match = cam1Raw.find(r => r.id === id);
        
        if (cam0Match && cam1Match) {
            const dx = cam0Match.x - cam1Match.x;
            const dy = cam0Match.y - cam1Match.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            rawDelta.set(id, dist);
        }
    });
    
    // Draw fused objects (solid circles)
    if (showFused) {
        fusedPositions.forEach(pos => {
            const [cx, cy] = worldToCanvas(pos.x, pos.y);
            
            // Color based on confidence/status
            let color = '#06b6d4';  // Default cyan
            if (pos.confidence !== undefined) {
                if (pos.confidence > 0.8) color = '#10b981';  // Green
                else if (pos.confidence < 0.5) color = '#f59e0b';  // Orange
            }
            if (pos.status === 'stale') color = '#ef4444';  // Red
            
            // Draw solid circle
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(cx, cy, 5, 0, 2 * Math.PI);
            ctx.fill();
            
            // Draw ID label with sensor count and raw-delta
            ctx.fillStyle = '#e5e7eb';
            ctx.font = '10px monospace';
            ctx.textAlign = 'center';
            let label = pos.id;
            if (pos.sensors !== undefined) {
                label += ` s=${pos.sensors}`;
            }
            
            // Add raw-delta if available
            const delta = rawDelta.get(pos.id);
            if (delta !== undefined) {
                const deltaColor = delta > 0.02 ? '#ef4444' : '#10b981';  // Red if > 20mm, green otherwise
                ctx.fillText(label, cx, cy - 10);
                ctx.fillStyle = deltaColor;
                ctx.font = '9px monospace';
                ctx.fillText(`δ=${(delta * 1000).toFixed(1)}mm`, cx, cy + 25);
            } else {
                ctx.fillText(label, cx, cy - 10);
            }
            
            // Draw confidence if available
            if (pos.confidence !== undefined) {
                ctx.fillStyle = '#9ca3af';
                ctx.font = '9px monospace';
                ctx.fillText(pos.confidence.toFixed(2), cx, cy + 18);
            }
        });
    }
}

function updateCameraTelemetry(camerasData) {
    const container = document.getElementById('camera-telemetry');
    if (!container) return;
    
    if (!camerasData || camerasData.length === 0) {
        container.innerHTML = '<div class="empty-state">No camera data</div>';
        return;
    }
    
    container.innerHTML = camerasData.map(cam => {
        const camId = cam.camera_id || cam.cam_id || '?';
        const detections = cam.detections !== undefined ? cam.detections : cam.detection_count;
        const stale = cam.stale_for_fusion !== undefined ? cam.stale_for_fusion : false;
        const mapped = cam.mapped_count !== undefined ? cam.mapped_count : cam.kept_count;
        const kept = cam.kept_count;
        
        const staleClass = stale ? 'stale' : 'healthy';
        const staleText = stale ? 'STALE' : 'OK';
        
        return `
            <div class="camera-card">
                <div class="camera-card-header">Camera ${camId}</div>
                <div class="camera-stat">
                    <span class="camera-stat-label">Detections</span>
                    <span class="camera-stat-value">${detections !== undefined ? detections : '—'}</span>
                </div>
                ${mapped !== undefined ? `
                <div class="camera-stat">
                    <span class="camera-stat-label">Mapped</span>
                    <span class="camera-stat-value">${mapped}</span>
                </div>
                ` : ''}
                ${kept !== undefined ? `
                <div class="camera-stat">
                    <span class="camera-stat-label">Kept</span>
                    <span class="camera-stat-value">${kept}</span>
                </div>
                ` : ''}
                <div class="camera-stat">
                    <span class="camera-stat-label">Fusion</span>
                    <span class="camera-stat-value ${staleClass}">${staleText}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ========================================
// Initialization
// ========================================

function init() {
    console.log('[Dashboard] Initializing...');
    
    // Setup navigation
    setupNavigation();
    
    // Start WebSocket
    connectWebSocket();
    
    // Start polling
    startHealthPolling();
    startMetricsPolling();
    
    // Load manifest (one-time)
    loadManifest();
    
    console.log('[Dashboard] Ready');
}

// Start when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (ws) ws.close();
    if (healthPollTimer) clearInterval(healthPollTimer);
    if (metricsPollTimer) clearInterval(metricsPollTimer);
    if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
});
