# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Canonical, injectable platform paths for Metriplane."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_APP_NAME = "metriplane"


class PlatformPathError(ValueError):
    """Raised when the process environment cannot provide safe platform paths."""


@dataclass(frozen=True, slots=True)
class PlatformPaths:
    """Resolved application directories that can be injected into path consumers."""

    config_dir: Path
    data_dir: Path
    cache_dir: Path
    state_dir: Path

    def __post_init__(self) -> None:
        for name in ("config_dir", "data_dir", "cache_dir", "state_dir"):
            value = Path(getattr(self, name))
            if not value.is_absolute():
                raise PlatformPathError(f"{name} must be an absolute path: {value}")
            object.__setattr__(self, name, value)

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def launcher_state_file(self) -> Path:
        return self.state_dir / "launcher-state.json"


def _absolute_env_path(environment: Mapping[str, str], name: str) -> Path | None:
    raw = environment.get(name)
    if raw is None or not raw.strip():
        return None
    value = Path(raw)
    if not value.is_absolute():
        raise PlatformPathError(f"{name} must be an absolute path: {raw}")
    return value


def _home_path(environment: Mapping[str, str], system: str) -> Path | None:
    names = ("USERPROFILE", "HOME") if system == "Windows" else ("HOME",)
    for name in names:
        value = _absolute_env_path(environment, name)
        if value is not None:
            return value
    return None


def _required_base(
    environment: Mapping[str, str],
    variable: str,
    fallback: Path | None,
) -> Path:
    configured = _absolute_env_path(environment, variable)
    if configured is not None:
        return configured
    if fallback is not None:
        return fallback
    raise PlatformPathError(
        f"cannot resolve {variable}: set it to an absolute path or provide a usable home"
    )


def resolve_platform_paths(
    *,
    environment: Mapping[str, str] | None = None,
    system: str | None = None,
) -> PlatformPaths:
    """Resolve paths without writing to disk or caching process environment state."""

    env = os.environ if environment is None else environment
    platform_name = platform.system() if system is None else system
    home = _home_path(env, platform_name)

    if platform_name == "Windows":
        roaming = _required_base(
            env,
            "APPDATA",
            home / "AppData" / "Roaming" if home is not None else None,
        )
        local = _required_base(
            env,
            "LOCALAPPDATA",
            home / "AppData" / "Local" if home is not None else None,
        )
        return PlatformPaths(
            config_dir=roaming / _APP_NAME,
            data_dir=roaming / _APP_NAME,
            cache_dir=local / _APP_NAME / "cache",
            state_dir=local / _APP_NAME / "state",
        )

    if platform_name == "Darwin":
        support = home / "Library" / "Application Support" if home is not None else None
        caches = home / "Library" / "Caches" if home is not None else None
        config_base = _required_base(env, "XDG_CONFIG_HOME", support)
        data_base = _required_base(env, "XDG_DATA_HOME", support)
        cache_base = _required_base(env, "XDG_CACHE_HOME", caches)
        state_base = _required_base(env, "XDG_STATE_HOME", support)
    else:
        config_base = _required_base(
            env,
            "XDG_CONFIG_HOME",
            home / ".config" if home is not None else None,
        )
        data_base = _required_base(
            env,
            "XDG_DATA_HOME",
            home / ".local" / "share" if home is not None else None,
        )
        cache_base = _required_base(
            env,
            "XDG_CACHE_HOME",
            home / ".cache" if home is not None else None,
        )
        state_base = _required_base(
            env,
            "XDG_STATE_HOME",
            home / ".local" / "state" if home is not None else None,
        )

    return PlatformPaths(
        config_dir=config_base / _APP_NAME,
        data_dir=data_base / _APP_NAME,
        cache_dir=cache_base / _APP_NAME,
        state_dir=state_base / _APP_NAME,
    )
