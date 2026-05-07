# Metriplane Evidence Manifest Specification

**Version**: 1.0  
**Last Updated**: 2026-04-26  
**Purpose**: Define standard format for tracking benchmark outputs and demo results

---

## Purpose

The **evidence manifest** (`evidence/manifest.csv`) provides a machine-readable catalog of all benchmark runs, test outputs, and demonstration results for:

1. **Evaluation Documentation**: Quick reference for which evidence files support which claims
2. **Reproducibility**: Track which commits/configs produced which results
3. **Release Validation**: Verify all M9 demos produce expected outputs
4. **Artifact Management**: Document large files kept out of Git (with SHA-256 for verification)

**Location**: `evidence/manifest.csv` (tracked in Git)  
**Large Artifacts**: `evidence/*.{mp4,jsonl,png}` (NOT tracked, included in `.gitignore`)

---

## CSV Format

### Column Specification

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `demo_id` | string | Yes | Unique demo identifier (e.g., `m9_1_determinism`, `m9_2_backpressure`) |
| `category` | string | Yes | Category: `determinism`, `backpressure`, `health`, `provenance`, `timing`, `gpu`, `integration` |
| `status` | string | Yes | Result: `PASS`, `FAIL`, `PARTIAL`, `SKIP` |
| `run_timestamp` | ISO8601 | Yes | When demo was executed (e.g., `2026-04-26T20:00:00+03:00`) |
| `git_commit` | string | Yes | Git commit hash (short or full) |
| `config_file` | string | Yes | Config used (e.g., `configs/fusion_health_300fps.yaml`) |
| `duration_s` | float | Yes | Demo duration in seconds |
| `artifact_path` | string | No | Relative path to output file (e.g., `evidence/m9_1_determinism_run1.jsonl`) |
| `artifact_sha256` | string | No | SHA-256 hash of artifact (for large files not in Git) |
| `artifact_size_mb` | float | No | Size in megabytes |
| `metric_key` | string | No | Key metric name (e.g., `frame_hash_match_count`, `fps_avg`) |
| `metric_value` | string | No | Metric value (may be numeric or text: "300", "healthy", "cpu", "true") |
| `pass_criteria` | string | No | Expected condition (e.g., `frame_hash_match_count == 100`, `fps_avg >= 25`) |
| `notes` | string | No | Free-text notes (e.g., "Replay run 1 vs run 2, CPU backend") |

### CSV Header

```csv
demo_id,category,status,run_timestamp,git_commit,config_file,duration_s,artifact_path,artifact_sha256,artifact_size_mb,metric_key,metric_value,pass_criteria,notes
```

---

## Example Rows

### 1. Deterministic Replay (M9.1)

```csv
m9_1_determinism_cpu_run1,determinism,PASS,2026-04-26T20:00:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_1_determinism_cpu_run1.jsonl,<sha256>,5.2,frame_count,300,frame_count > 0,CPU replay run 1 (illustrative)
m9_1_determinism_cpu_run2,determinism,PASS,2026-04-26T20:00:15+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_1_determinism_cpu_run2.jsonl,<sha256>,5.2,frame_hash_match,300,frame_hash_match == frame_count,CPU run 2 matches run 1 (illustrative)
m9_1_determinism_gpu_run1,determinism,PASS,2026-04-26T20:01:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_1_determinism_gpu_run1.jsonl,<sha256>,5.2,frame_count,300,frame_count > 0,GPU replay run 1 (illustrative)
m9_1_determinism_gpu_run2,determinism,PASS,2026-04-26T20:01:15+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_1_determinism_gpu_run2.jsonl,<sha256>,5.2,frame_hash_match,300,frame_hash_match == frame_count,GPU run 2 matches run 1 (illustrative)
```

**Note**: Artifact paths and SHA-256 hashes are illustrative examples. Actual paths depend on when/where demos are run.

