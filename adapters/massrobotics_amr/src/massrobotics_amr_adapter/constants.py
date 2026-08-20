# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

PROFILE_ID = "metriplane.massrobotics_amr_offline_replay.v1"
ADAPTER_ID = "org.metriplane.massrobotics_amr_offline_replay"
ADAPTER_VERSION = "1.0.0"
SOURCE_CLASSIFICATION = "synthetic_format_engineering"
SOURCE_DESCRIPTION = "Metriplane-authored synthetic MassRobotics-format engineering fixture"
SOURCE_BACKEND = "massrobotics_amr_offline_replay_v1_synthetic"
AMR_1_UUID = "11111111-1111-4111-8111-111111111111"
AMR_2_UUID = "22222222-2222-4222-8222-222222222222"
PLANAR_DATUM_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FRAME_INTERVAL_NS = 1_000_000_000
IDENTITY_TIMESTAMP = "2026-08-20T09:59:59Z"
FIRST_STATUS_TIMESTAMP = "2026-08-20T10:00:00Z"
EXPECTED_ORDER = (AMR_1_UUID, AMR_2_UUID)
UPSTREAM_RELEASE_COMMIT = "7161a0d"
UPSTREAM_SNAPSHOT_COMMIT = "f9357a423ecabc3f7112e6d10025a5231943ec50"
UPSTREAM_BLOBS = {
    "AMR_Interop_Standard.json": "7ba8974ae46d81ea0f6f8ed0ac7899d9d279af98",
    "AMR_Interop_Standard.pdf": "2436fee76da3a7b15516b518d85d237724925f90",
    "README.md": "4031260c9036672a6cd85b93111862b5daa568c3",
    "examples/identityReport1.json": "112ac8d1df62170f785dadf03419968c7e8b61df",
    "examples/statusReport1.json": "b396acbf743c2ffcd448dd675dc830b77384b054",
}
UPSTREAM_RAW_SHA256 = {
    "AMR_Interop_Standard.json": "816c8f78e1d280d10983a1bcea69a3c8e6572e5bb6f777a0863e6a5b2c3fc288",
    "AMR_Interop_Standard.pdf": "99aa8cceb10247dbfd2957695695b5f11d347bf51a0452e3f330887b2f4e2ff2",
    "README.md": "7b4db4d9b5ca0a6735690f2b37228c234703e4a5bdbbee634106fc7ba9f1a4e5",
    "examples/identityReport1.json": "c8c35e010535a83135f2dcaeacec42ae9e2411c108ce0b7035ab6438b0549a94",
    "examples/statusReport1.json": "13b230e7e884c92bc551ba2800a5490259858af59b69e4470029c71060430cfd",
}

CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
PACKAGED_DATA_ROOT = Path(__file__).resolve().parent / "data"
DATA_ROOT = PACKAGED_DATA_ROOT if PACKAGED_DATA_ROOT.is_dir() else CHECKOUT_ROOT
DEFAULT_CONFIG = DATA_ROOT / (
    "frozen-config.json" if DATA_ROOT == PACKAGED_DATA_ROOT else "config/frozen-config.json"
)
DEFAULT_LOCK = DATA_ROOT / "uv.lock"
DEFAULT_SOURCE_ROOT = DATA_ROOT / "source"
