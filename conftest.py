# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Repository-wide pytest policy without import-path mutation."""

from __future__ import annotations

import builtins
import datetime as dt
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent
_PROFILE_ENVIRONMENT = "METRIPLANE_TEST_PROFILE"
_ALLOWED_PROFILES = frozenset({"source", "installed"})
_POLICY_KEYS = frozenset({"warning_allowlist_version", "warning_allowlist"})
_ENTRY_KEYS = frozenset({"id", "owner", "reason", "scope", "category", "message", "expires"})
_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9._-]{2,63}$")
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


class WarningPolicyError(ValueError):
    """Raised when warning-policy configuration cannot be trusted."""


@dataclass(frozen=True)
class WarningAllowance:
    id: str
    owner: str
    reason: str
    scope: tuple[str, ...]
    category: str
    message: str
    expires: dt.datetime

    @property
    def pytest_filter(self) -> str:
        exact_message = rf"\A{re.escape(self.message)}\Z"
        return f"ignore:{exact_message}:{self.category}"


def _fail(message: str) -> None:
    raise WarningPolicyError(message)


def _nonempty_text(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        _fail(f"warning allowlist {key} must be non-empty text")
    return value


def _parse_expiry(value: Any) -> dt.datetime:
    if not isinstance(value, str) or _RFC3339_PATTERN.fullmatch(value) is None:
        _fail("warning allowlist expires must be an RFC3339 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise WarningPolicyError("warning allowlist expires must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("warning allowlist expires must include a timezone")
    return parsed.astimezone(dt.UTC)


def _validate_warning_allowlist(
    raw_entries: Any,
    *,
    profile: str,
    now: dt.datetime | None = None,
) -> tuple[WarningAllowance, ...]:
    if profile not in _ALLOWED_PROFILES:
        _fail(f"unknown test profile: {profile}")
    if not isinstance(raw_entries, list):
        _fail("warning_allowlist must be an array")
    current = now or dt.datetime.now(dt.UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        _fail("warning policy clock must include a timezone")
    current = current.astimezone(dt.UTC)

    seen: set[str] = set()
    active: list[WarningAllowance] = []
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            _fail(f"warning allowlist entry {index} must be a table")
        if set(raw_entry) != _ENTRY_KEYS:
            _fail(f"warning allowlist entry {index} has missing or unknown fields")

        entry_id = _nonempty_text(raw_entry, "id")
        if _ID_PATTERN.fullmatch(entry_id) is None:
            _fail(f"warning allowlist entry {index} has an invalid id")
        if entry_id in seen:
            _fail(f"duplicate warning allowlist id: {entry_id}")
        seen.add(entry_id)

        owner = _nonempty_text(raw_entry, "owner")
        reason = _nonempty_text(raw_entry, "reason")
        category = _nonempty_text(raw_entry, "category")
        message = _nonempty_text(raw_entry, "message")
        if ":" in message:
            _fail(f"warning allowlist entry {entry_id} message cannot contain ':'")
        category_type = getattr(builtins, category, None)
        if not isinstance(category_type, type) or not issubclass(category_type, Warning):
            _fail(f"warning allowlist entry {entry_id} has an unknown category")

        raw_scope = raw_entry.get("scope")
        if (
            not isinstance(raw_scope, list)
            or not raw_scope
            or any(not isinstance(item, str) for item in raw_scope)
            or len(set(raw_scope)) != len(raw_scope)
            or not set(raw_scope).issubset(_ALLOWED_PROFILES)
        ):
            _fail(f"warning allowlist entry {entry_id} has an invalid scope")
        expiry = _parse_expiry(raw_entry.get("expires"))
        if expiry <= current:
            _fail(f"warning allowlist entry {entry_id} is expired")

        allowance = WarningAllowance(
            id=entry_id,
            owner=owner,
            reason=reason,
            scope=tuple(raw_scope),
            category=category,
            message=message,
            expires=expiry,
        )
        if profile in allowance.scope:
            active.append(allowance)
    return tuple(active)


def _load_warning_policy(
    project_root: Path,
    *,
    profile: str,
    now: dt.datetime | None = None,
) -> tuple[WarningAllowance, ...]:
    try:
        pyproject = tomllib.loads((project_root / "pyproject.toml").read_text("utf-8"))
        policy = pyproject["tool"]["metriplane"]["testing"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise WarningPolicyError("warning policy configuration is missing or invalid") from exc
    if not isinstance(policy, dict) or set(policy) != _POLICY_KEYS:
        _fail("warning policy has missing or unknown fields")
    if policy.get("warning_allowlist_version") != 1:
        _fail("warning_allowlist_version must equal 1")
    return _validate_warning_allowlist(policy.get("warning_allowlist"), profile=profile, now=now)


def pytest_configure(config: pytest.Config) -> None:
    profile = os.environ.get(_PROFILE_ENVIRONMENT, "source")
    try:
        allowances = _load_warning_policy(_PROJECT_ROOT, profile=profile)
    except WarningPolicyError as exc:
        raise pytest.UsageError(f"invalid Metriplane warning policy: {exc}") from exc
    for allowance in allowances:
        config.addinivalue_line("filterwarnings", allowance.pytest_filter)
