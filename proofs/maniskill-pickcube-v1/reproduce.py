# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Portable public-CLI reproduction for the ManiSkill PickCube proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

EXPECTED_COUNTS = {
    "incident": {"frame_count": 75, "event_count": 4, "deviation_count": 1, "incident_count": 1},
    "control": {"frame_count": 75, "event_count": 3, "deviation_count": 0, "incident_count": 0},
}
FIXTURE_PATHS = {
    "incident": Path("examples/external_sources/maniskill_pickcube/incident"),
    "control": Path("examples/external_sources/maniskill_pickcube/control"),
}
RUN_IDS = {
    "incident": "maniskill_pickcube_incident_proof",
    "control": "maniskill_pickcube_control_proof",
}
FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
ABSOLUTE_PATH = re.compile(
    rb"(?:(?<![A-Za-z0-9_+.-])[A-Za-z]:[\\/][^\x00\r\n\"']+|"
    rb"/(?:home|Users|workspace|tmp|private/tmp|var/folders)/[^\x00\r\n\"']+)"
)
SOURCE_ASSUMPTION_TERMS = (
    b"camera-calibrated",
    b"camera tracked",
    b"fiducial-tagged",
    b"isaac sim source",
)


class ReproductionError(RuntimeError):
    """Raised when a public reproduction observation differs from the proof."""


