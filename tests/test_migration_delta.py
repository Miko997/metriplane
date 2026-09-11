# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from metriplane.release_control import canonical_json, sha256_json

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "validate_migration_delta.py"
_NODE_SIGN = r"""
const crypto = require("node:crypto");
const fs = require("node:fs");
const {privateKey, publicKey} = crypto.generateKeyPairSync("ed25519");
const publicDer = publicKey.export({format: "der", type: "spki"});
const prefix = Buffer.from("302a300506032b6570032100", "hex");
if (!publicDer.subarray(0, prefix.length).equals(prefix) || publicDer.length !== prefix.length + 32) {
  process.exit(2);
}
process.stdout.write(JSON.stringify({
  public_key_hex: publicDer.subarray(prefix.length).toString("hex"),
  signature: crypto.sign(null, fs.readFileSync(0), privateKey).toString("hex"),
}));
"""


def _write(path: Path, value: object) -> None:
    path.write_bytes(canonical_json(value))


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _signed_fixture(message: bytes) -> tuple[str, str]:
    completed = subprocess.run(
        ["node", "--eval", _NODE_SIGN],
        input=message,
        capture_output=True,
        check=True,
    )
    value = json.loads(completed.stdout)
    return value["public_key_hex"], value["signature"]


def _obligation(identity: str) -> dict[str, object]:
    return {
        "id": identity,
        "lifecycle": "active",
        "superseded_by": [],
        "supersession_authority": [],
        "capability_ids": ["capability"],
        "criterion_ids": ["MP2-017.A01"],
        "environment_ids": ["environment"],
        "family_ids": ["COMPAT", "SEMANTIC"],
        "profile_ids": ["profile"],
        "scenario_ids": ["scenario"],
    }


