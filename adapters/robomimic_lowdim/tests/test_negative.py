# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from robomimic_lowdim.fixture import FixtureError, write_fixtures
from robomimic_lowdim.hdf5_audit import SourceAuditError, SourceFrame, compare_raw_prepared


def _model_xml() -> str:
    return """<mujoco><worldbody>
      <body name="robot0_base"><body name="robot0_link" pos="0 0 0">
        <joint name="robot0_joint1" type="hinge" axis="0 0 1"/>
        <body name="robot0_eef" pos="0 0 1"><site name="gripper0_right_grip_site" pos="0 0 0"/></body>
      </body></body>
      <body name="Milk_main"><joint name="Milk_joint0" type="free"/></body>
      <body name="Bread_main"><joint name="Bread_joint0" type="free"/></body>
      <body name="Cereal_main"><joint name="Cereal_joint0" type="free"/></body>
      <body name="Can_main"><joint name="Can_joint0" type="free"/></body>
    </worldbody></mujoco>"""


def _env(version: str) -> str:
    return json.dumps(
        {
            "env_name": "PickPlaceCan",
            "env_version": version,
            "type": 1,
            "env_kwargs": {
                "control_freq": 20,
                "ignore_done": True,
                "controller_configs": {
                    "body_parts": {"right": {"type": "OSC_POSE", "input_ref_frame": "world"}}
                },
            },
        }
    )


def _make_pair(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root / "raw.hdf5"
    prepared_path = root / "prepared.hdf5"
    demos = ["demo_0", "demo_1"]
    xml = _model_xml()
    nq = 29
    nv = 25
    for path, prepared in ((raw_path, False), (prepared_path, True)):
        with h5py.File(path, "w") as handle:
            data = handle.create_group("data")
            data.attrs["env_args"] = _env("1.5.1" if prepared else "1.5.0")
            data.attrs["total"] = 5
            mask = handle.create_group("mask")
            encoded = np.asarray([name.encode() for name in demos], dtype="S8")
            for name in (
                "20_percent",
                "20_percent_train",
                "20_percent_valid",
                "50_percent",
                "50_percent_train",
                "50_percent_valid",
                "train",
                "valid",
            ):
                mask.create_dataset(name, data=encoded)
            for index, demo_name in enumerate(demos):
                count = 3 if index == 0 else 2
                group = data.create_group(demo_name)
                group.attrs["model_file"] = xml
                group.attrs["num_samples"] = count
                states = np.zeros((count, 1 + nq + nv), dtype=np.float64)
                states[:, 0] = np.arange(count) / 20
                states[:, 1 + 22 : 1 + 25] = np.asarray([0.12, -0.2, 0.86])
                group.create_dataset("states", data=states)
                group.create_dataset("actions", data=np.zeros((count, 7), dtype=np.float64))
                if not prepared:
                    for name in (
                        "controller_info",
                        "interventions",
                        "policy_acting",
                        "user_acting",
                        "user_info",
                    ):
                        group.create_dataset(name, data=np.zeros((count,), dtype=np.float64))
                else:
                    obs = group.create_group("obs")
                    next_obs = group.create_group("next_obs")
                    object_values = np.zeros((count, 14), dtype=np.float64)
                    object_values[:, 7:10] = np.asarray([0.12, -0.2, 0.86])
                    tcp = np.tile(np.asarray([0.0, 0.0, 1.0]), (count, 1))
                    for target in (obs, next_obs):
                        target.create_dataset("object", data=object_values)
                        target.create_dataset("robot0_eef_pos", data=tcp)
                        target.create_dataset("robot0_eef_quat", data=np.zeros((count, 4)))
                        target.create_dataset("robot0_eef_quat_site", data=np.zeros((count, 4)))
                        target.create_dataset("robot0_gripper_qpos", data=np.zeros((count, 2)))
                        target.create_dataset("robot0_gripper_qvel", data=np.zeros((count, 2)))
                        target.create_dataset("robot0_joint_pos", data=np.zeros((count, 7)))
                        target.create_dataset("robot0_joint_pos_cos", data=np.zeros((count, 7)))
                        target.create_dataset("robot0_joint_pos_sin", data=np.zeros((count, 7)))
                        target.create_dataset("robot0_joint_vel", data=np.zeros((count, 7)))
                    group.create_dataset("dones", data=np.zeros(count))
                    group.create_dataset("rewards", data=np.zeros(count))
    return raw_path, prepared_path


def test_source_shaped_pair_passes_correspondence(tmp_path: Path) -> None:
    raw, prepared = _make_pair(tmp_path)
    result = compare_raw_prepared(
        raw,
        prepared,
        verify_identity=False,
        expected_frame_count=3,
        expected_demo_count=2,
        expected_total_samples=5,
    )
    assert len(result.frames) == 3
    assert result.report["demo_count"] == 2


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("states", "states"),
        ("actions", "actions"),
        ("clock", "20 Hz"),
        ("missing_object", "unexpected keys"),
        ("nonfinite", "nonfinite"),
        ("can_witness", "Can_joint0"),
        ("tcp_witness", "XML FK"),
    ],
)
def test_closed_negative_matrix(tmp_path: Path, mutation: str, match: str) -> None:
    raw, prepared = _make_pair(tmp_path)
    with h5py.File(prepared if mutation != "clock" else raw, "r+") as handle:
        demo = handle["data/demo_0"]
        if mutation == "states":
            demo["states"][0, 2] = 1.0
        elif mutation == "actions":
            demo["actions"][0, 0] = 1.0
        elif mutation == "clock":
            demo["states"][1, 0] = 0.06
            with h5py.File(prepared, "r+") as other:
                other["data/demo_0/states"][1, 0] = 0.06
        elif mutation == "missing_object":
            del demo["obs/object"]
        elif mutation == "nonfinite":
            demo["obs/object"][0, 7] = np.nan
        elif mutation == "can_witness":
            demo["obs/object"][0, 7] += 0.01
        elif mutation == "tcp_witness":
            demo["obs/robot0_eef_pos"][0, 0] += 0.01
    with pytest.raises(SourceAuditError, match=match):
        compare_raw_prepared(
            raw,
            prepared,
            verify_identity=False,
            expected_frame_count=3,
            expected_demo_count=2,
            expected_total_samples=5,
        )


