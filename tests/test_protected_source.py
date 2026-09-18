# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from tools.protected_source import ProtectedSourceError, read_protected_blob

REPOSITORY = "Miko997/metriplane"
HEAD = "a" * 40
ROOT_TREE = "b" * 40
DOCS_TREE = "c" * 40
STATUS_TREE = "d" * 40


@dataclass
class FakeApi:
    responses: dict[str, dict]

    def request(self, path: str, *, token: str) -> SimpleNamespace:
        assert token == "fixture-token"
        return SimpleNamespace(value=self.responses[path])


def _api(content: bytes) -> FakeApi:
    blob_sha = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    return FakeApi(
        {
            f"repos/{REPOSITORY}/git/commits/{HEAD}": {"sha": HEAD, "tree": {"sha": ROOT_TREE}},
            f"repos/{REPOSITORY}/git/trees/{ROOT_TREE}": {
                "sha": ROOT_TREE,
                "truncated": False,
                "tree": [{"path": "docs", "type": "tree", "sha": DOCS_TREE}],
            },
            f"repos/{REPOSITORY}/git/trees/{DOCS_TREE}": {
                "sha": DOCS_TREE,
                "truncated": False,
                "tree": [{"path": "status", "type": "tree", "sha": STATUS_TREE}],
            },
            f"repos/{REPOSITORY}/git/trees/{STATUS_TREE}": {
                "sha": STATUS_TREE,
                "truncated": False,
                "tree": [{"path": "grant.json", "type": "blob", "sha": blob_sha}],
            },
            f"repos/{REPOSITORY}/git/blobs/{blob_sha}": {
                "sha": blob_sha,
                "size": len(content),
                "encoding": "base64",
                "content": base64.b64encode(content).decode(),
            },
        }
    )


def _read(api: FakeApi) -> bytes:
    return read_protected_blob(
        api,
        repository=REPOSITORY,
        main_sha=HEAD,
        path="docs/status/grant.json",
        token="fixture-token",
    )


def test_exact_git_blob_bytes_are_read() -> None:
    assert _read(_api(b'{"fixture":true}\n')) == b'{"fixture":true}\n'


def test_partial_tree_and_substituted_blob_rejected() -> None:
    api = _api(b"fixture")
    api.responses[f"repos/{REPOSITORY}/git/trees/{DOCS_TREE}"]["truncated"] = True
    with pytest.raises(ProtectedSourceError, match="partial"):
        _read(api)
    api = _api(b"fixture")
    blob_path = next(path for path in api.responses if "/git/blobs/" in path)
    api.responses[blob_path]["content"] = base64.b64encode(b"substituted").decode()
    with pytest.raises(ProtectedSourceError, match="substituted"):
        _read(api)


def test_wrong_repository_and_unsafe_path_rejected() -> None:
    api = _api(b"fixture")
    for repository, path in (("other/repo", "docs/status/grant.json"), (REPOSITORY, "../secret")):
        with pytest.raises(ProtectedSourceError):
            read_protected_blob(
                api,
                repository=repository,
                main_sha=HEAD,
                path=path,
                token="fixture-token",
            )
