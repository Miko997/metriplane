# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from .constants import (
    ARCHIVE_REPOSITORY_PATH,
    ARCHIVE_SHA256,
    ARCHIVE_SIZE,
    CONTROL_FREQUENCY_HZ,
    CONTROL_PERIOD_NS,
    CONVERSION_COMMIT,
    CONVERSION_WHEEL_SHA256,
    DATASET_GENERATION_COMMIT,
    DATASET_REPOSITORY,
    DATASET_REVISION,
    DEFAULT_LOCK,
    EPISODE_ID,
    EXPECTED_DATASETS,
    FROZEN_CONFIG_SHA256,
    GROUP_NAME,
    HDF5_SHA256,
    HDF5_SIZE,
    JSON_SHA256,
    JSON_SIZE,
    POSE_STREAM_SHA256,
    SOURCE_BACKEND,
    STATE_COUNT,
    TRANSITION_COUNT,
)

Pose7 = tuple[float, float, float, float, float, float, float]


class AdapterError(RuntimeError):
    """Expected, actionable adapter failure."""


@dataclass(frozen=True)
class RestoredFrame:
    cube_pose: Pose7
    tcp_pose: Pose7
    goal_pose: Pose7


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def pretty_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file() or config_path.is_symlink():
        raise AdapterError(f"config {config_path}: expected the frozen regular JSON file")
    observed_sha256 = sha256_file(config_path)
    if observed_sha256 != FROZEN_CONFIG_SHA256:
        raise AdapterError(
            f"config {config_path}: SHA-256 mismatch; expected {FROZEN_CONFIG_SHA256}, "
            f"got {observed_sha256}"
        )
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"config {config_path}: cannot read frozen JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise AdapterError(f"config {config_path}: root must be a JSON object")
    if config.get("schema_version") != "org.metriplane.maniskill_pickcube.config.v1":
        raise AdapterError(f"config {config_path}: unsupported schema_version")
    selection = config.get("selection") or {}
    required_selection = {
        "episode_id": EPISODE_ID,
        "hdf5_group": GROUP_NAME,
        "transitions": TRANSITION_COUNT,
        "stored_states": STATE_COUNT,
        "normalized_frames": STATE_COUNT,
        "registered_rl_horizon": 50,
    }
    if selection != required_selection:
        raise AdapterError(
            f"config {config_path}: selection differs from frozen episode/state accounting"
        )
    timing = config.get("timing") or {}
    if timing != {
        "control_frequency_hz": CONTROL_FREQUENCY_HZ,
        "control_period_ns": CONTROL_PERIOD_NS,
        "control_period_s": 0.05,
        "frame_zero_origin_ns": 0,
    }:
        raise AdapterError(f"config {config_path}: timing differs from the frozen 20 Hz clock")
    polygon = config.get("target_polygon") or {}
    center = polygon.get("center")
    half_extent = polygon.get("half_extent")
    if not (
        isinstance(center, list)
        and len(center) == 2
        and all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in center)
        and isinstance(half_extent, (int, float))
        and math.isfinite(float(half_extent))
        and float(half_extent) > 0
    ):
        raise AdapterError(f"config {config_path}: invalid target polygon center or half_extent")
    cx, cy = (float(center[0]), float(center[1]))
    h = float(half_extent)
    expected_vertices = [
        [cx - h, cy - h],
        [cx + h, cy - h],
        [cx + h, cy + h],
        [cx - h, cy + h],
    ]
    if polygon.get("vertices") != expected_vertices:
        raise AdapterError(
            f"config {config_path}: vertices are not the canonical CCW square from center/extent"
        )
    if (
        polygon.get("boundary_policy") != "inclusive"
        or polygon.get("overlap_policy") != "reject"
        or polygon.get("outside_label") != "outside_workspace"
    ):
        raise AdapterError(f"config {config_path}: frozen zone policies changed")
    variants = config.get("variants") or {}
    if (variants.get("incident") or {}).get("max_wait_s") != 0.2:
        raise AdapterError(f"config {config_path}: incident max_wait_s must be 0.20")
    if (variants.get("control") or {}).get("max_wait_s") != 0.3:
        raise AdapterError(f"config {config_path}: control max_wait_s must be 0.30")
    return config


