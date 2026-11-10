"""열린 일 큐 계산 (SPEC-queue.md 3-A). Qt 없음.

일 하나 = 채팅(Claude Code 세션, claude.ai 대화) 또는 노트 하나.
마지막 흔적이 queue_days일 안이고 닫히지 않았으면 열린 일이다.
닫은 뒤 더 늦은 흔적이 생기면 다시 열린다.
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

QUEUE_SOURCES = ("claude-code", "claude-ai", "note")   # 색인 문서 중 큐에 오르는 것. 그 밖에 "journal"(연결 안 된 일지 항목)
DAY = 86400.0
CLOSE_KINDS = ("done", "drop")
REOPEN = "open"
STATE_LABEL = {" ": "할 일", "/": "진행", "x": "완료", "-": "버림"}
_JOURNAL_REL = re.compile(r"^\d{4}[\\/]\d{2}[\\/]\d{4}-\d{2}-\d{2}\.md$", re.IGNORECASE)


@dataclass
class QueueDoc:
    """색인 docs 한 줄에서 큐에 필요한 것만."""
    conv_id: str
    source: str
    title: str
    project: str
    path: str
    updated_ts: float      # 채팅: 마지막 메시지 시각
    mtime: float           # 노트: 파일 수정 시각
    line: int = 1          # 열 때 갈 줄 (채팅은 마지막 메시지)


@dataclass
class QueueItem:
    id: str
    source: str
    title: str
    project: str
    path: str
    line: int
    trace_ts: float                     # 마지막 흔적 (유닉스 초)
    closed_kind: str = ""               # 닫은 일 목록에서만: "done" | "drop"
    closed_at: float = 0.0
    subtitle: str = ""                  # 연결된 일지 항목 한 줄 (2단계)
    summary: str = ""                   # 저장된 요약 첫 줄
    summary_text: str = ""              # 저장된 요약 전체
    summary_stale: bool = False         # 요약 뒤 새 흔적이 생김
    journal: list = field(default_factory=list)   # 연결된 일지 항목 (연결 안 된 일지 일은 자기 항목들)


@dataclass
class QueueResult:
    focus: list[QueueItem] = field(default_factory=list)
    rest: list[QueueItem] = field(default_factory=list)
    closed: list[QueueItem] = field(default_factory=list)   # 최근 닫은 일 (닫은 시각 늦은 순)
    days: int = 14

    @property
    def open_count(self) -> int:
        return len(self.focus) + len(self.rest)


# ---- 경로 ----------------------------------------------------------------
def _norm(p: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _under(path_norm: str, dir_norm: str) -> bool:
    return path_norm == dir_norm or path_norm.startswith(dir_norm.rstrip("\\/") + os.sep)


@dataclass
class Filters:
    """큐에서 뺄 경로. 모두 절대 경로."""
    exclude_dirs: list[str] = field(default_factory=list)   # 노트 제외 폴더, 보관 폴더 imported
    journal_dir: str = ""                                   # 일지 보관함 루트 (그 아래 YYYY/MM/YYYY-MM-DD.md 제외)

    @classmethod
    def build(cls, note_roots: list[Path], note_exclude: list[str], archive_dir: Path | None,
              journal_dir: str = "") -> "Filters":
        ex = []
        for root in note_roots:
            for rel in note_exclude or []:
                rel = str(rel).strip().strip("\\/")
                if rel:
                    ex.append(_norm(Path(root) / rel))
        if archive_dir:
            ex.append(_norm(Path(archive_dir) / "imported"))
        return cls(ex, _norm(journal_dir) if journal_dir else "")

    def excluded(self, path: str) -> bool:
        p = _norm(path)
        if any(_under(p, d) for d in self.exclude_dirs):
            return True
        if self.journal_dir and _under(p, self.journal_dir):
            rel = p[len(self.journal_dir):].lstrip("\\/")
            if _JOURNAL_REL.match(rel):
                return True
        return False


# ---- 계산 ----------------------------------------------------------------
def trace_of(doc: QueueDoc) -> float:
    return doc.mtime if doc.source == "note" else doc.updated_ts


def closed_ts(rec) -> tuple[str, float] | None:
    """queue_closed 기록 하나 -> (종류, 시각). 종류는 done/drop 또는 open(다시 열기). 형식이 이상하면 None."""
    if not isinstance(rec, dict) or rec.get("kind") not in (*CLOSE_KINDS, REOPEN):
        return None
    at = rec.get("at")
    try:
        if isinstance(at, (int, float)):
            ts = float(at)
        else:
            ts = datetime.fromisoformat(str(at)).timestamp()
    except (TypeError, ValueError):
        return None
    return rec["kind"], ts


def _latest(entries: list) -> object:
    """가장 늦은 날짜의 일지 항목 (같은 날이면 파일에서 뒤에 있는 것)."""
    return max(entries, key=lambda e: (e.day, e.line))


def compute(docs: list[QueueDoc], closed: dict, now: float, days: int = 14, focus: int = 5,
            filters: Filters | None = None, journal: list | None = None) -> QueueResult:
    """문서 목록, 일지 항목(journal.JournalEntry), 닫힘 기록으로 열린 일 목록을 만든다.

    - 일지 항목이 [session::]으로 가리키는 채팅에는 그 항목 날짜의 흔적이 더해진다.
    - 연결된(또는 같은 제목의) 일지 항목 중 가장 늦은 것이 [x]/[-]이고 남은 하위 할 일이 없으면 닫힘.
    - 직접 닫기와 일지 닫기 모두, 닫은 시각보다 늦은 흔적이 있으면 다시 열린다.
    """
    since = now - days * DAY
    closed = closed or {}
    by_id = {d.conv_id: d for d in docs if d.source in QUEUE_SOURCES}
    linked: dict[str, list] = {}
    unlinked: dict[str, list] = {}
    for e in journal or []:
        ids = [i for i in e.sessions if i in by_id]
        if ids:
            for i in ids:
                linked.setdefault(i, []).append(e)
        else:
            unlinked.setdefault(e.title, []).append(e)

    candidates: list[tuple[QueueItem, list]] = []
    for d in by_id.values():
        ents = linked.get(d.conv_id, [])
        trace = max([trace_of(d), *(e.at for e in ents)])
        if trace < since:
            continue
        if filters and filters.excluded(d.path):
            continue
        it = QueueItem(d.conv_id, d.source, d.title, d.project, d.path, d.line, trace)
        if ents:
            last = _latest(ents)
            it.subtitle = f"일지 {last.day:%m-%d} · {STATE_LABEL.get(last.state, '')} · {last.title}"
        it.journal = list(ents)
        candidates.append((it, ents))
    for title, ents in unlinked.items():
        last = _latest(ents)
        trace = max(e.at for e in ents)
        if trace < since:
            continue
        it = QueueItem(f"journal:{title}", "journal", title, "", last.path, last.line, trace, journal=list(ents))
        candidates.append((it, ents))

    open_items: list[QueueItem] = []
    closed_items: list[QueueItem] = []
    for it, ents in candidates:
        closes = []
        c = closed_ts(closed.get(it.id))
        if c:
            closes.append(c)
        if ents:
            last = _latest(ents)
            if last.closed_kind:
                closes.append((last.closed_kind, last.at))
        c = max(closes, key=lambda x: x[1]) if closes else None
        if c and c[0] in CLOSE_KINDS and c[1] >= it.trace_ts:
            it.closed_kind, it.closed_at = c
            if c[1] >= since:
                closed_items.append(it)
            continue
        open_items.append(it)
    open_items.sort(key=lambda i: (-i.trace_ts, i.id))
    closed_items.sort(key=lambda i: (-i.closed_at, i.id))
    n = max(0, int(focus))
    return QueueResult(open_items[:n], open_items[n:], closed_items, days)


def close(closed: dict, item_id: str, kind: str, now: datetime | None = None) -> None:
    if kind not in CLOSE_KINDS:
        raise ValueError(kind)
    at = (now or datetime.now(timezone.utc).astimezone()).isoformat(timespec="seconds")
    closed[item_id] = {"kind": kind, "at": at}


def reopen(closed: dict, item_id: str, now: datetime | None = None) -> None:
    """다시 열기. 일지 [x]로 닫힌 일도 열리도록 '열림' 기록을 남긴다(이후 더 늦은 [x]가 오면 다시 닫힘)."""
    at = (now or datetime.now(timezone.utc).astimezone()).isoformat(timespec="seconds")
    closed[item_id] = {"kind": REOPEN, "at": at}


def prune(closed: dict, now: float, keep_days: int) -> int:
    """오래된 닫힘 기록을 지운다(닫은 일 보기에도 안 나오고, 흔적도 그 전이라 의미 없음)."""
    old = [k for k, v in closed.items() if (c := closed_ts(v)) is None or c[1] < now - keep_days * DAY]
    for k in old:
        del closed[k]
    return len(old)


# ---- 색인 읽기 -------------------------------------------------------------
_DOC_COLS = """d.conv_id, d.source, d.title, d.project, d.path, d.updated_ts, d.md_mtime,
                   CASE WHEN d.source='note' THEN 1 ELSE
                     (SELECT max(m.line_no) FROM messages m WHERE m.doc_id=d.id AND m.is_branch=0) END"""


def load_docs(conn: sqlite3.Connection, since: float, extra_ids=()) -> list[QueueDoc]:
    """색인에서 흔적이 since 뒤인 큐 대상 문서를 읽는다. 채팅은 마지막 본문(가지 아님) 메시지 줄을 같이.
    extra_ids: 흔적이 오래됐어도 읽을 문서 id (일지가 가리키는 채팅)."""
    marks = ",".join("?" for _ in QUEUE_SOURCES)
    rows = conn.execute(
        f"""SELECT {_DOC_COLS} FROM docs d
            WHERE d.source IN ({marks})
              AND ((d.source='note' AND d.md_mtime>=?) OR (d.source!='note' AND d.updated_ts>=?))""",
        (*QUEUE_SOURCES, since, since)).fetchall()
    got = {r[0] for r in rows}
    rest = [i for i in dict.fromkeys(extra_ids) if i not in got]
    for k in range(0, len(rest), 500):
        part = rest[k:k + 500]
        rows += conn.execute(
            f"""SELECT {_DOC_COLS} FROM docs d
                WHERE d.source IN ({marks}) AND d.conv_id IN ({",".join("?" for _ in part)})""",
            (*QUEUE_SOURCES, *part)).fetchall()
    return [QueueDoc(r[0], r[1], r[2] or "", r[3] or "", r[4] or "", float(r[5] or 0), float(r[6] or 0),
                     int(r[7] or 1)) for r in rows]


# ---- 표시 도우미 -----------------------------------------------------------
def relative_time(ts: float, now: float) -> str:
    s = now - ts
    if s < 0:
        return "오늘"          # 시계가 어긋난 경우
    if s < 60:
        return "방금"
    if s < 3600:
        return f"{int(s // 60)}분 전"
    if s < DAY:
        return f"{int(s // 3600)}시간 전"
    then = datetime.fromtimestamp(ts).date()
    today = datetime.fromtimestamp(now).date()
    dd = (today - then).days
    if dd <= 1:
        return "어제"
    return f"{dd}일 전"