**PASS Criteria**:
- Frame hashes match 100% between runs (CPU run 1 == CPU run 2, GPU run 1 == GPU run 2)
- Same config produces identical outputs

### 2. Backpressure (M9.2)

```csv
m9_2_backpressure_300fps,backpressure,PASS,2026-04-26T20:05:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,30.0,evidence/m9_2_backpressure_300fps.csv,,0.001,target_fps,300,target_fps <= 300,Synthetic load at 300 FPS target
m9_2_backpressure_300fps,backpressure,PASS,2026-04-26T20:05:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,30.0,evidence/m9_2_backpressure_300fps.csv,,0.001,actual_fps_avg,285,actual_fps_avg >= 200,Actual throughput under load
m9_2_backpressure_300fps,backpressure,PASS,2026-04-26T20:05:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,30.0,evidence/m9_2_backpressure_300fps.csv,,0.001,frames_dropped,450,frames_dropped < 1000,Graceful degradation - frames dropped not crashed
```

**PASS Criteria**:
- System does not crash under load
- Frames dropped (not blocking pipeline)
- Actual FPS >= 200 (target 300, acceptable degradation)

### 3. Health Degradation (M9.3)

```csv
m9_3_health_degrade_cam1,health,PASS,2026-04-26T20:10:00+03:00,06fb0a5,configs/health_demo_missing_mapping_cam1.yaml,20.0,evidence/m9_3_health_degrade.jsonl,<sha256>,2.1,overall_status_before,healthy,overall_status_before == healthy,Before cam1 disabled (illustrative)
m9_3_health_degrade_cam1,health,PASS,2026-04-26T20:10:10+03:00,06fb0a5,configs/health_demo_missing_mapping_cam1.yaml,20.0,evidence/m9_3_health_degrade.jsonl,<sha256>,2.1,overall_status_after,degraded,overall_status_after == degraded,After cam1 disabled at t=10s (illustrative)
m9_3_health_degrade_cam1,health,PASS,2026-04-26T20:10:20+03:00,06fb0a5,configs/health_demo_missing_mapping_cam1.yaml,20.0,evidence/m9_3_health_degrade.jsonl,<sha256>,2.1,cam1_status_after,unhealthy,cam1_status_after == unhealthy,cam1 component marked unhealthy (illustrative)
m9_3_health_degrade_cam1,health,PASS,2026-04-26T20:10:20+03:00,06fb0a5,configs/health_demo_missing_mapping_cam1.yaml,20.0,evidence/m9_3_health_degrade.jsonl,<sha256>,2.1,pipeline_continues,true,pipeline_continues == true,Pipeline continues with cam0 only (illustrative)
```

**PASS Criteria**:
- Health status transitions from `healthy` → `degraded`
- Failing component marked `unhealthy`
- Pipeline continues operation (no crash)

### 4. Provenance (M9.4)

```csv
m9_4_provenance_run1,provenance,PASS,2026-04-26T20:15:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_4_provenance_run1/session.jsonl,<sha256>,5.0,run_id,run_20260426_201500_abc123,run_id != null,Unique run_id assigned (illustrative)
m9_4_provenance_run1,provenance,PASS,2026-04-26T20:15:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_4_provenance_run1/session.jsonl,<sha256>,5.0,config_hash,<sha256>,config_hash != null,Config SHA-256 stamped in every frame (illustrative)
m9_4_provenance_run1,provenance,PASS,2026-04-26T20:15:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_4_provenance_run1/session.jsonl,<sha256>,5.0,git_commit,06fb0a5,git_commit == 06fb0a5,Git commit stamped in every frame (illustrative)
m9_4_provenance_run1,provenance,PASS,2026-04-26T20:15:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_4_provenance_run1/session.jsonl,<sha256>,5.0,schema_version,1.0,schema_version == 1.0,Schema version v1.0 stamped (illustrative)
```

**PASS Criteria**:
- Every frame has `run_id`, `config_hash`, `git_commit`, `schema_version`
- Fields are non-null and consistent across session

