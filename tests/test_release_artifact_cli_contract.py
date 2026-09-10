# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from metriplane import release_control as control
from tools import build_release_artifacts as artifact_cli
from test_release_source_freeze import (
    ROOT,
    export_schema_records,
    freeze_argv,
    make_source_fixture,
    run_cli,
)


def _record_inputs(root: Path) -> dict[str, Any]:
    fixture = make_source_fixture(root)
    result = run_cli(fixture, "freeze_release_source.py", freeze_argv(fixture))
    assert result.returncode == 0, (result.stdout, result.stderr)
    return fixture


def _argv(fixture: dict[str, Any], sequence: int = 1) -> list[str]:
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
        str(run / "invocations/artifact-build" / f"{sequence:03d}"),
    ]


def _bootstrap(*, worker_patch: str = "", parent_patch: str = "") -> str:
    worker = (
        worker_patch
        + "\nimport sys; from metriplane.release_control import _release_worker_main; raise SystemExit(_release_worker_main(sys.argv[1]))"
    )
    return (
        "import os,sys; from pathlib import Path; from metriplane import release_control as c; original_cwd=os.getcwd(); os.chdir(Path(c.__file__).resolve().parents[1]); from tools import build_release_artifacts as a; os.chdir(original_cwd)\n"
        + "c._worker_command=lambda context: [sys.executable, '-c', "
        + repr(worker)
        + ", str(context.directory)]\n"
        + parent_patch
        + "\nraise SystemExit(a.main(sys.argv[2:]))"
    )


def _run_build(
    fixture: dict[str, Any],
    *,
    bootstrap: str | None = None,
    sequence: int = 1,
    fixture_mode: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_cli(
        fixture,
        "build_release_artifacts.py",
        _argv(fixture, sequence),
        bootstrap=bootstrap,
        fixture_mode=fixture_mode,
    )


def _terminal(fixture: dict[str, Any], sequence: int = 1) -> dict[str, Any]:
    return control.read_json(
        fixture["run"] / "invocations/artifact-build" / f"{sequence:03d}" / "invocation.json"
    )


def test_section_9b_parser_accepts_only_the_exact_artifact_form(tmp_path: Path) -> None:
    parsed = artifact_cli._parse_args(_argv({"run": tmp_path}))
    assert set(vars(parsed)) == {
        "manifest",
        "out_dir",
        "source_freeze",
        "target_resolution",
        "invocation_dir",
        "provider_attestation_keyring",
        "provider_attestation_keyring_digest",
        "authority_policy_digest",
    }
    result = subprocess.run(
        [sys.executable, "tools/build_release_artifacts.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    for flag in (
        "--target-resolution",
        "--source-freeze",
        "--out-dir",
        "--manifest",
        "--invocation-dir",
        "--provider-attestation-keyring",
        "--provider-attestation-keyring-digest",
        "--authority-policy-digest",
    ):
        assert flag in result.stdout
    assert "intentionally unsupported" in result.stdout


def test_artifact_compatibility_parser_retains_all_trust_flags(tmp_path: Path) -> None:
    keyring = str(tmp_path / "original keyring.json")
    parsed = artifact_cli._parse_args(
        [
            *_argv({"run": tmp_path}),
            "--provider-attestation-keyring",
            keyring,
            "--provider-attestation-keyring-digest",
            "a" * 64,
            "--authority-policy-digest",
            "b" * 64,
        ]
    )
    assert parsed.provider_attestation_keyring == keyring
    assert parsed.provider_attestation_keyring_digest == "a" * 64
    assert parsed.authority_policy_digest == "b" * 64


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--provider-attestation-keyring", " "),
        ("--provider-attestation-keyring-digest", ""),
        ("--provider-attestation-keyring-digest", "A" * 64),
        ("--provider-attestation-keyring-digest", "a" * 64 + "\n"),
        ("--authority-policy-digest", "bad"),
        ("--authority-policy-digest", "b" * 63),
        ("--authority-policy", "b" * 64),
    ],
)
def test_artifact_compatibility_parser_rejects_invalid_trust_flags(
    tmp_path: Path, flag: str, value: str
) -> None:
    with pytest.raises(SystemExit) as error:
        artifact_cli._parse_args([*_argv({"run": tmp_path}), flag, value])
    assert error.value.code == 2


def _artifact_compatibility_inputs(
    tmp_path: Path, *, version: object = "v0.4.1", tag: object = "v0.4.1", synthetic: bool = True
) -> tuple[Path, Path]:
    # Loader seam only. The target is the complete current schema shape, while
    # the source remains a minimal validator seam. Neither claims native proof.
    target_data = {
        "burn_lineage_digest": "3" * 64,
        "burn_target_ids": [],
        "initial_package_version": "v0.4.1",
        "initial_release_tag": "v0.4.1",
        "milestone": "v0.4",
        "observations_digest": "4" * 64,
        "prior_burn_digests": [],
        "release_context_digest": "5" * 64,
        "requires_new_burn": False,
        "resolution_rule": "owner_approved_exact_target",
        "selected_package_version": version,
        "selected_release_tag": tag,
        "producer_intent_digest": "6" * 64,
        "invocation_root_locator": "invocations",
    }
    target_data["resolution_digest"] = control.sha256_json(target_data)
    target = control.make_record(
        "release-target-resolution",
        target_data,
        invocation_id="synthetic-adapter-target",
        sequence=1,
        synthetic=synthetic,
    )
    source = control.make_record(
        "release-source-freeze",
        {
            "milestone": "v0.4",
            "dirty": False,
            "source_sha": "a" * 40,
            "source_tree": "b" * 40,
            "freeze_digest": "c" * 64,
            "build_recipe_digest": artifact_cli.BUILD_RECIPE_DIGEST,
        },
        invocation_id="synthetic-adapter-source",
        sequence=1,
        synthetic=synthetic,
    )
    target_path, source_path = tmp_path / "target-resolution.json", tmp_path / "source-freeze.json"
    target_path.write_bytes(control.canonical_json(target))
    source_path.write_bytes(control.canonical_json(source))
    return target_path, source_path


@pytest.mark.parametrize("fixture_mode", [False, True])
def test_artifact_compatibility_loader_passes_actual_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_mode: bool
) -> None:
    target, source = _artifact_compatibility_inputs(tmp_path, synthetic=fixture_mode)
    original_target = target.read_bytes()
    verifier = control.ProviderAttestationVerifier(
        keys={("github", "synthetic-key-owner"): bytes.fromhex("a" * 64)},
        keyring_digest="d" * 64,
    )
    calls = []

    def capture(record: dict[str, Any], path: Path, **kwargs: Any) -> None:
        calls.append((record, path, kwargs))

    monkeypatch.setattr(artifact_cli, "validate_release_source_freeze_record", capture)
    inputs = artifact_cli._load_inputs(
        target,
        source,
        fixture_mode=fixture_mode,
        repository=tmp_path,
        attestation_verifier=verifier,
    )
    assert inputs.package_version == "0.4.1" and inputs.release_tag == "v0.4.1"
    assert inputs.target_resolution["data"]["selected_package_version"] == "v0.4.1"
    assert target.read_bytes() == original_target
    assert len(calls) == 1
    assert calls[0][0] == control.read_json(source) and calls[0][1] == source.absolute()
    assert calls[0][2] == {
        "repository": tmp_path,
        "live": not fixture_mode,
        "attestation_verifier": verifier,
    }
    assert calls[0][2]["attestation_verifier"] is verifier


@pytest.mark.parametrize(
    ("version", "tag"),
    [
        ("0.4.1", "v0.4.1"),
        ("vv0.4.1", "vv0.4.1"),
        ("v0.4.01", "v0.4.01"),
        ("v0.4.1.post0", "v0.4.1.post0"),
        ("v0.4.1.post2", "v0.4.1.post2"),
        ("v0.4.１", "v0.4.１"),
        ("v0.4.1\n", "v0.4.1\n"),
        ("v0.4.1", "0.4.1"),
        ("v0.4.1", "v0.4.2"),
        ("v0.5.0", "v0.5.0"),
        (None, "v0.4.1"),
        ("v0.4.1", None),
    ],
)
def test_artifact_compatibility_loader_rejects_version_aliases_before_source_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: object, tag: object
) -> None:
    target, source = _artifact_compatibility_inputs(tmp_path, version=version, tag=tag)

    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("invalid target reached source validation")

    monkeypatch.setattr(artifact_cli, "validate_release_source_freeze_record", unexpected)
    with pytest.raises(artifact_cli.ArtifactBuildBlocked):
        artifact_cli._load_inputs(target, source, fixture_mode=True, repository=tmp_path)


