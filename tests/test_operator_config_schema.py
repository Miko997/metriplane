# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Tests for generated config schema validation.

The operator config builder (operator.js buildConfigObject) must emit
CameraSpec-compatible YAML that metriplane.config.load_config() can parse
without errors. The API-side _validate_camera_config() catches schema
errors before writing the file.

Key invariants verified here:
  - 'name' field is present (not 'id')
  - 'device' or 'index' field is present (not 'source')
  - 'mapping_file' field is present (not 'mapping')
  - Missing mapping_file on disk → 400 before write
  - Missing device+index → 400 before write
  - Valid multi-camera config → 200 + written file is loadable
"""

from unittest.mock import MagicMock

from metriplane.runner.operator_api import OperatorAPI, _validate_camera_config


# ── Unit tests for _validate_camera_config ────────────────────────────────────


class TestValidateCameraConfig:
    def test_no_cameras_key_passes(self, tmp_path):
        """Single-camera configs with no 'cameras' list are valid."""
        assert _validate_camera_config({"profile": "test"}, tmp_path) is None

    def test_valid_device_camera(self, tmp_path):
        mf = tmp_path / "cam0" / "mapping_raw.yaml"
        mf.parent.mkdir(parents=True)
        mf.write_text("h: 1\n")
        cfg = {"cameras": [{"name": "cam0", "device": "/dev/video0", "mapping_file": str(mf)}]}
        assert _validate_camera_config(cfg, tmp_path) is None

    def test_valid_index_camera(self, tmp_path):
        mf = tmp_path / "cam0" / "mapping_raw.yaml"
        mf.parent.mkdir(parents=True)
        mf.write_text("h: 1\n")
        cfg = {"cameras": [{"name": "cam0", "index": 0, "mapping_file": str(mf)}]}
        assert _validate_camera_config(cfg, tmp_path) is None

    def test_wrong_source_key_rejected(self, tmp_path):
        """'source' is the wrong field name — must use 'device' or 'index'."""
        mf = tmp_path / "cam0" / "mapping_raw.yaml"
        mf.parent.mkdir(parents=True)
        mf.write_text("h: 1\n")
        cfg = {"cameras": [{"name": "cam0", "source": "/dev/video0", "mapping_file": str(mf)}]}
        err = _validate_camera_config(cfg, tmp_path)
        assert err is not None
        assert "device" in err or "index" in err
        assert "source" in err  # error must mention the wrong key explicitly

    def test_wrong_id_key_still_allowed(self, tmp_path):
        """'id' instead of 'name' doesn't block validation (silently became 'cam0')."""
        mf = tmp_path / "cam0" / "mapping_raw.yaml"
        mf.parent.mkdir(parents=True)
        mf.write_text("h: 1\n")
        # 'id' key — the validator uses cam.get("name") or fallback "cam{i}"
        cfg = {"cameras": [{"id": "cam0", "device": "/dev/video0", "mapping_file": str(mf)}]}
        # id is wrong but doesn't cause a validation error (name defaults to cam0)
        # The device/mapping_file check is what matters
        assert _validate_camera_config(cfg, tmp_path) is None

    def test_wrong_mapping_key_rejected(self, tmp_path):
        """'mapping' is the wrong key — must use 'mapping_file'."""
        mf = tmp_path / "cam0" / "mapping_raw.yaml"
        mf.parent.mkdir(parents=True)
        mf.write_text("h: 1\n")
        cfg = {"cameras": [{"name": "cam0", "device": "/dev/video0", "mapping": str(mf)}]}
        err = _validate_camera_config(cfg, tmp_path)
        assert err is not None
        assert "mapping_file" in err

    def test_missing_mapping_file_on_disk_rejected(self, tmp_path):
        """mapping_file path must exist on disk."""
        cfg = {
            "cameras": [
                {
                    "name": "cam0",
                    "device": "/dev/video0",
                    "mapping_file": "calib/profiles/test/cam0/mapping_raw.yaml",
                }
            ]
        }
        err = _validate_camera_config(cfg, tmp_path)
        assert err is not None
        assert "not found" in err or "Step 5" in err

    def test_multi_camera_valid(self, tmp_path):
        for cam in ("cam0", "cam1"):
            mf = tmp_path / "calib" / "profiles" / "test" / cam / "mapping_raw.yaml"
            mf.parent.mkdir(parents=True)
            mf.write_text("h: 1\n")
        cfg = {
            "cameras": [
                {
                    "name": "cam0",
                    "device": "/dev/video0",
                    "mapping_file": "calib/profiles/test/cam0/mapping_raw.yaml",
                },
                {
                    "name": "cam1",
                    "device": "/dev/video2",
                    "mapping_file": "calib/profiles/test/cam1/mapping_raw.yaml",
                },
            ]
        }
        assert _validate_camera_config(cfg, tmp_path) is None


# ── Integration: _save_config rejects broken schema ──────────────────────────


