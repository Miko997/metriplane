# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ctypes
import errno
import hashlib
import io
import json
import os
import resource
import subprocess
import sys
import tarfile
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

import metriplane.external_sources.sandbox as sandbox_module
from metriplane.external_sources.cli import main as external_main
from metriplane.external_sources.execution import normalize_external_fixture
from metriplane.external_sources.sandbox import (
    AcquisitionIdentity,
    AdapterSandboxError,
    SandboxLimits,
    SandboxResult,
    _archive_byte_limit,
    _bounded_communicate,
    _create_output_archive,
    _create_seccomp_fd,
    _extract_bounded_output_archive,
    _limit_child,
    _open_verified_acquisition,
    _open_trusted_regular,
    credential_empty_environment,
    load_acquisition_allowlist,
    require_allowlisted_acquisition,
    run_normalization_sandbox,
    verify_allowlisted_acquisition,
)


SOURCE = AcquisitionIdentity("dataset", "a" * 40, "fixture.zip", 10, "b" * 64)


def _trusted_bwrap_available() -> bool:
    try:
        fd = _open_trusted_regular(Path("/usr/bin/bwrap"))
    except (AdapterSandboxError, OSError):
        return False
    os.close(fd)
    return True


TRUSTED_BWRAP_AVAILABLE = _trusted_bwrap_available()


def test_acquisition_allowlist_requires_one_exact_identity() -> None:
    require_allowlisted_acquisition(SOURCE, (SOURCE,))
    for changed in (
        AcquisitionIdentity("other", SOURCE.revision, SOURCE.artifact, SOURCE.size, SOURCE.sha256),
        AcquisitionIdentity(
            SOURCE.repository, "c" * 40, SOURCE.artifact, SOURCE.size, SOURCE.sha256
        ),
        AcquisitionIdentity(
            SOURCE.repository, SOURCE.revision, "other.zip", SOURCE.size, SOURCE.sha256
        ),
        AcquisitionIdentity(SOURCE.repository, SOURCE.revision, SOURCE.artifact, 11, SOURCE.sha256),
        AcquisitionIdentity(
            SOURCE.repository, SOURCE.revision, SOURCE.artifact, SOURCE.size, "d" * 64
        ),
    ):
        with pytest.raises(AdapterSandboxError, match="not exactly allowlisted"):
            require_allowlisted_acquisition(changed, (SOURCE,))
    with pytest.raises(AdapterSandboxError, match="not exactly allowlisted"):
        require_allowlisted_acquisition(SOURCE, (SOURCE, SOURCE))


def test_allowlist_schema_and_exact_artifact_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    artifact = source / "fixture.zip"
    artifact.write_bytes(b"0123456789")
    identity = AcquisitionIdentity(
        "dataset",
        "a" * 40,
        artifact.name,
        artifact.stat().st_size,
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(json.dumps([identity.__dict__]), encoding="utf-8")
    allowlist = load_acquisition_allowlist(allowlist_path)
    verify_allowlisted_acquisition(identity, allowlist, source)

    artifact.write_bytes(b"tampered!!")
    with pytest.raises(AdapterSandboxError, match="digest differs"):
        verify_allowlisted_acquisition(identity, allowlist, source)
    artifact.unlink()
    artifact.symlink_to("/etc/passwd")
    with pytest.raises(AdapterSandboxError, match="cannot be verified"):
        verify_allowlisted_acquisition(identity, allowlist, source)
    traversal = AcquisitionIdentity("dataset", "a" * 40, "../fixture.zip", 0, "0" * 64)
    with pytest.raises(AdapterSandboxError, match="safe relative"):
        verify_allowlisted_acquisition(traversal, (traversal,), source)


def test_offline_credential_empty_unprivileged_quota_environment() -> None:
    assert credential_empty_environment() == {
        "HOME": "/tmp/empty-home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "TZ": "UTC",
    }
    with pytest.raises(TypeError):
        credential_empty_environment({"ADAPTER_MODE": "normalize"})  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="positive and finite"):
        SandboxLimits(max_processes=0)


