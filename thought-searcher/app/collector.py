"""Claude Code 세션 수집: 원본 jsonl 로컬 복사 + md 변환."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .archive import Archive
from .importers.claude_code import main_sessions, parse_session

log = logging.getLogger("thought-searcher")

# Code md 만드는 규칙이 바뀌면 올린다. 올라가면 다음 수집에서 모든 세션 md를 자동으로 다시 만든다
RENDER_VERSION = 2  # 2: 도구 호출 줄 제외


@dataclass
class CollectResult:
    copied: int = 0
    new: int = 0
    changed: int = 0
    same: int = 0
    missing: int = 0
    written: list[Path] = field(default_factory=list)


def sync_raw(projects_dir: Path, raw_dir: Path, record: dict) -> int:
    """projects 폴더 전체를 같은 구조로 복사. 크기나 수정 시각이 바뀐 파일만. 원본에서 지워진 복사본은 남긴다."""
    copied = 0
    if not projects_dir.is_dir():
        return 0
    for src in projects_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(projects_dir).as_posix()
        try:
            st = src.stat()
        except OSError:
            continue
        key = [st.st_size, st.st_mtime_ns]
        dst = raw_dir / rel
        if record.get(rel) == key and dst.exists():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except OSError as e:
            log.warning("원본 복사 실패 %s: %s", rel, e)
            continue
        record[rel] = key
        copied += 1
    return copied


def collect(projects_dir: Path, raw_dir: Path, archive: Archive, state: dict, force: bool = False,
            progress=None) -> CollectResult:
    res = CollectResult()
    res.copied = sync_raw(projects_dir, raw_dir, state.setdefault("code_files", {}))
    sessions = state.setdefault("code_sessions", {})
    if state.get("code_render_version") != RENDER_VERSION:
        force = True
    files = main_sessions(raw_dir) if raw_dir.is_dir() else []
    for i, raw in enumerate(files, 1):
        if progress:
            progress(i, len(files))
        rel = raw.relative_to(raw_dir).as_posix()
        present = (projects_dir / rel).is_file()
        try:
            st = raw.stat()
        except OSError:
            continue
        key = [st.st_size, st.st_mtime_ns, present]
        if not force and sessions.get(rel) == key:
            continue
        conv = parse_session(raw)
        if conv is None:
            sessions[rel] = key
            continue
        status = "present" if present else "missing"
        r = archive.write(conv, status=status)
        if r.status in ("new", "changed"):
            res.written.append(r.path)
            if r.old_path:
                res.written.append(r.old_path)
        if r.status == "new":
            res.new += 1
        elif r.status == "changed":
            res.changed += 1
        else:
            res.same += 1
        if not present:
            res.missing += 1
        sessions[rel] = key
    state["code_render_version"] = RENDER_VERSION
    return res