class TestSaveConfigValidation:
    def _make_api(self, tmp_path):
        executor = MagicMock()
        executor.execute.return_value = "job-1"
        return OperatorAPI(executor=executor, repo_root=tmp_path)

    def test_save_config_rejects_source_key(self, tmp_path):
        api = self._make_api(tmp_path)
        cfg = {"cameras": [{"name": "cam0", "source": "0", "mapping_file": "nonexistent.yaml"}]}
        status, resp = api._save_config({"filename": "test_local.yaml", "config": cfg})
        assert status == 400
        assert "error" in resp
        assert "source" in resp["error"]

    def test_save_config_rejects_missing_mapping_file_on_disk(self, tmp_path):
        api = self._make_api(tmp_path)
        cfg = {
            "cameras": [
                {
                    "name": "cam0",
                    "device": "/dev/video0",
                    "mapping_file": "calib/profiles/test/cam0/mapping_raw.yaml",
                },
            ]
        }
        status, resp = api._save_config({"filename": "test_local.yaml", "config": cfg})
        assert status == 400
        assert "mapping_file" in resp["error"] or "not found" in resp["error"]

    def test_save_config_valid_writes_file(self, tmp_path):
        api = self._make_api(tmp_path)
        # Create the mapping file so existence check passes
        mf = tmp_path / "calib" / "profiles" / "test" / "cam0" / "mapping_raw.yaml"
        mf.parent.mkdir(parents=True)
        mf.write_text("homography: [[1,0,0],[0,1,0],[0,0,1]]\n")

        cfg = {
            "cameras": [
                {
                    "name": "cam0",
                    "device": "/dev/video0",
                    "mapping_file": "calib/profiles/test/cam0/mapping_raw.yaml",
                },
            ]
        }
        status, resp = api._save_config({"filename": "test_local.yaml", "config": cfg})
        assert status == 200
        saved = tmp_path / "configs" / "local" / "test_local.yaml"
        assert saved.exists()

    def test_save_config_valid_multi_writes_file(self, tmp_path):
        """Multi-camera config with correct field names must save successfully."""
        api = self._make_api(tmp_path)
        for cam in ("cam0", "cam1"):
            mf = tmp_path / "calib" / "profiles" / "test" / cam / "mapping_raw.yaml"
            mf.parent.mkdir(parents=True)
            mf.write_text("homography: [[1,0,0],[0,1,0],[0,0,1]]\n")

        cfg = {
            "profile": "test",
            "target_fps": 30,
            "ws_host": "127.0.0.1",
            "ws_port": 8765,
            "metrics_host": "127.0.0.1",
            "metrics_port": 8000,
            "cameras": [
                {
                    "name": "cam0",
                    "device": "/dev/video0",
                    "mapping_file": "calib/profiles/test/cam0/mapping_raw.yaml",
                },
                {
                    "name": "cam1",
                    "device": "/dev/video2",
                    "mapping_file": "calib/profiles/test/cam1/mapping_raw.yaml",
                },
            ],
            "fusion_enable": True,
            "fusion": {"method": "kalman"},
            "zones_file": "calib/profiles/test/zones.yaml",
        }
        status, resp = api._save_config({"filename": "test_multi_local.yaml", "config": cfg})
        assert status == 200
        saved = tmp_path / "configs" / "local" / "test_multi_local.yaml"
        assert saved.exists()

        # The saved file must be loadable by the real config loader
        import yaml as _yaml

        raw = _yaml.safe_load(saved.read_text())
        assert raw["cameras"][0]["name"] == "cam0"
        assert raw["cameras"][0].get("device") == "/dev/video0"
        assert raw["cameras"][0].get("mapping_file") == "calib/profiles/test/cam0/mapping_raw.yaml"
        assert "source" not in raw["cameras"][0], "should not have 'source' key"
        assert "id" not in raw["cameras"][0], "should not have 'id' key"
        assert "mapping" not in raw["cameras"][0], "should not have bare 'mapping' key"

    def test_save_config_index_camera_valid(self, tmp_path):
        """Integer index cameras should also pass validation."""
        api = self._make_api(tmp_path)
        mf = tmp_path / "calib" / "profiles" / "test" / "cam0" / "mapping_raw.yaml"
        mf.parent.mkdir(parents=True)
        mf.write_text("h: 1\n")

        cfg = {
            "cameras": [
                {
                    "name": "cam0",
                    "index": 0,
                    "mapping_file": "calib/profiles/test/cam0/mapping_raw.yaml",
                },
            ]
        }
        status, resp = api._save_config({"filename": "test_idx_local.yaml", "config": cfg})
        assert status == 200


# ── metriplane.config.load_config parses saved YAML correctly ─────────────────


class TestLoadConfigRoundtrip:
    def test_load_multi_camera_config(self, tmp_path):
        """
        Config written by the operator (correct field names) must be loadable
        by metriplane.config.load_config without errors.
        """
        import yaml as _yaml
        from metriplane.config import load_config

        # Write a valid multi-camera config
        cfg_data = {
            "profile": "test",
            "target_fps": 30,
            "ws_host": "127.0.0.1",
            "ws_port": 8765,
            "cameras": [
                {
                    "name": "cam0",
                    "index": 0,
                    "mapping_file": "calib/profiles/test/cam0/mapping_raw.yaml",
                },
                {
                    "name": "cam1",
                    "index": 2,
                    "mapping_file": "calib/profiles/test/cam1/mapping_raw.yaml",
                },
            ],
            "fusion_enable": True,
        }
        cfg_path = tmp_path / "test_config.yaml"
        cfg_path.write_text(_yaml.dump(cfg_data))

        cfg = load_config(cfg_path)
        assert cfg.cameras is not None
        assert len(cfg.cameras) == 2
        assert cfg.cameras[0].name == "cam0"
        assert cfg.cameras[0].index == 0
        assert cfg.cameras[0].device is None
        assert cfg.cameras[1].name == "cam1"
        assert cfg.cameras[1].index == 2