def test_artifact_compatibility_loader_does_not_drop_authority_policy(tmp_path: Path) -> None:
    # Until the controller accepts/replays this identity, explicit policy input
    # must block rather than be accepted and silently ignored.
    with pytest.raises(artifact_cli.ArtifactBuildBlocked, match="authority-policy replay hook"):
        artifact_cli._load_inputs(
            tmp_path / "target-resolution.json",
            tmp_path / "source-freeze.json",
            fixture_mode=False,
            repository=tmp_path,
            expected_authority_policy_digest="a" * 64,
        )


def test_artifact_compatibility_loader_preserves_source_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, source = _artifact_compatibility_inputs(tmp_path)

    def reject(*args: Any, **kwargs: Any) -> None:
        raise control.ReleaseControlError("original source proof is invalid")

    monkeypatch.setattr(artifact_cli, "validate_release_source_freeze_record", reject)
    with pytest.raises(control.ReleaseControlError, match="original source proof is invalid"):
        artifact_cli._load_inputs(target, source, fixture_mode=True, repository=tmp_path)


@pytest.mark.parametrize("binding", ["valid", "wrong-digest", "missing-digest", "digest-only"])
def test_artifact_compatibility_direct_verifier_parser_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, binding: str
) -> None:
    keyring = {
        "schema_version": "metriplane.provider-attestation-keyring.v1",
        "keys": [
            {"provider": "github", "actor_id": "synthetic-key-owner", "public_key_hex": "a" * 64}
        ],
    }
    keyring_path = tmp_path / "original-keyring.json"
    keyring_path.write_bytes(control.canonical_json(keyring))
    extra = ["--authority-policy-digest", "b" * 64]
    if binding != "digest-only":
        extra += ["--provider-attestation-keyring", str(keyring_path)]
    if binding != "missing-digest":
        extra += [
            "--provider-attestation-keyring-digest",
            "0" * 64 if binding == "wrong-digest" else control.sha256_json(keyring),
        ]
    args = artifact_cli._parse_args([*_argv({"run": tmp_path}), *extra])
    # Direct parser seam only; the production adapter always supplies its actual
    # reserved context, whose captured input rules are tested below.
    if binding == "valid":
        verifier = control._attestation_verifier_from_args(args, live=True)
        assert isinstance(verifier, control.ProviderAttestationVerifier)
        assert verifier.keyring_digest == control.sha256_json(keyring)
        assert verifier.keys == {("github", "synthetic-key-owner"): bytes.fromhex("a" * 64)}
    else:
        with pytest.raises(control.ReleaseControlError):
            control._attestation_verifier_from_args(args, live=True)
    assert not (tmp_path / "artifacts").exists()
    assert not args.invocation_dir.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--target-resolution", ""],
        ["--dist", "dist", "--version", "0.4.0", "--output", "manifest.json"],
        ["--not-a-section-9b-flag", "value"],
    ],
)
def test_section_9b_parser_rejects_missing_blank_legacy_and_unknown_flags(
    arguments: list[str],
) -> None:
    result = subprocess.run(
        [sys.executable, "tools/build_release_artifacts.py", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def _deterministic_build_patch() -> str:
    # An instrumented build isolates manifest determinism. The separate real
    # pinned-build test below covers the archive/backend/metadata boundary.
    return """import gzip,io,tarfile
from tools import build_release_artifacts as a
from tools.release_artifacts import _REQUIRED_SDIST_PATHS
def deterministic(source_dir,dist_dir,**kwargs):
 (dist_dir/'metriplane-0.4.0-py3-none-any.whl').write_bytes(b'synthetic deterministic wheel')
 stream=io.BytesIO()
 with tarfile.open(fileobj=stream,mode='w',format=tarfile.USTAR_FORMAT) as archive:
  for name in sorted(_REQUIRED_SDIST_PATHS):
   payload=(source_dir/name).read_bytes()
   info=tarfile.TarInfo('metriplane-0.4.0/'+name); info.mode=0o644; info.mtime=0; info.size=len(payload)
   archive.addfile(info,io.BytesIO(payload))
 with (dist_dir/'metriplane-0.4.0.tar.gz').open('wb') as raw:
  with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed: compressed.write(stream.getvalue())
a._run_build=deterministic"""


def test_fixture_build_is_deterministic_digest_bound_and_no_overwrite(tmp_path: Path) -> None:
    fixtures = [_record_inputs(tmp_path / name) for name in ("first", "second", "third")]
    for fixture in fixtures:
        result = _run_build(
            fixture, bootstrap=_bootstrap(worker_patch=_deterministic_build_patch())
        )
        assert result.returncode == 0, (
            result.stdout,
            result.stderr,
            (fixture["run"] / "invocations/artifact-build/001/stderr").read_text(),
        )
    first, second, third = (f["run"] for f in fixtures)
    expected_artifacts = {p.name: p.read_bytes() for p in (first / "artifacts").iterdir()}
    for run in (second, third):
        assert expected_artifacts == {p.name: p.read_bytes() for p in (run / "artifacts").iterdir()}
    record = control.read_json(first / "artifact-manifest.json")
    other = control.read_json(second / "artifact-manifest.json")
    last = control.read_json(third / "artifact-manifest.json")
    assert (
        record["data"]["artifact_set_digest"]
        == other["data"]["artifact_set_digest"]
        == last["data"]["artifact_set_digest"]
    )
    # Invocation-specific provenance must differ even when reproducible artifact bytes agree.
    assert len({record["invocation_id"], other["invocation_id"], last["invocation_id"]}) == 3
    assert set(record["data"]) == {
        "artifact_set_digest",
        "artifacts",
        "build_invocation_id",
        "build_recipe_digest",
        "milestone",
        "source_digest",
        "source_freeze_digest",
        "target_resolution_digest",
        "invocation_root_locator",
        "producer_intent_digest",
    }
    assert record["synthetic"] is True
    assert all(p.stat().st_mode & 0o222 == 0 for p in (first / "artifacts").iterdir())
    assert str(tmp_path) not in (first / "artifact-manifest.json").read_text()
    control.validate_release_artifact_files(record, first / "artifacts", live=False)
    result = run_cli(
        fixtures[0],
        "validate_release_artifact_manifest.py",
        [
            "--record",
            str(first / "artifact-manifest.json"),
            "--artifacts",
            str(first / "artifacts"),
            "--read-hash",
            "--invocation-dir",
            str(first / "invocations/artifact-manifest-validation/001"),
        ],
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    export_schema_records(tmp_path / "schema-cases", [first / "artifact-manifest.json"])
    original = {str(p.relative_to(first)): p.read_bytes() for p in first.rglob("*") if p.is_file()}
    assert _run_build(fixtures[0]).returncode == 2
    assert {
        str(p.relative_to(first)): p.read_bytes() for p in first.rglob("*") if p.is_file()
    } == original
    assert _run_build(fixtures[0], sequence=2).returncode == 3
    assert not (first / "invocations/artifact-build/002/worker.pid").exists()
    assert _terminal(fixtures[0], 2)["data"]["previous_invocation_digest"] == control.sha256_bytes(
        original["invocations/artifact-build/001/invocation.json"]
    )


def test_synthetic_inputs_are_blocked_without_fixture_authority(tmp_path: Path) -> None:
    fixture = _record_inputs(tmp_path)
    result = _run_build(fixture, fixture_mode=False)
    assert result.returncode == 3
    assert "fixture mode" in (fixture["run"] / "invocations/artifact-build/001/stderr").read_text()
    assert not (fixture["run"] / "artifacts").exists()
    assert not (fixture["run"] / "artifact-manifest.json").exists()


@pytest.mark.parametrize(
    ("source_synthetic", "source_overrides", "target_overrides", "reason"),
    [
        (False, {}, {}, "authority modes differ"),
        (True, {"dirty": True}, {}, "clean tree"),
        (True, {"milestone": "v0.5"}, {}, "milestones differ"),
        (True, {"build_recipe_digest": "f" * 64}, {}, "unsupported artifact build recipe"),
        (True, {}, {"selected_package_version": ""}, "selected_package_version"),
        (
            True,
            {},
            {"selected_package_version": "v0.5.0", "selected_release_tag": "v0.5.0"},
            "outside the resolved milestone",
        ),
    ],
)
def test_unresolved_or_cross_mode_inputs_block_before_build(
    tmp_path: Path,
    source_synthetic: bool,
    source_overrides: dict[str, Any],
    target_overrides: dict[str, Any],
    reason: str,
) -> None:
    fixture = _record_inputs(tmp_path)
    for name, overrides, synthetic in [
        ("source-freeze", source_overrides, source_synthetic),
        ("target-resolution", target_overrides, True),
    ]:
        path = fixture["run"] / (name + ".json")
        old = control.read_json(path)
        data = copy.deepcopy(old["data"])
        data.update(overrides)
        record = control.make_record(
            "release-" + name,
            data,
            invocation_id=old["invocation_id"],
            sequence=1,
            synthetic=synthetic,
        )
        path.chmod(0o600)
        path.write_bytes(control.canonical_json(record))
    result = _run_build(fixture)
    assert result.returncode == 3
    assert reason in (fixture["run"] / "invocations/artifact-build/001/stderr").read_text()
    assert not (fixture["run"] / "invocations/artifact-build/001/workspace").exists()
    assert not (fixture["run"] / "artifacts").exists()


def test_tampered_input_is_invalid_not_release_evidence(tmp_path: Path) -> None:
    fixture = _record_inputs(tmp_path)
    path = fixture["run"] / "target-resolution.json"
    record = control.read_json(path)
    record["data"]["selected_release_tag"] = "v0.4.1"
    path.chmod(0o600)
    path.write_text(json.dumps(record))
    assert _run_build(fixture).returncode == 2
    assert _terminal(fixture)["status"] == "FAIL"
    assert not (fixture["run"] / "artifacts").exists()


@pytest.mark.parametrize("occupied", ["artifacts", "manifest"])
def test_existing_destination_is_never_changed_or_rebuilt(tmp_path: Path, occupied: str) -> None:
    fixture = _record_inputs(tmp_path)
    run = fixture["run"]
    path = run / "artifact-manifest.json"
    if occupied == "artifacts":
        (run / "artifacts").mkdir()
        path = run / "artifacts/retained.bin"
    path.write_bytes(b"retained")
    assert _run_build(fixture).returncode == 3
    assert path.read_bytes() == b"retained"
    assert not (run / "invocations/artifact-build/001/worker.pid").exists()


def test_failed_build_leaves_no_canonical_output(tmp_path: Path) -> None:
    fixture = _record_inputs(tmp_path)
    patch = "from tools import build_release_artifacts as a\ndef failed(source_dir,dist_dir,**kwargs):\n (dist_dir/'partial.whl').write_bytes(b'partial build evidence')\n raise a.ArtifactBuildBlocked('injected build failure')\na._run_build=failed"
    assert _run_build(fixture, bootstrap=_bootstrap(worker_patch=patch)).returncode == 3
    root = fixture["run"]
    assert (
        root / "invocations/artifact-build/001/staged/artifacts/partial.whl"
    ).read_bytes() == b"partial build evidence"
    assert _terminal(fixture)["status"] == "BLOCKED"
    assert not (root / "artifacts").exists() and not (root / "artifact-manifest.json").exists()
    assert _run_build(fixture, sequence=2).returncode == 3
    assert not (root / "invocations/artifact-build/002/worker.pid").exists()


@pytest.mark.parametrize("fault", ["second-artifact-link", "manifest-link"])
def test_partial_install_and_manifest_failure_roll_back_owned_artifacts(
    tmp_path: Path, fault: str
) -> None:
    fixture = _record_inputs(tmp_path)
    if fault == "second-artifact-link":
        patch = (
            "original=a.os.link\nlinks=0\n"
            "def failed(source,destination,**kwargs):\n"
            " global links\n links+=1\n"
            " if links==2: raise OSError('injected installation failure')\n"
            " original(source,destination,**kwargs)\n"
            "a.os.link=failed"
        )
    else:
        patch = (
            "original=c._rename_candidate_exclusive\n"
            "def failed(source_fd,source_name,destination_fd,destination_name):\n"
            " if destination_name=='artifact-manifest.json': "
            "raise OSError('injected installation failure')\n"
            " original(source_fd,source_name,destination_fd,destination_name)\n"
            "c._rename_candidate_exclusive=failed"
        )
    result = _run_build(fixture, bootstrap=_bootstrap(parent_patch=patch))
    assert result.returncode == 3, (result.stdout, result.stderr)
    root = fixture["run"]
    assert not (root / "artifacts").exists() and not (root / "artifact-manifest.json").exists()
    assert len(list((root / "invocations/artifact-build/001/staged/artifacts").iterdir())) == 2
    assert _terminal(fixture)["status"] == "BLOCKED"


def test_worker_kill_retains_partial_build_and_terminal_failure(tmp_path: Path) -> None:
    fixture = _record_inputs(tmp_path)
    patch = "import os,signal; from tools import build_release_artifacts as a\ndef killed(source_dir,dist_dir,**kwargs):\n (dist_dir/'partial.whl').write_bytes(b'killed worker evidence')\n os.kill(os.getpid(),signal.SIGKILL)\na._run_build=killed"
    assert (
        _run_build(fixture, bootstrap=_bootstrap(worker_patch=patch)).returncode
        == 128 + signal.SIGKILL
    )
    assert _terminal(fixture)["status"] == "CANCELLED"
    root = fixture["run"]
    assert (
        root / "invocations/artifact-build/001/staged/artifacts/partial.whl"
    ).read_bytes() == b"killed worker evidence"
    assert not (root / "artifacts").exists()


@pytest.mark.parametrize("after_install", [False, True])
def test_artifact_supervisor_kill_cannot_authorize_a_second_build(
    tmp_path: Path, after_install: bool
) -> None:
    fixture = _record_inputs(tmp_path)
    patch = (
        "import os,signal\noriginal=c._install_release_outputs\ndef killed(*args,**kwargs):\n "
        + ("original(*args,**kwargs)\n " if after_install else "")
        + "os.kill(os.getpid(),signal.SIGKILL)\nc._install_release_outputs=killed"
    )
    assert (
        _run_build(fixture, bootstrap=_bootstrap(parent_patch=patch)).returncode == -signal.SIGKILL
    )
    root = fixture["run"]
    assert not (root / "invocations/artifact-build/001/invocation.json").exists()
    assert (root / "artifact-manifest.json").exists() is after_install
    if after_install:
        with pytest.raises(control.ReleaseControlError):
            control.validate_release_artifact_files(
                control.read_json(root / "artifact-manifest.json"), root / "artifacts", live=False
            )
    assert _run_build(fixture, sequence=2).returncode == 3
    assert not (root / "invocations/artifact-build/002/worker.pid").exists()


def test_real_locked_build_archives_and_validates_the_frozen_source(tmp_path: Path) -> None:
    fixture = _record_inputs(tmp_path)
    result = _run_build(fixture)
    invocation = fixture["run"] / "invocations/artifact-build/001"
    assert result.returncode == 0, (
        result.stdout,
        result.stderr,
        (invocation / "stderr").read_text(),
    )
    record = control.read_json(fixture["run"] / "artifact-manifest.json")
    control.validate_release_artifact_files(record, fixture["run"] / "artifacts", live=False)
    assert (invocation / "workspace/source.tar").is_file()
    assert (invocation / "workspace/SHA256SUMS").is_file()
    assert "Successfully built" in (invocation / "stdout").read_text()
    assert "PASSED" in (invocation / "stdout").read_text()


def test_supervisor_kill_during_partial_artifact_install_preserves_unaccepted_bytes(
    tmp_path: Path,
) -> None:
    fixture = _record_inputs(tmp_path)
    patch = "import os,signal\noriginal=a.os.link\ndef killed(source,destination,**kwargs):\n original(source,destination,**kwargs)\n os.kill(os.getpid(),signal.SIGKILL)\na.os.link=killed"
    assert (
        _run_build(fixture, bootstrap=_bootstrap(parent_patch=patch)).returncode == -signal.SIGKILL
    )
    root = fixture["run"]
    assert len(list((root / "artifacts").iterdir())) == 1
    assert not (root / "artifact-manifest.json").exists()
    assert not (root / "invocations/artifact-build/001/invocation.json").exists()
    assert _run_build(fixture, sequence=2).returncode == 3
    assert not (root / "invocations/artifact-build/002/worker.pid").exists()


def test_failed_build_partial_hashes_are_bound_by_terminal(tmp_path: Path) -> None:
    fixture = _record_inputs(tmp_path)
    patch = "from tools import build_release_artifacts as a\ndef failed(source_dir,dist_dir,**kwargs):\n (dist_dir/'partial.whl').write_bytes(b'partial')\n raise a.ArtifactBuildBlocked('injected failure')\na._run_build=failed"
    assert _run_build(fixture, bootstrap=_bootstrap(worker_patch=patch)).returncode == 3
    root = fixture["run"]
    directory = root / "invocations/artifact-build/001"
    partial = control.read_json(directory / "partial-files.json")
    row = next(r for r in partial["files"] if r["path"].endswith("/partial.whl"))
    assert row["sha256"] == control.sha256_bytes(b"partial") and row["size"] == 7
    assert any(
        r["sha256"] == control.sha256_bytes((directory / "partial-files.json").read_bytes())
        for r in _terminal(fixture)["data"]["inputs"]
    )


def test_locked_backend_mismatch_prevents_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_source_fixture(tmp_path)
    real_version = control.importlib.metadata.version
    monkeypatch.setattr(
        control.importlib.metadata,
        "version",
        lambda name: "0.0.0" if name == "setuptools" else real_version(name),
    )
    destination = tmp_path / "dist"
    destination.mkdir()
    with pytest.raises(control.ReleaseControlError, match="setuptools"):
        artifact_cli._run_build(fixture["repository"], destination, source_date_epoch=1_700_000_000)
    assert list(destination.iterdir()) == []


def test_canonical_build_command_uses_installed_backend_without_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = make_source_fixture(tmp_path)
    calls = []

    def recorded(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(artifact_cli.subprocess, "run", recorded)
    destination = tmp_path / "dist"
    destination.mkdir()
    artifact_cli._run_build(fixture["repository"], destination, source_date_epoch=1_700_000_000)
    assert calls[0][0] == [
        sys.executable,
        "-m",
        "build",
        "--no-isolation",
        "--sdist",
        "--wheel",
        "--outdir",
        str(destination),
        str(fixture["repository"]),
    ]
    assert calls[0][1]["env"]["SOURCE_DATE_EPOCH"] == "1700000000"
    assert calls[0][1]["env"]["PYTHONHASHSEED"] == "0"
    assert calls[1][0] == [sys.executable, "-m", "twine", "check", "--strict"]


@pytest.mark.parametrize("fault", ["tamper", "delete", "extra", "unsafe", "index-extra"])
def test_failed_partial_inventory_is_independently_read_back(tmp_path: Path, fault: str) -> None:
    fixture = _record_inputs(tmp_path)
    patch = "from tools import build_release_artifacts as a\ndef failed(source_dir,dist_dir,**kwargs):\n (dist_dir/'partial.whl').write_bytes(b'partial')\n raise a.ArtifactBuildBlocked('injected failure')\na._run_build=failed"
    assert _run_build(fixture, bootstrap=_bootstrap(worker_patch=patch)).returncode == 3
    directory = fixture["run"] / "invocations/artifact-build/001"
    path = directory / "staged/artifacts/partial.whl"
    if fault == "tamper":
        path.write_bytes(b"changed")
    elif fault == "delete":
        path.unlink()
    elif fault == "extra":
        (path.parent / "extra.bin").write_bytes(b"extra")
    elif fault == "unsafe":
        path.unlink()
        path.symlink_to(fixture["run"] / "gate-input.json")
    else:
        index = directory / "partial-files.json"
        value = control.read_json(index)
        value["unexpected"] = True
        index.chmod(0o600)
        index.write_bytes(control.canonical_json(value))
        terminal = control.read_json(directory / "invocation.json")
        for row in terminal["data"]["inputs"]:
            if row["path"].endswith("/partial-files.json"):
                row["sha256"] = control.sha256_bytes(index.read_bytes())
        terminal["data"]["invocation_digest"] = control.sha256_json(
            {k: v for k, v in terminal["data"].items() if k != "invocation_digest"}
        )
        replaced = control.make_record(
            "release-stage-invocation",
            terminal["data"],
            invocation_id=terminal["invocation_id"],
            sequence=1,
            synthetic=True,
            status="BLOCKED",
        )
        target = directory / "invocation.json"
        target.chmod(0o600)
        target.write_bytes(control.canonical_json(replaced))
    with pytest.raises(control.ReleaseControlError, match="partial file inventory"):
        control._validate_terminal(control._validate_intent(directory))


def test_worker_death_preserves_flushed_build_child_logs_and_stops_its_group(
    tmp_path: Path,
) -> None:
    fixture = _record_inputs(tmp_path)
    child = "import os,signal,sys,time; from pathlib import Path\np=Path(sys.argv[1]); (p/'child-pid').write_text(str(os.getpid()))\nprint('flushed child stdout',flush=True); print('flushed child stderr',file=sys.stderr,flush=True)\n(p/'heartbeat').write_text(str(time.monotonic_ns()))\nos.kill(os.getppid(),signal.SIGKILL)\nwhile True:\n (p/'heartbeat').write_text(str(time.monotonic_ns()))\n time.sleep(0.01)"
    patch = (
        "import sys; from tools import build_release_artifacts as a\nreal_run=a.subprocess.run\ndef streamed(argv,**kwargs):\n if len(argv)>2 and argv[1:3]==['-m','build']:\n  return real_run([sys.executable,'-c',"
        + repr(child)
        + ",argv[argv.index('--outdir')+1]],**kwargs)\n return real_run(argv,**kwargs)\na.subprocess.run=streamed"
    )
    result = _run_build(fixture, bootstrap=_bootstrap(worker_patch=patch))
    root = fixture["run"]
    directory = root / "invocations/artifact-build/001"
    assert result.returncode == 137, (
        result.stdout,
        result.stderr,
        (directory / "stderr").read_text(),
    )
    assert "flushed child stdout" in (directory / "stdout").read_text()
    assert "flushed child stderr" in (directory / "stderr").read_text()
    assert _terminal(fixture)["status"] == "CANCELLED"
    before = {p.name: p.read_bytes() for p in (directory / "staged/artifacts").iterdir()}
    assert {"child-pid", "heartbeat"} <= before.keys()
    import time

    time.sleep(0.1)
    assert before == {p.name: p.read_bytes() for p in (directory / "staged/artifacts").iterdir()}
    control._validate_terminal(control._validate_intent(directory))


@pytest.mark.parametrize(
    "outcome", ["permission-then-absent", "kill-then-absent", "denied", "present"]
)
def test_worker_group_requires_observed_absence(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    elapsed = [0.0]
    calls = []

    def advance(seconds: float) -> None:
        elapsed[0] += seconds

    def signal_group(pid: int, signum: int) -> None:
        calls.append((pid, signum))
        if outcome.endswith("then-absent") and len(calls) == 2:
            raise ProcessLookupError("group has disappeared")
        if outcome in {"permission-then-absent", "denied"}:
            raise PermissionError("group cannot currently be signalled")

    monkeypatch.setattr(control.os, "killpg", signal_group)
    monkeypatch.setattr(control.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(control.time, "sleep", advance)
    assert control._stop_worker_group(12345) is outcome.endswith("then-absent")
    assert all(call == (12345, signal.SIGKILL) for call in calls)
    if outcome.endswith("then-absent"):
        assert len(calls) == 2 and elapsed[0] == 0.05
    else:
        assert 5 <= elapsed[0] < 5.1


@pytest.mark.parametrize("fault", ["permission", "unexpected-error"])
def test_unconfirmed_worker_group_cannot_finalize_or_install(tmp_path: Path, fault: str) -> None:
    fixture = _record_inputs(tmp_path)
    exception = "PermissionError" if fault == "permission" else "OSError"
    parent_patch = (
        "def unavailable_group(pid,signum):\n raise "
        + exception
        + "('injected group observation failure')\nc.os.killpg=unavailable_group"
    )
    result = _run_build(
        fixture,
        bootstrap=_bootstrap(worker_patch=_deterministic_build_patch(), parent_patch=parent_patch),
    )
    directory = fixture["run"] / "invocations/artifact-build/001"
    assert result.returncode == 3, (result.stdout, result.stderr)
    assert (directory / "worker-result.json").is_file()
    assert (directory / "staged/artifact-manifest.json").is_file()
    assert not (directory / "invocation.json").exists()
    assert not (fixture["run"] / "artifacts").exists()
    assert not (fixture["run"] / "artifact-manifest.json").exists()
    with pytest.raises(control.ReleaseControlError):
        control._validate_terminal(control._validate_intent(directory))


@pytest.mark.parametrize("fault", ["prior-diagnostic", "prior-partial"])
def test_validator_of_successor_reads_all_predecessor_evidence(tmp_path: Path, fault: str) -> None:
    fixture = _record_inputs(tmp_path)
    patch = "from tools import build_release_artifacts as a\ndef failed(source_dir,dist_dir,**kwargs):\n (dist_dir/'partial.whl').write_bytes(b'partial')\n raise a.ArtifactBuildBlocked('injected failure')\na._run_build=failed"
    assert _run_build(fixture, bootstrap=_bootstrap(worker_patch=patch)).returncode == 3
    assert _run_build(fixture, sequence=2).returncode == 3
    stage = fixture["run"] / "invocations/artifact-build"
    path = stage / (
        "001/stderr" if fault == "prior-diagnostic" else "001/staged/artifacts/partial.whl"
    )
    path.write_bytes(b"changed predecessor evidence")
    with pytest.raises(control.ReleaseControlError):
        control._validate_terminal(control._validate_intent(stage / "002"))


def _synthetic_readiness_shape_inputs(missing_from: str | None) -> dict[str, Any]:
    # Complete retained pure-consumer fixture, with cross-digests rebuilt after
    # schema amendments. This proves shape compatibility only: no live upstream
    # producer, invocation journal, signer or release readiness is asserted.
    def make_record(kind: str, data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if kind in {"release-source-freeze", "release-artifact-manifest"} and kind != missing_from:
            data = {
                **data,
                "invocation_root_locator": "invocations",
                "producer_intent_digest": "b" * 64,
            }
        return control.make_record(kind, data, **kwargs)

    sha256_json = control.sha256_json
    digest = "a" * 64
    registry: dict[str, Any] = {
        "blockers": [],
        "evidence_resolution": {"status": "READY"},
        "framework": "READY",
        "live_release": "READY",
    }
    predecessor = make_record(
        "release-predecessor",
        {
            "candidate_milestone": "v0.4",
            "closed_decision_digest": "b" * 64,
            "lkg_digest": "c" * 64,
            "version": "v0.3.0",
        },
        invocation_id="readiness-predecessor",
        sequence=1,
        synthetic=True,
    )
    linear = make_record(
        "linear-release-snapshot",
        {
            "required_bom_ids": ["MET-154"],
            "required_bom_snapshot_digest": sha256_json(["MET-154"]),
            "state": "In Progress",
            "task_id": "MET-154",
            "tool": "linear",
        },
        invocation_id="readiness-linear-snapshot",
        sequence=1,
        synthetic=True,
    )
    gate_input = make_record(
        "release-gate-input",
        {
            "environment_registry_digest": "7" * 64,
            "evidence_store_registry_digest": "c" * 64,
            "expected_predecessor_milestone": "v0.3",
            "gate_input_digest": "4" * 64,
            "linear_snapshot_digest": sha256_json(linear),
            "milestone": "v0.4",
            "obligation_registry_digest": "9" * 64,
            "readiness_registry_digest": sha256_json(registry),
            "role_assignments_digest": "6" * 64,
            "run_id": "readiness-run",
            "scenario_registry_digest": "a" * 64,
            "target_burn_digest": "b" * 64,
            "target_burn_index_receipt_digest": None,
            "target_registry_digest": "1" * 64,
            "target_resolution_digest": "2" * 64,
            "task_state_policy_digest": "2" * 64,
        },
        invocation_id="readiness-gate-input",
        sequence=1,
        synthetic=True,
    )
    source_freeze = make_record(
        "release-source-freeze",
        {
            "build_recipe_digest": "e" * 64,
            "dirty": False,
            "freeze_digest": "f" * 64,
            "frozen_at": "2026-08-25T12:00:00Z",
            "gate_input_digest": sha256_json(gate_input),
            "milestone": "v0.4",
            "registry_inputs": [
                {
                    "path": "docs/status/release-readiness.json",
                    "schema_id": "release-readiness",
                    "sha256": sha256_json(registry),
                }
            ],
            "release_notes_digest": "3" * 64,
            "source_sha": "1" * 40,
            "source_tree": "2" * 40,
            "version_metadata_digest": "4" * 64,
            "workflow_inputs": [
                {
                    "path": ".github/workflows/release-required.yml",
                    "schema_id": "github-workflow",
                    "sha256": "5" * 64,
                }
            ],
        },
        invocation_id="readiness-source-freeze",
        sequence=1,
        synthetic=True,
    )
    impact_manifest = make_record(
        "release-impact-manifest",
        {
            "author_id": "readiness-author",
            "base_sha": "0" * 40,
            "changes": [],
            "head_sha": "1" * 40,
            "manifest_digest": "6" * 64,
            "milestone": "v0.4",
            "release_tag": "v0.4.0",
            "source_freeze_digest": sha256_json(source_freeze),
            "target_resolution_digest": "2" * 64,
            "unclassified_paths": [],
        },
        invocation_id="readiness-impact-manifest",
        sequence=1,
        synthetic=True,
    )
    artifact_rows = [
        {
            "media_type": "application/vnd.pypa.wheel+zip",
            "path": "metriplane-0.4.0-py3-none-any.whl",
            "sha256": "d" * 64,
            "size": 10,
        },
        {
            "media_type": "application/gzip",
            "path": "metriplane-0.4.0.tar.gz",
            "sha256": "e" * 64,
            "size": 11,
        },
    ]
    artifact_set_digest = sha256_json(artifact_rows)
    artifact = make_record(
        "release-artifact-manifest",
        {
            "artifact_set_digest": artifact_set_digest,
            "artifacts": artifact_rows,
            "build_invocation_id": "readiness-artifact-build",
            "build_recipe_digest": "e" * 64,
            "milestone": "v0.4",
            "source_digest": "f" * 64,
            "source_freeze_digest": sha256_json(source_freeze),
            "target_resolution_digest": "2" * 64,
        },
        invocation_id="readiness-artifact-manifest",
        sequence=1,
        synthetic=True,
    )
    candidate_data = {
        "artifact_manifest_digest": sha256_json(artifact),
        "artifact_set_digest": artifact_set_digest,
        "build_invocation_id": "readiness-artifact-build",
        "finalization_intent_digest": "3" * 64,
        "control_journal_locator": "/synthetic-release/.control/readiness/invocations/candidate-finalization/001/invocation.json",
        "evaluation_adoption_digest": None,
        "evaluation_adoption_mode": "none",
        "gate_input_digest": sha256_json(gate_input),
        "milestone": "v0.4",
        "package_version": "v0.4.0",
        "predecessor_digest": sha256_json(predecessor),
        "release_tag": "v0.4.0",
        "source_freeze_digest": sha256_json(source_freeze),
    }
    candidate_digest = control._candidate_payload_digest(candidate_data)
    candidate_data["candidate_digest"] = candidate_digest
    candidate_data["final_directory"] = "/synthetic-release/v0.4.0/" + candidate_digest
    candidate = make_record(
        "release-candidate-identity",
        candidate_data,
        invocation_id="readiness-candidate",
        sequence=1,
        synthetic=True,
    )
    delta = make_record(
        "release-capability-delta",
        {
            "added": [],
            "candidate_sha": "1" * 40,
            "changed": [
                {
                    "after_digest": "7" * 64,
                    "before_digest": "6" * 64,
                    "capability_id": "release-framework",
                }
            ],
            "delta_digest": "5" * 64,
            "impact_manifest_digest": sha256_json(impact_manifest),
            "milestone": "v0.4",
            "predecessor_digest": sha256_json(predecessor),
            "removed": [],
        },
        invocation_id="readiness-delta",
        sequence=1,
        synthetic=True,
    )
    delta_map = make_record(
        "release-delta-test-map",
        {
            "delta_digest": "5" * 64,
            "environment_registry_digest": "7" * 64,
            "impact_manifest_digest": sha256_json(impact_manifest),
            "map_digest": "8" * 64,
            "mappings": [
                {
                    "capability_id": "release-framework",
                    "environment_ids": ["ubuntu-24.04-py312"],
                    "obligation_ids": ["MP2-007.A01"],
                    "scenario_ids": ["hard-runner-loss"],
                }
            ],
            "milestone": "v0.4",
            "obligation_registry_digest": "9" * 64,
            "scenario_registry_digest": "a" * 64,
            "unmapped_capabilities": [],
        },
        invocation_id="readiness-delta-map",
        sequence=1,
        synthetic=True,
    )
    gate = make_record(
        "release-gate-instance",
        {
            "candidate_digest": candidate_digest,
            "candidate_identity_digest": sha256_json(candidate),
            "environment_registry_digest": "7" * 64,
            "evidence_store_preflight_digest": "b" * 64,
            "evidence_store_registry_digest": "c" * 64,
            "frozen_source_sha": "1" * 40,
            "gate_input_digest": sha256_json(gate_input),
            "instance_digest": digest,
            "linear_snapshot_digest": sha256_json(linear),
            "main_health_digest": "d" * 64,
            "main_health_history_digest": "e" * 64,
            "milestone": "v0.4",
            "obligation_registry_digest": "9" * 64,
            "package_version": "v0.4.0",
            "predecessor_digest": sha256_json(predecessor),
            "release_tag": "v0.4.0",
            "repository_protection_digest": "f" * 64,
            "run_id": "readiness-run",
            "scenario_registry_digest": "a" * 64,
            "target_registry_digest": "1" * 64,
            "task_state_policy_digest": "2" * 64,
        },
        invocation_id="readiness-gate",
        sequence=1,
        synthetic=True,
    )

    return {
        "gate_input": gate_input,
        "gate_instance": gate,
        "candidate_identity_record": candidate,
        "predecessor": predecessor,
        "linear_snapshot": linear,
        "source_freeze": source_freeze,
        "impact_manifest": impact_manifest,
        "artifact_manifest": artifact,
        "delta": delta,
        "delta_test_map": delta_map,
        "readiness_registry": registry,
    }


@pytest.mark.parametrize(
    "missing_from", [None, "release-source-freeze", "release-artifact-manifest"]
)
def test_readiness_shape_consumer_requires_amended_synthetic_inputs(
    missing_from: str | None,
) -> None:
    inputs = _synthetic_readiness_shape_inputs(missing_from)
    if missing_from is not None:
        with pytest.raises(control.ReleaseControlError, match="data shape is not closed"):
            control.build_release_readiness_record(**inputs)
    else:
        record = control.build_release_readiness_record(**inputs)
        assert record["synthetic"] is True
        assert record["data"]["disposition"] == "READY"


def _artifact_keyring_context(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, live: bool = False, policy: bool = False
) -> tuple[control.ReleaseInvocation, Any, dict[str, Any]]:
    # Actual public reservation/capture, stopped before worker dispatch. The
    # source record is deliberately only a semantic-validator seam, not proof.
    root.mkdir(parents=True, exist_ok=True)
    _artifact_compatibility_inputs(root, synthetic=not live)
    keyring = {
        "schema_version": "metriplane.provider-attestation-keyring.v1",
        "keys": [
            {"provider": "github", "actor_id": "synthetic-key-owner", "public_key_hex": "a" * 64}
        ],
    }
    keyring_path = root / "inputs/trust/keyring.json"
    keyring_path.parent.mkdir(parents=True)
    keyring_path.write_bytes(control.canonical_json(keyring))
    monkeypatch.chdir(root)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "0" if live else "1")
    argv = [
        *_argv({"run": root}),
        "--provider-attestation-keyring",
        str(keyring_path),
        "--provider-attestation-keyring-digest",
        control.sha256_json(keyring),
    ]
    if policy:
        argv += ["--authority-policy-digest", "b" * 64]
    contexts = []

    def retain(context: control.ReleaseInvocation, **kwargs: Any) -> int:
        contexts.append(context)
        return 3

    with monkeypatch.context() as capture:
        capture.setattr(control, "_supervise_release_invocation", retain)
        assert control.run_release_command("build_release_artifacts.py", argv) == 3
    assert len(contexts) == 1
    assert not (root / "artifacts").exists()
    return contexts[0], artifact_cli._parse_args(argv), keyring


def _artifact_keyring_rewrite_intent(
    context: control.ReleaseInvocation, intent: dict[str, Any]
) -> control.ReleaseInvocation:
    intent["invocation_id"] = control._intent_identity(intent)
    path = context.directory / "intent.json"
    path.chmod(0o600)
    path.write_bytes(control.canonical_json(intent))
    path.chmod(0o400)
    return control._validate_intent(context.directory)


@pytest.mark.parametrize("live", [False, True])
def test_artifact_keyring_actual_capture_and_adapter_forwarding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live: bool
) -> None:
    context, args, keyring = _artifact_keyring_context(
        tmp_path, monkeypatch, live=live, policy=True
    )
    control._validate_bound_invocation(context)
    row = next(r for r in context.intent["inputs"] if "keyring" in r["schema_id"])
    assert row == {
        "path": str(tmp_path / "inputs/trust/keyring.json"),
        "schema_id": "metriplane.provider-attestation-keyring.v1",
        "sha256": control.sha256_bytes(control.canonical_json(keyring)),
    }
    assert context.intent["argv"] == [
        "build_release_artifacts.py",
        *_argv({"run": tmp_path}),
        "--provider-attestation-keyring",
        args.provider_attestation_keyring,
        "--provider-attestation-keyring-digest",
        control.sha256_json(keyring),
        "--authority-policy-digest",
        "b" * 64,
    ]
    calls = []

    def stop(*paths: Path, **kwargs: Any) -> Any:
        calls.append(kwargs)
        raise artifact_cli.ArtifactBuildBlocked("test stop before source proof or build")

    def no_path_parse(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("bound keyring reopened through the unbound parser")

    monkeypatch.setattr(artifact_cli, "_load_inputs", stop)
    monkeypatch.setattr(control.ProviderAttestationVerifier, "from_keyring", no_path_parse)
    with pytest.raises(artifact_cli.ArtifactBuildBlocked, match="test stop"):
        artifact_cli._execute(args, context=context)
    assert len(calls) == 1 and calls[0]["fixture_mode"] is not live
    assert calls[0]["expected_authority_policy_digest"] == "b" * 64
    verifier = calls[0]["attestation_verifier"]
    assert isinstance(verifier, control.ProviderAttestationVerifier)
    assert verifier.keyring_digest == control.sha256_json(keyring)
    assert verifier.keys == {("github", "synthetic-key-owner"): bytes.fromhex("a" * 64)}


@pytest.mark.parametrize("change", ["missing", "wrong-type", "wrong-suffix", "extra", "external"])
def test_artifact_keyring_membership_precedes_keyring_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    context, args, _ = _artifact_keyring_context(tmp_path, monkeypatch)
    intent = copy.deepcopy(dict(context.intent))
    row = next(r for r in intent["inputs"] if "keyring" in r["schema_id"])
    if change == "missing":
        intent["inputs"].remove(row)
    elif change == "wrong-type":
        row["schema_id"] = "metriplane.release-source-freeze.v1"
    elif change == "wrong-suffix":
        other = tmp_path / "inputs/trust/other.json"
        other.write_bytes(Path(args.provider_attestation_keyring).read_bytes())
        row["path"] = str(other)
    elif change == "extra":
        intent["inputs"].append({**row, "path": str(tmp_path / "inputs/extra.json")})
    else:
        external = tmp_path.parent / "external-keyring.json"
        external.write_bytes(Path(args.provider_attestation_keyring).read_bytes())
        row["path"] = str(external)
        intent["argv"][intent["argv"].index("--provider-attestation-keyring") + 1] = str(external)
        args.provider_attestation_keyring = str(external)
    intent["inputs"].sort(key=lambda r: r["path"])
    context = _artifact_keyring_rewrite_intent(context, intent)
    original = control._release_held_path
    opened = []

    def held(path: Path, **kwargs: Any) -> Any:
        if not kwargs.get("directory") and path.name != "intent.json":
            opened.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(control, "_release_held_path", held)
    with pytest.raises(control.ReleaseControlError):
        control._attestation_verifier_from_args(args, live=False, context=context)
    assert opened == []


@pytest.mark.parametrize(
    "change", ["raw", "missing-digest", "wrong-digest", "args", "mode", "intent"]
)
def test_artifact_keyring_raw_and_independent_identity_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    context, args, _ = _artifact_keyring_context(tmp_path, monkeypatch)
    if change == "raw":
        Path(args.provider_attestation_keyring).write_bytes(b'{"invalid":')
    elif change in {"missing-digest", "wrong-digest"}:
        intent = copy.deepcopy(dict(context.intent))
        index = intent["argv"].index("--provider-attestation-keyring-digest")
        if change == "missing-digest":
            del intent["argv"][index : index + 2]
            args.provider_attestation_keyring_digest = None
        else:
            intent["argv"][index + 1] = "0" * 64
            args.provider_attestation_keyring_digest = "0" * 64
        context = _artifact_keyring_rewrite_intent(context, intent)
    elif change == "args":
        args.provider_attestation_keyring = "inputs/trust/keyring.json"
    elif change == "intent":
        intent = copy.deepcopy(dict(context.intent))
        intent["environment"]["source_date_epoch"] = "different"
        _artifact_keyring_rewrite_intent(context, intent)
    parsed = []
    original = control._source_json

    def parse(raw: bytes, label: str) -> dict[str, Any]:
        parsed.append(label)
        return original(raw, label)

    monkeypatch.setattr(control, "_source_json", parse)
    with pytest.raises(control.ReleaseControlError):
        control._attestation_verifier_from_args(args, live=change == "mode", context=context)
    if change != "wrong-digest":
        assert not any("original artifact provider" in label for label in parsed)


@pytest.mark.parametrize("relative", [False, True])
def test_artifact_keyring_relocation_never_reads_old_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: bool
) -> None:
    original_root = tmp_path / "original"
    context, args, keyring = _artifact_keyring_context(original_root, monkeypatch)
    if relative:
        intent = copy.deepcopy(dict(context.intent))
        for i, value in enumerate(intent["argv"]):
            if value.startswith(str(original_root) + "/"):
                intent["argv"][i] = str(Path(value).relative_to(original_root))
        context = _artifact_keyring_rewrite_intent(context, intent)
        args = artifact_cli._parse_args(intent["argv"][1:])
    relocated = tmp_path / "relocated"
    monkeypatch.chdir(tmp_path)
    original_root.rename(relocated)
    context = control._validate_intent(relocated / "invocations/artifact-build/001")
    original = control._release_held_path
    reads = []

    def held(path: Path, **kwargs: Any) -> Any:
        assert not path.is_relative_to(original_root)
        reads.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(control, "_release_held_path", held)
    verifier = control._attestation_verifier_from_args(args, live=False, context=context)
    assert verifier is not None and verifier.keyring_digest == control.sha256_json(keyring)
    assert relocated / "inputs/trust/keyring.json" in reads
    control._validate_bound_invocation(context)


@pytest.mark.parametrize("change", ["symlink", "hardlink", "parent-symlink", "root-race"])
def test_artifact_keyring_unsafe_objects_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    context, args, _ = _artifact_keyring_context(tmp_path, monkeypatch)
    path = Path(args.provider_attestation_keyring)
    if change == "symlink":
        other = path.with_name("original.json")
        path.rename(other)
        path.symlink_to(other)
    elif change == "hardlink":
        path.with_name("alias.json").hardlink_to(path)
    elif change == "parent-symlink":
        other = path.parent.with_name("original-trust")
        path.parent.rename(other)
        path.parent.symlink_to(other, target_is_directory=True)
    else:
        original = control._release_held_path
        changed = False

        def held(member: Path, **kwargs: Any) -> Any:
            nonlocal changed
            result = original(member, **kwargs)
            if member == context.directory / "intent.json" and not changed:
                changed = True
                # Substitute the held root with a real directory before member IO.
                monkeypatch.chdir(tmp_path.parent)
                tmp_path.rename(tmp_path.with_name(tmp_path.name + "-preserved"))
                tmp_path.mkdir()
            return result

        monkeypatch.setattr(control, "_release_held_path", held)
    with pytest.raises(control.ReleaseControlError):
        control._attestation_verifier_from_args(args, live=False, context=context)


def _artifact_supervisor_record(context: control.ReleaseInvocation) -> dict[str, Any]:
    source = control.read_json(context.root / "source-freeze.json")
    target = control.read_json(context.root / "target-resolution.json")
    return control.make_record(
        "release-artifact-manifest",
        {
            "source_digest": source["data"]["freeze_digest"],
            "source_freeze_digest": control.sha256_json(source),
            "target_resolution_digest": control.sha256_json(target),
            "build_recipe_digest": source["data"]["build_recipe_digest"],
            "milestone": source["data"]["milestone"],
        },
        invocation_id=context.intent["invocation_id"],
        sequence=1,
        synthetic=source["synthetic"],
    )


@pytest.mark.parametrize("live", [False, True])
def test_artifact_supervisor_reconstructs_verifier_for_source_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live: bool
) -> None:
    context, _, keyring = _artifact_keyring_context(tmp_path, monkeypatch, live=live)
    record = _artifact_supervisor_record(context)
    calls = []

    def capture(source: Any, **kwargs: Any) -> None:
        calls.append((source, kwargs))

    monkeypatch.setattr(control, "validate_release_source_freeze_record", capture)
    control._artifact_source_replay(context, record, repository=tmp_path)
    assert len(calls) == 1 and calls[0][1]["live"] is live
    assert calls[0][1]["repository"] == tmp_path
    assert calls[0][1]["record_path"] == tmp_path / "source-freeze.json"
    verifier = calls[0][1]["attestation_verifier"]
    assert isinstance(verifier, control.ProviderAttestationVerifier)
    assert verifier.keyring_digest == control.sha256_json(keyring)
    assert verifier.keys == {("github", "synthetic-key-owner"): bytes.fromhex("a" * 64)}


@pytest.mark.parametrize(
    "field",
    [
        "source_digest",
        "source_freeze_digest",
        "target_resolution_digest",
        "build_recipe_digest",
        "milestone",
        "synthetic",
    ],
)
def test_artifact_supervisor_semantic_mismatch_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    context, _, _ = _artifact_keyring_context(tmp_path, monkeypatch)
    record = _artifact_supervisor_record(context)
    if field == "synthetic":
        record[field] = False
    else:
        record["data"][field] = "different"
    monkeypatch.setattr(control, "validate_release_source_freeze_record", lambda *a, **k: None)
    with pytest.raises(control.ReleaseControlError, match="semantic source or target"):
        control._artifact_source_replay(context, record, repository=tmp_path)


@pytest.mark.parametrize("failure", ["native-source", "replay-rejection", "policy"])
def test_artifact_supervisor_does_not_accept_unverified_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    context, _, _ = _artifact_keyring_context(tmp_path, monkeypatch, policy=failure == "policy")
    record = _artifact_supervisor_record(context)
    if failure != "native-source":

        def reject(*args: Any, **kwargs: Any) -> None:
            raise control.ReleaseControlError("synthetic source replay rejection")

        monkeypatch.setattr(control, "validate_release_source_freeze_record", reject)
    with pytest.raises(control.ReleaseControlError) as error:
        control._artifact_source_replay(context, record, repository=tmp_path)
    if failure == "policy":
        assert "authority-policy replay hook" in str(error.value)
    elif failure == "replay-rejection":
        assert "synthetic source replay rejection" in str(error.value)
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize("case", ["external", "missing-digest", "digest-only", "duplicate"])
def test_artifact_keyring_public_capture_rejects_before_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    monkeypatch.chdir(tmp_path)
    keyring_path = tmp_path / "inputs/keyring.json"
    keyring_path.parent.mkdir()
    keyring_path.write_bytes(b"not parsed by this invalid request")
    extra = [
        "--provider-attestation-keyring",
        str(keyring_path),
        "--provider-attestation-keyring-digest",
        "a" * 64,
    ]
    if case == "external":
        extra[1] = str(tmp_path.parent / "external.json")
    elif case == "missing-digest":
        extra = extra[:2]
    elif case == "digest-only":
        extra = extra[2:]
    else:
        extra += extra[:2]
    monkeypatch.setattr(
        control, "_release_held_path", lambda *a, **k: pytest.fail("unexpected read")
    )
    monkeypatch.setattr(
        control, "_supervise_release_invocation", lambda *a, **k: pytest.fail("worker")
    )
    assert (
        control.run_release_command(
            "build_release_artifacts.py", [*_argv({"run": tmp_path}), *extra]
        )
        == 2
    )
    assert not (tmp_path / "invocations").exists()
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize("failure", ["none", "source-rejection", "keyring-tamper"])
def test_artifact_supervisor_full_staged_boundary_uses_source_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    context, args, keyring = _artifact_keyring_context(tmp_path, monkeypatch)
    staged = context.directory / "staged"
    (staged / "artifacts").mkdir(parents=True)
    artifacts = []
    for name, media in [
        ("metriplane-0.4.1-py3-none-any.whl", "application/vnd.pypa.wheel+zip"),
        ("metriplane-0.4.1.tar.gz", "application/gzip"),
    ]:
        # Synthetic bytes only: this boundary proves inventory and replay, not archives.
        raw = ("synthetic boundary bytes " + name).encode()
        (staged / "artifacts" / name).write_bytes(raw)
        artifacts.append(
            {
                "path": name,
                "media_type": media,
                "sha256": control.sha256_bytes(raw),
                "size": len(raw),
            }
        )
    record = _artifact_supervisor_record(context)
    record["data"].update(
        {
            "artifacts": artifacts,
            "artifact_set_digest": control.sha256_json(artifacts),
            "build_invocation_id": context.intent["invocation_id"],
            "producer_intent_digest": control.sha256_json(context.intent),
            "invocation_root_locator": "invocations",
        }
    )
    record = control.make_record(
        "release-artifact-manifest",
        record["data"],
        invocation_id=context.intent["invocation_id"],
        sequence=1,
        synthetic=True,
    )
    (staged / "artifact-manifest.json").write_bytes(control.canonical_json(record))
    outputs = control._collect_staged_outputs(context)
    calls = []

    def replay(source: Any, **kwargs: Any) -> None:
        verifier = kwargs["attestation_verifier"]
        assert verifier.keyring_digest == control.sha256_json(keyring)
        calls.append(source)
        if failure == "source-rejection":
            raise control.ReleaseControlError("source proof rejected at supervisor boundary")
        if failure == "keyring-tamper":
            Path(args.provider_attestation_keyring).write_bytes(b"changed during source replay")

    monkeypatch.setattr(control, "_source_repository", lambda path: path)
    monkeypatch.setattr(control, "validate_release_source_freeze_record", replay)
    if failure == "none":
        control._verify_staged_outputs(context, outputs)
    else:
        with pytest.raises(control.ReleaseControlError):
            control._verify_staged_outputs(context, outputs)
    assert len(calls) == 1
    assert not (tmp_path / "artifacts").exists()
    assert not (context.directory / "invocation.json").exists()


def test_artifact_keyring_absent_original_input_preserves_fixture_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, _, _ = _artifact_keyring_context(tmp_path, monkeypatch)
    intent = copy.deepcopy(dict(context.intent))
    intent["argv"] = ["build_release_artifacts.py", *_argv({"run": tmp_path})]
    intent["inputs"] = [r for r in intent["inputs"] if "keyring" not in r["schema_id"]]
    context = _artifact_keyring_rewrite_intent(context, intent)
    args = artifact_cli._parse_args(intent["argv"][1:])
    assert control._attestation_verifier_from_args(args, live=False, context=context) is None
    control._validate_bound_invocation(context)
    flags = {
        "provider-attestation-keyring",
        "provider-attestation-keyring-digest",
        "authority-policy-digest",
    }
    assert flags <= control.TOOL_CONTRACTS["build_release_artifacts.py"].optional
    assert not flags.intersection(control.TOOL_CONTRACTS["freeze_release_source.py"].flags)


def _artifact_preinstall_fixture(
    context: control.ReleaseInvocation,
    *,
    status: str = "PASS",
    wheel: str = "metriplane-0.4.1-py3-none-any.whl",
    sdist: str = "metriplane-0.4.1.tar.gz",
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    # Complete coherent output envelope and real raw hashes; distribution bytes
    # are explicitly synthetic. Construct worker refs independently of collector.
    staged = context.directory / "staged"
    (staged / "artifacts").mkdir(parents=True)
    artifacts = []
    outputs = []
    for name, media in sorted(
        [(wheel, "application/vnd.pypa.wheel+zip"), (sdist, "application/gzip")]
    ):
        raw = ("synthetic artifact " + name).encode()
        (staged / "artifacts" / name).write_bytes(raw)
        digest = control.sha256_bytes(raw)
        artifacts.append({"path": name, "media_type": media, "sha256": digest, "size": len(raw)})
        outputs.append({"path": "artifacts/" + name, "schema_id": media, "sha256": digest})
    data = _artifact_supervisor_record(context)["data"]
    data.update(
        {
            "artifacts": artifacts,
            "artifact_set_digest": control.sha256_json(artifacts),
            "build_invocation_id": context.intent["invocation_id"],
            "producer_intent_digest": control.sha256_json(context.intent),
            "invocation_root_locator": "invocations",
        }
    )
    record = control.make_record(
        "release-artifact-manifest",
        data,
        invocation_id=context.intent["invocation_id"],
        sequence=1,
        synthetic=True,
        status=status,
    )
    control.validate_record(record, "release-artifact-manifest")
    control._validate_artifact_manifest_payload(data, expected_milestone="v0.4")
    raw = control.canonical_json(record)
    (staged / "artifact-manifest.json").write_bytes(raw)
    outputs.append(
        {
            "path": "artifact-manifest.json",
            "schema_id": "metriplane.release-artifact-manifest.v1",
            "sha256": control.sha256_bytes(raw),
        }
    )
    return record, sorted(outputs, key=lambda row: row["path"])


@pytest.mark.parametrize(
    "status", sorted((control.TERMINAL_RESULTS | {"OPEN", "READY", "INVALIDATED"}) - {"PASS"})
)
def test_artifact_preinstall_rejects_coherent_nonpass_before_source_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    context, _, _ = _artifact_keyring_context(tmp_path, monkeypatch)
    _, outputs = _artifact_preinstall_fixture(context, status=status)
    monkeypatch.setattr(control, "_source_repository", lambda *a: pytest.fail("source lookup"))
    monkeypatch.setattr(
        control,
        "validate_release_source_freeze_record",
        lambda *a, **k: pytest.fail("source replay"),
    )
    with pytest.raises(control.ReleaseControlError, match="artifact manifest is not PASS"):
        control._collect_staged_outputs(context)
    with pytest.raises(control.ReleaseControlError, match="artifact manifest is not PASS"):
        control._verify_staged_outputs(context, outputs)
    assert not (tmp_path / "artifact-manifest.json").exists()
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize(
    ("wheel", "sdist", "valid"),
    [
        ("metriplane-0.4.1-py3-none-any.whl", "metriplane-0.4.1.tar.gz", True),
        ("metriplane-0.4.1-cp313-cp313-macosx_11_0_arm64.whl", "metriplane-0.4.1.tar.gz", True),
        ("metriplane-0.4.2-py3-none-any.whl", "metriplane-0.4.2.tar.gz", False),
        ("metriplane-0.4.2-py3-none-any.whl", "metriplane-0.4.1.tar.gz", False),
        ("metriplane-0.4.1-py3-none-any.whl", "metriplane-0.4.2.tar.gz", False),
        ("metriplane-0.4.10-py3-none-any.whl", "metriplane-0.4.1.tar.gz", False),
        ("other-0.4.1-py3-none-any.whl", "metriplane-0.4.1.tar.gz", False),
        ("metriplane-v0.4.1-py3-none-any.whl", "metriplane-0.4.1.tar.gz", False),
    ],
)
def test_artifact_preinstall_binds_distribution_names_to_exact_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wheel: str, sdist: str, valid: bool
) -> None:
    context, _, _ = _artifact_keyring_context(tmp_path, monkeypatch)
    record, outputs = _artifact_preinstall_fixture(context, wheel=wheel, sdist=sdist)
    assert outputs == control._collect_staged_outputs(context)
    assert record["data"]["target_resolution_digest"] == control.sha256_json(
        control.read_json(tmp_path / "target-resolution.json")
    )
    calls = []
    monkeypatch.setattr(control, "_source_repository", lambda path: path)
    monkeypatch.setattr(
        control, "validate_release_source_freeze_record", lambda *a, **k: calls.append(k)
    )
    if valid:
        control._verify_staged_outputs(context, outputs)
    else:
        with pytest.raises(
            control.ReleaseControlError, match="artifact filenames differ from exact target"
        ):
            control._verify_staged_outputs(context, outputs)
    assert len(calls) == 1
    assert not (tmp_path / "artifacts").exists()
    assert not (context.directory / "invocation.json").exists()


@pytest.mark.parametrize(
    ("version", "tag"),
    [
        ("0.4.1", "v0.4.1"),
        ("vv0.4.1", "vv0.4.1"),
        ("v0.4.01", "v0.4.01"),
        ("v0.4.1.post0", "v0.4.1.post0"),
        ("v0.4.1", "v0.4.2"),
        ("v0.5.0", "v0.5.0"),
    ],
)
def test_artifact_preinstall_target_projection_preserves_strict_current_grammar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, tag: str
) -> None:
    context, _, _ = _artifact_keyring_context(tmp_path, monkeypatch)
    target_path = tmp_path / "target-resolution.json"
    target = control.read_json(target_path)
    data = dict(target["data"])
    data.update(selected_package_version=version, selected_release_tag=tag)
    data.pop("resolution_digest")
    data["resolution_digest"] = control.sha256_json(data)
    target = control.make_record(
        "release-target-resolution",
        data,
        invocation_id=target["invocation_id"],
        sequence=1,
        synthetic=True,
    )
    target_path.write_bytes(control.canonical_json(target))
    intent = copy.deepcopy(dict(context.intent))
    next(row for row in intent["inputs"] if row["path"] == str(target_path))["sha256"] = (
        control.sha256_json(target)
    )
    context = _artifact_keyring_rewrite_intent(context, intent)
    _, outputs = _artifact_preinstall_fixture(context)
    monkeypatch.setattr(control, "_source_repository", lambda path: path)
    monkeypatch.setattr(control, "validate_release_source_freeze_record", lambda *a, **k: None)
    with pytest.raises(control.ReleaseControlError):
        control._verify_staged_outputs(context, outputs)
    assert not (tmp_path / "artifacts").exists()