def _fixture(
    tmp_path: Path,
    *,
    weak: bool = False,
    same_reviewer: bool = False,
    declare_row: bool = True,
    declare_replacement: bool = True,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    original_row = {
        "id": "SUPPORTED.ROW",
        "claim": {"classification": "compatibility", "statement": "before"},
    }
    changed_row = {
        "id": "SUPPORTED.ROW",
        "claim": {"classification": "compatibility", "statement": "after"},
    }
    stable_row = {
        "id": "SUPPORTED.STABLE",
        "claim": {"classification": "supported", "statement": "unchanged"},
    }
    functional = {"rows": [original_row, stable_row]}
    behavior = {"rows": []}
    original = _obligation("OLD")
    _write(repo / "functional.json", functional)
    _write(repo / "behavior.json", behavior)
    _write(repo / "obligations.json", {"obligations": [original]})
    (repo / "golden.txt").write_bytes(b"before\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = _git(repo, "rev-parse", "HEAD")

    retired = copy.deepcopy(original)
    retired.update(
        lifecycle="retired_with_reviewed_supersession",
        superseded_by=["NEW"],
        supersession_authority=[{"review": "fixture"}],
    )
    replacement = _obligation("NEW")
    if weak:
        replacement["family_ids"] = ["COMPAT"]
    _write(repo / "functional.json", {"rows": [changed_row, stable_row]})
    _write(repo / "obligations.json", {"obligations": [retired, replacement]})
    (repo / "golden.txt").write_bytes(b"after\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=repo, check=True)
    head = _git(repo, "rev-parse", "HEAD")

    manifest = {
        "schema_version": "metriplane.migration-delta.v1",
        "task_id": "MP2-017",
        "base_sha": base,
        "head_sha": head,
        "author_id": "fixture-author",
        "changed_paths": ["functional.json", "golden.txt", "obligations.json"],
        "changes": [
            *(
                [
                    {
                        "stable_id": "SUPPORTED.ROW",
                        "kind": "semantic",
                        "before_sha256": sha256_json(original_row),
                        "after_sha256": sha256_json(changed_row),
                        "supersedes": [],
                        "replacements": [],
                        "compatibility_window": {
                            "first_release": "v0.4",
                            "last_release": "v0.5",
                            "disposition": "deprecated",
                            "reason": "fixture semantic migration",
                        },
                    }
                ]
                if declare_row
                else []
            ),
            {
                "stable_id": "golden.txt",
                "kind": "golden",
                "before_sha256": hashlib.sha256(b"before\n").hexdigest(),
                "after_sha256": hashlib.sha256(b"after\n").hexdigest(),
                "supersedes": [],
                "replacements": [],
                "compatibility_window": {
                    "first_release": "v0.4",
                    "last_release": None,
                    "disposition": "preserved",
                    "reason": "fixture golden migration",
                },
            },
            {
                "stable_id": "OLD",
                "kind": "test_obligation",
                "before_sha256": sha256_json(original),
                "after_sha256": sha256_json(retired),
                "supersedes": ["OLD"],
                "replacements": ["NEW"],
                "compatibility_window": {
                    "first_release": "v0.4",
                    "last_release": "v0.5",
                    "disposition": "deprecated",
                    "reason": "fixture migration",
                },
            },
            *(
                [
                    {
                        "stable_id": "NEW",
                        "kind": "test_obligation",
                        "before_sha256": None,
                        "after_sha256": sha256_json(replacement),
                        "supersedes": [],
                        "replacements": [],
                        "compatibility_window": {
                            "first_release": "v0.4",
                            "last_release": None,
                            "disposition": "preserved",
                            "reason": "fixture replacement",
                        },
                    }
                ]
                if declare_replacement
                else []
            ),
        ],
    }
    reviewer = "fixture-author" if same_reviewer else "fixture-reviewer"
    digest = sha256_json(manifest)
    signed = canonical_json({"actor_id": reviewer, "provider": "github", "subject_digest": digest})
    public_key_hex, signature = _signed_fixture(signed)
    approval = {
        "schema_version": "metriplane.migration-delta-approval.v1",
        "reviewer_id": reviewer,
        "subject_digest": digest,
        "signature": {
            "provider": "github",
            "actor_id": reviewer,
            "signature": signature,
        },
    }
    keyring = {
        "schema_version": "metriplane.provider-attestation-keyring.v1",
        "keys": [{"provider": "github", "actor_id": reviewer, "public_key_hex": public_key_hex}],
    }
    _write(tmp_path / "manifest.json", manifest)
    _write(tmp_path / "approval.json", approval)
    _write(tmp_path / "keyring.json", keyring)
    return repo, manifest


def _run(tmp_path: Path, repo: Path, *, out: str = "result.json"):
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--repository-root",
            str(repo),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--schema",
            str(ROOT / "schemas/metriplane.migration-delta.v1.schema.json"),
            "--approval",
            str(tmp_path / "approval.json"),
            "--approval-schema",
            str(ROOT / "schemas/metriplane.migration-delta-approval.v1.schema.json"),
            "--keyring",
            str(tmp_path / "keyring.json"),
            "--functional-inventory",
            "functional.json",
            "--behavior-characterization",
            "behavior.json",
            "--obligations",
            "obligations.json",
            "--out",
            str(tmp_path / out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_accepts_exact_non_author_equal_or_stronger_supersession(tmp_path: Path) -> None:
    repo, _ = _fixture(tmp_path)
    result = _run(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "result.json").read_bytes())["verdict"] == "READY"


def test_rejects_author_as_reviewer(tmp_path: Path) -> None:
    repo, _ = _fixture(tmp_path, same_reviewer=True)
    assert _run(tmp_path, repo).returncode == 3
    assert not (tmp_path / "result.json").exists()


def test_rejects_weaker_replacement(tmp_path: Path) -> None:
    repo, _ = _fixture(tmp_path, weak=True)
    assert _run(tmp_path, repo).returncode == 3


def test_rejects_undeclared_obligation_change(tmp_path: Path) -> None:
    repo, _ = _fixture(tmp_path, declare_replacement=False)
    assert _run(tmp_path, repo).returncode == 3


def test_rejects_undeclared_supported_behavior_change(tmp_path: Path) -> None:
    repo, _ = _fixture(tmp_path, declare_row=False)
    assert _run(tmp_path, repo).returncode == 3


def test_result_is_immutable(tmp_path: Path) -> None:
    repo, _ = _fixture(tmp_path)
    assert _run(tmp_path, repo).returncode == 0
    assert _run(tmp_path, repo).returncode == 3