### 5. Timing Breakdown (M9.5)

```csv
m9_5_timing_breakdown,timing,PASS,2026-04-26T20:20:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,60.0,evidence/m9_5_timing_breakdown.csv,,0.002,stage_camera_ms_avg,5.2,stage_camera_ms_avg < 10,Camera capture latency
m9_5_timing_breakdown,timing,PASS,2026-04-26T20:20:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,60.0,evidence/m9_5_timing_breakdown.csv,,0.002,stage_detection_ms_avg,8.1,stage_detection_ms_avg < 15,ArUco detection latency
m9_5_timing_breakdown,timing,PASS,2026-04-26T20:20:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,60.0,evidence/m9_5_timing_breakdown.csv,,0.002,stage_mapping_ms_avg,0.3,stage_mapping_ms_avg < 5,Homography mapping latency
m9_5_timing_breakdown,timing,PASS,2026-04-26T20:20:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,60.0,evidence/m9_5_timing_breakdown.csv,,0.002,stage_fusion_ms_avg,1.2,stage_fusion_ms_avg < 10,Fusion latency (CPU backend)
m9_5_timing_breakdown,timing,PASS,2026-04-26T20:20:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,60.0,evidence/m9_5_timing_breakdown.csv,,0.002,stage_ws_ms_avg,0.5,stage_ws_ms_avg < 5,WebSocket broadcast latency
m9_5_timing_breakdown,timing,PASS,2026-04-26T20:20:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,60.0,evidence/m9_5_timing_breakdown.csv,,0.002,latency_total_ms_avg,15.3,latency_total_ms_avg < 50,End-to-end latency (camera to WS)
```

**PASS Criteria**:
- Total latency < 50ms average (real-time threshold)
- Per-stage latencies within expected bounds

### 6. GPU Equivalence (M9.6)

```csv
m9_6_gpu_equivalence,gpu,PASS,2026-04-26T20:25:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_6_gpu_equivalence_cpu.jsonl,<sha256>,5.0,backend,cpu,backend == cpu,CPU run for comparison (illustrative)
m9_6_gpu_equivalence,gpu,PASS,2026-04-26T20:25:15+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_6_gpu_equivalence_gpu.jsonl,<sha256>,5.0,backend,gpu,backend == gpu,GPU run for comparison (illustrative)
m9_6_gpu_equivalence,gpu,PASS,2026-04-26T20:25:30+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_6_gpu_equivalence_diff.csv,,0.001,position_diff_max_mm,0.01,position_diff_max_mm < 1.0,Max XY position difference < 1mm (illustrative)
m9_6_gpu_equivalence,gpu,PASS,2026-04-26T20:25:30+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_6_gpu_equivalence_diff.csv,,0.001,frames_compared,300,frames_compared > 0,Total frames compared (illustrative)
```

**PASS Criteria**:
- CPU and GPU outputs differ by < 1mm in XY coordinates (numerical precision tolerance)
- All frames compared successfully

---

## Required PASS Criteria Per Demo

### M9.1: Deterministic Replay

**Criteria**:
- ✅ Frame hashes match 100% between replay run 1 and run 2 (same backend)
- ✅ Same input produces same output (bit-exact)
- ✅ Both CPU and GPU backends individually deterministic

**Evidence Files**:
- `evidence/m9_1_determinism_cpu_run1.jsonl`
- `evidence/m9_1_determinism_cpu_run2.jsonl`
- `evidence/m9_1_determinism_gpu_run1.jsonl`
- `evidence/m9_1_determinism_gpu_run2.jsonl`
- `evidence/m9_1_determinism_comparison.csv` (hash match results)

### M9.2: Backpressure Handling

**Criteria**:
- ✅ System does not crash under 300 FPS target load
- ✅ Frames dropped gracefully (not blocking)
- ✅ Actual FPS >= 200 (acceptable degradation from 300 target)
- ✅ Bounded queue prevents unbounded memory growth