def test_hdf5_soft_link_is_rejected(tmp_path: Path) -> None:
    raw, prepared = _make_pair(tmp_path)
    with h5py.File(raw, "r+") as handle:
        handle["unsafe_link"] = h5py.SoftLink("/data/demo_0")
    with pytest.raises(SourceAuditError, match="soft/external link"):
        compare_raw_prepared(
            raw,
            prepared,
            verify_identity=False,
            expected_frame_count=3,
            expected_demo_count=2,
            expected_total_samples=5,
        )


def test_hdf5_external_link_is_rejected(tmp_path: Path) -> None:
    raw, prepared = _make_pair(tmp_path)
    external = tmp_path / "external.hdf5"
    with h5py.File(external, "w") as handle:
        handle.create_group("payload")
    with h5py.File(raw, "r+") as handle:
        handle["unsafe_external"] = h5py.ExternalLink(str(external), "/payload")
    with pytest.raises(SourceAuditError, match="soft/external link"):
        compare_raw_prepared(
            raw,
            prepared,
            verify_identity=False,
            expected_frame_count=3,
            expected_demo_count=2,
            expected_total_samples=5,
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("demo_set", "demo name sets"),
        ("sample_count", "num_samples"),
        ("shape", "expected .* float64"),
        ("missing_tcp", "unexpected keys"),
        ("frequency", "control_freq"),
        ("controller", "OSC_POSE"),
        ("frame", "input_ref_frame"),
    ],
)
def test_additional_structural_negative_matrix(tmp_path: Path, mutation: str, match: str) -> None:
    raw, prepared = _make_pair(tmp_path)
    if mutation == "demo_set":
        with h5py.File(prepared, "r+") as handle:
            del handle["data/demo_1"]
    elif mutation == "sample_count":
        with h5py.File(prepared, "r+") as handle:
            handle["data/demo_0"].attrs["num_samples"] = 2
    elif mutation == "shape":
        with h5py.File(prepared, "r+") as handle:
            values = handle["data/demo_0/obs/object"][...]
            del handle["data/demo_0/obs/object"]
            handle["data/demo_0/obs"].create_dataset("object", data=values.astype("float32"))
    elif mutation == "missing_tcp":
        with h5py.File(prepared, "r+") as handle:
            del handle["data/demo_0/obs/robot0_eef_pos"]
    else:
        with h5py.File(raw, "r+") as raw_file, h5py.File(prepared, "r+") as prepared_file:
            for handle in (raw_file, prepared_file):
                env = json.loads(handle["data"].attrs["env_args"])
                right = env["env_kwargs"]["controller_configs"]["body_parts"]["right"]
                if mutation == "frequency":
                    env["env_kwargs"]["control_freq"] = 19
                elif mutation == "controller":
                    right["type"] = "JOINT_POSITION"
                elif mutation == "frame":
                    right["input_ref_frame"] = "base"
                handle["data"].attrs["env_args"] = json.dumps(env)
    with pytest.raises(SourceAuditError, match=match):
        compare_raw_prepared(
            raw,
            prepared,
            verify_identity=False,
            expected_frame_count=3,
            expected_demo_count=2,
            expected_total_samples=5,
        )


