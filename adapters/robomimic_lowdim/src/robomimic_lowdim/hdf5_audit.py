# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Fail-closed raw/prepared correspondence and named-state witnesses.

This module intentionally knows one robomimic dataset shape. It is not a general
HDF5 importer and never reconstructs state from actions or ``next_obs``.
"""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from .constants import (
    CONTROL_FREQUENCY_HZ,
    DEMO_ID,
    EXPECTED_PREPARED_OBS_KEYS,
    FRAME_COUNT,
    PREPARED_SHA256,
    PREPARED_SIZE,
    RAW_SHA256,
    RAW_SIZE,
)


class SourceAuditError(RuntimeError):
    """Raised when pinned source bytes or semantics fail a closed gate."""


def reject_symlink_components(path: str | Path, *, label: str) -> Path:
    """Reject a symlink in any existing component before canonical resolution."""
    supplied = Path(path).absolute()
    current = Path(supplied.anchor)
    for part in supplied.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise SourceAuditError(f"{label}: symlink path component is prohibited: {current}")
        if not current.exists():
            break
    return supplied


@dataclass(frozen=True)
class SourceFrame:
    """The only two named prepared world-position observations consumed."""

    can_xyz: tuple[float, float, float]
    tcp_xyz: tuple[float, float, float]


@dataclass(frozen=True)
class AuditResult:
    frames: tuple[SourceFrame, ...]
    report: dict[str, Any]


_RAW_DEMO_KEYS = {
    "actions",
    "controller_info",
    "interventions",
    "policy_acting",
    "states",
    "user_acting",
    "user_info",
}
_PREPARED_DEMO_KEYS = {"actions", "dones", "next_obs", "obs", "rewards", "states"}
_QPOS_WIDTH = {"hinge": 1, "slide": 1, "ball": 4, "free": 7}
_QVEL_WIDTH = {"hinge": 1, "slide": 1, "ball": 3, "free": 6}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_source_file(
    path: str | Path, *, label: str, expected_size: int, expected_sha256: str
) -> Path:
    supplied = reject_symlink_components(path, label=label)
    if supplied.is_symlink() or not supplied.is_file():
        raise SourceAuditError(f"{label}: expected a regular, non-symlink file: {supplied}")
    source = supplied.resolve()
    size = source.stat().st_size
    if size != expected_size:
        raise SourceAuditError(f"{label}: size mismatch; expected {expected_size}, got {size}")
    actual = sha256_file(source)
    if actual != expected_sha256:
        raise SourceAuditError(
            f"{label}: SHA-256 mismatch; expected {expected_sha256}, computed {actual}"
        )
    return source


def _demo_sort_key(name: str) -> tuple[int, str]:
    if not name.startswith("demo_") or not name[5:].isdigit():
        raise SourceAuditError(f"unexpected demo name: {name!r}")
    return int(name[5:]), name


def _array_identity(left: h5py.Dataset, right: h5py.Dataset, *, label: str) -> None:
    if not isinstance(left, h5py.Dataset) or not isinstance(right, h5py.Dataset):
        raise SourceAuditError(f"{label}: expected datasets")
    if left.shape != right.shape or left.dtype != right.dtype:
        raise SourceAuditError(
            f"{label}: shape/dtype mismatch {left.shape}/{left.dtype} != "
            f"{right.shape}/{right.dtype}"
        )
    left_value = left[...]
    right_value = right[...]
    if left_value.tobytes(order="C") != right_value.tobytes(order="C"):
        raise SourceAuditError(f"{label}: array bytes differ")


def _attribute_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, np.generic):
        return value.tobytes()
    return repr(value).encode("utf-8")


def _attribute_identity(left: h5py.Group, right: h5py.Group, name: str, *, label: str) -> None:
    left_present = name in left.attrs
    right_present = name in right.attrs
    if left_present != right_present:
        raise SourceAuditError(f"{label}: attribute {name!r} presence differs")
    if left_present and _attribute_bytes(left.attrs[name]) != _attribute_bytes(right.attrs[name]):
        raise SourceAuditError(f"{label}: attribute {name!r} differs")


def _as_text(value: object, *, label: str) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceAuditError(f"{label}: not UTF-8") from exc
    if isinstance(value, str):
        return value
    raise SourceAuditError(f"{label}: expected text, got {type(value).__name__}")


def _finite(array: np.ndarray, *, label: str) -> None:
    if not np.issubdtype(array.dtype, np.number):
        raise SourceAuditError(f"{label}: expected numeric dtype, got {array.dtype}")
    if not np.isfinite(array).all():
        raise SourceAuditError(f"{label}: contains a nonfinite value")


def _vector(value: str | None, default: Iterable[float], *, label: str) -> np.ndarray:
    if value is None:
        result = np.asarray(tuple(default), dtype=np.float64)
    else:
        try:
            result = np.asarray([float(item) for item in value.split()], dtype=np.float64)
        except ValueError as exc:
            raise SourceAuditError(f"{label}: malformed numeric vector") from exc
    if not np.isfinite(result).all():
        raise SourceAuditError(f"{label}: nonfinite numeric vector")
    return result


def _quaternion_matrix(quaternion: np.ndarray, *, label: str) -> np.ndarray:
    if quaternion.shape != (4,):
        raise SourceAuditError(f"{label}: expected wxyz quaternion")
    norm = float(np.linalg.norm(quaternion))
    if not math.isfinite(norm) or norm == 0.0:
        raise SourceAuditError(f"{label}: invalid quaternion")
    w, x, y, z = quaternion / norm
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _axis_rotation(axis: np.ndarray, angle: float, *, label: str) -> np.ndarray:
    if axis.shape != (3,):
        raise SourceAuditError(f"{label}: expected a three-component axis")
    norm = float(np.linalg.norm(axis))
    if not math.isfinite(norm) or norm == 0.0:
        raise SourceAuditError(f"{label}: invalid joint axis")
    x, y, z = axis / norm
    cosine = math.cos(angle)
    sine = math.sin(angle)
    complement = 1.0 - cosine
    return np.asarray(
        [
            [
                cosine + x * x * complement,
                x * y * complement - z * sine,
                x * z * complement + y * sine,
            ],
            [
                y * x * complement + z * sine,
                cosine + y * y * complement,
                y * z * complement - x * sine,
            ],
            [
                z * x * complement - y * sine,
                z * y * complement + x * sine,
                cosine + z * z * complement,
            ],
        ],
        dtype=np.float64,
    )


@dataclass(frozen=True)
class _Joint:
    name: str
    kind: str
    qpos_address: int
    position: np.ndarray
    axis: np.ndarray


@dataclass(frozen=True)
class _Body:
    name: str
    position: np.ndarray
    rotation: np.ndarray
    joints: tuple[_Joint, ...]


@dataclass(frozen=True)
class _ModelWitness:
    nq: int
    nv: int
    can_qpos_address: int
    site_position: np.ndarray
    site_chain: tuple[_Body, ...]


def _compile_model(xml_text: str) -> _ModelWitness:
    uppercase_xml = xml_text.upper()
    if "<!DOCTYPE" in uppercase_xml or "<!ENTITY" in uppercase_xml:
        raise SourceAuditError("model_file: DTD/entity declarations are prohibited")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceAuditError(f"model_file: malformed XML: {exc}") from exc
    worldbody = root.find("worldbody")
    if worldbody is None:
        raise SourceAuditError("model_file: missing worldbody")

    qpos_addresses: dict[int, int] = {}
    qpos_address = 0
    qvel_address = 0
    can_address: int | None = None
    can_count = 0
    for joint in worldbody.iter("joint"):
        kind = joint.get("type", "hinge")
        if kind not in _QPOS_WIDTH:
            raise SourceAuditError(f"model_file: unsupported joint type {kind!r}")
        qpos_addresses[id(joint)] = qpos_address
        if joint.get("name") == "Can_joint0":
            can_count += 1
            if kind != "free":
                raise SourceAuditError("model_file: Can_joint0 is not a free joint")
            can_address = qpos_address
        qpos_address += _QPOS_WIDTH[kind]
        qvel_address += _QVEL_WIDTH[kind]
    if can_count != 1 or can_address is None:
        raise SourceAuditError("model_file: expected exactly one named Can_joint0")

    found_chains: list[tuple[list[ET.Element], ET.Element]] = []

    def visit(body: ET.Element, ancestors: list[ET.Element]) -> None:
        chain = [*ancestors, body]
        for site in body.findall("site"):
            if site.get("name") == "gripper0_right_grip_site":
                found_chains.append((chain, site))
        for child in body.findall("body"):
            visit(child, chain)

    for body in worldbody.findall("body"):
        visit(body, [])
    if len(found_chains) != 1:
        raise SourceAuditError("model_file: expected exactly one named gripper0_right_grip_site")
    chain_elements, site = found_chains[0]
    if any(site.get(name) is not None for name in ("euler", "axisangle", "xyaxes", "zaxis")):
        raise SourceAuditError("model_file: unsupported site orientation encoding")
    site_position = _vector(site.get("pos"), (0.0, 0.0, 0.0), label="site pos")
    if site_position.shape != (3,):
        raise SourceAuditError("model_file: site pos must have three components")

    compiled_bodies: list[_Body] = []
    for body in chain_elements:
        if any(body.get(name) is not None for name in ("euler", "axisangle", "xyaxes", "zaxis")):
            raise SourceAuditError(
                f"model_file: unsupported orientation encoding on body {body.get('name')!r}"
            )
        position = _vector(body.get("pos"), (0.0, 0.0, 0.0), label="body pos")
        quaternion = _vector(body.get("quat"), (1.0, 0.0, 0.0, 0.0), label="body quat")
        if position.shape != (3,) or quaternion.shape != (4,):
            raise SourceAuditError("model_file: malformed body pose")
        compiled_joints: list[_Joint] = []
        for joint in body.findall("joint"):
            kind = joint.get("type", "hinge")
            if kind not in {"hinge", "slide"}:
                raise SourceAuditError(
                    "model_file: TCP ancestry contains unsupported free/ball joint"
                )
            joint_position = _vector(joint.get("pos"), (0.0, 0.0, 0.0), label="joint pos")
            axis = _vector(joint.get("axis"), (0.0, 0.0, 1.0), label="joint axis")
            if joint_position.shape != (3,) or axis.shape != (3,):
                raise SourceAuditError("model_file: malformed joint geometry")
            compiled_joints.append(
                _Joint(
                    name=joint.get("name", ""),
                    kind=kind,
                    qpos_address=qpos_addresses[id(joint)],
                    position=joint_position,
                    axis=axis,
                )
            )
        compiled_bodies.append(
            _Body(
                name=body.get("name", ""),
                position=position,
                rotation=_quaternion_matrix(quaternion, label="body quat"),
                joints=tuple(compiled_joints),
            )
        )
    return _ModelWitness(
        nq=qpos_address,
        nv=qvel_address,
        can_qpos_address=can_address,
        site_position=site_position,
        site_chain=tuple(compiled_bodies),
    )


def _forward_kinematics(model: _ModelWitness, qpos: np.ndarray) -> np.ndarray:
    output = np.empty((qpos.shape[0], 3), dtype=np.float64)
    for row_index, row in enumerate(qpos):
        position = np.zeros(3, dtype=np.float64)
        rotation = np.eye(3, dtype=np.float64)
        for body in model.site_chain:
            position = position + rotation @ body.position
            rotation = rotation @ body.rotation
            for joint in body.joints:
                value = float(row[joint.qpos_address])
                if joint.kind == "hinge":
                    dynamic = _axis_rotation(joint.axis, value, label=joint.name)
                    position = position + rotation @ (joint.position - dynamic @ joint.position)
                    rotation = rotation @ dynamic
                elif joint.kind == "slide":
                    position = position + rotation @ (joint.axis * value)
                else:  # pragma: no cover - model compilation excludes this
                    raise AssertionError(joint.kind)
        output[row_index] = position + rotation @ model.site_position
    return output


def _environment_metadata(data: h5py.Group, *, label: str) -> dict[str, Any]:
    if "env_args" not in data.attrs:
        raise SourceAuditError(f"{label}: missing data.attrs.env_args")
    try:
        value = json.loads(_as_text(data.attrs["env_args"], label=f"{label} env_args"))
    except json.JSONDecodeError as exc:
        raise SourceAuditError(f"{label}: malformed env_args JSON") from exc
    if not isinstance(value, dict):
        raise SourceAuditError(f"{label}: env_args is not an object")
    return value


def _validate_environment(raw_data: h5py.Group, prepared_data: h5py.Group) -> dict[str, Any]:
    raw = _environment_metadata(raw_data, label="raw")
    prepared = _environment_metadata(prepared_data, label="prepared")
    for label, value, version in (
        ("raw", raw, "1.5.0"),
        ("prepared", prepared, "1.5.1"),
    ):
        if value.get("env_name") != "PickPlaceCan" or value.get("env_version") != version:
            raise SourceAuditError(f"{label}: expected PickPlaceCan environment version {version}")
        kwargs = value.get("env_kwargs")
        if not isinstance(kwargs, dict) or kwargs.get("control_freq") != CONTROL_FREQUENCY_HZ:
            raise SourceAuditError(f"{label}: expected explicit control_freq=20")
        if kwargs.get("ignore_done") is not True:
            raise SourceAuditError(f"{label}: expected explicit ignore_done=true")
        controller = kwargs.get("controller_configs")
        if not isinstance(controller, dict):
            raise SourceAuditError(f"{label}: missing controller_configs")
        body_parts = controller.get("body_parts")
        right = body_parts.get("right") if isinstance(body_parts, dict) else None
        if not isinstance(right, dict) or right.get("type") != "OSC_POSE":
            raise SourceAuditError(f"{label}: expected named right-arm OSC_POSE controller")
        if right.get("input_ref_frame") != "world":
            raise SourceAuditError(f"{label}: expected explicit controller input_ref_frame=world")
    return {
        "control_frequency_hz": CONTROL_FREQUENCY_HZ,
        "prepared_environment_version": "1.5.1",
        "raw_environment_version": "1.5.0",
        "controller": "OSC_POSE",
        "controller_input_ref_frame": "world",
        "ignore_done": True,
        "task": "PickPlaceCan",
    }


def compare_raw_prepared(
    raw_path: str | Path,
    prepared_path: str | Path,
    *,
    verify_identity: bool = True,
    selected_demo: str = DEMO_ID,
    expected_frame_count: int | None = FRAME_COUNT,
    expected_demo_count: int = 200,
    expected_total_samples: int = 23_207,
) -> AuditResult:
    """Prove correspondence and return only the selected named observation rows.

    ``verify_identity=False`` exists solely for source-shaped unit tests. The public CLI
    and :func:`convert` always verify exact source size and SHA-256.
    """

    raw_supplied = reject_symlink_components(raw_path, label="raw")
    prepared_supplied = reject_symlink_components(prepared_path, label="prepared")
    if raw_supplied.is_symlink() or prepared_supplied.is_symlink():
        raise SourceAuditError("raw/prepared: source symlinks are prohibited")
    raw = raw_supplied.resolve()
    prepared = prepared_supplied.resolve()
    if raw == prepared:
        raise SourceAuditError("raw/prepared: paths must be distinct")
    if verify_identity:
        verify_source_file(
            raw, label="raw HDF5", expected_size=RAW_SIZE, expected_sha256=RAW_SHA256
        )
        verify_source_file(
            prepared,
            label="prepared HDF5",
            expected_size=PREPARED_SIZE,
            expected_sha256=PREPARED_SHA256,
        )
    else:
        for label, path in (("raw", raw_supplied), ("prepared", prepared_supplied)):
            if path.is_symlink() or not path.is_file():
                raise SourceAuditError(f"{label}: expected regular, non-symlink HDF5")

    first_mismatch: str | None = None
    model_cache: dict[str, _ModelWitness] = {}
    max_fk_error = 0.0
    can_rows = 0
    clock_rows = 0
    selected_frames: tuple[SourceFrame, ...] | None = None
    demo_reports: list[dict[str, Any]] = []
    try:
        with h5py.File(raw, "r") as raw_file, h5py.File(prepared, "r") as prepared_file:

            def reject_links(group: h5py.Group, *, label: str) -> None:
                unsafe: list[str] = []

                def visitor(name: str, link: h5py.HardLink) -> None:
                    if not isinstance(link, h5py.HardLink):
                        unsafe.append(name)

                group.visititems_links(visitor)
                if unsafe:
                    raise SourceAuditError(
                        f"{label}: HDF5 soft/external link is prohibited at {unsafe[0]}"
                    )

            def reject_unsafe_dataset_storage(group: h5py.Group, *, label: str) -> None:
                unsafe: list[str] = []

                def visitor(name: str, item: h5py.Group | h5py.Dataset) -> None:
                    if not isinstance(item, h5py.Dataset):
                        return
                    creation = item.id.get_create_plist()
                    if creation.get_nfilters() != 0:
                        unsafe.append(f"{name}: filters")
                    if creation.get_external_count() != 0:
                        unsafe.append(f"{name}: external storage")
                    if creation.get_layout() == h5py.h5d.VIRTUAL:
                        unsafe.append(f"{name}: virtual dataset")

                group.visititems(visitor)
                if unsafe:
                    raise SourceAuditError(
                        f"{label}: unsafe HDF5 dataset storage is prohibited at {unsafe[0]}"
                    )

            reject_links(raw_file, label="raw")
            reject_links(prepared_file, label="prepared")
            reject_unsafe_dataset_storage(raw_file, label="raw")
            reject_unsafe_dataset_storage(prepared_file, label="prepared")
            if set(raw_file.keys()) != {"data", "mask"}:
                raise SourceAuditError(f"raw: unexpected root keys {sorted(raw_file.keys())}")
            if set(prepared_file.keys()) != {"data", "mask"}:
                raise SourceAuditError(
                    f"prepared: unexpected root keys {sorted(prepared_file.keys())}"
                )
            raw_data = raw_file["data"]
            prepared_data = prepared_file["data"]
            if not isinstance(raw_data, h5py.Group) or not isinstance(prepared_data, h5py.Group):
                raise SourceAuditError("raw/prepared data nodes must be groups")
            environment = _validate_environment(raw_data, prepared_data)
            if int(raw_data.attrs.get("total", -1)) != int(prepared_data.attrs.get("total", -2)):
                raise SourceAuditError("data.attrs.total differs")
            demos = sorted(raw_data.keys(), key=_demo_sort_key)
            prepared_demos = sorted(prepared_data.keys(), key=_demo_sort_key)
            if demos != prepared_demos:
                raise SourceAuditError("raw/prepared demo name sets differ")
            expected_demos = [f"demo_{index}" for index in range(expected_demo_count)]
            if demos != expected_demos:
                raise SourceAuditError("expected exact contiguous demo_0 through demo_199 set")
            if selected_demo not in demos:
                raise SourceAuditError(f"selected demo missing: {selected_demo}")

            raw_mask = raw_file["mask"]
            prepared_mask = prepared_file["mask"]
            if not isinstance(raw_mask, h5py.Group) or not isinstance(prepared_mask, h5py.Group):
                raise SourceAuditError("raw/prepared mask nodes must be groups")
            if set(raw_mask.keys()) != set(prepared_mask.keys()):
                raise SourceAuditError("raw/prepared mask key sets differ")
            for mask_name in sorted(raw_mask.keys()):
                _array_identity(
                    raw_mask[mask_name],
                    prepared_mask[mask_name],
                    label=f"mask/{mask_name}",
                )
                if raw_mask[mask_name].ndim != 1:
                    raise SourceAuditError(f"mask/{mask_name}: expected one-dimensional dataset")
                members = raw_mask[mask_name][...]
                for member in members:
                    name = _as_text(member, label=f"mask/{mask_name} member")
                    if name not in raw_data or name not in prepared_data:
                        raise SourceAuditError(
                            f"mask/{mask_name}: member {name!r} does not resolve in both files"
                        )

            for demo_name in demos:
                raw_demo = raw_data[demo_name]
                prepared_demo = prepared_data[demo_name]
                if not isinstance(raw_demo, h5py.Group) or not isinstance(
                    prepared_demo, h5py.Group
                ):
                    raise SourceAuditError(f"{demo_name}: demo nodes must be groups")
                if set(raw_demo.keys()) != _RAW_DEMO_KEYS:
                    raise SourceAuditError(
                        f"raw data/{demo_name}: unexpected keys {sorted(raw_demo.keys())}"
                    )
                if set(prepared_demo.keys()) != _PREPARED_DEMO_KEYS:
                    raise SourceAuditError(
                        f"prepared data/{demo_name}: unexpected keys {sorted(prepared_demo.keys())}"
                    )
                _attribute_identity(raw_demo, prepared_demo, "model_file", label=demo_name)
                _attribute_identity(raw_demo, prepared_demo, "ep_meta", label=demo_name)
                raw_count = int(raw_demo.attrs.get("num_samples", -1))
                prepared_count = int(prepared_demo.attrs.get("num_samples", -2))
                if raw_count != prepared_count or raw_count <= 0:
                    raise SourceAuditError(f"{demo_name}: num_samples differs or is invalid")
                _array_identity(
                    raw_demo["states"], prepared_demo["states"], label=f"{demo_name}/states"
                )
                raw_actions = raw_demo["actions"]
                prepared_actions = prepared_demo["actions"]
                if not isinstance(raw_actions, h5py.Dataset) or not isinstance(
                    prepared_actions, h5py.Dataset
                ):
                    raise SourceAuditError(f"{demo_name}/actions: expected datasets")
                if raw_actions.shape != (raw_count, 7) or raw_actions.dtype != np.dtype("float64"):
                    raise SourceAuditError(
                        f"{demo_name}/actions: expected ({raw_count}, 7) float64"
                    )
                _array_identity(raw_actions, prepared_actions, label=f"{demo_name}/actions")
                states = raw_demo["states"][...]
                _finite(states, label=f"raw data/{demo_name}/states")
                if states.ndim != 2 or states.shape[0] != raw_count:
                    raise SourceAuditError(f"{demo_name}: states shape does not match num_samples")
                expected_time = np.arange(raw_count, dtype=np.float64) / CONTROL_FREQUENCY_HZ
                clock_error = float(np.max(np.abs(states[:, 0] - expected_time)))
                if clock_error > 1e-12:
                    raise SourceAuditError(
                        f"{demo_name}: raw state time is not one 20 Hz control step per row; "
                        f"max error {clock_error}"
                    )
                clock_rows += raw_count

                xml_text = _as_text(raw_demo.attrs["model_file"], label=f"{demo_name} model_file")
                model_hash = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()
                model = model_cache.setdefault(model_hash, _compile_model(xml_text))
                if states.shape[1] != 1 + model.nq + model.nv:
                    raise SourceAuditError(
                        f"{demo_name}: state width {states.shape[1]} != time+nq+nv "
                        f"({1 + model.nq + model.nv})"
                    )
                qpos = states[:, 1 : 1 + model.nq]
                obs = prepared_demo["obs"]
                next_obs = prepared_demo["next_obs"]
                if not isinstance(obs, h5py.Group) or not isinstance(next_obs, h5py.Group):
                    raise SourceAuditError(f"{demo_name}: obs/next_obs must be groups")
                if set(obs.keys()) != EXPECTED_PREPARED_OBS_KEYS:
                    raise SourceAuditError(f"{demo_name}/obs: unexpected keys {sorted(obs.keys())}")
                if set(next_obs.keys()) != EXPECTED_PREPARED_OBS_KEYS:
                    raise SourceAuditError(
                        f"{demo_name}/next_obs: unexpected keys {sorted(next_obs.keys())}"
                    )
                object_dataset = obs["object"]
                tcp_dataset = obs["robot0_eef_pos"]
                if not isinstance(object_dataset, h5py.Dataset) or not isinstance(
                    tcp_dataset, h5py.Dataset
                ):
                    raise SourceAuditError(
                        f"{demo_name}: named object/TCP observations must be datasets"
                    )
                object_values = object_dataset[...]
                tcp_values = tcp_dataset[...]
                if object_values.shape != (raw_count, 14) or object_values.dtype != np.dtype(
                    "float64"
                ):
                    raise SourceAuditError(
                        f"{demo_name}/obs/object: expected ({raw_count}, 14) float64"
                    )
                if tcp_values.shape != (raw_count, 3) or tcp_values.dtype != np.dtype("float64"):
                    raise SourceAuditError(
                        f"{demo_name}/obs/robot0_eef_pos: expected ({raw_count}, 3) float64"
                    )
                _finite(object_values, label=f"{demo_name}/obs/object")
                _finite(tcp_values, label=f"{demo_name}/obs/robot0_eef_pos")

                can_raw = qpos[:, model.can_qpos_address : model.can_qpos_address + 3]
                can_prepared = object_values[:, 7:10]
                if can_raw.tobytes(order="C") != can_prepared.tobytes(order="C"):
                    raise SourceAuditError(
                        f"{demo_name}: named Can_joint0 translation differs from obs/object[:,7:10]"
                    )
                can_rows += raw_count
                tcp_fk = _forward_kinematics(model, qpos)
                fk_error = float(np.max(np.abs(tcp_fk - tcp_values)))
                max_fk_error = max(max_fk_error, fk_error)
                if fk_error > 2e-12:
                    raise SourceAuditError(
                        f"{demo_name}: XML FK differs from obs/robot0_eef_pos; max error {fk_error}"
                    )
                demo_reports.append(
                    {
                        "demo_id": demo_name,
                        "fk_max_abs_error": fk_error,
                        "num_samples": raw_count,
                        "qpos_width": model.nq,
                        "qvel_width": model.nv,
                        "state_width": states.shape[1],
                    }
                )
                if demo_name == selected_demo:
                    if expected_frame_count is not None and raw_count != expected_frame_count:
                        raise SourceAuditError(
                            f"{demo_name}: expected {expected_frame_count} rows, got {raw_count}"
                        )
                    selected_frames = tuple(
                        SourceFrame(
                            can_xyz=tuple(float(value) for value in can_prepared[index]),
                            tcp_xyz=tuple(float(value) for value in tcp_values[index]),
                        )
                        for index in range(raw_count)
                    )
            total = sum(item["num_samples"] for item in demo_reports)
            if total != expected_total_samples or total != int(raw_data.attrs["total"]):
                raise SourceAuditError(
                    f"sample accounting: expected exact total {expected_total_samples}, got {total}"
                )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise SourceAuditError(f"malformed HDF5: {exc}") from exc
    except SourceAuditError as exc:
        first_mismatch = str(exc)
        raise
    finally:
        _ = first_mismatch

    if selected_frames is None:  # pragma: no cover - selected-demo check above
        raise SourceAuditError("selected demo was not extracted")
    report = {
        "all_actions_correspondence_only": True,
        "can_named_qpos_rows_verified": can_rows,
        "clock_rows_verified": clock_rows,
        "demo_count": len(demo_reports),
        "demo_reports": demo_reports,
        "excluded_values_used_for_normalization": [],
        "first_mismatch": None,
        "mask_membership_equal": True,
        "max_fk_abs_error": max_fk_error,
        "prepared_sha256": sha256_file(prepared),
        "raw_sha256": sha256_file(raw),
        "selected_demo": selected_demo,
        "selected_frame_count": len(selected_frames),
        "source_environment": environment,
        "states_actions_model_sample_masks_equal": True,
    }
    return AuditResult(frames=selected_frames, report=report)
