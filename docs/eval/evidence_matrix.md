# Metriplane — Evidence Matrix

**Generated**: 2026-04-28 | **Updated**: 2026-04-29 | **Tests**: 193/193 passing  
**Tests**: 193/193 passing (as of initial-public-release)  
Key: ✅ YES · ⚠️ PARTIAL · ❌ NO  
> 

---

## Technical Benchmark Evidence

| Claim | Required evidence | Expected artifact path | Found? | Actual artifact path(s) | Quality assessment | Missing action | Regenerate command |
|---|---|---|---|---|---|---|---|
| Deterministic replay: bit-exact frame replay | CSV with max_pos_diff_cm=0.0 and event_mismatch_count=0 | `evidence/experiments/replay_determinism.csv` | ✅ YES | `evidence/experiments/replay_determinism.csv` (SHA: 5705e43…) + `replay_det_001.csv` + manifest row `m9_1_deterministic_replay` | 301 frames, 0.0 cm max diff, 0 mismatches. Has git_commit. | — | `./tools/mp.sh deterministic-replay` |
| Backpressure: bounded queue under overload | CSV with drop counts, queue depth, latency | `evidence/experiments/backpressure_summary.csv` | ✅ YES | `evidence/experiments/backpressure_summary.csv` + `backpressure_timeseries_001.csv` + manifest row `m9_2_backpressure` | 30s at 120Hz, drops=2600, queue_max=5 honored, pass=true | — | `./tools/mp.sh backpressure` |
| Health degradation: graceful degradation on missing camera | Health metric CSV + scenario description | `evidence/experiments/health_degrade_*` | ⚠️ PARTIAL | `evidence/experiments/health_degrade_cam1_meta.json` (SHA present) **but no manifest row and no scenario CSV** | Only meta JSON. No narrative of what degradation looks like numerically. | Add manifest row; write a 1-page scenario CSV (`health_degrade_cam1_summary.csv`) | `./tools/mp.sh health-demo` or `configs/health_demo_missing_mapping_cam1.yaml` |
| Provenance stamping: run_id/config_hash/git_commit present | JSON with all four provenance fields | `evidence/experiments/run_meta.json` | ✅ YES | `evidence/experiments/run_meta.json` (SHA: 49997d1…) + manifest row `m9_4_provenance` | config_hash=e434604…, run_id, git_commit, schema_version all present | — | `./tools/mp.sh provenance` |
| Timing breakdown: per-stage latency | CSV with stage, count, mean_ms, p50_ms, p95_ms, git_commit | `evidence/experiments/latency_summary.csv` | ✅ YES | `evidence/experiments/latency_summary.csv` (SHA: 550b84d…) + manifest row `m9_5_timing_breakdown` | Full provenance: run_id + config_hash + git_commit. detect.cam0 p95=1.50ms, detect.cam1 p95=1.72ms, fuse p95=0.19ms | — | `./tools/mp.sh timing-breakdown` |
| Latency summary table | Table of per-stage p50/p95/max values | `evidence/experiments/latency_summary.csv` | ✅ YES | Same as above. Narrative in `docs/eval/latency_summary.md` | Strong. Git commit in CSV data. | Consider adding end-to-end WebSocket latency column | — |
| FPS / update-rate summary | Mean and range of FPS across a recording session | `docs/eval/fps_summary.md` | ✅ YES | `docs/eval/fps_summary.md` + manifest row `fps_update_rate` (mean 291.2, range 282–304 FPS, 4384 frames) | 15s session, commit bfce3d9. Solid. | — | Replay session + extract timestamps |
| Mapping error CSV and summary table | CSV of marker position error vs ground truth | `evidence/experiments/mapping_error_001.csv` | ✅ YES | `evidence/experiments/mapping_error_001.csv` + manifest row `mapping_error_001` | mean 0.40cm, max 1.09cm, N=9 points, commit recorded | — | `python benchmarks/run_mapping_error.py` |
| ID stability / drop-rate CSV (static) | Per-object coverage_pct, n_missing_gaps | `evidence/experiments/id_stability_001.csv` | ✅ YES | `evidence/experiments/id_stability_001.csv` (SHA: e30ee71…) + manifest row `id_continuity_001` | 3 objects, 100% coverage, 0 gaps, 4384 frames, commit bfce3d9 | — | `tools/analyze_id_stability_jsonl.py <session>` |
| ID stability under motion | Per-object coverage_pct ≥ 95% under movement | `evidence/experiments/id_stability_movement_001.csv` | ✅ YES | `evidence/experiments/id_stability_movement_001.csv` + manifest row `id_stability_movement_001` | IDs 4/7/12 all >97.4%; 300s session, 87608 frames, commit 9ac3366 | — | `tools/analyze_id_stability_jsonl.py <case_study_session>` |
| Fusion jitter / coverage CSV | Per-object jitter_std_m, coverage_pct, max_error_m | `evidence/experiments/fusion_jitter_001.csv` | ⚠️ PARTIAL | `evidence/experiments/fusion_jitter_001.csv` + manifest row `fusion_jitter_001` (**`max_error_m` column is all NaN** — ground-truth comparison not run) | jitter_std_m values present (0.00007–0.00023 m). max_error_m NaN suggests ground-truth comparison was not run. | NaN means ground-truth fusion accuracy not compared; acceptable — jitter_std_m is present | `python benchmarks/run_fusion_jitter.py` |
| CPU vs GPU benchmark CSV | Per-backend latency comparison (cpu_numpy vs gpu_cupy) | `evidence/experiments/gpu_benchmark_001.csv` | ✅ YES | `evidence/experiments/gpu_benchmark_001.csv` + manifest row `gpu_benchmark_001` | N=1..1000, CPU faster at all N; CPU p50(N=1000)=2.226ms GPU=2.642ms | — | `./tools/mp.sh gpu-benchmark` (requires cupy env) |
| CPU vs GPU equivalence CSV with nonzero frames | rmse_diff_cm=0.0, max_abs_diff_cm=0.0, frames>0 | `evidence/experiments/compute_equivalence_001.csv` | ✅ YES | `evidence/experiments/compute_equivalence_001.csv` (SHA: cbff2c7…) | 4384 frames, 13152 samples, rmse_diff=0.0, max_diff=0.0, pass=True. **Note: session_jsonl path is absolute local path** | Replace absolute session_jsonl path with checksum reference | `python benchmarks/run_compute_equivalence.py` |

