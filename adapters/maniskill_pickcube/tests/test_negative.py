# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from types import SimpleNamespace

import h5py
import maniskill_pickcube.core as core
import numpy as np
import pytest
from maniskill_pickcube.cli import main
from maniskill_pickcube.constants import (
    DATASET_GENERATION_COMMIT,
    DEFAULT_CONFIG,
    HDF5_SHA256,
    HDF5_SIZE,
)
from maniskill_pickcube.core import (
    AdapterError,
    RestoredFrame,
    _safe_zip_members,
    _verify_file,
    acquire,
    convert,
    inspect_source,
    load_config,
    normalize_frames,
    write_fixtures,
)


def _metadata() -> dict[str, object]:
    return {
        "env_info": {
            "env_id": "PickCube-v1",
            "env_kwargs": {
                "obs_mode": "none",
                "control_mode": "pd_joint_pos",
                "render_mode": "rgb_array",
                "reward_mode": "dense",
                "shader_dir": "default",
                "sim_backend": "auto",
            },
            "max_episode_steps": 50,
        },
        "commit_info": {"commit_id": DATASET_GENERATION_COMMIT, "branch": "main"},
        "episodes": [
            {
                "episode_id": 0,
                "episode_seed": 0,
                "control_mode": "pd_joint_pos",
                "elapsed_steps": 74,
                "success": True,
            }
        ],
        "source_type": "motionplanning",
        "source_desc": "source-shaped negative-test input",
    }


def _write_inspectable_source(trajectory: Path, metadata: Path) -> None:
    metadata.write_text(json.dumps(_metadata()), encoding="utf-8")
    with h5py.File(trajectory, "w") as handle:
        group = handle.create_group("traj_0")
        group.create_dataset("actions", data=np.zeros((74, 8), dtype=np.float32))
        states = group.create_group("env_states")
        actors = states.create_group("actors")
        actors.create_dataset("cube", data=np.zeros((75, 13), dtype=np.float32))
        actors.create_dataset("goal_site", data=np.zeros((75, 13), dtype=np.float32))
        actors.create_dataset("table-workspace", data=np.zeros((75, 13), dtype=np.float32))
        articulations = states.create_group("articulations")
        articulations.create_dataset("panda", data=np.zeros((75, 31), dtype=np.float32))
        group.create_dataset("rewards", data=np.zeros(74, dtype=np.float32))
        group.create_dataset("success", data=np.zeros(74, dtype=np.bool_))
        group.create_dataset("terminated", data=np.zeros(74, dtype=np.bool_))
        group.create_dataset("truncated", data=np.zeros(74, dtype=np.bool_))


def test_wrong_state_count_is_actionable(
    restored_frames: list[RestoredFrame], frozen_config: dict[str, object]
) -> None:
    with pytest.raises(AdapterError, match="expected 75 complete snapshots"):
        normalize_frames(restored_frames[:-1], frozen_config)


def test_nonfinite_pose_is_rejected(
    restored_frames: list[RestoredFrame], frozen_config: dict[str, object]
) -> None:
    restored_frames[0] = RestoredFrame(
        cube_pose=(math.nan, *restored_frames[0].cube_pose[1:]),
        tcp_pose=restored_frames[0].tcp_pose,
        goal_pose=restored_frames[0].goal_pose,
    )
    with pytest.raises(AdapterError, match="seven finite source pose values"):
        normalize_frames(restored_frames, frozen_config)


def test_polygon_and_wait_freeze_are_rejected(tmp_path: Path, config_path: Path) -> None:
    config = json.loads(config_path.read_text())
    config["target_polygon"]["vertices"][0][0] += 0.001
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(config))
    with pytest.raises(AdapterError, match="SHA-256 mismatch"):
        load_config(path)

    config = json.loads(config_path.read_text())
    config["variants"]["incident"]["max_wait_s"] = 2.5
    path.write_text(json.dumps(config))
    with pytest.raises(AdapterError, match="SHA-256 mismatch"):
        load_config(path)


def test_writer_requires_frozen_commit_and_explicit_overwrite(
    tmp_path: Path, restored_frames: list[RestoredFrame], config_path: Path
) -> None:
    output = tmp_path / "fixture"
    with pytest.raises(AdapterError, match="40-hex"):
        write_fixtures(
            restored_frames,
            config_path=config_path,
            output_root=output,
            adapter_commit="main",
        )
    write_fixtures(
        restored_frames,
        config_path=config_path,
        output_root=output,
        adapter_commit="a" * 40,
    )
    with pytest.raises(AdapterError, match="already exists"):
        write_fixtures(
            restored_frames,
            config_path=config_path,
            output_root=output,
            adapter_commit="a" * 40,
        )