def _verify_file(path: Path, *, label: str, size: int, sha256: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise AdapterError(f"{label} {path}: expected a regular file")
    actual_size = path.stat().st_size
    if actual_size != size:
        raise AdapterError(f"{label} {path}: size mismatch; expected {size}, got {actual_size}")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != sha256:
        raise AdapterError(
            f"{label} {path}: SHA-256 mismatch; expected {sha256}, got {actual_sha256}"
        )


def _read_metadata(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"metadata {path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError(f"metadata {path}: root must be an object")
    return value


def inspect_source(
    trajectory: str | Path,
    metadata: str | Path,
    *,
    episode_id: int = EPISODE_ID,
    verify_hashes: bool = True,
) -> dict[str, Any]:
    trajectory_path = Path(trajectory)
    metadata_path = Path(metadata)
    if episode_id != EPISODE_ID:
        raise AdapterError(f"selection episode_id: expected frozen value 0, got {episode_id}")
    if verify_hashes:
        _verify_file(
            trajectory_path,
            label="trajectory HDF5",
            size=HDF5_SIZE,
            sha256=HDF5_SHA256,
        )
        _verify_file(
            metadata_path,
            label="trajectory metadata JSON",
            size=JSON_SIZE,
            sha256=JSON_SHA256,
        )
    source_metadata = _read_metadata(metadata_path)
    env_info = source_metadata.get("env_info")
    if not isinstance(env_info, dict) or env_info.get("env_id") != "PickCube-v1":
        raise AdapterError("metadata env_info.env_id: expected PickCube-v1")
    if env_info.get("max_episode_steps") != 50:
        raise AdapterError("metadata env_info.max_episode_steps: expected provenance-only value 50")
    env_kwargs = env_info.get("env_kwargs")
    expected_kwargs = {
        "obs_mode": "none",
        "control_mode": "pd_joint_pos",
        "render_mode": "rgb_array",
        "reward_mode": "dense",
        "shader_dir": "default",
        "sim_backend": "auto",
    }
    if env_kwargs != expected_kwargs:
        raise AdapterError("metadata env_info.env_kwargs: wrong source version or environment identity")
    commit_info = source_metadata.get("commit_info")
    if not isinstance(commit_info, dict) or commit_info.get("commit_id") != DATASET_GENERATION_COMMIT:
        raise AdapterError(
            "metadata commit_info.commit_id: expected pinned dataset-generation commit "
            f"{DATASET_GENERATION_COMMIT}"
        )
    episodes = source_metadata.get("episodes")
    if not isinstance(episodes, list):
        raise AdapterError("metadata episodes: expected an array")
    episode_matches = [item for item in episodes if isinstance(item, dict) and item.get("episode_id") == 0]
    if len(episode_matches) != 1:
        raise AdapterError("metadata episodes: expected exactly one episode_id 0")
    episode = episode_matches[0]
    if episode.get("elapsed_steps") != TRANSITION_COUNT:
        raise AdapterError(
            f"metadata episode 0 elapsed_steps: expected {TRANSITION_COUNT}, got "
            f"{episode.get('elapsed_steps')!r}"
        )
    if episode.get("control_mode") != "pd_joint_pos":
        raise AdapterError("metadata episode 0 control_mode: expected pd_joint_pos")

    try:
        import h5py
        import numpy as np
    except ImportError as exc:
        raise AdapterError("inspection requires adapter dependencies h5py and numpy") from exc
    datasets: dict[str, dict[str, object]] = {}
    try:
        with h5py.File(trajectory_path, "r") as handle:
            if GROUP_NAME not in handle:
                raise AdapterError(f"trajectory HDF5 {trajectory_path}: missing group {GROUP_NAME}")
            group = handle[GROUP_NAME]
            for dataset_path, (expected_shape, expected_dtype) in EXPECTED_DATASETS.items():
                if dataset_path not in group:
                    raise AdapterError(
                        f"trajectory HDF5 {trajectory_path}: missing {GROUP_NAME}/{dataset_path}"
                    )
                dataset = group[dataset_path]
                actual_shape = tuple(int(item) for item in dataset.shape)
                actual_dtype = str(dataset.dtype)
                if actual_shape != expected_shape:
                    raise AdapterError(
                        f"trajectory HDF5 {trajectory_path}: {GROUP_NAME}/{dataset_path} "
                        f"shape mismatch; expected {expected_shape}, got {actual_shape}"
                    )
                if actual_dtype != expected_dtype:
                    raise AdapterError(
                        f"trajectory HDF5 {trajectory_path}: {GROUP_NAME}/{dataset_path} "
                        f"dtype mismatch; expected {expected_dtype}, got {actual_dtype}"
                    )
                values = dataset[...]
                if not np.all(np.isfinite(values)):
                    raise AdapterError(
                        f"trajectory HDF5 {trajectory_path}: nonfinite source state in "
                        f"{GROUP_NAME}/{dataset_path}"
                    )
                datasets[dataset_path] = {"shape": list(actual_shape), "dtype": actual_dtype}
    except AdapterError:
        raise
    except (OSError, ValueError) as exc:
        raise AdapterError(f"trajectory HDF5 {trajectory_path}: cannot inspect: {exc}") from exc

    conversion_runtime = None
    with suppress(importlib.metadata.PackageNotFoundError):
        conversion_runtime = importlib.metadata.version("mani-skill")
    return {
        "adapter_schema_version": "org.metriplane.maniskill_pickcube.inspect.v1",
        "source": {
            "archive_reference": {
                "immutable_uri": (
                    "https://huggingface.co/datasets/haosulab/"
                    "ManiSkill_Demonstrations/resolve/"
                    f"{DATASET_REVISION}/{ARCHIVE_REPOSITORY_PATH}"
                ),
                "repository_path": ARCHIVE_REPOSITORY_PATH,
                "size": ARCHIVE_SIZE,
                "sha256": ARCHIVE_SHA256,
            },
            "dataset_repository": DATASET_REPOSITORY,
            "dataset_revision": DATASET_REVISION,
            "dataset_generation_commit": DATASET_GENERATION_COMMIT,
            "dataset_generation_package": "3.0.0b4",
            "conversion_commit": CONVERSION_COMMIT,
            "conversion_package_required": "3.0.1",
            "conversion_package_observed": conversion_runtime,
            "conversion_wheel_sha256": CONVERSION_WHEEL_SHA256,
            "trajectory_hdf5": {
                "identity_agrees_with_metadata": True,
                "immutable_uri": (
                    "https://huggingface.co/datasets/haosulab/"
                    "ManiSkill_Demonstrations/resolve/"
                    f"{DATASET_REVISION}/demos/PickCube-v1/motionplanning/trajectory.h5"
                ),
                "path": str(trajectory_path),
                "size": trajectory_path.stat().st_size,
                "sha256": sha256_file(trajectory_path),
            },
            "trajectory_json": {
                "identity_agrees_with_hdf5": True,
                "immutable_uri": (
                    "https://huggingface.co/datasets/haosulab/"
                    "ManiSkill_Demonstrations/resolve/"
                    f"{DATASET_REVISION}/demos/PickCube-v1/motionplanning/trajectory.json"
                ),
                "path": str(metadata_path),
                "size": metadata_path.stat().st_size,
                "sha256": sha256_file(metadata_path),
            },
        },
        "selection": {
            "episode_id": 0,
            "hdf5_group": GROUP_NAME,
            "transitions": TRANSITION_COUNT,
            "stored_states": STATE_COUNT,
            "registered_rl_horizon": 50,
        },
        "datasets": datasets,
        "control_frequency_hz": CONTROL_FREQUENCY_HZ,
        "control_period_s": 0.05,
        "restoration_available": conversion_runtime == "3.0.1",
        "rights": {
            "source_license_declaration": "Apache-2.0 dataset card",
            "raw_source_distribution": "referenced_only",
            "portable_derived_data": "Apache-2.0 attribution and modified-data notice",
        },
    }


def restore_named_poses(
    trajectory: str | Path,
    metadata: str | Path,
) -> tuple[list[RestoredFrame], dict[str, object]]:
    inspect_source(trajectory, metadata, verify_hashes=True)
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise AdapterError(
            "conversion environment platform: expected Linux/x86_64, got "
            f"{platform.system()}/{platform.machine()}"
        )
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12):
        raise AdapterError(
            "conversion environment runtime: expected CPython 3.12, got "
            f"{platform.python_implementation()} {platform.python_version()}"
        )
    locked_direct_versions = {
        "h5py": "3.16.0",
        "huggingface-hub": "1.27.0",
        "mani-skill": "3.0.1",
        "numpy": "2.5.2",
        "PyYAML": "6.0.3",
    }
    for distribution, expected_version in locked_direct_versions.items():
        try:
            observed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise AdapterError(
                f"conversion environment dependency {distribution}: missing"
            ) from exc
        if observed != expected_version:
            raise AdapterError(
                f"conversion environment dependency {distribution}: expected "
                f"{expected_version}, got {observed}"
            )
    try:
        observed_version = importlib.metadata.version("mani-skill")
    except importlib.metadata.PackageNotFoundError as exc:
        raise AdapterError("conversion requires mani_skill==3.0.1") from exc
    if observed_version != "3.0.1":
        raise AdapterError(
            f"conversion runtime mani_skill version: expected 3.0.1, got {observed_version}"
        )
    try:
        import gymnasium as gym
        import h5py
        import mani_skill.envs  # noqa: F401
        import numpy as np
        from mani_skill.trajectory import utils as trajectory_utils
    except ImportError as exc:
        raise AdapterError(f"conversion environment dependency unavailable: {exc}") from exc

    env = None
    try:
        env = gym.make(
            "PickCube-v1",
            obs_mode="none",
            control_mode="pd_joint_pos",
            render_mode="rgb_array",
            reward_mode="dense",
            shader_dir="default",
            sim_backend="physx_cpu",
            robot_uids="panda",
            num_envs=1,
        )
        base = env.unwrapped
        if int(base.control_freq) != CONTROL_FREQUENCY_HZ:
            raise AdapterError(
                f"conversion environment control_freq: expected 20, got {base.control_freq}"
            )
        if not math.isclose(float(base.control_timestep), 0.05, rel_tol=0.0, abs_tol=1e-12):
            raise AdapterError(
                "conversion environment control_timestep: expected exactly 0.05 seconds"
            )
        env.reset(seed=0)
        frames: list[RestoredFrame] = []
        named_pose_values: list[list[float]] = []
        with h5py.File(Path(trajectory), "r") as handle:
            state_group = handle[f"{GROUP_NAME}/env_states"]
            states = trajectory_utils.dict_to_list_of_dicts(state_group)
            if len(states) != STATE_COUNT:
                raise AdapterError(
                    f"trajectory HDF5 {trajectory}: expected {STATE_COUNT} restored states, "
                    f"got {len(states)}"
                )
            for index, state in enumerate(states):
                base.set_state_dict(state)
                try:
                    cube = np.asarray(
                        base.cube.pose.raw_pose.detach().cpu().numpy()[0], dtype=np.float32
                    )
                    tcp = np.asarray(
                        base.agent.tcp_pose.raw_pose.detach().cpu().numpy()[0], dtype=np.float32
                    )
                    goal = np.asarray(
                        base.goal_site.pose.raw_pose.detach().cpu().numpy()[0], dtype=np.float32
                    )
                except AttributeError as exc:
                    raise AdapterError(
                        f"restored state {index}: missing named cube, Panda TCP, or goal pose API"
                    ) from exc
                for label, pose in (("cube.pose", cube), ("agent.tcp_pose", tcp), ("goal_site.pose", goal)):
                    if pose.shape != (7,) or not np.all(np.isfinite(pose)):
                        raise AdapterError(
                            f"restored state {index} {label}: expected seven finite pose values"
                        )
                stored_cube = np.asarray(state["actors"]["cube"][:7], dtype=np.float32)
                stored_goal = np.asarray(state["actors"]["goal_site"][:7], dtype=np.float32)
                if not np.array_equal(cube, stored_cube):
                    raise AdapterError(
                        f"restored state {index} cube.pose: named pose differs from source actor state"
                    )
                if not np.array_equal(goal, stored_goal):
                    raise AdapterError(
                        f"restored state {index} goal_site.pose: named pose differs from source actor state"
                    )
                # This ordering is the frozen audit pose stream: cube, goal, then TCP.
                named_pose_values.append([*cube.tolist(), *goal.tolist(), *tcp.tolist()])
                frames.append(
                        RestoredFrame(
                            cube_pose=cast(Pose7, tuple(float(item) for item in cube)),
                            tcp_pose=cast(Pose7, tuple(float(item) for item in tcp)),
                            goal_pose=cast(Pose7, tuple(float(item) for item in goal)),
                        )
                )
        pose_stream = np.asarray(named_pose_values, dtype="<f4").tobytes()
        pose_stream_sha256 = hashlib.sha256(pose_stream).hexdigest()
        if pose_stream_sha256 != POSE_STREAM_SHA256:
            raise AdapterError(
                "named restoration pose stream changed: expected "
                f"{POSE_STREAM_SHA256}, got {pose_stream_sha256}"
            )
        goal_pose = frames[0].goal_pose
        if any(frame.goal_pose != goal_pose for frame in frames):
            raise AdapterError("restored goal_site.pose changed within episode 0")
        return frames, {
            "mani_skill_version": observed_version,
            "control_frequency_hz": CONTROL_FREQUENCY_HZ,
            "control_period_s": 0.05,
            "pose_stream_sha256": pose_stream_sha256,
            "goal_pose": list(goal_pose),
            "conversion_environment_dependency": "software Vulkan device required for scene construction",
            "stepped_simulation": False,
            "actions_integrated": False,
            "rendered": False,
        }
    except AdapterError:
        raise
    except Exception as exc:
        raise AdapterError(f"ManiSkill named-state restoration failed: {type(exc).__name__}: {exc}") from exc
    finally:
        if env is not None:
            env.close()


def _point_on_segment(
    x: float,
    y: float,
    start: Sequence[float],
    end: Sequence[float],
    *,
    tolerance: float = 1e-12,
) -> bool:
    ax, ay = float(start[0]), float(start[1])
    bx, by = float(end[0]), float(end[1])
    cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
    if abs(cross) > tolerance:
        return False
    dot = (x - ax) * (bx - ax) + (y - ay) * (by - ay)
    return dot >= -tolerance and dot <= (bx - ax) ** 2 + (by - ay) ** 2 + tolerance


def point_in_polygon_inclusive(x: float, y: float, vertices: Sequence[Sequence[float]]) -> bool:
    if len(vertices) < 3:
        raise AdapterError("target polygon vertices: expected at least three points")
    for start, end in zip(vertices, [*vertices[1:], vertices[0]], strict=True):
        if _point_on_segment(x, y, start, end):
            return True
    inside = False
    previous = vertices[-1]
    for current in vertices:
        x1, y1 = float(current[0]), float(current[1])
        x2, y2 = float(previous[0]), float(previous[1])
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def normalize_frames(
    restored_frames: Sequence[RestoredFrame],
    config: Mapping[str, Any],
) -> tuple[bytes, dict[str, object]]:
    if len(restored_frames) != STATE_COUNT:
        raise AdapterError(
            f"restored states: expected {STATE_COUNT} complete snapshots, got {len(restored_frames)}"
        )
    polygon = config["target_polygon"]
    vertices = polygon["vertices"]
    zone_id = str(polygon["zone_id"])
    outside_label = str(polygon["outside_label"])
    lines: list[bytes] = []
    cube_inside: list[int] = []
    tcp_inside: list[int] = []
    for index, frame in enumerate(restored_frames):
        objects: list[dict[str, object]] = []
        for object_id, pose, entries in (
            ("cube_1", frame.cube_pose, cube_inside),
            ("robot_tcp_1", frame.tcp_pose, tcp_inside),
        ):
            if len(pose) != 7 or not all(math.isfinite(float(value)) for value in pose):
                raise AdapterError(
                    f"restored state {index} {object_id}: expected seven finite source pose values"
                )
            x, y = float(pose[0]), float(pose[1])
            inside = point_in_polygon_inclusive(x, y, vertices)
            if inside:
                entries.append(index)
            objects.append(
                {
                    "id": object_id,
                    "pos_world": [x, y, 0.0],
                    "zone": zone_id if inside else outside_label,
                }
            )
        ts_sim_ns = index * CONTROL_PERIOD_NS
        frame_record = {
            "schema_version": "1.0",
            "source_backend": SOURCE_BACKEND,
            "ts": ts_sim_ns / 1_000_000_000,
            "ts_sim_ns": ts_sim_ns,
            "frame_id": index,
            "objects": objects,
            "events": [],
        }
        raw = canonical_json_bytes(frame_record)
        if b'"extra"' in raw or b'"confidence"' in raw or b'"orientation"' in raw:
            raise AdapterError(f"normalized frame {index}: prohibited field emitted")
        lines.append(raw + b"\n")
    if cube_inside != list(range(66, 75)):
        raise AdapterError(f"target polygon: cube entry ordering changed; inside frames={cube_inside}")
    if tcp_inside != list(range(71, 75)):
        raise AdapterError(f"target polygon: TCP entry ordering changed; inside frames={tcp_inside}")
    return b"".join(lines), {
        "cube_target_entry_frame": 66,
        "tcp_target_entry_frame": 71,
        "missing_tool_interval_s": 0.25,
        "shared_session_sha256": hashlib.sha256(b"".join(lines)).hexdigest(),
    }


def _yaml_bytes(value: object) -> bytes:
    try:
        import yaml
    except ImportError as exc:
        raise AdapterError("fixture generation requires PyYAML") from exc
    return yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).encode("utf-8")


