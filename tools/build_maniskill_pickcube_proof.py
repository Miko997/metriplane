# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Build the deterministic ManiSkill PickCube public proof from frozen fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

PROOF_RELATIVE = Path("proofs/maniskill-pickcube-v1")
FIXTURE_RELATIVE = Path("examples/external_sources/maniskill_pickcube")
STATIC_PROOF_FILES = (
    "README.md",
    "REPRODUCE.md",
    "CLAIMS.md",
    "READINESS.md",
    "NOTICE.md",
    "EVALUATOR.md",
    "evaluator-report-template.md",
    "CITATION.cff",
    "proof-record.schema.json",
    "reproduce.py",
)
FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
FULL_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PRIVATE_PATH = re.compile(
    rb"(?:(?<![A-Za-z0-9_+.-])[A-Za-z]:[\\/][^\x00\r\n\"']+|"
    rb"/(?:home|Users|workspace|tmp|private/tmp|var/folders)/[^\x00\r\n\"']+)"
)
PROHIBITED_RAW_SUFFIXES = {
    ".h5",
    ".hdf5",
    ".urdf",
    ".glb",
    ".gltf",
    ".mp4",
    ".mov",
    ".avi",
    ".png",
    ".jpg",
    ".jpeg",
    ".ckpt",
    ".pth",
}
EXPECTED_COUNTS = {
    "incident": {"frame_count": 75, "event_count": 4, "deviation_count": 1, "incident_count": 1},
    "control": {"frame_count": 75, "event_count": 3, "deviation_count": 0, "incident_count": 0},
}
EXPECTED_FINGERPRINTS = {
    "incident": "954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2",
    "control": "8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e",
}
EXPECTED_SESSION = "7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df"
EXPECTED_MAPPING = "9127535a2e8eb3091aeac82f335e001f81c3a9e5098272881f7969c6eeecbee7"
EXPECTED_ADAPTER = "95d1134d9fb9273318c552c507952f1c5c26877e"
IMPLEMENTATION_MERGE = "1549d0a05e03db51efc0ee08edb7d9db66196b4e"
CONTRACT_SCHEMA_SHA = "b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4"
CANDIDATE_IDENTITY_PATHS = (
    "metriplane",
    "integrations",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "LICENSE",
    "NOTICE",
    "adapters/maniskill_pickcube",
    "examples/external_sources/maniskill_pickcube",
    "schemas/metriplane.external_source_contract.v1.schema.json",
    "proofs/maniskill-pickcube-v1/CITATION.cff",
    "proofs/maniskill-pickcube-v1/CLAIMS.md",
    "proofs/maniskill-pickcube-v1/EVALUATOR.md",
    "proofs/maniskill-pickcube-v1/NOTICE.md",
    "proofs/maniskill-pickcube-v1/README.md",
    "proofs/maniskill-pickcube-v1/REPRODUCE.md",
    "proofs/maniskill-pickcube-v1/evaluator-report-template.md",
    "proofs/maniskill-pickcube-v1/proof-record.schema.json",
    "proofs/maniskill-pickcube-v1/reproduce.py",
)