**Evidence Files**:
- `evidence/m9_2_backpressure_300fps.csv` (throughput, drops, queue depth)

### M9.3: Health Degradation

**Criteria**:
- ✅ Health status transitions `healthy` → `degraded`
- ✅ Failing component marked `unhealthy`
- ✅ Pipeline continues with remaining cameras
- ✅ Overall status reflects component health

**Evidence Files**:
- `evidence/m9_3_health_degrade_cam1.jsonl` (session with fault injection)
- `evidence/m9_3_health_timeline.csv` (health status over time)

### M9.4: Config Provenance

**Criteria**:
- ✅ Every frame has `run_id` (non-null, unique per session)
- ✅ Every frame has `config_hash` (SHA-256 of config content)
- ✅ Every frame has `git_commit` (matches current commit)
- ✅ Every frame has `schema_version: "1.0"`

**Evidence Files**:
- `evidence/m9_4_provenance_run1/session.jsonl`
- `evidence/m9_4_provenance_validation.csv` (provenance field checks)

### M9.5: Timing Breakdown

**Criteria**:
- ✅ End-to-end latency < 50ms average (real-time threshold)
- ✅ Per-stage latencies measured and within bounds
- ✅ Camera: < 10ms, Detection: < 15ms, Mapping: < 5ms, Fusion: < 10ms, WS: < 5ms

**Evidence Files**:
- `evidence/m9_5_timing_breakdown.csv` (per-stage latencies)

### M9.6: GPU Equivalence & Benchmark

**Criteria (Equivalence)**:
- ✅ CPU vs GPU position difference < 1mm (numerical precision)
- ✅ All frames compared successfully

**Criteria (Benchmark)**:
- ✅ Benchmark reports honest CPU and GPU metrics (throughput, latency)
- ✅ Speedup factor calculated and recorded (may be >1.0x or <1.0x depending on workload)

**Note**: GPU is not required to be faster than CPU. PASS means equivalence is verified and benchmark data is honestly reported.

**Evidence Files**:
- `evidence/m9_6_gpu_equivalence_cpu.jsonl`
- `evidence/m9_6_gpu_equivalence_gpu.jsonl`
- `evidence/m9_6_gpu_equivalence_diff.csv`
- `evidence/m9_6_gpu_benchmark.csv` (throughput, speedup factor)

---

## SHA-256 Handling

### When to Include SHA-256

**Required for**:
- Large artifacts (> 1MB) kept out of Git
- Binary files (JSONL, video, images)
- Files referenced in evaluation but not in repository

**Not Required for**:
- Small CSV files tracked in Git (<100KB)
- Files already in Git (Git provides SHA-1 hash)

### Generate SHA-256

```bash
# Single file
sha256sum evidence/m9_1_determinism_cpu_run1.jsonl

# Multiple files
sha256sum evidence/*.jsonl > evidence/checksums.txt
```

### Verify Artifacts

```bash
# Check manifest SHA-256 matches actual file
awk -F, 'NR>1 && $9!="" {print $9 "  " $8}' evidence/manifest.csv | sha256sum -c
```

---

## Relationship to Existing Scripts

### tools/mp.sh

The manifest should reflect outputs from `mp.sh` commands:

