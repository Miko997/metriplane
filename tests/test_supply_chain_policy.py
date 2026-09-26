# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools.check_supply_chain_policy import SupplyChainPolicyError, validate_policy


ROOT = Path(__file__).resolve().parents[1]


def test_committed_supply_chain_policy_is_current() -> None:
    policy = validate_policy(ROOT)
    schema = json.loads(
        (ROOT / "schemas/metriplane.supply-chain-policy.v1.schema.json").read_text(encoding="utf-8")
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == policy["schema_version"]
    assert set(schema["required"]) == set(policy)


def _copy_repository(tmp_path: Path) -> Path:
    for name in (
        ".clusterfuzzlite",
        ".github",
        "LICENSES",
        "adapters",
        "docker",
        "examples",
        "tests",
    ):
        shutil.copytree(ROOT / name, tmp_path / name)
    for name in ("LICENSE", "NOTICE", "pyproject.toml", "uv.lock", "supply-chain-policy.json"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    return tmp_path


def test_missing_project_lock_fails_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    (root / "adapters/maniskill_pickcube/uv.lock").unlink()
    with pytest.raises(SupplyChainPolicyError, match="missing lock"):
        validate_policy(root)


def test_unknown_project_lock_fails_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    extra = root / "unknown"
    extra.mkdir()
    (extra / "pyproject.toml").write_text(
        "[project]\nname='unknown'\nversion='1'\n", encoding="utf-8"
    )
    (extra / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match="lock inventory drift"):
        validate_policy(root)


def test_ignored_virtual_environment_lock_is_not_repository_policy(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    installed = root / "adapters/maniskill_pickcube/.venv/site-packages/package/data"
    installed.mkdir(parents=True)
    (installed / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    validate_policy(root)


def test_unpinned_action_and_persisted_credentials_fail_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    workflow = root / ".github/workflows/supply-chain-security.yml"
    original = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        original.replace(
            "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803", "actions/checkout@v6", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(SupplyChainPolicyError, match="unpinned action"):
        validate_policy(root)
    workflow.write_text(
        original.replace("persist-credentials: false", "persist-credentials: true", 1),
        encoding="utf-8",
    )
    with pytest.raises(SupplyChainPolicyError, match="checkout credentials persist"):
        validate_policy(root)


def test_yaml_workflow_cannot_bypass_action_policy(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    (root / ".github/workflows/untrusted.yaml").write_text(
        """name: Untrusted
on: push
permissions:
  contents: read
jobs:
  bypass:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
""",
        encoding="utf-8",
    )
    with pytest.raises(SupplyChainPolicyError, match="unpinned action"):
        validate_policy(root)


def test_unexpected_workflow_document_form_fails_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    (root / ".github/workflows/ignored.txt").write_text("not a workflow\n", encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match="unexpected workflow document form"):
        validate_policy(root)


def test_missing_required_control_fails_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    policy_path = root / "supply-chain-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["required_controls"].remove("secret-scan")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match="controls"):
        validate_policy(root)


def test_write_permission_and_unpinned_job_call_fail_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    docker = root / ".github/workflows/docker-smoke.yml"
    original = docker.read_text(encoding="utf-8")
    docker.write_text(original.replace("contents: read", "contents: write", 1), encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match="workflow-level write permission"):
        validate_policy(root)

    docker.write_text(original, encoding="utf-8")
    codeql = root / ".github/workflows/codeql.yml"
    codeql.write_text(
        codeql.read_text(encoding="utf-8").replace(
            "uses: ./.github/workflows/supply-chain-security.yml",
            "uses: example/untrusted/.github/workflows/scan.yml@v1",
        ),
        encoding="utf-8",
    )
    with pytest.raises(SupplyChainPolicyError, match="unpinned job action"):
        validate_policy(root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        ("exit-code: '1'", "exit-code: '0'", "Trivy fail-closed inputs"),
        (
            "needs: [policy, dependency-review, osv, pip-audit, image-scan, secret-scan, sbom]",
            "needs: [policy, dependency-review, osv, pip-audit, image-scan, secret-scan]",
            "supply-chain aggregate: dependency drift",
        ),
        (
            "uses: aquasecurity/trivy-action@",
            "continue-on-error: true\n        uses: aquasecurity/trivy-action@",
            "step allows failure",
        ),
        (
            "uses: google/osv-scanner-action/osv-scanner-action@",
            "if: false\n        uses: google/osv-scanner-action/osv-scanner-action@",
            "scanner is conditional",
        ),
    ),
)
def test_scanner_and_aggregate_mutations_fail_closed(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    root = _copy_repository(tmp_path)
    workflow = root / ".github/workflows/supply-chain-security.yml"
    text = workflow.read_text(encoding="utf-8")
    assert old in text
    workflow.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match=message):
        validate_policy(root)


@pytest.mark.parametrize(
    ("workflow_name", "old", "new", "message"),
    (
        (
            "supply-chain-security.yml",
            '"osv":{"result":"${{ needs.osv.result }}"',
            '"osv":{"result":"success"',
            "supply-chain aggregate: result binding drift: osv",
        ),
        (
            "codeql.yml",
            '"supply-chain":{"result":"${{ needs.supply-chain.result }}"',
            '"supply-chain":{"result":"${{ needs.analyze-javascript.result }}"',
            "security aggregate: result binding drift: supply-chain",
        ),
    ),
)
def test_aggregate_result_expressions_fail_closed(
    tmp_path: Path, workflow_name: str, old: str, new: str, message: str
) -> None:
    root = _copy_repository(tmp_path)
    workflow = root / ".github/workflows" / workflow_name
    text = workflow.read_text(encoding="utf-8")
    assert old in text
    workflow.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match=message):
        validate_policy(root)


def test_aggregate_validator_argv_fails_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    workflow = root / ".github/workflows/supply-chain-security.yml"
    text = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        text.replace('--terminal "Supply-chain aggregate"', '--terminal "Different aggregate"', 1),
        encoding="utf-8",
    )
    with pytest.raises(
        SupplyChainPolicyError, match="supply-chain aggregate: validator argv drift"
    ):
        validate_policy(root)


def test_dependency_review_command_drift_fails_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    workflow = root / ".github/workflows/supply-chain-security.yml"
    text = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        text.replace('--head "$GITHUB_SHA"', '--head "${{ github.sha }}"', 1),
        encoding="utf-8",
    )
    with pytest.raises(SupplyChainPolicyError, match="dependency review command drift"):
        validate_policy(root)


def test_dependency_license_command_and_export_drift_fail_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    workflow = root / ".github/workflows/supply-chain-security.yml"
    original = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        original.replace("--deny-license AGPL-3.0", "--deny-license LGPL-3.0", 1),
        encoding="utf-8",
    )
    with pytest.raises(SupplyChainPolicyError, match="dependency license command drift"):
        validate_policy(root)
    workflow.write_text(
        original.replace("output=.supply-chain-license", "output=.untrusted", 1),
        encoding="utf-8",
    )
    with pytest.raises(SupplyChainPolicyError, match="dependency license export drift"):
        validate_policy(root)


def test_osv_runtime_export_directory_drift_fails_closed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    policy_path = root / "supply-chain-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["osv_runtime_export_directory"] = ".untrusted"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match="OSV runtime export directory drift"):
        validate_policy(root)


def test_runtime_extra_coverage_cannot_be_removed(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    workflow = root / ".github/workflows/supply-chain-security.yml"
    text = workflow.read_text(encoding="utf-8")
    assert text.count("--all-extras") == 4
    workflow.write_text(text.replace("--all-extras ", "", 1), encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match="dependency license export drift"):
        validate_policy(root)


@pytest.mark.parametrize(
    ("workflow_name", "old", "new", "message"),
    (
        (
            "supply-chain-security.yml",
            "          persist-credentials: false\n",
            "          persist-credentials: false\n          ref: main\n",
            "policy: checkout input drift",
        ),
        (
            "supply-chain-security.yml",
            'source_sha="$(git rev-parse HEAD)"',
            'source_sha="$GITHUB_SHA"',
            "policy: source step drift",
        ),
        (
            "codeql.yml",
            "          persist-credentials: false\n",
            "          persist-credentials: false\n          ref: main\n",
            "codeql analyze-python: checkout input drift",
        ),
        (
            "codeql.yml",
            'source_sha="$(git rev-parse HEAD)"',
            'source_sha="$GITHUB_SHA"',
            "codeql analyze-python: source step drift",
        ),
    ),
)
def test_source_identity_mutations_fail_closed(
    tmp_path: Path, workflow_name: str, old: str, new: str, message: str
) -> None:
    root = _copy_repository(tmp_path)
    workflow = root / ".github/workflows" / workflow_name
    text = workflow.read_text(encoding="utf-8")
    assert old in text
    workflow.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match=message):
        validate_policy(root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        (
            "            ./.supply-chain-osv\n",
            "            /tmp\n",
            "OSV scan target",
        ),
        (
            '--output-file "$RUNNER_TEMP/requirements.txt"',
            "--output-file /tmp/empty-requirements.txt",
            "pip-audit export command drift",
        ),
        (
            "          inputs: ${{ runner.temp }}/requirements.txt",
            "          inputs: /tmp/empty-requirements.txt",
            "pip-audit fail-closed inputs",
        ),
        (
            '          --file "${{ matrix.dockerfile }}" .',
            '          --file "${{ matrix.dockerfile }}" /tmp',
            "runtime image build command drift",
        ),
        (
            "          image-ref: metriplane-supply-chain-${{ matrix.image }}:${{ github.sha }}",
            "          image-ref: alpine:latest",
            "Trivy fail-closed inputs",
        ),
        (
            "          path: ./\n          extra_args: --results=verified,unknown",
            "          path: /tmp\n          extra_args: --results=verified,unknown",
            "secret scanner inputs",
        ),
        (
            "          path: .\n          format: spdx-json",
            "          path: /tmp\n          format: spdx-json",
            "SBOM retention inputs",
        ),
    ),
)
def test_scanner_target_substitutions_fail_closed(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    root = _copy_repository(tmp_path)
    workflow = root / ".github/workflows/supply-chain-security.yml"
    text = workflow.read_text(encoding="utf-8")
    assert old in text
    workflow.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match=message):
        validate_policy(root)


def test_runtime_image_inventory_is_exact_and_classified(tmp_path: Path) -> None:
    root = _copy_repository(tmp_path)
    (root / "unclassified.Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    with pytest.raises(SupplyChainPolicyError, match="image inventory drift"):
        validate_policy(root)
