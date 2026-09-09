# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""S2 production finalization tests; all release inputs are synthetic fixtures.

This module is also the complete unrelated installed-wheel/sdist test harness.
It does not read the checkout or import another test module at import time.
Only the explicitly source-only locked-build test reads source project files.
"""

from __future__ import annotations

import copy
import errno
import gzip
import io
import json
import os
import signal
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

from metriplane import release_control as control


FINALIZER = "finalize_release_candidate_identity.py"
VALIDATOR = "validate_release_candidate_identity.py"
IDENTITY = "candidate-identity.json"
RUN_ID = "synthetic-finalization-fixture"
FIELDS = {
    "artifact_manifest_digest",
    "artifact_set_digest",
    "build_invocation_id",
    "candidate_digest",
    "evaluation_adoption_digest",
    "evaluation_adoption_mode",
    "gate_input_digest",
    "milestone",
    "package_version",
    "predecessor_digest",
    "release_tag",
    "source_freeze_digest",
    "finalization_intent_digest",
    "control_journal_locator",
    "final_directory",
}
INPUT_NAMES = (
    "artifact-manifest.json",
    "gate-input.json",
    "predecessor.json",
    "source-freeze.json",
    "target-resolution.json",
)
REGISTRIES = {
    "environment_registry_digest": "supported-environments",
    "evidence_store_registry_digest": "release-evidence-stores",
    "obligation_registry_digest": "release-test-obligations",
    "readiness_registry_digest": "release-readiness",
    "scenario_registry_digest": "release-scenarios",
    "target_registry_digest": "release-targets",
    "task_state_policy_digest": "release-task-state-policy",
}


def _git(repository: Path, *arguments: str) -> str:
    environment = dict(os.environ)
    environment.update(
        GIT_AUTHOR_DATE="2026-01-01T00:00:00Z", GIT_COMMITTER_DATE="2026-01-01T00:00:00Z"
    )
    return subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(repository),
            *arguments,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _environment(*, fixture_mode: bool = True) -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONOPTIMIZE",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
    ):
        environment.pop(name, None)
    environment["METRIPLANE_RELEASE_FIXTURE_MODE"] = "1" if fixture_mode else "0"
    return environment


def _command(tool: str, arguments: list[str], *, patch: str = "") -> list[str]:
    # argv=None is deliberate: the public adapter path must not enter the old
    # internal-validator shortcut used by tool_main(tool, explicit_argv).
    bootstrap = (
        "import os,sys,signal,errno,json; from pathlib import Path\n"
        "from metriplane import release_control as c\n" + patch + "\n"
        "tool=sys.argv[1]; sys.argv=[tool,*sys.argv[2:]]\n"
        "raise SystemExit(c.tool_main(tool))\n"
    )
    return [sys.executable, "-P", "-c", bootstrap, tool, *arguments]


def _public(
    fixture: dict[str, Any],
    tool: str,
    arguments: list[str],
    *,
    patch: str = "",
    fixture_mode: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _command(tool, arguments, patch=patch),
        cwd=fixture["repository"],
        env=_environment(fixture_mode=fixture_mode),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    control.write_immutable_json(path, value)


def _replace(path: Path, raw: bytes) -> None:
    path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(0o400)


def _remake(record: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    return control.make_record(
        record["record_type"],
        data,
        invocation_id=record["invocation_id"],
        sequence=record["sequence"],
        synthetic=record["synthetic"],
        status=record["status"],
        signatures=record["signatures"],
    )


def _snapshot(root: Path) -> dict[str, Any]:
    """Observe every object without following symlinks, retaining real identity."""
    if not os.path.lexists(root):
        return {}
    result: dict[str, Any] = {}
    pending = [root]
    while pending:
        path = pending.pop()
        info = path.lstat()
        row: dict[str, Any] = {"device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode}
        name = "." if path == root else path.relative_to(root).as_posix()
        if stat.S_ISREG(info.st_mode):
            raw = path.read_bytes()
            row.update(size=len(raw), sha256=control.sha256_bytes(raw))
        elif stat.S_ISLNK(info.st_mode):
            row["target"] = os.readlink(path)
        elif stat.S_ISDIR(info.st_mode):
            pending.extend(sorted(path.iterdir(), reverse=True))
        result[name] = row
    return result


def _assert_preserved(before: dict[str, Any], root: Path) -> None:
    after = _snapshot(root)
    assert {name: after.get(name) for name in before} == before


def _minimal_project(repository: Path, version: str) -> None:
    """Real tracked bytes under the production recipe; no live registry authority."""
    recipe = control.RELEASE_BUILD_RECIPE
    pins = recipe["toolchain"]
    project = (
        '[build-system]\nrequires = ["setuptools==' + pins["setuptools"] + '"]\n'
        'build-backend = "' + recipe["backend"] + '"\n'
        '[project]\nname = "metriplane"\ndynamic = ["version"]\n'
        '[tool.setuptools.dynamic]\nversion = {attr = "metriplane.__version__"}\n'
        '[tool.uv]\nrequired-version = "==' + recipe["uv"] + '"\n'
        "[dependency-groups]\ndev = "
        + json.dumps([name + "==" + version for name, version in pins.items()])
        + "\n"
    )
    files = {
        "pyproject.toml": project,
        "uv.lock": "\n".join(
            '[[package]]\nname = "' + name + '"\nversion = "' + version + '"\n'
            for name, version in pins.items()
        ),
        "metriplane/__init__.py": '__version__ = "' + version + '"\n',
    }
    for name, contents in files.items():
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)


def _make_fixture(
    tmp_path: Path,
    *,
    milestone: str = "v0.4",
    real_project: bool = False,
    build: bool = True,
    bootstrap_predecessor: str = "v0.3.0",
) -> dict[str, Any]:
    repository = tmp_path / "source"
    repository.mkdir(parents=True)
    release_parent = tmp_path / "release"
    run = release_parent / ".staging" / RUN_ID
    run.mkdir(parents=True)
    release_root = release_parent / (milestone + ".0")
    release_root.mkdir()
    version = milestone.removeprefix("v") + ".0"
    if real_project:
        # This branch is source-only, called solely by the real locked-build test.
        from tools.release_artifacts import _REQUIRED_SDIST_PATHS

        source_root = Path(__file__).resolve().parents[1]
        for name in sorted(_REQUIRED_SDIST_PATHS | {"uv.lock"}):
            destination = repository / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((source_root / name).read_bytes())
        (repository / "metriplane/__init__.py").write_text('__version__ = "' + version + '"\n')
        (repository / "uv.lock").write_text(
            (repository / "uv.lock")
            .read_text()
            .replace('version = "0.4.0.post2"', 'version = "' + version + '"')
        )
    else:
        _minimal_project(repository, version)
    registry_bytes = {}
    for key, name in REGISTRIES.items():
        value = {
            "schema_version": "metriplane." + name + ".v1",
            "owner": "MP2-007",
            "synthetic_fixture": True,
            "live_status": "UNRESOLVED",
        }
        if name == "release-readiness":
            value.update(
                framework="BLOCKED_NOT_READY",
                live_release="BLOCKED_NOT_READY",
                blockers=["UPSTREAM_SOFTWARE_AND_LIVE_ACCEPTANCE_REQUIRED"],
            )
        path = repository / "docs/status" / (name + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = control.canonical_json(value)
        path.write_bytes(raw)
        registry_bytes[key] = control.sha256_bytes(raw)
    note = repository / "docs/releases" / (milestone + ".0-release-notes.md")
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Synthetic S2 fixture only. No signing, publication or provider authority.\n")
    workflow = repository / ".github/workflows/fixture.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text("name: Synthetic S2 fixture\non: workflow_dispatch\njobs: {}\n")
    for arguments in [
        ("init", "--initial-branch=fixture"),
        ("config", "user.name", "S2 fixture"),
        ("config", "user.email", "fixture@example.invalid"),
        ("add", "--all"),
        ("commit", "-m", "Synthetic S2 source; no release authority"),
    ]:
        _git(repository, *arguments)
    target_data = {
        "burn_lineage_digest": "3" * 64,
        "burn_target_ids": [],
        "initial_package_version": milestone + ".0",
        "initial_release_tag": milestone + ".0",
        "milestone": milestone,
        "observations_digest": "4" * 64,
        "prior_burn_digests": [],
        "requires_new_burn": False,
        "resolution_rule": "next_unused_same_milestone_patch",
        "selected_package_version": milestone + ".0",
        "selected_release_tag": milestone + ".0",
    }
    target_data["resolution_digest"] = control.sha256_json(target_data)
    target = control.make_record(
        "release-target-resolution",
        target_data,
        invocation_id="synthetic-s2-target",
        sequence=1,
        synthetic=True,
    )
    previous = bootstrap_predecessor if milestone == "v0.4" else "v0." + str(int(milestone[-1]) - 1)
    if milestone == "v1.0":
        previous = "v0.9"
    gate_data = {
        **registry_bytes,
        "expected_predecessor_milestone": previous,
        "linear_snapshot_digest": "5" * 64,
        "milestone": milestone,
        "role_assignments_digest": "6" * 64,
        "run_id": RUN_ID,
        "target_burn_digest": "7" * 64,
        "target_burn_index_receipt_digest": None,
        "target_resolution_digest": control.sha256_json(target),
    }
    gate_data["gate_input_digest"] = control.sha256_json(gate_data)
    gate = control.make_record(
        "release-gate-input",
        gate_data,
        invocation_id="synthetic-s2-gate",
        sequence=1,
        synthetic=True,
    )
    predecessor_version = "v0.3.0" if milestone == "v0.4" else previous + ".0"
    predecessor_milestone = None if milestone == "v0.4" else previous
    raw_ref = {"path": "original/input.json", "bytes": 1, "sha256": "2" * 64}
    predecessor_subject = {
        "framework_milestone": predecessor_milestone,
        "normalized_package_version": predecessor_version.removeprefix("v"),
        "release_tag": predecessor_version,
        "source_commit": "3" * 40,
        "source_tree": "4" * 40,
        "tag_object": "5" * 40,
        "artifacts": [
            {
                "bytes": 1,
                "filename": "metriplane-predecessor-py3-none-any.whl",
                "kind": "wheel",
                "readback": raw_ref,
                "sha256": "6" * 64,
            },
            {
                "bytes": 1,
                "filename": "metriplane-predecessor.tar.gz",
                "kind": "sdist",
                "readback": raw_ref,
                "sha256": "7" * 64,
            },
        ],
    }
    predecessor_data: dict[str, Any] = {
        "lineage_mode": "ORIGINAL_BOOTSTRAP" if milestone == "v0.4" else "RECONCILED_LKG",
        "candidate_milestone": milestone,
        "predecessor_milestone": predecessor_milestone,
        "version": predecessor_version,
        "package_version": predecessor_version.removeprefix("v"),
        "release_context_digest": "8" * 64,
        "release_context": raw_ref,
        "predecessor_policy_digest": "9" * 64,
        "predecessor_policy": raw_ref,
        "predecessor_subject": predecessor_subject,
        "predecessor_subject_digest": control.sha256_json(predecessor_subject),
        "proof_index": raw_ref,
        "producer_intent_digest": "a" * 64,
        "invocation_root_locator": "invocations",
        "genesis_authority_digest": "b" * 64 if milestone == "v0.4" else None,
        "completion_digest": None,
        "selection_observations": None,
        "qualification_digest": None,
        "reconciliation_digest": None,
        "final_retention_digest": None,
        "chain_receipt_digest": None,
        "chain_head": None,
        "lkg_digest": None,
        "pointer_transition_retention_digest": None,
        "pointer_envelope_digest": None,
        "pointer_retention_digest": None,
        "pointer_index_receipt_digest": None,
        "closed_decision_digest": None,
        "close_ready_observation_digest": None,
        "close_root_digest": None,
    }
    if milestone != "v0.4":
        predecessor_data["selection_observations"] = {
            "observed_at": "2026-01-01T00:00:00Z",
            "provider_state": raw_ref,
            "provider_event_history": raw_ref,
            "success_chain_readback": raw_ref,
            "lkg_state_and_history_readback": raw_ref,
            "attempt_index_readback": raw_ref,
        }
        for field in (
            "qualification_digest",
            "reconciliation_digest",
            "final_retention_digest",
            "chain_receipt_digest",
            "chain_head",
            "lkg_digest",
            "pointer_transition_retention_digest",
            "pointer_envelope_digest",
            "pointer_retention_digest",
            "pointer_index_receipt_digest",
            "closed_decision_digest",
            "close_ready_observation_digest",
            "close_root_digest",
        ):
            predecessor_data[field] = control.sha256_json({"field": field})
    predecessor = control.make_record(
        "release-predecessor",
        predecessor_data,
        invocation_id="synthetic-s2-predecessor",
        sequence=1,
        synthetic=True,
    )
    for name, record in [
        ("target-resolution.json", target),
        ("gate-input.json", gate),
        ("predecessor.json", predecessor),
    ]:
        _write(run / name, record)
    fixture: dict[str, Any] = {
        "repository": repository,
        "run": run,
        "release_root": release_root,
        "release_parent": release_parent,
        "control": release_parent / ".control" / RUN_ID / "invocations/candidate-finalization",
        "sha": _git(repository, "rev-parse", "HEAD"),
        "tree": _git(repository, "rev-parse", "HEAD^{tree}"),
    }
    result = _public(
        fixture,
        "freeze_release_source.py",
        [
            "--gate-input",
            str(run / "gate-input.json"),
            "--source-sha",
            fixture["sha"],
            "--out",
            str(run / "source-freeze.json"),
            "--invocation-dir",
            str(run / "invocations/source-freeze/001"),
        ],
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    if build:
        _synthetic_build(fixture)
    return fixture


def _build_argv(fixture: dict[str, Any]) -> list[str]:
    run = fixture["run"]
    return [
        "--target-resolution",
        str(run / "target-resolution.json"),
        "--source-freeze",
        str(run / "source-freeze.json"),
        "--out-dir",
        str(run / "artifacts"),
        "--manifest",
        str(run / "artifact-manifest.json"),
        "--invocation-dir",
        str(run / "invocations/artifact-build/001"),
    ]


def _synthetic_artifact_worker(directory: str) -> int:
    """Fixture prerequisite producer, never the S2 worker or a release authority."""
    context = control._validate_intent(Path(directory))
    control._durable_json(context.directory / "worker.pid", {"pid": os.getpid()})
    staged = context.directory / "staged"
    artifacts = staged / "artifacts"
    artifacts.mkdir(parents=True)
    source = control.read_json(context.root / "source-freeze.json")
    target = control.read_json(context.root / "target-resolution.json")
    version = target["data"]["selected_package_version"].removeprefix("v")
    wheel = artifacts / ("metriplane-" + version + "-py3-none-any.whl")
    with zipfile.ZipFile(wheel, "x") as archive:
        info = zipfile.ZipInfo("metriplane/__init__.py", date_time=(2026, 1, 1, 0, 0, 0))
        archive.writestr(info, "# Synthetic artifact fixture; not a release build.\n")
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        raw = b"Synthetic S2 artifact fixture. No publication or live authority.\n"
        info = tarfile.TarInfo("metriplane-" + version + "/FIXTURE.txt")
        info.size, info.mtime, info.mode = len(raw), 0, 0o644
        archive.addfile(info, io.BytesIO(raw))
    sdist = artifacts / ("metriplane-" + version + ".tar.gz")
    with sdist.open("xb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
            archive.write(tar_bytes.getvalue())
    rows = [
        {
            "path": path.name,
            "sha256": control.sha256_bytes(path.read_bytes()),
            "size": path.stat().st_size,
            "media_type": "application/vnd.pypa.wheel+zip"
            if path.suffix == ".whl"
            else "application/gzip",
        }
        for path in sorted(artifacts.iterdir())
    ]
    data = {
        "artifact_set_digest": control.sha256_json(rows),
        "artifacts": rows,
        "build_invocation_id": context.intent["invocation_id"],
        "build_recipe_digest": control.RELEASE_BUILD_RECIPE_DIGEST,
        "milestone": target["data"]["milestone"],
        "source_digest": source["data"]["freeze_digest"],
        "source_freeze_digest": control.sha256_json(source),
        "target_resolution_digest": control.sha256_json(target),
        "invocation_root_locator": "invocations",
        "producer_intent_digest": control.sha256_json(context.intent),
    }
    record = control.make_record(
        "release-artifact-manifest",
        data,
        invocation_id=context.intent["invocation_id"],
        sequence=1,
        synthetic=True,
    )
    _write(staged / "artifact-manifest.json", record)
    outputs = control._collect_staged_outputs(context)
    control._durable_json(
        context.directory / "worker-result.json",
        {
            "schema_version": "metriplane.release-worker-result.v1",
            "exit_code": 0,
            "outputs": outputs,
            "producer_intent_digest": control.sha256_json(context.intent),
        },
    )
    return 0


def _fixture_artifact_install(source: Path, destination: Path) -> list[tuple[Path, Path]]:
    destination.mkdir()
    installed = []
    for path in sorted(source.iterdir()):
        path.chmod(0o400)
        target = destination / path.name
        os.link(path, target, follow_symlinks=False)
        installed.append((path, target))
    return installed


def _synthetic_build(fixture: dict[str, Any]) -> None:
    run = fixture["run"]
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(fixture["repository"])
        patch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
        context = control.begin_release_invocation(
            "build_release_artifacts.py",
            _build_argv(fixture),
            run / "invocations/artifact-build/001",
            input_paths=[
                (run / "target-resolution.json", "metriplane.release-target-resolution.v1"),
                (run / "source-freeze.json", "metriplane.release-source-freeze.v1"),
            ],
            planned_outputs=[
                (run / "artifact-manifest.json", "metriplane.release-artifact-manifest.v1"),
                (run / "artifacts", "metriplane.release-artifact-directory.v1"),
            ],
        )
        code = (
            "import runpy,sys; namespace=runpy.run_path("
            + repr(str(Path(__file__).resolve()))
            + "); raise SystemExit(namespace['_synthetic_artifact_worker'](sys.argv[1]))"
        )
        patch.setattr(
            control,
            "_worker_command",
            lambda context: [sys.executable, "-c", code, str(context.directory)],
        )
        assert (
            control._supervise_release_invocation(
                context, artifact_installer=_fixture_artifact_install
            )
            == 0
        )
    manifest = control.read_json(run / "artifact-manifest.json")
    control.validate_release_artifact_files(manifest, run / "artifacts", live=False)


def _finalize_argv(fixture: dict[str, Any], sequence: int = 1) -> list[str]:
    run = fixture["run"]
    return [
        "--invocation-dir",
        str(fixture["control"] / f"{sequence:03d}"),
        "--gate-input",
        str(run / "gate-input.json"),
        "--source-freeze",
        str(run / "source-freeze.json"),
        "--predecessor",
        str(run / "predecessor.json"),
        "--artifact-manifest",
        str(run / "artifact-manifest.json"),
        "--no-evaluation-adoption",
        "--work-dir",
        str(run),
        "--release-root",
        str(fixture["release_root"]),
        "--identity-name",
        IDENTITY,
    ]


def _finalize(
    fixture: dict[str, Any], sequence: int = 1, *, patch: str = "", fixture_mode: bool = True
) -> subprocess.CompletedProcess[str]:
    return _public(
        fixture,
        FINALIZER,
        _finalize_argv(fixture, sequence),
        patch=patch,
        fixture_mode=fixture_mode,
    )


def _validator_argv(candidate: Path, sequence: int = 1) -> list[str]:
    return [
        "--record",
        str(candidate / IDENTITY),
        "--predecessor",
        str(candidate / "predecessor.json"),
        "--no-evaluation-adoption",
        "--candidate-dir",
        str(candidate),
        "--invocation-dir",
        str(candidate / "invocations" / "validate-release-candidate-identity" / f"{sequence:03d}"),
    ]


def _validate(
    fixture: dict[str, Any], candidate: Path, sequence: int = 1, *, patch: str = ""
) -> subprocess.CompletedProcess[str]:
    return _public(fixture, VALIDATOR, _validator_argv(candidate, sequence), patch=patch)


def _success(fixture: dict[str, Any], result: subprocess.CompletedProcess[str]) -> Path:
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert len(result.stdout.splitlines()) == 1
    value = json.loads(result.stdout)
    assert set(value) == {"status", "candidate_id", "candidate_dir", "identity_record"}
    assert value["status"] == "PASS"
    candidate = Path(value["candidate_dir"])
    assert candidate == fixture["release_root"] / value["candidate_id"]
    assert value["identity_record"] == str(candidate / IDENTITY)
    assert not fixture["run"].exists()
    record = control.read_json(candidate / IDENTITY)
    assert record["synthetic"] is True and record["signatures"] == []
    data = record["data"]
    assert set(data) == FIELDS
    expected = control.sha256_json(
        {k: v for k, v in data.items() if k not in {"candidate_digest", "final_directory"}}
    )
    assert value["candidate_id"] == data["candidate_digest"] == expected
    assert data["final_directory"] == str(candidate)
    journal = fixture["control"] / "001"
    intent = control.read_json(journal / "intent.json")
    assert data["finalization_intent_digest"] == control.sha256_json(intent)
    assert data["control_journal_locator"] == str(journal / "invocation.json")
    assert (journal / "stdout").read_bytes() == result.stdout.encode()
    terminal = control.read_json(journal / "invocation.json")
    assert terminal["status"] == "PASS" and terminal["data"]["exit_code"] == 0
    assert (journal / "terminal-commit.json").is_file()
    assert terminal["data"]["stdout_digest"] == control.sha256_bytes(result.stdout.encode())
    assert terminal["data"]["outputs"] == [
        {
            "path": IDENTITY,
            "schema_id": "metriplane.release-candidate-identity.v1",
            "sha256": control.sha256_bytes((candidate / IDENTITY).read_bytes()),
        }
    ]
    for name in ("inputs", "outputs"):
        assert all(set(row) == {"path", "schema_id", "sha256"} for row in terminal["data"][name])
    return candidate


def _direct_validate(candidate: Path) -> None:
    control.validate_release_candidate_identity_record(
        control.read_json(candidate / IDENTITY),
        predecessor_record=control.read_json(candidate / "predecessor.json"),
        candidate_dir=candidate,
        no_evaluation_adoption=True,
        live=False,
    )


def _export_records(destination: Path, candidate: Path, control_stage: Path) -> None:
    destination.mkdir()
    sources = [candidate / name for name in (*INPUT_NAMES, IDENTITY)]
    sources.append(control_stage / "001/invocation.json")
    rows = []
    for index, source in enumerate(sources):
        raw = source.read_bytes()
        record = json.loads(raw)
        assert record["synthetic"] is True
        name = f"record-{index:03d}.json"
        (destination / name).write_bytes(raw)
        rows.append(
            {"path": name, "kind": record["record_type"], "sha256": control.sha256_bytes(raw)}
        )
    _write(
        destination / "schema-positive-records.json",
        {"schema_version": "metriplane.s2-synthetic-schema-cases.v1", "records": rows},
    )


@pytest.fixture
def prepared(tmp_path: Path) -> dict[str, Any]:
    return _make_fixture(tmp_path)


@pytest.fixture
def finalized(prepared: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    return prepared, _success(prepared, _finalize(prepared))


def test_real_locked_s1_build_finalization_and_public_validation(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path, real_project=True, build=False)
    # Only this source test executes the genuine pinned build adapter/backend.
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tools/build_release_artifacts.py"), *_build_argv(fixture)],
        cwd=fixture["repository"],
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert (
        "Successfully built"
        in (fixture["run"] / "invocations/artifact-build/001/stdout").read_text()
    )
    before = _snapshot(fixture["run"])
    candidate = _success(fixture, _finalize(fixture))
    _assert_preserved(before, candidate)
    for name, tool in [
        ("source-freeze.json", "freeze_release_source.py"),
        ("artifact-manifest.json", "build_release_artifacts.py"),
    ]:
        control.validate_release_producer_journal(
            control.read_json(candidate / name), candidate / name, producer=tool
        )
    assert _validate(fixture, candidate).returncode == 0
    _direct_validate(candidate)
    _export_records(tmp_path / "actual-schema-records", candidate, fixture["control"])


class TestInstalledFinalization:
    """Exactly three installed smokes; no source-only fixtures or checkout imports."""

    def test_import_origin(self) -> None:
        module = Path(control.__file__).resolve()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json;from pathlib import Path;from metriplane import release_control as c;"
                "print(json.dumps({'path':str(Path(c.__file__).resolve()),'bytes':"
                "c.sha256_bytes(Path(c.__file__).read_bytes())}))",
            ],
            cwd=Path.cwd(),
            env=_environment(),
            capture_output=True,
            text=True,
            check=True,
        )
        observed = json.loads(result.stdout)
        assert observed == {"path": str(module), "bytes": control.sha256_bytes(module.read_bytes())}
        # Existing installed-profile conftest also enforces distribution/source origin.
        if os.environ.get("METRIPLANE_TEST_PROFILE", "source") != "source":
            assert Path(sys.prefix).resolve() in module.parents
            assert Path(__file__).resolve().parents[1] not in module.parents

    def test_public_finalization_and_validation(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        before = _snapshot(fixture["run"])
        candidate = _success(fixture, _finalize(fixture))
        _assert_preserved(before, candidate)
        assert _validate(fixture, candidate).returncode == 0
        _direct_validate(candidate)

    def test_conflict_recovery_and_tamper_rejection(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        candidate = _success(fixture, _finalize(fixture))
        before = _snapshot(candidate)
        original = _snapshot(fixture["control"] / "001")
        assert _finalize(fixture, 2).returncode == 3
        _assert_preserved(before, candidate)
        _assert_preserved(original, fixture["control"] / "001")
        assert not (fixture["control"] / "002/worker.pid").exists()
        artifact = next((candidate / "artifacts").glob("*.whl"))
        _replace(artifact, artifact.read_bytes() + b"tamper")
        assert _validate(fixture, candidate).returncode != 0
        with pytest.raises(control.ReleaseControlError):
            _direct_validate(candidate)


@pytest.mark.parametrize("field", sorted(FIELDS))
@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_every_candidate_field_recomputed(
    finalized: tuple[dict[str, Any], Path], field: str, mutation: str
) -> None:
    _, candidate = finalized
    record = control.read_json(candidate / IDENTITY)
    data = copy.deepcopy(record["data"])
    if mutation == "missing":
        del data[field]
    else:
        replacements: dict[str, Any] = {
            "evaluation_adoption_digest": "a" * 64,
            "evaluation_adoption_mode": "adopted",
            "milestone": "v0.5",
            "package_version": "v0.4.1",
            "release_tag": "v0.4.1",
            "build_invocation_id": "changed-build-invocation",
            "final_directory": str(candidate.parent / ("f" * 64)),
            "control_journal_locator": str(candidate / "invocation.json"),
        }
        data[field] = replacements.get(field, "a" * 64)
    mutant = _remake(record, data)
    _replace(candidate / IDENTITY, control.canonical_json(mutant))
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)
    with pytest.raises(control.ReleaseControlError):
        control._validate_candidate_identity_payload(
            data, expected_digest=record["data"]["candidate_digest"], expected_milestone="v0.4"
        )


def test_extra_candidate_field_and_rehashed_foreign_binding_fail(
    finalized: tuple[dict[str, Any], Path],
) -> None:
    _, candidate = finalized
    record = control.read_json(candidate / IDENTITY)
    for key, value in [("unrecognized", True), ("gate_input_digest", "f" * 64)]:
        data = {**record["data"], key: value}
        data["candidate_digest"] = control.sha256_json(
            {k: v for k, v in data.items() if k not in {"candidate_digest", "final_directory"}}
        )
        data["final_directory"] = str(candidate.parent / data["candidate_digest"])
        _replace(candidate / IDENTITY, control.canonical_json(_remake(record, data)))
        with pytest.raises(control.ReleaseControlError):
            _direct_validate(candidate)


@pytest.mark.parametrize("name", INPUT_NAMES)
@pytest.mark.parametrize("fault", ["missing", "raw-tamper", "symlink", "fifo"])
def test_fixed_input_unavailable_or_unsafe_blocks_before_identity(
    prepared: dict[str, Any],
    name: str,
    fault: str,
) -> None:
    path = prepared["run"] / name
    if fault == "raw-tamper":
        _replace(path, path.read_bytes() + b" ")
    else:
        raw = path.read_bytes()
        path.unlink()
        if fault == "symlink":
            outside = prepared["repository"].parent / "outside-input.json"
            outside.write_bytes(raw)
            path.symlink_to(outside)
        elif fault == "fifo":
            os.mkfifo(path)
    result = _finalize(prepared)
    assert result.returncode != 0
    assert not (prepared["run"] / IDENTITY).exists()
    assert list(prepared["release_root"].iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_milestone", "v0.5"),
        ("version", "v0.3.1"),
        ("version", "v0.4.0"),
        ("version", "0.3.0"),
        ("closed_decision_digest", ""),
        ("lkg_digest", "x" * 64),
        ("completion_digest", "f" * 64),
        ("predecessor_milestone", "v0.4"),
        ("unrecognized", True),
    ],
)
def test_predecessor_applicability_and_closed_shape_fail(
    prepared: dict[str, Any],
    field: str,
    value: Any,
) -> None:
    path = prepared["run"] / "predecessor.json"
    record = control.read_json(path)
    _replace(path, control.canonical_json(_remake(record, {**record["data"], field: value})))
    assert _finalize(prepared).returncode != 0
    assert not (prepared["run"] / IDENTITY).exists()


@pytest.mark.parametrize("milestone", ["v0.4", "v0.5", "v0.6", "v0.7", "v0.8", "v0.9"])
def test_ordinary_milestones_require_complete_applicable_predecessor(
    tmp_path: Path,
    milestone: str,
) -> None:
    fixture = _make_fixture(tmp_path, milestone=milestone)
    candidate = _success(fixture, _finalize(fixture))
    assert _validate(fixture, candidate).returncode == 0


def test_v1_completion_adoption_is_not_ordinary_finalization(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path, milestone="v1.0")
    assert _finalize(fixture).returncode != 0
    assert not (fixture["run"] / IDENTITY).exists()


def test_synthetic_inputs_cannot_authorize_live_mode(prepared: dict[str, Any]) -> None:
    assert _finalize(prepared, fixture_mode=False).returncode != 0
    assert not (prepared["run"] / IDENTITY).exists()


@pytest.mark.parametrize(
    "flag,replacement",
    [
        ("--identity-name", "../candidate-identity.json"),
        ("--identity-name", "/candidate-identity.json"),
        ("--identity-name", "alternate.json"),
        ("--identity-name", "nested/candidate-identity.json"),
        ("--work-dir", "wrong-staging"),
        ("--release-root", "wrong-tag"),
        ("--invocation-dir", "wrong-run"),
        ("--invocation-dir", "wrong-stage"),
        ("--invocation-dir", "wrong-sequence"),
    ],
)
def test_exact_two_root_path_contract(
    prepared: dict[str, Any], flag: str, replacement: str
) -> None:
    arguments = _finalize_argv(prepared)
    if replacement == "wrong-staging":
        value = str(prepared["run"].parent / "different-run")
    elif replacement == "wrong-tag":
        value = str(prepared["release_parent"] / "v0.4.1")
    elif replacement == "wrong-run":
        value = str(
            prepared["release_parent"]
            / ".control/another-run/invocations/candidate-finalization/001"
        )
    elif replacement == "wrong-stage":
        value = str(prepared["control"].parent / "source-freeze/001")
    elif replacement == "wrong-sequence":
        value = str(prepared["control"] / "01")
    else:
        value = replacement
    arguments[arguments.index(flag) + 1] = value
    before = _snapshot(prepared["run"])
    assert _public(prepared, FINALIZER, arguments).returncode != 0
    _assert_preserved(before, prepared["run"])
    assert not (prepared["run"] / IDENTITY).exists()


@pytest.mark.parametrize("component", ["staging", "release-root", "control-parent"])
def test_symlink_ancestors_do_not_supply_release_roots(
    prepared: dict[str, Any], component: str
) -> None:
    original = {
        "staging": prepared["run"].parent,
        "release-root": prepared["release_root"],
        "control-parent": prepared["release_parent"] / ".control",
    }[component]
    original.mkdir(parents=True, exist_ok=True)
    moved = original.with_name(original.name + "-actual")
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=True)
    before = _snapshot(moved)
    assert _finalize(prepared).returncode != 0
    _assert_preserved(before, moved)


def test_original_sequence_collision_does_not_reexecute(prepared: dict[str, Any]) -> None:
    candidate = _success(prepared, _finalize(prepared))
    before = _snapshot(candidate)
    journal = _snapshot(prepared["control"] / "001")
    assert _finalize(prepared).returncode != 0
    _assert_preserved(before, candidate)
    _assert_preserved(journal, prepared["control"] / "001")


def test_simultaneous_original_producers_have_one_identity_and_move(
    prepared: dict[str, Any],
) -> None:
    command = _command(FINALIZER, _finalize_argv(prepared))
    processes = [
        subprocess.Popen(
            command,
            cwd=prepared["repository"],
            env=_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            results.append(subprocess.CompletedProcess(command, process.returncode, stdout, stderr))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
    assert sorted(result.returncode == 0 for result in results) == [False, True]
    candidate = _success(prepared, next(result for result in results if result.returncode == 0))
    assert list(prepared["release_root"].iterdir()) == [candidate]
    _direct_validate(candidate)


@pytest.mark.parametrize(
    "extra",
    ["unexpected.json", "artifacts/unexpected.whl", "invocations/future-stage/001/intent.json"],
)
def test_arbitrary_appendages_are_not_later_control_authority(
    finalized: tuple[dict[str, Any], Path],
    extra: str,
) -> None:
    fixture, candidate = finalized
    path = candidate / extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"unapproved extra bytes")
    assert _validate(fixture, candidate).returncode != 0
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)


@pytest.mark.parametrize(
    "stage,tool",
    [
        ("source-freeze-validation", "validate_release_source_freeze.py"),
        ("artifact-manifest-validation", "validate_release_artifact_manifest.py"),
        ("validate-release-candidate-identity", VALIDATOR),
    ],
)
def test_complete_supported_validator_append_is_replayed(
    finalized: tuple[dict[str, Any], Path],
    stage: str,
    tool: str,
) -> None:
    fixture, candidate = finalized
    before = _snapshot(candidate)
    if tool == VALIDATOR:
        arguments = _validator_argv(candidate)
    elif tool == "validate_release_source_freeze.py":
        arguments = [
            "--record",
            str(candidate / "source-freeze.json"),
            "--verify-tree-clean",
            "--invocation-dir",
            str(candidate / "invocations" / stage / "001"),
        ]
    else:
        arguments = [
            "--record",
            str(candidate / "artifact-manifest.json"),
            "--artifacts",
            str(candidate / "artifacts"),
            "--read-hash",
            "--invocation-dir",
            str(candidate / "invocations" / stage / "001"),
        ]
    result = _public(fixture, tool, arguments)
    assert result.returncode == 0, (result.stdout, result.stderr)
    _assert_preserved(before, candidate)
    _direct_validate(candidate)
    assert _validate(fixture, candidate, 2 if tool == VALIDATOR else 1).returncode == 0
    _direct_validate(candidate)


@pytest.mark.parametrize("fault", ["incomplete", "gap", "wrong-tool", "wrong-input", "diagnostic"])
def test_other_validator_journal_cannot_use_active_caller_exception(
    finalized: tuple[dict[str, Any], Path],
    fault: str,
) -> None:
    fixture, candidate = finalized
    assert _validate(fixture, candidate).returncode == 0
    directory = candidate / "invocations/validate-release-candidate-identity/001"
    if fault == "incomplete":
        (directory / "invocation.json").unlink()
    elif fault == "gap":
        directory.rename(directory.with_name("002"))
    elif fault == "diagnostic":
        _replace(directory / "stderr", b"changed retained diagnostic")
    else:
        intent = control.read_json(directory / "intent.json")
        if fault == "wrong-tool":
            intent["tool"] = "validate_release_source_freeze.py"
        else:
            intent["argv"][intent["argv"].index("--record") + 1] = str(candidate / "other.json")
        intent["invocation_id"] = control._intent_identity(intent)
        _replace(directory / "intent.json", control.canonical_json(intent))
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)
    # A new public caller must not adopt an unrelated incomplete/forged original.
    assert _validate(fixture, candidate, 2 if fault != "gap" else 3).returncode != 0


@pytest.mark.parametrize(
    "name",
    [
        *INPUT_NAMES,
        "artifacts/metriplane-0.4.0-py3-none-any.whl",
        "invocations/source-freeze/001/stdout",
        "invocations/artifact-build/001/intent.json",
    ],
)
def test_captured_immutable_member_tamper_is_rejected(
    finalized: tuple[dict[str, Any], Path],
    name: str,
) -> None:
    fixture, candidate = finalized
    path = candidate / name
    _replace(path, path.read_bytes() + b"tamper")
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)
    assert _validate(fixture, candidate).returncode != 0


@pytest.mark.parametrize("member", ["intent.json", "invocation.json", "stdout", "stderr"])
def test_external_original_control_bytes_are_required(
    finalized: tuple[dict[str, Any], Path],
    member: str,
) -> None:
    fixture, candidate = finalized
    path = fixture["control"] / "001" / member
    _replace(path, path.read_bytes() + b"tamper")
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)
    assert _validate(fixture, candidate).returncode != 0


def _wrap(name: str, *, before: str = "", after: str = "") -> str:
    """Wrap a real production boundary; never substitute a passing verdict."""
    return (
        "original_" + name + "=c." + name + "\n"
        "def wrapped_"
        + name
        + "(*args,**kwargs):\n"
        + ("\n".join(" " + line for line in before.splitlines()) + "\n" if before else "")
        + " result=original_"
        + name
        + "(*args,**kwargs)\n"
        + ("\n".join(" " + line for line in after.splitlines()) + "\n" if after else "")
        + " return result\nc."
        + name
        + "=wrapped_"
        + name
        + "\n"
    )


def _kill_patch(point: str, fixture: dict[str, Any]) -> str:
    kill = "os.kill(os.getpid(),signal.SIGKILL)"
    if point == "before-identity":
        return _wrap("_install_release_outputs", before=kill)
    if point == "after-identity-before-rename":
        return _wrap("_rename_candidate_exclusive", before=kill)
    if point == "after-rename":
        return _wrap("_rename_candidate_exclusive", after=kill)
    if point == "after-retained-stdout-before-terminal":
        return _wrap("_complete_invocation", before=kill)
    if point == "after-terminal":
        return _wrap("_complete_invocation", after=kill)
    if point == "after-full-readback-before-stdout":
        return _wrap(
            "_verify_finalized_candidate_inventory",
            after=(
                "if kwargs.get('allow_appended',False) is False and "
                "Path(args[1]['data']['final_directory']).is_dir():\n " + kill
            ),
        )
    if point in {"first-final-readback-before", "first-final-readback-after"}:
        condition = (
            "path=Path(args[0])\nif path.name=="
            + repr(IDENTITY)
            + " and path.parent.parent==Path("
            + repr(str(fixture["release_root"]))
            + "):\n "
            + kill
        )
        return _wrap(
            "_safe_release_bytes",
            before=condition if point.endswith("before") else "",
            after=condition if point.endswith("after") else "",
        )
    if point in {"before-intent-write", "partial-intent-write", "partial-terminal-write"}:
        name = "invocation.json" if point == "partial-terminal-write" else "intent.json"
        condition = (
            "path=Path(args[0])\nif path==Path("
            + repr(str(fixture["control"] / "001" / name))
            + "):\n"
        )
        if point.startswith("partial"):
            condition += (
                " descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)\n"
                " os.write(descriptor,b'{\"incomplete\":'); os.fsync(descriptor); os.close(descriptor)\n"
            )
        condition += " " + kill
        return _wrap("_durable_json", before=condition)
    if point == "after-reservation-before-intent":
        return (
            "original_mkdir=Path.mkdir\ndef reservation(path,*args,**kwargs):\n"
            " result=original_mkdir(path,*args,**kwargs)\n"
            " if path==Path("
            + repr(str(fixture["control"] / "001"))
            + "):\n "
            + " "
            + kill
            + "\n return result\nPath.mkdir=reservation\n"
        )
    raise AssertionError("Unrecognized finite fault boundary: " + point)


@pytest.mark.parametrize("contents", [None, b"preserved existing destination member"])
def test_native_exclusive_rename_never_replaces_existing_destination(
    tmp_path: Path,
    contents: bytes | None,
) -> None:
    source_parent, destination_parent = tmp_path / "source-parent", tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source, destination = source_parent / "source", destination_parent / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "source.txt").write_bytes(b"source bytes")
    if contents is not None:
        (destination / "existing.txt").write_bytes(contents)
    before_source, before_destination = _snapshot(source), _snapshot(destination)
    source_fd = os.open(source_parent, os.O_RDONLY)
    destination_fd = os.open(destination_parent, os.O_RDONLY)
    try:
        with pytest.raises((OSError, control.ReleaseControlError)):
            control._rename_candidate_exclusive(source_fd, "source", destination_fd, "destination")
    finally:
        os.close(destination_fd)
        os.close(source_fd)
    assert _snapshot(source) == before_source
    assert _snapshot(destination) == before_destination


def test_native_exclusive_rename_preserves_object_and_bytes_on_required_platform(
    tmp_path: Path,
) -> None:
    assert sys.platform in {"linux", "darwin"}, (
        "Required native qualification platform is unsupported"
    )
    source_parent, destination_parent = tmp_path / "source-parent", tmp_path / "destination-parent"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "source"
    source.mkdir()
    (source / "payload").write_bytes(b"immutable native rename fixture")
    before = _snapshot(source)
    source_fd, destination_fd = (
        os.open(source_parent, os.O_RDONLY),
        os.open(destination_parent, os.O_RDONLY),
    )
    try:
        control._rename_candidate_exclusive(source_fd, "source", destination_fd, "destination")
    finally:
        os.close(destination_fd)
        os.close(source_fd)
    assert not source.exists()
    assert _snapshot(destination_parent / "destination") == before


@pytest.mark.parametrize(
    "error",
    [errno.EXDEV, errno.ENOSYS, errno.EINVAL, errno.ENOTSUP],
    ids=["cross-device", "not-implemented", "invalid", "not-supported"],
)
def test_native_failure_has_no_fallback_or_false_terminal(
    prepared: dict[str, Any], error: int
) -> None:
    before = _snapshot(prepared["run"])
    marker = prepared["repository"].parent / "native-call.json"
    patch = (
        "def fail_native(*args):\n"
        " Path(" + repr(str(marker)) + ").write_text(json.dumps(list(args)))\n"
        " raise OSError(" + str(error) + ", 'injected native boundary failure')\n"
        "c._rename_candidate_exclusive=fail_native\n"
    )
    result = _finalize(prepared, patch=patch)
    assert result.returncode != 0
    assert marker.is_file(), "The test must reach the actual native boundary"
    args = json.loads(marker.read_text())
    assert isinstance(args[0], int) and isinstance(args[2], int)
    assert Path(args[1]).name == args[1] and Path(args[3]).name == args[3]
    _assert_preserved(before, prepared["run"])
    assert list(prepared["release_root"].iterdir()) == []
    terminal = control.read_json(prepared["control"] / "001/invocation.json")
    assert terminal["status"] != "PASS" and terminal["data"]["outputs"] == []
    original = _snapshot(prepared["control"] / "001")
    assert _finalize(prepared, 2).returncode == 3
    _assert_preserved(original, prepared["control"] / "001")


@pytest.mark.parametrize("nonempty", [False, True])
def test_destination_collision_at_commit_preserves_both_names(
    prepared: dict[str, Any], nonempty: bool
) -> None:
    marker = prepared["repository"].parent / "collision.json"
    patch = _wrap(
        "_rename_candidate_exclusive",
        before=(
            "destination=Path(" + repr(str(prepared["release_root"])) + ")/args[3]\n"
            "destination.mkdir()\n"
            + (
                "(destination/'foreign').write_bytes(b'foreign destination bytes')\n"
                if nonempty
                else ""
            )
            + "Path("
            + repr(str(marker))
            + ").write_text(str(destination))"
        ),
    )
    assert _finalize(prepared, patch=patch).returncode != 0
    assert marker.exists()
    destination = Path(marker.read_text())
    before_source, before_destination = _snapshot(prepared["run"]), _snapshot(destination)
    assert (prepared["run"] / IDENTITY).is_file()
    assert _finalize(prepared, 2).returncode == 3
    assert _snapshot(prepared["run"]) == before_source
    assert _snapshot(destination) == before_destination
    assert not (destination / IDENTITY).exists()


@pytest.mark.parametrize("substitution", ["staging-object", "source-parent", "destination-parent"])
def test_object_substitution_at_rename_cannot_authorize_candidate(
    prepared: dict[str, Any],
    substitution: str,
) -> None:
    if substitution == "staging-object":
        original = prepared["run"]
    elif substitution == "source-parent":
        original = prepared["run"].parent
    else:
        original = prepared["release_root"]
    moved = original.with_name(original.name + "-preserved")
    patch = _wrap(
        "_rename_candidate_exclusive",
        before=(
            "original=Path(" + repr(str(original)) + "); preserved=Path(" + repr(str(moved)) + ")\n"
            "original.rename(preserved); original.mkdir()\n"
            "(original/'foreign').write_bytes(b'concurrently substituted object')"
        ),
    )
    result = _finalize(prepared, patch=patch)
    assert result.returncode != 0
    assert moved.exists()
    # The substitution is injected after the final source check. The native syscall
    # may move that foreign object; the post-readback must detect it and preserve
    # both objects without attempting a compensating move or deletion.
    foreign = list(prepared["release_parent"].rglob("foreign"))
    assert len(foreign) == 1
    assert foreign[0].read_bytes() == b"concurrently substituted object"
    assert foreign[0].parent == original or (
        substitution == "staging-object" and foreign[0].parent.parent == prepared["release_root"]
    )
    all_identities = list(prepared["release_parent"].rglob(IDENTITY))
    assert all_identities, "Original identity/staging evidence must survive ambiguous commit"
    for identity in all_identities:
        with pytest.raises(control.ReleaseControlError):
            _direct_validate(identity.parent)


@pytest.mark.parametrize("phase", ["before-rename", "after-rename", "before-terminal"])
def test_fsync_failure_does_not_authorize_public_candidate(
    prepared: dict[str, Any], phase: str
) -> None:
    marker = prepared["repository"].parent / "fsync-reached"
    arm = (
        "original_fsync=c.os.fsync\n"
        "def fail_once(descriptor):\n"
        " c.os.fsync=original_fsync\n"
        " Path(" + repr(str(marker)) + ").write_text('injected fsync error')\n"
        " raise OSError(errno.EIO,'injected fsync failure')\n"
        "c.os.fsync=fail_once"
    )
    if phase == "before-rename":
        patch = _wrap("_install_release_outputs", before=arm)
    elif phase == "after-rename":
        patch = _wrap("_rename_candidate_exclusive", after=arm)
    else:
        patch = _wrap("_complete_invocation", before=arm)
    assert _finalize(prepared, patch=patch).returncode != 0
    assert marker.is_file()
    for path in prepared["release_root"].glob("*/" + IDENTITY):
        with pytest.raises(control.ReleaseControlError):
            _direct_validate(path.parent)


@pytest.mark.parametrize(
    "point",
    [
        "before-identity",
        "after-identity-before-rename",
        "after-rename",
        "first-final-readback-before",
        "first-final-readback-after",
        "after-full-readback-before-stdout",
        "after-retained-stdout-before-terminal",
        "partial-terminal-write",
    ],
)
def test_supervisor_interruption_has_no_public_authority_or_recovery_reexecution(
    prepared: dict[str, Any],
    point: str,
) -> None:
    result = _finalize(prepared, patch=_kill_patch(point, prepared))
    assert result.returncode == -signal.SIGKILL, (point, result.stdout, result.stderr)
    assert not result.stdout, "Success must not be exposed before durable terminal validation"
    original = _snapshot(prepared["control"] / "001")
    staging = _snapshot(prepared["run"])
    destinations = _snapshot(prepared["release_root"])
    for path in prepared["release_root"].glob("*/" + IDENTITY):
        with pytest.raises(control.ReleaseControlError):
            _direct_validate(path.parent)
    recovery = _finalize(prepared, 2)
    assert recovery.returncode == 3, (recovery.stdout, recovery.stderr)
    assert not (prepared["control"] / "002/worker.pid").exists()
    _assert_preserved(original, prepared["control"] / "001")
    assert _snapshot(prepared["run"]) == staging
    assert _snapshot(prepared["release_root"]) == destinations
    terminal = control.read_json(prepared["control"] / "002/invocation.json")
    assert terminal["status"] == "BLOCKED" and terminal["data"]["outputs"] == []


def test_worker_kill_retains_cancellation_and_never_moves_candidate(
    prepared: dict[str, Any],
) -> None:
    patch = (
        "c._worker_command=lambda context:[sys.executable,'-c',"
        "'import os,signal; os.kill(os.getpid(),signal.SIGKILL)']\n"
    )
    result = _finalize(prepared, patch=patch)
    assert result.returncode == 128 + signal.SIGKILL
    assert not (prepared["run"] / IDENTITY).exists()
    assert list(prepared["release_root"].iterdir()) == []
    assert control.read_json(prepared["control"] / "001/invocation.json")["status"] == "CANCELLED"
    assert _finalize(prepared, 2).returncode == 3


def test_kill_after_valid_terminal_preserves_original_pass_without_second_finalization(
    prepared: dict[str, Any],
) -> None:
    result = _finalize(prepared, patch=_kill_patch("after-terminal", prepared))
    assert result.returncode == -signal.SIGKILL
    assert result.stdout == ""
    original = _snapshot(prepared["control"] / "001")
    terminal = control.read_json(prepared["control"] / "001/invocation.json")
    assert terminal["status"] == "PASS"
    candidate = next(prepared["release_root"].iterdir())
    _direct_validate(candidate)
    assert _finalize(prepared, 2).returncode == 3
    _assert_preserved(original, prepared["control"] / "001")
    _direct_validate(candidate)


@pytest.mark.parametrize(
    "state",
    ["staging-no-identity", "staging-exact-identity", "final-exact-identity", "both", "neither"],
)
def test_recovery_classifies_all_surviving_locations_without_mutation(
    prepared: dict[str, Any],
    state: str,
) -> None:
    point = (
        "before-identity"
        if state == "staging-no-identity"
        else "after-rename"
        if state in {"final-exact-identity", "both"}
        else "after-identity-before-rename"
    )
    assert _finalize(prepared, patch=_kill_patch(point, prepared)).returncode == -signal.SIGKILL
    if state == "both":
        candidate = next(prepared["release_root"].iterdir())
        shutil.copytree(candidate, prepared["run"], copy_function=shutil.copy2)
    elif state == "neither":
        prepared["run"].rename(prepared["run"].with_name("removed-from-both-protocol-locations"))
    original, staging, final = (
        _snapshot(prepared["control"] / "001"),
        _snapshot(prepared["run"]),
        _snapshot(prepared["release_root"]),
    )
    assert _finalize(prepared, 2).returncode == 3
    assert _snapshot(prepared["control"] / "001") == original
    assert _snapshot(prepared["run"]) == staging
    assert _snapshot(prepared["release_root"]) == final
    assert not (prepared["control"] / "002/worker.pid").exists()
    terminal = control.read_json(prepared["control"] / "002/invocation.json")
    assert terminal["status"] == "BLOCKED" and terminal["data"]["outputs"] == []


@pytest.mark.parametrize("form", ["absent", "partial", "malformed", "wrong-record", "unsafe"])
def test_raw_original_terminal_witness_is_preserved_and_never_backfilled(
    prepared: dict[str, Any],
    form: str,
) -> None:
    assert (
        _finalize(prepared, patch=_kill_patch("after-rename", prepared)).returncode
        == -signal.SIGKILL
    )
    path = prepared["control"] / "001/invocation.json"
    if form == "partial":
        path.write_bytes(b'{"schema_version":')
    elif form == "malformed":
        path.write_bytes(b"not a terminal record\x00")
    elif form == "wrong-record":
        path.write_bytes(control.canonical_json({"status": "PASS"}))
    elif form == "unsafe":
        path.symlink_to(prepared["run"] / "missing-outside.json")
    original = _snapshot(prepared["control"] / "001")
    assert _finalize(prepared, 2).returncode == 3
    assert _snapshot(prepared["control"] / "001") == original
    successor = prepared["control"] / "002"
    terminal = control.read_json(successor / "invocation.json")
    assert terminal["status"] == "BLOCKED" and terminal["data"]["outputs"] == []
    diagnostic = control.read_json(successor / "classification.json")
    assert diagnostic["original_terminal"]["disposition"] == (
        "ABSENT" if form == "absent" else "UNREADABLE" if form == "unsafe" else "INVALID_OR_PARTIAL"
    )
    assert diagnostic["original_terminal"]["witness"] == control._finalization_witness(path)
    if form in {"partial", "malformed", "wrong-record"}:
        retained = b"\n".join(
            p.read_bytes() for p in successor.iterdir() if p.is_file() and not p.is_symlink()
        )
        assert control.sha256_bytes(path.read_bytes()).encode() in retained
    candidate = next(prepared["release_root"].iterdir())
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)


@pytest.mark.parametrize(
    "point", ["after-reservation-before-intent", "before-intent-write", "partial-intent-write"]
)
def test_kill_during_original_reservation_retains_untrusted_intent_branch(
    prepared: dict[str, Any],
    point: str,
) -> None:
    assert _finalize(prepared, patch=_kill_patch(point, prepared)).returncode == -signal.SIGKILL
    original = _snapshot(prepared["control"] / "001")
    staging = _snapshot(prepared["run"])
    result = _finalize(prepared, 2)
    assert result.returncode == 3, (result.stdout, result.stderr)
    assert _snapshot(prepared["control"] / "001") == original
    assert _snapshot(prepared["run"]) == staging
    assert list(prepared["release_root"].iterdir()) == []
    successor = prepared["control"] / "002"
    assert not (successor / "worker.pid").exists()
    retained = b"\n".join(
        path.read_bytes()
        for path in successor.iterdir()
        if path.is_file() and not path.is_symlink()
    )
    assert b"UNTRUSTED_OR_INCOMPLETE_ORIGINAL_INTENT" in retained
    intent = control.read_json(successor / "intent.json")
    assert "candidate_digest" not in intent and "final_directory" not in intent
    terminal = control.read_json(successor / "invocation.json")
    assert terminal["status"] == "BLOCKED" and terminal["data"]["outputs"] == []


@pytest.mark.parametrize("form", ["malformed", "wrong-shape", "symlink", "fifo"])
def test_untrusted_original_intent_cannot_derive_identity_or_follow_unsafe_input(
    prepared: dict[str, Any],
    form: str,
) -> None:
    directory = prepared["control"] / "001"
    directory.mkdir(parents=True)
    path = directory / "intent.json"
    if form == "malformed":
        path.write_bytes(b"not an invocation intent")
    elif form == "wrong-shape":
        path.write_bytes(
            control.canonical_json({"candidate_digest": "a" * 64, "final_directory": "/untrusted"})
        )
    elif form == "symlink":
        path.symlink_to(prepared["repository"] / "pyproject.toml")
    else:
        os.mkfifo(path)
    original, staging = _snapshot(directory), _snapshot(prepared["run"])
    result = _finalize(prepared, 2)
    assert result.returncode == 3, (result.stdout, result.stderr)
    assert _snapshot(directory) == original
    assert _snapshot(prepared["run"]) == staging
    assert list(prepared["release_root"].iterdir()) == []
    successor = prepared["control"] / "002"
    assert not (successor / "worker.pid").exists()
    assert control.read_json(successor / "invocation.json")["data"]["outputs"] == []


@pytest.mark.parametrize(
    "subject,initial",
    [
        ("intent.json", "missing"),
        ("intent.json", "raw"),
        ("invocation.json", "missing"),
        ("invocation.json", "raw"),
    ],
)
def test_later_appearance_or_change_contradicts_predecessor_witness(
    prepared: dict[str, Any],
    subject: str,
    initial: str,
) -> None:
    point = "before-intent-write" if subject == "intent.json" else "after-rename"
    assert _finalize(prepared, patch=_kill_patch(point, prepared)).returncode == -signal.SIGKILL
    path = prepared["control"] / "001" / subject
    if initial == "raw":
        path.write_bytes(b"original raw invalid witness")
    assert _finalize(prepared, 2).returncode == 3
    successor = prepared["control"] / "002"
    before = _snapshot(successor)
    if path.exists():
        _replace(path, b"later changed original witness")
    else:
        path.write_bytes(b"later appeared original witness")
    with pytest.raises(control.ReleaseControlError):
        control._validate_terminal(control._validate_intent(successor))
    assert _finalize(prepared, 3).returncode == 3
    assert _snapshot(successor) == before
    assert not (prepared["control"] / "003/worker.pid").exists()
    latest = prepared["control"] / "003"
    terminal = control._validate_terminal(control._validate_intent(latest))
    assert terminal["status"] == "BLOCKED" and terminal["data"]["outputs"] == []
    diagnostic = control.read_json(latest / "classification.json")
    assert diagnostic["classification"] == "HISTORICAL_WITNESS_CONTRADICTION"
    assert diagnostic["history_consistency"] == "CONTRADICTED"
    assert diagnostic["contradicted_sequences"] == [2]
    with pytest.raises(control.ReleaseControlError):
        control._check_finalization_history(control._validate_intent(latest))


def _pure_inputs(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        control.read_json(fixture["run"] / name)
        for name in (
            "gate-input.json",
            "source-freeze.json",
            "predecessor.json",
            "artifact-manifest.json",
            "target-resolution.json",
        )
    ]


def _pure(
    fixture: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    intent_digest: str = "2" * 64,
    locator: str | None = None,
    no_evaluation_adoption: bool = True,
) -> dict[str, Any]:
    return control._build_candidate_identity_payload(
        *records,
        finalization_intent_digest=intent_digest,
        control_journal_locator=(
            str(fixture["control"] / "001/invocation.json") if locator is None else locator
        ),
        release_root=fixture["release_root"],
        no_evaluation_adoption=no_evaluation_adoption,
        live=False,
    )


def test_pure_builder_has_one_acyclic_identity_projection(prepared: dict[str, Any]) -> None:
    records = _pure_inputs(prepared)
    before = copy.deepcopy(records)
    one = _pure(prepared, records)
    two = _pure(prepared, copy.deepcopy(records))
    assert one == two and records == before
    assert set(one) == FIELDS
    expected = control.sha256_json(
        {k: v for k, v in one.items() if k not in {"candidate_digest", "final_directory"}}
    )
    assert expected == one["candidate_digest"]
    assert one["final_directory"] == str(prepared["release_root"] / expected)
    control._validate_candidate_identity_payload(
        one, expected_digest=expected, expected_milestone="v0.4"
    )
    for intent in [
        {"sequence": 1, "started_at": "2026-01-01T00:00:00Z"},
        {"sequence": 2, "started_at": "2026-01-01T00:00:00Z"},
        {"sequence": 1, "started_at": "2026-01-01T00:00:01Z"},
    ]:
        value = _pure(prepared, records, intent_digest=control.sha256_json(intent))
        assert value["candidate_digest"] != expected
    identities = {
        _pure(prepared, records, intent_digest=control.sha256_json(intent))["candidate_digest"]
        for intent in [
            {"sequence": 1, "started_at": "2026-01-01T00:00:00Z"},
            {"sequence": 2, "started_at": "2026-01-01T00:00:00Z"},
            {"sequence": 1, "started_at": "2026-01-01T00:00:01Z"},
        ]
    }
    assert len(identities) == 3


@pytest.mark.parametrize(
    "index,field,value",
    [
        (0, "target_resolution_digest", "0" * 64),
        (0, "milestone", "v0.5"),
        (1, "gate_input_digest", "0" * 64),
        (1, "milestone", "v0.5"),
        (1, "dirty", True),
        (1, "freeze_digest", "0" * 64),
        (3, "source_freeze_digest", "0" * 64),
        (3, "source_digest", "0" * 64),
        (3, "target_resolution_digest", "0" * 64),
        (3, "artifact_set_digest", "0" * 64),
        (3, "build_recipe_digest", "0" * 64),
        (3, "milestone", "v0.5"),
        (4, "selected_package_version", "v0.4.1"),
        (4, "selected_release_tag", "v0.4.1"),
        (4, "milestone", "v0.5"),
    ],
)
def test_pure_builder_rejects_rehashed_cross_record_mismatch(
    prepared: dict[str, Any],
    index: int,
    field: str,
    value: Any,
) -> None:
    records = _pure_inputs(prepared)
    record = records[index]
    records[index] = _remake(record, {**record["data"], field: value})
    with pytest.raises(control.ReleaseControlError):
        _pure(prepared, records)


@pytest.mark.parametrize(
    "field",
    [
        "chain_head",
        "predecessor_milestone",
        "qualification_digest",
        "reconciliation_digest",
        "pointer_envelope_digest",
        "pointer_index_receipt_digest",
    ],
)
def test_later_milestone_missing_chain_or_pointer_never_finalizes(
    tmp_path: Path, field: str
) -> None:
    fixture = _make_fixture(tmp_path, milestone="v0.5")
    path = fixture["run"] / "predecessor.json"
    record = control.read_json(path)
    data = copy.deepcopy(record["data"])
    del data[field]
    _replace(path, control.canonical_json(_remake(record, data)))
    assert _finalize(fixture).returncode != 0
    assert not (fixture["run"] / IDENTITY).exists()


def test_no_evaluation_adoption_is_explicit_and_not_a_default(prepared: dict[str, Any]) -> None:
    arguments = _finalize_argv(prepared)
    arguments.remove("--no-evaluation-adoption")
    assert _public(prepared, FINALIZER, arguments).returncode != 0
    with pytest.raises(control.ReleaseControlError):
        _pure(prepared, _pure_inputs(prepared), no_evaluation_adoption=False)


def test_stage_reference_shape_cannot_add_a_caller_selected_root(
    finalized: tuple[dict[str, Any], Path],
) -> None:
    fixture, candidate = finalized
    path = fixture["control"] / "001/invocation.json"
    record = control.read_json(path)
    data = copy.deepcopy(record["data"])
    data["outputs"][0]["root"] = "candidate"
    data["invocation_digest"] = control.sha256_json(
        {k: v for k, v in data.items() if k != "invocation_digest"}
    )
    _replace(path, control.canonical_json(_remake(record, data)))
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)


@pytest.mark.parametrize(
    "replacement",
    [
        "/candidate-identity.json",
        "../candidate-identity.json",
        "artifacts/candidate-identity.json",
        "alternate.json",
    ],
)
def test_external_terminal_output_is_exact_candidate_basename(
    finalized: tuple[dict[str, Any], Path],
    replacement: str,
) -> None:
    fixture, candidate = finalized
    path = fixture["control"] / "001/invocation.json"
    record = control.read_json(path)
    data = copy.deepcopy(record["data"])
    data["outputs"][0]["path"] = replacement
    data["invocation_digest"] = control.sha256_json(
        {k: v for k, v in data.items() if k != "invocation_digest"}
    )
    _replace(path, control.canonical_json(_remake(record, data)))
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)


def test_candidate_payload_cannot_move_its_own_validation_root(
    finalized: tuple[dict[str, Any], Path],
) -> None:
    fixture, candidate = finalized
    moved = candidate.with_name("f" * 64)
    candidate.rename(moved)
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(moved)
    assert _validate(fixture, moved).returncode != 0


def test_run_binding_changed_after_freeze_does_not_supply_another_control_root(
    prepared: dict[str, Any],
) -> None:
    path = prepared["run"] / "gate-input.json"
    record = control.read_json(path)
    data = {**record["data"], "run_id": "another-run"}
    data["gate_input_digest"] = control.sha256_json(
        {key: value for key, value in data.items() if key != "gate_input_digest"}
    )
    _replace(path, control.canonical_json(_remake(record, data)))
    assert _finalize(prepared).returncode != 0
    assert not (prepared["run"] / IDENTITY).exists()


def test_original_intent_cannot_choose_arbitrary_context_discriminator(
    prepared: dict[str, Any],
) -> None:
    assert (
        _finalize(prepared, patch=_kill_patch("before-identity", prepared)).returncode
        == -signal.SIGKILL
    )
    path = prepared["control"] / "001/intent.json"
    intent = control.read_json(path)
    intent["unrecognized_root"] = str(prepared["release_root"])
    intent["invocation_id"] = control._intent_identity(intent)
    _replace(path, control.canonical_json(intent))
    before = _snapshot(prepared["run"])
    assert _finalize(prepared, 2).returncode == 3
    assert _snapshot(prepared["run"]) == before
    assert not (prepared["control"] / "002/worker.pid").exists()


@pytest.mark.parametrize("mutation", ["changed-input", "extra-root", "extra-artifact"])
def test_commit_inventory_must_match_before_later_append_rules_apply(
    prepared: dict[str, Any],
    mutation: str,
) -> None:
    if mutation == "changed-input":
        patch = _wrap(
            "_install_release_outputs",
            before=(
                "path=Path(" + repr(str(prepared["run"] / "predecessor.json")) + ")\n"
                "path.chmod(0o600); path.write_bytes(path.read_bytes()+b'changed after worker'); path.chmod(0o400)"
            ),
        )
    else:
        name = "unplanned.json" if mutation == "extra-root" else "artifacts/unplanned.whl"
        patch = _wrap(
            "_rename_candidate_exclusive",
            after=(
                "destination=Path(" + repr(str(prepared["release_root"])) + ")/args[3]\n"
                "(destination/" + repr(name) + ").write_bytes(b'extra at exact commit readback')"
            ),
        )
    result = _finalize(prepared, patch=patch)
    assert result.returncode != 0
    for identity in prepared["release_root"].glob("*/" + IDENTITY):
        with pytest.raises(control.ReleaseControlError):
            _direct_validate(identity.parent)
    original = _snapshot(prepared["control"] / "001")
    staging, final = _snapshot(prepared["run"]), _snapshot(prepared["release_root"])
    assert _finalize(prepared, 2).returncode == 3
    assert _snapshot(prepared["control"] / "001") == original
    assert _snapshot(prepared["run"]) == staging
    assert _snapshot(prepared["release_root"]) == final


def test_worker_success_shaped_diagnostic_does_not_authorize_finalization(
    prepared: dict[str, Any],
) -> None:
    worker = (
        "import os,sys; from metriplane import release_control as c; "
        "print(c.canonical_json({'status':'PASS','candidate_id':'forged-worker-id',"
        "'candidate_dir':'/forged','identity_record':'/forged/candidate-identity.json'}).decode(),flush=True); "
        "raise SystemExit(3)"
    )
    patch = "c._worker_command=lambda context:[sys.executable,'-c'," + repr(worker) + "]\n"
    result = _finalize(prepared, patch=patch)
    assert result.returncode != 0
    assert "forged-worker-id" not in result.stdout
    assert not (prepared["run"] / IDENTITY).exists()
    assert list(prepared["release_root"].iterdir()) == []
    journal = prepared["control"] / "001"
    assert b"forged-worker-id" in (journal / "stdout").read_bytes()
    terminal = control.read_json(journal / "invocation.json")
    assert terminal["status"] != "PASS" and terminal["data"]["outputs"] == []


def test_corrupt_staged_identity_cannot_reach_native_commit(prepared: dict[str, Any]) -> None:
    marker = prepared["repository"].parent / "forbidden-native-commit"
    patch = _wrap(
        "_verify_staged_outputs",
        before=(
            "context=args[0]\n"
            "paths=list((context.directory/'staged').rglob('candidate-identity.json'))\n"
            "assert len(paths)==1\n"
            "path=paths[0]; path.chmod(0o600); path.write_bytes(path.read_bytes()+b'tamper'); path.chmod(0o400)"
        ),
    )
    patch += _wrap(
        "_rename_candidate_exclusive",
        before="Path(" + repr(str(marker)) + ").write_text('native boundary was reached')",
    )
    result = _finalize(prepared, patch=patch)
    assert result.returncode != 0
    assert not marker.exists()
    assert not (prepared["run"] / IDENTITY).exists()
    assert list(prepared["release_root"].iterdir()) == []


def test_active_validator_exception_requires_its_exact_declared_record(
    finalized: tuple[dict[str, Any], Path],
) -> None:
    fixture, candidate = finalized
    # The current caller has a lawful stage/sequence but an unrelated record path.
    arguments = _validator_argv(candidate)
    arguments[arguments.index("--record") + 1] = str(candidate / "artifact-manifest.json")
    assert _public(fixture, VALIDATOR, arguments).returncode != 0
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)


@pytest.mark.parametrize(
    "point", ["before-computation", "after-computation", "after-staged-identity"]
)
def test_actual_finalization_worker_interruption_never_commits(
    prepared: dict[str, Any],
    point: str,
) -> None:
    kill = "os.kill(os.getpid(),signal.SIGKILL)"
    if point == "after-staged-identity":
        worker_patch = _wrap(
            "_durable_json",
            after="if Path(args[0]).name=='candidate-identity.json':\n " + kill,
        )
    else:
        worker_patch = _wrap(
            "_candidate_identity_for_context",
            before=kill if point == "before-computation" else "",
            after=kill if point == "after-computation" else "",
        )
    worker = (
        "import os,sys,signal; from pathlib import Path\n"
        "from metriplane import release_control as c\n"
        + worker_patch
        + "raise SystemExit(c._release_worker_main(sys.argv[1]))\n"
    )
    patch = (
        "c._worker_command=lambda context:[sys.executable,'-c',"
        + repr(worker)
        + ",str(context.directory)]\n"
    )
    result = _finalize(prepared, patch=patch)
    assert result.returncode == 128 + signal.SIGKILL, (result.stdout, result.stderr)
    assert not (prepared["run"] / IDENTITY).exists()
    assert list(prepared["release_root"].iterdir()) == []
    journal = prepared["control"] / "001"
    assert control.read_json(journal / "invocation.json")["status"] == "CANCELLED"
    if point == "after-staged-identity":
        assert list((journal / "staged").rglob(IDENTITY))
    before = _snapshot(journal)
    assert _finalize(prepared, 2).returncode == 3
    assert _snapshot(journal) == before
    assert not (prepared["control"] / "002/worker.pid").exists()


@pytest.mark.parametrize("fault", ["absent", "partial", "tampered", "symlink"])
def test_public_candidate_requires_original_terminal_commit_receipt(
    finalized: tuple[dict[str, Any], Path],
    fault: str,
) -> None:
    fixture, candidate = finalized
    path = fixture["control"] / "001/terminal-commit.json"
    original = path.read_bytes()
    if fault in {"absent", "symlink"}:
        path.unlink()
        if fault == "symlink":
            other = fixture["repository"].parent / "other-terminal-commit.json"
            other.write_bytes(original)
            path.symlink_to(other)
    elif fault == "partial":
        _replace(path, b'{"incomplete":')
    else:
        value = json.loads(original)
        value["unrecognized"] = True
        _replace(path, control.canonical_json(value))
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)
    assert _validate(fixture, candidate).returncode != 0


def test_late_terminal_commit_receipt_contradicts_blocked_recovery_witness(
    finalized: tuple[dict[str, Any], Path],
) -> None:
    fixture, candidate = finalized
    receipt = fixture["control"] / "001/terminal-commit.json"
    raw = receipt.read_bytes()
    receipt.unlink()
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)
    assert _finalize(fixture, 2).returncode == 3
    successor = fixture["control"] / "002"
    before = _snapshot(successor)
    receipt.write_bytes(raw)
    receipt.chmod(0o400)
    with pytest.raises(control.ReleaseControlError):
        control._validate_terminal(control._validate_intent(successor))
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)
    assert _finalize(fixture, 3).returncode == 3
    assert _snapshot(successor) == before
    latest = fixture["control"] / "003"
    terminal = control._validate_terminal(control._validate_intent(latest))
    assert terminal["status"] == "BLOCKED" and terminal["data"]["outputs"] == []
    diagnostic = control.read_json(latest / "classification.json")
    assert diagnostic["history_consistency"] == "CONTRADICTED"
    assert diagnostic["contradicted_sequences"] == [2]
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)


def test_existing_readiness_bootstrap_label_has_exact_v030_predecessor(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path, bootstrap_predecessor="v0.3")
    candidate = _success(fixture, _finalize(fixture))
    assert _validate(fixture, candidate).returncode == 0
    assert control.read_json(candidate / "predecessor.json")["data"]["version"] == "v0.3.0"


@pytest.mark.parametrize("stage", ["source-freeze", "artifact-build"])
@pytest.mark.parametrize("fault", ["missing-terminal", "failed-terminal", "changed-diagnostic"])
def test_s1_producer_completion_is_required_before_candidate_commit(
    prepared: dict[str, Any],
    stage: str,
    fault: str,
) -> None:
    directory = prepared["run"] / "invocations" / stage / "001"
    path = directory / "invocation.json"
    if fault == "missing-terminal":
        path.unlink()
    elif fault == "changed-diagnostic":
        _replace(directory / "stderr", b"altered S1 producer diagnostic")
    else:
        record = control.read_json(path)
        data = {**record["data"], "exit_code": 3, "terminal_status": "BLOCKED", "outputs": []}
        data["invocation_digest"] = control.sha256_json(
            {key: value for key, value in data.items() if key != "invocation_digest"}
        )
        record["status"] = "BLOCKED"
        _replace(path, control.canonical_json(_remake(record, data)))
    assert _finalize(prepared).returncode != 0
    assert not (prepared["run"] / IDENTITY).exists()
    assert list(prepared["release_root"].iterdir()) == []


def test_terminal_commit_receipt_cannot_be_replayed_from_another_original(tmp_path: Path) -> None:
    first, second = _make_fixture(tmp_path / "first"), _make_fixture(tmp_path / "second")
    candidate = _success(first, _finalize(first))
    _success(second, _finalize(second))
    first_receipt = first["control"] / "001/terminal-commit.json"
    second_receipt = second["control"] / "001/terminal-commit.json"
    assert first_receipt.read_bytes() != second_receipt.read_bytes()
    _replace(first_receipt, second_receipt.read_bytes())
    with pytest.raises(control.ReleaseControlError):
        _direct_validate(candidate)
    assert _validate(first, candidate).returncode != 0


@pytest.mark.parametrize("fault", ["prelaunch", "before-worker-pid"])
def test_completed_early_negative_validator_journal_remains_replayable(
    finalized: tuple[dict[str, Any], Path],
    fault: str,
) -> None:
    fixture, candidate = finalized
    if fault == "prelaunch":
        patch = "c._worker_command=lambda context:['/no-such-metriplane-worker-executable']\n"
        expected = "BLOCKED"
    else:
        patch = (
            "c._worker_command=lambda context:[sys.executable,'-c',"
            "'import os,signal; os.kill(os.getpid(),signal.SIGKILL)']\n"
        )
        expected = "CANCELLED"
    result = _public(fixture, VALIDATOR, _validator_argv(candidate), patch=patch)
    assert result.returncode != 0
    directory = candidate / "invocations/validate-release-candidate-identity/001"
    terminal = control._validate_terminal(control._validate_intent(directory))
    assert terminal["status"] == expected and terminal["data"]["outputs"] == []
    assert not (directory / "worker.pid").exists()
    assert not (directory / "worker-result.json").exists()
    _direct_validate(candidate)
    assert _validate(fixture, candidate, 2).returncode == 0


def test_identity_creation_uses_original_held_staging_object(prepared: dict[str, Any]) -> None:
    source = prepared["run"]
    preserved = source.with_name(source.name + "-preserved")
    foreign = prepared["repository"].parent / "foreign-identity-target"
    foreign.mkdir()
    (foreign / "retained").write_bytes(b"foreign bytes")
    original = _snapshot(source)
    patch = _wrap(
        "_durable_candidate_identity",
        before=(
            "source=Path(" + repr(str(source)) + "); "
            "source.rename(Path(" + repr(str(preserved)) + ")); "
            "source.symlink_to(Path(" + repr(str(foreign)) + "),target_is_directory=True)"
        ),
    )
    result = _finalize(prepared, patch=patch)
    assert result.returncode != 0 and not result.stdout.startswith('{"candidate_dir"')
    assert (foreign / "retained").read_bytes() == b"foreign bytes"
    assert not (foreign / IDENTITY).exists()
    assert (preserved / IDENTITY).is_file()
    for name, entry in original.items():
        assert _snapshot(preserved)[name] == entry
    assert list(prepared["release_root"].iterdir()) == []


def test_candidate_fsync_never_traverses_substituted_intermediate_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, foreign = tmp_path / "candidate", tmp_path / "foreign"
    nested = root / "nested"
    nested.mkdir(parents=True)
    foreign.mkdir()
    (nested / "member").write_bytes(b"candidate")
    foreign_file = foreign / "member"
    foreign_file.write_bytes(b"unrelated")
    foreign_identity = (foreign_file.stat().st_dev, foreign_file.stat().st_ino)
    original_open, original_fsync = os.open, os.fsync
    changed = False
    flushed = []

    def substitute(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal changed
        if path == "nested" and "dir_fd" in kwargs and not changed:
            changed = True
            nested.rename(root / "preserved")
            nested.symlink_to(foreign, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    def observe(descriptor: int) -> None:
        info = os.fstat(descriptor)
        flushed.append((info.st_dev, info.st_ino))
        original_fsync(descriptor)

    root_fd = control._candidate_open_directory(root)
    expected_identity = control._release_object_identity(root)
    inventory = control._candidate_inventory(root)
    monkeypatch.setattr(os, "open", substitute)
    monkeypatch.setattr(os, "fsync", observe)
    try:
        with pytest.raises((OSError, control.ReleaseControlError)):
            control._fsync_candidate_tree(
                root, directory_fd=root_fd, expected_identity=expected_identity, inventory=inventory
            )
    finally:
        os.close(root_fd)
    assert changed and foreign_identity not in flushed
    assert foreign_file.read_bytes() == b"unrelated"


def test_opaque_witness_stops_before_inspecting_unsafe_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "forbidden-leaf").write_bytes(b"never inspected")
    blocker = tmp_path / "unsafe"
    blocker.symlink_to(foreign, target_is_directory=True)
    identity = blocker.lstat()
    original_stat = os.stat

    def guarded(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        assert path != "forbidden-leaf", "witness inspected beyond the unsafe ancestor"
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", guarded)
    witness = control._finalization_witness(blocker / "forbidden-leaf")
    assert witness["state"] == "UNREADABLE"
    assert witness["object"]["inode"] == identity.st_ino
    assert witness["object"]["mode"] == identity.st_mode


@pytest.mark.parametrize("fault", ["post-worker-verification", "killed-after-worker-result"])
def test_completed_negative_validator_can_retain_earlier_worker_success(
    finalized: tuple[dict[str, Any], Path],
    fault: str,
) -> None:
    fixture, candidate = finalized
    if fault == "post-worker-verification":
        patch = _wrap("_verify_staged_outputs", before="raise OSError('injected readback error')")
        expected = "BLOCKED"
    else:
        worker_patch = _wrap(
            "_durable_json",
            after=(
                "if Path(args[0]).name=='worker-result.json':\n os.kill(os.getpid(),signal.SIGKILL)"
            ),
        )
        patch = (
            "original_command=c._worker_command\n"
            "def kill_after_result(context):\n"
            " command=original_command(context)\n"
            " bootstrap=command[2]\n"
            " command[2]='import os,sys,signal; from pathlib import Path; "
            "from metriplane import release_control as c\\n'+"
            + repr(worker_patch)
            + "+'\\n'+bootstrap\n"
            " return command\nc._worker_command=kill_after_result\n"
        )
        expected = "CANCELLED"
    result = _public(fixture, VALIDATOR, _validator_argv(candidate), patch=patch)
    assert result.returncode != 0, (result.stdout, result.stderr)
    directory = candidate / "invocations/validate-release-candidate-identity/001"
    terminal = control._validate_terminal(control._validate_intent(directory))
    assert terminal["status"] == expected and terminal["data"]["outputs"] == []
    assert control.read_json(directory / "worker-result.json")["exit_code"] == 0
    _direct_validate(candidate)
    assert _validate(fixture, candidate, 2).returncode == 0


@pytest.mark.parametrize("subject", ["candidate", "control"])
def test_fsync_entry_rejects_replacement_of_previously_bound_root(
    prepared: dict[str, Any],
    subject: str,
) -> None:
    foreign = prepared["repository"].parent / "foreign-root-at-fsync"
    foreign.mkdir()
    (foreign / "foreign-payload").write_bytes(b"unrelated durable object")
    foreign_identity = (foreign.stat().st_dev, foreign.stat().st_ino)
    marker = foreign.parent / "foreign-root-flushed"
    patch = (
        "original_fsync=os.fsync\n"
        "def observed_fsync(fd):\n"
        " info=os.fstat(fd)\n"
        " if (info.st_dev,info.st_ino)==" + repr(foreign_identity) + ":\n"
        "  Path(" + repr(str(marker)) + ").write_text('foreign root was flushed')\n"
        " return original_fsync(fd)\nos.fsync=observed_fsync\n"
    )
    condition = (
        "root.parent==Path(" + repr(str(prepared["release_root"])) + ")"
        if subject == "candidate"
        else "root==Path(" + repr(str(prepared["control"].parents[1])) + ")"
    )
    patch += _wrap(
        "_fsync_candidate_tree",
        before=(
            "root=Path(args[0])\nif " + condition + ":\n"
            " root.rename(root.with_name(root.name+'-preserved'))\n"
            " Path(" + repr(str(foreign)) + ").rename(root)"
        ),
    )
    result = _finalize(prepared, patch=patch)
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert not marker.exists()
    # The injected substitution remains in place; the supervisor never rolls it back.
    if subject == "candidate":
        originals = list(prepared["release_root"].glob("*-preserved/" + IDENTITY))
        assert len(originals) == 1
    else:
        root = prepared["control"].parents[1]
        assert (
            root.with_name(root.name + "-preserved")
            / "invocations/candidate-finalization/001/intent.json"
        ).is_file()