def test_trusted_runtime_rejects_symlink_or_unsafe_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "bwrap"
    executable.write_text("x", encoding="utf-8")
    executable.chmod(0o755)
    link = tmp_path / "link"
    link.symlink_to(executable)
    with pytest.raises(AdapterSandboxError, match="must not be a symlink"):
        _open_trusted_regular(link)
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox.os.fstat",
        lambda _: os.stat_result((0o100755, 0, 0, 1, 1000, 1000, 0, 0, 0, 0)),
    )
    with pytest.raises(AdapterSandboxError, match="ownership or mode is unsafe"):
        _open_trusted_regular(executable)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux seccomp architecture is unavailable")
def test_seccomp_filter_is_finite_and_readable() -> None:
    fd = _create_seccomp_fd()
    try:
        payload = os.read(fd, 4096)
    finally:
        os.close(fd)
    assert payload
    assert len(payload) % 8 == 0
    assert len(payload) <= 256


class _FakeProcess:
    def __init__(self, command: list[str], **kwargs: Any) -> None:
        self.command = command
        self.returncode: int | None = 0
        self.pid = 12345
        self.stdout = object()
        self.stderr = object()
        self.waited = False
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"] == {}
        assert kwargs["start_new_session"] is True
        assert kwargs["pass_fds"]
        assert kwargs["executable"] == command[0]
        if sys.platform == "linux":
            assert kwargs["executable"].startswith("/proc/self/fd/")

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.waited = True
        if self.returncode is None:
            self.returncode = -9
        return self.returncode


def _fake_trusted_open(_: Path, **__: Any) -> int:
    return os.open("/dev/null", os.O_RDONLY)


def _portable_unlinked_archive_fd(tmp_path: Path) -> int:
    path = tmp_path / f"archive-{uuid.uuid4().hex}.tar"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    path.unlink()
    return fd


@pytest.fixture(autouse=True)
def _portable_non_linux_unit_fds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if sys.platform == "linux":
        return
    real_fcntl = sandbox_module.fcntl.fcntl

    def portable_fd_path(fd: int) -> str:
        raw_path = real_fcntl(fd, sandbox_module.fcntl.F_GETPATH, b"\0" * 1024)
        assert isinstance(raw_path, bytes)
        return os.fsdecode(raw_path.split(b"\0", 1)[0])

    def portable_fcntl(fd: int, command: int, argument: int = 0) -> int:
        if command == sandbox_module._F_ADD_SEALS:
            return 0
        if command == sandbox_module._F_GET_SEALS:
            return sandbox_module._REQUIRED_SEALS
        return int(real_fcntl(fd, command, argument))

    def portable_rename_noreplace(parent_fd: int, source: str, destination: str) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            raise AdapterSandboxError("atomic no-replace publication is unavailable")
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        if (
            renameatx_np(
                parent_fd,
                os.fsencode(source),
                parent_fd,
                os.fsencode(destination),
                0x00000004,  # Darwin RENAME_EXCL
            )
            != 0
        ):
            error = ctypes.get_errno()
            if error == errno.EEXIST:
                raise AdapterSandboxError("adapter output appeared before atomic publication")
            raise AdapterSandboxError(f"atomic adapter publication failed: {os.strerror(error)}")

    monkeypatch.setattr(sandbox_module, "_fd_path", portable_fd_path)
    monkeypatch.setattr(
        sandbox_module,
        "_create_memfd",
        lambda _name, *, allow_sealing=False: _portable_unlinked_archive_fd(tmp_path),
    )
    monkeypatch.setattr(
        sandbox_module,
        "_create_output_archive",
        lambda: _portable_unlinked_archive_fd(tmp_path),
    )
    monkeypatch.setattr(sandbox_module, "_rename_noreplace", portable_rename_noreplace)
    monkeypatch.setattr(sandbox_module.fcntl, "fcntl", portable_fcntl)