```bash
# M9.1: Deterministic Replay
./tools/mp.sh deterministic-replay
# Generates: Run dirs with session.jsonl files
# Manifest row: demo_id=m9_1_determinism, artifact_path points to output

# M9.2: Backpressure
./tools/mp.sh backpressure
# Generates: CSV with throughput metrics
# Manifest row: demo_id=m9_2_backpressure, artifact_path points to CSV

# M9.3: Health Degradation
./tools/mp.sh health-degrade-cam1
# Generates: Session JSONL with health transitions
# Manifest row: demo_id=m9_3_health_degrade, status transitions tracked

# M9.4: Provenance
./tools/mp.sh provenance
# Generates: Run dir with stamped session.jsonl
# Manifest row: demo_id=m9_4_provenance, validates stamping

# M9.5: Timing Breakdown
./tools/mp.sh timing-breakdown
# Generates: CSV with per-stage latencies
# Manifest row: demo_id=m9_5_timing, latencies listed

# M9.6: GPU Tests
./tools/mp.sh gpu-equivalence
./tools/mp.sh gpu-benchmark
# Generates: Comparison CSVs
# Manifest rows: demo_id=m9_6_gpu_*, equivalence and benchmark results
```

### scripts/M9_full.sh

**Current State**: M9_full.sh does not yet generate the manifest automatically.

**Future Integration Target**: The manifest could serve as a checklist for M9_full.sh execution:

```bash
# Pseudo-code for future M9_full.sh integration:
# 1. Run all M9 demos
# 2. Capture outputs to evidence/
# 3. Generate manifest.csv with results (FUTURE: automated)
# 4. Validate all demos PASS
# 5. Exit 0 if all PASS, exit 1 if any FAIL
```

**Manual Validation** (current workaround):
```bash
# Check all M9 demos passed
awk -F, '$1 ~ /^m9_/ && $3 != "PASS" {print "FAIL: " $1; exit 1}' evidence/manifest.csv && echo "✅ All M9 demos PASS"
```

### scripts/DEMO_ALL.sh

Simpler version for quick smoke tests:

```bash
# demo-all runs shorter tests (5-10s each)
# Manifest includes demo-all runs for quick validation
# Status should be PASS for all core features
```

---

## Large Artifacts Strategy

### Keep Out of Git

**Add to `.gitignore`**:
```
evidence/*.jsonl
evidence/*.mp4
evidence/*.png
evidence/*.jpg
evidence/runs/
```

**Track in Git** (small files only):
```
evidence/manifest.csv          # Always tracked
evidence/*.csv                 # Metrics CSVs (usually <100KB)
evidence/checksums.txt         # SHA-256 for large files
```

### Why Not Track Large Files?

- **Repository bloat**: JSONL sessions can be 5-50MB each
- **Git performance**: Large binary files slow clone/fetch
- **Storage costs**: GitHub has repo size limits
- **Reproducibility**: Manifest + checksums allow verification without committing files

### Alternative Storage

For archiving and reproducibility:
1. **Zenodo**: Upload `evidence.tar.gz` with DOI
2. **Google Drive**: Share link in manifest or evaluation appendix
3. **University Repository**: Institutional data storage
4. **Git LFS**: If necessary (not recommended for community repos)

### Manifest as Inventory

The manifest provides a **complete inventory** of evidence without storing files in Git:

```csv
demo_id,category,status,artifact_path,artifact_sha256,artifact_size_mb,notes
m9_1_determinism_cpu_run1,determinism,PASS,evidence/m9_1_determinism_cpu_run1.jsonl,<sha256>,5.2,Available on request or Zenodo (illustrative)
```

Consumers can:
- See what evidence exists (manifest tracked)
- Request specific files if needed
- Verify file integrity (SHA-256)
- Reproduce results (commit + config documented)

---

## Workflow Integration

### Generate Manifest

**Manual** (current):
```bash
# Run demo
./tools/mp.sh deterministic-replay

# Add row to evidence/manifest.csv manually
# Calculate SHA-256: sha256sum ~/metriplane-runs/*/session.jsonl
```

**Automated** (future):
```bash
# tools/generate_evidence_manifest.py (not yet implemented)
python tools/generate_evidence_manifest.py \
  --demo-id m9_1_determinism \
  --run-dir ~/metriplane-runs/my_run_001 \
  --status PASS \
  --update evidence/manifest.csv
```

### Validate Manifest

