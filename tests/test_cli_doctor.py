# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from types import SimpleNamespace

import pytest

from metriplane import cli


@pytest.mark.parametrize(
    ("version", "expected_status"),
    [
        ((3, 11, 9), "FAIL"),
        ((3, 12, 0), "PASS"),
        ((3, 13, 7), "PASS"),
        ((3, 14, 0), "FAIL"),
        ((4, 0, 0), "FAIL"),
    ],
)
def test_doctor_enforces_the_declared_python_range(
    monkeypatch: pytest.MonkeyPatch,
    version: tuple[int, int, int],
    expected_status: str,
) -> None:
    monkeypatch.setattr(
        cli.sys,
        "version_info",
        SimpleNamespace(major=version[0], minor=version[1], micro=version[2]),
    )

    status, message = cli._check_python_version()

    assert status == expected_status
    assert f"{version[0]}.{version[1]}.{version[2]}" in message
    if expected_status == "FAIL":
        assert "Python 3.12 or 3.13" in message


def test_doctor_source_checkout_helpers_are_always_optional(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_package_source_root", lambda: tmp_path)

    assert cli._check_vt_sh_exists() == (
        "WARN",
        "tools/mp.sh not found (source-checkout helper, optional)",
    )
    assert cli._check_config_exists() == (
        "WARN",
        "configs/fusion_health_300fps.yaml not found "
        "(source-checkout live-camera example, optional)",
    )


def test_doctor_git_commit_is_warning_outside_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_package_source_root", lambda: tmp_path)

    status, message = cli._check_git_commit()

    assert status == "WARN"
    assert message == "Git commit not available for the source checkout"


def test_doctor_required_dependency_failure_is_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = cli.importlib.import_module

    def missing_pydantic(name: str):
        if name == "pydantic":
            raise ModuleNotFoundError("pydantic")
        return real_import(name)

    monkeypatch.setattr(cli.importlib, "import_module", missing_pydantic)

    status, message = cli._check_required_dependencies()

    assert status == "FAIL"
    assert "pydantic (ModuleNotFoundError)" in message


def test_doctor_checks_every_bundled_demo_resource() -> None:
    assert cli._check_demo_resources() == (
        "PASS",
        "Bundled demo resources available (6 files)",
    )


def test_doctor_reports_a_missing_bundled_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import metriplane.demo as demo

    monkeypatch.setattr(demo, "BUNDLED_DEMO_RESOURCES", ("assets/missing.jsonl",))

    status, message = cli._check_demo_resources()

    assert status == "FAIL"
    assert message == "Bundled demo resources missing: assets/missing.jsonl"


def test_doctor_distinguishes_editable_and_installed_packages(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib import metadata

    class Distribution:
        def __init__(self, direct_url: str | None) -> None:
            self.direct_url = direct_url

        def read_text(self, filename: str) -> str | None:
            assert filename == "direct_url.json"
            return self.direct_url

    source_root = tmp_path / "source"
    (source_root / "metriplane").mkdir(parents=True)
    (source_root / "metriplane" / "cli.py").write_text("# source marker\n")
    (source_root / "pyproject.toml").write_text(
        '[project]\nname = "metriplane"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_package_source_root", lambda: source_root)
    monkeypatch.setattr(
        metadata,
        "distribution",
        lambda _name: Distribution('{"dir_info": {"editable": true}}'),
    )
    assert cli._installation_context() == "editable source checkout"

    monkeypatch.setattr(metadata, "distribution", lambda _name: Distribution(None))
    assert cli._installation_context() == "source checkout"

    installed_root = tmp_path / "site-packages"
    installed_root.mkdir()
    monkeypatch.setattr(cli, "_package_source_root", lambda: installed_root)
    assert cli._installation_context() == "installed distribution"


def _stub_doctor_checks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    required_status: str = "PASS",
    optional_status: str = "WARN",
) -> None:
    required = (
        "_check_python_version",
        "_check_import_metriplane",
        "_check_required_dependencies",
        "_check_demo_resources",
    )
    optional = (
        "_check_git_commit",
        "_check_vt_sh_exists",
        "_check_config_exists",
        "_check_ports_available",
        "_check_video_devices",
        "_check_nvidia_smi",
    )
    for name in required:
        monkeypatch.setattr(cli, name, lambda name=name: (required_status, name))
    for name in optional:
        monkeypatch.setattr(cli, name, lambda name=name: (optional_status, name))


def test_doctor_optional_capabilities_do_not_block_the_demo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_doctor_checks(monkeypatch)
    monkeypatch.setattr(cli, "_installation_context", lambda: "installed distribution")

    assert cli._main_doctor([]) == 0

    output = capsys.readouterr().out
    assert "Installation:" in output
    assert "Required for the bundled camera-free demo:" in output
    assert "Summary: 4 passed, 0 warnings, 0 failed" in output
    assert "Optional: 0 available, 4 unavailable or not configured" in output
    assert "Source-checkout development checks skipped" in output
    assert "Ready for the bundled camera-free demo." in output
    assert "Not ready" not in output


def test_doctor_required_failure_is_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_doctor_checks(monkeypatch, required_status="FAIL")
    monkeypatch.setattr(cli, "_installation_context", lambda: "installed distribution")

    assert cli._main_doctor([]) == 1

    output = capsys.readouterr().out
    assert "Summary: 0 passed, 0 warnings, 4 failed" in output
    assert "Not ready for the bundled camera-free demo." in output


def test_doctor_in_use_ports_are_optional(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_doctor_checks(monkeypatch, optional_status="PASS")
    monkeypatch.setattr(cli, "_installation_context", lambda: "installed distribution")
    monkeypatch.setattr(
        cli,
        "_check_ports_available",
        lambda: ("WARN", "Ports 8000 in use"),
    )

    assert cli._main_doctor([]) == 0

    output = capsys.readouterr().out
    assert "○ OPTIONAL: Ports 8000 in use" in output
    assert "Ready for the bundled camera-free demo." in output


def test_installed_doctor_never_reads_an_unrelated_git_checkout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_doctor_checks(monkeypatch, optional_status="PASS")
    monkeypatch.setattr(cli, "_installation_context", lambda: "installed distribution")

    def unexpected_git_check() -> tuple[str, str]:
        raise AssertionError("installed-package doctor must not inspect the current Git checkout")

    monkeypatch.setattr(cli, "_check_git_commit", unexpected_git_check)

    assert cli._main_doctor([]) == 0
    assert "Git commit" not in capsys.readouterr().out