---

## Productization Evidence

| Claim | Required evidence | Expected artifact path | Found? | Actual artifact path(s) | Quality assessment | Missing action | Regenerate command |
|---|---|---|---|---|---|---|---|
| Docker quickstart works | Executed terminal log: container up + WebSocket message received | `evidence/experiments/docker_demo_proof_001.md` | ❌ NO | `docker/docker_quickstart.md` exists as a doc, but **no executed proof artifact** | Documentation only — no proof of execution | Run quickstart, capture output, save to `evidence/experiments/docker_demo_proof_001.md` + manifest row | `./tools/docker_demo_up.sh && tools/ws_smoke_client.py` |
| Onboarding log | Executed onboarding with actual time + steps recorded | `evidence/onboarding/onboarding_001.md` | ⚠️ PARTIAL | `evidence/onboarding/onboarding_001.md` **EXECUTED 2026-04-29** + manifest row `onboarding_001` | **Same-machine fresh clone, warm pip cache — NOT clean-VM.** 6 steps, 1 friction (pytest not in deps), 2.1 min clone-to-demo (incl. tests), stack up in 3s, 193/193 PASS | Execute again on fresh Ubuntu VM with cold cache for quantitative clean-machine claim | Follow `evidence/onboarding/onboarding_001.md` |
| Time-to-first-demo measurement | Minutes from git clone to first working WebSocket frame | Recorded in `evidence/onboarding/onboarding_001.md` | ⚠️ PARTIAL | **2.1 min** (warm cache, same machine) — not clean-VM | Measured but on warm cache; cold-cache estimate 2–5min | Repeat on clean VM | — |
| Steps-to-first-demo measurement | Count of non-trivial actions required | Recorded in `evidence/onboarding/onboarding_001.md` | ✅ YES | **6 non-trivial steps**, 1 friction (pytest not in deps) | Solid step count; qualitatively useful even without clean-VM | — | — |
| Setup failure/fix log | List of errors encountered during onboarding | Recorded in `evidence/onboarding/onboarding_001.md` | ✅ YES | Non-fatal ROS warning + missing pytest dep documented | Friction identified and documented | — | — |
| CI test proof | CI passing badge or log showing automated tests green | `.github/workflows/ci.yml` + green run | ✅ YES | `ci.yml` exists; runs `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q` on ubuntu-latest on each push | Solid coverage. 193 tests. Docker CI is manual-trigger only (`workflow_dispatch`). | Add Docker CI to push/PR triggers for completeness | Automatic on push |
| Doctor/preflight output proof | Output of `vt doctor` or health check command | `evidence/experiments/doctor_proof_001.md` | ❌ NO | No `vt doctor` command exists; `tools/mp.sh` has `health-demo` but no preflight/doctor | Scripts do not currently have a doctor/preflight command | Either create a `vt doctor` subcommand or substitute with `docker-smoke-test.sh` output | `./tools/docker_smoke_test.sh` |
| Operator UI proof | Screenshots or step-by-step validated run | `evidence/experiments/operator_ui_smoke_001.md` | ✅ YES | `evidence/experiments/operator_ui_smoke_001.md` + manifest row `operator_ui_smoke_001` | 13 steps validated, 1797 frames, commit ac186ef, including calibration/alignment/config/run/export | — | `docs/operator_ui_runbook.md` |