```bash
# Check all demos have PASS status
awk -F, 'NR>1 && $1 ~ /^m9_/ && $3 != "PASS" {print "FAIL: " $1}' evidence/manifest.csv

# Verify SHA-256 checksums
# (for files present locally)
awk -F, 'NR>1 && $9 != "" {print $9 "  " $8}' evidence/manifest.csv | sha256sum -c

# Check all required demos present
for demo in m9_1_determinism m9_2_backpressure m9_3_health_degrade m9_4_provenance m9_5_timing m9_6_gpu_equivalence; do
  grep -q "^$demo," evidence/manifest.csv || echo "MISSING: $demo"
done
```

---

## Manifest Maintenance

### When to Update

**Add Row When**:
- Running any M9 demo (`./tools/mp.sh <demo>`)
- Running benchmarks (`benchmarks/run_*.py`)
- Generating evidence
- Validating release candidate

**Update Row When**:
- Re-running demo with new code (update `git_commit`, `artifact_sha256`)
- Status changes (e.g., FAIL → PASS after bugfix)

### Manifest Rotation

**For Active Development**:
- Keep only latest run per demo_id
- Rotate old rows to `evidence/manifest_archive.csv`

**For Evaluation/Release**:
- Freeze manifest for release
- Copy to `evidence/manifest_v1.0_final.csv`
- Tag with git commit and date

---

## Future Enhancements

### V1.1 Manifest Features

- **Auto-generation**: `tools/mp.sh` appends to manifest automatically
- **JSON format**: `evidence/manifest.json` for programmatic access
- **Web viewer**: Interactive HTML dashboard from manifest
- **CI integration**: GitHub Actions validates manifest on PR

### V2.0 Manifest Features

- **Time-series tracking**: Historical performance trends
- **Regression detection**: Alert if metrics degrade
- **Artifact compression**: Auto-compress .jsonl to .jsonl.gz
- **Cloud sync**: S3/Zenodo upload integration

---

## Example Manifest File

Complete `evidence/manifest.csv` for M9 demos:

```csv
demo_id,category,status,run_timestamp,git_commit,config_file,duration_s,artifact_path,artifact_sha256,artifact_size_mb,metric_key,metric_value,pass_criteria,notes
m9_1_determinism_cpu_run1,determinism,PASS,2026-04-26T20:00:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_1_determinism_cpu_run1.jsonl,<sha256>,5.2,frame_count,300,frame_count > 0,CPU replay run 1 (illustrative)
m9_1_determinism_cpu_run2,determinism,PASS,2026-04-26T20:00:15+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_1_determinism_cpu_run2.jsonl,<sha256>,5.2,frame_hash_match,300,frame_hash_match == frame_count,CPU run 2 matches run 1 (illustrative)
m9_2_backpressure_300fps,backpressure,PASS,2026-04-26T20:05:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,30.0,evidence/m9_2_backpressure_300fps.csv,,0.001,actual_fps_avg,285,actual_fps_avg >= 200,Throughput under load (illustrative)
m9_3_health_degrade_cam1,health,PASS,2026-04-26T20:10:00+03:00,06fb0a5,configs/health_demo_missing_mapping_cam1.yaml,20.0,evidence/m9_3_health_degrade.jsonl,<sha256>,2.1,overall_status_after,degraded,overall_status_after == degraded,Health degrades with cam1 disabled (illustrative)
m9_4_provenance_run1,provenance,PASS,2026-04-26T20:15:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_4_provenance_run1/session.jsonl,<sha256>,5.0,config_hash,<sha256>,config_hash != null,Config stamped in frames (illustrative)
m9_5_timing_breakdown,timing,PASS,2026-04-26T20:20:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,60.0,evidence/m9_5_timing_breakdown.csv,,0.002,latency_total_ms_avg,15.3,latency_total_ms_avg < 50,End-to-end latency (illustrative)
m9_6_gpu_equivalence,gpu,PASS,2026-04-26T20:25:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_6_gpu_equivalence_diff.csv,,0.001,position_diff_max_mm,0.01,position_diff_max_mm < 1.0,CPU vs GPU equivalence (illustrative)
m9_6_gpu_benchmark,gpu,PASS,2026-04-26T20:30:00+03:00,06fb0a5,configs/fusion_health_300fps.yaml,10.0,evidence/m9_6_gpu_benchmark.csv,,0.001,speedup_factor,2.3,speedup_factor >= 1.0,GPU vs CPU performance (illustrative)
```

