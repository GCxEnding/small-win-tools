"""보관본(md): 렌더링, 파일 이름, 변경 판정, missing 처리, 원자적 저장."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from pathlib import Path
from typing import Callable

from .model import Conversation, Message
from .timeutil import fmt_iso, local_tz, parse_iso

FORMAT_VERSION = 1
MARKER = "<!-- bs:msg"
MARKER_ESCAPED = "<!-- bs\\:msg"
APPENDIX = "## 부록: 다른 가지"
FRONT_KEYS = ("id", "source", "title", "project", "created", "updated", "url", "messages",
              "source_status", "missing_since", "format_version")

_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
SLUG_LEN = 60

SOURCE_DIRS = {"claude-ai": "claude-ai", "claude-code": "claude-code", "chatgpt": "chatgpt"}
# 보관 폴더에서 도구가 읽고 쓰는 하위 폴더. 이 밖의 md는 보지 않는다 (보관 폴더가 드라이브 최상위여도 안전)
IMPORTED_DIR = "imported"   # 사람이 직접 넣는 md (MD_IMPORT.md 형식). 도구는 읽기만 하고 고치지 않는다
ARCHIVE_SUBDIRS = ("claude-ai", "claude-code", "chatgpt", IMPORTED_DIR)


def md_files(root: Path):
    for sub in ARCHIVE_SUBDIRS:
        d = Path(root) / sub
        if d.is_dir():
            yield from d.rglob("*.md")


def slugify(title: str) -> str:
    s = _FORBIDDEN_RE.sub("", title or "")
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-{2,}", "-", s)
    s = s[:SLUG_LEN].strip(" .-")
    if not s:
        s = "제목-없음"
    if s.split(".")[0].lower() in _RESERVED:
        s = "_" + s
    return s


def _one_line(s: str) -> str:
    return " ".join(str(s).split())


# ---- frontmatter --------------------------------------------------------
def read_front(text: str) -> dict[str, str] | None:
    if "\r" in text[:8192]:
        text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 3)
    if end < 0:
        return None
    meta: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        k, sep, v = line.partition(":")
        if sep:
            meta[k.strip()] = v[1:] if v.startswith(" ") else v
    return meta


def read_front_file(path: Path) -> dict[str, str] | None:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            head = f.read(4096)
            if "\n---\n" not in head[3:]:
                head += f.read(60000)
    except (OSError, UnicodeDecodeError):
        return None
    return read_front(head)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ---- 렌더링 --------------------------------------------------------------
def _escape(text: str) -> str:
    return text.replace(MARKER, MARKER_ESCAPED)


def render(conv: Conversation, tz: tzinfo, status: str = "present", missing_since: str = "",
           redact: Callable[[str], str] | None = None) -> str:
    red = redact or (lambda s: s)
    title = _one_line(red(conv.title)) or "(제목 없음)"
    front = {
        "id": conv.conv_id, "source": conv.source, "title": title, "project": _one_line(conv.project),
        "created": fmt_iso(conv.created, tz), "updated": fmt_iso(conv.updated, tz), "url": conv.url,
        "messages": str(len(conv.messages)), "source_status": status,
        "missing_since": missing_since if status == "missing" else "", "format_version": str(FORMAT_VERSION),
    }
    out = ["---", *(f"{k}: {front[k]}" for k in FRONT_KEYS), "---", "", f"# {title}", ""]
    main = [m for m in conv.messages if m.on_main_branch]
    branch = [m for m in conv.messages if not m.on_main_branch]
    n = 0
    for group, is_branch in ((main, False), (branch, True)):
        if is_branch and group:
            out += [APPENDIX, ""]
        for m in group:
            n += 1
            out += _render_msg(n, m, tz, is_branch, red)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def _render_msg(n: int, m: Message, tz: tzinfo, is_branch: bool, red) -> list[str]:
    ts = m.created.astimezone(tz)
    mark = f"{MARKER} {n} {m.role} {ts.isoformat(timespec='seconds')}{' branch' if is_branch else ''} -->"
    if m.label:
        head = f"## 📄 {_one_line(m.label)}"
    else:
        who = "🧑 사용자" if m.role == "user" else "🤖 Claude"
        head = f"## {who} ({ts.strftime('%Y-%m-%d %H:%M')}){' [다른 가지]' if is_branch else ''}"
    body = _escape(red(m.text.replace("\r\n", "\n").replace("\r", "\n"))).strip("\n")
    return [mark, head, "", body, ""]


# ---- 보관 폴더 -----------------------------------------------------------
@dataclass
class WriteResult:
    status: str          # "new" | "changed" | "same" | "older"
    path: Path
    old_path: Path | None = None   # 이름이 바뀐 경우 이전 경로


class ArchiveMissing(Exception):
    pass


class Archive:
    def __init__(self, root: Path, tz: tzinfo | None = None, redact: Callable[[str], str] | None = None,
                 today: Callable[[], date] | None = None):
        self.root = Path(root)
        self.tz = tz or local_tz()
        self.redact = redact
        self.today = today or date.today
        self._suffix_map: dict[str, list[Path]] | None = None

    def check(self) -> None:
        if not self.root.is_dir():
            raise ArchiveMissing(f"보관 폴더가 없습니다: {self.root}")

    # 파일 이름 접미사(ID 앞 8/12자) -> 경로들
    def _map(self) -> dict[str, list[Path]]:
        if self._suffix_map is None:
            m: dict[str, list[Path]] = {}
            for p in md_files(self.root):
                stem = p.stem
                if "_" in stem:
                    m.setdefault(stem.rsplit("_", 1)[1], []).append(p)
            self._suffix_map = m
        return self._suffix_map

    def _map_add(self, path: Path, old: Path | None = None) -> None:
        m = self._map()
        if old is not None:
            for lst in m.values():
                if old in lst:
                    lst.remove(old)
        stem = path.stem
        if "_" in stem:
            lst = m.setdefault(stem.rsplit("_", 1)[1], [])
            if path not in lst:
                lst.append(path)

    def find(self, conv_id: str) -> Path | None:
        source, _, native = conv_id.partition(":")
        if source == "claude-ai-memory":
            p = self.root / "claude-ai" / "memories.md"
            return p if p.exists() else None
        for n in (12, 8):
            for p in self._map().get(native[:n], []):
                if p.exists():
                    meta = read_front_file(p)
                    if meta and meta.get("id") == conv_id:
                        return p
        return None

    def _id_len(self, conv_id: str) -> int:
        native = conv_id.partition(":")[2]
        for p in self._map().get(native[:8], []):
            if p.exists():
                meta = read_front_file(p)
                if meta and meta.get("id") and meta.get("id") != conv_id:
                    return 12
        return 8

    def target_path(self, conv: Conversation) -> Path:
        native = conv.native_id
        if conv.source == "claude-ai-memory":
            return self.root / "claude-ai" / "memories.md"
        idn = native[:self._id_len(conv.conv_id)]
        if conv.source == "claude-ai-project":
            return self.root / "claude-ai" / "projects" / f"{slugify(conv.title)}_{idn}.md"
        base = SOURCE_DIRS.get(conv.source, conv.source)
        d = conv.created.astimezone(self.tz)
        return self.root / base / f"{d:%Y}" / f"{d:%Y-%m-%d}_{slugify(conv.title)}_{idn}.md"

    def write(self, conv: Conversation, status: str = "present", missing_since: str | None = None,
              skip_if_older: bool = False) -> WriteResult:
        self.check()
        existing = self.find(conv.conv_id)
        old_text = None
        old_meta = None
        if existing is not None:
            try:
                old_text = existing.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                old_text = None
            old_meta = read_front(old_text) if old_text is not None else None
        if skip_if_older and old_meta:
            old_upd = parse_iso(old_meta.get("updated"))
            if old_upd and conv.updated < old_upd:
                return WriteResult("older", existing)
        if status == "missing" and missing_since is None:
            if old_meta and old_meta.get("source_status") == "missing" and old_meta.get("missing_since"):
                missing_since = old_meta["missing_since"]
            else:
                missing_since = self.today().isoformat()
        text = render(conv, self.tz, status, missing_since or "", self.redact)
        if existing is not None:
            # 제목이 바뀐 경우 같은 ID 길이를 유지한 새 이름으로
            target = existing if self._same_name(existing, conv) else self._renamed(existing, conv)
        else:
            target = self.target_path(conv)
        if existing is not None and target == existing and old_text == text:
            return WriteResult("same", existing)
        if existing is not None and target != existing:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(existing, target)
            self._map_add(target, existing)
        if existing is not None and old_text == text:
            return WriteResult("changed", target, existing)
        atomic_write(target, text)
        self._map_add(target)
        return WriteResult("new" if existing is None else "changed", target,
                           existing if existing is not None and existing != target else None)

    def _same_name(self, existing: Path, conv: Conversation) -> bool:
        return existing == self._renamed(existing, conv)

    def _renamed(self, existing: Path, conv: Conversation) -> Path:
        if conv.source == "claude-ai-memory":
            return existing
        idn = existing.stem.rsplit("_", 1)[1] if "_" in existing.stem else conv.native_id[:8]
        if conv.source == "claude-ai-project":
            return existing.parent / f"{slugify(conv.title)}_{idn}.md"
        d = conv.created.astimezone(self.tz)
        return existing.parent / f"{d:%Y-%m-%d}_{slugify(conv.title)}_{idn}.md"

    def set_status(self, path: Path, status: str) -> bool:
        """frontmatter의 source_status만 바꾼다. 바뀌었으면 True."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        meta = read_front(text)
        if not meta or meta.get("source_status") == status:
            return False
        since = self.today().isoformat() if status == "missing" else ""
        end = text.find("\n---\n", 3)
        lines = text[:end].split("\n")
        for i, line in enumerate(lines):
            if line.startswith("source_status:"):
                lines[i] = f"source_status: {status}"
            elif line.startswith("missing_since:"):
                lines[i] = f"missing_since: {since}"
        atomic_write(path, "\n".join(lines) + text[end:])
        return True

    def iter_docs(self, sources: set[str]) -> list[tuple[Path, dict[str, str]]]:
        """보관 폴더의 md 중 frontmatter source가 sources에 속하는 것."""
        out = []
        for p in md_files(self.root):
            if IMPORTED_DIR in p.relative_to(self.root).parts[:1]:
                continue   # 직접 넣은 md는 missing 처리 대상이 아님
            meta = read_front_file(p)
            if meta and meta.get("source") in sources and meta.get("id"):
                out.append((p, meta))
        return out