def _write_test_archive(fd: int, entries: dict[str, bytes]) -> None:
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(fd), "wb") as destination:
        with tarfile.open(fileobj=destination, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, payload in entries.items():
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                member.mode = 0o600
                archive.addfile(member, io.BytesIO(payload))


def _fake_communicate(entries: dict[str, bytes]) -> Any:
    def communicate(process: Any, limits: SandboxLimits, archive_fd: int) -> tuple[bytes, bytes]:
        del process, limits
        _write_test_archive(archive_fd, entries)
        return b"", b""

    return communicate


def test_memory_limit_is_finite_and_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(resource, "setrlimit", lambda kind, value: observed.append((kind, value)))
    limits = SandboxLimits(max_memory_bytes=128 * 1024 * 1024)
    _limit_child(limits)
    assert (resource.RLIMIT_AS, (limits.max_memory_bytes, limits.max_memory_bytes)) in observed
    with pytest.raises(ValueError, match="positive and finite"):
        SandboxLimits(max_memory_bytes=0)


def test_stdout_archive_spool_accepts_exact_boundary_and_rejects_n_plus_one() -> None:
    limits = SandboxLimits(
        timeout_seconds=5,
        max_output_files=1,
        max_output_tree_bytes=512,
    )
    byte_limit = _archive_byte_limit(limits)
    for size, should_pass in ((byte_limit, True), (byte_limit + 1, False)):
        archive_fd = _create_output_archive()
        script = (
            "import sys,time;"
            f"sys.stdout.buffer.write(b'x'*{size});"
            "sys.stdout.buffer.flush();" + ("" if should_pass else "time.sleep(30)")
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            if should_pass:
                stdout, stderr = _bounded_communicate(process, limits, archive_fd)
                assert stdout == stderr == b""
                assert process.returncode == 0
                assert os.fstat(archive_fd).st_size == byte_limit
            else:
                with pytest.raises(AdapterSandboxError, match="archive quota exceeded"):
                    _bounded_communicate(process, limits, archive_fd)
                assert process.poll() is not None
                assert os.fstat(archive_fd).st_size <= byte_limit
                assert os.fstat(archive_fd).st_size != size
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            assert process.stdout is not None and process.stdout.closed
            assert process.stderr is not None and process.stderr.closed
            os.close(archive_fd)


def test_verified_artifact_descriptor_survives_path_substitution(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    artifact = source / "artifact.bin"
    approved = b"approved artifact bytes"
    artifact.write_bytes(approved)
    identity = AcquisitionIdentity(
        "repo",
        "revision",
        artifact.name,
        len(approved),
        hashlib.sha256(approved).hexdigest(),
    )
    with _open_verified_acquisition(identity, (identity,), source) as verified:
        artifact.write_bytes(b"in-place mutation bytes")
        assert os.pread(verified.artifact_fd, len(approved), 0) == approved
        replacement = source / "replacement.bin"
        replacement.write_bytes(b"substituted artifact")
        replacement.replace(artifact)
        assert artifact.read_bytes() != approved
        assert os.pread(verified.artifact_fd, len(approved), 0) == approved


def test_staged_canonical_validation_precedes_atomic_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "linux":
        with pytest.raises(AssertionError):
            _FakeProcess(
                ["/usr/bin/bwrap"],
                executable="/usr/bin/bwrap",
                stdin=subprocess.DEVNULL,
                env={},
                start_new_session=True,
                pass_fds=(1,),
            )
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    output = tmp_path / "published"
    observed: dict[str, Any] = {}
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._open_trusted_regular", _fake_trusted_open
    )
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._create_seccomp_fd",
        lambda: os.open("/dev/null", os.O_RDONLY),
    )
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._create_output_archive",
        lambda: _portable_unlinked_archive_fd(tmp_path),
    )
    monkeypatch.setattr("metriplane.external_sources.sandbox.os.geteuid", lambda: 1000)

    def fake_popen(command: list[str], **kwargs: Any) -> _FakeProcess:
        process = _FakeProcess(command, **kwargs)
        observed["process"] = process
        return process

    monkeypatch.setattr("metriplane.external_sources.sandbox.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._bounded_communicate",
        _fake_communicate({"canonical.json": b"{}\n"}),
    )

    def validate(stage: Path) -> None:
        assert not output.exists()
        assert (stage / "canonical.json").read_text(encoding="utf-8") == "{}\n"

    result = run_normalization_sandbox(
        ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
        fixture_root=fixture,
        output_root=output,
        validate_output=validate,
    )
    command = observed["process"].command
    assert "--unshare-net" in command
    assert "--unshare-pid" in command
    assert "--clearenv" in command
    assert result.returncode == 0
    assert (output / "canonical.json").is_file()