def _json_load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReproductionError(f"expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_json(command: list[str], *, env: dict[str, str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ReproductionError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReproductionError(
            f"command did not emit one JSON value: {' '.join(command)}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ReproductionError(f"command emitted non-object JSON: {' '.join(command)}")
    return value


def _canonical_validation(value: dict[str, Any], variant: str) -> dict[str, Any]:
    canonical = json.loads(json.dumps(value))
    canonical["fixture_root"] = FIXTURE_PATHS[variant].as_posix()
    return canonical


def _canonical_run(value: dict[str, Any], variant: str) -> dict[str, Any]:
    canonical = json.loads(json.dumps(value))
    canonical["output_directory"] = f"{variant}-run"
    canonical["report_path"] = f"{variant}-run/cell_truth_report.html"
    validation = canonical.get("validation")
    if isinstance(validation, dict):
        canonical["validation"] = _canonical_validation(validation, variant)
    provenance = canonical.get("provenance")
    if isinstance(provenance, dict):
        provenance["path"] = f"{variant}-run/external_source_provenance.json"
    for item in canonical.get("evidence_bundles", []):
        if isinstance(item, dict):
            item["path"] = "incident-run/evidence_bundles/INC-0001.zip"
    for item in canonical.get("generated_regressions", []):
        if isinstance(item, dict):
            item["path"] = "incident-run/regression_tests/INC-0001.yaml"
    return canonical


def _assert_counts(summary: dict[str, Any], variant: str) -> None:
    if summary.get("pass") is not True:
        raise ReproductionError(f"{variant} run did not pass: {summary.get('errors')}")
    for name, expected in EXPECTED_COUNTS[variant].items():
        observed = summary.get(name)
        if observed != expected:
            raise ReproductionError(
                f"{variant} {name} mismatch: expected {expected}, observed {observed}"
            )


def _iter_durable_bytes(root: Path) -> list[tuple[str, bytes]]:
    values: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for member in sorted(archive.infolist(), key=lambda item: item.filename):
                    if not member.is_dir():
                        values.append((f"{relative}!{member.filename}", archive.read(member)))
        else:
            values.append((relative, path.read_bytes()))
    return values


def _scan_outputs(root: Path, sentinels: list[bytes]) -> None:
    failures: list[str] = []
    for name, data in _iter_durable_bytes(root):
        lowered = data.lower()
        for sentinel in sentinels:
            if sentinel and sentinel.lower() in lowered:
                failures.append(f"machine-local sentinel in {name}")
        if ABSOLUTE_PATH.search(data):
            failures.append(f"machine-local absolute path in {name}")
        for term in SOURCE_ASSUMPTION_TERMS:
            if term in lowered:
                failures.append(f"source-specific assumption {term!r} in {name}")
    if failures:
        raise ReproductionError("durable artifact scan failed:\n- " + "\n- ".join(failures))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _semantic_hash(run: Path) -> str:
    paths = (
        "state_segment.jsonl",
        "physical_event_log.jsonl",
        "deviations.jsonl",
        "incidents.jsonl",
    )
    digest = hashlib.sha256()
    for name in paths:
        path = run / name
        data = path.read_bytes()
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    regression = run / "regression_tests" / "INC-0001.yaml"
    if regression.is_file():
        data = regression.read_bytes()
        digest.update(b"regression_tests/INC-0001.yaml\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _verify_proof_inventory(proof_dir: Path, record: dict[str, Any]) -> None:
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, list):
        raise ReproductionError("proof-record artifacts must be an array")
    for item in artifacts:
        if not isinstance(item, dict):
            raise ReproductionError("proof-record artifact entry must be an object")
        relative = item.get("path")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ReproductionError("proof-record artifact path/hash is invalid")
        pure = Path(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ReproductionError(f"unsafe proof-record artifact path: {relative}")
        path = proof_dir / pure
        if not path.is_file() or _sha256(path) != expected:
            raise ReproductionError(f"proof-record artifact hash mismatch: {relative}")

    checksum_path = proof_dir / "SHA256SUMS"
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, marker_path = line.split(maxsplit=1)
        relative = marker_path.lstrip(" *")
        pure = Path(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ReproductionError(f"unsafe SHA256SUMS path: {relative}")
        path = proof_dir / pure
        if not path.is_file() or _sha256(path) != expected:
            raise ReproductionError(f"SHA256SUMS mismatch: {relative}")


def _verify_moved_output(
    out: Path,
    *,
    metriplane: str,
    env: dict[str, str],
    repo_root: Path,
    sentinels: list[bytes],
) -> tuple[dict[str, Any], dict[str, Any]]:
    moved = out.with_name(f"{out.name}.moved-portability-check")
    if moved.exists() or moved.is_symlink():
        raise ReproductionError(f"move-test destination already exists: {moved}")
    out.rename(moved)
    try:
        required = [
            moved / variant / name
            for variant in ("incident-run", "control-run")
            for name in (
                "cell_truth_report.html",
                "atlas_dashboard.html",
                "twinverify_replay.usda",
            )
        ]
        missing = [path.relative_to(moved).as_posix() for path in required if not path.is_file()]
        if missing:
            raise ReproductionError(f"moved output is missing required render artifacts: {missing}")
        if any(path.stat().st_size == 0 for path in required):
            raise ReproductionError("moved report, dashboard, or USDA artifact is empty")

        bundle = moved / "incident-run" / "evidence_bundles" / "INC-0001.zip"
        regression = moved / "incident-run" / "regression_tests" / "INC-0001.yaml"
        bundle_result = _run_json(
            [metriplane, "atlas", "bundle", "verify", str(bundle)],
            env=env,
            cwd=repo_root,
        )
        regression_result = _run_json(
            [metriplane, "atlas", "test", str(regression), "--json"],
            env=env,
            cwd=repo_root,
        )
        if bundle_result.get("pass") is not True:
            raise ReproductionError("incident bundle failed after output-tree move")
        if regression_result.get("pass") is not True:
            raise ReproductionError("incident regression failed after output-tree move")
        if list((moved / "control-run" / "evidence_bundles").glob("*")):
            raise ReproductionError("control bundle appeared after output-tree move")
        if list((moved / "control-run" / "regression_tests").glob("*")):
            raise ReproductionError("control regression appeared after output-tree move")
        _scan_outputs(moved, [*sentinels, str(moved.resolve()).encode()])
        return bundle_result, regression_result
    finally:
        if moved.exists() and not out.exists():
            moved.rename(out)


def _expected_record(proof_dir: Path) -> dict[str, Any]:
    record = _json_load(proof_dir / "proof-record.json")
    if record.get("schema_version") != "org.metriplane.maniskill_pickcube_proof.v1":
        raise ReproductionError("unsupported or missing proof-record schema_version")
    return record


def reproduce(repo_root: Path, out: Path, commit: str, metriplane: str) -> dict[str, Any]:
    if FULL_COMMIT.fullmatch(commit) is None:
        raise ReproductionError("--metriplane-commit must be a full lowercase 40-hex commit")
    repo_root = repo_root.resolve()
    proof_dir = repo_root / "proofs" / "maniskill-pickcube-v1"
    record = _expected_record(proof_dir)
    identity = record.get("proof_identity", {})
    contract = record.get("contract", {})
    if identity.get("candidate_commit") != commit:
        raise ReproductionError("requested commit does not match proof-record candidate_commit")
    if contract.get("metriplane_git_commit") != commit:
        raise ReproductionError("requested commit does not match proof-record contract commit")
    _verify_proof_inventory(proof_dir, record)
    if out.exists() or out.is_symlink():
        raise ReproductionError(f"refusing non-fresh output path: {out}")
    out.mkdir(parents=True)

    env = dict(os.environ)
    env["METRIPLANE_GIT_COMMIT"] = commit
    observed: dict[str, Any] = {}
    for variant in ("incident", "control"):
        fixture = repo_root / FIXTURE_PATHS[variant]
        if not fixture.is_dir():
            raise ReproductionError(f"missing canonical fixture: {fixture}")
        validation = _run_json(
            [metriplane, "external", "validate", str(fixture), "--json"],
            env=env,
            cwd=repo_root,
        )
        if validation.get("pass") is not True:
            raise ReproductionError(f"{variant} validation failed: {validation.get('errors')}")
        run_root = out / f"{variant}-run"
        run = _run_json(
            [
                metriplane,
                "external",
                "run",
                str(fixture),
                "--out",
                str(run_root),
                "--run-id",
                RUN_IDS[variant],
                "--json",
            ],
            env=env,
            cwd=repo_root,
        )
        _assert_counts(run, variant)
        canonical_validation = _canonical_validation(validation, variant)
        canonical_run = _canonical_run(run, variant)
        published_validation = _json_load(proof_dir / "artifacts" / f"{variant}-validation.json")
        published_run = _json_load(proof_dir / "artifacts" / f"{variant}-run-summary.json")
        if canonical_validation != published_validation:
            raise ReproductionError(f"{variant} validation differs from the published result")
        if canonical_run != published_run:
            raise ReproductionError(f"{variant} run summary differs from the published result")
        observed[variant] = {"validation": canonical_validation, "run": canonical_run}

    incident_run = out / "incident-run"
    incident_bundles = sorted((incident_run / "evidence_bundles").glob("*.zip"))
    incident_regressions = sorted((incident_run / "regression_tests").glob("*.yaml"))
    if len(incident_bundles) != 1 or len(incident_regressions) != 1:
        raise ReproductionError("incident run must create exactly one bundle and one regression")
    bundle_result = _run_json(
        [metriplane, "atlas", "bundle", "verify", str(incident_bundles[0])],
        env=env,
        cwd=repo_root,
    )
    if bundle_result.get("pass") is not True:
        raise ReproductionError(f"incident bundle did not verify: {bundle_result.get('errors')}")
    regression_result = _run_json(
        [metriplane, "atlas", "test", str(incident_regressions[0]), "--json"],
        env=env,
        cwd=repo_root,
    )
    if regression_result.get("pass") is not True:
        raise ReproductionError(f"incident regression failed: {regression_result.get('errors')}")

    control_run = out / "control-run"
    control_bundles = list((control_run / "evidence_bundles").glob("*"))
    control_regressions = list((control_run / "regression_tests").glob("*"))
    if control_bundles or control_regressions:
        raise ReproductionError("control run fabricated an evidence bundle or regression")

    fixture_paths = [str((repo_root / path).resolve()).encode() for path in FIXTURE_PATHS.values()]
    sentinels = [
        str(repo_root).encode(),
        str(out.resolve()).encode(),
        str(Path.home()).encode(),
        *fixture_paths,
    ]
    _scan_outputs(out, sentinels)

    expected = record["results"]
    for variant in ("incident", "control"):
        expected_counts = expected[f"{variant}_run"]["counts"]
        for name, value in EXPECTED_COUNTS[variant].items():
            if expected_counts.get(name) != value:
                raise ReproductionError(
                    f"proof-record {variant} {name} does not match the frozen expectation"
                )
        observed_hash = _semantic_hash(out / f"{variant}-run")
        if observed_hash != expected[f"{variant}_run"].get("semantic_hash"):
            raise ReproductionError(
                f"{variant} semantic result differs from the published proof record"
            )

    _, moved_regression_result = _verify_moved_output(
        out,
        metriplane=metriplane,
        env=env,
        repo_root=repo_root,
        sentinels=sentinels,
    )

    result = {
        "schema_version": "org.metriplane.maniskill_pickcube_reproduction.v1",
        "pass": True,
        "level": "portable_fixture_evaluation",
        "proof_id": record["proof_identity"]["proof_id"],
        "metriplane_version": observed["incident"]["run"]["metriplane_version"],
        "metriplane_git_commit": commit,
        "environment": {
            "operating_system": platform.system(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
        },
        "incident": {
            "counts": EXPECTED_COUNTS["incident"],
            "bundle_verified": True,
            "regression_passed": True,
            "bundle_sha256": _sha256(incident_bundles[0]),
            "semantic_hash": _semantic_hash(incident_run),
        },
        "control": {
            "counts": EXPECTED_COUNTS["control"],
            "bundle_count": 0,
            "regression_count": 0,
            "semantic_hash": _semantic_hash(control_run),
        },
        "path_portability_scan": "pass",
        "source_neutral_wording_scan": "pass",
        "moved_output_reverification": {
            "reports_dashboards_and_usda_present": True,
            "incident_bundle_verified": True,
            "incident_regression_passed": moved_regression_result.get("pass") is True,
            "control_artifacts_absent": True,
        },
        "maintainer_assistance_required": False,
    }
    _write_json(out / "reproduction-result.json", result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="exact proof-tag checkout root (defaults to this script's checkout)",
    )
    parser.add_argument("--out", type=Path, required=True, help="new reproduction output root")
    parser.add_argument(
        "--metriplane-commit",
        default=os.environ.get("METRIPLANE_GIT_COMMIT"),
        help="full exact commit used to build the installed wheel",
    )
    parser.add_argument(
        "--metriplane-command",
        default=shutil.which("metriplane") or "metriplane",
        help="public metriplane executable (default: PATH lookup)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    out_preexisted = args.out.exists() or args.out.is_symlink()
    error: Exception | None = None
    if not args.metriplane_commit:
        error = ReproductionError("--metriplane-commit or METRIPLANE_GIT_COMMIT is required")
    else:
        try:
            result = reproduce(
                args.repo_root,
                args.out,
                str(args.metriplane_commit),
                str(args.metriplane_command),
            )
        except (OSError, ReproductionError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
            error = exc
    if error is not None:
        message = str(error)
        replacements = {
            str(args.repo_root.resolve()): "<repo-root>",
            str(args.out.resolve()): "<out>",
            str(Path.home()): "<home>",
        }
        command = str(args.metriplane_command)
        if "/" in command or "\\" in command:
            replacements[command] = "<metriplane-command>"
        for value in sorted(replacements, key=len, reverse=True):
            message = message.replace(value, replacements[value])
        failure = {
            "schema_version": "org.metriplane.maniskill_pickcube_reproduction.v1",
            "pass": False,
            "level": "portable_fixture_evaluation",
            "proof_id": "maniskill-pickcube-v1",
            "metriplane_git_commit": args.metriplane_commit,
            "environment": {
                "operating_system": platform.system(),
                "architecture": platform.machine(),
                "python_version": platform.python_version(),
            },
            "errors": [message],
            "maintainer_assistance_required": False,
        }
        if not out_preexisted:
            try:
                args.out.mkdir(parents=True, exist_ok=True)
                _write_json(args.out / "reproduction-result.json", failure)
            except OSError as write_error:
                print(f"reproduce: could not write failure result: {write_error}", file=sys.stderr)
        print(f"reproduce: {message}", file=sys.stderr)
        return 2 if not args.metriplane_commit else 1
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
