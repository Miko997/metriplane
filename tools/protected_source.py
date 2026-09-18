# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Read exact protected Git objects through the existing GitHub App token."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Any


class ProtectedSourceError(ValueError):
    """A requested protected Git object is absent, malformed, or substituted."""


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ProtectedSourceError(f"{label} is not a Git SHA")
    return value


def _blob_sha(value: bytes) -> str:
    return hashlib.sha1(f"blob {len(value)}\0".encode("ascii") + value).hexdigest()


def read_protected_blob(
    api: Any,
    *,
    repository: str,
    main_sha: str,
    path: str,
    token: str,
    max_bytes: int = 2_000_000,
) -> bytes:
    if repository != "Miko997/metriplane":
        raise ProtectedSourceError("protected source repository is not canonical")
    _sha(main_sha, "protected main")
    parts = path.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ProtectedSourceError("protected source path is invalid")
    commit = api.request(f"repos/{repository}/git/commits/{main_sha}", token=token).value
    if not isinstance(commit, dict) or commit.get("sha") != main_sha:
        raise ProtectedSourceError("protected source commit response is not exact")
    tree = commit.get("tree")
    if not isinstance(tree, dict):
        raise ProtectedSourceError("protected source commit tree is absent")
    tree_sha = _sha(tree.get("sha"), "protected source root tree")
    for index, part in enumerate(parts):
        response = api.request(f"repos/{repository}/git/trees/{tree_sha}", token=token).value
        if not isinstance(response, dict) or response.get("sha") != tree_sha:
            raise ProtectedSourceError("protected source tree response is not exact")
        rows = response.get("tree")
        if not isinstance(rows, list) or response.get("truncated") is not False:
            raise ProtectedSourceError("protected source tree inventory is partial")
        matches = [row for row in rows if isinstance(row, dict) and row.get("path") == part]
        if len(matches) != 1:
            raise ProtectedSourceError("protected source path is missing or ambiguous")
        row = matches[0]
        kind = "blob" if index == len(parts) - 1 else "tree"
        if row.get("type") != kind:
            raise ProtectedSourceError("protected source path object has the wrong type")
        object_sha = _sha(row.get("sha"), "protected source path object")
        if kind == "tree":
            tree_sha = object_sha
    blob = api.request(f"repos/{repository}/git/blobs/{object_sha}", token=token).value
    if not isinstance(blob, dict) or blob.get("sha") != object_sha:
        raise ProtectedSourceError("protected source blob response is not exact")
    if blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
        raise ProtectedSourceError("protected source blob encoding is unsupported")
    try:
        encoded = blob["content"].replace("\n", "")
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProtectedSourceError("protected source blob content is malformed") from exc
    if (
        len(content) > max_bytes
        or _blob_sha(content) != object_sha
        or blob.get("size") != len(content)
    ):
        raise ProtectedSourceError("protected source blob content is truncated or substituted")
    return content


def read_protected_json(
    api: Any, *, repository: str, main_sha: str, path: str, token: str
) -> dict[str, Any]:
    content = read_protected_blob(
        api, repository=repository, main_sha=main_sha, path=path, token=token
    )
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProtectedSourceError("protected JSON object is malformed") from exc
    if not isinstance(value, dict):
        raise ProtectedSourceError("protected JSON object is not a mapping")
    return value
