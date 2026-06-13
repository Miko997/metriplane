from __future__ import annotations

from pathlib import Path

from metriplane.assistant.models import CitationModel


def is_within_root(path: str | Path, root: str | Path) -> bool:
    """True if `path` resolves inside `root` (reject path traversal)."""
    try:
        p = Path(path).resolve()
        r = Path(root).resolve()
        return p == r or r in p.parents
    except Exception:
        return False


def relpath(path: str | Path, root: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except Exception:
        return str(path)


def make_citation(path: str | Path, root: str | Path, source_type: str,
                  record_id: str | None = None, line_number: int | None = None,
                  field: str | None = None) -> CitationModel:
    return CitationModel(
        source_path=relpath(path, root),
        source_type=source_type,
        record_id=record_id,
        line_number=line_number,
        field=field,
    )