def test_unsafe_archive_member_and_symlink_are_rejected(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape", b"x")
    with (
        zipfile.ZipFile(traversal) as archive,
        pytest.raises(AdapterError, match="unsafe path"),
    ):
        _safe_zip_members(archive)

    symlink = tmp_path / "symlink.zip"
    member = zipfile.ZipInfo("source-link")
    member.create_system = 3
    member.external_attr = (0o120777 << 16)
    with zipfile.ZipFile(symlink, "w") as archive:
        archive.writestr(member, b"target")
    with zipfile.ZipFile(symlink) as archive, pytest.raises(AdapterError, match="symlink"):
        _safe_zip_members(archive)


def test_wrong_source_hashes_name_the_artifact_and_field(tmp_path: Path) -> None:
    wrong_size = tmp_path / "trajectory.h5"
    wrong_size.write_bytes(b"wrong")
    with pytest.raises(AdapterError, match=r"trajectory HDF5 .* size mismatch"):
        _verify_file(
            wrong_size,
            label="trajectory HDF5",
            size=HDF5_SIZE,
            sha256=HDF5_SHA256,
        )

    wrong_hash = tmp_path / "trajectory.json"
    wrong_hash.write_bytes(b"x")
    with pytest.raises(AdapterError, match=r"trajectory metadata JSON .* SHA-256 mismatch"):
        _verify_file(
            wrong_hash,
            label="trajectory metadata JSON",
            size=1,
            sha256=HDF5_SHA256,
        )

    with pytest.raises(AdapterError, match=r"source ZIP .* size mismatch"):
        acquire(tmp_path / "source", downloaded_archive=wrong_size)


def test_expected_cli_hash_failure_has_no_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    trajectory = tmp_path / "trajectory.h5"
    metadata = tmp_path / "trajectory.json"
    trajectory.write_bytes(b"wrong")
    metadata.write_text("{}", encoding="utf-8")
    exit_code = main(
        [
            "convert",
            "--trajectory",
            str(trajectory),
            "--metadata",
            str(metadata),
            "--config",
            str(DEFAULT_CONFIG),
            "--adapter-commit",
            "a" * 40,
            "--out",
            str(tmp_path / "output"),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "trajectory HDF5" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing_group", "missing group traj_0"),
        ("wrong_actions", "traj_0/actions shape mismatch"),
        ("wrong_t_plus_one", "traj_0/env_states/actors/cube shape mismatch"),
        ("missing_cube", "missing traj_0/env_states/actors/cube"),
        ("missing_panda", "missing traj_0/env_states/articulations/panda"),
        ("nonfinite", "nonfinite source state in traj_0/env_states/actors/cube"),
    ],
)
def test_source_structure_failures_name_the_exact_hdf5_field(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    trajectory = tmp_path / "trajectory.h5"
    metadata = tmp_path / "trajectory.json"
    _write_inspectable_source(trajectory, metadata)
    with h5py.File(trajectory, "r+") as handle:
        group = handle["traj_0"]
        if case == "missing_group":
            handle.move("traj_0", "traj_1")
        elif case == "wrong_actions":
            del group["actions"]
            group.create_dataset("actions", data=np.zeros((73, 8), dtype=np.float32))
        elif case == "wrong_t_plus_one":
            del group["env_states/actors/cube"]
            group.create_dataset(
                "env_states/actors/cube",
                data=np.zeros((74, 13), dtype=np.float32),
            )
        elif case == "missing_cube":
            del group["env_states/actors/cube"]
        elif case == "missing_panda":
            del group["env_states/articulations/panda"]
        elif case == "nonfinite":
            group["env_states/actors/cube"][0, 0] = np.nan
        else:  # pragma: no cover - parameter list is closed
            raise AssertionError(case)
    with pytest.raises(AdapterError, match=message):
        inspect_source(trajectory, metadata, verify_hashes=False)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("episode", "expected exactly one episode_id 0"),
        ("elapsed", "episode 0 elapsed_steps"),
        ("task", "expected PickCube-v1"),
        ("generation", "expected pinned dataset-generation commit"),
        ("horizon", "expected provenance-only value 50"),
    ],
)
def test_metadata_identity_mismatches_fail_closed(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    trajectory = tmp_path / "trajectory.h5"
    metadata = tmp_path / "trajectory.json"
    _write_inspectable_source(trajectory, metadata)
    value = _metadata()
    if case == "episode":
        value["episodes"][0]["episode_id"] = 1
    elif case == "elapsed":
        value["episodes"][0]["elapsed_steps"] = 73
    elif case == "task":
        value["env_info"]["env_id"] = "OtherTask-v1"
    elif case == "generation":
        value["commit_info"]["commit_id"] = "0" * 40
    elif case == "horizon":
        value["env_info"]["max_episode_steps"] = 51
    metadata.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(AdapterError, match=message):
        inspect_source(trajectory, metadata, verify_hashes=False)


def test_all_conversion_inputs_reject_output_overlap(
    tmp_path: Path,
    restored_frames: list[RestoredFrame],
    config_path: Path,
) -> None:
    trajectory = tmp_path / "source" / "trajectory.h5"
    metadata = tmp_path / "source" / "trajectory.json"
    trajectory.parent.mkdir()
    trajectory.write_bytes(b"not-read")
    metadata.write_bytes(b"not-read")
    with pytest.raises(AdapterError, match="output/source overlap"):
        convert(
            trajectory,
            metadata,
            config_path=config_path,
            output_root=trajectory.parent,
            adapter_commit="a" * 40,
        )

    with pytest.raises(AdapterError, match="output/input overlap"):
        write_fixtures(
            restored_frames,
            config_path=config_path,
            output_root=config_path.parent,
            adapter_commit="a" * 40,
        )


def test_source_mutation_is_detected_after_restoration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restored_frames: list[RestoredFrame],
    config_path: Path,
) -> None:
    trajectory = tmp_path / "trajectory.h5"
    metadata = tmp_path / "trajectory.json"
    trajectory.write_bytes(b"before")
    metadata.write_bytes(b"metadata")
    monkeypatch.setattr(core, "_verify_file", lambda *_args, **_kwargs: None)

    def mutating_restorer(
        trajectory_path: str | Path,
        _metadata_path: str | Path,
    ) -> tuple[list[RestoredFrame], dict[str, object]]:
        Path(trajectory_path).write_bytes(b"after")
        return restored_frames, {}

    with pytest.raises(AdapterError, match="source mutation"):
        convert(
            trajectory,
            metadata,
            config_path=config_path,
            output_root=tmp_path / "output",
            adapter_commit="a" * 40,
            restorer=mutating_restorer,
        )


