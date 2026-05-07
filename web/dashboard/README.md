# Metriplane Dashboard V1

Lightweight browser-based dashboard for monitoring Metriplane runtime.

## Features

- **WebSocket Live Stream**: Real-time object tracking and zone events
- **Health Monitoring**: Poll `/health` endpoint for system status
- **Metrics Display**: View Prometheus metrics from `/metrics` endpoint
- **Evidence Manifest**: Browse M9 demo results from `evidence/manifest.csv`
- **Command Helper**: Copyable commands for common operations (no execution)

## Quick Start

### 1. Start Metriplane Pipeline

```bash
# From repository root
./tools/mp.sh run-fusion cpu 60 test
```

This starts:
- WebSocket server on `ws://localhost:8765`
- Metrics/Health HTTP server on `http://localhost:8000`

### 2. Launch Dashboard

```bash
# From repository root
python -m http.server 8088 -d web/dashboard
```

### 3. Open in Browser

Navigate to: http://localhost:8088/

## Requirements

- **Metriplane running**: Pipeline must be active on localhost
- **Modern browser**: Chrome, Firefox, or Safari (ES6 support)
- **No build tools**: Pure HTML/CSS/JS, no npm required

## Limitations

### Read-Only
- Dashboard cannot start/stop pipeline
- Dashboard cannot edit configurations
- Dashboard cannot execute shell commands

### Endpoint Dependencies
- WebSocket: Requires `ws://localhost:8765` active
- Health: Requires `http://localhost:8000/health` endpoint
- Metrics: Requires `http://localhost:8000/metrics` endpoint

### Evidence Manifest Loading
The manifest viewer tries to fetch `evidence/manifest.csv` from:
1. `../../evidence/manifest.csv` (if served from repo root context)
2. `evidence/manifest.csv` (if copied locally)

**If manifest doesn't load**:
- Option A: Serve from repository root instead of `web/dashboard/`
- Option B: Copy `evidence/manifest.csv` to `web/dashboard/data/manifest.csv` and update fetch path

## Troubleshooting

### WebSocket Won't Connect
**Symptom**: "WebSocket: Disconnected" status  
**Fix**: Ensure Metriplane pipeline is running: `./tools/mp.sh run-fusion cpu 60 test`

### Health/Metrics Endpoints Offline
**Symptom**: "Health: Offline" or "Metrics: Offline"  
**Fix**: Check if metrics server is running on port 8000

### CORS Errors
**Symptom**: Browser console shows CORS errors  
**Fix**: Dashboard must be served from HTTP server, not `file://` URL

### Manifest Not Loading
**Symptom**: "Manifest: Unavailable"  
**Solutions**:
1. Serve entire repository with: `python -m http.server 8088` (from repo root)
2. Copy manifest: `cp evidence/manifest.csv web/dashboard/data/manifest.csv`
3. View manifest status in status cards for instructions

## Architecture

### Data Flow
```
Browser Dashboard (port 8088)
    │
    ├─> WebSocket (ws://localhost:8765)    [Real-time objects]
    ├─> HTTP GET /health (port 8000)       [Poll every 2s]
    ├─> HTTP GET /metrics (port 8000)      [Poll every 5s]
    └─> HTTP GET ../../evidence/manifest.csv [Once on load]
```

### Files
- `index.html`: Main dashboard UI
- `app.js`: WebSocket, polling, and data handling
- `style.css`: Responsive layout and styling
- `README.md`: This file

### No Dependencies
- No npm packages
- No build step
- No transpilation
- Vanilla JS (ES6)

## Development

### Testing Changes
1. Edit files in `web/dashboard/`
2. Refresh browser (Ctrl+R or Cmd+R)
3. Check browser console for errors

### Browser Console
Press F12 to open developer tools and monitor:
- WebSocket connection status
- XHR requests to health/metrics
- JavaScript errors
- Network activity

## Usage Tips

### Viewing Long-Running Sessions
The dashboard auto-scrolls to show latest objects. For historical analysis:
- Use recorded session files (`.jsonl`)
- Replay with: `metriplane replay --input session.jsonl ...`
- Dashboard will show replayed objects in real-time

### Monitoring Multiple Runs
Open multiple browser tabs to monitor:
- Tab 1: Live production run
- Tab 2: Replay analysis
- Each tab connects independently to WebSocket

### Copying Commands
Use the Command Helper panel to copy common mp.sh commands:
- Hover over command
- Click "Copy" button
- Paste into terminal

## Version

**Dashboard V1**: Read-only monitoring  
**Last Updated**: 2026-04-26

## Future Enhancements (V2+)

Potential future features:
- Camera preview thumbnails
- Historical metric charts (with Chart.js)
- Log streaming
- Configuration editor (with validation)
- Start/stop pipeline controls (with safety checks)

---

**Note**: This is a monitoring tool. For full control, use `./tools/mp.sh` commands directly.
