# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import base64
import copy
import errno
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from importlib import metadata as importlib_metadata
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

AUDITED_BASE_SHA = "14c1befff886215d928f1c3f6b412b843b902671"
AUDITED_BASE_TREE = "38dcd26db9a467c850c75d4af0e6c932c3d0ecd7"
SCHEMA_VERSION = "metriplane.baseline-snapshot.v1"
EXPECTED_NODE_IDS_SHA256 = "ba68bcaa580c7e392a435ddedd254a6487d8032db3e1e23ad0e6793c5e2a4469"
EXPECTED_AUTHORITY_SHA256 = "40f105fd42388945af2f1885ce8abcbff22764531ccb2661afe98fbf5459b0cf"

OBLIGATION_IDS = (
    "MP2-000.OBL.PREEDIT_BASELINE",
    "MP2-000.OBL.CAPTURE_VALID",
    "MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER",
    "MP2-000.OBL.THREE_RUN_DETERMINISM",
    "MP2-000.OBL.INSTALLED_HELP_AND_RESOURCES",
    "MP2-000.OBL.SCHEMA_AND_CHECKSUM",
    "MP2-000.OBL.DOCS_PARITY",
    "MP2-000.OBL.FINAL_CLEAN_TREE",
)

HELP_IDENTITIES = {
    "metriplane": (
        1034,
        "11ca5ddd640693091a77ef825007b7c9f9be5a993e482ab3fa16aa543dadbefd",
    ),
    "metriplane-run": (
        587,
        "16ecd4bf8f45f14aba40d5cb9859914ad75c1c18504ff0a283254591c7c572ef",
    ),
}

RESOURCE_IDENTITIES = {
    "assets/assembly_cell_missing_tool.jsonl": (
        "a10ea2a25fb9cc09e599ab28f6c8aaec41b5aeb92cd397f062da0f2314e349a6"
    ),
    "assets/assembly_cell/assets.yaml": (
        "601e73b12ef2752e1047a27fdd7b5a0840187f2e5b9877e9857095dd15902926"
    ),
    "assets/assembly_cell/contracts.yaml": (
        "1be158e6a1b50ed0b2514b1f573a2c991547c317d87f1b05b85f0f3afc9a4077"
    ),
    "assets/assembly_cell/process.yaml": (
        "57978f6eafeaad4b97304b73754710e3ddde565d51e2eaf59b01b79f8cb35ca3"
    ),
    "assets/assembly_cell/work_orders.csv": (
        "de2d198c0311bc1c3feb60f82303b867f5278a90aabc8489e85cc4171ab74ea4"
    ),
    "assets/assembly_cell/workspace.yaml": (
        "c876232bc8509bec95b97b528b748a9daa700509c9cc3c779549075e42e3194a"
    ),
}

EXPECTED_ROOT_KEYS = {
    "schema_version",
    "captured_source",
    "tracked_tree",
    "commands_and_help",
    "http_routes",
    "schemas",
    "resources",
    "workflows_and_jobs",
    "tests",
    "environment",
    "limitations",
}


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "baseline_snapshot.py"
SCHEMA_SOURCE = ROOT / "schemas" / "metriplane.baseline-snapshot.v1.schema.json"
DOCS_PATH = ROOT / "docs" / "status" / "baseline-snapshot.md"
_BOOTSTRAP_CLI_PYTHON = Path(sys.executable)

