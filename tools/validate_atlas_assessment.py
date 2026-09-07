#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Retain installed-package before/after evidence for MET-162.

The controller uses only the standard library. Each isolated worker imports the
selected, non-editable installed package from an unrelated working directory.
Generated inputs are synthetic; no private recordings or historical evidence
are required or modified. Existing output directories are never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import time
from typing import Any
import zipfile


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _without_run_id(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_run_id(item) for key, item in value.items() if key != "run_id"}
    if isinstance(value, list):
        return [_without_run_id(item) for item in value]
    return value


def _installed_identity() -> dict[str, Any]:
    import metriplane

    distribution = importlib.metadata.distribution("metriplane")
    roots = {Path(sysconfig.get_path(name)).resolve() for name in ("purelib", "platlib")}
    origin = Path(metriplane.__file__).resolve()
    if not any(origin.is_relative_to(root) for root in roots):
        raise ValueError(f"package must be installed in this interpreter's site-packages: {origin}")
    direct_url = distribution.read_text("direct_url.json")
    if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable"):
        raise ValueError("editable installations are not an installed-artifact proof")
    for name, module in tuple(sys.modules.items()):
        if name != "metriplane" and not name.startswith("metriplane."):
            continue
        filename = getattr(module, "__file__", None)
        if filename and not any(Path(filename).resolve().is_relative_to(root) for root in roots):
            raise ValueError(f"imported module escaped installed package roots: {name}")
    sources = {
        str(relative): _sha256(Path(distribution.locate_file(relative)))
        for relative in sorted(distribution.files or [], key=str)
        if str(relative).startswith("metriplane/") and str(relative).endswith(".py")
    }
    record = distribution.read_text("RECORD")
    return {
        "version": distribution.version,
        "executable": sys.executable,
        "python": sys.version,
        "platform": platform.platform(),
        "package_origin": str(origin),
        "site_packages_roots": sorted(str(root) for root in roots),
        "installed_source_sha256": sources,
        "record_sha256": hashlib.sha256(record.encode()).hexdigest() if record else None,
        "direct_url": json.loads(direct_url) if direct_url else None,
        "packages": {
            item.metadata["Name"]: item.version for item in importlib.metadata.distributions()
        },
        "isolated_interpreter": bool(sys.flags.isolated),
        "pythonpath_present": "PYTHONPATH" in os.environ,
    }


