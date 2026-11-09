"""업무 일지 읽기 (SPEC-queue.md 3-B). Qt 없음. 일지는 읽기만 한다.

- 파일: <journal_dir>/YYYY/MM/YYYY-MM-DD.md
- 읽는 범위: `## 업무` 제목부터 다음 `#`/`##` 제목 전까지
- 항목: 들여쓰기 없는 목록 줄 `- [s] 본문` 또는 `- 본문`. 들여쓴 줄은 그 항목의 하위 내용
- 세션 연결: 항목 줄이나 하위 줄의 `[session:: <id>]`
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

SECTION = "## 업무"
_HEADING = re.compile(r"^#{1,2}\s")
_ITEM = re.compile(r"^[-*+]\s+(?:\[(.)\]\s*)?(.*)$")
_CHILD_CHECK = re.compile(r"^\s+[-*+]\s+\[(.)\]")
_SESSION = re.compile(r"\[session::\s*([^\]\s]+)\s*\]", re.IGNORECASE)
_FIELD = re.compile(r"\[[^\[\]]*?::[^\[\]]*\]")
_TAG = re.compile(r"(?<!\S)#[^\s#]+")
_SPACES = re.compile(r"\s+")

DONE, DROP, TODO, DOING = "x", "-", " ", "/"


@dataclass
class JournalEntry:
    day: date
    path: str
    line: int                  # 항목 줄 번호 (1부터)
    state: str                 # "x" 완료, "-" 버림, " " 할 일, "/" 진행 (체크 없음과 그 밖의 표시는 "/")
    text: str                  # 체크 표시를 뺀 본문 원문
    title: str                 # 정규화한 제목 (연결 안 된 항목의 id)
    sessions: list[str] = field(default_factory=list)   # 문서 id (claude-code:<uuid> 등)
    open_children: bool = False                         # 하위에 [ ] 또는 [/]가 남았는지
    children: list[str] = field(default_factory=list)   # 하위 줄 원문
    at: float = 0.0            # 흔적 시각 (유닉스 초). read_recent가 채운다

    @property
    def closed_kind(self) -> str:
        """일지 신호로 닫혔으면 "done"/"drop". 하위 할 일이 남았으면 열린 채."""
        if self.open_children:
            return ""
        return {DONE: "done", DROP: "drop"}.get(self.state, "")


def normalize_title(text: str) -> str:
    s = _FIELD.sub(" ", text)
    s = _TAG.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


def session_doc_id(raw: str) -> str:
    """`[session:: x]`의 값 -> 문서 id. 콜론이 없으면 Claude Code 세션 id로 본다."""
    raw = raw.strip()
    return raw if ":" in raw else f"claude-code:{raw}"


def _state(ch: str | None) -> str:
    if ch is None:
        return DOING
    ch = ch.lower()
    return ch if ch in (DONE, DROP, TODO, DOING) else DOING


def parse_journal(text: str, day: date, path: str = "") -> list[JournalEntry]:
    lines = text.splitlines()
    out: list[JournalEntry] = []
    inside = False
    cur: JournalEntry | None = None
    for no, line in enumerate(lines, 1):
        if not inside:
            if line.rstrip() == SECTION:
                inside = True
            continue
        if _HEADING.match(line):
            break
        if not line.strip():
            continue
        if line[0] in " \t":
            if cur is not None:
                cur.children.append(line)
                m = _CHILD_CHECK.match(line)
                if m and _state(m.group(1)) in (TODO, DOING):
                    cur.open_children = True
            continue
        cur = None
        m = _ITEM.match(line)
        if not m:
            continue                       # 목록이 아닌 글은 무시
        body = m.group(2).strip()
        title = normalize_title(body)
        if not title:
            continue                       # 빈 항목, 태그만 있는 항목
        cur = JournalEntry(day, path, no, _state(m.group(1)), body, title)
        out.append(cur)
    for e in out:
        ids = []
        for s in [e.text, *e.children]:
            for raw in _SESSION.findall(s):
                did = session_doc_id(raw)
                if did not in ids:
                    ids.append(did)
        e.sessions = ids
    return out


def journal_path(root: Path, day: date) -> Path:
    return Path(root) / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y-%m-%d}.md"


def entry_time(day: date, mtime: float | None) -> float:
    """일지 항목의 흔적 시각: 그날 23:59, 단 파일을 그 전에 마지막으로 고쳤으면 그 시각.
    (오늘 일지에 [x]를 적은 뒤 새 대화를 하면 다시 열리게)"""
    start = datetime.combine(day, time(0, 0)).timestamp()
    end = datetime.combine(day, time(23, 59)).timestamp()
    if mtime is None:
        return end
    return max(start, min(end, mtime))


class JournalReader:
    """최근 일지를 읽는다. 파일 크기와 수정 시각이 같으면 앞서 읽은 결과를 쓴다."""

    def __init__(self):
        self._cache: dict[str, tuple[float, int, list[JournalEntry]]] = {}

    def read_recent(self, root: Path | str, today: date, days: int) -> list[JournalEntry]:
        """today부터 거슬러 days+1일치 (SPEC: queue_days + 1)."""
        out: list[JournalEntry] = []
        seen = set()
        for i in range(days + 1):
            d = today - timedelta(days=i)
            p = journal_path(Path(root), d)
            key = str(p)
            seen.add(key)
            try:
                st = os.stat(p)
            except OSError:
                continue
            hit = self._cache.get(key)
            if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
                out.extend(hit[2])
                continue
            try:
                text = p.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            entries = parse_journal(text, d, key)
            at = entry_time(d, st.st_mtime)
            for e in entries:
                e.at = at
            self._cache[key] = (st.st_mtime, st.st_size, entries)
            out.extend(entries)
        for k in [k for k in self._cache if k not in seen]:
            del self._cache[k]
        return out
