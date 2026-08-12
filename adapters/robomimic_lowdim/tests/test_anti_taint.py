# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
from test_negative import _make_pair

from robomimic_lowdim.fixture import normalize_frames
from robomimic_lowdim.hdf5_audit import compare_raw_prepared


def test_outcome_annotation_action_and_next_obs_changes_cannot_change_state(
    tmp_path: Path, frozen_config: dict[str, object]
) -> None:
    raw, prepared = _make_pair(tmp_path)
    keyword_arguments = {
        "verify_identity": False,
        "expected_frame_count": 3,
        "expected_demo_count": 2,
        "expected_total_samples": 5,
    }
    baseline = compare_raw_prepared(raw, prepared, **keyword_arguments)
    baseline_frames = baseline.frames
    with h5py.File(raw, "r+") as raw_file, h5py.File(prepared, "r+") as prepared_file:
        for mask_name in raw_file["mask"]:
            # Paired valid membership mutation remains correspondence-only.
            members = raw_file[f"mask/{mask_name}"][...][::-1]
            raw_file[f"mask/{mask_name}"][...] = members
            prepared_file[f"mask/{mask_name}"][...] = members
        raw_env = json.loads(raw_file["data"].attrs["env_args"])
        prepared_env = json.loads(prepared_file["data"].attrs["env_args"])
        raw_env["env_kwargs"]["horizon"] = 777
        prepared_env["env_kwargs"]["horizon"] = 777
        raw_file["data"].attrs["env_args"] = json.dumps(raw_env)
        prepared_file["data"].attrs["env_args"] = json.dumps(prepared_env)
        for demo_name in raw_file["data"]:
            raw_demo = raw_file[f"data/{demo_name}"]
            prepared_demo = prepared_file[f"data/{demo_name}"]
            # Paired Can free-joint orientation and episode metadata mutations
            # remain correspondence-only; neither can affect emitted XY state.
            raw_demo["states"][:, 26:30] = np.asarray([1.0, 0.0, 0.0, 0.0])
            prepared_demo["states"][:, 26:30] = np.asarray([1.0, 0.0, 0.0, 0.0])
            raw_demo.attrs["ep_meta"] = '{"success": true, "end_reason": "taint"}'
            prepared_demo.attrs["ep_meta"] = '{"success": true, "end_reason": "taint"}'
            replacement = np.full(raw_demo["actions"].shape, 17.0)
            raw_demo["actions"][...] = replacement
            prepared_demo["actions"][...] = replacement
            raw_demo["interventions"][...] = 11.0
            raw_demo["policy_acting"][...] = 12.0
            raw_demo["user_acting"][...] = 13.0
            raw_demo["user_info"][...] = 14.0
            raw_demo["controller_info"][...] = 18.0
            prepared_demo["rewards"][...] = 15.0
            prepared_demo["dones"][...] = 16.0
            prepared_demo["obs/object"][:, 0:7] = 19.0
            prepared_demo["obs/object"][:, 10:14] = 20.0
            prepared_demo["obs/robot0_eef_quat"][...] = 21.0
            prepared_demo["obs/robot0_eef_quat_site"][...] = 22.0
            prepared_demo["next_obs/object"][...] = 999.0
            prepared_demo["next_obs/robot0_eef_pos"][...] = 999.0
    mutated = compare_raw_prepared(raw, prepared, **keyword_arguments)
    assert mutated.frames == baseline_frames


def test_durable_bundle_has_no_outcome_or_local_path_fields(
    tmp_path: Path,
    source_frames: list,
    frozen_config: dict[str, object],
) -> None:
    session, _ = normalize_frames(source_frames, frozen_config)
    text = session.decode("utf-8")
    for prohibited in (
        "reward",
        "done",
        "success",
        "failure",
        "action",
        "next_obs",
        str(tmp_path),
    ):
        assert prohibited not in text
    rows = [json.loads(line) for line in session.splitlines()]
    assert all(row["events"] == [] for row in rows)