---

## Case Study Evidence

| Claim | Required evidence | Expected artifact path | Found? | Actual artifact path(s) | Quality assessment | Missing action | Regenerate command |
|---|---|---|---|---|---|---|---|
| Complete case study document | Scenario description + config + results narrative | `docs/case-studies/case-study-1.md` | ✅ YES | `docs/case-studies/case-study-1.md` + `docs/eval/case_study_summary.md` | Exists. Documents movement study scenario. | — | — |
| Scenario config | YAML config used for the case study | `configs/fusion_health_300fps.yaml` | ✅ YES | `configs/fusion_health_300fps.yaml` in manifest rows | Referenced in all case study manifest rows | — | — |
| Zone definitions | Zone boundaries for the case study | `calib/zones_warehouse.yaml` or `calib/zones.yaml` | ✅ YES | `calib/zones_warehouse.yaml`, `calib/zones.yaml` | Zone left/right used in case study analytics | — | — |
| Recorded session JSONL or checksum | Session recording anchoring the analytics | Case study session JSONL | ⚠️ PARTIAL | `case_study_1_movement_session` manifest row has SHA256=a639b51…, 327 MB, **path at `~/metriplane-runs/` — not in git** | Checksum exists; file not in git due to size. Use `datasets/demo/session_001.jsonl` for replay tests. | Consider adding representative 30s slice to `datasets/` | Replay session |
| Analytics CSV | Zone events, dwell times, transitions | `evidence/experiments/case_study_1_movement_zone_*.csv` | ✅ YES | 4 CSVs: events, dwell, dwell_by_zone, transitions + manifest rows | 120 zone events, 880 obj-s dwell, 77 transitions. Solid. | — | `tools/zones_report_jsonl.py <session>` |
| Summary table | Summary of case study numeric results | `docs/eval/case_study_summary.md` | ✅ YES | `docs/eval/case_study_summary.md` | Present | — | — |
| Screenshot / video link | Visual proof of running system | Not present in evidence/ | ❌ NO | Not referenced in any manifest row or evidence file | Strengthens evaluation; not required for numeric claims | Take screenshot of live overlay or WebSocket viewer during a session | `tools/preview_world_overlay_multi.py` |

---

## Reproducibility Evidence

| Claim | Required evidence | Expected artifact path | Found? | Actual artifact path(s) | Quality assessment | Missing action | Regenerate command |
|---|---|---|---|---|---|---|---|
| Git commit hash for each result | All manifest rows include git_commit | `evidence/manifest.csv` | ✅ YES | Manifest col `git_commit` present on all rows. `latency_summary.csv` also embeds commit in data rows. | Strong. Each row traceable to a specific commit. | — | — |
| Config snapshot for each run | Config file referenced in manifest | `evidence/manifest.csv` col `config_file` | ✅ YES | All manifest rows have `config_file` filled. Config files are in git at `configs/`. | Solid. Local configs (gitignored) are noted in manifest notes. | — | — |
| Hardware/environment spec | Platform info with CUDA version, GPU model | `evidence/experiments/run_meta.json` + manifest notes | ✅ YES | GPU noted as "RTX 5070 Ti" in manifest notes. `run_meta.json` includes `git_commit`. | Acceptable. Could be more formal (add CPU, OS, Python version). | Add `hw_spec.md` to evidence/ with full hardware profile | `uname -a; nvidia-smi; python --version` |
| Dataset / session checksum | SHA256 of session JSONL used in each benchmar | SHA256 in manifest col `artifact_sha256` | ✅ YES | Most manifest rows include SHA256. Large sessions have checksum but not file in git. | Good — as long as the original files are archived separately. | Archive large sessions on stable storage (NAS/cloud). | — |
| Evidence manifest entries | Manifest row for every claimed result | `evidence/manifest.csv` | ⚠️ PARTIAL | 36 rows present. mapping_error_001, gpu_benchmark_001, fusion_jitter_001, onboarding_001 all now have manifest rows. **1 artifact still without manifest row**: `health_degrade_cam1_meta` | Minor gap — add a manifest row for health_degrade demo | Manual CSV edit | Manual CSV edit |
| Release tag or RC tag | Version tag pointing to evaluation submission state | git tags | ✅ YES | initial-public-release @ `4a899bb` (evidence closeout); `v1.0.0` and `v1.0.0-rc1` also present | Strong anchoring. | — | — |