def test_malformed_hdf5_and_wrong_exact_identity_fail(tmp_path: Path) -> None:
    malformed = tmp_path / "not.hdf5"
    malformed.write_bytes(b"not hdf5")
    valid = tmp_path / "other.hdf5"
    valid.write_bytes(b"also not hdf5")
    with pytest.raises(SourceAuditError, match="malformed HDF5"):
        compare_raw_prepared(
            malformed,
            valid,
            verify_identity=False,
            expected_frame_count=3,
            expected_demo_count=2,
            expected_total_samples=5,
        )
    raw, prepared = _make_pair(tmp_path / "pair")
    with pytest.raises(SourceAuditError, match="size mismatch"):
        compare_raw_prepared(raw, prepared, verify_identity=True)


def test_actions_group_is_an_actionable_malformed_hdf5_error(tmp_path: Path) -> None:
    raw, prepared = _make_pair(tmp_path)
    for path in (raw, prepared):
        with h5py.File(path, "r+") as handle:
            del handle["data/demo_0/actions"]
            handle["data/demo_0"].create_group("actions")
    with pytest.raises(SourceAuditError, match="demo_0/actions: expected datasets"):
        compare_raw_prepared(
            raw,
            prepared,
            verify_identity=False,
            expected_frame_count=3,
            expected_demo_count=2,
            expected_total_samples=5,
        )


def test_filtered_dataset_and_xml_entity_declaration_are_rejected(tmp_path: Path) -> None:
    raw, prepared = _make_pair(tmp_path / "filtered")
    with h5py.File(prepared, "r+") as handle:
        values = handle["data/demo_0/obs/object"][...]
        del handle["data/demo_0/obs/object"]
        handle["data/demo_0/obs"].create_dataset("object", data=values, compression="gzip")
    with pytest.raises(SourceAuditError, match="filters"):
        compare_raw_prepared(
            raw,
            prepared,
            verify_identity=False,
            expected_frame_count=3,
            expected_demo_count=2,
            expected_total_samples=5,
        )
    raw, prepared = _make_pair(tmp_path / "entity")
    malicious = '<!DOCTYPE foo [<!ENTITY x "x">]>' + _model_xml()
    with h5py.File(raw, "r+") as raw_file, h5py.File(prepared, "r+") as prepared_file:
        raw_file["data/demo_0"].attrs["model_file"] = malicious
        prepared_file["data/demo_0"].attrs["model_file"] = malicious
    with pytest.raises(SourceAuditError, match="DTD/entity"):
        compare_raw_prepared(
            raw,
            prepared,
            verify_identity=False,
            expected_frame_count=3,
            expected_demo_count=2,
            expected_total_samples=5,
        )


def test_symlinked_source_config_and_output_are_rejected(
    tmp_path: Path,
    source_frames: list[SourceFrame],
    config_path: Path,
) -> None:
    raw, prepared = _make_pair(tmp_path / "source")
    link = tmp_path / "raw-link.hdf5"
    link.symlink_to(raw)
    with pytest.raises(SourceAuditError, match="symlink"):
        compare_raw_prepared(
            link,
            prepared,
            verify_identity=False,
            expected_frame_count=3,
            expected_demo_count=2,
            expected_total_samples=5,
        )
    config_link = tmp_path / "config-link.json"
    config_link.symlink_to(config_path)
    with pytest.raises(FixtureError, match="symlink"):
        write_fixtures(
            source_frames,
            config_path=config_link,
            output_root=tmp_path / "out",
            adapter_commit="a" * 40,
            allow_unbound_test_fixture=True,
        )
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    output_link = tmp_path / "output-link"
    output_link.symlink_to(real_output, target_is_directory=True)
    with pytest.raises(FixtureError, match="symlink"):
        write_fixtures(
            source_frames,
            config_path=config_path,
            output_root=output_link,
            adapter_commit="a" * 40,
            allow_unbound_test_fixture=True,
            overwrite=True,
        )