def _worker(request: dict[str, Any]) -> Any:
    from metriplane.atlas.bundles import verify_bundle
    from metriplane.atlas.improvement import compare_runs
    from metriplane.atlas.regression import create_regression_from_bundle, run_regression
    from metriplane.atlas.runtime import run_atlas

    identity = _installed_identity()
    action = request["action"]
    if action == "identity":
        return identity
    if action == "run":
        fixture = Path(request["fixture"])
        output = Path(request["output"])
        manifest = run_atlas(
            fixture / "session.jsonl",
            fixture / "domain-pack",
            output,
            run_id="met-162-" + request["case_id"],
        )
        assessment_path = output / "requirement_assessment.json"
        assessment = _read(assessment_path) if assessment_path.exists() else None
        return _without_run_id(
            {
                "incident_count": manifest.incident_count,
                "event_count": manifest.event_count,
                "events": _jsonl(output / "physical_event_log.jsonl"),
                "deviations": _jsonl(output / "deviations.jsonl"),
                "incidents": _jsonl(output / "incidents.jsonl"),
                "metrics": _read(output / "metrics.json"),
                "process_trace": _read(output / "process_trace.json"),
                "process_assessment": assessment.get("process_assessment") if assessment else None,
                "observed_wait": assessment.get("observed_wait") if assessment else None,
                "coverage": assessment.get("coverage") if assessment else None,
                "assessment_schema": assessment.get("schema_version") if assessment else None,
            }
        )
    if action == "compare":
        return compare_runs(request["before"], request["after"], request["output"])
    if action == "bundle":
        bundle = Path(request["bundle"])
        output = Path(request["output"])
        output.mkdir()
        verified = verify_bundle(bundle)
        spec = output / "regression.yaml"
        create_regression_from_bundle(bundle, spec)
        regression = run_regression(spec)
        tampered = output / "tampered.zip"
        modified = False
        with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(tampered, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename.endswith("cell_truth_report.md"):
                    data += b"\nIntentional MET-162 integrity probe.\n"
                    modified = True
                target.writestr(info, data)
        if not modified:
            raise ValueError("bundle has no incident report to tamper")
        return {
            "verified": verified,
            "regression": regression,
            "tampered_verification": verify_bundle(tampered),
            "original_sha256": _sha256(bundle),
            "tampered_sha256": _sha256(tampered),
        }
    raise ValueError(f"unknown worker action: {action}")


def _fixtures(root: Path) -> list[dict[str, Any]]:
    root.mkdir()
    cases = [
        {"id": "slow", "arrival": 1.5, "outcome": "violated", "incidents": 1, "wait": 1.5},
        {"id": "fast", "arrival": 0.5, "outcome": "satisfied", "incidents": 0, "wait": 0.5},
        {
            "id": "relaxed-rule",
            "arrival": 1.5,
            "threshold": 2.0,
            "outcome": "satisfied",
            "incidents": 0,
            "wait": 1.5,
        },
        {
            "id": "pending",
            "arrival": None,
            "times": [0.0, 0.5],
            "outcome": "unresolved",
            "incidents": 0,
            "wait": None,
            "wait_lower_bound": 0.5,
        },
        {
            "id": "not-exercised",
            "arrival": None,
            "outcome": "not_exercised",
            "incidents": 0,
            "wait": None,
        },
        {
            "id": "late-arrival",
            "arrival": 1.25,
            "times": [0.0, 0.75, 1.25],
            "outcome": "satisfied",
            "incidents": 0,
            "wait": 1.25,
        },
        {"id": "equality", "arrival": 1.0, "outcome": "satisfied", "incidents": 0, "wait": 1.0},
        {
            "id": "pending-violated",
            "arrival": None,
            "outcome": "violated",
            "incidents": 1,
            "wait": None,
            "wait_lower_bound": 2.0,
        },
        {
            "id": "missing-observation",
            "arrival": 1.5,
            "outcome": "violated",
            "incidents": 1,
            "wait": 1.5,
        },
        {
            "id": "translated-clock",
            "arrival": 1.5,
            "time_offset": 4.7,
            "outcome": "violated",
            "incidents": 1,
            "wait": 1.5,
        },
        {
            "id": "cropped-after-arrival",
            "arrival": 0.0,
            "times": [0.0, 0.5],
            "outcome": "satisfied",
            "incidents": 0,
            "wait": 0.0,
        },
    ]
    for case in cases:
        fixture = root / str(case["id"])
        pack = fixture / "domain-pack"
        pack.mkdir(parents=True)
        _write(
            pack / "assets.yaml",
            {
                "schema_version": "metriplane.atlas.asset_registry.v1",
                "assets": [
                    {"object_id": key, "asset_id": key, "asset_type": kind, "label": key}
                    for key, kind in (("material", "workpiece"), ("tool", "tool"))
                ],
            },
        )
        _write(
            pack / "workspace.yaml",
            {
                "schema_version": "metriplane.atlas.workspace.v1",
                "cell_id": "met-162-synthetic-cell",
                "units": "meters",
                "zones": [
                    {
                        "zone_id": name,
                        "zone_type": "work" if name == "work" else "staging",
                        "polygon": polygon,
                    }
                    for name, polygon in (
                        ("work", [[0, 0], [1, 0], [1, 1], [0, 1]]),
                        ("outside", [[2, 0], [3, 0], [3, 1], [2, 1]]),
                    )
                ],
            },
        )
        _write(
            pack / "process.yaml",
            {
                "schema_version": "metriplane.atlas.process_model.v1",
                "process_id": "met-162-tool-arrival",
                "steps": [
                    {
                        "step_id": "tool-ready",
                        "label": "Tool ready for the observed material",
                        "expected_asset_types": ["workpiece"],
                        "required_assets": ["tool"],
                        "required_zone": "work",
                        "max_wait_s": case.get("threshold", 1.0),
                    }
                ],
            },
        )
        rows = []
        for frame_id, ts in enumerate(case.get("times", [0.0, 0.5, 1.0, 1.5, 2.0])):
            present = case["arrival"] is not None and ts >= case["arrival"]
            objects = []
            for key, inside in (("material", case["id"] != "not-exercised"), ("tool", present)):
                if case["id"] == "missing-observation" and key == "tool" and frame_id == 1:
                    continue
                objects.append(
                    {
                        "id": key,
                        "zone": "work" if inside else "outside",
                        "pos_world": [0.5 if inside else 2.5, 0.5, 0.0],
                        "confidence": 1.0,
                    }
                )
            rows.append(
                {
                    "schema_version": "1.0",
                    "run_id": "met-162-synthetic-recording",
                    "source_backend": "synthetic_complete_snapshot",
                    "ts": ts + float(case.get("time_offset", 0.0)),
                    "frame_id": frame_id,
                    "objects": objects,
                    "events": [],
                }
            )
        (fixture / "session.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )
        case["input_sha256"] = {
            path.relative_to(fixture).as_posix(): _sha256(path)
            for path in sorted(fixture.rglob("*"))
            if path.is_file()
        }
    if _sha256(root / "slow/session.jsonl") != _sha256(root / "relaxed-rule/session.jsonl"):
        raise ValueError("rule-relaxation pair must contain byte-identical observations")
    return cases


def _execute(python: Path, request: dict[str, Any], folder: Path) -> tuple[dict[str, Any], Any]:
    folder.mkdir(parents=True)
    request_path = folder / "request.json"
    _write(request_path, request)
    command = [str(python), "-I", str(Path(__file__).resolve()), "--worker", str(request_path)]
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment["METRIPLANE_TEST_PROFILE"] = "installed"
    started = time.perf_counter()
    timed_out = False
    try:
        result = subprocess.run(
            command, cwd=folder, env=environment, capture_output=True, text=True, timeout=180
        )
        stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
        exit_code = 124
    record = {
        "command": command,
        "cwd": str(folder),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - started,
        "PYTHONPATH": "absent",
        "METRIPLANE_TEST_PROFILE": "installed",
    }
    _write(folder / "invocation.json", record)
    (folder / "stdout.txt").write_text(stdout, encoding="utf-8")
    (folder / "stderr.txt").write_text(stderr, encoding="utf-8")
    if exit_code:
        raise RuntimeError(f"worker failed; retained diagnostics: {folder / 'stderr.txt'}")
    value = json.loads(stdout)
    _write(folder / "result.json", value)
    return record, value


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-python", required=True, type=Path)
    parser.add_argument("--after-python", required=True, type=Path)
    parser.add_argument("--before-artifact", type=Path, help="optional retained wheel or sdist")
    parser.add_argument("--after-artifact", type=Path, help="optional retained wheel or sdist")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--trials", type=int, default=2)
    args = parser.parse_args()
    if args.trials < 2:
        parser.error("at least two trials are required for semantic repeatability")
    output = args.out.resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("--out must be outside the checkout for installed-package isolation")
    output.mkdir(parents=True, exist_ok=False)
    environments = {}
    checks = []
    interpreters = {
        "before": args.before_python.absolute(),
        "after": args.after_python.absolute(),
    }
    for label, python in interpreters.items():
        _, identity = _execute(python, {"action": "identity"}, output / "environments" / label)
        artifact = getattr(args, label + "_artifact")
        if artifact:
            identity["retained_artifact"] = {
                "path": str(artifact.resolve()),
                "sha256": _sha256(artifact),
            }
            if artifact.suffix == ".whl":
                with zipfile.ZipFile(artifact) as archive:
                    wheel_sources = {
                        name: hashlib.sha256(archive.read(name)).hexdigest()
                        for name in archive.namelist()
                        if name.startswith("metriplane/") and name.endswith(".py")
                    }
                matches = wheel_sources == identity["installed_source_sha256"]
                identity["retained_artifact"]["matches_installed_python_sources"] = matches
                if not matches:
                    raise ValueError(f"{label} artifact differs from installed Python sources")
        environments[label] = identity
    if environments["before"]["version"] != "0.4.0.post2":
        raise ValueError("before interpreter must contain metriplane==0.4.0.post2")
    checks.append(
        {
            "check": "distinct_installed_source_identities",
            "pass": environments["before"]["installed_source_sha256"]
            != environments["after"]["installed_source_sha256"],
        }
    )
    cases = _fixtures(output / "inputs")
    _write(
        output / "protocol.json",
        {
            "schema_version": "metriplane.met162.validation_protocol.v1",
            "runner_sha256": _sha256(Path(__file__)),
            "trials": args.trials,
            "cases": cases,
            "environments": environments,
            "scope": "synthetic recorded-state characterization; no human or adoption study",
            "policy": "legacy_sampled_missing_v1; no continuous-time deadline guarantee",
        },
    )
    rows = []
    semantics = {}
    for trial in range(1, args.trials + 1):
        for label, python in interpreters.items():
            for case in cases:
                case_id = str(case["id"])
                for relative, expected_hash in case["input_sha256"].items():
                    if _sha256(output / "inputs" / case_id / relative) != expected_hash:
                        raise ValueError(
                            f"protocol input changed before execution: {case_id}/{relative}"
                        )
                folder = output / f"trial-{trial}" / label / case_id
                record, result = _execute(
                    python,
                    {
                        "action": "run",
                        "case_id": case_id,
                        "fixture": str(output / "inputs" / case_id),
                        "output": str(folder / "artifacts"),
                    },
                    folder,
                )
                assessment = result.get("process_assessment") or {}
                row = {
                    "trial": trial,
                    "package": label,
                    "case_id": case_id,
                    "exit_code": record["exit_code"],
                    "incident_count": result["incident_count"],
                    "outcome": assessment.get("outcome"),
                    "expected_after_outcome": case["outcome"],
                    "legacy_incidents_preserved": result["incident_count"] == case["incidents"],
                }
                rows.append(row)
                semantics[(trial, label, case_id)] = result
                checks.append(
                    {
                        "check": f"trial-{trial}/{label}/{case_id}/legacy-incidents",
                        "pass": row["legacy_incidents_preserved"],
                    }
                )
                if label == "after":
                    checks.append(
                        {
                            "check": f"trial-{trial}/after/{case_id}/explicit-outcome",
                            "pass": row["outcome"] == case["outcome"],
                        }
                    )
                    steps = assessment.get("steps", [])
                    step = steps[0] if len(steps) == 1 else {}
                    observed_wait = result.get("observed_wait") or {}
                    expected_total = (
                        None
                        if case_id in {"missing-observation", "cropped-after-arrival"}
                        else case["wait"]
                    )
                    checks.append(
                        {
                            "check": f"trial-{trial}/after/{case_id}/observed-wait",
                            "pass": bool(step)
                            and step.get("observed_wait_s") == case["wait"]
                            and step.get("observed_wait_lower_bound_s")
                            == case.get("wait_lower_bound")
                            and observed_wait.get("total_s") == expected_total,
                        }
                    )
                print(f"trial={trial} package={label} case={case_id} complete", flush=True)
    for case in cases:
        for label in interpreters:
            checks.append(
                {
                    "check": f"{label}/{case['id']}/semantic-repeatability",
                    "pass": all(
                        semantics[(1, label, case["id"])] == semantics[(trial, label, case["id"])]
                        for trial in range(2, args.trials + 1)
                    ),
                }
            )
        for trial in range(1, args.trials + 1):
            before = semantics[(trial, "before", case["id"])]
            after = semantics[(trial, "after", case["id"])]
            checks.append(
                {
                    "check": f"trial-{trial}/{case['id']}/legacy-events-and-metrics",
                    "pass": all(
                        before[key] == after[key]
                        for key in ("events", "deviations", "incidents", "metrics", "process_trace")
                    ),
                }
            )
    for trial in range(1, args.trials + 1):
        late = semantics[(trial, "after", "late-arrival")]["process_assessment"]
        checks.append(
            {
                "check": f"trial-{trial}/late-arrival/policy-boundary-disclosed",
                "pass": "arrival_observed_after_threshold_without_sampled_violation"
                in json.dumps(late),
            }
        )
    comparisons = []
    pairs = [
        ("rule-relaxation", "slow", "relaxed-rule", "incompatible", None),
        ("faster-arrival", "slow", "fast", "eligible", "improved"),
        ("unchanged", "slow", "slow", "eligible", "unchanged"),
        ("pending", "slow", "pending", "insufficient_evidence", None),
        ("not-exercised", "not-exercised", "not-exercised", "insufficient_evidence", None),
        ("missing-observation", "slow", "missing-observation", "insufficient_evidence", None),
        ("legacy-artifacts", "slow", "slow", "insufficient_evidence", None),
        ("translated-clock", "slow", "translated-clock", "incompatible", None),
        (
            "cropped-after-arrival",
            "slow",
            "cropped-after-arrival",
            ("incompatible", "insufficient_evidence"),
            None,
        ),
    ]
    for trial in range(1, args.trials + 1):
        for label, python in interpreters.items():
            for pair_id, before_case, after_case, expected_status, expected_direction in pairs:
                if pair_id == "legacy-artifacts" and label == "before":
                    continue
                before_label = "before" if pair_id == "legacy-artifacts" else label
                base = output / f"trial-{trial}"
                folder = base / "comparisons" / label / pair_id
                _, result = _execute(
                    python,
                    {
                        "action": "compare",
                        "before": str(base / before_label / before_case / "artifacts"),
                        "after": str(base / label / after_case / "artifacts"),
                        "output": str(folder / "comparison.json"),
                    },
                    folder,
                )
                comparisons.append(
                    {"trial": trial, "package": label, "pair": pair_id, "result": result}
                )
                if label == "after":
                    eligibility = result.get("eligibility", {})
                    expected_statuses = (
                        expected_status
                        if isinstance(expected_status, tuple)
                        else (expected_status,)
                    )
                    checks.append(
                        {
                            "check": f"trial-{trial}/{pair_id}/comparison-eligibility",
                            "pass": eligibility.get("status") in expected_statuses,
                            "expected": expected_status,
                            "actual": eligibility.get("status"),
                        }
                    )
                    if expected_direction:
                        actual = result.get("comparison_status")
                        checks.append(
                            {
                                "check": f"trial-{trial}/{pair_id}/comparison-direction",
                                "pass": actual == expected_direction,
                                "expected": expected_direction,
                                "actual": actual,
                            }
                        )
                    else:
                        checks.append(
                            {
                                "check": f"trial-{trial}/{pair_id}/no-improvement-conclusion",
                                "pass": result.get("comparison_status") == "not_comparable"
                                and eligibility.get("eligible") is False
                                and result.get("observed_wait", {}).get(
                                    "used_for_improvement_conclusion"
                                )
                                is False,
                            }
                        )
                elif pair_id == "rule-relaxation":
                    checks.append(
                        {
                            "check": f"trial-{trial}/before/characterize-false-improvement",
                            "pass": result["incident_delta"] < 0
                            and "reduced" in result["conclusion"],
                        }
                    )
    bundle_probes = []
    for trial in range(1, args.trials + 1):
        for reader_label, producer_label in (
            ("before", "before"),
            ("after", "after"),
            ("before", "after"),
            ("after", "before"),
        ):
            folder = (
                output / f"trial-{trial}" / "bundle-probes" / f"{reader_label}-{producer_label}"
            )
            bundle = (
                output
                / f"trial-{trial}"
                / producer_label
                / "slow/artifacts/evidence_bundles/INC-0001.zip"
            )
            _, probe = _execute(
                interpreters[reader_label],
                {"action": "bundle", "bundle": str(bundle), "output": str(folder / "artifacts")},
                folder,
            )
            bundle_probes.append(
                {"trial": trial, "reader": reader_label, "producer": producer_label, **probe}
            )
            checks.append(
                {
                    "check": f"trial-{trial}/{reader_label}-reads-{producer_label}/bundle-replay-tamper",
                    "pass": probe["verified"]["pass"] is True
                    and probe["regression"]["pass"] is True
                    and probe["tampered_verification"]["pass"] is False,
                }
            )
    _write(output / "results.json", rows)
    _write(output / "comparisons.json", comparisons)
    _write(output / "bundle-probes.json", bundle_probes)
    _write(output / "checks.json", checks)
    summary = {
        "pass": all(check["pass"] for check in checks),
        "run_invocations": len(rows),
        "comparison_invocations": len(comparisons),
        "bundle_probe_invocations": len(bundle_probes),
        "checks_passed": sum(check["pass"] for check in checks),
        "checks_total": len(checks),
        "failed_checks": [check for check in checks if not check["pass"]],
        "claim_boundary": "same-environment synthetic replay; no physical or human outcome measured",
    }
    _write(output / "summary.json", summary)
    (output / "CHECKSUMS.sha256").write_text(
        "".join(
            f"{_sha256(path)}  {path.relative_to(output).as_posix()}\n"
            for path in sorted(output.rglob("*"))
            if path.is_file() and path.name != "CHECKSUMS.sha256"
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker_result = _worker(_read(Path(sys.argv[2])))
        _installed_identity()  # Also inspect modules lazily imported by the action.
        print(json.dumps(worker_result, sort_keys=True))
    else:
        raise SystemExit(_main())
