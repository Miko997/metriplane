from __future__ import annotations

import dataclasses
import datetime as dt
import getpass
import hashlib
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, TextIO

import yaml

from metriplane.config import Config, resolve_profile


HEADER_TYPES = {"header", "run_header", "provenance"}


def is_header_record(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    t = obj.get("type") or obj.get("record_type")
    return t in HEADER_TYPES


def canonical_json_dumps(obj: Any) -> str:
    # Canonical JSON for stable hashing and more stable JSONL evidence bytes.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def in_docker() -> bool:
    return Path("/.dockerenv").exists()


def data_dir() -> Path:
    env = os.getenv("METRIPLANE_DATA_DIR")
    if env:
        return Path(env)
    return Path("/data") if in_docker() else Path(".")


def resolve_under_data_dir(p: str | Path) -> Path:
    pp = Path(p)
    if pp.is_absolute():
        return pp
    return data_dir() / pp


def generate_run_id(prefix: str = "run") -> str:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    rnd = secrets.token_hex(3)
    return f"{prefix}_{ts}_{rnd}"


def _find_repo_root(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / ".git").exists():
            return p
    return None


@dataclass(frozen=True, slots=True)
class GitInfo:
    commit: str | None
    dirty: bool | None
    describe: str | None
    repo_root: str | None


def get_git_info(*, start: Path | None = None) -> GitInfo:
    # Explicit override for Docker/no-.git builds
    env_commit = os.getenv("METRIPLANE_GIT_COMMIT") or os.getenv("GIT_COMMIT") or os.getenv("GITHUB_SHA")
    repo_root = _find_repo_root(start)

    if env_commit:
        return GitInfo(
            commit=str(env_commit)[:40],
            dirty=None,
            describe=None,
            repo_root=str(repo_root) if repo_root else None,
        )

    if repo_root is None:
        return GitInfo(commit=None, dirty=None, describe=None, repo_root=None)

    def _run(args: list[str]) -> str | None:
        try:
            p = subprocess.run(args, cwd=repo_root, check=True, capture_output=True, text=True)
            return p.stdout.strip()
        except Exception:
            return None

    commit = _run(["git", "rev-parse", "HEAD"])
    describe = _run(["git", "describe", "--tags", "--always", "--dirty"])

    dirty: bool | None
    try:
        p = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root, check=True, capture_output=True, text=True)
        dirty = bool(p.stdout.strip())
    except Exception:
        dirty = None

    return GitInfo(commit=commit, dirty=dirty, describe=describe, repo_root=str(repo_root))


def config_to_primitive(cfg: Config) -> dict[str, Any]:
    # asdict recursively converts nested dataclasses; JSON roundtrip ensures only JSON primitives.
    d = dataclasses.asdict(cfg)
    return json.loads(canonical_json_dumps(d))


def compute_config_hash(cfg: Config) -> tuple[str, str]:
    prim = config_to_primitive(cfg)
    canon = canonical_json_dumps(prim)
    return sha256_text(canon), canon


def dump_config_yaml(cfg: Config) -> str:
    prim = config_to_primitive(cfg)
    return yaml.safe_dump(prim, sort_keys=True, default_flow_style=False)


def _ensure_unique_run_dir(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 1000):
        cand = Path(f"{path}-{i}")
        if not cand.exists():
            return cand
    raise RuntimeError(f"could not find unique run dir name for {path}")


@dataclass(frozen=True, slots=True)
class RunContext:
    run_id: str
    run_dir: Path
    created_utc: str
    argv: list[str]

    resolved_profile: str | None

    config_hash: str
    git: GitInfo

    source_config_path: str | None

    meta_json: Path
    env_txt: Path
    config_yaml: Path
    config_canonical_json_path: Path
    session_jsonl: Path

    def header_record(self) -> dict[str, Any]:
        return {
            "type": "run_header",
            "schema_version": "1.0",
            "created_utc": self.created_utc,
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "git_commit": self.git.commit,
            "git_dirty": self.git.dirty,
            "git_describe": self.git.describe,
            "argv": list(self.argv),
            "source_config_path": self.source_config_path,
            "resolved_profile": self.resolved_profile,
        }


class JsonlWriter:
    def __init__(self, files: list[TextIO], paths: list[Path]) -> None:
        self._files = files
        self.paths = paths

    def write(self, obj: Any) -> None:
        # Accept pydantic models or plain dicts
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump()
        if not isinstance(obj, dict):
            raise TypeError(f"JsonlWriter.write expects dict-like; got {type(obj)}")

        line = canonical_json_dumps(obj)
        for f in self._files:
            f.write(line + "\n")

    def close(self) -> None:
        for f in self._files:
            try:
                f.close()
            except Exception:
                pass
        self._files = []