class ProofBuildError(RuntimeError):
    """Raised when a publication invariant is not satisfied."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _json_load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProofBuildError(f"expected JSON object: {path}")
    return value


def _json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ProofBuildError(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _check_repository(repo: Path, commit: str, allow_dirty: bool) -> None:
    if FULL_COMMIT.fullmatch(commit) is None:
        raise ProofBuildError("--metriplane-commit must be a full lowercase 40-hex commit")
    _git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    head = _git(repo, "rev-parse", "HEAD")
    identity_diff = subprocess.run(
        ["git", "diff", "--exit-code", commit, head, "--", *CANDIDATE_IDENTITY_PATHS],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if identity_diff.returncode != 0:
        raise ProofBuildError(
            "tested candidate commit differs from template HEAD on the frozen "
            f"identity boundary: {commit} != {head}"
        )
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if dirty and not allow_dirty:
        raise ProofBuildError("refusing to build publication proof from a dirty Git tree")


def _copy_static_template(template: Path, out: Path) -> None:
    for name in STATIC_PROOF_FILES:
        source = template / name
        if not source.is_file():
            raise ProofBuildError(f"missing proof template file: {source}")
        destination = out / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _command(executable: str, *arguments: str) -> list[str]:
    return [executable, *arguments]


def _run_json(command: list[str], *, repo: Path, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ProofBuildError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProofBuildError(f"command did not emit JSON: {' '.join(command)}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProofBuildError(f"command emitted non-object JSON: {' '.join(command)}")
    return value


def _canonical_validation(value: dict[str, Any], variant: str) -> dict[str, Any]:
    result = json.loads(json.dumps(value))
    result["fixture_root"] = f"examples/external_sources/maniskill_pickcube/{variant}"
    return result


def _canonical_run(value: dict[str, Any], variant: str) -> dict[str, Any]:
    result = json.loads(json.dumps(value))
    result["output_directory"] = f"{variant}-run"
    result["report_path"] = f"{variant}-run/cell_truth_report.html"
    if isinstance(result.get("validation"), dict):
        result["validation"] = _canonical_validation(result["validation"], variant)
    if isinstance(result.get("provenance"), dict):
        result["provenance"]["path"] = f"{variant}-run/external_source_provenance.json"
    for item in result.get("evidence_bundles", []):
        if isinstance(item, dict):
            item["path"] = "incident-run/evidence_bundles/INC-0001.zip"
    for item in result.get("generated_regressions", []):
        if isinstance(item, dict):
            item["path"] = "incident-run/regression_tests/INC-0001.yaml"
    return result


def _assert_summary(value: dict[str, Any], variant: str) -> None:
    if value.get("pass") is not True:
        raise ProofBuildError(f"{variant} run failed: {value.get('errors')}")
    for name, expected in EXPECTED_COUNTS[variant].items():
        observed = value.get(name)
        if observed != expected:
            raise ProofBuildError(f"{variant} {name}: expected {expected}, observed {observed}")


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


def _deterministic_zip(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        members = sorted(archive.infolist(), key=lambda item: item.filename)
        payloads = [
            (member.filename, archive.read(member)) for member in members if not member.is_dir()
        ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name, data in payloads:
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits |= 0x800
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _fixture_inventory(fixture: Path) -> list[str]:
    values = ["CHECKSUMS.sha256"]
    for line in (fixture / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, marker_path = line.split(maxsplit=1)
        relative = marker_path.lstrip(" *")
        path = fixture / relative
        if _sha256(path) != digest:
            raise ProofBuildError(f"fixture checksum mismatch: {path}")
        values.append(relative)
    return sorted(values)


def _environment_matrix(path: Path | None, commit: str) -> dict[str, Any]:
    if path is not None:
        value = _json_load(path)
        if value.get("metriplane_git_commit") != commit:
            raise ProofBuildError("environment matrix commit does not match candidate commit")
        matrix = value
    else:
        matrix = {
            "schema_version": "org.metriplane.maniskill_pickcube_environment_matrix.v1",
            "proof_level": "portable_fixture_evaluation",
            "conversion_portability": "not_evaluated_by_this_matrix",
            "metriplane_git_commit": commit,
            "complete": False,
            "jobs": [
                {
                    "job_id": f"{system.lower()}-python-{python}",
                    "operating_system": system,
                    "architecture": "x86_64" if system == "Ubuntu" else "arm64",
                    "python_version": python,
                    "level": "portable_fixture_evaluation",
                    "simulator_dependencies": [],
                    "status": "pending",
                    "workflow_url": None,
                    "reproduction_result_sha256": None,
                }
                for system in ("Ubuntu", "macOS")
                for python in ("3.12", "3.13")
            ],
            "limitations": [
                "CI runners are portability evidence, not independent users.",
                "The matrix evaluates portable fixtures and does not claim conversion portability on macOS.",
            ],
        }
    jobs = matrix.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 4:
        raise ProofBuildError("environment matrix must contain exactly four jobs")
    identities: set[tuple[object, object]] = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise ProofBuildError("environment matrix job must be a JSON object")
        identities.add((job.get("operating_system"), job.get("python_version")))
        if job.get("architecture") not in {"x86_64", "arm64"}:
            raise ProofBuildError("environment matrix architecture must be x86_64 or arm64")
        if job.get("level") != "portable_fixture_evaluation":
            raise ProofBuildError("environment matrix jobs must be Level A")
        if job.get("simulator_dependencies") != []:
            raise ProofBuildError("Level-A matrix jobs must have no simulator dependencies")
        if job.get("status") not in {"pending", "pass"}:
            raise ProofBuildError("environment matrix job status must be pending or pass")
        if job.get("status") == "pass":
            job_id = job.get("github_job_id")
            run_id = matrix.get("evidence_workflow_run_id")
            if not isinstance(job_id, int) or job_id <= 0:
                raise ProofBuildError("passing matrix job must record a GitHub job ID")
            if not isinstance(run_id, int) or run_id <= 0:
                raise ProofBuildError("complete matrix must record a GitHub workflow run ID")
            expected_url = (
                f"https://github.com/Miko997/metriplane/actions/runs/{run_id}/job/{job_id}"
            )
            if job.get("workflow_url") != expected_url:
                raise ProofBuildError("passing matrix job URL does not match its run and job IDs")
            result_hash = job.get("reproduction_result_sha256")
            if not isinstance(result_hash, str) or FULL_SHA256.fullmatch(result_hash) is None:
                raise ProofBuildError("passing matrix job must record a full reproduction hash")
            python_patch = job.get("python_patch_version")
            if not isinstance(python_patch, str) or not python_patch.startswith(
                f"{job.get('python_version')}."
            ):
                raise ProofBuildError("matrix Python patch version disagrees with its minor")
            for field in (
                "operating_system_version",
                "runner_image",
                "runner_image_version",
            ):
                if not isinstance(job.get(field), str) or not job[field]:
                    raise ProofBuildError(f"passing matrix job must record {field}")
    if identities != {
        ("Ubuntu", "3.12"),
        ("Ubuntu", "3.13"),
        ("macOS", "3.12"),
        ("macOS", "3.13"),
    }:
        raise ProofBuildError("environment matrix does not cover the required OS/Python pairs")
    complete = all(job["status"] == "pass" for job in jobs)
    if matrix.get("complete") is not complete:
        raise ProofBuildError("environment matrix complete flag disagrees with job statuses")
    if complete:
        evidence_head = matrix.get("evidence_head_commit")
        if not isinstance(evidence_head, str) or FULL_COMMIT.fullmatch(evidence_head) is None:
            raise ProofBuildError("complete matrix must record a full evidence-head commit")
        run_id = matrix.get("evidence_workflow_run_id")
        expected_run_url = f"https://github.com/Miko997/metriplane/actions/runs/{run_id}"
        if matrix.get("evidence_workflow_run_url") != expected_run_url:
            raise ProofBuildError("complete matrix workflow URL does not match its run ID")
    return matrix


def _artifact_record(
    path: Path, relative: str, media: str, purpose: str, license_text: str
) -> dict[str, str]:
    return {
        "path": relative,
        "media_type": media,
        "sha256": _sha256(path),
        "purpose": purpose,
        "license_classification": license_text,
    }


def _proof_record(
    *,
    repo: Path,
    out: Path,
    commit: str,
    publication_date: str,
    semantic_hashes: dict[str, str],
    matrix: dict[str, Any],
) -> dict[str, Any]:
    incident_fixture = repo / FIXTURE_RELATIVE / "incident"
    control_fixture = repo / FIXTURE_RELATIVE / "control"
    incident_manifest = _json_load(incident_fixture / "source-manifest.json")
    control_manifest = _json_load(control_fixture / "source-manifest.json")
    conversion = _json_load(incident_fixture / "normalization-report.json")[
        "conversion_reproducibility"
    ]
    run_ids = [item["run_id"] for item in conversion["runs"]]
    artifacts_root = out / "artifacts"
    artifacts = [
        _artifact_record(
            out / "proof-record.schema.json",
            "proof-record.schema.json",
            "application/schema+json",
            "Closed Draft 2020-12 schema for the proof record.",
            "MIT proof metadata",
        ),
        _artifact_record(
            artifacts_root / "incident-validation.json",
            "artifacts/incident-validation.json",
            "application/json",
            "Canonical incident fixture validation summary.",
            "MIT proof metadata",
        ),
        _artifact_record(
            artifacts_root / "control-validation.json",
            "artifacts/control-validation.json",
            "application/json",
            "Canonical control fixture validation summary.",
            "MIT proof metadata",
        ),
        _artifact_record(
            artifacts_root / "incident-run-summary.json",
            "artifacts/incident-run-summary.json",
            "application/json",
            "Canonical incident evaluation summary.",
            "MIT proof metadata",
        ),
        _artifact_record(
            artifacts_root / "control-run-summary.json",
            "artifacts/control-run-summary.json",
            "application/json",
            "Canonical control evaluation summary.",
            "MIT proof metadata",
        ),
        _artifact_record(
            artifacts_root / "incident-evidence.zip",
            "artifacts/incident-evidence.zip",
            "application/zip",
            "Verified incident evidence bundle.",
            "Mixed: MIT-generated evidence metadata and Apache-2.0-treated modified fixture state",
        ),
        _artifact_record(
            artifacts_root / "incident-regression.yaml",
            "artifacts/incident-regression.yaml",
            "application/yaml",
            "Portable generated incident regression specification.",
            "MIT proof metadata",
        ),
        _artifact_record(
            artifacts_root / "incident-regression-result.json",
            "artifacts/incident-regression-result.json",
            "application/json",
            "Public-command regression execution result.",
            "MIT proof metadata",
        ),
        _artifact_record(
            artifacts_root / "equivalence-summary.json",
            "artifacts/equivalence-summary.json",
            "application/json",
            "Three-conversion and three-run equivalence summary.",
            "MIT proof metadata",
        ),
        _artifact_record(
            artifacts_root / "environment-matrix.json",
            "artifacts/environment-matrix.json",
            "application/json",
            "Required installed-wheel OS and Python portability matrix.",
            "MIT proof metadata",
        ),
    ]
    exact_inventory = _fixture_inventory(incident_fixture)
    if exact_inventory != _fixture_inventory(control_fixture):
        raise ProofBuildError("incident/control fixture inventories differ")
    return {
        "schema_version": "org.metriplane.maniskill_pickcube_proof.v1",
        "proof_identity": {
            "proof_id": "maniskill-pickcube-v1",
            "proof_version": 1,
            "status": "candidate",
            "publication_date": publication_date,
            "canonical_repository": "https://github.com/Miko997/metriplane",
            "canonical_tag": "maniskill-pickcube-proof-v1",
            "canonical_commit": None,
            "implementation_merge_commit": IMPLEMENTATION_MERGE,
            "candidate_commit": commit,
            "proof_publication_commit": None,
            "proof_landing_page_path": "proofs/maniskill-pickcube-v1/README.md",
            "proposed_canonical_url": "https://github.com/Miko997/metriplane/tree/maniskill-pickcube-proof-v1/proofs/maniskill-pickcube-v1",
            "canonical_url": None,
        },
        "source": {
            "source_project": "mani-skill/ManiSkill",
            "conversion_release": "v3.0.1",
            "conversion_commit": "a4a4f9272ad64b1564035874b605ceb687b63ed8",
            "conversion_wheel": {
                "package": "mani_skill==3.0.1",
                "sha256": "685de2f03c300b1ede49881a1bf6306ad062082d39c8d3be8b8e85603f32e33a",
            },
            "dataset_project": "haosulab/ManiSkill_Demonstrations",
            "dataset_revision": "d674485bbffdd533914e52d272fdda34c0515608",
            "source_generation_package": "ManiSkill 3.0.0b4",
            "source_generation_commit": "652ad9353c0223507a938f0e8d990dd6f1c771ad",
            "artifacts": [
                {
                    "artifact_id": "pickcube_archive",
                    "path": "demos/PickCube-v1.zip",
                    "bytes": 36590010,
                    "sha256": "b2d4afb30fa309755862b98c342e6ee18918253c93f3bbac16ed6670748f26d8",
                },
                {
                    "artifact_id": "pickcube_trajectory_hdf5",
                    "path": "demos/PickCube-v1/motionplanning/trajectory.h5",
                    "bytes": 29349195,
                    "sha256": "03ca60546541a7f18321d9d32721f0254bc75217828c0cadacd217d0c014576a",
                },
                {
                    "artifact_id": "pickcube_trajectory_metadata",
                    "path": "demos/PickCube-v1/motionplanning/trajectory.json",
                    "bytes": 228218,
                    "sha256": "16e403cb77bfbdda28c243b96eb90adbae1c0edf42854283be57ee47076a2e90",
                },
            ],
            "episode_id": 0,
            "hdf5_group": "traj_0",
            "transition_count": 74,
            "stored_state_count": 75,
            "rl_horizon": 50,
            "upstream_corpus_limitation": "Episode selection was outcome-blind only within an official demonstration corpus already success-filtered upstream.",
        },
        "adapter": {
            "adapter_id": "org.metriplane.maniskill_pickcube",
            "adapter_version": "1.0.0",
            "commit": EXPECTED_ADAPTER,
            "path": "adapters/maniskill_pickcube",
            "dependency_lock_sha256": "f28f8618680de09c94e855a8b5d2a995ab6241b96c462650cada9c896335ec80",
            "environment": {
                "operating_system": "Linux",
                "architecture": "x86_64",
                "runtime": "CPython",
                "runtime_version": "3.12",
            },
            "restoration_method": "Restore each of 75 states independently with env.unwrapped.set_state_dict, then read cube.pose and agent.tcp_pose through named APIs.",
            "actions_integrated": False,
            "rendering": False,
        },
        "contract": {
            "external_source_contract_version": "metriplane.external_source_contract.v1",
            "contract_profile": "metriplane.atlas.complete_snapshot.v1",
            "contract_schema_sha256": CONTRACT_SCHEMA_SHA,
            "frame_state_model_version": "1.0",
            "metriplane_package_version": "0.3.0",
            "metriplane_git_commit": commit,
        },
        "normalization": {
            "object_ids": ["cube_1", "robot_tcp_1"],
            "source_to_normalized_mapping": [
                {
                    "source": "traj_0/env_states/actors/cube via cube.pose",
                    "normalized": "cube_1.pos_world",
                },
                {
                    "source": "traj_0/env_states/articulations/panda via agent.tcp_pose",
                    "normalized": "robot_tcp_1.pos_world",
                },
            ],
            "authoritative_clock": "ts_sim_ns(i) = i * 50000000 for stored-state index i; ts is derived from that integer clock.",
            "coordinate_mapping": "Identity source-world X/Y in metres, normalized Z set to 0.0, no translation, rotation, scale, or axis swap.",
            "discarded_fields": [
                "source Z",
                "complete quaternion",
                "yaw",
                "roll",
                "pitch",
                "velocities",
                "grasp/contact state",
                "actions",
            ],
            "confidence_policy": "absent",
            "interpolation_policy": "none",
            "resampling_policy": "none",
            "carry_forward_policy": "none",
            "annotation_exclusion_policy": "Reward, success, termination, truncation, task outcomes, and the RL horizon remain provenance only and never feed normalized state or Atlas incidents.",
        },
        "operator_rules": {
            "target_polygon": [
                [0.016815734803676603, -0.01198131799697876],
                [0.03681573480367661, -0.01198131799697876],
                [0.03681573480367661, 0.00801868200302124],
                [0.016815734803676603, 0.00801868200302124],
            ],
            "boundary_policy": "inclusive",
            "overlap_policy": "reject",
            "outside_workspace_policy": "explicit_label",
            "outside_zone_label": "outside_workspace",
            "incident_wait_s": 0.2,
            "control_wait_s": 0.3,
            "provenance": "The polygon and both relative waits are operator-configured Metriplane compatibility-test rules, not source task truth.",
        },
        "fixtures": {
            "incident": {
                "path": FIXTURE_RELATIVE.joinpath("incident").as_posix(),
                "fixture_id": incident_manifest["fixture"]["fixture_id"],
                "manifest_sha256": _sha256(incident_fixture / "source-manifest.json"),
                "fingerprint_sha256": _sha256(incident_fixture / "CHECKSUMS.sha256"),
                "inventory_count": len(exact_inventory),
            },
            "control": {
                "path": FIXTURE_RELATIVE.joinpath("control").as_posix(),
                "fixture_id": control_manifest["fixture"]["fixture_id"],
                "manifest_sha256": _sha256(control_fixture / "source-manifest.json"),
                "fingerprint_sha256": _sha256(control_fixture / "CHECKSUMS.sha256"),
                "inventory_count": len(exact_inventory),
            },
            "shared_session_sha256": EXPECTED_SESSION,
            "mapping_sha256": EXPECTED_MAPPING,
            "exact_inventory": exact_inventory,
        },
        "results": {
            "validation": {
                "incident": {"pass": True, "frame_count": 75},
                "control": {"pass": True, "frame_count": 75},
            },
            "incident_run": {
                "counts": EXPECTED_COUNTS["incident"],
                "semantic_hash": semantic_hashes["incident"],
                "bundle_verified": True,
                "regression_passed": True,
                "bundle_count": 1,
                "regression_count": 1,
            },
            "control_run": {
                "counts": EXPECTED_COUNTS["control"],
                "semantic_hash": semantic_hashes["control"],
                "bundle_verified": False,
                "regression_passed": False,
                "bundle_count": 0,
                "regression_count": 0,
            },
            "conversions": {
                "equivalent": True,
                "run_ids": run_ids,
                "compared_artifact_count": 28,
            },
            "run_equivalence": {
                "incident": {
                    "equivalent": True,
                    "run_count": 3,
                    "semantic_hash": semantic_hashes["incident"],
                },
                "control": {
                    "equivalent": True,
                    "run_count": 3,
                    "semantic_hash": semantic_hashes["control"],
                },
            },
            "environment_matrix": {
                "path": "artifacts/environment-matrix.json",
                "complete": matrix["complete"],
                "required_jobs": 4,
            },
        },
        "rights": {
            "source_artifacts_referenced_not_included": True,
            "adapter_software_license": "MIT",
            "derived_fixture_data_treatment": "Apache-2.0 fixture-scoped modified/derived data",
            "modified_data_notice": "The portable positions are modified/derived data; raw ZIP, HDF5, JSON, simulator assets, images, and recordings are not included.",
            "upstream_attribution": "ManiSkill and the ManiSkill Demonstrations dataset are cited at immutable source identities without implying endorsement.",
            "excluded_assets": [
                "raw ZIP",
                "raw HDF5",
                "raw JSON",
                "Panda assets",
                "table assets",
                "URDF/GLB",
                "checkpoints",
                "videos",
                "screenshots",
                "rendered images",
            ],
        },
        "claims": {
            "allowed": [
                "One exact official ManiSkill demonstration episode was normalized into a contract-valid position-only Metriplane fixture.",
                "All 75 stored source states were retained and the 50-step RL horizon remained separate provenance.",
                "Incident and control used byte-identical normalized state and differed only by declared variant identities and operator-configured relative waits.",
                "The portable fixture can be evaluated without ManiSkill, and the representative incident bundle verifies and regression passes.",
            ],
            "prohibited": [
                "official PickCube success or failure",
                "grasp or robot-control failure",
                "3D placement or orientation evaluation",
                "physical accuracy, simulator realism, or sim-to-real validity",
                "safety, quality certification, or production readiness",
                "native or general ManiSkill integration or endorsement",
                "independent reproduction, external adoption, or industry use",
            ],
            "limitations": [
                "The source corpus was already success-filtered upstream.",
                "Source Z and all orientation are discarded.",
                "The polygon and waits are operator-authored rather than source task truth.",
            ],
            "evidence_classification": "owner_generated_public_technical_proof",
            "independent_reproduction": False,
        },
        "artifacts": artifacts,
    }


def _scan_publication(out: Path, forbidden: list[bytes]) -> None:
    errors: list[str] = []
    for path in sorted(item for item in out.rglob("*") if item.is_file()):
        relative = path.relative_to(out).as_posix()
        if path.suffix.lower() in PROHIBITED_RAW_SUFFIXES:
            errors.append(f"prohibited raw/source asset extension: {relative}")
        if path.parent != out / "artifacts" and path.name != "proof-record.json":
            continue
        candidates: list[tuple[str, bytes]] = [(relative, path.read_bytes())]
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                candidates = [
                    (f"{relative}!{member.filename}", archive.read(member))
                    for member in archive.infolist()
                    if not member.is_dir()
                ]
        for location, data in candidates:
            if PRIVATE_PATH.search(data):
                errors.append(f"machine-local path in {location}")
            for value in forbidden:
                if value and value in data:
                    errors.append(f"operational path sentinel in {location}")
    if errors:
        raise ProofBuildError("publication scan failed:\n- " + "\n- ".join(sorted(set(errors))))


def _write_checksums(out: Path) -> None:
    paths = sorted(path for path in out.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text(
        "".join(f"{_sha256(path)}  {path.relative_to(out).as_posix()}\n" for path in paths),
        encoding="utf-8",
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo_root.resolve()
    out = args.out.resolve()
    template = (args.template_root or (repo / PROOF_RELATIVE)).resolve()
    _check_repository(repo, args.metriplane_commit, args.allow_dirty)
    if out.exists() or out.is_symlink():
        raise ProofBuildError(f"output must not exist: {out}")
    out.mkdir(parents=True)
    _copy_static_template(template, out)
    artifacts = out / "artifacts"
    artifacts.mkdir()

    incident_fixture = repo / FIXTURE_RELATIVE / "incident"
    control_fixture = repo / FIXTURE_RELATIVE / "control"
    fixture_tree_before = {
        "incident": _tree_sha256(incident_fixture),
        "control": _tree_sha256(control_fixture),
    }
    if _sha256(incident_fixture / "CHECKSUMS.sha256") != EXPECTED_FINGERPRINTS["incident"]:
        raise ProofBuildError("incident fixture fingerprint changed")
    if _sha256(control_fixture / "CHECKSUMS.sha256") != EXPECTED_FINGERPRINTS["control"]:
        raise ProofBuildError("control fixture fingerprint changed")
    if _sha256(incident_fixture / "session.jsonl") != EXPECTED_SESSION:
        raise ProofBuildError("incident session changed")
    if _sha256(control_fixture / "session.jsonl") != EXPECTED_SESSION:
        raise ProofBuildError("control session changed")
    if (
        _sha256(repo / "schemas/metriplane.external_source_contract.v1.schema.json")
        != CONTRACT_SCHEMA_SHA
    ):
        raise ProofBuildError("External Source Contract v1 schema changed")

    env = dict(os.environ)
    env["METRIPLANE_GIT_COMMIT"] = args.metriplane_commit
    executable = args.metriplane_command
    semantic_hashes: dict[str, str] = {}
    canonical_runs: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="metriplane-proof-build-") as temp_value:
        temp = Path(temp_value)
        for variant, fixture in (("incident", incident_fixture), ("control", control_fixture)):
            validation = _run_json(
                _command(executable, "external", "validate", str(fixture), "--json"),
                repo=repo,
                env=env,
            )
            if validation.get("pass") is not True:
                raise ProofBuildError(f"{variant} validation failed: {validation.get('errors')}")
            _json_write(
                artifacts / f"{variant}-validation.json",
                _canonical_validation(validation, variant),
            )
            run_hashes: list[str] = []
            summaries: list[dict[str, Any]] = []
            for index in range(1, 4):
                run_root = temp / f"{variant}-run-{index}"
                summary = _run_json(
                    _command(
                        executable,
                        "external",
                        "run",
                        str(fixture),
                        "--out",
                        str(run_root),
                        "--run-id",
                        f"maniskill_pickcube_{variant}_proof",
                        "--json",
                    ),
                    repo=repo,
                    env=env,
                )
                _assert_summary(summary, variant)
                if variant == "control":
                    if list((run_root / "evidence_bundles").glob("*")):
                        raise ProofBuildError("control created evidence artifacts")
                    if list((run_root / "regression_tests").glob("*")):
                        raise ProofBuildError("control created regression artifacts")
                run_hashes.append(_semantic_hash(run_root))
                summaries.append(summary)
            if len(set(run_hashes)) != 1:
                raise ProofBuildError(f"{variant} three-run semantic equivalence failed")
            semantic_hashes[variant] = run_hashes[0]
            canonical_runs[variant] = _canonical_run(summaries[0], variant)
            _json_write(artifacts / f"{variant}-run-summary.json", canonical_runs[variant])

        first_incident = temp / "incident-run-1"
        generated_bundle = first_incident / "evidence_bundles" / "INC-0001.zip"
        _deterministic_zip(generated_bundle, artifacts / "incident-evidence.zip")
        verify = _run_json(
            _command(
                executable, "atlas", "bundle", "verify", str(artifacts / "incident-evidence.zip")
            ),
            repo=repo,
            env=env,
        )
        if verify.get("pass") is not True:
            raise ProofBuildError(f"deterministic incident bundle failed verification: {verify}")
        create = subprocess.run(
            _command(
                executable,
                "atlas",
                "regression",
                "create",
                "--bundle",
                str(artifacts / "incident-evidence.zip"),
                "--out",
                str(artifacts / "incident-regression.yaml"),
            ),
            cwd=repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if create.returncode != 0:
            raise ProofBuildError(f"regression creation failed: {create.stderr}")
        regression = _run_json(
            _command(
                executable, "atlas", "test", str(artifacts / "incident-regression.yaml"), "--json"
            ),
            repo=repo,
            env=env,
        )
        if regression.get("pass") is not True:
            raise ProofBuildError(f"published regression failed: {regression}")
        _json_write(artifacts / "incident-regression-result.json", regression)

    conversion = _json_load(incident_fixture / "normalization-report.json")[
        "conversion_reproducibility"
    ]
    equivalence = {
        "schema_version": "org.metriplane.maniskill_pickcube_equivalence_summary.v1",
        "metriplane_git_commit": args.metriplane_commit,
        "conversion": {
            "equivalent": conversion["equivalent"],
            "comparison_policy": conversion["comparison_policy"],
            "run_ids": [item["run_id"] for item in conversion["runs"]],
            "compared_artifact_count": 28,
            "incident_fixture_fingerprint_sha256": EXPECTED_FINGERPRINTS["incident"],
            "control_fixture_fingerprint_sha256": EXPECTED_FINGERPRINTS["control"],
        },
        "evaluation": {
            variant: {
                "equivalent": True,
                "run_count": 3,
                "semantic_hash": semantic_hashes[variant],
                "counts": EXPECTED_COUNTS[variant],
            }
            for variant in ("incident", "control")
        },
    }
    _json_write(artifacts / "equivalence-summary.json", equivalence)
    matrix = _environment_matrix(args.environment_matrix, args.metriplane_commit)
    _json_write(artifacts / "environment-matrix.json", matrix)

    if fixture_tree_before != {
        "incident": _tree_sha256(incident_fixture),
        "control": _tree_sha256(control_fixture),
    }:
        raise ProofBuildError("proof build mutated a frozen fixture")

    record = _proof_record(
        repo=repo,
        out=out,
        commit=args.metriplane_commit,
        publication_date=args.publication_date,
        semantic_hashes=semantic_hashes,
        matrix=matrix,
    )
    _json_write(out / "proof-record.json", record)
    _scan_publication(
        out,
        [str(repo).encode(), str(out).encode(), str(Path.home()).encode()],
    )
    _write_checksums(out)
    return {
        "schema_version": "org.metriplane.maniskill_pickcube_proof_build.v1",
        "pass": True,
        "out": out.as_posix(),
        "candidate_commit": args.metriplane_commit,
        "proof_record_sha256": _sha256(out / "proof-record.json"),
        "sha256sums_sha256": _sha256(out / "SHA256SUMS"),
        "environment_matrix_complete": matrix["complete"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--metriplane-commit", required=True)
    parser.add_argument("--publication-date", required=True)
    parser.add_argument("--template-root", type=Path)
    parser.add_argument("--environment-matrix", type=Path)
    parser.add_argument("--metriplane-command", default=shutil.which("metriplane") or "metriplane")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="controlled development build only; never use for the publication artifact",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build(args)
    except (OSError, ProofBuildError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(f"proof-builder: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
