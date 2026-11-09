"""Codex(OpenAI) 대화 수집.

Codex 데스크톱/CLI는 대화 원본을 `~/.codex/sessions/**/rollout-*.jsonl.zst`(zstd 압축)로 두는데,
Python 3.13 표준 라이브러리로는 zstd를 풀 수 없다. 대신 Codex가 같이 관리하는 SQLite를 읽기 전용으로 연다.
  state_<N>.sqlite          : threads(id, title, cwd, created_at, updated_at, archived ...)
  thread_history_<N>.sqlite : thread_items(thread_id, rollout_ordinal, item_type, item_json, created_at_ms ...)
item_type이 userMessage, agentMessage인 것만 쓴다. 도구 실행, 생각 과정 등 다른 항목은 뺀다.

Claude Code 세션을 Codex로 옮겨 온 대화(external_agent_session_imports.json에 기록)는
같은 세션의 Claude Code md가 보관 폴더에 있으면 건너뛴다(중복 방지). 원본이 지워져 Codex에만 남은 것만 들어온다.
옮겨 온 대화의 '[external_agent_tool_call: ...]', '[external_agent_tool_result]' 메시지는 도구 호출이라 뺀다.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from .archive import Archive
from .importers.claude_code import user_text
from .model import Conversation, Message

log = logging.getLogger("thought-searcher")

SOURCE = "codex"
TITLE_LEN = 60
RENDER_VERSION = 1
_TOOL_PREFIX = "[external_agent_tool_"
_USER_SKIP = ("[Request interrupted", "[external unsupported")
_NUM_RE = re.compile(r"_(\d+)\.sqlite$")


@dataclass
class CodexResult:
    new: int = 0
    changed: int = 0
    same: int = 0
    skipped_dup: int = 0      # Claude Code md가 이미 있어 건너뜀
    missing: int = 0
    written: list[Path] = field(default_factory=list)


def _latest_db(home: Path, prefix: str) -> Path | None:
    best = None
    for p in home.glob(f"{prefix}_*.sqlite"):
        m = _NUM_RE.search(p.name)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p)
    return best[1] if best else None


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5)


def _ts(sec) -> datetime | None:
    if isinstance(sec, (int, float)) and sec > 0:
        if sec > 1e12:          # 밀리초
            sec = sec / 1000
        return datetime.fromtimestamp(sec, tz=timezone.utc)
    return None


def _project(cwd: str) -> str:
    if not cwd:
        return ""
    return PureWindowsPath(cwd).name if ("\\" in cwd or ":" in cwd) else Path(cwd).name


def imported_sessions(home: Path) -> dict[str, str]:
    """Codex thread id -> 옮겨 온 Claude Code 세션 id(원본 jsonl 파일 이름)."""
    p = home / "external_agent_session_imports.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    out = {}
    for r in data.get("records") or [] if isinstance(data, dict) else []:
        if not isinstance(r, dict):
            continue
        tid, src = r.get("imported_thread_id"), str(r.get("source_path") or "")
        if tid and src.lower().endswith(".jsonl"):
            out[str(tid)] = PureWindowsPath(src).stem if "\\" in src else Path(src).stem
    return out


def _agent_text(t: str) -> str:
    t = (t or "").strip("\n")
    if t.startswith(_TOOL_PREFIX):
        return ""
    return t


def _user_text(content) -> str:
    if isinstance(content, str):
        raw = content
    else:
        raw = "\n\n".join(str(c.get("text") or "") for c in content or []
                          if isinstance(c, dict) and c.get("type") == "text")
    if raw.lstrip().startswith(_USER_SKIP):
        return ""
    return user_text(raw)


def read_threads(home: Path) -> tuple[list[dict], dict[str, list[tuple]]] | None:
    """(threads, thread_id -> [(ordinal, item_type, item_json, created_ms)]). DB가 없으면 None."""
    state_db = _latest_db(home, "state")
    hist_db = _latest_db(home, "thread_history")
    if state_db is None or hist_db is None:
        return None
    with closing(_connect_ro(state_db)) as s:
        s.row_factory = sqlite3.Row
        threads = [dict(r) for r in s.execute(
            "SELECT id, title, cwd, created_at, updated_at, archived FROM threads")]
    items: dict[str, list[tuple]] = {}
    with closing(_connect_ro(hist_db)) as h:
        for tid, ordn, it, js, cms in h.execute(
                "SELECT thread_id, rollout_ordinal, item_type, item_json, created_at_ms FROM thread_items "
                "WHERE item_type IN ('userMessage', 'agentMessage') ORDER BY thread_id, rollout_ordinal"):
            items.setdefault(tid, []).append((ordn, it, js, cms))
    return threads, items


def convert_thread(th: dict, rows: list[tuple]) -> Conversation | None:
    tid = str(th["id"])
    created = _ts(th.get("created_at"))
    messages: list[Message] = []
    pending: list[str] = []
    pending_meta: tuple[str, datetime] | None = None

    def flush():
        nonlocal pending, pending_meta
        if pending and pending_meta:
            messages.append(Message(pending_meta[0], "assistant", pending_meta[1], "\n\n".join(pending)))
        pending, pending_meta = [], None

    for ordn, it, js, cms in rows:
        try:
            j = json.loads(js)
        except (TypeError, ValueError):
            continue
        when = _ts(cms) or created or datetime(2000, 1, 1, tzinfo=timezone.utc)
        mid = f"{ordn}"
        if it == "userMessage":
            body = _user_text(j.get("content"))
            if not body.strip():
                continue
            flush()
            messages.append(Message(mid, "user", when, body))
        else:
            body = _agent_text(j.get("text"))
            if not body.strip():
                continue
            if pending_meta is None:
                pending_meta = (mid, when)
            pending.append(body)          # 이어지는 답변 글은 한 메시지로
    flush()
    if not messages:
        return None
    times = [m.created for m in messages]
    title = " ".join(str(th.get("title") or "").split())
    if not title:
        first = next((m.text for m in messages if m.role == "user"), "")
        title = " ".join(first.split())[:TITLE_LEN].strip() or "(제목 없음)"
    created = created or min(times)
    updated = max([_ts(th.get("updated_at")) or created] + times)
    return Conversation(
        conv_id=f"{SOURCE}:{tid}", source=SOURCE, title=title[:200], project=_project(str(th.get("cwd") or "")),
        created=min(created, min(times)), updated=updated, url="", messages=messages,
    )


def collect(home: Path, archive: Archive, state: dict, force: bool = False) -> CodexResult:
    res = CodexResult()
    if not home.is_dir():
        return res
    try:
        data = read_threads(home)
    except sqlite3.Error as e:
        log.warning("Codex DB 읽기 실패: %s", e)
        return res
    if data is None:
        return res
    threads, items = data
    imported = imported_sessions(home)
    seen_state = state.setdefault("codex_threads", {})
    if state.get("codex_render_version") != RENDER_VERSION:
        force = True
    alive: set[str] = set()
    for th in threads:
        tid = str(th["id"])
        alive.add(f"{SOURCE}:{tid}")
        rows = items.get(tid, [])
        key = [th.get("updated_at"), len(rows), rows[-1][0] if rows else 0]
        dup_of = imported.get(tid)
        if dup_of and archive.find(f"claude-code:{dup_of}") is not None:
            res.skipped_dup += 1
            seen_state[tid] = key + ["dup"]
            continue
        if not force and seen_state.get(tid) == key and archive.find(f"{SOURCE}:{tid}") is not None:
            continue
        conv = convert_thread(th, rows)
        seen_state[tid] = key
        if conv is None:
            continue
        r = archive.write(conv, status="present")
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
    # Codex에서 지운 대화: md는 두고 missing 표시
    for p, meta in archive.iter_docs({SOURCE}):
        if meta["id"] not in alive and archive.set_status(p, "missing"):
            res.missing += 1
            res.written.append(p)
    state["codex_render_version"] = RENDER_VERSION
    return res