def test_path_escape_and_target_creation_race_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    output = tmp_path / "published"
    for command in (
        ["../python", "/input/normalize.py"],
        ["/usr/bin/python3", "/input/../normalize.py"],
        ["/usr/bin/python3", "/output/normalize.py"],
    ):
        with pytest.raises(AdapterSandboxError, match="trusted Python|traversal|below /input"):
            run_normalization_sandbox(
                command,
                fixture_root=fixture,
                output_root=output,
                validate_output=lambda _: None,
            )

    with pytest.raises(AdapterSandboxError, match="input and output must be disjoint"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=fixture / "published",
            validate_output=lambda _: None,
        )

    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._open_trusted_regular", _fake_trusted_open
    )
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._create_seccomp_fd",
        lambda: os.open("/dev/null", os.O_RDONLY),
    )
    monkeypatch.setattr("metriplane.external_sources.sandbox.os.geteuid", lambda: 1000)

    def fake_popen(command: list[str], **kwargs: Any) -> _FakeProcess:
        return _FakeProcess(command, **kwargs)

    monkeypatch.setattr("metriplane.external_sources.sandbox.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._bounded_communicate",
        _fake_communicate({"canonical.json": b"{}\n"}),
    )

    def racing_validator(_: Path) -> None:
        output.mkdir()

    with pytest.raises(AdapterSandboxError, match="appeared before atomic publication"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=racing_validator,
        )

    output.rmdir()
    displaced = tmp_path / "displaced-stage"

    def stage_substitution_validator(stage: Path) -> None:
        stage_path = stage.resolve(strict=True)
        stage_path.rename(displaced)
        stage_path.mkdir()

    with pytest.raises(AdapterSandboxError, match="staging directory identity changed"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=stage_substitution_validator,
        )
    (displaced / "canonical.json").unlink()
    displaced.rmdir()


def test_root_preopen_and_output_prepublication_substitution_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    output_parent = tmp_path / "output-parent"
    output_parent.mkdir()
    output = output_parent / "published"
    displaced_fixture = tmp_path / "displaced-fixture"
    displaced_parent = tmp_path / "displaced-parent"
    real_open_directory = sandbox_module._open_directory

    def substitute_fixture_after_open(path: Path, *, label: str) -> int:
        fd = real_open_directory(path, label=label)
        if label == "adapter fixture root":
            fixture.rename(displaced_fixture)
            fixture.mkdir()
        return fd

    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._open_directory", substitute_fixture_after_open
    )
    with pytest.raises(AdapterSandboxError, match="fixture root identity changed"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=lambda _: None,
        )
    fixture.rmdir()
    displaced_fixture.rename(fixture)

    def substitute_parent_after_open(path: Path, *, label: str) -> int:
        fd = real_open_directory(path, label=label)
        if label == "adapter output parent":
            output_parent.rename(displaced_parent)
            output_parent.mkdir()
        return fd

    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._open_directory", substitute_parent_after_open
    )
    with pytest.raises(AdapterSandboxError, match="output parent identity changed"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=lambda _: None,
        )
    output_parent.rmdir()
    displaced_parent.rename(output_parent)

    monkeypatch.setattr("metriplane.external_sources.sandbox._open_directory", real_open_directory)
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._open_trusted_regular", _fake_trusted_open
    )
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._create_seccomp_fd",
        lambda: os.open("/dev/null", os.O_RDONLY),
    )
    monkeypatch.setattr("metriplane.external_sources.sandbox.os.geteuid", lambda: 1000)

    def fake_popen(command: list[str], **kwargs: Any) -> _FakeProcess:
        return _FakeProcess(command, **kwargs)

    monkeypatch.setattr("metriplane.external_sources.sandbox.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._bounded_communicate",
        _fake_communicate({"canonical.json": b"{}\n"}),
    )

    def substitute_parent_before_publication(_: Path) -> None:
        output_parent.rename(displaced_parent)
        output_parent.mkdir()

    with pytest.raises(AdapterSandboxError, match="output parent identity changed"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=substitute_parent_before_publication,
        )
    assert not output.exists()
    assert list(displaced_parent.iterdir()) == []
    output_parent.rmdir()
    displaced_parent.rename(output_parent)

    validated_stage = tmp_path / "validated-stage"
    real_rename_noreplace = sandbox_module._rename_noreplace

    def substitute_stage_before_rename(parent_fd: int, source: str, destination: str) -> None:
        source_path = Path(sandbox_module._fd_path(parent_fd)) / source
        source_path.rename(validated_stage)
        source_path.mkdir()
        (source_path / "unvalidated.txt").write_text("unvalidated\n", encoding="utf-8")
        real_rename_noreplace(parent_fd, source, destination)

    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._rename_noreplace",
        substitute_stage_before_rename,
    )
    with pytest.raises(AdapterSandboxError, match="published adapter staging identity changed"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=lambda _: None,
        )
    assert (output / "unvalidated.txt").read_text(encoding="utf-8") == "unvalidated\n"
    (output / "unvalidated.txt").unlink()
    output.rmdir()
    (validated_stage / "canonical.json").unlink()
    validated_stage.rmdir()


