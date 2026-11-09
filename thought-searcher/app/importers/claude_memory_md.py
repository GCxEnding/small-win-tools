"""claude.ai 메모리 md 묶음 가져오기.

내보내기의 memories-000.zip(JSON)이 안 받아질 때 claude.ai 메모리 화면에서 따로 받는 zip이다.
  claude-memory-YYYY-MM-DD/
    profile.md, preferences.md
    areas/*.md, topics/*.md
    projects/<프로젝트 이름>/*.md, projects/<이름>/areas/*.md, projects/<이름>/topics/*.md
각 md는 frontmatter(name, description) + 본문이다.
결과는 공식 JSON과 같은 대화(claude-ai-memory:main, memories.md)로 만든다. 둘 중 더 새것이 남는다.
"""
from __future__ import annotations

import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator

from ..model import Conversation, Message
from .base import ImportFailed, SkipFn
from .claude_export import SRC_MEMORY

KIND_DIRS = ("areas", "topics")
_FRONT_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.S)
_DATE_IN_NAME = re.compile(r"claude-memory-(\d{4})-(\d{2})-(\d{2})")


def split_front(text: str) -> tuple[dict[str, str], str]:
    m = _FRONT_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep:
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            meta[k.strip()] = v
    return meta, text[m.end():]


def _rel_parts(name: str, root: str) -> tuple[str, ...]:
    parts = PurePosixPath(name).parts
    return parts[1:] if root and parts and parts[0] == root else parts


def _is_memory_path(parts: tuple[str, ...]) -> bool:
    """묶음 안에서 메모리 md가 놓일 수 있는 자리인지."""
    if not parts or not parts[-1].endswith(".md"):
        return False
    if len(parts) == 1:
        return True                                    # profile.md, preferences.md
    if len(parts) == 2:
        return parts[0] in KIND_DIRS                   # areas/x.md
    if parts[0] != "projects":
        return False
    if len(parts) == 3:
        return True                                    # projects/<이름>/x.md
    return len(parts) == 4 and parts[2] in KIND_DIRS   # projects/<이름>/areas/x.md


class _Bundle:
    def __init__(self, path: Path):
        self.path = path
        self._zip: zipfile.ZipFile | None = None
        if path.is_dir():
            self.names = [p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()]
        else:
            try:
                self._zip = zipfile.ZipFile(path)
            except (zipfile.BadZipFile, OSError) as e:
                raise ImportFailed(f"zip을 열 수 없음: {e}") from e
            self.names = [n for n in self._zip.namelist() if not n.endswith("/")]
        tops = {PurePosixPath(n).parts[0] for n in self.names if len(PurePosixPath(n).parts) > 1}
        loose = [n for n in self.names if len(PurePosixPath(n).parts) == 1]
        # 최상위 폴더 하나로 감싸진 묶음이면 그 폴더를 벗겨 낸다
        self.root = next(iter(tops)) if len(tops) == 1 and not loose and next(iter(tops)) not in KIND_DIRS + ("projects",) else ""

    def close(self):
        if self._zip:
            self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def md_names(self) -> list[str]:
        return sorted(n for n in self.names if n.endswith(".md"))

    def read_text(self, name: str) -> str:
        try:
            raw = self._zip.read(name) if self._zip else (self.path / name).read_bytes()
            return raw.decode("utf-8-sig")
        except (KeyError, OSError, zipfile.BadZipFile, UnicodeDecodeError) as e:
            raise ImportFailed(f"{name} 읽기 실패: {e}") from e

    def mtime(self, name: str) -> datetime | None:
        if self._zip:
            y, mo, d, h, mi, s = self._zip.getinfo(name).date_time
            if y <= 1980:
                return None
            return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)   # claude.ai가 UTC로 기록
        return datetime.fromtimestamp(os.path.getmtime(self.path / name), tz=timezone.utc)


class ClaudeMemoryMdImporter:
    name = "claude-ai-memory-md"

    def detect(self, path: Path) -> bool:
        path = Path(path)
        if not (path.is_dir() or zipfile.is_zipfile(path)):
            return False
        try:
            with _Bundle(path) as b:
                mds = b.md_names()
                if not mds or len(mds) != len(b.names):
                    return False                       # md 말고 다른 파일이 섞여 있으면 메모리 묶음이 아님
                rels = [_rel_parts(n, b.root) for n in mds]
                if not all(_is_memory_path(r) for r in rels):
                    return False
                if any(r[-1] == "SKILL.md" for r in rels):
                    return False
                if not any(len(r) >= 2 and (r[0] in KIND_DIRS or r[0] == "projects") for r in rels):
                    return False
                for n in mds[:3]:
                    meta, _ = split_front(b.read_text(n))
                    if not ("name" in meta and "description" in meta):
                        return False
                return True
        except ImportFailed:
            return False

    def is_full_snapshot(self) -> bool:
        return True

    def snapshot_sources(self, path: Path) -> set[str]:
        return set()   # 메모리는 문서 하나라 사라짐 처리 대상이 없다

    def snapshot_time(self, path: Path) -> datetime | None:
        with _Bundle(Path(path)) as b:
            times = [t for t in (b.mtime(n) for n in b.md_names()) if t]
            if times:
                return max(times)
            m = _DATE_IN_NAME.search(b.root or Path(path).name)
        if m:
            return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
        return None

    def iter_conversations(self, path: Path, on_skip: SkipFn | None = None) -> Iterator[Conversation]:
        skip = on_skip or (lambda msg: None)
        when = self.snapshot_time(path) or datetime(2000, 1, 1, tzinfo=timezone.utc)
        msgs: list[Message] = []
        with _Bundle(Path(path)) as b:
            for n in b.md_names():
                rel = "/" + "/".join(_rel_parts(n, b.root))
                try:
                    meta, body = split_front(b.read_text(n))
                except ImportFailed as e:
                    skip(f"메모리 파일 {rel}: {e}")
                    continue
                body = body.strip("\n")
                desc = meta.get("description", "").strip()
                text = f"> {desc}\n\n{body}" if desc and body else (f"> {desc}" if desc else body)
                if not text.strip():
                    continue
                msgs.append(Message(f"file:{rel}", "assistant", b.mtime(n) or when, text,
                                    label=f"메모리 파일: {rel}"))
        if not msgs:
            return
        times = [m.created for m in msgs]
        yield Conversation(
            conv_id=f"{SRC_MEMORY}:main", source=SRC_MEMORY, title="Claude 메모리", project="",
            created=min(times), updated=max(times + [when]), url="", messages=msgs,
        )
