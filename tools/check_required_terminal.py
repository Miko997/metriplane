# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Validate an aggregate required terminal without accepting partial success."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import platform
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SUCCESS = "success"


class TerminalValidationError(ValueError):
    """The aggregate cannot truthfully report success."""


def validate_terminal(
    *,
    terminal: str,
    expected_sha: str,
    expected_dependencies: list[str],
    results: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Return a deterministic success record or raise on any mismatch."""
    if len(expected_dependencies) != len(set(expected_dependencies)):
        raise TerminalValidationError("expected dependencies contain duplicates")
    expected = set(expected_dependencies)
    actual = set(results)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise TerminalValidationError(
            f"dependency set mismatch; missing={missing!r}; extra={extra!r}"
        )
    failures: list[str] = []
    for name in expected_dependencies:
        result = results[name]
        if set(result) != {"result", "sha"}:
            failures.append(f"{name}: invalid result shape")
            continue
        if result["sha"] != expected_sha:
            failures.append(f"{name}: wrong SHA {result['sha']!r}, expected {expected_sha!r}")
        if result["result"] != SUCCESS:
            failures.append(f"{name}: result is {result['result']!r}, expected success")
    if failures:
        raise TerminalValidationError("; ".join(failures))
    return {
        "dependencies": expected_dependencies,
        "result": SUCCESS,
        "schema_version": 1,
        "sha": expected_sha,
        "terminal": terminal,
    }


def validate_policy(path: Path, workflow_root: Path) -> dict[str, Any]:
    """Validate sole producers and the future Release handoff."""
    try:
        import yaml
    except ImportError as exc:
        raise TerminalValidationError("policy validation requires PyYAML") from exc

    policy = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise TerminalValidationError("terminal policy must be a JSON object")
    terminals = policy["terminals"]
    expected_names = {
        "Metriplane / required",
        "Documentation / required",
        "Security / required",
        "Main health / required",
        "Release / required",
    }
    expected_active_producers = {
        "Metriplane / required": ".github/workflows/ci.yml",
        "Documentation / required": ".github/workflows/docs.yml",
        "Security / required": ".github/workflows/codeql.yml",
        "Main health / required": "github-app:metriplane-main-health-publisher",
    }
    if {item["name"] for item in terminals} != expected_names:
        raise TerminalValidationError("terminal inventory is incomplete or contains extras")

    workflow_job_names: dict[str, list[str]] = {}
    workflow_paths = sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")))
    for workflow_path in workflow_paths:
        try:
            document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise TerminalValidationError(f"{workflow_path.name}: invalid workflow YAML") from exc
        if not isinstance(document, dict) or not isinstance(document.get("jobs"), dict):
            raise TerminalValidationError(f"{workflow_path.name}: workflow jobs must be an object")
        workflow_job_names[workflow_path.name] = [
            job["name"]
            for job in document["jobs"].values()
            if isinstance(job, dict) and isinstance(job.get("name"), str)
        ]
    for workflow_name, job_names in workflow_job_names.items():
        for job_name in job_names:
            if "${{" not in job_name:
                continue
            expression_start = job_name.find("${{")
            expression_end = job_name.rfind("}}")
            if expression_end < expression_start:
                raise TerminalValidationError(f"{workflow_name}: malformed dynamic job name")
            prefix = job_name[:expression_start]
            suffix = job_name[expression_end + 2 :]
            ambiguous = [
                name
                for name in expected_names
                if name.startswith(prefix)
                and name.endswith(suffix)
                and len(name) >= len(prefix) + len(suffix)
            ]
            if ambiguous:
                raise TerminalValidationError(
                    f"{workflow_name}: dynamic job name may produce protected terminal(s) "
                    f"{ambiguous!r}"
                )
    for terminal in terminals:
        producers = [
            name for name, job_names in workflow_job_names.items() if terminal["name"] in job_names
        ]
        if terminal["state"] == "active":
            producer = terminal["producer"]
            expected_producer = expected_active_producers.get(terminal["name"])
            if expected_producer is None:
                raise TerminalValidationError("Release / required must remain reserved")
            if terminal["owner"] != "MP2-004" or producer != expected_producer:
                raise TerminalValidationError(
                    f"{terminal['name']}: owner or producer is not the governed MP2-004 value"
                )
            if "transition" in terminal:
                raise TerminalValidationError(f"{terminal['name']}: transition is not permitted")
            if producer == "github-app:metriplane-main-health-publisher":
                expected_producers = []
            else:
                assert isinstance(producer, str)
                expected_producers = [Path(producer).name]
            if producers != expected_producers:
                raise TerminalValidationError(
                    f"{terminal['name']}: expected sole producer {producer!r}, found {producers!r}"
                )
        elif terminal["state"] == "reserved":
            if terminal["name"] != "Release / required":
                raise TerminalValidationError("only Release / required may be reserved")
            if terminal["owner"] != "MP2-007" or producers:
                raise TerminalValidationError(
                    "Release / required must be producer-free and reserved for MP2-007"
                )
        else:
            raise TerminalValidationError(f"{terminal['name']}: terminal state is invalid")
    return dict(policy)


# These reports describe source qualification, never a release or approval record.
_SUITE_SCHEMA = "metriplane.ci-suite-report.v1"
_SUITE_FILES = ("stdout.txt", "stderr.txt", "junit.xml")
_SOURCE_FILES = (
    ".github/workflows/ci.yml",
    "tools/check_required_terminal.py",
    "pyproject.toml",
    "uv.lock",
    "conftest.py",
    "tests/conftest.py",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TerminalValidationError(message)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _shape(value: Any, keys: set[str], label: str) -> None:
    _require(isinstance(value, dict) and set(value) == keys, f"{label}: invalid shape")


def _strings(value: Any, label: str, *, nonempty: bool = True) -> None:
    _require(isinstance(value, list), f"{label}: expected list")
    _require(all(isinstance(x, str) and x for x in value), f"{label}: invalid string")
    _require(len(set(value)) == len(value), f"{label}: duplicate identity")
    _require(bool(value) or not nonempty, f"{label}: empty")


def _number(value: Any, label: str) -> None:
    _require(
        type(value) in (int, float) and math.isfinite(value) and value >= 0,
        f"{label}: invalid duration",
    )


def _safe_bytes(path: Path) -> bytes:
    _require(not path.is_symlink(), f"symlink evidence: {path}")
    _require(path.is_file() and stat.S_ISREG(path.stat().st_mode), f"not regular: {path}")
    return path.read_bytes()


def _file_identity(path: Path) -> dict[str, Any]:
    raw = _safe_bytes(path)
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _source_identity(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    _require(git("status", "--porcelain", "--untracked-files=all") == "", "unclean source")
    commit, tree = git("rev-parse", "HEAD", "HEAD^{tree}").splitlines()
    inventory = subprocess.check_output(["git", "ls-tree", "-r", "-z", "HEAD"], cwd=root)
    # Raw Git bytes: mode SP type SP object-id TAB unquoted path NUL, in Git tree
    # order. No decoding, newline conversion, filtering, or locale sorting.
    # The retained commit deterministically reconstructs these exact bytes.
    reconstructed = subprocess.check_output(["git", "ls-tree", "-r", "-z", commit], cwd=root)
    _require(inventory == reconstructed, "HEAD tree inventory changed during capture")
    _require(
        git("rev-parse", "HEAD", "HEAD^{tree}").splitlines() == [commit, tree],
        "source commit changed during capture",
    )
    return {
        "commit": commit,
        "tree": tree,
        "tree_inventory": {
            "format": "git-ls-tree-r-z.v1",
            "bytes": len(inventory),
            "sha256": hashlib.sha256(inventory).hexdigest(),
        },
        "files": {name: _file_identity(root / name) for name in _SOURCE_FILES},
    }


def _validate_source_identity(source: Any) -> None:
    _shape(source, {"commit", "tree", "tree_inventory", "files"}, "source identity")
    for name in ("commit", "tree"):
        _require(
            isinstance(source[name], str) and re.fullmatch(r"[0-9a-f]{40}", source[name]),
            f"invalid source {name}",
        )
    inventory = source["tree_inventory"]
    _shape(inventory, {"format", "bytes", "sha256"}, "source inventory")
    _require(inventory["format"] == "git-ls-tree-r-z.v1", "wrong source inventory encoding")
    _require(
        type(inventory["bytes"]) is int and inventory["bytes"] > 0, "invalid source inventory bytes"
    )
    _require(
        isinstance(inventory["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", inventory["sha256"]),
        "invalid source digest",
    )
    _shape(source["files"], set(_SOURCE_FILES), "source control files")
    for name, binding in source["files"].items():
        _shape(binding, {"bytes", "sha256"}, name)
        _require(
            type(binding["bytes"]) is int and binding["bytes"] >= 0, "invalid source control bytes"
        )
        _require(
            isinstance(binding["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]),
            "invalid source control digest",
        )


def _job_name(system: str, version: str) -> str:
    return (
        "macos-regressions"
        if system == "macos"
        else ("test" if version == "3.12" else "linux-python313")
    )


def _coordinates() -> list[tuple[str, str, int, int]]:
    return [
        (system, version, index, count)
        for system, count in (("linux", 1), ("macos", 4))
        for version in ("3.12", "3.13")
        for index in range(count)
    ]


def _artifact_name(run_id: str, attempt: str, system: str, version: str, index: int) -> str:
    return f"ci-suite-{run_id}-{attempt}-{system}-py{version}-shard{index}"


def _expected_skips(system: str) -> dict[str, tuple[str, str]]:
    adapter = "tests/adapter_conformance/test_results.py::"
    names = [
        "test_result_shape_rejects_missing_or_extra_fields",
        "test_result_schema_and_semantics_reject_vacuous_pass_records",
        "test_package_only_python_result_cannot_claim_unexecuted_contract_evidence",
        "test_summary_accepts_only_the_complete_exact_commit_result_set",
        "test_summary_rejects_a_missing_required_job",
        "test_summary_rejects_missing_stale_duplicate_and_failed_records",
    ] + [
        f"test_summary_rejects_every_non_success_job_result[{status}]"
        for status in ("failure", "cancelled", "skipped", "neutral", "timed_out", "missing")
    ]
    result = {
        adapter + name: (
            "setup",
            "result-schema tests run in the locked cross-adapter gate environment",
        )
        for name in names
    }
    result.update(
        {
            "tests/test_gpu_equivalence_extended.py::test_gpu_matches_cpu_if_available": (
                "call",
                "could not import 'cupy': No module named 'cupy'",
            ),
            "tests/test_functional_inventory.py::test_final_criterion_evidence_bindings"
            "[MP2-010.OBL.TRACE_CLOSURE]": (
                "call",
                "requires governed retained evidence profile via "
                "METRIPLANE_MP2_010_MATERIALIZATION_ROOT",
            ),
            "tests/test_functional_inventory.py::test_installed_console_scripts_match_frozen_cli_seed"
            "[MP2-010.OBL.INSTALLED_ENTRY_POINTS]": (
                "call",
                "requires the governed non-editable installed test profile",
            ),
        }
    )
    if system == "macos":
        result.update(
            {
                "tests/e2e/test_dashboard_playwright_smoke.py::"
                "test_dashboard_pages_render_without_uncaught_js_errors": (
                    "call",
                    "Playwright Chromium browser is not installed",
                ),
                "tests/ui_api/test_operator_api_safety.py::"
                "test_generate_report_async_child_reads_pinned_inode_after_parent_swap": (
                    "setup",
                    "Linux /proc descriptor path",
                ),
            }
        )
    return result


def _validate_suite_identity(
    identity: Any, *, source: dict[str, Any], run_id: str, attempt: str, repository: str
) -> None:
    _shape(
        identity,
        {
            "source",
            "workflow",
            "repository",
            "run_id",
            "run_attempt",
            "job",
            "platform",
            "python_version",
            "python_full",
            "pytest_version",
            "runner_os",
            "runner_arch",
            "runner_image",
            "runner_image_version",
        },
        "suite identity",
    )
    _validate_source_identity(identity["source"])
    _require(identity["source"] == source, "suite source drift")
    _require(
        identity["workflow"] == "CI" and identity["repository"] == repository,
        "wrong workflow or repository",
    )
    _require(
        identity["run_id"] == run_id and identity["run_attempt"] == attempt, "wrong run or attempt"
    )
    system, version = identity["platform"], identity["python_version"]
    _require(
        system in ("linux", "macos") and version in ("3.12", "3.13"), "wrong platform or Python"
    )
    _require(identity["job"] == _job_name(system, version), "wrong source job")
    _require(
        identity["runner_os"] == {"linux": "Linux", "macos": "macOS"}[system], "wrong runner OS"
    )
    _require(
        isinstance(identity["python_full"], str)
        and re.fullmatch(re.escape(version) + r"\.\d+", identity["python_full"]),
        "wrong full Python version",
    )
    _require(identity["pytest_version"] == "8.4.2", "wrong pytest version")
    for key in ("runner_arch", "runner_image", "runner_image_version"):
        _require(isinstance(identity[key], str) and bool(identity[key]), f"missing {key}")


def _validate_shard_report(
    report: Any, *, source: dict[str, Any], run_id: str, attempt: str, repository: str
) -> tuple[str, str, int, int]:
    _shape(
        report,
        {
            "schema_version",
            "identity",
            "partition",
            "collection",
            "collection_sha256",
            "selected",
            "execution_order",
            "outcomes",
            "errors",
            "warnings",
            "exit_code",
            "elapsed_seconds",
            "evidence",
            "source_after",
        },
        "suite report",
    )
    _require(report["schema_version"] == _SUITE_SCHEMA, "wrong suite schema")
    identity = report["identity"]
    _validate_suite_identity(
        identity, source=source, run_id=run_id, attempt=attempt, repository=repository
    )
    _require(report["source_after"] == source, "suite source drift")
    system, version = identity["platform"], identity["python_version"]
    partition = report["partition"]
    _shape(partition, {"index", "count"}, "partition")
    index, count = partition["index"], partition["count"]
    _require(type(index) is int and type(count) is int, "noninteger partition")
    coordinate = (system, version, index, count)
    _require(coordinate in _coordinates(), "invalid partition")
    full, selected = report["collection"], report["selected"]
    _strings(full, "collection")
    _strings(selected, "selected")
    _require(report["collection_sha256"] == _digest(full), "collection digest mismatch")
    _require(selected == full[index::count], "wrong ordered partition")
    _require(type(report["exit_code"]) is int and report["exit_code"] == 0, "pytest failed")
    _require(report["errors"] == [] and report["warnings"] == [], "suite errors or warnings")
    _number(report["elapsed_seconds"], "elapsed")
    _shape(report["evidence"], set(_SUITE_FILES), "raw evidence")
    for name, binding in report["evidence"].items():
        _shape(binding, {"bytes", "sha256"}, name)
        _require(type(binding["bytes"]) is int and binding["bytes"] >= 0, "invalid bytes")
        _require(
            isinstance(binding["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]),
            "invalid evidence hash",
        )
    _require(report["execution_order"] == selected, "wrong actual execution order")
    outcomes = report["outcomes"]
    _shape(outcomes, set(selected), "outcome node set")
    expected_skips = _expected_skips(system)
    _require(set(expected_skips) <= set(full), "governed skip node missing from collection")
    for node in selected:
        phases = outcomes[node]
        _require(isinstance(phases, list), "invalid phase list")
        expected_skip = expected_skips.get(node)
        expected_phases = (
            ["setup", "teardown"]
            if expected_skip and expected_skip[0] == "setup"
            else ["setup", "call", "teardown"]
        )
        _require(
            [phase.get("when") for phase in phases if isinstance(phase, dict)] == expected_phases,
            f"incomplete or duplicate phases: {node}",
        )
        for phase in phases:
            _shape(
                phase,
                {"when", "outcome", "duration", "diagnostic", "skip_reason", "xfail"},
                "test phase",
            )
            _number(phase["duration"], "phase")
            _require(isinstance(phase["diagnostic"], str), "invalid diagnostic")
            _require(phase["xfail"] is None, f"xfail/xpass is not qualification: {node}")
            if expected_skip and phase["when"] == expected_skip[0]:
                _require(
                    phase["outcome"] == "skipped" and phase["skip_reason"] == expected_skip[1],
                    f"wrong governed skip: {node}",
                )
            else:
                _require(
                    phase["outcome"] == "passed" and phase["skip_reason"] is None,
                    f"non-success or unexpected skip: {node}",
                )
    return coordinate


def _strict_json(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            _require(key not in result, f"duplicate JSON member: {key}")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise TerminalValidationError(f"nonfinite JSON number: {value}")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def _validate_suite_reports(
    root: Path, *, source: dict[str, Any], run_id: str, attempt: str, repository: str
) -> dict[str, Any]:
    _require(not root.is_symlink() and root.is_dir(), "unsafe reports root")
    expected = {
        _artifact_name(run_id, attempt, system, version, index): (system, version, index, count)
        for system, version, index, count in _coordinates()
    }
    _require({p.name for p in root.iterdir()} == set(expected), "incomplete artifact inventory")
    collection: list[str] | None = None
    environments: dict[tuple[str, str], list[str]] = {}
    coverage: dict[tuple[str, str], list[str]] = {}
    retained: dict[str, Any] = {}
    totals: dict[str, dict[str, int]] = {}
    for name, coordinate in expected.items():
        directory = root / name
        _require(not directory.is_symlink() and directory.is_dir(), "unsafe artifact directory")
        _require(
            {p.name for p in directory.iterdir()} == {"report.json", *_SUITE_FILES},
            "unexpected artifact member",
        )
        report = _strict_json(_safe_bytes(directory / "report.json"))
        actual = _validate_shard_report(
            report, source=source, run_id=run_id, attempt=attempt, repository=repository
        )
        _require(actual == coordinate, "artifact coordinate mismatch")
        for filename in _SUITE_FILES:
            _require(
                _file_identity(directory / filename) == report["evidence"][filename],
                f"raw evidence mismatch: {filename}",
            )
        if collection is None:
            collection = report["collection"]
        _require(report["collection"] == collection, "full collections disagree")
        key = coordinate[:2]
        observed_environment = [
            report["identity"][field]
            for field in (
                "python_full",
                "runner_os",
                "runner_arch",
                "runner_image",
                "runner_image_version",
            )
        ]
        if key not in environments:
            environments[key] = observed_environment
        _require(environments[key] == observed_environment, "shard environments disagree")
        coverage.setdefault(key, []).extend(report["selected"])
        group_totals = totals.setdefault(
            f"{key[0]}-py{key[1]}", {"passed": 0, "skipped": 0, "failed": 0, "total": 0}
        )
        for node in report["selected"]:
            # The complete phase validator already rejected errors, partial nodes,
            # and ungoverned skips. Count original outcomes once per actual test.
            outcomes = [phase["outcome"] for phase in report["outcomes"][node]]
            outcome = (
                "failed"
                if "failed" in outcomes
                else ("skipped" if "skipped" in outcomes else "passed")
            )
            group_totals[outcome] += 1
            group_totals["total"] += 1
        retained[name] = _file_identity(directory / "report.json")
    for selected in coverage.values():
        _require(
            len(selected) == len(set(selected)) and set(selected) == set(collection or []),
            "incomplete or overlapping suite coverage",
        )
    return {
        "schema_version": 1,
        "result": "success",
        "sha": source["commit"],
        "source": source,
        "totals": totals,
        "collection_sha256": _digest(collection),
        "collection_count": len(collection or []),
        "reports": retained,
    }


def _shard_plugin(index: int, count: int) -> Any:
    # Lazy import preserves the stdlib-only protected aggregate command.
    import pytest

    class ShardPlugin:
        def __init__(self) -> None:
            self.collected: list[str] = []
            self.collection: list[str] = []
            self.selected: list[str] = []
            self.execution_order: list[str] = []
            self.outcomes: dict[str, list[dict[str, Any]]] = {}
            self.errors: list[str] = []
            self.warnings: list[str] = []
            self.planned_deselection = False

        def pytest_itemcollected(self, item: Any) -> None:
            self.collected.append(item.nodeid)

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_collection_modifyitems(self, session: Any, config: Any, items: list[Any]) -> Any:
            yield
            # Pytest's own fixture ordering is part of canonical collection. Compare
            # membership before selecting from the final normally ordered stream.
            self.collection = [item.nodeid for item in items]
            if len(set(self.collected)) != len(self.collected) or sorted(self.collected) != sorted(
                self.collection
            ):
                self.errors.append("duplicate or filtered original collection")
            self.selected = self.collection[index::count]
            selected_items = items[index::count]
            deselected = [item for offset, item in enumerate(items) if offset % count != index]
            self.planned_deselection = True
            try:
                config.hook.pytest_deselected(items=deselected)
            finally:
                self.planned_deselection = False
            items[:] = selected_items

        def pytest_collection_finish(self, session: Any) -> None:
            if [item.nodeid for item in session.items] != self.selected:
                self.errors.append("post-partition collection changed")

        def pytest_deselected(self, items: list[Any]) -> None:
            if items and not self.planned_deselection:
                self.errors.append("unexpected deselection")

        def pytest_collectreport(self, report: Any) -> None:
            if report.failed or report.skipped:
                self.errors.append(
                    f"collection {report.outcome}: {report.nodeid}: {report.longrepr}"
                )

        def pytest_runtest_logstart(self, nodeid: str, location: Any) -> None:
            self.execution_order.append(nodeid)

        def pytest_runtest_logreport(self, report: Any) -> None:
            reason = None
            if report.skipped and isinstance(report.longrepr, tuple):
                reason = str(report.longrepr[2]).removeprefix("Skipped: ")
            self.outcomes.setdefault(report.nodeid, []).append(
                {
                    "when": report.when,
                    "outcome": report.outcome,
                    "duration": report.duration,
                    "diagnostic": str(report.longrepr) if report.longrepr else "",
                    "skip_reason": reason,
                    "xfail": getattr(report, "wasxfail", None),
                }
            )

        def pytest_warning_recorded(
            self, warning_message: Any, when: str, nodeid: str, location: Any
        ) -> None:
            self.warnings.append(f"{when}: {nodeid}: {warning_message.message}")

        def pytest_internalerror(self, excrepr: Any, excinfo: Any) -> None:
            self.errors.append(str(excrepr))

        def pytest_keyboard_interrupt(self, excinfo: Any) -> None:
            self.errors.append(str(excinfo))

    return ShardPlugin()


class _Tee:
    def __init__(self, retained: Any, original: Any) -> None:
        self.retained = retained
        self.original = original

    def write(self, value: str) -> int:
        self.retained.write(value)
        self.original.write(value)
        return len(value)

    def flush(self) -> None:
        self.retained.flush()
        self.original.flush()

    def isatty(self) -> bool:
        return False


def _run_pytest_shard(
    directory: Path,
    identity: dict[str, Any],
    index: int,
    count: int,
    *,
    pytest_args: list[str] | None = None,
) -> dict[str, Any]:
    import pytest

    plugin = _shard_plugin(index, count)
    started = time.monotonic()
    args = ["-q", "-p", "no:cacheprovider", "--color=no", f"--junitxml={directory / 'junit.xml'}"]
    if pytest_args is not None:  # Private fixture API; the public CLI has no selectors.
        args.extend(pytest_args)
    with (
        (directory / "stdout.txt").open("x", encoding="utf-8") as stdout,
        (directory / "stderr.txt").open("x", encoding="utf-8") as stderr,
        contextlib.redirect_stdout(_Tee(stdout, sys.stdout)),
        contextlib.redirect_stderr(_Tee(stderr, sys.stderr)),
    ):
        exit_code = int(pytest.main(args, plugins=[plugin]))
    return {
        "schema_version": _SUITE_SCHEMA,
        "identity": identity,
        "partition": {"index": index, "count": count},
        "collection": plugin.collection,
        "collection_sha256": _digest(plugin.collection),
        "selected": plugin.selected,
        "execution_order": plugin.execution_order,
        "outcomes": plugin.outcomes,
        "errors": plugin.errors,
        "warnings": plugin.warnings,
        "exit_code": exit_code,
        "elapsed_seconds": time.monotonic() - started,
        "evidence": {name: _file_identity(directory / name) for name in _SUITE_FILES},
        "source_after": identity["source"],
    }


def _host_context() -> dict[str, str]:
    context = {
        name: os.environ.get(name, "")
        for name in (
            "GITHUB_SHA",
            "GITHUB_WORKFLOW",
            "GITHUB_REPOSITORY",
            "GITHUB_RUN_ID",
            "GITHUB_RUN_ATTEMPT",
        )
    }
    _require(context["GITHUB_WORKFLOW"] == "CI", "not the CI workflow")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", context["GITHUB_SHA"])), "invalid hosted SHA")
    _require(context["GITHUB_REPOSITORY"] == "Miko997/metriplane", "wrong hosted repository")
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        _require(bool(re.fullmatch(r"[1-9][0-9]*", context[name])), f"invalid {name}")
    return context


def _shard_run(args: argparse.Namespace) -> dict[str, Any]:
    import pytest

    context = _host_context()
    _require(os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1", "plugin autoload enabled")
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "METRIPLANE_MP2_010_MATERIALIZATION_ROOT"):
        _require(not os.environ.get(name), f"unexpected test environment: {name}")
    _require(os.environ.get("METRIPLANE_TEST_PROFILE", "source") == "source", "wrong test profile")
    _require(
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").startswith("/"),
        "explicit browser cache required",
    )
    _require(
        (args.platform, args.python_version, args.shard_index, args.shard_count) in _coordinates(),
        "invalid hosted shard",
    )
    _require(
        platform.system() == {"linux": "Linux", "macos": "Darwin"}[args.platform],
        "wrong actual platform",
    )
    _require(
        f"{sys.version_info.major}.{sys.version_info.minor}" == args.python_version,
        "wrong actual Python",
    )
    root = Path.cwd()
    _require(
        Path(__file__).resolve() == (root / "tools/check_required_terminal.py").resolve(),
        "execution is outside the checked-out owner",
    )
    source = _source_identity(root)
    _require(source["commit"] == context["GITHUB_SHA"], "checked-out SHA differs from event")
    identity = {
        "source": source,
        "workflow": context["GITHUB_WORKFLOW"],
        "repository": context["GITHUB_REPOSITORY"],
        "run_id": context["GITHUB_RUN_ID"],
        "run_attempt": context["GITHUB_RUN_ATTEMPT"],
        "job": os.environ.get("GITHUB_JOB", ""),
        "platform": args.platform,
        "python_version": args.python_version,
        "python_full": platform.python_version(),
        "pytest_version": pytest.__version__,
        "runner_os": os.environ.get("RUNNER_OS", ""),
        "runner_arch": os.environ.get("RUNNER_ARCH", ""),
        "runner_image": os.environ.get("ImageOS", ""),
        "runner_image_version": os.environ.get("ImageVersion", ""),
    }
    _validate_suite_identity(
        identity,
        source=source,
        run_id=context["GITHUB_RUN_ID"],
        attempt=context["GITHUB_RUN_ATTEMPT"],
        repository=context["GITHUB_REPOSITORY"],
    )
    _require(
        args.report_dir.is_absolute() and ".." not in args.report_dir.parts,
        "report destination must be a canonical absolute path",
    )
    directory = args.report_dir
    _require(
        not directory.is_relative_to(root.resolve()), "report directory must be outside source"
    )
    _require(
        all(not parent.is_symlink() for parent in (directory, *directory.parents)),
        "symlink report destination",
    )
    directory.mkdir(exist_ok=False)
    report = _run_pytest_shard(directory, identity, args.shard_index, args.shard_count)
    try:
        report["source_after"] = _source_identity(root)
    except (OSError, subprocess.CalledProcessError, TerminalValidationError) as exc:
        report["source_after"] = None
        report["errors"].append(f"source readback failed: {exc}")
    with (directory / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    _validate_shard_report(
        report,
        source=source,
        run_id=context["GITHUB_RUN_ID"],
        attempt=context["GITHUB_RUN_ATTEMPT"],
        repository=context["GITHUB_REPOSITORY"],
    )
    return {
        "result": "success",
        "report": str(directory / "report.json"),
        "selected": len(report["selected"]),
        "sha": source["commit"],
    }


def _shard_aggregate(args: argparse.Namespace) -> dict[str, Any]:
    context = _host_context()
    _require(
        (args.expected_sha, args.expected_run_id, args.expected_run_attempt)
        == (context["GITHUB_SHA"], context["GITHUB_RUN_ID"], context["GITHUB_RUN_ATTEMPT"]),
        "aggregate arguments differ from hosted identity",
    )
    _require(
        Path(__file__).resolve() == (Path.cwd() / "tools/check_required_terminal.py").resolve(),
        "execution is outside the checked-out owner",
    )
    source = _source_identity(Path.cwd())
    _require(source["commit"] == args.expected_sha, "aggregate checkout differs from expected SHA")
    result = _validate_suite_reports(
        args.reports_root,
        source=source,
        run_id=args.expected_run_id,
        attempt=args.expected_run_attempt,
        repository=context["GITHUB_REPOSITORY"],
    )
    _require(_source_identity(Path.cwd()) == source, "aggregate source drift")
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--terminal", required=True)
    aggregate.add_argument("--expected-sha", required=True)
    aggregate.add_argument("--expected-dependency", action="append", default=[])
    aggregate.add_argument("--results-json", required=True)

    policy = subparsers.add_parser("policy")
    policy.add_argument("--policy", type=Path, required=True)
    policy.add_argument("--workflow-root", type=Path, required=True)
    shard = subparsers.add_parser("shard-run")
    shard.add_argument("--platform", choices=("linux", "macos"), required=True)
    shard.add_argument("--python-version", choices=("3.12", "3.13"), required=True)
    shard.add_argument("--shard-index", type=int, required=True)
    shard.add_argument("--shard-count", type=int, choices=(1, 4), required=True)
    shard.add_argument("--report-dir", type=Path, required=True)

    suite = subparsers.add_parser("shard-aggregate")
    suite.add_argument("--reports-root", type=Path, required=True)
    suite.add_argument("--expected-sha", required=True)
    suite.add_argument("--expected-run-id", required=True)
    suite.add_argument("--expected-run-attempt", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        if args.command == "aggregate":
            result = validate_terminal(
                terminal=args.terminal,
                expected_sha=args.expected_sha,
                expected_dependencies=args.expected_dependency,
                results=json.loads(args.results_json),
            )
        elif args.command == "policy":
            result = validate_policy(args.policy, args.workflow_root)
        elif args.command == "shard-run":
            result = _shard_run(args)
        else:
            result = _shard_aggregate(args)
    except (KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"required terminal validation failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