class _FakeRawPose:
    def __init__(self) -> None:
        self._value = np.asarray([[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]])

    def detach(self) -> _FakeRawPose:
        return self

    def cpu(self) -> _FakeRawPose:
        return self

    def numpy(self) -> np.ndarray:
        return self._value


class _FakeBase:
    def __init__(
        self,
        *,
        control_freq: int = 20,
        control_timestep: float = 0.05,
        missing_named_api: str | None = None,
    ) -> None:
        self.control_freq = control_freq
        self.control_timestep = control_timestep
        pose = SimpleNamespace(pose=SimpleNamespace(raw_pose=_FakeRawPose()))
        if missing_named_api != "cube":
            self.cube = pose
        self.goal_site = pose
        self.agent = SimpleNamespace()
        if missing_named_api != "tcp":
            self.agent.tcp_pose = pose.pose

    def reset(self, *, seed: int) -> None:
        assert seed == 0

    def set_state_dict(self, _state: object) -> None:
        return None


class _FakeEnv:
    def __init__(self, base: _FakeBase) -> None:
        self.unwrapped = base

    def close(self) -> None:
        return None

    def reset(self, *, seed: int) -> None:
        self.unwrapped.reset(seed=seed)


def _patch_restoration_shell(
    monkeypatch: pytest.MonkeyPatch,
    base: _FakeBase,
) -> None:
    import gymnasium
    from mani_skill.trajectory import utils as trajectory_utils

    monkeypatch.setattr(core, "inspect_source", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(gymnasium, "make", lambda *_args, **_kwargs: _FakeEnv(base))
    monkeypatch.setattr(
        trajectory_utils,
        "dict_to_list_of_dicts",
        lambda _group: [{} for _ in range(75)],
    )


@pytest.mark.parametrize(
    ("base", "message"),
    [
        (_FakeBase(control_freq=19), "control_freq: expected 20"),
        (_FakeBase(control_timestep=0.04), "control_timestep: expected exactly 0.05"),
        (_FakeBase(missing_named_api="cube"), "missing named cube, Panda TCP, or goal pose API"),
        (_FakeBase(missing_named_api="tcp"), "missing named cube, Panda TCP, or goal pose API"),
    ],
)
def test_runtime_timing_and_named_pose_failures_are_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base: _FakeBase,
    message: str,
) -> None:
    trajectory = tmp_path / "trajectory.h5"
    with h5py.File(trajectory, "w") as handle:
        handle.create_group("traj_0/env_states")
    metadata = tmp_path / "trajectory.json"
    metadata.write_text("{}", encoding="utf-8")
    _patch_restoration_shell(monkeypatch, base)
    with pytest.raises(AdapterError, match=message):
        core.restore_named_poses(trajectory, metadata)


def test_wrong_conversion_runtime_version_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core, "inspect_source", lambda *_args, **_kwargs: {})
    observed_versions = {
        "h5py": "3.16.0",
        "huggingface-hub": "1.27.0",
        "mani-skill": "3.0.0",
        "numpy": "2.5.2",
        "PyYAML": "6.0.3",
    }
    monkeypatch.setattr(
        core.importlib.metadata,
        "version",
        lambda name: observed_versions[name],
    )
    with pytest.raises(AdapterError, match=r"expected 3\.0\.1, got 3\.0\.0"):
        core.restore_named_poses(tmp_path / "trajectory.h5", tmp_path / "trajectory.json")