def _file_reference(path: str, data: bytes, media_type: str) -> dict[str, str]:
    return {
        "media_type": media_type,
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _entity_mapping() -> dict[str, object]:
    return {
        "mappings": [
            {
                "atlas_asset_id": "cube_1",
                "description": (
                    "One-to-one operator-frozen mapping from the restored cube actor to the "
                    "normalized material object."
                ),
                "normalized_object_id": "cube_1",
                "process_relevant": True,
                "source_entities": [
                    {
                        "source_artifact_id": "pickcube_trajectory_hdf5",
                        "source_entity_id": "traj_0/env_states/actors/cube",
                    }
                ],
            },
            {
                "atlas_asset_id": "robot_tcp_1",
                "description": (
                    "One-to-one operator-frozen mapping from Panda state to the named "
                    "agent.tcp_pose tool object."
                ),
                "normalized_object_id": "robot_tcp_1",
                "process_relevant": True,
                "source_entities": [
                    {
                        "source_artifact_id": "pickcube_trajectory_hdf5",
                        "source_entity_id": "traj_0/env_states/articulations/panda",
                    }
                ],
            },
        ],
        "schema_version": "metriplane.external_entity_mapping.v1",
    }


def _domain_pack_files(config: Mapping[str, Any], max_wait_s: float) -> dict[str, bytes]:
    polygon = config["target_polygon"]
    assets = {
        "schema_version": "metriplane.atlas.asset_registry.v1",
        "assets": [
            {
                "object_id": "cube_1",
                "asset_id": "cube_1",
                "asset_type": "material",
                "label": "Restored PickCube cube (planar material object)",
                "work_order_id": "WO-MANISKILL-PICKCUBE-001",
                "expected_zones": ["target_xy_region"],
                "expected_stations": ["target_station"],
            },
            {
                "object_id": "robot_tcp_1",
                "asset_id": "robot_tcp_1",
                "asset_type": "tool",
                "label": "Restored Panda TCP (planar required tool)",
                "work_order_id": "WO-MANISKILL-PICKCUBE-001",
                "expected_zones": ["target_xy_region"],
                "expected_stations": ["target_station"],
            },
        ],
    }
    workspace = {
        "schema_version": "metriplane.atlas.workspace.v1",
        "cell_id": "maniskill_pickcube_planar_fixture",
        "units": "meters",
        "zones": [
            {
                "zone_id": "target_xy_region",
                "zone_type": "work_station",
                "label": "Operator-configured planar target region",
                "polygon": polygon["vertices"],
            }
        ],
        "stations": [
            {
                "station_id": "target_station",
                "zone_id": "target_xy_region",
                "label": "Operator-configured planar target station",
            }
        ],
    }
    process = {
        "schema_version": "metriplane.atlas.process_model.v1",
        "process_id": "maniskill_pickcube_planar_tcp_presence",
        "work_order_type": "external_fixture",
        "steps": [
            {
                "step_id": "cube_target_requires_tcp",
                "label": "Cube in target planar region requires robot TCP",
                "expected_asset_types": ["material"],
                "required_assets": ["robot_tcp_1"],
                "required_zone": "target_xy_region",
                "required_station": "target_station",
                "max_wait_s": max_wait_s,
            }
        ],
    }
    contracts = {
        "schema_version": "metriplane.atlas.contracts.v1",
        "contracts": [
            {
                "contract_id": "robot_tcp_required_with_cube",
                "kind": "process_asset_presence",
                "process_step_id": "cube_target_requires_tcp",
                "required_asset_id": "robot_tcp_1",
                "zone_id": "target_xy_region",
                "station_id": "target_station",
                "max_wait_s": max_wait_s,
                "severity": "warning",
                "note": (
                    "Observe-only Metriplane-authored planar rule; it is not a PickCube "
                    "success or safety decision."
                ),
            }
        ],
    }
    work_orders = (
        b"work_order_id,process_id,product,priority\n"
        b"WO-MANISKILL-PICKCUBE-001,maniskill_pickcube_planar_tcp_presence,"
        b"pickcube_planar_fixture,normal\n"
    )
    return {
        "domain-pack/assets.yaml": _yaml_bytes(assets),
        "domain-pack/workspace.yaml": _yaml_bytes(workspace),
        "domain-pack/process.yaml": _yaml_bytes(process),
        "domain-pack/contracts.yaml": _yaml_bytes(contracts),
        "domain-pack/work_orders.csv": work_orders,
    }


def _normalization_operations() -> list[dict[str, object]]:
    return [
        {
            "applied": True,
            "declaration_path": "normalization.clock",
            "kind": "time_mapping",
            "operation_id": "map-state-index-to-fixed-nanoseconds",
            "summary": "Mapped state index i to ts_sim_ns=i*50000000 and derived ts from it.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.entity_mapping",
            "kind": "entity_mapping",
            "operation_id": "map-cube-and-tcp",
            "summary": "Applied the hashed one-to-one cube and Panda TCP mapping.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.coordinates.transform",
            "kind": "coordinate_transform",
            "operation_id": "identity-world-frame",
            "summary": "Source and target use the same metre-valued ManiSkill world frame.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.coordinates.projection",
            "kind": "projection",
            "operation_id": "project-planar-xy",
            "summary": "Copied world x/y and set normalized z to zero; orientation was omitted.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.zone_assignment",
            "kind": "zone_assignment",
            "operation_id": "assign-frozen-target-polygon",
            "summary": "Applied the Layer-C inclusive polygon and explicit outside label.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.temporal_alignment.synchronization",
            "kind": "synchronization",
            "operation_id": "no-synchronization",
            "summary": "Each restored simulator state supplies both objects synchronously.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.temporal_alignment.resampling",
            "kind": "resampling",
            "operation_id": "no-resampling",
            "summary": "All 75 stored states are retained one-for-one.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.temporal_alignment.interpolation",
            "kind": "interpolation",
            "operation_id": "no-interpolation",
            "summary": "No position or time value is interpolated.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.completeness.carry_forward",
            "kind": "carry_forward",
            "operation_id": "no-carry-forward",
            "summary": "Every frame is complete; no observation is carried forward.",
        },
    ]


def _source_artifacts() -> list[dict[str, object]]:
    base_uri = (
        "https://huggingface.co/datasets/haosulab/ManiSkill_Demonstrations/resolve/"
        f"{DATASET_REVISION}/"
    )
    return [
        {
            "artifact_id": "pickcube_archive",
            "description": "Pinned upstream PickCube demonstration ZIP; referenced, never included.",
            "media_type": "application/zip",
            "presence": "referenced",
            "rights_id": "maniskill-demonstrations-rights",
            "role": "source_archive",
            "sha256": ARCHIVE_SHA256,
            "uri": base_uri + ARCHIVE_REPOSITORY_PATH,
        },
        {
            "artifact_id": "pickcube_trajectory_hdf5",
            "description": (
                "Pinned HDF5 trajectory member from the verified PickCube archive; "
                "referenced, never included."
            ),
            "media_type": "application/x-hdf5",
            "presence": "referenced",
            "rights_id": "maniskill-demonstrations-rights",
            "role": "trajectory",
            "sha256": HDF5_SHA256,
            "uri": base_uri + "demos/PickCube-v1/motionplanning/trajectory.h5",
        },
        {
            "artifact_id": "pickcube_trajectory_metadata",
            "description": (
                "Pinned JSON metadata member from the verified PickCube archive; "
                "referenced, never included."
            ),
            "media_type": "application/json",
            "presence": "referenced",
            "rights_id": "maniskill-demonstrations-rights",
            "role": "metadata_sidecar",
            "sha256": JSON_SHA256,
            "uri": base_uri + "demos/PickCube-v1/motionplanning/trajectory.json",
        },
    ]


def _rights() -> dict[str, object]:
    citation = [
        {
            "text": "ManiSkill Demonstrations dataset and PickCube-v1 motion-planning trajectory",
            "uri": (
                "https://huggingface.co/datasets/haosulab/ManiSkill_Demonstrations/tree/"
                + DATASET_REVISION
            ),
        },
        {
            "text": "ManiSkill project",
            "uri": "https://github.com/mani-skill/ManiSkill",
        },
    ]
    return {
        "fixture": {
            "access": "public",
            "citation": citation,
            "license": {
                "identifier": "Apache-2.0",
                "status": "declared",
                "uri": "https://www.apache.org/licenses/LICENSE-2.0",
            },
            "permission_basis": (
                "The portable normalized coordinates are modified/derived data distributed "
                "with Apache-2.0 attribution and notice; raw source bytes and assets are absent."
            ),
            "redistribution": "allowed",
            "redistribution_permission": "verified",
        },
        "source_artifacts": [
            {
                "citation": citation,
                "license": {
                    "identifier": "Apache-2.0",
                    "status": "declared",
                    "uri": "https://www.apache.org/licenses/LICENSE-2.0",
                },
                "permission_basis": (
                    "The public dataset card declares Apache-2.0. No standalone dataset "
                    "LICENSE file was found; only modified/derived fixture data are redistributed."
                ),
                "redistribution": "derived_only",
                "redistribution_permission": "verified",
                "rights_id": "maniskill-demonstrations-rights",
                "source_access": "public",
                "source_use_permission": "verified",
            }
        ],
    }


def _annotation_policy() -> dict[str, object]:
    hdf = "pickcube_trajectory_hdf5"
    meta = "pickcube_trajectory_metadata"
    values = [
        ("reward", "traj_0/rewards", "provenance_only", "source_artifact", [hdf]),
        ("success", "traj_0/success", "provenance_only", "source_artifact", [hdf]),
        ("success", "episodes[0].success", "provenance_only", "source_artifact", [meta]),
        ("terminated", "traj_0/terminated", "provenance_only", "source_artifact", [hdf]),
        ("truncated", "traj_0/truncated", "provenance_only", "source_artifact", [hdf]),
        ("actions", "traj_0/actions", "excluded", "not_retained", [hdf]),
        (
            "elapsed steps",
            "episodes[0].elapsed_steps",
            "provenance_only",
            "source_artifact",
            [meta],
        ),
        (
            "registered RL horizon",
            "env_info.max_episode_steps",
            "provenance_only",
            "source_artifact",
            [meta],
        ),
        ("task/environment label", "env_info.env_id", "source_selection_only", "source_artifact", [meta]),
        ("control mode", "episodes[0].control_mode", "provenance_only", "source_artifact", [meta]),
        ("source type", "source_type", "provenance_only", "source_artifact", [meta]),
        ("source description", "source_desc", "provenance_only", "source_artifact", [meta]),
    ]
    return {
        "annotations": [
            {
                "name": name,
                "retained_in": retained,
                "source_artifact_ids": artifacts,
                "source_field": field,
                "treatment": treatment,
            }
            for name, field, treatment, retained, artifacts in values
        ],
        "frame_state_events_policy": "empty",
        "inventory_complete": True,
        "source_incident_ids_in_normalized_input": False,
        "used_as_incident_truth": False,
        "used_as_process_events": False,
    }


def _manifest(
    *,
    config: Mapping[str, Any],
    variant: str,
    adapter_commit: str,
    files: Mapping[str, bytes],
    config_sha256: str,
    session_sha256: str,
) -> dict[str, object]:
    variant_config = config["variants"][variant]
    fixture_id = str(variant_config["fixture_id"])
    domain_pack_id = str(variant_config["domain_pack_id"])
    mapping_file_ref = _file_reference(
        "entity-mapping.json", files["entity-mapping.json"], "application/json"
    )
    mapping_ref = dict(mapping_file_ref)
    mapping_ref["schema_version"] = "metriplane.external_entity_mapping.v1"
    workspace_ref = _file_reference(
        "domain-pack/workspace.yaml", files["domain-pack/workspace.yaml"], "application/yaml"
    )
    assets_ref = _file_reference(
        "domain-pack/assets.yaml", files["domain-pack/assets.yaml"], "application/yaml"
    )
    adapter_environment_ref = _file_reference(
        "source/uv.lock", files["source/uv.lock"], "text/plain"
    )
    parameter_reference = _file_reference(
        "source/frozen-config.json", files["source/frozen-config.json"], "application/json"
    )
    hdf = "pickcube_trajectory_hdf5"
    return {
        "adapter": {
            "adapter_id": "org.metriplane.maniskill_pickcube",
            "commit": adapter_commit,
            "entrypoint": "maniskill_pickcube.cli:main",
            "environment": {
                "architecture": "x86_64",
                "dependency_lock": adapter_environment_ref,
                "description": (
                    "Pinned isolated Linux conversion environment; software Vulkan may be "
                    "needed for upstream scene construction but not fixture evaluation."
                ),
                "operating_system": "Linux",
                "runtime": "CPython",
                "runtime_version": "3.12",
            },
            "name": "Metriplane ManiSkill PickCube adapter",
            "parameters": {
                "reference": parameter_reference,
                "sha256": config_sha256,
            },
            "repository_uri": "https://github.com/Miko997/metriplane",
            "version": "1.0.0",
        },
        "contract_profile": "metriplane.atlas.complete_snapshot.v1",
        "domain_pack": {
            "assets": assets_ref,
            "contracts": _file_reference(
                "domain-pack/contracts.yaml", files["domain-pack/contracts.yaml"], "application/yaml"
            ),
            "domain_pack_id": domain_pack_id,
            "process": _file_reference(
                "domain-pack/process.yaml", files["domain-pack/process.yaml"], "application/yaml"
            ),
            "rationale": (
                "The operator froze this planar target region after inspecting the selected "
                "source goal pose. The region is a Metriplane compatibility-test rule, not a "
                "ManiSkill task-success definition."
            ),
            "rule_origin": "operator_configured_rules",
            "source_annotations_used": False,
            "work_orders": _file_reference(
                "domain-pack/work_orders.csv", files["domain-pack/work_orders.csv"], "text/csv"
            ),
            "workspace": workspace_ref,
        },
        "evaluation": {
            "domain_pack_id": domain_pack_id,
            "engine": "atlas",
            "expected_outcome_is_input": False,
            "metriplane_version": "0.3.0",
            "provenance_layer": "metriplane_derived_results",
        },
        "extensions": {
            "org.maniskill.pick_cube": {
                "conversion_identity": {
                    "commit": CONVERSION_COMMIT,
                    "package_version": "3.0.1",
                    "release": "v3.0.1",
                    "wheel_sha256": CONVERSION_WHEEL_SHA256,
                },
                "dataset_generation_identity": {
                    "commit": DATASET_GENERATION_COMMIT,
                    "package_version": "3.0.0b4",
                },
                "descriptive_goal_pose": {
                    "projected_xy": config["target_polygon"]["center"],
                    "restored_source_pose_xyz_qwxyz": [
                        0.026815734803676605,
                        -0.0019813179969787598,
                        0.2889334559440613,
                        1.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    "source_api": "goal_site.pose",
                    "use": "audit and operator rationale only; not Atlas runtime input",
                },
                "source_absence_inventory": {"failure_array": "absent"},
                "orientation_exclusion": {
                    "audit_yaw_well_defined": True,
                    "excluded_components": ["source z", "quaternion", "yaw", "roll", "pitch"],
                },
                "selection_accounting": {
                    "episode_id": EPISODE_ID,
                    "hdf5_group": GROUP_NAME,
                    "normalized_frames": STATE_COUNT,
                    "registered_rl_horizon": 50,
                    "stored_states": STATE_COUNT,
                    "transitions": TRANSITION_COUNT,
                },
                "source_byte_sizes": {
                    "pickcube_archive": ARCHIVE_SIZE,
                    "pickcube_trajectory_hdf5": HDF5_SIZE,
                    "pickcube_trajectory_metadata": JSON_SIZE,
                },
            }
        },
        "fixture": {
            "bounded_recording": True,
            "description": (
                "All 75 restored states from pinned PickCube episode 0, normalized as "
                "position-only cube and Panda TCP planar snapshots."
            ),
            "distribution": "derived_only",
            "fixture_id": fixture_id,
            "title": f"ManiSkill PickCube episode 0 planar {variant} fixture",
        },
        "limitations": [
            "This fixture evaluates bounded XY occupancy and timing only; it does not evaluate 3D placement, orientation, grasp state, or official PickCube success.",
            "The source quaternion exists and audit yaw was numerically well-defined, but source Z, quaternion, yaw, roll, and pitch are excluded from normalized evaluation.",
            "Atlas does not establish physical accuracy, correctness, calibration, or simulator realism of upstream restored state.",
            "Episode selection was outcome-blind within an official corpus that had already been success-filtered upstream.",
            "The target polygon is an operator-authored compatibility rule, not ManiSkill source truth.",
            "This is not a certified safety or quality decision and does not control machinery.",
        ],
        "normalization": {
            "atlas_asset_mapping": assets_ref,
            "authoritative_object_collection": "objects",
            "clock": {
                "description": (
                    "Map stored-state index i to ts_sim_ns=i*50000000; ts is derived from the "
                    "same integer nanosecond value."
                ),
                "evaluation_field": "ts_sim_ns",
                "fixed_step_ns": CONTROL_PERIOD_NS,
                "fixed_step_origin_ns": 0,
                "mapping_method": "fixed_step",
                "source_clock": "stored environment-state order",
                "source_field": "traj_0/env_states[*] index",
                "source_unit": "index",
            },
            "completeness": {
                "carry_forward": {"fields": [], "method": "none"},
                "frame_semantics": "complete_snapshot",
                "omission_policy": "reject_omission",
                "partial_updates_materialized": False,
                "process_relevant_entity_policy": "known_in_every_frame",
                "source_stream_semantics": "complete_snapshot",
                "unknown_state_policy": "reject_fixture",
            },
            "confidence": {"mode": "absent"},
            "coordinates": {
                "information_loss": [
                    {
                        "impact": (
                            "Atlas receives x/y with z=0 and no orientation; 3D placement, "
                            "attitude, grasp state, and official task success cannot be evaluated."
                        ),
                        "lost_information": [
                            "source z coordinate",
                            "complete source quaternion",
                            "yaw",
                            "roll",
                            "pitch",
                        ],
                        "operation": "position-only planar projection",
                    }
                ],
                "projection": {
                    "dropped_axes": ["z"],
                    "implementation": "Copy source world x/y, set normalized z to 0.0, omit orientation.",
                    "method": "planar_xy",
                    "output_z_policy": "zero",
                },
                "source_frame": "maniskill_world",
                "source_units": "meters",
                "target_frame": "maniskill_world",
                "target_units": "meters",
                "transform": {
                    "implementation": "No translation, rotation, scaling, or axis swap.",
                    "method": "identity",
                },
            },
            "entity_mapping": mapping_ref,
            "field_provenance": [
                {
                    "derivation": "Set the frozen FrameStateModel 1.0 schema version.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "schema_version",
                    "source_artifact_ids": [hdf],
                },
                {
                    "derivation": "Set the stable namespaced external restoration backend.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "source_backend",
                    "source_artifact_ids": [hdf],
                },
                {
                    "derivation": "Derive seconds from the authoritative fixed-step nanosecond clock.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "ts",
                    "source_artifact_ids": [hdf],
                    "source_fields": ["traj_0/env_states[*] index"],
                },
                {
                    "derivation": "Multiply stored-state index by 50000000 ns.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "ts_sim_ns",
                    "source_artifact_ids": [hdf],
                    "source_fields": ["traj_0/env_states[*] index"],
                },
                {
                    "derivation": "Assign sequential normalized frame IDs from stored-state order.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "frame_id",
                    "source_artifact_ids": [hdf],
                    "source_fields": ["traj_0/env_states[*] index"],
                },
                {
                    "derivation": "Apply the separately hashed one-to-one entity mapping.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "objects[*].id",
                    "parameter_references": [mapping_file_ref],
                    "source_artifact_ids": [hdf],
                    "source_fields": [
                        "traj_0/env_states/actors/cube",
                        "traj_0/env_states/articulations/panda",
                    ],
                },
                {
                    "derivation": (
                        "Restore every state independently, read cube.pose and agent.tcp_pose "
                        "(pinned forward kinematics), copy x/y, and set z=0."
                    ),
                    "layer": "adapter_derived_fact",
                    "normalized_field": "objects[*].pos_world",
                    "source_artifact_ids": [hdf],
                    "source_fields": [
                        "traj_0/env_states/actors/cube",
                        "traj_0/env_states/articulations/panda",
                    ],
                },
                {
                    "derivation": "Apply the separately hashed Layer-C inclusive polygon.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "objects[*].zone",
                    "parameter_references": [workspace_ref],
                    "source_artifact_ids": [hdf],
                    "source_fields": [
                        "traj_0/env_states/actors/cube",
                        "traj_0/env_states/articulations/panda",
                    ],
                },
            ],
            "frame_state_model_version": "1.0",
            "source_annotations": _annotation_policy(),
            "source_backend": SOURCE_BACKEND,
            "temporal_alignment": {
                "interpolation": {"fields": [], "method": "none"},
                "resampling": {"fields": [], "method": "none"},
                "synchronization": {"fields": [], "method": "not_applicable"},
            },
            "zone_assignment": {
                "boundary_policy": "inclusive",
                "definitions": workspace_ref,
                "implementation": (
                    "Test each x/y point against the frozen polygon, reject overlap, and "
                    "emit outside_workspace when outside."
                ),
                "method": "polygon",
                "outside_workspace_policy": "explicit_label",
                "outside_zone_label": "outside_workspace",
                "overlap_policy": "reject",
                "zone_priority": [],
            },
        },
        "normalized_artifacts": {
            "checksums_path": "CHECKSUMS.sha256",
            "expected_outcome": {
                **_file_reference(
                    "expected-outcome.json", files["expected-outcome.json"], "application/json"
                ),
                "atlas_input": False,
                "role": "test_metadata_only",
            },
            "normalization_report": _file_reference(
                "normalization-report.json", files["normalization-report.json"], "application/json"
            ),
            "session": {
                **_file_reference("session.jsonl", files["session.jsonl"], "application/x-ndjson"),
                "frame_count": STATE_COUNT,
                "frame_state_model_version": "1.0",
            },
        },
        "rights": _rights(),
        "schema_version": "metriplane.external_source_contract.v1",
        "selection": {
            "artifact_ids": [hdf, "pickcube_trajectory_metadata"],
            "episode_id": "0",
            "method": "episode",
            "rationale": (
                "Select frozen episode 0 (HDF5 group traj_0), retaining all 74 transitions "
                "and 75 stored states. Selection was outcome-blind within a success-filtered corpus."
            ),
        },
        "source_artifacts": _source_artifacts(),
        "source_project": {
            "canonical_uri": "https://huggingface.co/datasets/haosulab/ManiSkill_Demonstrations",
            "name": "ManiSkill Demonstrations",
            "revision": {"kind": "dataset_revision", "value": DATASET_REVISION},
            "version": "generated-with-mani_skill-3.0.0b4",
        },
        "trust_layers": {
            "adapter_derived_facts": "adapter_and_normalization",
            "expected_outcome_is_atlas_input": False,
            "metriplane_derived_results": "atlas_outputs_only",
            "operator_configured_rules": "domain_pack_only",
            "source_annotations_can_drive_incidents": False,
            "source_facts": "source.artifacts_and_field_provenance",
        },
    }


def _normalization_report(
    *,
    fixture_id: str,
    input_fingerprint: str,
    session_sha256: str,
    mapping_sha256: str,
) -> dict[str, object]:
    artifacts = {
        "entity-mapping.json": mapping_sha256,
        "session.jsonl": session_sha256,
    }
    return {
        "contract_schema_version": "metriplane.external_source_contract.v1",
        "conversion_reproducibility": {
            "comparison_policy": "sha256_byte_identity",
            "equivalent": False,
            "input_fingerprint_sha256": input_fingerprint,
            "runs": [
                {"artifacts": artifacts, "run_id": f"{fixture_id}-current-conversion"},
            ],
            "status": "not_demonstrated",
        },
        "fixture_id": fixture_id,
        "limitations": [
            "This is a position-only planar conversion: source Z and the complete source quaternion, including yaw, roll, and pitch, are discarded.",
            "Audit yaw was numerically well-defined, but no orientation is emitted or used for positions, zones, time, process rules, Atlas events, or incidents.",
            "The result does not evaluate 3D placement, grasp state, official PickCube success, physical accuracy, or simulator realism.",
            "The goal-centered polygon is wholly an operator-configured Layer-C compatibility-test rule.",
            "The source corpus was success-filtered upstream; episode selection within it was outcome-blind.",
            "The restored source goal pose is xyz=(0.026815734803676605, -0.0019813179969787598, 0.2889334559440613) with qwxyz=(1.0, 0.0, 0.0, 0.0); projected goal XY is descriptive only.",
        ],
        "normalized_frame_count": STATE_COUNT,
        "omitted_process_relevant_observations": 0,
        "operations": _normalization_operations(),
        "process_relevant_entity_count": 2,
        "result": "pass",
        "schema_version": "metriplane.external_normalization_report.v1",
        "source_record_count": STATE_COUNT,
        "unknown_process_relevant_observations": 0,
        "warnings": [],
    }


def _conversion_inputs_fingerprint(manifest: Mapping[str, Any]) -> str:
    """Mirror the frozen contract's model-dump fingerprint without importing Metriplane."""
    source_artifacts = json.loads(json.dumps(manifest["source_artifacts"]))
    for artifact in source_artifacts:
        artifact.setdefault("path", None)
        artifact.setdefault("immutable_identifier", None)
    selection = json.loads(json.dumps(manifest["selection"]))
    for key in (
        "group_path",
        "start_index",
        "end_index_exclusive",
        "start_time",
        "end_time",
        "selector",
    ):
        selection.setdefault(key, None)
    adapter = json.loads(json.dumps(manifest["adapter"]))
    adapter["environment"].setdefault("container_image_digest", None)
    adapter["parameters"].setdefault("inline", None)
    normalization = json.loads(json.dumps(manifest["normalization"]))
    mapping_path = normalization["entity_mapping"]["path"]
    normalization["entity_mapping"].pop("sha256")
    for key in ("scale", "offset", "lookup"):
        normalization["clock"].setdefault(key, None)
    normalization["coordinates"]["transform"].setdefault("parameters", None)
    normalization["coordinates"]["projection"].setdefault("parameters", None)
    normalization["completeness"].setdefault("materialization", None)
    normalization["completeness"]["carry_forward"].setdefault("max_gap_ns", None)
    confidence = normalization["confidence"]
    for key in (
        "source_field",
        "algorithm",
        "implementation",
        "parameters",
        "output_semantics",
        "placeholder_or_invented_values",
    ):
        confidence.setdefault(key, None)
    confidence.setdefault("input_fields", [])
    for declaration in normalization["field_provenance"]:
        declaration.setdefault("source_fields", [])
        declaration.setdefault("derivation", None)
        declaration.setdefault("parameter_references", [])
        declaration.setdefault("confidence_origin", None)
        for reference in declaration["parameter_references"]:
            if reference["path"] == mapping_path:
                reference.pop("sha256")
    for annotation in normalization["source_annotations"]["annotations"]:
        annotation.setdefault("retained_reference", None)
    interpolation = normalization["temporal_alignment"]["interpolation"]
    interpolation.setdefault("max_gap_ns", None)
    resampling = normalization["temporal_alignment"]["resampling"]
    resampling.setdefault("output_period_ns", None)
    resampling.setdefault("max_gap_ns", None)
    synchronization = normalization["temporal_alignment"]["synchronization"]
    synchronization.setdefault("reference_stream", None)
    synchronization.setdefault("max_skew_ns", None)
    normalization["zone_assignment"].setdefault("parameters", None)
    payload = {
        "schema_version": manifest["schema_version"],
        "contract_profile": manifest["contract_profile"],
        "source_project": manifest["source_project"],
        "source_artifacts": source_artifacts,
        "selection": selection,
        "rights": manifest["rights"],
        "adapter": adapter,
        "normalization": normalization,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _expected_outcome(variant: str, fixture_id: str) -> dict[str, object]:
    incident = variant == "incident"
    event_types = (
        [
            "required_asset_missing",
            "step_delayed",
            "required_asset_present",
            "step_completed",
        ]
        if incident
        else ["required_asset_missing", "required_asset_present", "step_completed"]
    )
    return {
        "atlas_input": False,
        "deviation_count": 1 if incident else 0,
        "event_count": len(event_types),
        "event_types": event_types,
        "evidence_bundle_verified": incident,
        "fixture_id": fixture_id,
        "frame_count": STATE_COUNT,
        "incident_count": 1 if incident else 0,
        "incident_types": ["missing_tool_caused_delay"] if incident else [],
        "regression_passed": incident,
        "role": "test_metadata_only",
        "schema_version": "metriplane.external_expected_outcome.v1",
    }


def _adapter_environment(config_sha256: str, adapter_commit: str) -> bytes:
    return (
        "adapter=maniskill-pickcube-adapter==1.0.0\n"
        f"adapter_commit={adapter_commit}\n"
        f"frozen_config_sha256={config_sha256}\n"
        "python=CPython==3.12\n"
        "operating_system=Linux\n"
        "architecture=x86_64\n"
        "mani_skill==3.0.1\n"
        "mani_skill_commit=a4a4f9272ad64b1564035874b605ceb687b63ed8\n"
        "mani_skill_wheel_sha256=685de2f03c300b1ede49881a1bf6306ad062082d39c8d3be8b8e85603f32e33a\n"
        "h5py==3.16.0\n"
        "huggingface-hub==1.27.0\n"
        "numpy==2.5.2\n"
        "PyYAML==6.0.3\n"
        "conversion_scene_dependency=software Vulkan device when required by upstream scene construction\n"
        "portable_fixture_requires_simulator=false\n"
    ).encode()


def _checksum_inventory(files: Mapping[str, bytes]) -> bytes:
    return "".join(
        f"{hashlib.sha256(data).hexdigest()}  {path}\n"
        for path, data in sorted(files.items())
        if path != "CHECKSUMS.sha256"
    ).encode("utf-8")


def _write_bytes(root: Path, files: Mapping[str, bytes]) -> None:
    for relative, data in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


_FIXTURE_FILE_INVENTORY = {
    "CHECKSUMS.sha256",
    "domain-pack/assets.yaml",
    "domain-pack/contracts.yaml",
    "domain-pack/process.yaml",
    "domain-pack/work_orders.csv",
    "domain-pack/workspace.yaml",
    "entity-mapping.json",
    "expected-outcome.json",
    "normalization-report.json",
    "session.jsonl",
    "source/adapter-environment.txt",
    "source/frozen-config.json",
    "source/uv.lock",
    "source-manifest.json",
}


def _relative_file_inventory(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def finalize_conversion_equivalence(
    conversion_roots: Sequence[str | Path],
    *,
    output_root: str | Path,
    run_ids: Sequence[str] = (
        "clean-conversion-1",
        "clean-conversion-2",
        "clean-conversion-3",
    ),
    overwrite: bool = False,
) -> dict[str, object]:
    """Finalize three independently generated, byte-identical conversion roots."""
    if len(conversion_roots) != 3:
        raise AdapterError("conversion equivalence: exactly three clean roots are required")
    if len(run_ids) != 3 or len(set(run_ids)) != 3 or any(not value.strip() for value in run_ids):
        raise AdapterError("conversion equivalence: exactly three unique nonblank run IDs required")
    roots = [Path(value).resolve() for value in conversion_roots]
    if len(set(roots)) != 3:
        raise AdapterError("conversion equivalence: roots must be three distinct directories")
    output = Path(output_root).resolve()
    for root in roots:
        if not root.is_dir():
            raise AdapterError(f"conversion equivalence root {root}: directory not found")
        if output == root or output in root.parents or root in output.parents:
            raise AdapterError(
                f"conversion equivalence output/root overlap: {output} and {root} must be disjoint"
            )
    if output.exists() and not overwrite:
        raise AdapterError(f"conversion equivalence output {output}: already exists; pass --overwrite")

    compared: dict[str, str] = {}
    for variant in ("incident", "control"):
        variant_roots = [root / variant for root in roots]
        for variant_root in variant_roots:
            inventory = _relative_file_inventory(variant_root)
            if inventory != _FIXTURE_FILE_INVENTORY:
                missing = sorted(_FIXTURE_FILE_INVENTORY - inventory)
                extra = sorted(inventory - _FIXTURE_FILE_INVENTORY)
                raise AdapterError(
                    f"conversion equivalence {variant_root}: file inventory mismatch; "
                    f"missing={missing}, extra={extra}"
                )
        for relative in sorted(_FIXTURE_FILE_INVENTORY):
            values = [(root / variant / relative).read_bytes() for root in roots]
            if values[0] != values[1] or values[0] != values[2]:
                raise AdapterError(
                    f"conversion equivalence {variant}/{relative}: bytes differ across roots"
                )
            compared[f"{variant}/{relative}"] = hashlib.sha256(values[0]).hexdigest()
    summaries = [(root / "conversion-summary.json").read_bytes() for root in roots]
    if summaries[0] != summaries[1] or summaries[0] != summaries[2]:
        raise AdapterError(
            "conversion equivalence conversion-summary.json: bytes differ across roots"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        shutil.copytree(roots[0], stage, dirs_exist_ok=True)
        # Contract v1 intentionally records only Stage 1 outputs per conversion run.
        # The finalizer has already compared the full inventories above.
        reproducibility_paths = ["entity-mapping.json", "session.jsonl"]
        fixture_fingerprints: dict[str, str] = {}
        for variant in ("incident", "control"):
            variant_root = stage / variant
            report_path = variant_root / "normalization-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            runs = []
            for index, run_id in enumerate(run_ids):
                source_root = roots[index] / variant
                runs.append(
                    {
                        "artifacts": {
                            relative: sha256_file(source_root / relative)
                            for relative in reproducibility_paths
                        },
                        "run_id": run_id,
                    }
                )
            report["conversion_reproducibility"].update(
                {"equivalent": True, "runs": runs, "status": "demonstrated"}
            )
            report_path.write_bytes(pretty_json_bytes(report))

            manifest_path = variant_root / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["normalized_artifacts"]["normalization_report"]["sha256"] = sha256_file(
                report_path
            )
            manifest_path.write_bytes(pretty_json_bytes(manifest))
            fixture_files = {
                relative: (variant_root / relative).read_bytes()
                for relative in _FIXTURE_FILE_INVENTORY
                if relative != "CHECKSUMS.sha256"
            }
            checksum_bytes = _checksum_inventory(fixture_files)
            (variant_root / "CHECKSUMS.sha256").write_bytes(checksum_bytes)
            fixture_fingerprints[variant] = hashlib.sha256(checksum_bytes).hexdigest()

        summary = json.loads((stage / "conversion-summary.json").read_text(encoding="utf-8"))
        summary["conversion_reproducibility"] = {
            "comparison_policy": "sha256_byte_identity",
            "equivalent": True,
            "run_ids": list(run_ids),
            "status": "demonstrated",
        }
        for variant, fingerprint in fixture_fingerprints.items():
            summary[variant]["fixture_fingerprint_sha256"] = fingerprint
        (stage / "conversion-summary.json").write_bytes(pretty_json_bytes(summary))
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                raise AdapterError(
                    f"conversion equivalence output {output}: refusing non-directory replacement"
                )
            shutil.rmtree(output)
        stage.replace(output)
        return {
            "compared_artifact_count": len(compared),
            "control_fixture_fingerprint_sha256": fixture_fingerprints["control"],
            "equivalent": True,
            "incident_fixture_fingerprint_sha256": fixture_fingerprints["incident"],
            "output_root": str(output),
            "run_ids": list(run_ids),
            "schema_version": "org.metriplane.maniskill_pickcube.equivalence.v1",
        }
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def write_fixtures(
    restored_frames: Sequence[RestoredFrame],
    *,
    config_path: str | Path,
    output_root: str | Path,
    adapter_commit: str,
    overwrite: bool = False,
) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{40}", adapter_commit) is None:
        raise AdapterError("adapter commit: expected one exact lowercase 40-hex freeze commit")
    config_path = Path(config_path).resolve()
    output_path = Path(output_root).resolve()
    for semantic_input in (config_path, DEFAULT_LOCK.resolve()):
        if (
            output_path == semantic_input
            or output_path in semantic_input.parents
            or semantic_input in output_path.parents
        ):
            raise AdapterError(
                f"output/input overlap: output {output_path} and input {semantic_input} "
                "must be disjoint"
            )
    config = load_config(config_path)
    config_sha256 = sha256_file(config_path)
    first_session, accounting = normalize_frames(restored_frames, config)
    # Repeat the pure conversion step to fail closed on hidden mutable conversion state.
    repeated_sessions = [normalize_frames(restored_frames, config)[0] for _ in range(2)]
    if any(value != first_session for value in repeated_sessions):
        raise AdapterError("normalization determinism: repeated session bytes differ")
    session_sha256 = hashlib.sha256(first_session).hexdigest()
    mapping_bytes = pretty_json_bytes(_entity_mapping())
    mapping_sha256 = hashlib.sha256(mapping_bytes).hexdigest()
    if output_path.exists() and not overwrite:
        raise AdapterError(f"output {output_path}: already exists; pass --overwrite explicitly")
    parent = output_path.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.stage-", dir=parent))
    try:
        summaries: dict[str, object] = {}
        shared_environment = _adapter_environment(config_sha256, adapter_commit)
        frozen_config_bytes = config_path.read_bytes()
        if not DEFAULT_LOCK.is_file():
            raise AdapterError(f"adapter dependency lock {DEFAULT_LOCK}: missing")
        lock_bytes = DEFAULT_LOCK.read_bytes()
        for variant in ("incident", "control"):
            variant_config = config["variants"][variant]
            fixture_id = str(variant_config["fixture_id"])
            files: dict[str, bytes] = {
                "session.jsonl": first_session,
                "entity-mapping.json": mapping_bytes,
                "source/adapter-environment.txt": shared_environment,
                "source/frozen-config.json": frozen_config_bytes,
                "source/uv.lock": lock_bytes,
                **_domain_pack_files(config, float(variant_config["max_wait_s"])),
            }
            files["expected-outcome.json"] = pretty_json_bytes(
                _expected_outcome(variant, fixture_id)
            )
            files["normalization-report.json"] = pretty_json_bytes(
                _normalization_report(
                    fixture_id=fixture_id,
                    input_fingerprint="0" * 64,
                    session_sha256=session_sha256,
                    mapping_sha256=mapping_sha256,
                )
            )
            manifest = _manifest(
                config=config,
                variant=variant,
                adapter_commit=adapter_commit,
                files=files,
                config_sha256=config_sha256,
                session_sha256=session_sha256,
            )
            input_fingerprint = _conversion_inputs_fingerprint(manifest)
            files["normalization-report.json"] = pretty_json_bytes(
                _normalization_report(
                    fixture_id=fixture_id,
                    input_fingerprint=input_fingerprint,
                    session_sha256=session_sha256,
                    mapping_sha256=mapping_sha256,
                )
            )
            files["source-manifest.json"] = pretty_json_bytes(
                _manifest(
                    config=config,
                    variant=variant,
                    adapter_commit=adapter_commit,
                    files=files,
                    config_sha256=config_sha256,
                    session_sha256=session_sha256,
                )
            )
            files["CHECKSUMS.sha256"] = _checksum_inventory(files)
            variant_root = stage / variant
            _write_bytes(variant_root, files)
            fixture_fingerprint = hashlib.sha256(files["CHECKSUMS.sha256"]).hexdigest()
            summaries[variant] = {
                "fixture_fingerprint_sha256": fixture_fingerprint,
                "fixture_id": fixture_id,
                "max_wait_s": variant_config["max_wait_s"],
            }
        summary = {
            "adapter_commit": adapter_commit,
            "config_sha256": config_sha256,
            "control": summaries["control"],
            "incident": summaries["incident"],
            "pose_stream_sha256": POSE_STREAM_SHA256,
            "schema_version": "org.metriplane.maniskill_pickcube.conversion_summary.v1",
            "shared_session_sha256": session_sha256,
            "source_sha256": {
                "trajectory_hdf5": HDF5_SHA256,
                "trajectory_json": JSON_SHA256,
            },
            **accounting,
        }
        (stage / "conversion-summary.json").write_bytes(pretty_json_bytes(summary))
        if output_path.exists():
            if output_path.is_symlink() or not output_path.is_dir():
                raise AdapterError(f"output {output_path}: refusing to replace non-directory")
            shutil.rmtree(output_path)
        stage.replace(output_path)
        return summary
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def convert(
    trajectory: str | Path,
    metadata: str | Path,
    *,
    config_path: str | Path,
    output_root: str | Path,
    adapter_commit: str,
    overwrite: bool = False,
    restorer: Callable[[str | Path, str | Path], tuple[list[RestoredFrame], dict[str, object]]] = restore_named_poses,
) -> dict[str, object]:
    trajectory_path = Path(trajectory).resolve()
    metadata_path = Path(metadata).resolve()
    output_path = Path(output_root).resolve()
    for source_path in (trajectory_path, metadata_path):
        if output_path == source_path or output_path in source_path.parents or source_path in output_path.parents:
            raise AdapterError(
                f"output/source overlap: output {output_path} and source {source_path} must be disjoint"
            )
    _verify_file(trajectory_path, label="trajectory HDF5", size=HDF5_SIZE, sha256=HDF5_SHA256)
    _verify_file(metadata_path, label="trajectory metadata JSON", size=JSON_SIZE, sha256=JSON_SHA256)
    before = {
        trajectory_path: (trajectory_path.stat().st_size, sha256_file(trajectory_path)),
        metadata_path: (metadata_path.stat().st_size, sha256_file(metadata_path)),
    }
    restored_frames, restoration = restorer(trajectory_path, metadata_path)
    summary = write_fixtures(
        restored_frames,
        config_path=config_path,
        output_root=output_path,
        adapter_commit=adapter_commit,
        overwrite=overwrite,
    )
    after = {
        path: (path.stat().st_size, sha256_file(path)) for path in (trajectory_path, metadata_path)
    }
    if before != after:
        raise AdapterError("source mutation: HDF5 or JSON bytes changed during conversion")
    summary["restoration"] = restoration
    return summary


def _safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    seen: set[str] = set()
    for member in archive.infolist():
        name = member.filename
        pure = PurePosixPath(name)
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or any(part in ("", ".", "..") for part in pure.parts)
        ):
            raise AdapterError(f"archive member {name!r}: unsafe path")
        normalized = pure.as_posix().rstrip("/")
        if normalized in seen:
            raise AdapterError(f"archive member {name!r}: duplicate path")
        seen.add(normalized)
        mode = (member.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise AdapterError(f"archive member {name!r}: source symlink is prohibited")
        members.append(member)
    return members


def acquire(
    output_root: str | Path,
    *,
    overwrite: bool = False,
    downloaded_archive: str | Path | None = None,
) -> dict[str, object]:
    output = Path(output_root).resolve()
    if output.exists() and not overwrite:
        raise AdapterError(f"acquisition output {output}: already exists; pass --overwrite")
    if downloaded_archive is None:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise AdapterError("acquisition requires huggingface-hub==1.27.0") from exc
        downloaded_archive = hf_hub_download(
            repo_id=DATASET_REPOSITORY,
            repo_type="dataset",
            revision=DATASET_REVISION,
            filename=ARCHIVE_REPOSITORY_PATH,
        )
    source_archive = Path(downloaded_archive).resolve()
    if (
        output == source_archive
        or output in source_archive.parents
        or source_archive in output.parents
    ):
        raise AdapterError(
            f"acquisition output/archive overlap: {output} and {source_archive} must be disjoint"
        )
    _verify_file(source_archive, label="source ZIP", size=ARCHIVE_SIZE, sha256=ARCHIVE_SHA256)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        archive_copy = stage / "PickCube-v1.zip"
        shutil.copyfile(source_archive, archive_copy)
        extracted = stage / "extracted"
        extracted.mkdir()
        try:
            with zipfile.ZipFile(archive_copy) as archive:
                members = _safe_zip_members(archive)
                for member in members:
                    destination = extracted.joinpath(*PurePosixPath(member.filename).parts)
                    destination_parent = destination.parent
                    destination_parent.mkdir(parents=True, exist_ok=True)
                    if member.is_dir():
                        destination.mkdir(exist_ok=True)
                    else:
                        with archive.open(member) as source, destination.open("xb") as target:
                            shutil.copyfileobj(source, target)
        except (OSError, zipfile.BadZipFile) as exc:
            raise AdapterError(f"source ZIP {archive_copy}: safe extraction failed: {exc}") from exc
        candidates = [
            (
                extracted / "demos/PickCube-v1/motionplanning/trajectory.h5",
                extracted / "demos/PickCube-v1/motionplanning/trajectory.json",
            ),
            (
                extracted / "PickCube-v1/motionplanning/trajectory.h5",
                extracted / "PickCube-v1/motionplanning/trajectory.json",
            ),
        ]
        selected = next(((h5, js) for h5, js in candidates if h5.is_file() and js.is_file()), None)
        if selected is None:
            raise AdapterError("source ZIP: missing PickCube-v1 motionplanning HDF5/JSON members")
        hdf5_path, json_path = selected
        _verify_file(hdf5_path, label="extracted trajectory HDF5", size=HDF5_SIZE, sha256=HDF5_SHA256)
        _verify_file(json_path, label="extracted trajectory JSON", size=JSON_SIZE, sha256=JSON_SHA256)
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                raise AdapterError(f"acquisition output {output}: refusing non-directory replacement")
            shutil.rmtree(output)
        stage.replace(output)
        relative_hdf5 = hdf5_path.relative_to(stage).as_posix()
        relative_json = json_path.relative_to(stage).as_posix()
        return {
            "archive": str(output / "PickCube-v1.zip"),
            "archive_sha256": ARCHIVE_SHA256,
            "dataset_revision": DATASET_REVISION,
            "metadata": str(output / relative_json),
            "trajectory": str(output / relative_hdf5),
        }
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