for required_path in (TOOL_PATH, SCHEMA_SOURCE, DOCS_PATH):
    if not required_path.is_file():
        raise RuntimeError(f"required repository artifact is missing: {required_path}")


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "metriplane_baseline_snapshot_under_test", TOOL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def obligation(identifier: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return cast(
        Callable[[Callable[..., Any]], Callable[..., Any]],
        pytest.mark.parametrize("_obligation", [pytest.param(identifier, id=identifier)]),
    )


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_canonical(path: Path, value: Any) -> bytes:
    raw = cast(bytes, tool._canonical_bytes(value))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _command_record(
    command_id: str,
    argv: list[str],
    cwd: str,
    stdout: bytes,
    *,
    stderr: bytes = b"",
    environment: dict[str, str] | None = None,
    exit_code: int = 0,
) -> dict[str, Any]:
    return {
        "command_id": command_id,
        "argv": argv,
        "cwd": cwd,
        "environment": {} if environment is None else environment,
        "exit_code": exit_code,
        "stdout_base64": base64.b64encode(stdout).decode("ascii"),
        "stderr_base64": base64.b64encode(stderr).decode("ascii"),
        "stdout_sha256": _sha(stdout),
        "stderr_sha256": _sha(stderr),
    }


def _filesystem_home_cache(repo: Path, *, suffix: str = "primary") -> dict[str, Any]:
    synthetic_root = repo / f"synthetic-bootstrap-{suffix}"
    environment = {
        "HOME": str(synthetic_root / "home"),
        "XDG_CONFIG_HOME": str(synthetic_root / "xdg/config"),
        "XDG_CACHE_HOME": str(synthetic_root / "xdg/cache"),
        "XDG_DATA_HOME": str(synthetic_root / "xdg/data"),
        "XDG_STATE_HOME": str(synthetic_root / "xdg/state"),
        "TMPDIR": str(synthetic_root / "tmp"),
        "UV_CACHE_DIR": str(synthetic_root / "uv-cache"),
        "UV_PROJECT_ENVIRONMENT": str(synthetic_root / "venv"),
    }
    paths = []
    for kind, path in (
        ("repository_root", str(repo)),
        ("home", environment["HOME"]),
        ("uv_cache_dir", environment["UV_CACHE_DIR"]),
        ("uv_project_environment", environment["UV_PROJECT_ENVIRONMENT"]),
        ("temporary_root", environment["TMPDIR"]),
    ):
        paths.append(
            {
                "kind": kind,
                "path": path,
                "exists": True,
                "is_dir": True,
                "readable": True,
                "writable": True,
                "device": 1,
            }
        )
    return {
        "filesystem_encoding": "utf-8",
        "os_name": "posix",
        "sys_platform": "linux",
        "path_separator": "/",
        "allowlisted_environment": environment,
        "paths": paths,
    }


def _resolved_authority() -> dict[str, Any]:
    schema_names = (
        (
            "canonical_materialization_input_schema",
            "metriplane.bootstrap-materialization-input.v1.schema.json",
        ),
        (
            "bootstrap_environment_observation_schema",
            "metriplane.bootstrap-environment-observation.v1.schema.json",
        ),
        (
            "github_remote_collision_proof_schema",
            "metriplane.github-remote-collision-proof.v1.schema.json",
        ),
        (
            "resolved_bootstrap_authority_schema",
            "metriplane.resolved-bootstrap-authority.v1.schema.json",
        ),
        (
            "resolved_anchors_schema",
            "metriplane.resolved-anchors.v1.schema.json",
        ),
        (
            "materialized_work_order_schema",
            "metriplane.task-work-order.v1.schema.json",
        ),
        (
            "work_order_validation_schema",
            "metriplane.task-work-order-validation.v1.schema.json",
        ),
        (
            "criterion_result_schema",
            "metriplane.validation-result.v1.schema.json",
        ),
    )
    return {
        "authority_path": "13_BOOTSTRAP_EXECUTION_AUTHORITY.json",
        "authority_sha256": EXPECTED_AUTHORITY_SHA256,
        "base_sha": AUDITED_BASE_SHA,
        "base_tree": AUDITED_BASE_TREE,
        "expected_sha256": EXPECTED_AUTHORITY_SHA256,
        "schema_checks": [
            {
                "schema_id": f"https://metriplane.com/schemas/bootstrap/{leaf}",
                "schema_name": name,
                "verdict": "PASS",
            }
            for name, leaf in schema_names
        ],
        "schema_version": "metriplane.resolved-bootstrap-authority.v1",
        "verdict": "PASS",
    }


def _synthetic_environment(repo: Path, *, os_release: str) -> dict[str, Any]:
    filesystem = _filesystem_home_cache(repo)
    bootstrap_root = repo / "synthetic-bootstrap-primary"
    bootstrap_source_root = bootstrap_root / "source"
    git_binary = "/usr/bin/git"
    uv_binary = "/usr/bin/uv"
    sync_python = "/usr/bin/python3.12"
    venv_python = f"{filesystem['allowlisted_environment']['UV_PROJECT_ENVIRONMENT']}/bin/python"
    uname_binary = "/usr/bin/uname"
    installed_distributions = [
        {
            "name": "metriplane",
            "normalized_name": "metriplane",
            "version": "0.3.0",
        }
    ]
    lock_sha256 = "5857debd56a7d0a82bb7057c4edae136644b0887765423e73be41002f8ba5f70"
    declared_environment = {
        "UV_CACHE_DIR": filesystem["allowlisted_environment"]["UV_CACHE_DIR"],
        "UV_PROJECT_ENVIRONMENT": filesystem["allowlisted_environment"]["UV_PROJECT_ENVIRONMENT"],
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
        "LC_ALL": "C.UTF-8",
    }
    setup_specs = (
        (
            "PREPARE_SOURCE_CLONE",
            [
                git_binary,
                "-c",
                "core.hooksPath=/dev/null",
                "clone",
                "--no-hardlinks",
                "--no-checkout",
                str(repo),
                str(bootstrap_source_root),
            ],
            str(bootstrap_root),
            b"",
        ),
        (
            "CHECKOUT_SOURCE_BASE",
            [
                git_binary,
                "-C",
                str(bootstrap_source_root),
                "-c",
                "core.hooksPath=/dev/null",
                "checkout",
                "--detach",
                AUDITED_BASE_SHA,
            ],
            str(bootstrap_root),
            b"",
        ),
        (
            "VERIFY_SOURCE_IDENTITY",
            [
                git_binary,
                "-C",
                str(bootstrap_source_root),
                "rev-parse",
                "HEAD",
                "HEAD^{tree}",
            ],
            str(bootstrap_root),
            f"{AUDITED_BASE_SHA}\n{AUDITED_BASE_TREE}\n".encode("ascii"),
        ),
        (
            "VERIFY_SOURCE_CLEAN",
            [
                git_binary,
                "-C",
                str(bootstrap_source_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            str(bootstrap_root),
            b"",
        ),
        (
            "SYNC_FROZEN_NONEDITABLE",
            [
                uv_binary,
                "--no-config",
                "--quiet",
                "sync",
                "--python",
                sync_python,
                "--frozen",
                "--all-groups",
                "--no-editable",
            ],
            str(bootstrap_source_root),
            b"",
        ),
        (
            "INSTALL_SCHEMA_VALIDATOR_PINS",
            [
                uv_binary,
                "--no-config",
                "--quiet",
                "pip",
                "install",
                "--python",
                venv_python,
                "jsonschema==4.25.1",
                "rfc3339-validator==0.1.4",
            ],
            str(bootstrap_source_root),
            b"",
        ),
    )
    setup_records = [
        _command_record(
            command_id,
            argv,
            cwd,
            stdout,
            environment=declared_environment,
        )
        for command_id, argv, cwd, stdout in setup_specs
    ]
    platform_program = (
        "import platform,sys; print(platform.platform()); "
        "print(platform.machine()); print(sys.implementation.cache_tag)"
    )
    os_release_program = (
        "import json,platform; d=platform.freedesktop_os_release(); "
        "out={k:d.get(k) for k in ('PRETTY_NAME','ID','VERSION_ID')}; "
        "print(json.dumps(out,ensure_ascii=False,allow_nan=False,sort_keys=True,"
        "separators=(',',':')))"
    )
    lock_program = (
        "import hashlib,pathlib,sys; "
        "print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())"
    )
    installed_program = (
        "import importlib.metadata as m,json,re,unicodedata; "
        "rows=[{'name':unicodedata.normalize('NFC',d.metadata['Name']),"
        "'normalized_name':re.sub(r'[-_.]+','-',unicodedata.normalize('NFC',"
        "d.metadata['Name'])).lower(),'version':unicodedata.normalize('NFC',"
        "d.version)} for d in m.distributions() if d.metadata.get('Name')]; "
        "rows.sort(key=lambda r:r['normalized_name'].encode('utf-8')); "
        "assert len(rows)==len({r['normalized_name'] for r in rows}); "
        "print(json.dumps(rows,ensure_ascii=False,allow_nan=False,sort_keys=True,"
        "separators=(',',':')))"
    )
    filesystem_program = (
        "import json,os,pathlib,sys; "
        "keys=('HOME','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_DATA_HOME',"
        "'XDG_STATE_HOME','TMPDIR','UV_CACHE_DIR','UV_PROJECT_ENVIRONMENT'); "
        "allow={k:os.environ.get(k) for k in keys}; "
        "kinds={'repository_root':sys.argv[1],'home':allow['HOME'],"
        "'uv_cache_dir':allow['UV_CACHE_DIR'],'uv_project_environment':"
        "allow['UV_PROJECT_ENVIRONMENT'],'temporary_root':allow['TMPDIR']}; "
        "rows=[]; [(lambda p,k: rows.append({'kind':k,'path':str(p) if p else "
        "None,'exists':bool(p and p.exists()),'is_dir':bool(p and p.is_dir()),"
        "'readable':bool(p and os.access(p,os.R_OK)),'writable':bool(p and "
        "os.access(p,os.W_OK)),'device':p.stat().st_dev if p and p.exists() else "
        "None}))(pathlib.Path(v).resolve() if v else None,k) for k,v in "
        "kinds.items()]; out={'filesystem_encoding':sys.getfilesystemencoding(),"
        "'os_name':os.name,'sys_platform':sys.platform,'path_separator':os.sep,"
        "'allowlisted_environment':allow,'paths':rows}; "
        "print(json.dumps(out,ensure_ascii=False,allow_nan=False,sort_keys=True,"
        "separators=(',',':')))"
    )
    observation_streams = (
        ("UNAME", [uname_binary, "-srm"], str(repo), b"Linux synthetic x86_64\n"),
        (
            "PYTHON_VERSION",
            [venv_python, "-VV"],
            str(repo),
            b"Python 3.12.13 (synthetic retained observation)\n",
        ),
        (
            "PLATFORM",
            [venv_python, "-c", platform_program],
            str(repo),
            b"Synthetic Linux\nx86_64\ncpython-312\n",
        ),
        (
            "OS_RELEASE",
            [venv_python, "-c", os_release_program],
            str(repo),
            tool._canonical_bytes({"ID": "synthetic", "PRETTY_NAME": os_release, "VERSION_ID": "1"})
            + b"\n",
        ),
        (
            "UV_VERSION",
            [uv_binary, "--version"],
            str(repo),
            b"uv 0.12.0 (synthetic retained observation)\n",
        ),
        (
            "LOCK_SHA256",
            [venv_python, "-c", lock_program, f"{repo}/uv.lock"],
            str(repo),
            f"{lock_sha256}\n".encode("ascii"),
        ),
        (
            "INSTALLED_DISTRIBUTIONS",
            [venv_python, "-c", installed_program],
            str(bootstrap_root),
            tool._canonical_bytes(installed_distributions) + b"\n",
        ),
        (
            "FILESYSTEM_HOME_CACHE",
            [venv_python, "-c", filesystem_program, str(repo)],
            str(repo),
            tool._canonical_bytes(filesystem) + b"\n",
        ),
    )
    observation_records = [
        _command_record(
            command_id,
            argv,
            cwd,
            stdout,
            environment=declared_environment,
        )
        for command_id, argv, cwd, stdout in observation_streams
    ]
    return {
        "schema_version": "metriplane.bootstrap-environment-observation.v1",
        "task_id": "MP2-000",
        "base_sha": AUDITED_BASE_SHA,
        "repository_root": str(repo),
        "bootstrap_source_root": str(bootstrap_source_root),
        "declared_environment": declared_environment,
        "setup_command_results": setup_records,
        "derived": {
            "profile": "bootstrap-lock-derived-root-suite",
            "os_release": os_release,
            "kernel": "Linux synthetic x86_64",
            "architecture": "x86_64",
            "python": "Python 3.12.13 (synthetic retained observation)",
            "uv": "uv 0.12.0 (synthetic retained observation)",
            "lock_sha256": lock_sha256,
            "installed_distributions": installed_distributions,
            "filesystem": f"sha256:{_sha(tool._canonical_bytes(filesystem))}",
            "filesystem_home_cache": filesystem,
            "browser": None,
            "hardware": None,
        },
        "observation_command_results": observation_records,
    }


def _synthetic_remote_proof(repo: Path) -> dict[str, Any]:
    git_binary = "/usr/bin/git"
    proof_root = str(repo / "synthetic-remote-proof")
    proof_repository = f"{proof_root}/proof.git"
    git_dir = f"--git-dir={proof_repository}"
    actor = dict(tool.EXPECTED_GITHUB_ACTOR)
    remote_snapshot = {
        "repository": {
            "database_id": 1,
            "full_name": "Miko997/metriplane",
            "default_branch": "main",
            "default_branch_sha": AUDITED_BASE_SHA,
            "origin_url": "https://github.com/Miko997/metriplane.git",
        },
        "branches": [{"head_sha": AUDITED_BASE_SHA, "name": "main"}],
        "open_pull_requests": [],
    }
    receipts = [
        tool._receipt(
            "mcp__codex_apps__github_get_repo",
            None,
            {"repository_full_name": "Miko997/metriplane"},
            remote_snapshot["repository"],
        ),
        tool._receipt(
            "mcp__codex_apps__github_get_user_login",
            None,
            {},
            {"database_id": actor["database_id"], "login": actor["login"]},
        ),
        tool._receipt(
            "mcp__codex_apps__github_get_repo_collaborator_permission",
            None,
            {
                "repository_full_name": "Miko997/metriplane",
                "username": actor["login"],
            },
            actor["permission"],
        ),
        tool._receipt(
            "mcp__codex_apps__github_search_prs",
            None,
            {
                "order": "asc",
                "query": "is:pr is:open",
                "repository_full_name": "Miko997/metriplane",
                "sort": "created",
                "state": "open",
                "topn": 100,
            },
            [],
        ),
    ]
    git_ids = (
        "LS_REMOTE_HEADS",
        "INIT_BARE",
        "REMOTE_ADD",
        "FETCH_BRANCHES",
        "LIST_FETCHED_REFS",
        f"LS_TREE_{AUDITED_BASE_SHA}",
        f"GREP_{AUDITED_BASE_SHA}",
        "HISTORY_CREATE_PATHS",
    )
    git_argv = {
        "LS_REMOTE_HEADS": [git_binary, "ls-remote", "--heads", "origin"],
        "INIT_BARE": [git_binary, "init", "--bare", proof_repository],
        "REMOTE_ADD": [
            git_binary,
            git_dir,
            "remote",
            "add",
            "origin",
            "https://github.com/Miko997/metriplane.git",
        ],
        "FETCH_BRANCHES": [
            git_binary,
            git_dir,
            "fetch",
            "--no-tags",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
        ],
        "LIST_FETCHED_REFS": [
            git_binary,
            git_dir,
            "for-each-ref",
            "--sort=refname",
            "--format=%(objectname)%09%(refname)",
            "refs/remotes/origin/",
            "refs/remotes/pull/",
        ],
        f"LS_TREE_{AUDITED_BASE_SHA}": [
            git_binary,
            git_dir,
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            AUDITED_BASE_SHA,
        ],
        f"GREP_{AUDITED_BASE_SHA}": [
            git_binary,
            git_dir,
            "grep",
            "-I",
            "-n",
            "-i",
            "-E",
            "baseline[-_ ]snapshot|MP2-000|MET-69",
            AUDITED_BASE_SHA,
            "--",
            ".",
        ],
        "HISTORY_CREATE_PATHS": [
            git_binary,
            git_dir,
            "log",
            "--all",
            "--format=%H",
            "--name-only",
            "-z",
            "--",
            *tool.EXPECTED_CREATE_PATHS,
        ],
    }
    git_records = []
    for command_id in git_ids:
        stdout = b""
        if command_id == "LS_REMOTE_HEADS":
            stdout = f"{AUDITED_BASE_SHA}\trefs/heads/main\n".encode("ascii")
        elif command_id == "LIST_FETCHED_REFS":
            stdout = f"{AUDITED_BASE_SHA}\trefs/remotes/origin/main\n".encode("ascii")
        git_records.append(
            _command_record(
                command_id,
                git_argv[command_id],
                str(repo) if command_id == "LS_REMOTE_HEADS" else proof_root,
                stdout,
                environment={"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8"},
                exit_code=1 if command_id.startswith("GREP_") else 0,
            )
        )
    return {
        "schema_version": "metriplane.github-remote-collision-proof.v1",
        "provider": "GitHub",
        "base_sha": AUDITED_BASE_SHA,
        "authenticated_actor": actor,
        "target_paths": list(tool.EXPECTED_CREATE_PATHS),
        "semantic_regex": "baseline[-_ ]snapshot|MP2-000|MET-69",
        "collection_contract": {
            "repository_tool": "mcp__codex_apps__github_get_repo",
            "actor_tool": "mcp__codex_apps__github_get_user_login",
            "permission_tool": "mcp__codex_apps__github_get_repo_collaborator_permission",
            "open_pr_tool": "mcp__codex_apps__github_search_prs",
            "open_pr_limit": 100,
            "pr_detail_tool": "mcp__codex_apps__github_fetch_pr",
            "pr_files_tool": "mcp__codex_apps__github_list_pr_changed_filenames",
            "branch_argv": [git_binary, "ls-remote", "--heads", "origin"],
            "inspection_mode": "fresh-isolated-bare-fetch",
        },
        "remote_snapshot": remote_snapshot,
        "remote_snapshot_sha256": _sha(tool._canonical_bytes(remote_snapshot)),
        "collection_receipts": receipts,
        "isolated_fetch": {
            "branch_ref_set_equal": True,
            "open_pr_head_set_equal": True,
            "default_branch_head_equal_base": True,
            "unavailable_heads": [],
        },
        "inspected_heads": [
            {
                "head_sha": AUDITED_BASE_SHA,
                "source_refs": ["refs/heads/main"],
                "exact_path_hits": [],
                "semantic_path_hits": [],
                "semantic_content_hits": [],
            }
        ],
        "history_hits": [],
        "ownership_metadata_hits": [],
        "collisions": [],
        "completeness": {
            "repository_visible": True,
            "branch_collection_complete": True,
            "open_pr_collection_complete": True,
            "open_pr_returned_count": 0,
            "open_pr_page_limit": 100,
            "all_heads_inspected": True,
            "no_provider_or_fetch_drift": True,
        },
        "git_command_results": git_records,
        "verdict": "NO_COLLISION",
    }


def _synthetic_task_authority() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    task_row = {
        "task_id": "MP2-000",
        "linear_issue": "MET-69",
        "linear_milestone_id": "cbefcf4c-5177-41d7-9ce0-6499e5af9d3c",
        "role": "implementation",
        "authoritative_blocked_by": [],
    }
    issue = {
        "id": "MET-69",
        "identifier": "MET-69",
        "title": "Freeze the v0.3 truth baseline",
        "description_sha256": _sha(b"synthetic exact-authority fixture"),
        "team_id": "synthetic-team",
        "project_id": "synthetic-project",
        "milestone_id": "cbefcf4c-5177-41d7-9ce0-6499e5af9d3c",
        "status_name": "In Progress",
        "status_type": "started",
        "assignee_id": "synthetic-linear-owner",
        "updated_at": "2026-08-24T00:00:00Z",
        "labels": [],
        "attachments": [],
        "relations": [],
    }
    actor = {
        "provider": "Linear",
        "id": "synthetic-linear-owner",
        "name": "Synthetic Owner",
        "display_name": "Synthetic Owner",
        "is_active": True,
    }
    assignment_proof = {
        "schema_version": "metriplane.provider-assignee-proof.v1",
        "provider": "Linear",
        "authenticated_actor_projection": actor,
        "authenticated_actor_projection_sha256": _sha(tool._canonical_bytes(actor)),
        "authenticated_actor_id": actor["id"],
        "assignee_id": actor["id"],
        "repository_executor_linear_actor_id": actor["id"],
        "repository_executor_github_login": "Miko997",
        "issue_id": "MET-69",
        "issue_identifier": "MET-69",
        "issue_cursor": issue["updated_at"],
        "authority_scope": {
            "allowed": [
                "edit, test, retain evidence, commit and push only the exact MP2-000 task branch",
                "open or update the exact MP2-000 pull request and leave it unmerged",
            ],
            "excluded": [
                "merge, tag, publish, protected tracker transition, repository settings and later milestones"
            ],
        },
    }
    return task_row, issue, assignment_proof


def _synthetic_projection_digests(canonical_input: dict[str, Any]) -> dict[str, str]:
    commands = canonical_input["resolved_commands_and_obligations"]
    anchors = canonical_input["resolved_anchors_outputs_contracts"]
    values = {
        "repository_instruction": canonical_input[
            "repository_instruction_state_and_pr_contract_phase"
        ],
        "resolved_obligations": commands["resolved_obligations"],
        "criterion_mapping": commands["criterion_to_test_obligation_mapping"],
        "ordered_outcomes": commands["ordered_pr_outcomes"],
        "produced_contracts": anchors[
            "produced_contract_paths_schemas_producers_validators_consumers"
        ],
        "typed_resource_static": [
            {key: row[key] for key in ("kind", "owner_or_authority", "requirement", "status")}
            for row in canonical_input["typed_people_permissions_secrets_services_hardware"]
        ],
        "manual_actions": canonical_input["manual_and_irreversible_actions"],
        "command_static": [
            {key: row[key] for key in ("command_id", "expected_exit", "expected_outputs")}
            for row in commands["exact_command_ids_argv_expected_exits_outputs"]
        ],
    }
    return {name: _sha(tool._canonical_bytes(value)) for name, value in values.items()}


def _write_synthetic_ready_evidence(repo: Path) -> Path:
    collected = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=repo,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert collected.returncode == 0, collected.stderr.decode("utf-8", "replace")
    node_ids = [
        line
        for line in collected.stdout.decode("utf-8", "strict").splitlines()
        if line.startswith("tests/") and "::" in line
    ]
    assert len(node_ids) == 1194
    assert _sha(tool._canonical_bytes(node_ids)) == EXPECTED_NODE_IDS_SHA256
    root_stdout = b"1192 passed, 2 skipped in 0.01s\n"
    collect_stdout = ("\n".join(node_ids) + "\n\n1194 tests collected in 0.01s\n").encode("utf-8")
    status_stdout = b""
    environment_observation = _synthetic_environment(repo, os_release="Synthetic Linux")
    declared_environment = environment_observation["declared_environment"]
    bootstrap_python = f"{declared_environment['UV_PROJECT_ENVIRONMENT']}/bin/python"
    git_binary = environment_observation["setup_command_results"][0]["argv"][0]
    command_specs = (
        (
            "MP2-000.CMD.ROOT_BASELINE",
            [bootstrap_python, "-m", "pytest", "-q"],
            root_stdout,
        ),
        (
            "MP2-000.CMD.COLLECT_BASELINE",
            [bootstrap_python, "-m", "pytest", "--collect-only", "-q"],
            collect_stdout,
        ),
        (
            "MP2-000.CMD.STATUS_IDENTITY",
            [git_binary, "status", "--porcelain=v1"],
            status_stdout,
        ),
    )
    command_records = [
        _command_record(
            command_id,
            argv,
            str(repo),
            stdout,
            environment=declared_environment,
        )
        for command_id, argv, stdout in command_specs
    ]
    manifest_commands = [
        {
            "command_id": record["command_id"],
            "argv": record["argv"],
            "cwd": record["cwd"],
            "environment": record["environment"],
            "expected_exit": 0,
            "expected_outputs": [],
        }
        for record in command_records
    ]
    remote_proof = _synthetic_remote_proof(repo)
    resolved_authority = _resolved_authority()
    anchors: dict[str, Any] = {}
    environment_digest = _sha(tool._canonical_bytes(environment_observation))
    remote_digest = _sha(tool._canonical_bytes(remote_proof))
    anchors_digest = _sha(tool._canonical_bytes(anchors))
    authority_digest = _sha(tool._canonical_bytes(resolved_authority))
    task_row, issue, assignment_proof = _synthetic_task_authority()
    task_row_digest = _sha(tool._canonical_bytes(task_row))
    issue_digest = _sha(tool._canonical_bytes(issue))
    assignment_digest = _sha(tool._canonical_bytes(assignment_proof))
    catalog_digest = _sha(b"synthetic MP2 work-order catalog")
    repository_instruction = {
        "instruction_paths": ["AGENTS.md"],
        "pr_contract_phase": "bootstrap-create-set",
    }
    create_rows = [
        {
            "path": path,
            "state": "CREATE",
            "owner_task": "MP2-000",
            "absence_or_identity_proof_sha256": anchors_digest,
        }
        for path in tool.EXPECTED_CREATE_PATHS
    ]
    produced_contracts = [
        {
            "path": path,
            "producer_task": "MP2-000",
            "schema_or_media_type": "synthetic exact-contract fixture",
            "validator_command_id": "MP2-000.CMD.TASK_TESTS",
            "consumers": ["MP2-007"],
        }
        for path in tool.EXPECTED_CREATE_PATHS
    ]
    setup_commands = [
        {
            "command_id": record["command_id"],
            "argv": record["argv"],
            "cwd": record["cwd"],
        }
        for record in environment_observation["setup_command_results"]
    ]
    resolved_obligations = [
        {
            "obligation_id": obligation_id,
            "command_ids": [manifest_commands[index % len(manifest_commands)]["command_id"]],
            "details": f"Synthetic exact obligation fixture for {obligation_id}",
        }
        for index, obligation_id in enumerate(OBLIGATION_IDS)
    ]
    criterion_mapping = [
        {
            "criterion_id": f"MP2-000.CRITERION.{index + 1}",
            "obligation_ids": [obligation_id],
            "expected_outcome": "PASS",
        }
        for index, obligation_id in enumerate(OBLIGATION_IDS)
    ]
    ordered_outcomes = [
        {
            "order": index + 1,
            "path": path,
            "outcome": "review-ready artifact",
        }
        for index, path in enumerate(tool.EXPECTED_CREATE_PATHS)
    ]
    typed_resources = [
        {
            "kind": "github_repository_read_visibility",
            "status": "AVAILABLE",
            "owner_or_authority": "repository_task_branch_pr_writer",
            "requirement": "read-only repository visibility",
            "availability_evidence_sha256": _sha(
                tool._canonical_bytes(remote_proof["authenticated_actor"])
            ),
        }
    ]
    manual_actions = [
        {
            "action": "merge or release",
            "disposition": "human-controlled and prohibited to this task agent",
        }
    ]
    environment_row = {
        "architecture": environment_observation["derived"]["architecture"],
        "browser": None,
        "claim_level": "bootstrap_execution_observation_only",
        "evidence_use": "Synthetic test-only bootstrap observation.",
        "filesystem": environment_observation["derived"]["filesystem"],
        "hardware": None,
        "kernel": environment_observation["derived"]["kernel"],
        "observation_sha256": environment_digest,
        "os_release": environment_observation["derived"]["os_release"],
        "profile": "bootstrap-lock-derived-root-suite",
        "python": environment_observation["derived"]["python"],
        "row_id": f"BOOTSTRAP.MP2-000.{environment_digest[:16]}",
        "support_disposition": "not_measured",
        "uv": environment_observation["derived"]["uv"],
    }
    resolved_commands = {
        "ordered_pr_outcomes": ordered_outcomes,
        "resolved_obligations": resolved_obligations,
        "criterion_to_test_obligation_mapping": criterion_mapping,
        "toolchain_setup_commands": setup_commands,
        "exact_command_ids_argv_expected_exits_outputs": manifest_commands,
    }
    canonical_input: dict[str, Any] = {
        "schema_version": "metriplane.bootstrap-materialization-input.v1",
        "base_sha": AUDITED_BASE_SHA,
        "canonical_task_row": {
            "catalog_schema_version": "metriplane.mp2-work-order-set.v1",
            "catalog_sha256": catalog_digest,
            "row_sha256": task_row_digest,
            "row": task_row,
        },
        "repository_instruction_state_and_pr_contract_phase": repository_instruction,
        "live_issue_snapshot_and_relation_cursor": {
            "provider": "Linear",
            "event_cursor": issue["updated_at"],
            "issue_sha256": issue_digest,
            "issue": issue,
        },
        "assignment_or_delegation_proof": {
            "mode": "provider_authenticated_assignee",
            "proof_sha256": assignment_digest,
            "proof": assignment_proof,
        },
        "dependency_evidence": [],
        "resolved_anchors_outputs_contracts": {
            "remote_collision_proofs": [
                {
                    "path": "github-remote-collision-proof.json",
                    "provider": "GitHub",
                    "sha256": remote_digest,
                }
            ],
            "resolved_anchors_sha256": anchors_digest,
            "resolved_bootstrap_authority_sha256": authority_digest,
            "exact_existing_and_CREATE_paths": create_rows,
            "exact_symbols_routes_workflows_schemas": [],
            "consumed_contract_digests": [
                {
                    "contract": "12_TASK_WORK_ORDERS.json",
                    "sha256": catalog_digest,
                },
                {
                    "contract": "13_BOOTSTRAP_EXECUTION_AUTHORITY.json",
                    "sha256": EXPECTED_AUTHORITY_SHA256,
                },
            ],
            "produced_contract_paths_schemas_producers_validators_consumers": produced_contracts,
        },
        "resolved_environment_profiles": {
            "environment_profile_rows": [environment_row],
            "observations": [
                {
                    "path": "environment-observation.json",
                    "sha256": environment_digest,
                }
            ],
        },
        "resolved_commands_and_obligations": resolved_commands,
        "typed_people_permissions_secrets_services_hardware": typed_resources,
        "manual_and_irreversible_actions": manual_actions,
    }
    materialization_id = _sha(tool._canonical_bytes(canonical_input))
    instance = repo / "build" / "work-orders" / "MP2-000" / AUDITED_BASE_SHA / materialization_id
    instance.mkdir(parents=True)
    assignment_actor = assignment_proof["authenticated_actor_id"]
    manifest = {
        "schema_version": "metriplane.task-work-order.v1",
        "task_id": "MP2-000",
        "linear_issue": "MET-69",
        "base_sha": AUDITED_BASE_SHA,
        "materialization_id": materialization_id,
        "canonical_materialization_input_digest": materialization_id,
        "signed_assignment_or_delegation_record_digest": assignment_digest,
        "assignment_actor_and_authority": {
            "actor_id": assignment_actor,
            "authority": "Linear authenticated assignee at bound issue cursor",
            "authority_scope": assignment_proof["authority_scope"],
            "mode": "provider_authenticated_assignee",
        },
        "linear_issue_snapshot_digest_and_event_cursor": {
            "event_cursor": issue["updated_at"],
            "provider": "Linear",
            "sha256": issue_digest,
        },
        "repository_instruction_state_and_pr_contract_phase": repository_instruction,
        "exact_dependency_ids_and_merged_artifact_proof": [],
        "exact_existing_and_CREATE_paths": create_rows,
        "exact_symbols_routes_workflows_schemas": [],
        "produced_contract_paths_schemas_producers_validators_consumers": produced_contracts,
        "consumed_contract_digests": canonical_input["resolved_anchors_outputs_contracts"][
            "consumed_contract_digests"
        ],
        "environment_profile_rows": [environment_row],
        "exact_command_ids_argv_expected_exits_outputs": manifest_commands,
        "criterion_to_test_obligation_mapping": criterion_mapping,
        "ordered_pr_outcomes": ordered_outcomes,
        "people_permissions_secrets_services_hardware": typed_resources,
        "manual_and_irreversible_actions": manual_actions,
        "clean_tree": {
            "is_clean": True,
            "status_porcelain_sha256": _sha(b""),
        },
        "compatibility_and_non_goals": {
            "compatibility_and_rollback": {},
            "out_of_scope": [],
        },
        "evidence_and_downstream_handoff": {
            "downstream_handoff": {},
            "evidence_output": [],
        },
        "stop_conditions": ["synthetic fixture stop condition"],
    }

    core_values = {
        "work-order.json": manifest,
        "canonical-materialization-input.json": canonical_input,
        "environment-observation.json": environment_observation,
        "github-remote-collision-proof.json": remote_proof,
        "resolved-bootstrap-authority.json": resolved_authority,
        "resolved-anchors.json": anchors,
    }
    core_raw = {
        filename: _write_canonical(instance / filename, value)
        for filename, value in core_values.items()
    }
    assert _sha(core_raw["resolved-bootstrap-authority.json"]) == (
        "c8aab5496882c3a01553d604b1ad8437d0dafa73287d135a668342cf9de4f378"
    )

    tests = {
        "collection": {
            "exit_code": 0,
            "count": len(node_ids),
            "node_ids": node_ids,
            "stdout_sha256": _sha(collect_stdout),
            "stderr_sha256": _sha(b""),
            "warning_count": 0,
        },
        "execution": {
            "exit_code": 0,
            "collected_count": len(node_ids),
            "passed_count": len(node_ids) - 2,
            "failed_count": 0,
            "error_count": 0,
            "skipped_count": 2,
            "xfailed_count": 0,
            "xpassed_count": 0,
            "warning_count": 0,
            "deselected_count": 0,
            "retry_count": 0,
            "failure_node_ids": [],
        },
        "status_identity": {
            "exit_code": 0,
            "clean": True,
            "stdout_sha256": _sha(status_stdout),
            "stderr_sha256": _sha(b""),
        },
    }
    evidence = {
        "schema_version": tool.BASELINE_EVIDENCE_VERSION,
        "task_id": "MP2-000",
        "base_sha": AUDITED_BASE_SHA,
        "materialization_id": materialization_id,
        "commands": command_records,
        "tests": tests,
    }
    preedit_raw = _write_canonical(instance / "evidence" / "pre-edit-baseline.json", evidence)
    preedit_digest = _sha(preedit_raw)

    check_ids = tuple(tool.EXPECTED_VALIDATION_CHECK_IDS)
    checks = [
        {
            "check_id": check_id,
            "evidence": f"synthetic canonical fixture proof for {check_id}",
            "verdict": "PASS",
        }
        for check_id in check_ids
    ]
    review_evidence = {
        "findings": [],
        "method": "independent_agent_review",
        "reviewed_authority_sha256": EXPECTED_AUTHORITY_SHA256,
        "reviewed_canonical_input_sha256": _sha(core_raw["canonical-materialization-input.json"]),
        "reviewed_check_ids": list(check_ids),
        "reviewed_environment_observation_sha256": _sha(core_raw["environment-observation.json"]),
        "reviewed_github_remote_collision_proof_sha256": _sha(
            core_raw["github-remote-collision-proof.json"]
        ),
        "reviewed_manifest_sha256": _sha(core_raw["work-order.json"]),
        "reviewed_resolved_anchors_sha256": _sha(core_raw["resolved-anchors.json"]),
        "reviewed_resolved_bootstrap_authority_sha256": _sha(
            core_raw["resolved-bootstrap-authority.json"]
        ),
        "reviewer_identity": "synthetic-independent-test-reviewer",
        "schema_version": "metriplane.independent-work-order-review.v1",
        "verdict": "APPROVED",
    }
    review = {
        "method": "independent_agent_review",
        "review_evidence": review_evidence,
        "review_evidence_sha256": _sha(tool._canonical_bytes(review_evidence)),
        "reviewed_manifest_sha256": _sha(core_raw["work-order.json"]),
        "reviewer_identity": "synthetic-independent-test-reviewer",
        "verdict": "APPROVED",
    }
    validation = {
        "schema_version": "metriplane.task-work-order-validation.v1",
        "task_id": "MP2-000",
        "base_sha": AUDITED_BASE_SHA,
        "materialization_id": materialization_id,
        "manifest_sha256": _sha(core_raw["work-order.json"]),
        "canonical_input_sha256": _sha(core_raw["canonical-materialization-input.json"]),
        "environment_observation_sha256": _sha(core_raw["environment-observation.json"]),
        "github_remote_collision_proof_sha256": _sha(
            core_raw["github-remote-collision-proof.json"]
        ),
        "github_actor_permission_sha256": _sha(
            tool._canonical_bytes(remote_proof["authenticated_actor"])
        ),
        "authority_sha256": EXPECTED_AUTHORITY_SHA256,
        "validated_at": "2026-08-24T00:00:00Z",
        "verdict": "READY",
        "exit_code": 0,
        "checks": checks,
        "review": review,
    }
    validation_raw = _write_canonical(instance / "work-order-validation.json", validation)

    _write_canonical(
        instance.parent / "synthetic-identity-overrides.json",
        {
            "materialization_id": materialization_id,
            "work_order_manifest_bytes": len(core_raw["work-order.json"]),
            "work_order_manifest_sha256": _sha(core_raw["work-order.json"]),
            "work_order_validation_bytes": len(validation_raw),
            "work_order_validation_sha256": _sha(validation_raw),
            "manifest_only_projection_sha256": {
                field: _sha(tool._canonical_bytes(manifest[field]))
                for field in tool.EXPECTED_MANIFEST_ONLY_PROJECTION_SHA256
            },
            "preedit_baseline_sha256": preedit_digest,
            "catalog_sha256": catalog_digest,
            "task_row_sha256": task_row_digest,
            "issue_sha256": issue_digest,
            "assignment_proof_sha256": assignment_digest,
            "resolved_anchors_sha256": anchors_digest,
            "canonical_projection_sha256": _synthetic_projection_digests(canonical_input),
        },
    )

    history_environment = _synthetic_environment(repo, os_release="Synthetic Linux History")
    history_environment_digest = _sha(tool._canonical_bytes(history_environment))
    history_input = copy.deepcopy(canonical_input)
    history_profile = history_input["resolved_environment_profiles"]
    history_profile["observations"][0]["sha256"] = history_environment_digest
    history_row = history_profile["environment_profile_rows"][0]
    history_row.update(
        {
            "observation_sha256": history_environment_digest,
            "os_release": history_environment["derived"]["os_release"],
            "row_id": f"BOOTSTRAP.MP2-000.{history_environment_digest[:16]}",
        }
    )
    history_id = _sha(tool._canonical_bytes(history_input))
    history = instance.parent / history_id
    history.mkdir()
    history_manifest = copy.deepcopy(manifest)
    history_manifest["materialization_id"] = history_id
    history_manifest["canonical_materialization_input_digest"] = history_id
    history_manifest["environment_profile_rows"] = [history_row]
    history_values = {
        "work-order.json": history_manifest,
        "canonical-materialization-input.json": history_input,
        "environment-observation.json": history_environment,
        "github-remote-collision-proof.json": remote_proof,
        "resolved-bootstrap-authority.json": resolved_authority,
        "resolved-anchors.json": anchors,
    }
    history_raw = {
        filename: _write_canonical(history / filename, value)
        for filename, value in history_values.items()
    }
    history_validation = copy.deepcopy(validation)
    history_validation.update(
        {
            "materialization_id": history_id,
            "manifest_sha256": _sha(history_raw["work-order.json"]),
            "canonical_input_sha256": _sha(history_raw["canonical-materialization-input.json"]),
            "environment_observation_sha256": _sha(history_raw["environment-observation.json"]),
            "github_remote_collision_proof_sha256": _sha(
                history_raw["github-remote-collision-proof.json"]
            ),
            "authority_sha256": EXPECTED_AUTHORITY_SHA256,
        }
    )
    history_review_evidence = copy.deepcopy(review_evidence)
    history_review_evidence.update(
        {
            "reviewed_canonical_input_sha256": _sha(
                history_raw["canonical-materialization-input.json"]
            ),
            "reviewed_environment_observation_sha256": _sha(
                history_raw["environment-observation.json"]
            ),
            "reviewed_github_remote_collision_proof_sha256": _sha(
                history_raw["github-remote-collision-proof.json"]
            ),
            "reviewed_manifest_sha256": _sha(history_raw["work-order.json"]),
            "reviewed_resolved_anchors_sha256": _sha(history_raw["resolved-anchors.json"]),
            "reviewed_resolved_bootstrap_authority_sha256": _sha(
                history_raw["resolved-bootstrap-authority.json"]
            ),
        }
    )
    history_review = copy.deepcopy(review)
    history_review.update(
        {
            "review_evidence": history_review_evidence,
            "review_evidence_sha256": _sha(tool._canonical_bytes(history_review_evidence)),
            "reviewed_manifest_sha256": _sha(history_raw["work-order.json"]),
        }
    )
    history_validation["review"] = history_review
    _write_canonical(history / "work-order-validation.json", history_validation)
    _write_canonical(
        history / "evidence" / "pre-edit-baseline.blocked.json",
        {"verdict": "BLOCKED_NOT_READY"},
    )
    return instance


def _run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    process_env = os.environ.copy()
    process_env.update(
        {
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    if env:
        process_env.update(env)
    return subprocess.run(
        argv,
        cwd=cwd,
        env=process_env,
        capture_output=True,
        check=check,
    )


@pytest.fixture(scope="session", autouse=True)
def installed_bootstrap_cli_python(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Give capture subprocesses a real non-editable candidate installation."""
    global _BOOTSTRAP_CLI_PYTHON
    editable = False
    for distribution in importlib_metadata.distributions(name="metriplane"):
        direct_url = distribution.read_text("direct_url.json")
        direct = json.loads(direct_url) if direct_url else {}
        editable = editable or direct.get("dir_info", {}).get("editable") is True
    if not editable and sys.version_info[:2] == (3, 12):
        yield
        return

    root = tmp_path_factory.mktemp("mp2-000-installed-bootstrap")
    source = root / "source"
    ignored_names = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in ignored_names or name.endswith((".egg-info", ".pyc", ".pyo"))
        }

    shutil.copytree(ROOT, source, ignore=ignore)
    uv = shutil.which("uv")
    assert uv is not None
    cross_minor = sys.version_info[:2] != (3, 12)
    bootstrap_python = "3.12" if cross_minor else sys.executable
    venv = root / "venv"
    sync_args = [
        uv,
        "--no-config",
        "sync",
        "--frozen",
        "--no-editable",
        "--no-dev",
        "--python",
        str(bootstrap_python),
    ]
    sync_env = {"UV_PROJECT_ENVIRONMENT": str(venv)}
    if cross_minor:
        sync_args.append("--managed-python")
        sync_env["UV_PYTHON_INSTALL_DIR"] = str(root / "python")
    else:
        sync_args.insert(3, "--offline")
    installed = _run(
        sync_args,
        cwd=source,
        env=sync_env,
    )
    assert installed.returncode == 0, installed.stderr.decode("utf-8", "replace")
    binary = venv / ("Scripts" if os.name == "nt" else "bin")
    probe = _run(
        [
            str(binary / "python"),
            "-c",
            (
                "import importlib.metadata as m,json,metriplane,sys; "
                "d=m.distribution('metriplane'); "
                "print(json.dumps({'direct_url':json.loads(d.read_text('direct_url.json') "
                "or '{}'),'module':metriplane.__file__,'python':"
                "[sys.version_info.major,sys.version_info.minor]},sort_keys=True))"
            ),
        ],
        cwd=root,
    )
    assert probe.returncode == 0, probe.stderr.decode("utf-8", "replace")
    identity = json.loads(probe.stdout)
    assert identity["direct_url"].get("dir_info", {}).get("editable") is not True
    assert Path(identity["module"]).resolve().is_relative_to(venv.resolve())
    assert identity["python"] == [3, 12]

    previous = _BOOTSTRAP_CLI_PYTHON
    _BOOTSTRAP_CLI_PYTHON = binary / "python"
    try:
        yield
    finally:
        _BOOTSTRAP_CLI_PYTHON = previous


def _validate_value(
    parent: Path,
    value: dict[str, Any],
    schema_path: Path,
) -> tuple[dict[str, Any], str]:
    parent.mkdir(parents=True, exist_ok=True)
    snapshot = parent / tool.SNAPSHOT_LEAF
    checksum = parent / tool.CHECKSUM_LEAF
    schema = parent / "metriplane.baseline-snapshot.v1.schema.json"
    raw = tool._canonical_bytes(value)
    snapshot.write_bytes(raw)
    checksum.write_bytes(f"{_sha(raw)}  {tool.SNAPSHOT_LEAF}\n".encode("ascii"))
    schema.write_bytes(schema_path.read_bytes())
    return cast(
        tuple[dict[str, Any], str],
        tool._validate_artifact(snapshot, schema, checksum),
    )


def _internal_schema_accepts(instance: Any, schema: dict[str, Any]) -> bool:
    try:
        tool._internal_validate(instance, schema)
    except tool.SnapshotError as exc:
        assert exc.code == "SCHEMA_VALIDATION_FAILED"
        return False
    return True


def _pinned_external_schema_accepts(instance: Any, schema: dict[str, Any]) -> bool | None:
    try:
        versions = (
            importlib_metadata.version("jsonschema"),
            importlib_metadata.version("rfc3339-validator"),
        )
    except importlib_metadata.PackageNotFoundError:
        return None
    if versions != ("4.25.1", "0.1.4"):
        return None
    jsonschema_spec = importlib.util.find_spec("jsonschema")
    assert jsonschema_spec is not None
    import jsonschema  # type: ignore[import-untyped]

    validator_class = jsonschema.Draft202012Validator
    validator_class.check_schema(schema)
    validator = validator_class(schema, format_checker=jsonschema.FormatChecker())
    try:
        validator.validate(instance)
    except jsonschema.exceptions.ValidationError:
        return False
    return True


def _run_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return _run([sys.executable, str(TOOL_PATH), *args], cwd=repo)


NONREGULAR_STAT_CLI_WRAPPER = """
import importlib.util,os,pathlib,stat,sys
tool_path=pathlib.Path(sys.argv[1])
target_name=pathlib.Path(sys.argv[2]).name
spec=importlib.util.spec_from_file_location('baseline_snapshot_nonregular_cli',tool_path)
assert spec is not None and spec.loader is not None
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
real_stat=module.os.stat
def fake_stat(path,*args,**kwargs):
    result=real_stat(path,*args,**kwargs)
    if kwargs.get('dir_fd') is not None and str(path)==target_name:
        values=list(result)
        values[0]=stat.S_IFSOCK | 0o600
        return os.stat_result(values)
    return result
module.os.stat=fake_stat
module.os.supports_dir_fd=set(module.os.supports_dir_fd)
module.os.supports_dir_fd.add(fake_stat)
module.os.supports_follow_symlinks=set(module.os.supports_follow_symlinks)
module.os.supports_follow_symlinks.add(fake_stat)
raise SystemExit(module.main(sys.argv[3:]))
"""


def _run_nonregular_stat_cli(
    repo: Path, target: Path, *args: str
) -> subprocess.CompletedProcess[bytes]:
    return _run(
        [
            sys.executable,
            "-c",
            NONREGULAR_STAT_CLI_WRAPPER,
            str(TOOL_PATH),
            str(target),
            *args,
        ],
        cwd=repo,
    )


BOOTSTRAP_CLI_WRAPPER = """
import importlib.util,json,pathlib,sys
tool_path=pathlib.Path(sys.argv[1])
repo=pathlib.Path(sys.argv[2])
spec=importlib.util.spec_from_file_location('baseline_snapshot_cli_under_test',tool_path)
assert spec is not None and spec.loader is not None
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
identity_path=(repo/'build'/'work-orders'/'MP2-000'/module.AUDITED_BASE_SHA/
               'synthetic-identity-overrides.json')
identity=json.loads(identity_path.read_bytes())
module.EXPECTED_MATERIALIZATION_ID=identity['materialization_id']
module.EXPECTED_WORK_ORDER_MANIFEST_BYTES=identity['work_order_manifest_bytes']
module.EXPECTED_WORK_ORDER_MANIFEST_SHA256=identity['work_order_manifest_sha256']
module.EXPECTED_WORK_ORDER_VALIDATION_BYTES=identity['work_order_validation_bytes']
module.EXPECTED_WORK_ORDER_VALIDATION_SHA256=identity['work_order_validation_sha256']
module.EXPECTED_MANIFEST_ONLY_PROJECTION_SHA256=dict(
    identity['manifest_only_projection_sha256'])
module.EXPECTED_PREEDIT_BASELINE_SHA256=identity['preedit_baseline_sha256']
module.EXPECTED_CATALOG_SHA256=identity['catalog_sha256']
module.EXPECTED_TASK_ROW_SHA256=identity['task_row_sha256']
module.EXPECTED_ISSUE_SHA256=identity['issue_sha256']
module.EXPECTED_ASSIGNMENT_PROOF_SHA256=identity['assignment_proof_sha256']
module.EXPECTED_RESOLVED_ANCHORS_SHA256=identity['resolved_anchors_sha256']
module.EXPECTED_CANONICAL_PROJECTION_SHA256.update(
    identity['canonical_projection_sha256'])
raise SystemExit(module.main(sys.argv[3:]))
"""


def _run_bootstrap_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return _run(
        [
            str(_BOOTSTRAP_CLI_PYTHON),
            "-c",
            BOOTSTRAP_CLI_WRAPPER,
            str(TOOL_PATH),
            str(repo),
            *args,
        ],
        cwd=repo,
    )


def _patch_synthetic_identity(repo: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    identity_path = (
        repo
        / "build"
        / "work-orders"
        / "MP2-000"
        / AUDITED_BASE_SHA
        / "synthetic-identity-overrides.json"
    )
    identity = cast(
        dict[str, Any],
        tool._strict_json(identity_path.read_bytes(), require_canonical=True),
    )
    constant_fields = {
        "EXPECTED_MATERIALIZATION_ID": "materialization_id",
        "EXPECTED_WORK_ORDER_MANIFEST_BYTES": "work_order_manifest_bytes",
        "EXPECTED_WORK_ORDER_MANIFEST_SHA256": "work_order_manifest_sha256",
        "EXPECTED_WORK_ORDER_VALIDATION_BYTES": "work_order_validation_bytes",
        "EXPECTED_WORK_ORDER_VALIDATION_SHA256": "work_order_validation_sha256",
        "EXPECTED_PREEDIT_BASELINE_SHA256": "preedit_baseline_sha256",
        "EXPECTED_CATALOG_SHA256": "catalog_sha256",
        "EXPECTED_TASK_ROW_SHA256": "task_row_sha256",
        "EXPECTED_ISSUE_SHA256": "issue_sha256",
        "EXPECTED_ASSIGNMENT_PROOF_SHA256": "assignment_proof_sha256",
        "EXPECTED_RESOLVED_ANCHORS_SHA256": "resolved_anchors_sha256",
    }
    for constant, field in constant_fields.items():
        monkeypatch.setattr(tool, constant, identity[field])
    monkeypatch.setattr(
        tool,
        "EXPECTED_CANONICAL_PROJECTION_SHA256",
        dict(identity["canonical_projection_sha256"]),
    )
    monkeypatch.setattr(
        tool,
        "EXPECTED_MANIFEST_ONLY_PROJECTION_SHA256",
        dict(identity["manifest_only_projection_sha256"]),
    )
    return identity


def _primary_ready_instance(repo: Path) -> Path:
    identity_path = (
        repo
        / "build"
        / "work-orders"
        / "MP2-000"
        / AUDITED_BASE_SHA
        / "synthetic-identity-overrides.json"
    )
    identity = cast(
        dict[str, Any],
        tool._strict_json(identity_path.read_bytes(), require_canonical=True),
    )
    return identity_path.parent / cast(str, identity["materialization_id"])


def _read_canonical_object(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], tool._strict_json(path.read_bytes(), require_canonical=True))


def _refresh_validation_bindings(instance: Path, *, materialization_id: str | None = None) -> None:
    raw = {
        leaf: (instance / leaf).read_bytes()
        for leaf in (
            "work-order.json",
            "canonical-materialization-input.json",
            "environment-observation.json",
            "github-remote-collision-proof.json",
            "resolved-bootstrap-authority.json",
            "resolved-anchors.json",
        )
    }
    remote = _read_canonical_object(instance / "github-remote-collision-proof.json")
    validation_path = instance / "work-order-validation.json"
    validation = _read_canonical_object(validation_path)
    if materialization_id is not None:
        validation["materialization_id"] = materialization_id
    validation.update(
        {
            "manifest_sha256": _sha(raw["work-order.json"]),
            "canonical_input_sha256": _sha(raw["canonical-materialization-input.json"]),
            "environment_observation_sha256": _sha(raw["environment-observation.json"]),
            "github_remote_collision_proof_sha256": _sha(raw["github-remote-collision-proof.json"]),
            "github_actor_permission_sha256": _sha(
                tool._canonical_bytes(remote["authenticated_actor"])
            ),
        }
    )
    review = validation["review"]
    evidence = review["review_evidence"]
    evidence.update(
        {
            "reviewed_canonical_input_sha256": _sha(raw["canonical-materialization-input.json"]),
            "reviewed_environment_observation_sha256": _sha(raw["environment-observation.json"]),
            "reviewed_github_remote_collision_proof_sha256": _sha(
                raw["github-remote-collision-proof.json"]
            ),
            "reviewed_manifest_sha256": _sha(raw["work-order.json"]),
            "reviewed_resolved_anchors_sha256": _sha(raw["resolved-anchors.json"]),
            "reviewed_resolved_bootstrap_authority_sha256": _sha(
                raw["resolved-bootstrap-authority.json"]
            ),
        }
    )
    review["reviewed_manifest_sha256"] = _sha(raw["work-order.json"])
    review["review_evidence_sha256"] = _sha(tool._canonical_bytes(evidence))
    _write_canonical(validation_path, validation)


def _refresh_test_only_raw_identity_bindings(instance: Path) -> None:
    identity_path = instance.parent / "synthetic-identity-overrides.json"
    identity = _read_canonical_object(identity_path)
    manifest_raw = (instance / "work-order.json").read_bytes()
    validation_raw = (instance / "work-order-validation.json").read_bytes()
    identity.update(
        {
            "work_order_manifest_bytes": len(manifest_raw),
            "work_order_manifest_sha256": _sha(manifest_raw),
            "work_order_validation_bytes": len(validation_raw),
            "work_order_validation_sha256": _sha(validation_raw),
        }
    )
    _write_canonical(identity_path, identity)


def _rebind_mutated_materialization(repo: Path, instance: Path) -> Path:
    canonical_path = instance / "canonical-materialization-input.json"
    new_materialization_id = _sha(canonical_path.read_bytes())
    manifest_path = instance / "work-order.json"
    manifest = _read_canonical_object(manifest_path)
    manifest["materialization_id"] = new_materialization_id
    manifest["canonical_materialization_input_digest"] = new_materialization_id
    _write_canonical(manifest_path, manifest)
    evidence_path = instance / "evidence" / "pre-edit-baseline.json"
    evidence = _read_canonical_object(evidence_path)
    evidence["materialization_id"] = new_materialization_id
    preedit_raw = _write_canonical(evidence_path, evidence)
    _refresh_validation_bindings(instance, materialization_id=new_materialization_id)
    rebound = instance.with_name(new_materialization_id)
    instance.rename(rebound)
    identity_path = rebound.parent / "synthetic-identity-overrides.json"
    identity = _read_canonical_object(identity_path)
    identity["materialization_id"] = new_materialization_id
    identity["preedit_baseline_sha256"] = _sha(preedit_raw)
    _write_canonical(identity_path, identity)
    return rebound


def _assert_domain_failure(
    result: subprocess.CompletedProcess[bytes], error_code: str
) -> dict[str, Any]:
    assert result.returncode == 3
    assert result.stdout == b""
    assert b"Traceback" not in result.stderr
    error = tool._strict_json(result.stderr, require_canonical=True)
    assert isinstance(error, dict)
    assert error["ok"] is False
    assert error["error"]["code"] == error_code
    return error


def _fresh_exact_base_repository(target: Path) -> Path:
    result = _run(
        [
            shutil.which("git") or "git",
            "clone",
            "--shared",
            "--quiet",
            "--no-checkout",
            str(ROOT),
            str(target),
        ],
        cwd=target.parent,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    result = _run(
        [
            shutil.which("git") or "git",
            "checkout",
            "--quiet",
            "--detach",
            AUDITED_BASE_SHA,
        ],
        cwd=target,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert _run(["git", "status", "--porcelain=v1"], cwd=target).stdout == b""
    return target


def _fresh_ready_repository(target: Path) -> Path:
    _fresh_exact_base_repository(target)
    exclude = target / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n/build/work-orders/MP2-000/\n/schemas/metriplane.baseline-snapshot.v1.schema.json\n"
        )
    shutil.copyfile(
        SCHEMA_SOURCE,
        target / "schemas" / "metriplane.baseline-snapshot.v1.schema.json",
    )
    _write_synthetic_ready_evidence(target)
    assert _run(["git", "status", "--porcelain=v1"], cwd=target).stdout == b""
    return target


@pytest.fixture(scope="session")
def ready_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("mp2-000-ready") / "repository"
    return _fresh_ready_repository(target)


@pytest.fixture(scope="session")
def schema_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destination = (
        tmp_path_factory.mktemp("mp2-000-schema") / "metriplane.baseline-snapshot.v1.schema.json"
    )
    value = json.loads(SCHEMA_SOURCE.read_text(encoding="utf-8"))
    destination.write_bytes(tool._canonical_bytes(value))
    return destination


@pytest.fixture(scope="session")
def schema_value(schema_path: Path) -> dict[str, Any]:
    value = tool._strict_json(schema_path.read_bytes(), require_canonical=True)
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


@pytest.fixture(scope="session")
def captured_pair(ready_repo: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    parent = tmp_path_factory.mktemp("mp2-000-capture")
    snapshot = parent / tool.SNAPSHOT_LEAF
    checksum = parent / tool.CHECKSUM_LEAF
    result = _run_bootstrap_cli(
        ready_repo,
        "capture",
        "--repo",
        str(ready_repo),
        "--base-sha",
        AUDITED_BASE_SHA,
        "--output",
        str(snapshot),
        "--checksum-output",
        str(checksum),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout == b""
    assert result.stderr == b""
    return snapshot, checksum


@pytest.fixture(scope="session")
def captured_value(captured_pair: tuple[Path, Path]) -> dict[str, Any]:
    value = tool._strict_json(captured_pair[0].read_bytes(), require_canonical=True)
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize(
    "obligation_id",
    [pytest.param(value, id=value) for value in OBLIGATION_IDS],
)
def test_obligation_registry_is_exact_and_stably_collected(obligation_id: str) -> None:
    assert tuple(tool.OBLIGATION_IDS) == OBLIGATION_IDS
    assert obligation_id in tool.OBLIGATION_IDS
    source = Path(__file__).read_text(encoding="utf-8")
    assert source.count(f'"{obligation_id}"') >= 1


def test_production_reviewed_identity_constants_are_not_test_overrides() -> None:
    assert tool.EXPECTED_MATERIALIZATION_ID == (
        "f72ad822f4bc4bd8ebd02a8a41e2662161a634b3246832bfb099e1b150e20478"
    )
    assert tool.EXPECTED_WORK_ORDER_MANIFEST_BYTES == 22_526
    assert tool.EXPECTED_WORK_ORDER_MANIFEST_SHA256 == (
        "d94cb3b4cbdc896a95ffab8e40d5268dda1e372fb18ece31476072d525a8eaaa"
    )
    assert tool.EXPECTED_WORK_ORDER_VALIDATION_SHA256 == (
        "2b475791f0d3b4cdec7ea2f1265de5afddc746b21880b295b096d277fd943d55"
    )
    assert tool.EXPECTED_WORK_ORDER_VALIDATION_BYTES == 4_698
    assert tool.EXPECTED_MANIFEST_ONLY_PROJECTION_SHA256 == {
        "clean_tree": "d71bbec5b3db1754278000bfa0b1acdc2a9303832310e5aebe4e6d18c1c2d3f9",
        "compatibility_and_non_goals": (
            "ccd2a84c61c9d7b147ff4c042df87deabee2b82ad6db0d70572df00e6b7d7eb2"
        ),
        "evidence_and_downstream_handoff": (
            "b56eb93adf6948afe503ef06d4de45c73bc0c04e8689926aa986de1f36d79144"
        ),
        "stop_conditions": ("a16c0e51af6a5db44a3612a5308ca3ed218238818c3b99859b24cd7b61ab96c7"),
    }
    assert tool.EXPECTED_PREEDIT_BASELINE_SHA256 == (
        "90d7afa45338d61121c09ad5b3b8fa5b342f14f2988c507147b35ab083403eb6"
    )
    assert tool.EXPECTED_CATALOG_SHA256 == (
        "f04a69658ae8c0c11c1ad96cb666b03d92cdf2d0a59a7520580487a61a43c161"
    )
    assert tool.EXPECTED_TASK_ROW_SHA256 == (
        "7637789f9430f3d99fa2dba4aff7c15cde68f694fbadaaac31b6f14921e90501"
    )
    assert tool.EXPECTED_ISSUE_SHA256 == (
        "ed1898cceee84957ced7a1973bdacaf879971951c519b9376c625752bb3f1a7f"
    )
    assert tool.EXPECTED_ASSIGNMENT_PROOF_SHA256 == (
        "7d0f9da663e3fc5b9f1e9ad188e802ee64eb6272a47f02a0cd9c92a1b7cfdbd2"
    )
    assert tool.EXPECTED_RESOLVED_ANCHORS_SHA256 == (
        "db692c1e6b37fc887e777faa75f0085d778f99ab2bb46c2af02d8962dfaa4588"
    )
    assert tool.EXPECTED_CANONICAL_PROJECTION_SHA256 == {
        "repository_instruction": "20eadd406136169fc1fe44095c818b95ab34ddb016eed948ae8c4437316ae120",
        "resolved_obligations": "6390534dbd2df86d08d1861dd78e69121983f5fb7d1bda8d6f1d6e23dfc2adb3",
        "criterion_mapping": "2218b807889895a8fd1e0c60b2b5b54129aeb76b5a063cc82989d439f21d0e9b",
        "ordered_outcomes": "80c1da20d787b3473e62811c99158b39468cda57d9b2d41ad3b358ce725b1fd5",
        "produced_contracts": "8d6efca9fde5ad7749409922eb1a59a5d41f0b1c74443a5db23e23c5df03b8b7",
        "typed_resource_static": "0ce68da7882fa75700e4ce4cb1382b4eb64f155b894f41d80679f3afd921ae66",
        "manual_actions": "e966855bda100281d5c20a371f377490366ae45d188e7a01c426f5ade8639ed9",
        "command_static": "7b04707c62dd0c7d68d38b0bd23b0d01c6864713aa3280604ebe5e206656afb1",
    }


@obligation("MP2-000.OBL.PREEDIT_BASELINE")
def test_committed_snapshot_binds_the_audited_base(
    _obligation: str, captured_value: dict[str, Any]
) -> None:
    assert _obligation == OBLIGATION_IDS[0]
    assert captured_value["captured_source"] == {
        "repository": "Miko997/metriplane",
        "commit": AUDITED_BASE_SHA,
        "tree": AUDITED_BASE_TREE,
        "version": "0.3.0",
    }
    tests = captured_value["tests"]
    assert tests["collection"]["count"] == 1194
    assert tests["execution"]["collected_count"] == 1194
    assert tests["execution"]["failed_count"] == 0
    assert tests["execution"]["error_count"] == 0
    assert tests["execution"]["deselected_count"] == 0
    assert tests["execution"]["retry_count"] == 0
    assert tests["execution"]["stdout_sha256"] == _sha(b"1192 passed, 2 skipped in 0.01s\n")
    assert tests["execution"]["stderr_sha256"] == _sha(b"")


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(
    ("candidate_kind", "error_code"),
    [
        pytest.param(
            "malformed",
            "READY_INSTANCE_AMBIGUOUS",
            id="malformed-present-baseline",
        ),
        pytest.param(
            "second-valid",
            "READY_INSTANCE_AMBIGUOUS",
            id="multiple-eligible-ready-instances",
        ),
    ],
)
def test_ready_instance_selection_ignores_absent_history_but_fails_closed(
    _obligation: str,
    candidate_kind: str,
    error_code: str,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    repo = _fresh_ready_repository(tmp_path / "repository")
    instance_root = repo / "build" / "work-orders" / "MP2-000" / AUDITED_BASE_SHA
    instances = sorted(path for path in instance_root.iterdir() if path.is_dir())
    primary = next(
        path for path in instances if (path / "evidence" / "pre-edit-baseline.json").is_file()
    )
    history = next(path for path in instances if path != primary)
    baseline = history / "evidence" / "pre-edit-baseline.json"
    if candidate_kind == "malformed":
        baseline.write_bytes(b"{")
    else:
        value = tool._strict_json(
            (primary / "evidence" / "pre-edit-baseline.json").read_bytes(),
            require_canonical=True,
        )
        value["materialization_id"] = history.name
        _write_canonical(baseline, value)

    with pytest.raises(tool.SnapshotError) as raised:
        tool._instance_core(repo, AUDITED_BASE_SHA)
    assert raised.value.code == error_code


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(
    ("evidence_mutation", "error_code"),
    [
        pytest.param("node-list", "PREEDIT_EVIDENCE_INVALID", id="node-list-vs-raw-collect"),
        pytest.param(
            "collection-count",
            "PREEDIT_EVIDENCE_INVALID",
            id="count-vs-raw-collect",
        ),
        pytest.param("outcomes", "PREEDIT_EVIDENCE_INVALID", id="outcomes-vs-root-summary"),
        pytest.param(
            "failure-ids",
            "PREEDIT_EVIDENCE_INVALID",
            id="failure-ids-vs-root-summary",
        ),
        pytest.param(
            "timing-only",
            "PREEDIT_EVIDENCE_INVALID",
            id="timing-only-raw-stream-rewrite",
        ),
        pytest.param(
            "environment",
            "ENVIRONMENT_EVIDENCE_INVALID",
            id="environment-derived-vs-platform-raw",
        ),
    ],
)
def test_capture_rejects_retained_evidence_that_diverges_from_raw_commands(
    _obligation: str,
    evidence_mutation: str,
    error_code: str,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    repo = _fresh_ready_repository(tmp_path / "repository")
    instance_root = repo / "build" / "work-orders" / "MP2-000" / AUDITED_BASE_SHA
    instance = next(
        path
        for path in instance_root.iterdir()
        if (path / "evidence" / "pre-edit-baseline.json").is_file()
    )
    if evidence_mutation == "environment":
        environment_path = instance / "environment-observation.json"
        environment = tool._strict_json(environment_path.read_bytes(), require_canonical=True)
        environment["derived"]["os_release"] = "Forged Linux"
        environment_raw = _write_canonical(environment_path, environment)
        validation_path = instance / "work-order-validation.json"
        validation = tool._strict_json(validation_path.read_bytes(), require_canonical=True)
        validation["environment_observation_sha256"] = _sha(environment_raw)
        validation["review"]["review_evidence"]["reviewed_environment_observation_sha256"] = _sha(
            environment_raw
        )
        validation["review"]["review_evidence_sha256"] = _sha(
            tool._canonical_bytes(validation["review"]["review_evidence"])
        )
        _write_canonical(validation_path, validation)
        _refresh_test_only_raw_identity_bindings(instance)
    else:
        evidence_path = instance / "evidence" / "pre-edit-baseline.json"
        evidence = tool._strict_json(evidence_path.read_bytes(), require_canonical=True)
        collection = evidence["tests"]["collection"]
        execution = evidence["tests"]["execution"]
        if evidence_mutation == "timing-only":
            root_record = evidence["commands"][0]
            changed_stdout = b"1192 passed, 2 skipped in 0.02s\n"
            root_record["stdout_base64"] = base64.b64encode(changed_stdout).decode("ascii")
            root_record["stdout_sha256"] = _sha(changed_stdout)
        elif evidence_mutation == "node-list":
            _swap_first_two(collection["node_ids"])
        elif evidence_mutation == "collection-count":
            collection["count"] -= 1
        elif evidence_mutation == "outcomes":
            execution["passed_count"] -= 1
            execution["skipped_count"] += 1
        else:
            execution["failure_node_ids"] = [collection["node_ids"][0]]
        _write_canonical(evidence_path, evidence)

    output = tmp_path / "capture" / tool.SNAPSHOT_LEAF
    checksum = tmp_path / "capture" / tool.CHECKSUM_LEAF
    output.parent.mkdir()
    result = _run_bootstrap_cli(
        repo,
        "capture",
        "--repo",
        str(repo),
        "--base-sha",
        AUDITED_BASE_SHA,
        "--output",
        str(output),
        "--checksum-output",
        str(checksum),
    )
    _assert_domain_failure(result, error_code)
    assert not os.path.lexists(output)
    assert not os.path.lexists(checksum)
    assert not [name for name in os.listdir(output.parent) if ".stage." in name]


AUTHORITY_MUTATION_CATEGORIES = (
    "canonical-manifest-projection",
    "validation-review-digest",
    "resolved-anchors-binding",
    "task-issue-assignment-identity",
    "remote-snapshot-receipt-binding",
    "environment-raw-derived-binding",
)


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_capture_rejects_self_rebound_ready_manifest_and_validation(
    _obligation: str,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    repo = _fresh_ready_repository(tmp_path / "repository")
    instance = _primary_ready_instance(repo)
    manifest_path = instance / "work-order.json"
    manifest = _read_canonical_object(manifest_path)
    manifest["clean_tree"] = {
        "is_clean": False,
        "status_porcelain_sha256": "0" * 64,
    }
    manifest["stop_conditions"] = ["forged stop condition"]
    manifest["unreviewed_extra_field"] = {"accepted": True}
    _write_canonical(manifest_path, manifest)
    _refresh_validation_bindings(instance)

    output_parent = tmp_path / "capture"
    output_parent.mkdir()
    output = output_parent / tool.SNAPSHOT_LEAF
    checksum = output_parent / tool.CHECKSUM_LEAF
    result = _run_bootstrap_cli(
        repo,
        "capture",
        "--repo",
        str(repo),
        "--base-sha",
        AUDITED_BASE_SHA,
        "--output",
        str(output),
        "--checksum-output",
        str(checksum),
    )

    _assert_domain_failure(result, "READY_INSTANCE_DIGEST_MISMATCH")
    assert not os.path.lexists(output)
    assert not os.path.lexists(checksum)
    assert not [name for name in os.listdir(output_parent) if ".stage." in name]


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        pytest.param("manifest-keyset", "READY_INSTANCE_INVALID", id="manifest-keyset"),
        pytest.param("manifest-projection", "READY_INSTANCE_INVALID", id="manifest-projection"),
        pytest.param(
            "validation-record",
            "READY_INSTANCE_DIGEST_MISMATCH",
            id="validation-record",
        ),
    ],
)
def test_capture_defense_layers_reject_independently_rebound_ready_records(
    _obligation: str,
    mutation: str,
    expected_error: str,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    repo = _fresh_ready_repository(tmp_path / "repository")
    instance = _primary_ready_instance(repo)
    if mutation == "validation-record":
        validation_path = instance / "work-order-validation.json"
        validation = _read_canonical_object(validation_path)
        validation["validated_at"] = "2099-01-01T00:00:00Z"
        validation["checks"][0]["evidence"] = "forged validation evidence"
        review = validation["review"]
        review["reviewer_identity"] = "forged-reviewer"
        review["review_evidence"]["reviewer_identity"] = "forged-reviewer"
        review["review_evidence_sha256"] = _sha(tool._canonical_bytes(review["review_evidence"]))
        _write_canonical(validation_path, validation)
    else:
        manifest_path = instance / "work-order.json"
        manifest = _read_canonical_object(manifest_path)
        if mutation == "manifest-keyset":
            manifest["unreviewed_extra_field"] = {"accepted": True}
        else:
            manifest["stop_conditions"] = ["forged stop condition"]
        _write_canonical(manifest_path, manifest)
        _refresh_validation_bindings(instance)
        # Test-only overrides bypass the raw pins to exercise the independent
        # keyset and semantic-projection defenses behind them.
        _refresh_test_only_raw_identity_bindings(instance)

    output_parent = tmp_path / "capture"
    output_parent.mkdir()
    output = output_parent / tool.SNAPSHOT_LEAF
    checksum = output_parent / tool.CHECKSUM_LEAF
    result = _run_bootstrap_cli(
        repo,
        "capture",
        "--repo",
        str(repo),
        "--base-sha",
        AUDITED_BASE_SHA,
        "--output",
        str(output),
        "--checksum-output",
        str(checksum),
    )

    _assert_domain_failure(result, expected_error)
    assert not os.path.lexists(output)
    assert not os.path.lexists(checksum)
    assert not [name for name in os.listdir(output_parent) if ".stage." in name]


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize("category", AUTHORITY_MUTATION_CATEGORIES)
def test_capture_rejects_self_consistent_authority_relation_mutations(
    _obligation: str,
    category: str,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    repo = _fresh_ready_repository(tmp_path / "repository")
    instance = _primary_ready_instance(repo)
    canonical_path = instance / "canonical-materialization-input.json"
    canonical = _read_canonical_object(canonical_path)
    manifest_path = instance / "work-order.json"
    manifest = _read_canonical_object(manifest_path)

    if category == "canonical-manifest-projection":
        changed = "human-controlled, prohibited, and synthetically rewritten"
        canonical["manual_and_irreversible_actions"][0]["disposition"] = changed
        manifest["manual_and_irreversible_actions"][0]["disposition"] = changed
        _write_canonical(canonical_path, canonical)
        _write_canonical(manifest_path, manifest)
        instance = _rebind_mutated_materialization(repo, instance)
    elif category == "validation-review-digest":
        validation_path = instance / "work-order-validation.json"
        validation = _read_canonical_object(validation_path)
        review_evidence = validation["review"]["review_evidence"]
        review_evidence["reviewed_check_ids"] = list(
            reversed(review_evidence["reviewed_check_ids"])
        )
        validation["review"]["review_evidence_sha256"] = _sha(
            tool._canonical_bytes(review_evidence)
        )
        _write_canonical(validation_path, validation)
    elif category == "resolved-anchors-binding":
        anchors_path = instance / "resolved-anchors.json"
        anchors = _read_canonical_object(anchors_path)
        anchors["synthetic_rewrite"] = True
        _write_canonical(anchors_path, anchors)
        _refresh_validation_bindings(instance)
    elif category == "task-issue-assignment-identity":
        issue_projection = canonical["live_issue_snapshot_and_relation_cursor"]
        issue_projection["issue"]["title"] = "Synthetic rewritten task title"
        issue_projection["issue_sha256"] = _sha(tool._canonical_bytes(issue_projection["issue"]))
        _write_canonical(canonical_path, canonical)
        instance = _rebind_mutated_materialization(repo, instance)
    elif category == "remote-snapshot-receipt-binding":
        remote_path = instance / "github-remote-collision-proof.json"
        remote = _read_canonical_object(remote_path)
        repository = remote["remote_snapshot"]["repository"]
        repository["database_id"] += 1
        remote["remote_snapshot_sha256"] = _sha(tool._canonical_bytes(remote["remote_snapshot"]))
        remote["collection_receipts"][0] = tool._receipt(
            "mcp__codex_apps__github_get_repo",
            None,
            {"repository_full_name": "Miko997/metriplane"},
            repository,
        )
        _write_canonical(remote_path, remote)
        _refresh_validation_bindings(instance)
    else:
        environment_path = instance / "environment-observation.json"
        environment = _read_canonical_object(environment_path)
        os_record = next(
            row
            for row in environment["observation_command_results"]
            if row["command_id"] == "OS_RELEASE"
        )
        os_release = {"ID": "synthetic", "PRETTY_NAME": "Rewritten Linux", "VERSION_ID": "1"}
        stdout = tool._canonical_bytes(os_release) + b"\n"
        os_record["stdout_base64"] = base64.b64encode(stdout).decode("ascii")
        os_record["stdout_sha256"] = _sha(stdout)
        environment["derived"]["os_release"] = os_release["PRETTY_NAME"]
        _write_canonical(environment_path, environment)
        _refresh_validation_bindings(instance)

    output_parent = tmp_path / "capture"
    output_parent.mkdir()
    output = output_parent / tool.SNAPSHOT_LEAF
    checksum = output_parent / tool.CHECKSUM_LEAF
    result = _run_bootstrap_cli(
        repo,
        "capture",
        "--repo",
        str(repo),
        "--base-sha",
        AUDITED_BASE_SHA,
        "--output",
        str(output),
        "--checksum-output",
        str(checksum),
    )
    assert result.returncode == 3
    assert result.stdout == b""
    error = tool._strict_json(result.stderr, require_canonical=True)
    assert error["ok"] is False
    assert not os.path.lexists(output)
    assert not os.path.lexists(checksum)
    assert not [name for name in os.listdir(output_parent) if ".stage." in name]


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_git_read_only_environment_is_consistent_for_all_object_reads(
    _obligation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    oid = "0" * 40
    objects = object.__new__(tool.GitObjects)
    objects.repo = tmp_path
    objects.git = "/synthetic/git"
    objects.entries = [{"blob_oid": oid}]
    observed: list[tuple[list[str], dict[str, str], bytes | None]] = []

    for name in tool.GIT_READ_ONLY_ENVIRONMENT:
        monkeypatch.setenv(name, "unsafe-inherited-value")

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed.append((argv, kwargs["env"], kwargs.get("input")))
        stdout = (
            f"{oid} blob 1\nX\n".encode("ascii")
            if argv[-2:] == ["cat-file", "--batch"]
            else b"ok\n"
        )
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    assert objects.run("rev-parse", "HEAD") == b"ok\n"
    assert objects._read_blobs() == {oid: b"X"}

    assert len(observed) == 2
    assert observed[0][2] is None
    assert observed[1][2] == f"{oid}\n".encode("ascii")
    for _, environment, _ in observed:
        assert {
            name: environment[name] for name in tool.GIT_READ_ONLY_ENVIRONMENT
        } == tool.GIT_READ_ONLY_ENVIRONMENT


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_git_batch_parser_preserves_framing_bounds_and_process_failures(
    _obligation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    oid = "1" * 40
    objects = object.__new__(tool.GitObjects)
    objects.repo = tmp_path
    objects.git = "/synthetic/git"
    objects.entries = [{"blob_oid": oid}]
    valid = f"{oid} blob 1\nX\n".encode("ascii")
    response = subprocess.CompletedProcess([objects.git], 0, stdout=valid, stderr=b"")

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        del argv, kwargs
        return response

    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    cases = (
        (valid + b"trailing", b"", 0, "MALFORMED_CAT_FILE"),
        (
            f"{oid} blob {tool.MAX_GIT_BLOB_BYTES + 1}\n".encode("ascii"),
            b"",
            0,
            "INVALID_CAT_FILE",
        ),
        (valid, b"unexpected stderr", 0, "CAT_FILE_FAILED"),
        (b"", b"", 1, "CAT_FILE_FAILED"),
    )
    for stdout, stderr, returncode, expected_code in cases:
        response = subprocess.CompletedProcess(
            [objects.git], returncode, stdout=stdout, stderr=stderr
        )
        with pytest.raises(tool.SnapshotError) as raised:
            objects._read_blobs()
        assert raised.value.code == expected_code


BLOCKED_GIT_BATCH_RUNNER = """
import importlib.util,pathlib,sys
tool_path=pathlib.Path(sys.argv[1])
repo=pathlib.Path(sys.argv[2])
git=sys.argv[3]
count=int(sys.argv[4])
spec=importlib.util.spec_from_file_location('blocked_git_batch_tool',tool_path)
assert spec is not None and spec.loader is not None
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
objects=object.__new__(module.GitObjects)
objects.repo=repo
objects.git=git
oids=[f'{index:040x}' for index in range(1,count+1)]
objects.entries=[{'blob_oid':oid} for oid in oids]
blobs=objects._read_blobs()
assert len(blobs)==count
assert blobs[oids[0]].startswith(b'GIT_NO_LAZY_FETCH=1;GIT_NO_REPLACE_OBJECTS=1;')
assert b'GIT_OPTIONAL_LOCKS=0;GIT_TERMINAL_PROMPT=0;LC_ALL=C.UTF-8' in blobs[oids[0]]
assert blobs[oids[-1]]==b'Z'
"""


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_git_batch_drains_large_output_while_supplying_large_input(
    _obligation: str, tmp_path: Path
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    count = 4096
    git = tmp_path / "blocking-git"
    git_program = tmp_path / "blocking_git.py"
    git_program.write_text(
        "import os,sys\n"
        "count=int(os.environ['MP2_TEST_OID_COUNT'])\n"
        "oids=[f'{index:040x}' for index in range(1,count+1)]\n"
        "names=('GIT_NO_LAZY_FETCH','GIT_NO_REPLACE_OBJECTS','GIT_OPTIONAL_LOCKS',"
        "'GIT_TERMINAL_PROMPT','LC_ALL')\n"
        "marker=';'.join(f'{name}={os.environ.get(name)}' for name in names).encode()\n"
        "payload=marker+b'\\0'+b'X'*(256*1024-len(marker)-1)\n"
        "stream=sys.stdout.buffer\n"
        "stream.write(f'{oids[0]} blob {len(payload)}\\n'.encode()+payload+b'\\n')\n"
        "stream.flush()\n"
        "requests=sys.stdin.buffer.read().splitlines()\n"
        "if requests != [oid.encode() for oid in oids]:\n"
        "    sys.stderr.write('unexpected batch request')\n"
        "    raise SystemExit(91)\n"
        "for oid in oids[1:]:\n"
        "    stream.write(f'{oid} blob 1\\nZ\\n'.encode())\n"
        "stream.flush()\n",
        encoding="utf-8",
    )
    git.write_text(
        '#!/bin/sh\nexec "$MP2_TEST_PYTHON" "$MP2_TEST_GIT_SCRIPT" "$@"\n',
        encoding="utf-8",
    )
    git.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "MP2_TEST_OID_COUNT": str(count),
            "MP2_TEST_PYTHON": sys.executable,
            "MP2_TEST_GIT_SCRIPT": str(git_program),
            "GIT_NO_LAZY_FETCH": "unsafe",
            "GIT_NO_REPLACE_OBJECTS": "unsafe",
            "GIT_OPTIONAL_LOCKS": "unsafe",
            "GIT_TERMINAL_PROMPT": "unsafe",
            "LC_ALL": "C",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            BLOCKED_GIT_BATCH_RUNNER,
            str(TOOL_PATH),
            str(tmp_path),
            str(git),
            str(count),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout == b""
    assert result.stderr == b""


@obligation("MP2-000.OBL.CAPTURE_VALID")
def test_capture_validate_check_and_exact_source_census(
    _obligation: str,
    ready_repo: Path,
    schema_path: Path,
    captured_pair: tuple[Path, Path],
    captured_value: dict[str, Any],
) -> None:
    assert _obligation == OBLIGATION_IDS[1]
    snapshot, checksum = captured_pair
    assert set(captured_value) == EXPECTED_ROOT_KEYS
    assert snapshot.read_bytes() == tool._canonical_bytes(captured_value)
    assert not snapshot.read_bytes().endswith(b"\n")
    expected_sidecar = f"{_sha(snapshot.read_bytes())}  {tool.SNAPSHOT_LEAF}\n".encode()
    assert checksum.read_bytes() == expected_sidecar
    assert len(expected_sidecar) == 92
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o644
    assert stat.S_IMODE(checksum.stat().st_mode) == 0o644

    validated, validated_digest = _validate_value(
        snapshot.parent / "library-validation", captured_value, schema_path
    )
    assert validated == captured_value
    assert validated_digest == _sha(snapshot.read_bytes())

    for command in ("validate", "check"):
        args = [
            command,
            "--snapshot",
            str(snapshot),
            "--schema",
            str(schema_path),
            "--checksum",
            str(checksum),
        ]
        if command == "check":
            args[1:1] = ["--repo", str(ready_repo)]
        result = (
            _run_bootstrap_cli(ready_repo, *args)
            if command == "check"
            else _run_cli(ready_repo, *args)
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        assert result.stderr == b""
        parsed = tool._strict_json(result.stdout, require_canonical=True)
        assert parsed["ok"] is True
        assert parsed["command"] == command
        assert parsed["snapshot_sha256"] == _sha(snapshot.read_bytes())

    objects = tool.GitObjects(ready_repo, AUDITED_BASE_SHA)
    assert tool._tracked_tree(objects) == captured_value["tracked_tree"]
    assert tool._http_routes(objects) == captured_value["http_routes"]
    assert tool._schemas(objects) == captured_value["schemas"]
    assert tool._resources(objects) == captured_value["resources"]
    assert tool._workflows(objects) == captured_value["workflows_and_jobs"]

    resources = captured_value["resources"]
    repository_paths = [
        row["path"]
        for row in resources["entries"]
        if any(kind in row["kinds"] for kind in ("config", "example", "proof"))
    ]
    package_paths = [row["path"] for row in resources["entries"] if "package_data" in row["kinds"]]
    assert tool._path_array_digest(repository_paths) == (
        "3ac908ab77d8e31e6b760ab1a598f69ff614ed2ce10dcd44b9524eb80a0c9477"
    )
    assert tool._path_array_digest(package_paths) == (
        "51e103bed72e65a6913af2762544bb67645c4b440f494b8353e03a93ff6a60d1"
    )
    assert resources["canonical_path_array_sha256"] == (
        "fc3bbd56c48c54bedddc92caee716a97bd95718228ff2eb7d34826c4dbc32033"
    )
    assert captured_value["http_routes"]["canonical_rows_sha256"] == (
        "c278c306fe36d7251da0a04d710fe02d8d90758c911c325e4c827a0b41e7abaf"
    )
    assert captured_value["schemas"]["canonical_rows_sha256"] == (
        "68069c30fce592538fe7b181396df64deac35abd48751bdaf5b1a5242bbfbaf6"
    )
    assert captured_value["workflows_and_jobs"]["canonical_rows_sha256"] == (
        "76a647b24cba2203386722406fdd6626757fabcb79390dc1afb8fc20f36bc93c"
    )
    workflows = captured_value["workflows_and_jobs"]["entries"]
    dispatch = [row for row in workflows if "workflow_dispatch" in row["triggers"]]
    schedules = [row for row in workflows if "schedule" in row["triggers"]]
    assert dispatch and schedules
    assert any(
        isinstance(row["triggers"]["workflow_dispatch"], dict)
        and "inputs" in row["triggers"]["workflow_dispatch"]
        for row in dispatch
    )
    assert all(
        isinstance(row["triggers"]["schedule"], list)
        and all("cron" in item for item in row["triggers"]["schedule"])
        for row in schedules
    )


def test_unknown_help_identity_is_rejected(captured_value: dict[str, Any]) -> None:
    candidate = copy.deepcopy(captured_value)
    row = next(
        item
        for item in candidate["commands_and_help"]["entries"]
        if item["command"] == "metriplane-run"
    )
    row["stdout"] = "unknown help identity\n"
    row["stdout_sha256"] = _sha(row["stdout"].encode("utf-8"))

    with pytest.raises(tool.SnapshotError) as raised:
        tool._validate_snapshot_invariants(candidate)

    assert raised.value.code == "SNAPSHOT_INVARIANT_FAILED"


@obligation("MP2-000.OBL.CAPTURE_VALID")
def test_check_validates_frozen_help_without_live_console_execution(
    _obligation: str,
    ready_repo: Path,
    captured_pair: tuple[Path, Path],
    captured_value: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _obligation == OBLIGATION_IDS[1]

    def unavailable_live_help(_objects: Any) -> dict[str, Any]:
        raise AssertionError("check must not execute the invoking installation's help")

    _patch_synthetic_identity(ready_repo, monkeypatch)
    monkeypatch.setattr(tool, "_installed_help", unavailable_live_help)
    tool._check_snapshot(
        ready_repo,
        captured_value,
        _sha(captured_pair[0].read_bytes()),
    )


@obligation("MP2-000.OBL.CAPTURE_VALID")
@pytest.mark.parametrize(
    "absent_layout",
    ["no-build", "unrelated-build", "work-orders-only"],
)
def test_clean_checkout_check_uses_only_reviewed_digest_when_mp2_namespace_absent(
    _obligation: str,
    absent_layout: str,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[1]
    repo = _fresh_exact_base_repository(tmp_path / "repository")
    if absent_layout == "unrelated-build":
        unrelated = repo / "build" / "unrelated"
        unrelated.mkdir(parents=True)
        (unrelated / "sentinel").write_bytes(b"preserve")
    elif absent_layout == "work-orders-only":
        (repo / "build" / "work-orders").mkdir(parents=True)
    snapshot = ROOT / "docs" / "status" / tool.SNAPSHOT_LEAF
    checksum = ROOT / "docs" / "status" / tool.CHECKSUM_LEAF
    assert _sha(snapshot.read_bytes()) == tool.EXPECTED_COMMITTED_SNAPSHOT_SHA256
    result = _run_cli(
        repo,
        "check",
        "--repo",
        str(repo),
        "--snapshot",
        str(snapshot),
        "--schema",
        str(SCHEMA_SOURCE),
        "--checksum",
        str(checksum),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stderr == b""
    success = tool._strict_json(result.stdout, require_canonical=True)
    assert success["snapshot_sha256"] == tool.EXPECTED_COMMITTED_SNAPSHOT_SHA256


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(
    ("layout", "error_code"),
    [
        ("partial-task-root", "EVIDENCE_ROOT_INVALID"),
        ("symlink-build", "EVIDENCE_ROOT_INVALID"),
        ("symlink-work-orders", "EVIDENCE_ROOT_INVALID"),
        ("symlink-task", "EVIDENCE_ROOT_INVALID"),
        ("symlink-base", "EVIDENCE_ROOT_INVALID"),
        ("empty-base", "READY_INSTANCE_AMBIGUOUS"),
    ],
)
def test_present_or_partial_mp2_evidence_never_downgrades_to_absent_fallback(
    _obligation: str,
    layout: str,
    error_code: str,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    repo = _fresh_exact_base_repository(tmp_path / "repository")
    external = tmp_path / "external-evidence-target"
    external.mkdir()
    (external / "sentinel").write_bytes(b"preserve")
    build = repo / "build"
    work_orders = build / "work-orders"
    task = work_orders / "MP2-000"
    base = task / AUDITED_BASE_SHA
    if layout == "symlink-build":
        build.symlink_to(external, target_is_directory=True)
    elif layout == "symlink-work-orders":
        build.mkdir()
        work_orders.symlink_to(external, target_is_directory=True)
    elif layout == "symlink-task":
        work_orders.mkdir(parents=True)
        task.symlink_to(external, target_is_directory=True)
    elif layout == "symlink-base":
        task.mkdir(parents=True)
        base.symlink_to(external, target_is_directory=True)
    elif layout == "partial-task-root":
        task.mkdir(parents=True)
    else:
        base.mkdir(parents=True)
    result = _run_cli(
        repo,
        "check",
        "--repo",
        str(repo),
        "--snapshot",
        str(ROOT / "docs" / "status" / tool.SNAPSHOT_LEAF),
        "--schema",
        str(SCHEMA_SOURCE),
        "--checksum",
        str(ROOT / "docs" / "status" / tool.CHECKSUM_LEAF),
    )
    _assert_domain_failure(result, error_code)
    assert (external / "sentinel").read_bytes() == b"preserve"


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_absent_evidence_check_rejects_schema_valid_rechecksummed_snapshot(
    _obligation: str,
    schema_path: Path,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    repo = _fresh_exact_base_repository(tmp_path / "repository")
    committed = tool._strict_json(
        (ROOT / "docs" / "status" / tool.SNAPSHOT_LEAF).read_bytes(),
        require_canonical=True,
    )
    committed["tests"]["execution"]["stdout_sha256"] = "0" * 64
    validated, digest = _validate_value(tmp_path / "tampered", committed, schema_path)
    assert validated == committed
    assert digest != tool.EXPECTED_COMMITTED_SNAPSHOT_SHA256
    result = _run_cli(
        repo,
        "check",
        "--repo",
        str(repo),
        "--snapshot",
        str(tmp_path / "tampered" / tool.SNAPSHOT_LEAF),
        "--schema",
        str(tmp_path / "tampered" / "metriplane.baseline-snapshot.v1.schema.json"),
        "--checksum",
        str(tmp_path / "tampered" / tool.CHECKSUM_LEAF),
    )
    _assert_domain_failure(result, "COMMITTED_SNAPSHOT_IDENTITY_MISMATCH")


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize("projection", ["tests", "environment"])
def test_evidence_present_check_exact_compares_historical_projections(
    _obligation: str,
    projection: str,
    ready_repo: Path,
    captured_value: dict[str, Any],
    schema_path: Path,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    candidate = copy.deepcopy(captured_value)
    if projection == "tests":
        candidate["tests"]["execution"]["stdout_sha256"] = "0" * 64
    else:
        candidate["environment"]["os_release"] = "Schema-valid forged Linux"
    validated, _ = _validate_value(tmp_path / projection, candidate, schema_path)
    assert validated == candidate
    result = _run_bootstrap_cli(
        ready_repo,
        "check",
        "--repo",
        str(ready_repo),
        "--snapshot",
        str(tmp_path / projection / tool.SNAPSHOT_LEAF),
        "--schema",
        str(tmp_path / projection / "metriplane.baseline-snapshot.v1.schema.json"),
        "--checksum",
        str(tmp_path / projection / tool.CHECKSUM_LEAF),
    )
    _assert_domain_failure(result, "RETAINED_EVIDENCE_MISMATCH")


PARSER_CASES = (
    pytest.param(b"", "MALFORMED_JSON", id="empty"),
    pytest.param(b"{", "MALFORMED_JSON", id="truncated"),
    pytest.param(b"\xef\xbb\xbf{}", "JSON_BOM", id="bom"),
    pytest.param(b'{"x":"\xff"}', "INVALID_UTF8", id="invalid-utf8"),
    pytest.param(b'{"a":1,"a":2}', "DUPLICATE_KEY", id="duplicate-key"),
    pytest.param('{"é":1,"e\\u0301":2}'.encode(), "DUPLICATE_KEY", id="nfc-key-collision"),
    pytest.param(b'{"x":"\\ud800"}', "INVALID_UNICODE", id="lone-surrogate"),
    pytest.param(b'{"x":"e\\u0301"}', "NON_CANONICAL_JSON", id="non-nfc-value"),
    pytest.param(b'{"x":1.0}', "NON_INTEGER_NUMBER", id="float"),
    pytest.param(b'{"x":1e2}', "NON_INTEGER_NUMBER", id="exponent"),
    pytest.param(b'{"x":NaN}', "NONFINITE_NUMBER", id="nan"),
    pytest.param(b'{"x":Infinity}', "NONFINITE_NUMBER", id="infinity"),
    pytest.param(b'{"x":-Infinity}', "NONFINITE_NUMBER", id="negative-infinity"),
    pytest.param(b'{"x":-0}', "NEGATIVE_ZERO", id="negative-zero"),
    pytest.param(b'{"x":-0.0}', "NON_INTEGER_NUMBER", id="negative-zero-float"),
    pytest.param(b" {}", "NON_CANONICAL_JSON", id="leading-space"),
    pytest.param(b"{}\n", "NON_CANONICAL_JSON", id="trailing-lf"),
    pytest.param(b"{\n}\n", "NON_CANONICAL_JSON", id="pretty-json"),
    pytest.param(b"{}{}", "MALFORMED_JSON", id="second-json-value"),
)


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(("payload", "error_code"), PARSER_CASES)
def test_validate_rejects_strict_parser_mutations(
    _obligation: str, payload: bytes, error_code: str
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    with pytest.raises(tool.SnapshotError) as raised:
        tool._strict_json(payload, require_canonical=True)
    assert raised.value.code == error_code


PYTEST_EXECUTION_SUMMARY_NEGATIVES = (
    pytest.param(
        "1192 passed, 2 skipped\n1191 passed, 3 skipped\n",
        id="conflicting-summary-lines",
    ),
    pytest.param("1191 passed, 1 passed, 2 skipped\n", id="duplicate-category-one-line"),
    pytest.param(
        "test emitted: 999 passed\n1192 passed, 2 skipped\n",
        id="summary-like-embedded-output",
    ),
    pytest.param(
        "1192 passed, 2 skipped\n1192 passed, 2 skipped\n",
        id="duplicate-identical-summary-lines",
    ),
)


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize("raw_summary", PYTEST_EXECUTION_SUMMARY_NEGATIVES)
def test_pytest_execution_summary_parser_rejects_ambiguity(
    _obligation: str, raw_summary: str
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    with pytest.raises(tool.SnapshotError) as raised:
        tool._parse_pytest_summary(raw_summary)
    assert raised.value.code == "PREEDIT_EVIDENCE_INVALID"


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_pytest_collection_parser_rejects_multiple_summaries(
    _obligation: str,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    raw_collection = (
        "tests/test_one.py::test_one\n\n1 test collected in 0.01s\n1 test collected in 0.02s\n"
    )
    with pytest.raises(tool.SnapshotError) as raised:
        tool._parse_pytest_collection(raw_collection)
    assert raised.value.code == "PREEDIT_EVIDENCE_INVALID"


CLI_VALIDATE_NEGATIVE_CASES = (
    pytest.param("snapshot", b"{", "MALFORMED_JSON", id="malformed-json"),
    pytest.param("snapshot", b'{"x":"\xff"}', "INVALID_UTF8", id="invalid-utf8"),
    pytest.param("snapshot", b'{"x":1,"x":2}', "DUPLICATE_KEY", id="duplicate-key"),
    pytest.param("snapshot", b'{"x":NaN}', "NONFINITE_NUMBER", id="nonfinite"),
    pytest.param("checksum", None, "CHECKSUM_MISMATCH", id="checksum-mismatch"),
    pytest.param("schema", None, "SCHEMA_IDENTITY_MISMATCH", id="schema-tamper"),
)


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(("mutation_kind", "payload", "error_code"), CLI_VALIDATE_NEGATIVE_CASES)
def test_validate_cli_failures_are_canonical_and_do_not_mutate_inputs(
    _obligation: str,
    mutation_kind: str,
    payload: bytes | None,
    error_code: str,
    captured_pair: tuple[Path, Path],
    schema_path: Path,
    ready_repo: Path,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    snapshot = tmp_path / tool.SNAPSHOT_LEAF
    checksum = tmp_path / tool.CHECKSUM_LEAF
    schema = tmp_path / "metriplane.baseline-snapshot.v1.schema.json"
    snapshot.write_bytes(captured_pair[0].read_bytes())
    checksum.write_bytes(captured_pair[1].read_bytes())
    schema.write_bytes(schema_path.read_bytes())
    if mutation_kind == "snapshot":
        assert payload is not None
        snapshot.write_bytes(payload)
        checksum.write_bytes(f"{_sha(payload)}  {tool.SNAPSHOT_LEAF}\n".encode("ascii"))
    elif mutation_kind == "checksum":
        checksum.write_bytes(f"{'0' * 64}  {tool.SNAPSHOT_LEAF}\n".encode("ascii"))
    else:
        schema_value = tool._strict_json(schema.read_bytes(), require_canonical=True)
        schema_value["description"] = "tampered but structurally valid schema"
        schema.write_bytes(tool._canonical_bytes(schema_value))

    before = {path: path.read_bytes() for path in (snapshot, checksum, schema)}
    result = _run_cli(
        ready_repo,
        "validate",
        "--snapshot",
        str(snapshot),
        "--schema",
        str(schema),
        "--checksum",
        str(checksum),
    )
    _assert_domain_failure(result, error_code)
    assert {path: path.read_bytes() for path in before} == before


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(
    ("input_name", "entry_kind"),
    [
        pytest.param(name, kind, id=f"{name}-{kind}")
        for name in ("snapshot", "schema", "checksum")
        for kind in ("symlink", "directory")
    ],
)
def test_validate_cli_rejects_nonregular_input_artifacts_without_mutation(
    _obligation: str,
    input_name: str,
    entry_kind: str,
    captured_pair: tuple[Path, Path],
    schema_path: Path,
    ready_repo: Path,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    paths = {
        "snapshot": tmp_path / tool.SNAPSHOT_LEAF,
        "schema": tmp_path / "metriplane.baseline-snapshot.v1.schema.json",
        "checksum": tmp_path / tool.CHECKSUM_LEAF,
    }
    source_bytes = {
        "snapshot": captured_pair[0].read_bytes(),
        "schema": schema_path.read_bytes(),
        "checksum": captured_pair[1].read_bytes(),
    }
    for name, path in paths.items():
        if name == input_name and entry_kind == "symlink":
            target = tmp_path / f"{name}.target"
            target.write_bytes(source_bytes[name])
            path.symlink_to(target.name)
        elif name == input_name:
            path.mkdir()
            (path / "sentinel").write_bytes(b"preserve")
        else:
            path.write_bytes(source_bytes[name])
    before = {path: _entry_identity(path) for path in paths.values()}
    targets_before = {
        path.resolve(): path.resolve().read_bytes() for path in paths.values() if path.is_symlink()
    }
    result = _run_cli(
        ready_repo,
        "validate",
        "--snapshot",
        str(paths["snapshot"]),
        "--schema",
        str(paths["schema"]),
        "--checksum",
        str(paths["checksum"]),
    )
    _assert_domain_failure(result, "NOT_REGULAR_FILE")
    assert {path: _entry_identity(path) for path in before} == before
    assert {path: path.read_bytes() for path in targets_before} == targets_before


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize("input_name", ["snapshot", "schema", "checksum"])
@pytest.mark.parametrize("entry_kind", ["fifo", "unix-socket"])
def test_validate_cli_rejects_fifo_and_socket_inputs_without_blocking(
    _obligation: str,
    input_name: str,
    entry_kind: str,
    captured_pair: tuple[Path, Path],
    schema_path: Path,
    ready_repo: Path,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    paths = {
        "snapshot": tmp_path / tool.SNAPSHOT_LEAF,
        "schema": tmp_path / "metriplane.baseline-snapshot.v1.schema.json",
        "checksum": tmp_path / tool.CHECKSUM_LEAF,
    }
    source_bytes = {
        "snapshot": captured_pair[0].read_bytes(),
        "schema": schema_path.read_bytes(),
        "checksum": captured_pair[1].read_bytes(),
    }
    for name, path in paths.items():
        if name != input_name:
            path.write_bytes(source_bytes[name])
        elif entry_kind == "fifo":
            os.mkfifo(path, 0o600)
        else:
            # Descriptor-level mode injection remains deterministic in sandboxes that
            # prohibit creating AF_UNIX sockets while exercising the same CLI guard.
            path.write_bytes(b"socket-sentinel")
    before = {path: _entry_identity(path) for path in paths.values()}
    if entry_kind == "unix-socket":
        result = _run_nonregular_stat_cli(
            ready_repo,
            paths[input_name],
            "validate",
            "--snapshot",
            str(paths["snapshot"]),
            "--schema",
            str(paths["schema"]),
            "--checksum",
            str(paths["checksum"]),
        )
    else:
        process_env = os.environ.copy()
        process_env.update(
            {
                "LC_ALL": "C.UTF-8",
                "TZ": "UTC",
                "PYTHONHASHSEED": "0",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                str(TOOL_PATH),
                "validate",
                "--snapshot",
                str(paths["snapshot"]),
                "--schema",
                str(paths["schema"]),
                "--checksum",
                str(paths["checksum"]),
            ],
            cwd=ready_repo,
            env=process_env,
            capture_output=True,
            check=False,
            timeout=5,
        )
    _assert_domain_failure(result, "NOT_REGULAR_FILE")
    assert {path: _entry_identity(path) for path in before} == before


SECTION_BOUNDS = (
    pytest.param("tracked_tree", "entries", "entry_count", 1469, id="tracked-tree"),
    pytest.param("commands_and_help", "entries", None, 2, id="commands-help"),
    pytest.param("http_routes", "entries", "count", 48, id="routes"),
    pytest.param("schemas", "entries", "count", 6, id="schemas"),
    pytest.param("resources", "entries", "count", 256, id="resources"),
    pytest.param("workflows_and_jobs", "entries", "count", 15, id="workflows"),
    pytest.param("tests.collection", "node_ids", "count", 1194, id="test-node-ids"),
)


def _section(value: dict[str, Any], dotted: str) -> dict[str, Any]:
    current: Any = value
    for component in dotted.split("."):
        current = current[component]
    assert isinstance(current, dict)
    return current


def _append_unique(section_name: str, rows: list[Any]) -> None:
    if section_name == "tests.collection":
        rows.append("tests/test_synthetic.py::test_case[n-plus-one]")
        return
    row = copy.deepcopy(rows[-1])
    if section_name == "commands_and_help":
        row["command"] = "metriplane-extra"
    elif section_name == "http_routes":
        row["normalized_path"] += "/n-plus-one"
    elif section_name == "schemas":
        row["path"] += ".n-plus-one.schema.json"
        row["schema_id"] += "/n-plus-one"
    elif section_name == "workflows_and_jobs":
        row["path"] = ".github/workflows/n-plus-one.yml"
        row["name"] = "n-plus-one"
    else:
        row["path"] += ".n-plus-one"
    rows.append(row)


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(("section_name", "rows_key", "count_key", "bound"), SECTION_BOUNDS)
@pytest.mark.parametrize("delta", [-1, 0, 1], ids=["n-minus-one", "n", "n-plus-one"])
def test_declared_schema_bounds_are_n_minus_one_n_n_plus_one(
    _obligation: str,
    section_name: str,
    rows_key: str,
    count_key: str | None,
    bound: int,
    delta: int,
    captured_value: dict[str, Any],
    schema_path: Path,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    candidate = copy.deepcopy(captured_value)
    section = _section(candidate, section_name)
    rows = section[rows_key]
    assert len(rows) == bound
    if delta < 0:
        rows.pop()
    elif delta > 0:
        _append_unique(section_name, rows)
    if count_key is not None:
        section[count_key] = bound + delta
    if delta == 0:
        validated, _ = _validate_value(tmp_path, candidate, schema_path)
        assert validated == candidate
    else:
        with pytest.raises(tool.SnapshotError) as raised:
            _validate_value(tmp_path, candidate, schema_path)
        assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(
    ("definition", "size"),
    [
        pytest.param("sha1", 39, id="sha1-n-minus-one"),
        pytest.param("sha1", 40, id="sha1-n"),
        pytest.param("sha1", 41, id="sha1-n-plus-one"),
        pytest.param("sha256", 63, id="sha256-n-minus-one"),
        pytest.param("sha256", 64, id="sha256-n"),
        pytest.param("sha256", 65, id="sha256-n-plus-one"),
    ],
)
def test_digest_token_n_minus_one_n_n_plus_one(
    _obligation: str,
    definition: str,
    size: int,
    captured_value: dict[str, Any],
    schema_path: Path,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    candidate = copy.deepcopy(captured_value)
    if definition == "sha1":
        original = candidate["tracked_tree"]["entries"][0]["blob_oid"]
        candidate["tracked_tree"]["entries"][0]["blob_oid"] = (
            original[:size] if size <= 40 else original + "a"
        )
    else:
        original = candidate["tests"]["collection"]["stdout_sha256"]
        candidate["tests"]["collection"]["stdout_sha256"] = (
            original[:size] if size <= 64 else original + "a"
        )
    expected = 40 if definition == "sha1" else 64
    if size == expected:
        validated, _ = _validate_value(tmp_path, candidate, schema_path)
        assert validated == candidate
    else:
        with pytest.raises(tool.SnapshotError) as raised:
            _validate_value(tmp_path, candidate, schema_path)
        assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


TOKEN_SCHEMA_CASES = (
    pytest.param("sha1", "a" * 40, id="sha1"),
    pytest.param("sha256", "a" * 64, id="sha256"),
    pytest.param("filesystem-sha256", "sha256:" + "a" * 64, id="filesystem-sha256"),
    pytest.param("python-cache-tag", "cpython-312", id="python-cache-tag"),
    pytest.param("normalized-name", "pytest", id="normalized-name"),
    pytest.param("package-name", "metriplane.demo", id="package-name"),
    pytest.param("workflow-job-id", "tests.linux-3", id="workflow-job-id"),
    pytest.param("normalized-route", "/health", id="normalized-route"),
    pytest.param("workflow-path", ".github/workflows/ci.yml", id="workflow-path"),
)


def _token_schema(schema: dict[str, Any], token_kind: str) -> dict[str, Any]:
    definitions = schema["$defs"]
    paths = {
        "sha1": ("sha1",),
        "sha256": ("sha256",),
        "filesystem-sha256": ("filesystem", "properties", "sha256"),
        "python-cache-tag": ("environment", "properties", "python_cache_tag"),
        "normalized-name": ("installed_distribution", "properties", "normalized_name"),
        "package-name": ("package_data_declaration", "properties", "package"),
        "workflow-job-id": ("workflow_entry", "properties", "job_ids", "items"),
        "normalized-route": ("http_route", "properties", "normalized_path"),
        "workflow-path": ("workflow_entry", "properties", "path"),
    }
    value: Any = definitions
    for component in paths[token_kind]:
        value = value[component]
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
@pytest.mark.parametrize(("token_kind", "valid_token"), TOKEN_SCHEMA_CASES)
@pytest.mark.parametrize("suffix", ["\n", "\r"], ids=["terminal-lf", "terminal-cr"])
def test_token_schemas_reject_terminal_controls_with_internal_and_pinned_engines(
    _obligation: str,
    token_kind: str,
    valid_token: str,
    suffix: str,
    schema_value: dict[str, Any],
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    token_schema = _token_schema(schema_value, token_kind)
    assert _internal_schema_accepts(valid_token, token_schema)
    external_valid = _pinned_external_schema_accepts(valid_token, token_schema)
    if external_valid is not None:
        assert external_valid is True

    invalid_token = valid_token + suffix
    assert not _internal_schema_accepts(invalid_token, token_schema)
    external_invalid = _pinned_external_schema_accepts(invalid_token, token_schema)
    if external_invalid is not None:
        assert external_invalid is False


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
@pytest.mark.parametrize("field", ["execution-sha256", "python-cache-tag"])
@pytest.mark.parametrize("suffix", ["\n", "\r"], ids=["terminal-lf", "terminal-cr"])
def test_validate_rejects_terminal_controls_in_schema_tokens(
    _obligation: str,
    field: str,
    suffix: str,
    captured_value: dict[str, Any],
    schema_path: Path,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    candidate = copy.deepcopy(captured_value)
    if field == "execution-sha256":
        candidate["tests"]["execution"]["stdout_sha256"] += suffix
    else:
        candidate["environment"]["python_cache_tag"] += suffix
    with pytest.raises(tool.SnapshotError) as raised:
        _validate_value(tmp_path, candidate, schema_path)
    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


INTERNAL_INVARIANT_MUTATIONS = (
    pytest.param("tracked_tree", id="tracked-tree-order-and-digest"),
    pytest.param("commands_and_help", id="installed-help-order"),
    pytest.param("http_routes", id="route-order-and-digest"),
    pytest.param("schemas", id="schema-order-and-digest"),
    pytest.param("resources", id="resource-order-and-digest"),
    pytest.param("resource-self-consistent", id="reviewed-resource-row-identity"),
    pytest.param("workflows_and_jobs", id="workflow-order-and-digest"),
    pytest.param("tests", id="test-node-order-and-stream-digest"),
    pytest.param("environment", id="filesystem-observation-digest"),
    pytest.param("installed-duplicate", id="duplicate-installed-normalized-name"),
    pytest.param("limitations", id="limitation-authority-order"),
)


def _swap_first_two(rows: list[Any]) -> None:
    assert len(rows) >= 2
    rows[0], rows[1] = rows[1], rows[0]


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize("section_name", INTERNAL_INVARIANT_MUTATIONS)
def test_standalone_validate_rejects_schema_valid_internal_invariant_mutations(
    _obligation: str,
    section_name: str,
    captured_value: dict[str, Any],
    schema_path: Path,
    schema_value: dict[str, Any],
    tmp_path: Path,
    ready_repo: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    candidate = copy.deepcopy(captured_value)
    if section_name == "tests":
        _swap_first_two(candidate["tests"]["collection"]["node_ids"])
    elif section_name == "environment":
        _swap_first_two(candidate["environment"]["filesystem"]["home_cache"]["paths"])
    elif section_name == "installed-duplicate":
        installed = candidate["environment"]["installed_distributions"]
        duplicate = copy.deepcopy(installed[0])
        duplicate["version"] = duplicate["version"] + ".duplicate"
        installed.append(duplicate)
    elif section_name == "resource-self-consistent":
        resources = candidate["resources"]
        resources["entries"][0]["blob_oid"] = "0" * 40
        resources["canonical_rows_sha256"] = _sha(tool._canonical_bytes(resources["entries"]))
    elif section_name == "limitations":
        _swap_first_two(candidate["limitations"])
    else:
        _swap_first_two(candidate[section_name]["entries"])

    assert _internal_schema_accepts(candidate, schema_value)
    external = _pinned_external_schema_accepts(candidate, schema_value)
    if external is not None:
        assert external is True
    with pytest.raises(tool.SnapshotError) as raised:
        _validate_value(tmp_path, candidate, schema_path)
    assert raised.value.code == "SNAPSHOT_INVARIANT_FAILED"

    result = _run_cli(
        ready_repo,
        "validate",
        "--snapshot",
        str(tmp_path / tool.SNAPSHOT_LEAF),
        "--schema",
        str(tmp_path / "metriplane.baseline-snapshot.v1.schema.json"),
        "--checksum",
        str(tmp_path / tool.CHECKSUM_LEAF),
    )
    assert result.returncode == 3
    assert result.stdout == b""
    error = tool._strict_json(result.stderr, require_canonical=True)
    assert error["ok"] is False
    assert error["error"]["code"] == "SNAPSHOT_INVARIANT_FAILED"


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
def test_schema_and_checksum_are_strict_and_checksum_first(
    _obligation: str,
    tmp_path: Path,
    captured_pair: tuple[Path, Path],
    schema_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    snapshot_raw = captured_pair[0].read_bytes()
    snapshot = tmp_path / tool.SNAPSHOT_LEAF
    checksum = tmp_path / tool.CHECKSUM_LEAF
    schema = tmp_path / "metriplane.baseline-snapshot.v1.schema.json"
    snapshot.write_bytes(snapshot_raw)
    schema.write_bytes(schema_path.read_bytes())

    checksum.write_bytes(f"{'0' * 64}  {tool.SNAPSHOT_LEAF}\n".encode())
    snapshot.write_bytes(b"{")
    with pytest.raises(tool.SnapshotError) as raised:
        tool._validate_artifact(snapshot, schema, checksum)
    assert raised.value.code == "CHECKSUM_MISMATCH"

    checksum.write_bytes(f"{_sha(b'{')}  {tool.SNAPSHOT_LEAF}\n".encode())
    with pytest.raises(tool.SnapshotError) as raised:
        tool._validate_artifact(snapshot, schema, checksum)
    assert raised.value.code == "MALFORMED_JSON"

    snapshot.write_bytes(snapshot_raw)
    checksum.write_bytes(f"{_sha(snapshot_raw)}  {tool.SNAPSHOT_LEAF}\n".encode())
    value, digest = tool._validate_artifact(snapshot, schema, checksum)
    assert value["schema_version"] == SCHEMA_VERSION
    assert digest == _sha(snapshot_raw)

    schema_value = json.loads(schema.read_text(encoding="utf-8"))
    schema_value["description"] = "tampered but still meta-valid"
    schema.write_bytes(tool._canonical_bytes(schema_value))
    with pytest.raises(tool.SnapshotError) as raised:
        tool._validate_artifact(snapshot, schema, checksum)
    assert "SCHEMA" in raised.value.code


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
@pytest.mark.parametrize("size", [91, 92, 93], ids=["n-minus-one", "n", "n-plus-one"])
def test_checksum_sidecar_n_minus_one_n_n_plus_one(
    _obligation: str,
    size: int,
    tmp_path: Path,
    captured_pair: tuple[Path, Path],
    schema_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    snapshot = tmp_path / tool.SNAPSHOT_LEAF
    checksum = tmp_path / tool.CHECKSUM_LEAF
    schema = tmp_path / "metriplane.baseline-snapshot.v1.schema.json"
    snapshot.write_bytes(captured_pair[0].read_bytes())
    schema.write_bytes(schema_path.read_bytes())
    valid = captured_pair[1].read_bytes()
    checksum.write_bytes(valid[:size] if size <= 92 else valid + b"\n")
    if size == 92:
        tool._validate_artifact(snapshot, schema, checksum)
    else:
        with pytest.raises(tool.SnapshotError) as raised:
            tool._validate_artifact(snapshot, schema, checksum)
        assert raised.value.code == "INVALID_SIZE"


CONDITIONAL_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"enum": ["number", "text"]},
        "value": {},
    },
    "required": ["kind", "value"],
    "additionalProperties": False,
    "if": {"properties": {"kind": {"const": "number"}}},
    "then": {"properties": {"value": {"type": "integer"}}},
    "else": {"properties": {"value": {"type": "string"}}},
}


SCHEMA_ENGINE_DIFFERENTIAL_CASES = (
    pytest.param(
        "ok",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://metriplane.com/schemas/test-control.json",
            "title": "control",
            "description": "accepted control",
            "type": "string",
        },
        True,
        id="metadata-and-valid-control",
    ),
    pytest.param(
        "bad",
        {
            "$defs": {"token": {"type": "string", "pattern": "^ok$"}},
            "$ref": "#/$defs/token",
        },
        False,
        id="defs-and-ref",
    ),
    pytest.param(
        0,
        {"allOf": [{"type": "integer"}, {"minimum": 1}]},
        False,
        id="all-of",
    ),
    pytest.param(
        1,
        {"oneOf": [{"type": "integer"}, {"type": "number"}]},
        False,
        id="one-of-exactly-one",
    ),
    pytest.param(True, {"type": "integer"}, False, id="type-bool-not-integer"),
    pytest.param("other", {"const": "fixed"}, False, id="const"),
    pytest.param("other", {"enum": ["fixed", "second"]}, False, id="enum"),
    pytest.param(
        {},
        {
            "type": "object",
            "properties": {"required_value": {"type": "integer"}},
            "required": ["required_value"],
        },
        False,
        id="properties-and-required",
    ),
    pytest.param(
        {"extra": 1},
        {"type": "object", "properties": {}, "additionalProperties": False},
        False,
        id="additional-properties-false",
    ),
    pytest.param(
        {"extra": "wrong"},
        {
            "type": "object",
            "properties": {},
            "additionalProperties": {"type": "integer"},
        },
        False,
        id="additional-properties-schema",
    ),
    pytest.param(
        [1, "wrong"],
        {"type": "array", "items": {"type": "integer"}},
        False,
        id="items",
    ),
    pytest.param(
        [1],
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "items": False,
        },
        False,
        id="prefix-items",
    ),
    pytest.param(
        [1, 1],
        {"type": "array", "uniqueItems": True},
        False,
        id="unique-items",
    ),
    pytest.param([], {"type": "array", "minItems": 1}, False, id="min-items"),
    pytest.param([1, 2], {"type": "array", "maxItems": 1}, False, id="max-items"),
    pytest.param("", {"type": "string", "minLength": 1}, False, id="min-length"),
    pytest.param("too long", {"type": "string", "maxLength": 1}, False, id="max-length"),
    pytest.param(0, {"type": "integer", "minimum": 1}, False, id="minimum"),
    pytest.param(2, {"type": "integer", "maximum": 1}, False, id="maximum"),
    pytest.param("wrong", {"type": "string", "pattern": "^right$"}, False, id="pattern"),
    pytest.param(
        "https://metriplane.com/schemas/baseline-snapshot/test",
        {"type": "string", "format": "uri"},
        True,
        id="uri-format",
    ),
    pytest.param(
        "2026-08-24T00:00:00Z",
        {"type": "string", "format": "date-time"},
        True,
        id="rfc3339-date-time-valid",
    ),
    pytest.param(
        "2026-02-30T00:00:00Z",
        {"type": "string", "format": "date-time"},
        False,
        id="rfc3339-date-time-invalid",
    ),
    pytest.param(
        {"kind": "number", "value": 1},
        CONDITIONAL_SCHEMA,
        True,
        id="if-then-valid",
    ),
    pytest.param(
        {"kind": "number", "value": "wrong"},
        CONDITIONAL_SCHEMA,
        False,
        id="if-then-invalid",
    ),
    pytest.param(
        {"kind": "text", "value": "ok"},
        CONDITIONAL_SCHEMA,
        True,
        id="if-else-valid",
    ),
    pytest.param(
        {"kind": "text", "value": 1},
        CONDITIONAL_SCHEMA,
        False,
        id="if-else-invalid",
    ),
    pytest.param(
        {"": 1},
        {
            "type": "object",
            "propertyNames": {"type": "string", "minLength": 1},
        },
        False,
        id="property-names",
    ),
    pytest.param({}, {"type": "object", "minProperties": 1}, False, id="min-properties"),
)


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
@pytest.mark.parametrize(("instance", "schema", "expected"), SCHEMA_ENGINE_DIFFERENTIAL_CASES)
def test_internal_schema_engine_has_fixed_keyword_verdicts_and_pinned_parity(
    _obligation: str,
    instance: Any,
    schema: dict[str, Any],
    expected: bool,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    internal = _internal_schema_accepts(instance, schema)
    assert internal is expected
    external = _pinned_external_schema_accepts(instance, schema)
    if external is not None:
        assert external is expected
        assert external is internal


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
def test_internal_schema_engine_preflights_unselected_conditional_branches(
    _obligation: str,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    schema = {
        "if": {"const": "selected"},
        "then": True,
        "else": {"type": []},
    }
    with pytest.raises(tool.SnapshotError) as raised:
        tool._internal_validate("selected", schema)
    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
@pytest.mark.parametrize("suffix", ["\n", "\r"], ids=["terminal-lf", "terminal-cr"])
def test_internal_schema_engine_treats_anchored_patterns_as_full_tokens(
    _obligation: str,
    suffix: str,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    anchored = {"type": "string", "pattern": "^[a-z]+$"}
    assert _internal_schema_accepts("valid", anchored)
    assert not _internal_schema_accepts("valid" + suffix, anchored)
    assert _internal_schema_accepts("prefix valid suffix", {"pattern": "valid"})


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
def test_pinned_external_engine_is_an_additional_fail_closed_check(
    _obligation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    original_version = tool.importlib.metadata.version
    original_import = tool.importlib.import_module
    events: list[str] = []

    class SyntheticSchemaError(Exception):
        pass

    class SyntheticValidationError(Exception):
        pass

    class SyntheticFormatChecker:
        def __init__(self) -> None:
            events.append("format-checker")
            self.checkers = {"date-time": object()}

    class SyntheticValidator:
        @classmethod
        def check_schema(cls, _schema: dict[str, Any]) -> None:
            events.append("check-schema")

        def __init__(self, _schema: dict[str, Any], *, format_checker: Any) -> None:
            assert isinstance(format_checker, SyntheticFormatChecker)
            events.append("validator")

        def validate(self, instance: Any) -> None:
            assert instance == "valid"
            events.append("validate")

    synthetic_jsonschema = SimpleNamespace(
        Draft202012Validator=SyntheticValidator,
        FormatChecker=SyntheticFormatChecker,
        exceptions=SimpleNamespace(
            SchemaError=SyntheticSchemaError,
            ValidationError=SyntheticValidationError,
        ),
    )

    def pinned_version(distribution: str) -> str:
        if distribution == "jsonschema":
            return "4.25.1"
        if distribution == "rfc3339-validator":
            return "0.1.4"
        return cast(str, original_version(distribution))

    def pinned_import(module: str, package: str | None = None) -> Any:
        if module == "jsonschema":
            events.append("import")
            return synthetic_jsonschema
        return original_import(module, package)

    monkeypatch.setattr(tool.importlib.metadata, "version", pinned_version)
    monkeypatch.setattr(tool.importlib, "import_module", pinned_import)
    assert tool._validate_with_available_engine("valid", {"type": "string"}) == (
        "jsonschema-4.25.1"
    )
    assert events == ["import", "format-checker", "check-schema", "validator", "validate"]

    events.clear()
    with pytest.raises(tool.SnapshotError) as raised:
        tool._validate_with_available_engine(1, {"type": "string"})
    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"
    assert events == []


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
def test_hash_locked_authority_schemas_have_fail_closed_internal_fallback(
    _obligation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    original_version = tool.importlib.metadata.version

    def missing_validator_pins(distribution: str) -> str:
        if distribution in {"jsonschema", "rfc3339-validator"}:
            raise importlib_metadata.PackageNotFoundError(distribution)
        return cast(str, original_version(distribution))

    monkeypatch.setattr(tool.importlib.metadata, "version", missing_validator_pins)
    assert (
        tool._validate_with_available_engine(
            "2026-08-24T00:00:00Z",
            {"type": "string", "format": "date-time"},
        )
        == "internal-exact-schema-v1"
    )
    with pytest.raises(tool.SnapshotError) as raised:
        tool._validate_with_available_engine(
            "2026-02-30T00:00:00Z",
            {"type": "string", "format": "date-time"},
        )
    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"

    repository = tmp_path / "repository"
    repository.mkdir()
    environment = _synthetic_environment(repository, os_release="Synthetic Linux")
    remote = _synthetic_remote_proof(repository)

    tool._validate_pinned_authority_schema(
        environment,
        encoded=tool._BOOTSTRAP_ENVIRONMENT_SCHEMA_ZLIB_BASE64,
        expected_bytes=tool.BOOTSTRAP_ENVIRONMENT_SCHEMA_BYTES,
        expected_sha256=tool.BOOTSTRAP_ENVIRONMENT_SCHEMA_SHA256,
        expected_id=tool.BOOTSTRAP_ENVIRONMENT_SCHEMA_ID,
        label="bootstrap environment observation",
    )

    def validate_remote(candidate: dict[str, Any]) -> None:
        tool._validate_pinned_authority_schema(
            candidate,
            encoded=tool._GITHUB_REMOTE_SCHEMA_ZLIB_BASE64,
            expected_bytes=tool.GITHUB_REMOTE_SCHEMA_BYTES,
            expected_sha256=tool.GITHUB_REMOTE_SCHEMA_SHA256,
            expected_id=tool.GITHUB_REMOTE_SCHEMA_ID,
            label="GitHub remote collision proof",
        )

    validate_remote(remote)

    then_receipt = copy.deepcopy(remote)
    then_receipt["collection_receipts"].append(
        tool._receipt(
            "mcp__codex_apps__github_fetch_pr",
            1,
            {"pr_number": 1, "repo_full_name": "Miko997/metriplane"},
            {"head_sha": AUDITED_BASE_SHA},
        )
    )
    validate_remote(then_receipt)

    invalid_then_receipt = copy.deepcopy(remote)
    invalid_then_receipt["collection_receipts"].append(
        tool._receipt(
            "mcp__codex_apps__github_fetch_pr",
            None,
            {"pr_number": 1, "repo_full_name": "Miko997/metriplane"},
            {"head_sha": AUDITED_BASE_SHA},
        )
    )
    with pytest.raises(tool.SnapshotError) as raised:
        validate_remote(invalid_then_receipt)
    assert raised.value.code == "READY_INSTANCE_INVALID"

    invalid_else_receipt = copy.deepcopy(remote)
    invalid_else_receipt["collection_receipts"][0]["pr_number"] = 1
    with pytest.raises(tool.SnapshotError) as raised:
        validate_remote(invalid_else_receipt)
    assert raised.value.code == "READY_INSTANCE_INVALID"

    invalid_no_collision = copy.deepcopy(remote)
    invalid_no_collision["authenticated_actor"]["permission"] = "read"
    with pytest.raises(tool.SnapshotError) as raised:
        validate_remote(invalid_no_collision)
    assert raised.value.code == "READY_INSTANCE_INVALID"

    collision = copy.deepcopy(remote)
    collision["verdict"] = "COLLISION"
    collision["authenticated_actor"]["permission"] = "read"
    collision["collisions"] = ["synthetic collision"]
    validate_remote(collision)


@pytest.mark.parametrize(
    "fallback_reason",
    ["version-mismatch", "broken-import", "missing-date-time-format"],
)
@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
def test_internal_schema_fallback_covers_unusable_external_engine(
    _obligation: str,
    monkeypatch: pytest.MonkeyPatch,
    fallback_reason: str,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    original_version = tool.importlib.metadata.version
    original_import = tool.importlib.import_module

    def validator_version(distribution: str) -> str:
        if distribution == "jsonschema" and fallback_reason == "version-mismatch":
            return "4.25.0"
        if distribution == "jsonschema":
            return "4.25.1"
        if distribution == "rfc3339-validator":
            return "0.1.4"
        return cast(str, original_version(distribution))

    def validator_import(module: str, package: str | None = None) -> Any:
        if module == "jsonschema" and fallback_reason == "broken-import":
            raise ImportError("synthetic broken validator import")
        if module == "jsonschema" and fallback_reason == "missing-date-time-format":
            jsonschema = original_import(module, package)

            class MissingDateTimeFormatChecker:
                def __init__(self) -> None:
                    self.checkers: dict[str, Any] = {}

            class MissingDateTimeEngine:
                Draft202012Validator = jsonschema.Draft202012Validator
                FormatChecker = MissingDateTimeFormatChecker
                exceptions = jsonschema.exceptions

            return MissingDateTimeEngine
        return original_import(module, package)

    monkeypatch.setattr(tool.importlib.metadata, "version", validator_version)
    monkeypatch.setattr(tool.importlib, "import_module", validator_import)
    schema = {"type": "string", "format": "date-time"}
    assert (
        tool._validate_with_available_engine("2026-08-24T00:00:00Z", schema)
        == "internal-exact-schema-v1"
    )
    with pytest.raises(tool.SnapshotError) as raised:
        tool._validate_with_available_engine("2026-02-30T00:00:00Z", schema)
    assert raised.value.code == "SCHEMA_VALIDATION_FAILED"


RELATIVE_PATH_SECTIONS = (
    pytest.param("tracked", id="tracked-path"),
    pytest.param("route", id="route-source-path"),
    pytest.param("forwarded-route", id="forwarded-route-source-path"),
    pytest.param("schema", id="schema-path"),
    pytest.param("resource", id="resource-path"),
    pytest.param("package-data", id="package-data-pattern"),
    pytest.param("workflow", id="workflow-path"),
)

UNSAFE_RELATIVE_PATHS = (
    pytest.param("/absolute", False, id="absolute"),
    pytest.param("../escape", False, id="leading-dot-dot"),
    pytest.param("a/../escape", False, id="internal-dot-dot"),
    pytest.param(".", False, id="dot"),
    pytest.param("a/./b", False, id="internal-dot"),
    pytest.param("a//b", False, id="empty-segment"),
    pytest.param("a/", False, id="trailing-slash"),
    pytest.param("a\\b", False, id="backslash"),
    pytest.param("a\x00b", False, id="nul"),
    pytest.param("a\x01b", False, id="c0"),
    pytest.param("a\rb", False, id="carriage-return"),
    pytest.param("a\nb", False, id="line-feed"),
    pytest.param("a\tb", False, id="tab"),
    pytest.param("a\x7fb", False, id="del"),
    pytest.param("a\x85b", False, id="c1"),
    pytest.param("cafe\u0301/file", True, id="non-nfc"),
)


def _replace_path_in_section(snapshot: dict[str, Any], section: str, replacement: str) -> None:
    if section == "tracked":
        snapshot["tracked_tree"]["entries"][0]["path"] = replacement
    elif section == "route":
        snapshot["http_routes"]["entries"][0]["source_path"] = replacement
    elif section == "forwarded-route":
        route = next(
            row for row in snapshot["http_routes"]["entries"] if row["forwarded_by"] is not None
        )
        route["forwarded_by"]["source_path"] = replacement
    elif section == "schema":
        snapshot["schemas"]["entries"][0]["path"] = replacement
    elif section == "resource":
        snapshot["resources"]["entries"][0]["path"] = replacement
    elif section == "package-data":
        resource = next(
            row for row in snapshot["resources"]["entries"] if row["package_data_declarations"]
        )
        resource["package_data_declarations"][0]["pattern"] = replacement
    else:
        assert section == "workflow"
        snapshot["workflows_and_jobs"]["entries"][0]["path"] = replacement


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize("section", RELATIVE_PATH_SECTIONS)
@pytest.mark.parametrize(("replacement", "schema_accepts"), UNSAFE_RELATIVE_PATHS)
def test_all_relative_path_surfaces_reject_unsafe_or_non_nfc_values(
    _obligation: str,
    section: str,
    replacement: str,
    schema_accepts: bool,
    captured_value: dict[str, Any],
    schema_value: dict[str, Any],
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    candidate = copy.deepcopy(captured_value)
    _replace_path_in_section(candidate, section, replacement)
    expected_schema_acceptance = schema_accepts
    if replacement == "cafe\N{COMBINING ACUTE ACCENT}/file":
        expected_schema_acceptance = section not in {"forwarded-route", "workflow"}
    assert _internal_schema_accepts(candidate, schema_value) is expected_schema_acceptance
    with pytest.raises(tool.SnapshotError) as raised:
        tool._require_safe_relative_posix(
            replacement,
            code="SNAPSHOT_INVARIANT_FAILED",
            label="test path",
        )
    assert raised.value.code == (
        "NON_NFC_VALUE"
        if replacement == "cafe\N{COMBINING ACUTE ACCENT}/file"
        else "SNAPSHOT_INVARIANT_FAILED"
    )
    if expected_schema_acceptance:
        with pytest.raises(tool.SnapshotError) as invariant:
            tool._validate_snapshot_invariants(candidate)
        assert invariant.value.code == (
            "NON_NFC_VALUE"
            if replacement == "cafe\N{COMBINING ACUTE ACCENT}/file"
            else "SNAPSHOT_INVARIANT_FAILED"
        )


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_relative_posix_paths_allow_colons_but_parser_rejects_non_nfc_bytes(
    _obligation: str, schema_value: dict[str, Any]
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    safe_path_schema = schema_value["$defs"]["safe_path"]
    assert _internal_schema_accepts("assets/name:variant.json", safe_path_schema)
    assert (
        tool._require_safe_relative_posix(
            "assets/name:variant.json", code="TEST", label="test path"
        )
        == "assets/name:variant.json"
    )
    non_nfc_raw = b'"cafe\\u0301/file"'
    with pytest.raises(tool.SnapshotError) as raised:
        tool._strict_json(non_nfc_raw, require_canonical=True)
    assert raised.value.code == "NON_CANONICAL_JSON"


UNSAFE_ABSOLUTE_PATHS = (
    pytest.param("relative/path", False, id="relative"),
    pytest.param("//server", False, id="double-leading-slash"),
    pytest.param("/a//b", False, id="empty-segment"),
    pytest.param("/./a", False, id="leading-dot"),
    pytest.param("/a/../b", False, id="internal-dot-dot"),
    pytest.param("/a/", False, id="trailing-slash"),
    pytest.param("/a\\b", False, id="backslash"),
    pytest.param("/a\x00b", False, id="nul"),
    pytest.param("/a\x01b", False, id="c0"),
    pytest.param("/a\nb", False, id="line-feed"),
    pytest.param("/a\tb", False, id="tab"),
    pytest.param("/a\x7fb", False, id="del"),
    pytest.param("/a\x85b", False, id="c1"),
    pytest.param("/cafe\u0301", True, id="non-nfc"),
)


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(("replacement", "schema_accepts"), UNSAFE_ABSOLUTE_PATHS)
def test_absolute_observation_paths_reject_ambiguity_controls_and_non_nfc(
    _obligation: str,
    replacement: str,
    schema_accepts: bool,
    schema_value: dict[str, Any],
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    absolute_path_schema = schema_value["$defs"]["nullable_absolute_path"]
    assert _internal_schema_accepts(replacement, absolute_path_schema) is schema_accepts
    with pytest.raises(tool.SnapshotError) as raised:
        tool._require_normalized_absolute_posix(
            replacement,
            code="SNAPSHOT_INVARIANT_FAILED",
            label="test observation path",
        )
    assert raised.value.code == (
        "NON_NFC_VALUE"
        if replacement == "/cafe\N{COMBINING ACUTE ACCENT}"
        else "SNAPSHOT_INVARIANT_FAILED"
    )


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize("value", [None, "/", "/a/b:c"], ids=["null", "root", "nested"])
def test_absolute_observation_path_valid_boundaries(
    _obligation: str, value: str | None, schema_value: dict[str, Any]
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    absolute_path_schema = schema_value["$defs"]["nullable_absolute_path"]
    assert _internal_schema_accepts(value, absolute_path_schema)
    assert (
        tool._require_normalized_absolute_posix(value, code="TEST", label="test observation path")
        == value
    )


@obligation("MP2-000.OBL.SCHEMA_AND_CHECKSUM")
def test_exact_schema_fallback_without_jsonschema_dependency(
    _obligation: str,
    captured_pair: tuple[Path, Path],
    schema_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[5]
    probe = (
        "import importlib.util,sys\n"
        "assert importlib.util.find_spec('jsonschema') is None\n"
        "spec=importlib.util.spec_from_file_location('snapshot_tool',sys.argv[1])\n"
        "assert spec is not None and spec.loader is not None\n"
        "module=importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "snapshot=module._strict_json("
        "open(sys.argv[2],'rb').read(),require_canonical=True)\n"
        "schema=module._strict_json("
        "open(sys.argv[3],'rb').read(),require_canonical=True)\n"
        "print(module._validate_with_available_engine(snapshot,schema))\n"
        "snapshot['unexpected_root_key']=True\n"
        "try:\n"
        " module._validate_with_available_engine(snapshot,schema)\n"
        "except module.SnapshotError as exc:\n"
        " assert exc.code == 'SCHEMA_VALIDATION_FAILED'\n"
        " print(exc.code)\n"
        "else:\n"
        " raise AssertionError('fallback accepted invalid root property')\n"
    )
    result = _run(
        [
            sys.executable,
            "-S",
            "-c",
            probe,
            str(TOOL_PATH),
            str(captured_pair[0]),
            str(schema_path),
        ],
        cwd=captured_pair[0].parent,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stderr == b""
    assert result.stdout == (b"internal-exact-schema-v1\nSCHEMA_VALIDATION_FAILED\n")


CAPTURE_PATH_CASES = (
    pytest.param("existing-snapshot", "OUTPUT_EXISTS", id="existing-snapshot"),
    pytest.param("existing-checksum", "OUTPUT_EXISTS", id="existing-checksum"),
    pytest.param("dangling-snapshot", "OUTPUT_EXISTS", id="dangling-snapshot"),
    pytest.param("dangling-checksum", "OUTPUT_EXISTS", id="dangling-checksum"),
    pytest.param("directory-snapshot", "OUTPUT_EXISTS", id="directory-snapshot"),
    pytest.param("directory-checksum", "OUTPUT_EXISTS", id="directory-checksum"),
    pytest.param("symlinked-parent", "OUTPUT_PARENT_INVALID", id="symlinked-parent"),
    pytest.param("different-parents", "OUTPUT_PARENT_MISMATCH", id="different-parents"),
    pytest.param("wrong-snapshot-name", "OUTPUT_NAME_INVALID", id="wrong-snapshot"),
    pytest.param("wrong-checksum-name", "OUTPUT_NAME_INVALID", id="wrong-checksum"),
)


def _entry_identity(path: Path) -> tuple[Any, ...]:
    if not os.path.lexists(path):
        return ("absent",)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return ("symlink", os.readlink(path))
    if stat.S_ISREG(info.st_mode):
        return ("file", stat.S_IMODE(info.st_mode), path.read_bytes())
    if stat.S_ISDIR(info.st_mode):
        return (
            "directory",
            stat.S_IMODE(info.st_mode),
            tuple(sorted(os.listdir(path))),
        )
    return ("other", info.st_mode, info.st_size)


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(("path_case", "error_code"), CAPTURE_PATH_CASES)
def test_capture_cli_rejects_unsafe_output_paths_without_partial_publication(
    _obligation: str,
    path_case: str,
    error_code: str,
    ready_repo: Path,
    tmp_path: Path,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    parent = tmp_path / "outputs"
    parent.mkdir()
    output = parent / tool.SNAPSHOT_LEAF
    checksum = parent / tool.CHECKSUM_LEAF
    inspected_directories = [parent]
    if path_case.startswith("existing-"):
        target = output if path_case.endswith("snapshot") else checksum
        target.write_bytes(b"sentinel")
        target.chmod(0o640)
    elif path_case.startswith("dangling-"):
        target = output if path_case.endswith("snapshot") else checksum
        target.symlink_to("missing-target")
    elif path_case.startswith("directory-"):
        target = output if path_case.endswith("snapshot") else checksum
        target.mkdir()
        (target / "sentinel").write_bytes(b"preserve")
    elif path_case == "symlinked-parent":
        real_parent = tmp_path / "real-output-parent"
        real_parent.mkdir()
        linked_parent = tmp_path / "linked-output-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        output = linked_parent / tool.SNAPSHOT_LEAF
        checksum = linked_parent / tool.CHECKSUM_LEAF
        inspected_directories.append(real_parent)
    elif path_case == "different-parents":
        second_parent = tmp_path / "second-output-parent"
        second_parent.mkdir()
        checksum = second_parent / tool.CHECKSUM_LEAF
        inspected_directories.append(second_parent)
    elif path_case == "wrong-snapshot-name":
        output = parent / "wrong-snapshot.json"
    elif path_case == "wrong-checksum-name":
        checksum = parent / "wrong-checksum.sha256"

    before = {
        output: _entry_identity(output),
        checksum: _entry_identity(checksum),
    }
    result = _run_cli(
        ready_repo,
        "capture",
        "--repo",
        str(ready_repo),
        "--base-sha",
        AUDITED_BASE_SHA,
        "--output",
        str(output),
        "--checksum-output",
        str(checksum),
    )
    _assert_domain_failure(result, error_code)
    assert {path: _entry_identity(path) for path in before} == before
    for directory in inspected_directories:
        assert not [name for name in os.listdir(directory) if ".stage." in name]


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_atomic_pair_no_overwrite_symlink_rollback_and_concurrency(
    _obligation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    payload = tool._canonical_bytes({"schema_version": SCHEMA_VERSION})

    successful = tmp_path / "successful"
    successful.mkdir()
    snapshot = successful / tool.SNAPSHOT_LEAF
    checksum = successful / tool.CHECKSUM_LEAF
    tool._publish_pair(snapshot, checksum, payload)
    assert snapshot.read_bytes() == payload
    assert checksum.read_bytes() == f"{_sha(payload)}  {tool.SNAPSHOT_LEAF}\n".encode()
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o644
    assert stat.S_IMODE(checksum.stat().st_mode) == 0o644
    with pytest.raises(tool.SnapshotError) as raised:
        tool._publish_pair(snapshot, checksum, b"different")
    assert raised.value.code == "OUTPUT_EXISTS"
    assert snapshot.read_bytes() == payload

    symlink_parent = tmp_path / "symlink"
    symlink_parent.mkdir()
    target = symlink_parent / "target"
    target.write_bytes(b"sentinel")
    symlink = symlink_parent / tool.SNAPSHOT_LEAF
    symlink.symlink_to(target.name)
    with pytest.raises(tool.SnapshotError) as raised:
        tool._publish_pair(symlink, symlink_parent / tool.CHECKSUM_LEAF, payload)
    assert raised.value.code == "OUTPUT_EXISTS"
    assert symlink.is_symlink() and target.read_bytes() == b"sentinel"

    rollback = tmp_path / "rollback"
    rollback.mkdir()
    rollback_snapshot = rollback / tool.SNAPSHOT_LEAF
    rollback_checksum = rollback / tool.CHECKSUM_LEAF
    real_link = tool.os.link
    calls = 0

    def fail_second_link(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EIO, "synthetic second-link failure")
        real_link(*args, **kwargs)

    monkeypatch.setattr(tool.os, "link", fail_second_link)
    with pytest.raises(tool.SnapshotError) as raised:
        tool._publish_pair(rollback_snapshot, rollback_checksum, payload)
    assert raised.value.code == "ATOMIC_PUBLICATION_FAILED"
    assert not os.path.lexists(rollback_snapshot)
    assert not os.path.lexists(rollback_checksum)
    assert not list(rollback.glob("*.stage.*"))
    monkeypatch.setattr(tool.os, "link", real_link)

    concurrent = tmp_path / "concurrent"
    concurrent.mkdir()
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, bytes]] = []

    def publish(candidate: bytes) -> None:
        barrier.wait()
        try:
            tool._publish_pair(
                concurrent / tool.SNAPSHOT_LEAF,
                concurrent / tool.CHECKSUM_LEAF,
                candidate,
            )
            outcomes.append(("pass", candidate))
        except tool.SnapshotError:
            outcomes.append(("fail", candidate))

    threads = [threading.Thread(target=publish, args=(value,)) for value in (b"one", b"two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    winners = [candidate for result, candidate in outcomes if result == "pass"]
    assert len(winners) == 1
    assert concurrent.joinpath(tool.SNAPSHOT_LEAF).read_bytes() == winners[0]
    assert concurrent.joinpath(tool.CHECKSUM_LEAF).read_bytes() == (
        f"{_sha(winners[0])}  {tool.SNAPSHOT_LEAF}\n".encode()
    )


ATOMIC_FAULT_CASES = (
    "first-link-side-effect",
    "second-link-side-effect",
    "stage-open",
    "stage-fstat-nonregular",
    "stage-fstat-unknown-ownership",
    "stage-write",
    "stage-fchmod",
    "stage-file-fsync",
    "final-directory-fsync",
    "first-stage-collision",
    "second-stage-collision",
    "both-stage-cleanups",
    "stage-inode-replacement",
    "final-inode-replacement",
    "rollback-stat-eacces",
    "rollback-stat-eio",
    "path-safety-capability-absent",
)


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize("fault_case", ATOMIC_FAULT_CASES)
def test_atomic_publication_fault_matrix_preserves_only_owned_entries(
    _obligation: str,
    fault_case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    parent = tmp_path / fault_case
    parent.mkdir()
    original_open = tool.os.open
    original_fstat = tool.os.fstat
    original_fsync = tool.os.fsync
    original_link = tool.os.link
    original_stat = tool.os.stat
    original_unlink = tool.os.unlink
    original_write = tool.os.write
    directory_fd = original_open(parent, os.O_RDONLY | os.O_DIRECTORY)
    token = "d" * 32
    suffix = f".{os.getpid()}.{token}"
    stage_names = (
        f".{tool.SNAPSHOT_LEAF}.stage{suffix}",
        f".{tool.CHECKSUM_LEAF}.stage{suffix}",
    )
    monkeypatch.setattr(tool.secrets, "token_hex", lambda _size: token)

    def expect_error(call: Callable[[], None], code: str) -> Any:
        with pytest.raises(tool.SnapshotError) as raised:
            call()
        assert raised.value.code == code
        return raised.value

    try:
        if fault_case in {"first-link-side-effect", "second-link-side-effect"}:
            failure_call = 1 if fault_case.startswith("first") else 2
            calls = 0

            def link_then_raise(*args: Any, **kwargs: Any) -> None:
                nonlocal calls
                calls += 1
                original_link(*args, **kwargs)
                if calls == failure_call:
                    raise OSError(errno.EIO, "link failed after side effect")

            monkeypatch.setattr(tool.os, "link", link_then_raise)
            expect_error(
                lambda: tool._publish_pair_at(directory_fd, b"{}"),
                "ATOMIC_PUBLICATION_FAILED",
            )
            assert calls == failure_call
            assert list(parent.iterdir()) == []
        elif fault_case == "stage-open":

            def fail_stage_open(*_args: Any, **_kwargs: Any) -> int:
                raise OSError(errno.EIO, "stage open failed")

            monkeypatch.setattr(tool.os, "open", fail_stage_open)
            expect_error(
                lambda: tool._write_stage(directory_fd, ".stage", b"payload"),
                "OUTPUT_WRITE_FAILED",
            )
            assert list(parent.iterdir()) == []
        elif fault_case == "stage-fstat-nonregular":
            calls = 0

            def nonregular_fstat(target_fd: int) -> Any:
                nonlocal calls
                calls += 1
                result = original_fstat(target_fd)
                if calls == 1:
                    return SimpleNamespace(
                        st_mode=stat.S_IFIFO | 0o600,
                        st_dev=result.st_dev,
                        st_ino=result.st_ino,
                    )
                return result

            monkeypatch.setattr(tool.os, "fstat", nonregular_fstat)
            expect_error(
                lambda: tool._write_stage(directory_fd, ".stage", b"payload"),
                "OUTPUT_WRITE_FAILED",
            )
            assert list(parent.iterdir()) == []
        elif fault_case == "stage-fstat-unknown-ownership":

            def fail_fstat(_target_fd: int) -> Any:
                raise OSError(errno.EIO, "fstat failed after exclusive open")

            monkeypatch.setattr(tool.os, "fstat", fail_fstat)
            error = expect_error(
                lambda: tool._write_stage(directory_fd, ".stage", b"payload"),
                "OUTPUT_WRITE_FAILED",
            )
            assert "safe cleanup ownership could not be established" in error.message
            assert (parent / ".stage").is_file()
        elif fault_case in {"stage-write", "stage-fchmod", "stage-file-fsync"}:
            operation = {
                "stage-write": "write",
                "stage-fchmod": "fchmod",
                "stage-file-fsync": "fsync",
            }[fault_case]

            def fail_owned_operation(*_args: Any, **_kwargs: Any) -> Any:
                raise OSError(errno.EIO, f"{operation} failed")

            monkeypatch.setattr(tool.os, operation, fail_owned_operation)
            expect_error(
                lambda: tool._write_stage(directory_fd, ".stage", b"payload"),
                "OUTPUT_WRITE_FAILED",
            )
            assert list(parent.iterdir()) == []
        elif fault_case == "final-directory-fsync":
            calls = 0

            def fail_final_fsync(target_fd: int) -> None:
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError(errno.EIO, "final directory fsync failed")
                original_fsync(target_fd)

            monkeypatch.setattr(tool.os, "fsync", fail_final_fsync)
            expect_error(
                lambda: tool._publish_pair_at(directory_fd, b"{}"),
                "ATOMIC_PUBLICATION_FAILED",
            )
            assert list(parent.iterdir()) == []
        elif fault_case in {"first-stage-collision", "second-stage-collision"}:
            stage_index = 0 if fault_case.startswith("first") else 1
            sentinel = parent / stage_names[stage_index]
            sentinel.write_bytes(b"sentinel")
            expect_error(
                lambda: tool._publish_pair_at(directory_fd, b"{}"),
                "OUTPUT_WRITE_FAILED",
            )
            assert sentinel.read_bytes() == b"sentinel"
            assert sorted(item.name for item in parent.iterdir()) == [sentinel.name]
        elif fault_case == "both-stage-cleanups":
            original_helper = tool._unlink_owned_entry
            observed: list[str] = []
            injected = False

            def fail_first_cleanup(directory: int, leaf: str, identity: Any) -> str | None:
                nonlocal injected
                if leaf in stage_names:
                    observed.append(leaf)
                if leaf == stage_names[0] and not injected:
                    injected = True
                    return f"{leaf}: injected cleanup failure"
                return cast(str | None, original_helper(directory, leaf, identity))

            monkeypatch.setattr(tool, "_unlink_owned_entry", fail_first_cleanup)
            expect_error(
                lambda: tool._publish_pair_at(directory_fd, b"{}"),
                "OUTPUT_CLEANUP_FAILED",
            )
            assert set(stage_names).issubset(observed)
            assert list(parent.iterdir()) == []
        elif fault_case == "stage-inode-replacement":
            replaced = False

            def replace_during_write(target_fd: int, data: bytes) -> int:
                nonlocal replaced
                if not replaced:
                    replaced = True
                    original_unlink(".stage", dir_fd=directory_fd)
                    replacement_fd = original_open(
                        ".stage",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                        0o600,
                        dir_fd=directory_fd,
                    )
                    try:
                        original_write(replacement_fd, b"external")
                    finally:
                        os.close(replacement_fd)
                    raise OSError(errno.EIO, "write failed after replacement")
                return cast(int, original_write(target_fd, data))

            monkeypatch.setattr(tool.os, "write", replace_during_write)
            error = expect_error(
                lambda: tool._write_stage(directory_fd, ".stage", b"payload"),
                "OUTPUT_WRITE_FAILED",
            )
            assert "entry identity changed" in error.message
            assert (parent / ".stage").read_bytes() == b"external"
        elif fault_case == "final-inode-replacement":
            calls = 0

            def replace_final_after_link(*args: Any, **kwargs: Any) -> None:
                nonlocal calls
                calls += 1
                original_link(*args, **kwargs)
                if calls == 1:
                    original_unlink(tool.SNAPSHOT_LEAF, dir_fd=directory_fd)
                    replacement_fd = original_open(
                        tool.SNAPSHOT_LEAF,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                        0o600,
                        dir_fd=directory_fd,
                    )
                    try:
                        original_write(replacement_fd, b"external-final")
                    finally:
                        os.close(replacement_fd)
                    raise OSError(errno.EIO, "link failed after replacement")

            monkeypatch.setattr(tool.os, "link", replace_final_after_link)
            error = expect_error(
                lambda: tool._publish_pair_at(directory_fd, b"{}"),
                "ATOMIC_PUBLICATION_FAILED",
            )
            assert "entry identity changed" in error.message
            assert (parent / tool.SNAPSHOT_LEAF).read_bytes() == b"external-final"
            assert not (parent / tool.CHECKSUM_LEAF).exists()
            assert not any(".stage." in item.name for item in parent.iterdir())
        elif fault_case.startswith("rollback-stat-"):
            linked = False

            def fail_link_after_effect(*args: Any, **kwargs: Any) -> None:
                nonlocal linked
                original_link(*args, **kwargs)
                linked = True
                raise OSError(errno.EIO, "link failed after side effect")

            stat_errno = errno.EACCES if fault_case.endswith("eacces") else errno.EIO

            def fail_rollback_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
                if linked and path == tool.SNAPSHOT_LEAF:
                    raise OSError(stat_errno, "rollback stat failed")
                return original_stat(path, *args, **kwargs)

            monkeypatch.setattr(tool.os, "link", fail_link_after_effect)
            monkeypatch.setattr(tool.os, "stat", fail_rollback_stat)
            error = expect_error(
                lambda: tool._publish_pair_at(directory_fd, b"{}"),
                "ATOMIC_PUBLICATION_FAILED",
            )
            assert "cannot inspect entry identity" in error.message
            assert (parent / tool.SNAPSHOT_LEAF).is_file()
        else:
            monkeypatch.setattr(tool.os, "supports_dir_fd", set())
            expect_error(
                tool._require_descriptor_capabilities,
                "PATH_SAFETY_UNAVAILABLE",
            )
            assert list(parent.iterdir()) == []
    finally:
        os.close(directory_fd)


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
@pytest.mark.parametrize(
    "race_case",
    [
        "after-preflight",
        "before-links",
        "after-links",
        "relative-cwd-after-preflight",
    ],
)
def test_output_parent_replacement_is_detected_and_rolled_back(
    _obligation: str,
    race_case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    requested = tmp_path / "requested"
    held = tmp_path / "held"
    external = tmp_path / "external"
    if race_case == "relative-cwd-after-preflight":
        (requested / "output").mkdir(parents=True)
        (external / "output").mkdir(parents=True)
        snapshot = Path("output") / tool.SNAPSHOT_LEAF
        checksum = Path("output") / tool.CHECKSUM_LEAF
    else:
        requested.mkdir()
        external.mkdir()
        snapshot = requested / tool.SNAPSHOT_LEAF
        checksum = requested / tool.CHECKSUM_LEAF

    if race_case in {"after-preflight", "relative-cwd-after-preflight"}:
        original_preflight = tool._preflight_capture_outputs

        def replace_after_preflight(output: Path, checksum_output: Path) -> tuple[Path, int]:
            requested_parent, directory_fd = original_preflight(output, checksum_output)
            requested.rename(held)
            requested.symlink_to(external, target_is_directory=True)
            return requested_parent, directory_fd

        monkeypatch.setattr(tool, "_preflight_capture_outputs", replace_after_preflight)
    else:
        original_identity_check = tool._require_output_parent_identity
        swap_after_call = 1 if race_case == "before-links" else 2
        calls = 0

        def replace_during_publication(path: Path, directory_fd: int) -> None:
            nonlocal calls
            calls += 1
            original_identity_check(path, directory_fd)
            if calls == swap_after_call:
                requested.rename(held)
                requested.symlink_to(external, target_is_directory=True)

        monkeypatch.setattr(tool, "_require_output_parent_identity", replace_during_publication)

    original_cwd = Path.cwd()
    if race_case == "relative-cwd-after-preflight":
        os.chdir(requested)
    try:
        with pytest.raises(tool.SnapshotError) as raised:
            tool._publish_pair(snapshot, checksum, b"{}")
        assert raised.value.code == "OUTPUT_PARENT_RACE"
    finally:
        if race_case == "relative-cwd-after-preflight":
            os.chdir(original_cwd)
    assert requested.is_symlink()
    held_output = held / "output" if race_case.startswith("relative") else held
    external_output = external / "output" if race_case.startswith("relative") else external
    assert list(held_output.iterdir()) == []
    assert list(external_output.iterdir()) == []


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_input_leaf_swap_to_symlink_fails_without_reading_target(
    _obligation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    victim = tmp_path / "input.json"
    victim.write_bytes(b"original")
    external = tmp_path / "external"
    external.write_bytes(b"external-sentinel")
    original_open = tool.os.open
    swapped = False

    def swap_before_leaf_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal swapped
        if str(path) == victim.name and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            victim.unlink()
            victim.symlink_to(external)
        return cast(int, original_open(path, flags, *args, **kwargs))

    monkeypatch.setattr(tool.os, "open", swap_before_leaf_open)
    with pytest.raises(tool.SnapshotError) as raised:
        tool._read_regular(victim, 1024)
    assert raised.value.code == "NOT_REGULAR_FILE"
    assert swapped
    assert victim.is_symlink()
    assert external.read_bytes() == b"external-sentinel"


@obligation("MP2-000.OBL.THREE_RUN_DETERMINISM")
def test_three_run_determinism(_obligation: str, ready_repo: Path, tmp_path: Path) -> None:
    assert _obligation == OBLIGATION_IDS[3]
    before = _run(["git", "status", "--porcelain=v1"], cwd=ready_repo).stdout
    pairs: list[tuple[bytes, bytes]] = []
    capture_directories: list[Path] = []
    for index in range(3):
        parent = tmp_path / f"capture-{index}"
        parent.mkdir()
        capture_directories.append(parent)
        snapshot = parent / tool.SNAPSHOT_LEAF
        checksum = parent / tool.CHECKSUM_LEAF
        result = _run_bootstrap_cli(
            ready_repo,
            "capture",
            "--repo",
            str(ready_repo),
            "--base-sha",
            AUDITED_BASE_SHA,
            "--output",
            str(snapshot),
            "--checksum-output",
            str(checksum),
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        assert result.stdout == result.stderr == b""
        pairs.append((snapshot.read_bytes(), checksum.read_bytes()))
    assert pairs[0] == pairs[1] == pairs[2]
    after = _run(["git", "status", "--porcelain=v1"], cwd=ready_repo).stdout
    assert after == before == b""
    snapshot_text = pairs[0][0].decode("utf-8")
    snapshot_value = cast(dict[str, Any], tool._strict_json(pairs[0][0], require_canonical=True))

    def keys_in(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {nested for child in value.values() for nested in keys_in(child)}
        if isinstance(value, list):
            return {nested for child in value for nested in keys_in(child)}
        return set()

    assert str(tmp_path) not in snapshot_text
    assert not {
        "captured_at",
        "duration",
        "duration_seconds",
        "elapsed",
        "timestamp",
    }.intersection(keys_in(snapshot_value))
    for directory in capture_directories:
        (directory / tool.SNAPSHOT_LEAF).unlink()
        (directory / tool.CHECKSUM_LEAF).unlink()
        directory.rmdir()
    assert all(not directory.exists() for directory in capture_directories)


@obligation("MP2-000.OBL.DOCS_PARITY")
def test_docs_parity(_obligation: str) -> None:
    assert _obligation == OBLIGATION_IDS[6]
    text = DOCS_PATH.read_text(encoding="utf-8")
    required = (
        "tools/baseline_snapshot.py capture",
        "tools/baseline_snapshot.py validate",
        "tools/baseline_snapshot.py check",
        AUDITED_BASE_SHA,
        AUDITED_BASE_TREE,
        "Miko997/metriplane",
        SCHEMA_VERSION,
        "schemas/metriplane.baseline-snapshot.v1.schema.json",
        "docs/status/baseline-snapshot.v1.json",
        "docs/status/baseline-snapshot.v1.sha256",
        "92-byte",
        "no trailing newline",
        "not_measured",
        "MP2-007",
        "MP2-010",
        "MP2-011",
        "MP2-012",
        "MP2-013",
        "MP2-014",
        "MP2-015",
        "MP2-016",
        "256-resource",
        "48 terminal",
        "v0.4",
        "bootstrap-only maintainer command",
        "qualifying `READY` MP2-000 work-order instance",
        "ordinary clean checkout uses the committed",
        "all internal semantic invariants",
        "identity-safe rollback",
        "residual pair must not be treated as authoritative",
        "does not execute the invoking",
        "frozen installed-help identities",
        "supersession through MP2-017",
    )
    assert all(fragment in text for fragment in required)
    assert "does not remove, rewrite, or\nreplace any commit" in text
    parser = tool._parser()
    subparser_actions = [
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    ]
    assert len(subparser_actions) == 1
    assert set(subparser_actions[0].choices) == {"capture", "validate", "check"}


@obligation("MP2-000.OBL.FINAL_CLEAN_TREE")
def test_capture_writes_only_the_two_requested_temp_outputs(
    _obligation: str, ready_repo: Path, tmp_path: Path
) -> None:
    assert _obligation == OBLIGATION_IDS[7]
    before_status = _run(["git", "status", "--porcelain=v1"], cwd=ready_repo).stdout
    assert list(tmp_path.iterdir()) == []
    snapshot = tmp_path / tool.SNAPSHOT_LEAF
    checksum = tmp_path / tool.CHECKSUM_LEAF
    result = _run_bootstrap_cli(
        ready_repo,
        "capture",
        "--repo",
        str(ready_repo),
        "--base-sha",
        AUDITED_BASE_SHA,
        "--output",
        str(snapshot),
        "--checksum-output",
        str(checksum),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert {path.name for path in tmp_path.iterdir()} == {
        tool.SNAPSHOT_LEAF,
        tool.CHECKSUM_LEAF,
    }
    assert not list(tmp_path.glob("*.stage.*"))
    after_status = _run(["git", "status", "--porcelain=v1"], cwd=ready_repo).stdout
    assert after_status == before_status == b""


@obligation("MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER")
def test_capture_validates_schema_and_semantics_before_publication(
    _obligation: str,
    ready_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    assert _obligation == OBLIGATION_IDS[2]
    output = tmp_path / tool.SNAPSHOT_LEAF
    checksum = tmp_path / tool.CHECKSUM_LEAF
    monkeypatch.setattr(
        tool,
        "_build_snapshot",
        lambda _repo, _base: {"schema_version": SCHEMA_VERSION},
    )
    result = tool.main(
        [
            "capture",
            "--repo",
            str(ready_repo),
            "--base-sha",
            AUDITED_BASE_SHA,
            "--output",
            str(output),
            "--checksum-output",
            str(checksum),
        ]
    )
    assert result == 3
    captured = capfd.readouterr()
    assert captured.out == ""
    error = tool._strict_json(captured.err.encode("utf-8"), require_canonical=True)
    assert error["ok"] is False
    assert not os.path.lexists(output)
    assert not os.path.lexists(checksum)
    assert not [name for name in os.listdir(tmp_path) if ".stage." in name]


def _copy_source_for_build(source: Path, destination: Path) -> None:
    ignored_names = {
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in ignored_names or name.endswith((".egg-info", ".pyc", ".pyo"))
        }

    shutil.copytree(source, destination, ignore=ignore)


@obligation("MP2-000.OBL.INSTALLED_HELP_AND_RESOURCES")
def test_installed_wheel_help_and_resources_fail_closed(_obligation: str, tmp_path: Path) -> None:
    assert _obligation == OBLIGATION_IDS[4]
    source = tmp_path / "source"
    _copy_source_for_build(ROOT, source)
    dist = tmp_path / "dist"
    dist.mkdir()
    uv = shutil.which("uv")
    assert uv is not None
    installer_env: dict[str, str] = {}
    base_python = Path(_BOOTSTRAP_CLI_PYTHON)
    bootstrap_paths_result = _run(
        [
            str(base_python),
            "-c",
            (
                "import json,sys,sysconfig; "
                "print(json.dumps({'prefix':sys.prefix,'purelib':"
                "sysconfig.get_paths()['purelib']},sort_keys=True))"
            ),
        ],
        cwd=source,
    )
    assert bootstrap_paths_result.returncode == 0, bootstrap_paths_result.stderr.decode(
        "utf-8", "replace"
    )
    bootstrap_paths = json.loads(bootstrap_paths_result.stdout)
    bootstrap_prefix = Path(bootstrap_paths["prefix"])
    bootstrap_site_packages = Path(bootstrap_paths["purelib"])
    assert bootstrap_site_packages.resolve().is_relative_to(bootstrap_prefix.resolve())
    built = _run(
        [
            uv,
            "--no-config",
            "build",
            "--wheel",
            "--offline",
            "--python",
            str(base_python),
            "--out-dir",
            str(dist),
        ],
        cwd=source,
        env=installer_env,
    )
    assert built.returncode == 0, built.stderr.decode("utf-8", "replace")
    wheels = list(dist.glob("metriplane-0.3.0-*.whl"))
    assert len(wheels) == 1

    venv = tmp_path / "installed-venv"
    created = _run(
        [
            uv,
            "--no-config",
            "venv",
            "--system-site-packages",
            "--python",
            str(base_python),
            str(venv),
        ],
        cwd=tmp_path,
        env=installer_env,
    )
    assert created.returncode == 0, created.stderr.decode("utf-8", "replace")
    binary = venv / ("Scripts" if os.name == "nt" else "bin")
    installed_site_packages = list(venv.glob("lib/python*/site-packages"))
    assert len(installed_site_packages) == 1
    (installed_site_packages[0] / "bootstrap-dependency-inventory.pth").write_text(
        f"{bootstrap_site_packages}\n", encoding="utf-8"
    )
    installed = _run(
        [
            uv,
            "--no-config",
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--python",
            str(binary / "python"),
            str(wheels[0]),
        ],
        cwd=tmp_path,
        env=installer_env,
    )
    assert installed.returncode == 0, installed.stderr.decode("utf-8", "replace")

    unrelated = tmp_path / "unrelated-cwd"
    unrelated.mkdir()
    home = tmp_path / "home"
    environment: dict[str, str] = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "xdg-config"),
        "XDG_CACHE_HOME": str(home / "xdg-cache"),
        "XDG_DATA_HOME": str(home / "xdg-data"),
        "XDG_STATE_HOME": str(home / "xdg-state"),
        "TMPDIR": str(tmp_path / "runtime-tmp"),
        "UV_CACHE_DIR": str(tmp_path / "runtime-uv-cache"),
        "PYTHONNOUSERSITE": "1",
    }
    for value in environment.values():
        if value.startswith("/"):
            Path(value).mkdir(parents=True, exist_ok=True)
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    clean_env.pop("PYTHONHOME", None)
    clean_env.update(environment)

    imported = subprocess.run(
        [
            str(binary / "python"),
            "-c",
            (
                "import importlib.metadata as m,metriplane; "
                "print(m.version('metriplane')); print(metriplane.__file__)"
            ),
        ],
        cwd=unrelated,
        env=clean_env,
        capture_output=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr.decode("utf-8", "replace")
    version, imported_path = imported.stdout.decode().splitlines()
    assert version == "0.3.0"
    assert Path(imported_path).is_relative_to(venv)
    assert not Path(imported_path).is_relative_to(ROOT)

    for command, (size, digest) in HELP_IDENTITIES.items():
        result = subprocess.run(
            [str(binary / command), "--help"],
            cwd=unrelated,
            env=clean_env,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        assert result.stderr == b""
        assert len(result.stdout) == size
        assert _sha(result.stdout) == digest

    resource_probe = (
        "import hashlib,json; from importlib import resources; "
        f"paths={list(RESOURCE_IDENTITIES)!r}; root=resources.files('metriplane.demo'); "
        "rows={p:{'sha256':hashlib.sha256(root.joinpath(p).read_bytes()).hexdigest(),"
        "'path':str(root.joinpath(p))} for p in paths}; "
        "print(json.dumps(rows,sort_keys=True,separators=(',',':')))"
    )
    resources_result = subprocess.run(
        [str(binary / "python"), "-c", resource_probe],
        cwd=unrelated,
        env=clean_env,
        capture_output=True,
        check=False,
    )
    assert resources_result.returncode == 0, resources_result.stderr.decode("utf-8", "replace")
    rows = json.loads(resources_result.stdout)
    assert {path: row["sha256"] for path, row in rows.items()} == RESOURCE_IDENTITIES
    missing_relative = "assets/assembly_cell_missing_tool.jsonl"
    missing_path = Path(rows[missing_relative]["path"])
    assert missing_path.is_relative_to(venv)
    missing_path.unlink()

    doctor = subprocess.run(
        [str(binary / "metriplane"), "doctor"],
        cwd=unrelated,
        env=clean_env,
        capture_output=True,
        check=False,
    )
    assert doctor.returncode == 1
    assert doctor.stderr == b""
    assert missing_relative.encode() in doctor.stdout
    assert b"Not ready for the bundled camera-free demo." in doctor.stdout
    for child in list(tmp_path.iterdir()):
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)
    assert list(tmp_path.iterdir()) == []
