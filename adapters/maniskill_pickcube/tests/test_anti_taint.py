# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import h5py
import numpy as np
from maniskill_pickcube.core import RestoredFrame, normalize_frames, write_fixtures


def test_quaternion_is_inert_and_not_emitted(
    restored_frames: list[RestoredFrame], frozen_config: dict[str, object]
) -> None:
    baseline = normalize_frames(restored_frames, frozen_config)[0]
    changed = [
        replace(
            frame,
            cube_pose=(*frame.cube_pose[:3], 0.0, 1.0, 0.0, 0.0),
            tcp_pose=(*frame.tcp_pose[:3], 0.5, 0.5, 0.5, 0.5),
            goal_pose=(*frame.goal_pose[:3], 0.0, 0.0, 1.0, 0.0),
        )
        for frame in restored_frames
    ]
    assert normalize_frames(changed, frozen_config)[0] == baseline
    assert b"quaternion" not in baseline
    assert b"orientation" not in baseline
    assert b'"extra"' not in baseline


def _write_source_shaped_hdf5(path: Path, frames: list[RestoredFrame]) -> None:
    with h5py.File(path, "w") as handle:
        group = handle.create_group("traj_0")
        group.create_dataset("actions", data=np.zeros((74, 8), dtype=np.float32))
        group.create_dataset("rewards", data=np.ones(74, dtype=np.float32))
        group.create_dataset("success", data=np.ones(74, dtype=np.bool_))
        group.create_dataset("failure", data=np.zeros(74, dtype=np.bool_))
        group.create_dataset("terminated", data=np.zeros(74, dtype=np.bool_))
        group.create_dataset("truncated", data=np.zeros(74, dtype=np.bool_))
        states = group.create_group("env_states")
        actors = states.create_group("actors")
        cube = np.zeros((75, 13), dtype=np.float32)
        goal = np.zeros((75, 13), dtype=np.float32)
        panda = np.zeros((75, 31), dtype=np.float32)
        cube[:, :7] = np.asarray([frame.cube_pose for frame in frames], dtype=np.float32)
        goal[:, :7] = np.asarray([frame.goal_pose for frame in frames], dtype=np.float32)
        panda[:, :7] = np.asarray([frame.tcp_pose for frame in frames], dtype=np.float32)
        actors.create_dataset("cube", data=cube)
        actors.create_dataset("goal_site", data=goal)
        states.create_group("articulations").create_dataset("panda", data=panda)


def _extract_test_named_poses(path: Path) -> list[RestoredFrame]:
    """Small-source decoder standing in for the named-API restoration boundary."""
    with h5py.File(path) as handle:
        states = handle["traj_0/env_states"]
        cube = states["actors/cube"][:, :7]
        goal = states["actors/goal_site"][:, :7]
        tcp = states["articulations/panda"][:, :7]
        return [
            RestoredFrame(
                cube_pose=tuple(float(value) for value in cube[index]),
                tcp_pose=tuple(float(value) for value in tcp[index]),
                goal_pose=tuple(float(value) for value in goal[index]),
            )
            for index in range(75)
        ]


def test_source_shaped_outcome_action_horizon_and_quaternion_anti_taint(
    tmp_path: Path,
    restored_frames: list[RestoredFrame],
    frozen_config: dict[str, object],
    config_path: Path,
) -> None:
    baseline_hdf5 = tmp_path / "baseline.h5"
    mutated_hdf5 = tmp_path / "mutated.h5"
    baseline_json = tmp_path / "baseline.json"
    mutated_json = tmp_path / "mutated.json"
    _write_source_shaped_hdf5(baseline_hdf5, restored_frames)
    shutil.copy2(baseline_hdf5, mutated_hdf5)
    baseline_json.write_text(json.dumps({"max_episode_steps": 50, "success": True}))
    mutated_json.write_text(json.dumps({"max_episode_steps": 999, "success": False}))

    with h5py.File(mutated_hdf5, "r+") as handle:
        group = handle["traj_0"]
        group["actions"][:] = 999.0
        group["rewards"][:] = -999.0
        group["success"][:] = False
        group["failure"][:] = True
        group["terminated"][:] = True
        # Removing an optional outcome array proves the semantic extractor does not require it.
        del group["truncated"]
        group["env_states/actors/cube"][:, 3:7] = [0.0, 1.0, 0.0, 0.0]
        group["env_states/actors/goal_site"][:, 3:7] = [0.0, 0.0, 1.0, 0.0]
        group["env_states/articulations/panda"][:, 3:7] = [0.5, 0.5, 0.5, 0.5]

    baseline_frames = _extract_test_named_poses(baseline_hdf5)
    mutated_frames = _extract_test_named_poses(mutated_hdf5)
    baseline_session = normalize_frames(baseline_frames, frozen_config)[0]
    mutated_session = normalize_frames(mutated_frames, frozen_config)[0]
    assert mutated_session == baseline_session
    assert hashlib.sha256(baseline_hdf5.read_bytes()).digest() != hashlib.sha256(
        mutated_hdf5.read_bytes()
    ).digest()
    assert baseline_json.read_bytes() != mutated_json.read_bytes()

    baseline_output = tmp_path / "baseline-output"
    mutated_output = tmp_path / "mutated-output"
    write_fixtures(
        baseline_frames,
        config_path=config_path,
        output_root=baseline_output,
        adapter_commit="a" * 40,
    )
    write_fixtures(
        mutated_frames,
        config_path=config_path,
        output_root=mutated_output,
        adapter_commit="a" * 40,
    )
    for variant in ("incident", "control"):
        for relative in (
            "session.jsonl",
            "entity-mapping.json",
            "domain-pack/assets.yaml",
            "domain-pack/workspace.yaml",
            "domain-pack/process.yaml",
            "domain-pack/contracts.yaml",
            "domain-pack/work_orders.csv",
        ):
            assert (baseline_output / variant / relative).read_bytes() == (
                mutated_output / variant / relative
            ).read_bytes()
