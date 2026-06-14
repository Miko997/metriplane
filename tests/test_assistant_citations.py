# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from metriplane.assistant.answer import answer_question
from metriplane.assistant.citations import is_within_root, make_citation, relpath

BUNDLE = "evidence/incidents/INC-DIST-001"


def test_citation_has_source_path():
    a = answer_question("what incident happened?", BUNDLE)
    assert a.citations
    assert a.citations[0].source_path
    assert a.citations[0].source_type == "incidents"


def test_citation_paths_are_relative_inside_root():
    a = answer_question("what incident happened?", BUNDLE)
    for c in a.citations:
        # relative path, not absolute, and does not escape the root
        assert not Path(c.source_path).is_absolute()
        assert ".." not in c.source_path


def test_is_within_root_accepts_child(tmp_path):
    child = tmp_path / "a" / "b.txt"
    child.parent.mkdir(parents=True)
    child.write_text("x")
    assert is_within_root(child, tmp_path) is True


def test_is_within_root_rejects_traversal(tmp_path):
    outside = tmp_path.parent / "elsewhere.txt"
    assert is_within_root(outside, tmp_path) is False


def test_relpath_inside_root(tmp_path):
    f = tmp_path / "sub" / "x.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    assert relpath(f, tmp_path) == "sub/x.json"


def test_make_citation_fields(tmp_path):
    f = tmp_path / "incident.json"
    f.write_text("[]")
    c = make_citation(f, tmp_path, "incidents", record_id="inc_0001", line_number=1)
    assert c.source_path == "incident.json"
    assert c.record_id == "inc_0001"
    assert c.line_number == 1