def capture_env_txt(path: Path) -> None:
    lines: list[str] = []
    lines.append(f"created_utc: {_utc_now_iso()}")
    lines.append(f"python: {sys.version.replace(os.linesep, ' ')}")
    lines.append(f"executable: {sys.executable}")
    lines.append(f"platform: {platform.platform()}")
    lines.append(f"machine: {platform.machine()}")
    lines.append(f"processor: {platform.processor()}")
    lines.append("")

    no_freeze = os.getenv("METRIPLANE_NO_PIP_FREEZE", "0").strip() == "1"
    lines.append("pip_freeze:")
    if no_freeze:
        lines.append("(skipped: METRIPLANE_NO_PIP_FREEZE=1)")
    else:
        try:
            p = subprocess.run([sys.executable, "-m", "pip", "freeze"], check=True, capture_output=True, text=True)
            lines.append(p.stdout.strip())
        except Exception as e:
            lines.append(f"(pip freeze failed: {type(e).__name__}: {e})")

    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_run_context(
    cfg: Config,
    *,
    config_path: Path | None,
    argv: Sequence[str] | None,
    run_id: str | None,
    runs_dir: str | None,
) -> RunContext:
    created = _utc_now_iso()

    rid = str(run_id or os.getenv("METRIPLANE_RUN_ID") or "").strip()
    if not rid:
        rid = generate_run_id()

    # Where runs live
    base: Path
    if runs_dir and str(runs_dir).strip():
        base = resolve_under_data_dir(str(runs_dir).strip())
    elif cfg.runs_dir and str(cfg.runs_dir).strip():
        base = resolve_under_data_dir(str(cfg.runs_dir).strip())
    else:
        base = data_dir() / "runs"

    # Make run dir unique (avoid overwriting)
    run_dir = _ensure_unique_run_dir(base / rid)
    run_dir.mkdir(parents=True, exist_ok=False)

    # IMPORTANT: if we had to suffix, run_id must match directory name
    rid = run_dir.name

    # Git + config hash
    git = get_git_info(start=Path.cwd())
    cfg_hash, cfg_canon = compute_config_hash(cfg)

    # Resolved profile (captures calib/active_profile.yaml even if cfg.profile is None)
    resolved_prof = resolve_profile(cfg.profile, active_profile_path=Path("calib/active_profile.yaml"))

    # Artifact paths
    meta_json = run_dir / "meta.json"
    env_txt = run_dir / "env.txt"
    config_yaml = run_dir / "config.yaml"
    cfg_canon_path = run_dir / "config.canonical.json"
    session_jsonl = run_dir / "session.jsonl"

    # Write config snapshot + canonical JSON used for hashing
    config_yaml.write_text(dump_config_yaml(cfg), encoding="utf-8")
    cfg_canon_path.write_text(cfg_canon, encoding="utf-8")
    assert sha256_file(cfg_canon_path) == cfg_hash

    # Capture env
    capture_env_txt(env_txt)

    # Meta
    meta: dict[str, Any] = {
        "schema_version": "1.0",
        "created_utc": created,
        "run_id": rid,
        "run_dir": str(run_dir),
        "user": getpass.getuser(),
        "hostname": socket.gethostname(),
        "cwd": str(Path.cwd()),
        "argv": list(argv) if argv is not None else [],
        "source_config_path": str(config_path) if config_path else None,
        "resolved_profile": resolved_prof,
        "git": {
            "commit": git.commit,
            "dirty": git.dirty,
            "describe": git.describe,
            "repo_root": git.repo_root,
        },
        "config": {
            "hash_algo": "sha256",
            "hash": cfg_hash,
            "canonical_json_path": str(cfg_canon_path),
            "snapshot_yaml_path": str(config_yaml),
            "source_config_path": str(config_path) if config_path else None,
        },
        "artifacts": {
            "session_jsonl": str(session_jsonl),
            "env_txt": str(env_txt),
        },
        "checksums": {
            "config_yaml_sha256": sha256_file(config_yaml),
            "config_canonical_json_sha256": sha256_file(cfg_canon_path),
            "env_txt_sha256": sha256_file(env_txt),
        },
    }
    meta_json.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")

    return RunContext(
        run_id=rid,
        run_dir=run_dir,
        created_utc=created,
        argv=list(argv) if argv is not None else [],
        resolved_profile=resolved_prof,
        config_hash=cfg_hash,
        git=git,
        source_config_path=str(config_path) if config_path else None,
        meta_json=meta_json,
        env_txt=env_txt,
        config_yaml=config_yaml,
        config_canonical_json_path=cfg_canon_path,
        session_jsonl=session_jsonl,
    )


def open_jsonl_writer(*, primary_path: Path, mirror_path: str | None) -> JsonlWriter:
    paths: list[Path] = [primary_path]

    if mirror_path and str(mirror_path).strip():
        mp = resolve_under_data_dir(str(mirror_path).strip())
        try:
            if mp.resolve() != primary_path.resolve():
                paths.append(mp)
        except Exception:
            # If resolve() fails (permissions), still compare raw Paths.
            if mp != primary_path:
                paths.append(mp)

    files: list[TextIO] = []
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        files.append(p.open("w", encoding="utf-8", buffering=1))
    return JsonlWriter(files, paths)