def test_output_link_and_output_quota_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._open_trusted_regular", _fake_trusted_open
    )
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._create_seccomp_fd",
        lambda: os.open("/dev/null", os.O_RDONLY),
    )
    monkeypatch.setattr("metriplane.external_sources.sandbox.os.geteuid", lambda: 1000)

    def fake_popen(command: list[str], **kwargs: Any) -> _FakeProcess:
        return _FakeProcess(command, **kwargs)

    def write_link_archive(
        process: Any, limits: SandboxLimits, archive_fd: int
    ) -> tuple[bytes, bytes]:
        del process, limits
        with os.fdopen(os.dup(archive_fd), "wb") as destination:
            with tarfile.open(fileobj=destination, mode="w") as archive:
                member = tarfile.TarInfo("escape")
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                archive.addfile(member)
        return b"", b""

    monkeypatch.setattr("metriplane.external_sources.sandbox.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._bounded_communicate",
        write_link_archive,
    )
    with pytest.raises(AdapterSandboxError, match="link or special"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=tmp_path / "published",
            validate_output=lambda _: None,
        )
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._bounded_communicate",
        lambda process, limits, archive_fd: (_ for _ in ()).throw(
            AdapterSandboxError("adapter sandbox output quota exceeded")
        ),
    )
    with pytest.raises(AdapterSandboxError, match="output quota"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=tmp_path / "quota",
            validate_output=lambda _: None,
        )


@pytest.mark.parametrize(
    ("names", "message"),
    [
        (["../escape"], "unsafe path"),
        (["duplicate", "duplicate"], "duplicate path"),
        (["parent/child", "parent"], "type conflicts"),
    ],
)
def test_output_archive_path_abuse_fails_before_extraction(
    tmp_path: Path,
    names: list[str],
    message: str,
) -> None:
    archive_fd = _portable_unlinked_archive_fd(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with os.fdopen(os.dup(archive_fd), "wb") as destination:
            with tarfile.open(fileobj=destination, mode="w") as archive:
                for name in names:
                    member = tarfile.TarInfo(name)
                    member.size = 1
                    archive.addfile(member, io.BytesIO(b"x"))
        with pytest.raises(AdapterSandboxError, match=message):
            _extract_bounded_output_archive(archive_fd, stage_fd, SandboxLimits())
        assert list(stage.iterdir()) == []
    finally:
        os.close(stage_fd)
        os.close(archive_fd)


def test_output_archive_rejects_extended_metadata_before_parsing_payload(tmp_path: Path) -> None:
    archive_fd = _portable_unlinked_archive_fd(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with os.fdopen(os.dup(archive_fd), "wb") as destination:
            with tarfile.open(fileobj=destination, mode="w", format=tarfile.PAX_FORMAT) as archive:
                member = tarfile.TarInfo("x" * 200)
                member.size = 1
                archive.addfile(member, io.BytesIO(b"x"))
        with pytest.raises(AdapterSandboxError, match="extension"):
            _extract_bounded_output_archive(archive_fd, stage_fd, SandboxLimits())
        assert list(stage.iterdir()) == []
    finally:
        os.close(stage_fd)
        os.close(archive_fd)


def test_unexpected_supervision_error_kills_and_reaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    output = tmp_path / "published"
    observed: dict[str, Any] = {"kills": 0}
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._open_trusted_regular", _fake_trusted_open
    )
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._create_seccomp_fd",
        lambda: os.open("/dev/null", os.O_RDONLY),
    )
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._create_output_archive",
        lambda: _portable_unlinked_archive_fd(tmp_path),
    )
    monkeypatch.setattr("metriplane.external_sources.sandbox.os.geteuid", lambda: 1000)

    def fake_popen(command: list[str], **kwargs: Any) -> _FakeProcess:
        process = _FakeProcess(command, **kwargs)
        process.returncode = None
        observed["process"] = process
        return process

    def fake_killpg(pid: int, signal_number: int) -> None:
        assert pid == 12345
        assert signal_number != 0
        observed["kills"] += 1

    monkeypatch.setattr("metriplane.external_sources.sandbox.subprocess.Popen", fake_popen)
    monkeypatch.setattr("metriplane.external_sources.sandbox.os.killpg", fake_killpg)
    monkeypatch.setattr(
        "metriplane.external_sources.sandbox._bounded_communicate",
        lambda process, limits, archive_fd: (_ for _ in ()).throw(RuntimeError("selector failed")),
    )
    with pytest.raises(RuntimeError, match="selector failed"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/normalize.py", "--out", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=lambda _: None,
        )
    assert observed["kills"] >= 1
    assert observed["process"].waited is True
    assert not output.exists()