---

## Integration Evidence

| Claim | Required evidence | Expected artifact path | Found? | Actual artifact path(s) | Quality assessment | Missing action | Regenerate command |
|---|---|---|---|---|---|---|---|
| WebSocket integration proof | WS message received + client code | `tools/ws_smoke_client.py` + docker quickstart | ✅ YES | `tools/ws_smoke_client.py` exists. Docker quickstart doc shows WS proof. CI workflow includes WS check. | Solid at implementation level; no executed artifact in evidence/. | Add `docker_demo_proof` to evidence (see productization section) | `python tools/ws_smoke_client.py` |
| Omniverse live integration evidence | Screen recording or log of Omniverse extension loading and receiving frames | Not present | ❌ NO | `tools/omniverse/` scripts exist. Extension in `metriplane-omniverse-ext/`. No execution log. | `docs/INTEGRATIONS.md` correctly marks this as external/experimental. | Evaluation should not claim live Omniverse integration. Narrow claim to WebSocket surface. | N/A scope |
| ROS 2 live integration evidence | ROS 2 topic published + `ros2 topic echo` output | Not present | ❌ NO | `docs/INTEGRATIONS.md` marks ROS 2 as "Community Integration" — no bridge node provided | Correctly scoped as external. No product claim needs this. | Evaluation should state "ROS 2 integration is user-implemented via WebSocket consumer" | N/A scope |
| Integration architecture claim | WebSocket as the integration surface boundary | `docs/INTEGRATIONS.md`, `docs/schema.md`, `metriplane/streaming/` | ✅ YES | `ws_server.py` + `ws_thread.py` + `FrameStateModel` + integration doc | Architecture well documented. WebSocket is the verified integration surface. | — | — |

---

## Documentation Consistency

| Check | Expected | Actual | Status | Action |
|---|---|---|---|---|
| `docs/schema.md` vs `metriplane/schema.py` — field list | Identical | Identical (`run_id`, `config_hash`, `git_commit`, `ts_sim_ns`, `fused`, `raw_per_camera`, `objects`) | ✅ CONSISTENT | — |
| `docs/frames.md` — completeness | Non-empty, covers coordinate systems | 205 lines, covers world coords, camera coords, fusion merge | ✅ | — |
| `docs/evaluation/research_plan.md` — DeepStream/TensorRT | Should NOT claim DeepStream/TensorRT | Not mentioned; CuPy used exclusively | ✅ NO MISMATCH | — |
| `docs/evaluation/research_plan.md` — GPU claim | Should claim CuPy fusion compute | Correctly states "GPU-accelerated fusion compute (CuPy on CUDA)" | ✅ | — |
| Release docs — V1 integration completeness | Should not over-claim Omniverse/ROS 2 | `docs/INTEGRATIONS.md`: Omniverse and ROS2 marked as external/experimental | ✅ HONEST | — |
| Omniverse latency claim | Should not claim live measured latency | No live Omniverse measurement exists | ✅ OK | Not claimed in public release |
| Manifest completeness | Every executed result has a row | 3 artifacts orphaned from manifest | ⚠️ | Add fusion_jitter, health_degrade, mapping_error rows |
| Large session files | In-repo or checksummed | Checksummed in manifest, files on local disk only | ⚠️ | Archive on stable storage; document path |

---

## Quick Reference — Gap Priority

> Last updated: 2026-04-29 second docs consistency pass. Stale fixed gaps removed (onboarding not executed, mapping_error not in evidence, GPU benchmark absolute path). Current real remaining gaps only.

| # | Gap | Severity | RQ | Action |
|---|---|---|---|---|
| 1 | `onboarding_001` is same-machine warm-cache only — not clean-VM | MEDIUM | RQ1 | Repeat on fresh Ubuntu VM for quantitative clean-machine claim |
| 2 | Docker quickstart — no executed proof artifact | LOW | RQ1 | Run `docker_demo_up.sh`, save output to `evidence/experiments/docker_demo_proof_001.md` |
| 3 | No screenshot/video of live system | NICE-TO-HAVE | RQ1 | Take screenshot during next live session |
| 4 | M9.3 health degradation — partial; second USB port not capture-capable | MEDIUM (hardware-blocked) | RQ3 | Document as "implemented, hardware-constrained" in the evaluation |
| 5 | Omniverse/ROS 2 — no live measured integration | DOCUMENTED | RQ2 | Claims WebSocket as measured surface; Omniverse/ROS2 are external/experimental adapters |

---

*See  for narrative analysis and recommended evaluation text.*