**Note**: All artifact paths, SHA-256 hashes, and metric values are illustrative examples for documentation purposes.

---

## Usage Examples

### Query Manifest

**Get all PASS demos**:
```bash
awk -F, 'NR>1 && $3=="PASS" {print $1}' evidence/manifest.csv
```

**Get determinism evidence**:
```bash
awk -F, 'NR>1 && $2=="determinism" {print $1 "," $3 "," $8}' evidence/manifest.csv
```

**Check M9 completion**:
```bash
for m in m9_1 m9_2 m9_3 m9_4 m9_5 m9_6; do
  count=$(awk -F, -v m="$m" 'NR>1 && $1 ~ m && $3=="PASS"' evidence/manifest.csv | wc -l)
  echo "$m: $count demo(s) PASS"
done
```

### Evaluation Integration

**Generate Evidence Table** (LaTeX):
```python
# tools/export_manifest_latex.py
import csv

with open('evidence/manifest.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['category'] == 'determinism':
            print(f"\\texttt{{{row['demo_id']}}} & {row['status']} & {row['metric_value']} \\\\")
```

---

## Implementation Roadmap

### Phase 1: Manual Manifest (Current)
- Create `evidence/manifest.csv` by hand
- Record outputs from `./tools/mp.sh` commands
- Calculate SHA-256 manually

### Phase 2: Semi-Automated (V1.0)
- Add CSV append helper: `tools/add_manifest_entry.sh`
- Update `tools/mp.sh` to print manifest-ready output
- Validation script: `tools/validate_manifest.py`

### Phase 3: Fully Automated (V1.1)
- Generate manifest automatically from `tools/mp.sh` runs
- Append to manifest.csv on every demo execution
- Validate on CI (GitHub Actions checks manifest completeness)

### Phase 4: Advanced Features (V2.0)
- JSON format for programmatic access
- Web dashboard for evidence browsing
- Historical tracking and regression detection

---

## Notes and Recommendations

### Git Hygiene

- ✅ **DO track**: `evidence/manifest.csv` (inventory)
- ✅ **DO track**: Small CSVs < 100KB (metrics summaries)
- ✅ **DO track**: `evidence/checksums.txt` (SHA-256 hashes)
- ❌ **DO NOT track**: `*.jsonl` > 1MB (session recordings)
- ❌ **DO NOT track**: `*.mp4` (video captures)
- ❌ **DO NOT track**: `evidence/runs/*` (run directories)

**Note on .gitignore**: If `evidence/` is globally ignored, add explicit exceptions:
```gitignore
evidence/
!evidence/manifest.csv
!evidence/checksums.txt
!evidence/*.csv
```

### Reproducibility Without Artifacts

The manifest enables reproducibility even without artifact files:

1. **Config + Commit**: Checkout commit, use config file
2. **Re-run Demo**: `./tools/mp.sh deterministic-replay` with same input
3. **Compare SHA-256**: New output should match manifest hash
4. **Validate PASS**: Criteria should still be met

### Evaluation Requirements

For evaluation submission, the manifest should:
- List all evidence supporting claims (Table in Appendix A)
- Reference Zenodo DOI for large artifacts
- Include PASS/FAIL criteria for each claim
- Link demo_id to documentation sections

---

**Version**: 1.0  
**Status**: Specification complete, implementation pending  
**Next Step**: Create manual manifest for existing M9 outputs, then automate in V1.1