def test_writer_refuses_overwrite_and_input_overlap(
    tmp_path: Path, source_frames: list[SourceFrame], config_path: Path
) -> None:
    output = tmp_path / "out"
    write_fixtures(
        source_frames,
        config_path=config_path,
        output_root=output,
        adapter_commit="a" * 40,
        allow_unbound_test_fixture=True,
    )
    with pytest.raises(FixtureError, match="already exists"):
        write_fixtures(
            source_frames,
            config_path=config_path,
            output_root=output,
            adapter_commit="a" * 40,
            allow_unbound_test_fixture=True,
        )


def test_finalizer_rejects_extra_root_file_and_nested_symlink(
    tmp_path: Path, source_frames: list[SourceFrame], config_path: Path
) -> None:
    from robomimic_lowdim.fixture import finalize_conversion_equivalence

    roots = [tmp_path / f"conversion-{index}" for index in range(3)]
    for root in roots:
        write_fixtures(
            source_frames,
            config_path=config_path,
            output_root=root,
            adapter_commit="a" * 40,
            allow_unbound_test_fixture=True,
        )
    (roots[0] / "raw.hdf5").write_bytes(b"prohibited")
    with pytest.raises(FixtureError, match="top-level inventory"):
        finalize_conversion_equivalence(
            roots, output_root=tmp_path / "final-extra", allow_unbound_test_fixture=True
        )
    (roots[0] / "raw.hdf5").unlink()
    target = roots[0] / "incident" / "session.jsonl"
    link = roots[0] / "incident" / "nested-link"
    link.symlink_to(target)
    with pytest.raises(FixtureError, match="symlink"):
        finalize_conversion_equivalence(
            roots, output_root=tmp_path / "final-link", allow_unbound_test_fixture=True
        )


def test_finalizer_rejects_identically_corrupted_roots(
    tmp_path: Path, source_frames: list[SourceFrame], config_path: Path
) -> None:
    from robomimic_lowdim.fixture import finalize_conversion_equivalence

    roots = [tmp_path / f"corrupt-{index}" for index in range(3)]
    for root in roots:
        write_fixtures(
            source_frames,
            config_path=config_path,
            output_root=root,
            adapter_commit="a" * 40,
            allow_unbound_test_fixture=True,
        )
        for variant in ("incident", "control"):
            with (root / variant / "session.jsonl").open("ab") as handle:
                handle.write(b"{}\n")
    with pytest.raises(FixtureError, match="checksum mismatch"):
        finalize_conversion_equivalence(
            roots, output_root=tmp_path / "final-corrupt", allow_unbound_test_fixture=True
        )
    with pytest.raises(FixtureError, match="overlap"):
        write_fixtures(
            source_frames,
            config_path=config_path,
            output_root=config_path.parent,
            adapter_commit="a" * 40,
            allow_unbound_test_fixture=True,
        )


def test_finalizer_rejects_incident_control_state_mismatch(
    tmp_path: Path, source_frames: list[SourceFrame], config_path: Path
) -> None:
    from robomimic_lowdim.fixture import finalize_conversion_equivalence

    roots = [tmp_path / f"state-mismatch-{index}" for index in range(3)]
    for root in roots:
        write_fixtures(
            source_frames,
            config_path=config_path,
            output_root=root,
            adapter_commit="a" * 40,
            allow_unbound_test_fixture=True,
        )
        with (root / "incident/session.jsonl").open("ab") as handle:
            handle.write(b"{}\n")
    with pytest.raises(FixtureError, match="incident/control shared artifact differs: session"):
        finalize_conversion_equivalence(
            roots,
            output_root=tmp_path / "final-state-mismatch",
            allow_unbound_test_fixture=True,
        )