def test_canonical_normalization_api_and_cli_use_the_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    artifact = source / "artifact.bin"
    artifact.write_bytes(b"source")
    identity = AcquisitionIdentity(
        "repo",
        "revision",
        artifact.name,
        artifact.stat().st_size,
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    (source / "normalize.py").write_text("# untrusted adapter\n", encoding="utf-8")
    observed: dict[str, Any] = {}

    def fake_sandbox(argv: list[str], **kwargs: Any) -> SandboxResult:
        observed["argv"] = argv
        verified = kwargs["verified_acquisition"]
        observed["verified_identity"] = verified.identity
        observed["verified_bytes"] = os.pread(verified.artifact_fd, identity.size, 0)
        return SandboxResult(tuple(argv), 0, "", "", 0.25)

    monkeypatch.setattr(
        "metriplane.external_sources.execution.run_normalization_sandbox",
        fake_sandbox,
    )
    result = normalize_external_fixture(
        source,
        tmp_path / "output",
        adapter_script="normalize.py",
        acquisition=identity,
        acquisition_allowlist=(identity,),
    )
    assert result.returncode == 0
    assert observed["argv"] == [
        "/usr/bin/python3",
        "/input/normalize.py",
        "--input",
        "/input",
        "--out",
        "/dev/stdout",
    ]
    assert observed["verified_identity"] == identity
    assert observed["verified_bytes"] == b"source"

    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(json.dumps([identity.__dict__]), encoding="utf-8")
    monkeypatch.setattr(
        "metriplane.external_sources.cli.normalize_external_fixture",
        lambda *args, **kwargs: SandboxResult(("/usr/bin/python3",), 0, "", "", 0.25),
    )
    assert (
        external_main(
            [
                "normalize",
                str(source),
                "--out",
                str(tmp_path / "cli-output"),
                "--adapter-script",
                "normalize.py",
                "--allowlist",
                str(allowlist),
                "--repository",
                identity.repository,
                "--revision",
                identity.revision,
                "--artifact",
                identity.artifact,
                "--artifact-size",
                str(identity.size),
                "--artifact-sha256",
                identity.sha256,
            ]
        )
        == 0
    )
    assert "PASS external fixture normalization" in capsys.readouterr().out


@pytest.mark.skipif(not TRUSTED_BWRAP_AVAILABLE, reason="bubblewrap is unavailable")
def test_escape_or_fork_or_output_or_network_fail_closed(tmp_path: Path) -> None:
    """Exercise the supported Linux boundary with a hostile real subprocess."""
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    host_sentinel = tmp_path / "host-sentinel"
    host_sentinel.write_text("unchanged\n", encoding="utf-8")
    script = fixture / "hostile.py"
    script.write_text(
        """\
import os
import socket
import sys
import io
import tarfile
from pathlib import Path

assert sys.argv[1:] == ["--out", "/dev/stdout"]
try:
    socket.create_connection(("1.1.1.1", 53), timeout=0.2)
except OSError:
    pass
else:
    raise SystemExit("network escaped")
try:
    Path("/input/hostile.py").write_text("changed")
except OSError:
    pass
else:
    raise SystemExit("input became writable")
try:
    Path(__HOST_SENTINEL__).write_text("escaped")
except OSError:
    pass
else:
    raise SystemExit("filesystem escaped")
children = []
try:
    for _ in range(128):
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        children.append(pid)
except OSError:
    pass
if children:
    raise SystemExit("process creation escaped seccomp")
for pid in children:
    os.waitpid(pid, 0)
payload = b"contained\\n"
with tarfile.open("/dev/stdout", "w|", format=tarfile.USTAR_FORMAT) as archive:
    member = tarfile.TarInfo("result.txt")
    member.size = len(payload)
    archive.addfile(member, io.BytesIO(payload))
""".replace("__HOST_SENTINEL__", repr(str(host_sentinel))),
        encoding="utf-8",
    )
    output = tmp_path / "published"

    def validate_result(stage: Path) -> None:
        assert (stage / "result.txt").read_text(encoding="utf-8") == "contained\n"

    result = run_normalization_sandbox(
        ["/usr/bin/python3", "/input/hostile.py", "--out", "/dev/stdout"],
        fixture_root=fixture,
        output_root=output,
        validate_output=validate_result,
        limits=SandboxLimits(timeout_seconds=10),
    )
    assert result.returncode == 0
    assert (output / "result.txt").read_text(encoding="utf-8") == "contained\n"
    assert host_sentinel.read_text(encoding="utf-8") == "unchanged\n"


@pytest.mark.skipif(not TRUSTED_BWRAP_AVAILABLE, reason="bubblewrap is unavailable")
def test_escape_or_fork_or_output_or_network_timeout_no_survivor(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    nonce = f"mp2-031-{uuid.uuid4()}"
    (fixture / "linger.py").write_text(
        """\
import time

time.sleep(30)
""",
        encoding="utf-8",
    )
    output = tmp_path / "published"
    with pytest.raises(AdapterSandboxError, match="timed out"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/linger.py", nonce, "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=lambda _: None,
            limits=SandboxLimits(timeout_seconds=0.25),
        )
    assert not output.exists()
    time.sleep(0.1)
    survivors = []
    for command_line in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if nonce.encode() in command_line.read_bytes():
                survivors.append(command_line.parent.name)
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
    assert survivors == []


@pytest.mark.skipif(not TRUSTED_BWRAP_AVAILABLE, reason="bubblewrap is unavailable")
def test_escape_or_fork_or_output_or_network_real_output_cap(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "noisy.py").write_text(
        "import sys\nprint('x' * 8192, file=sys.stderr)\n", encoding="utf-8"
    )
    output = tmp_path / "published"
    with pytest.raises(AdapterSandboxError, match="output quota exceeded"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/noisy.py", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=lambda _: None,
            limits=SandboxLimits(timeout_seconds=5, max_output_bytes=1024),
        )
    assert not output.exists()


@pytest.mark.skipif(not TRUSTED_BWRAP_AVAILABLE, reason="bubblewrap is unavailable")
def test_escape_or_fork_or_output_or_network_real_memory_cap(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "memory.py").write_text(
        """\
from pathlib import Path
import io
import tarfile

try:
    bytearray(96 * 1024 * 1024)
except MemoryError:
    payload = b"contained\\n"
    with tarfile.open("/dev/stdout", "w|", format=tarfile.USTAR_FORMAT) as archive:
        member = tarfile.TarInfo("result.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
else:
    raise SystemExit("memory quota escaped")
""",
        encoding="utf-8",
    )
    output = tmp_path / "published"

    def validate_result(stage: Path) -> None:
        assert (stage / "result.txt").read_text(encoding="utf-8") == "contained\n"

    result = run_normalization_sandbox(
        ["/usr/bin/python3", "/input/memory.py", "/dev/stdout"],
        fixture_root=fixture,
        output_root=output,
        validate_output=validate_result,
        limits=SandboxLimits(timeout_seconds=10, max_memory_bytes=64 * 1024 * 1024),
    )
    assert result.returncode == 0
    assert (output / "result.txt").read_text(encoding="utf-8") == "contained\n"


@pytest.mark.skipif(not TRUSTED_BWRAP_AVAILABLE, reason="bubblewrap is unavailable")
def test_escape_or_fork_or_output_or_network_real_inode_n_plus_one_cap(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "inodes.py").write_text(
        """\
import io
import tarfile

with tarfile.open("/dev/stdout", "w|", format=tarfile.USTAR_FORMAT) as archive:
    for index in range(5):
        payload = b"x"
        member = tarfile.TarInfo(f"{index}.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
""",
        encoding="utf-8",
    )
    output = tmp_path / "published"

    with pytest.raises(AdapterSandboxError, match="node-count quota exceeded"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/inodes.py", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=lambda _: None,
            limits=SandboxLimits(timeout_seconds=10, max_output_files=4),
        )
    assert not output.exists()


@pytest.mark.skipif(not TRUSTED_BWRAP_AVAILABLE, reason="bubblewrap is unavailable")
def test_escape_or_fork_or_output_or_network_real_tree_bytes_n_plus_one_cap(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "bytes.py").write_text(
        """\
import io
import tarfile

payload = b"x" * 65537
with tarfile.open("/dev/stdout", "w|", format=tarfile.USTAR_FORMAT) as archive:
    member = tarfile.TarInfo("result.bin")
    member.size = len(payload)
    archive.addfile(member, io.BytesIO(payload))
""",
        encoding="utf-8",
    )
    output = tmp_path / "published"

    with pytest.raises(AdapterSandboxError, match="tree-size quota exceeded"):
        run_normalization_sandbox(
            ["/usr/bin/python3", "/input/bytes.py", "/dev/stdout"],
            fixture_root=fixture,
            output_root=output,
            validate_output=lambda _: None,
            limits=SandboxLimits(timeout_seconds=10, max_output_tree_bytes=64 * 1024),
        )
    assert not output.exists()


@pytest.mark.skipif(not TRUSTED_BWRAP_AVAILABLE, reason="bubblewrap is unavailable")
def test_escape_or_fork_or_output_or_network_real_verified_artifact_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    approved = b"approved artifact bytes\n"
    substituted = b"substitute artifact bytes"
    artifact = source / "artifact.bin"
    artifact.write_bytes(approved)
    identity = AcquisitionIdentity(
        "repo",
        "revision",
        artifact.name,
        len(approved),
        hashlib.sha256(approved).hexdigest(),
    )
    (source / "normalize.py").write_text(
        """\
import io
import tarfile
from pathlib import Path

payload = Path("/input/artifact.bin").read_bytes()
with tarfile.open("/dev/stdout", "w|", format=tarfile.USTAR_FORMAT) as archive:
    member = tarfile.TarInfo("result.bin")
    member.size = len(payload)
    archive.addfile(member, io.BytesIO(payload))
""",
        encoding="utf-8",
    )
    real_sandbox = run_normalization_sandbox

    def substitute_then_run(argv: list[str], **kwargs: Any) -> SandboxResult:
        replacement = source / "replacement.bin"
        replacement.write_bytes(substituted)
        replacement.replace(artifact)
        return real_sandbox(argv, **kwargs)

    monkeypatch.setattr(
        "metriplane.external_sources.execution.run_normalization_sandbox",
        substitute_then_run,
    )

    def validate_result(stage: Path) -> None:
        assert (stage / "result.bin").read_bytes() == approved

    monkeypatch.setattr(
        "metriplane.external_sources.execution.validate_external_fixture_bundle",
        validate_result,
    )
    output = tmp_path / "published"
    result = normalize_external_fixture(
        source,
        output,
        adapter_script="normalize.py",
        acquisition=identity,
        acquisition_allowlist=(identity,),
        limits=SandboxLimits(timeout_seconds=10),
    )
    assert result.returncode == 0
    assert artifact.read_bytes() == substituted
    assert (output / "result.bin").read_bytes() == approved
