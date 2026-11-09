"""열린 일 큐 (SPEC-queue.md 3-A, 12번 test_queue.py 중 1단계 범위).

일지 연결(`[x]` 닫힘, 하위 `[ ]`, 가장 늦은 날짜 항목, 연결 안 된 항목)은 2단계에서 이 파일에 더한다.
"""
import json
import os
import time
from datetime import datetime, timedelta

import pytest

from app import queue
from app.index import Index, connect
from app.queue import DAY, Filters, QueueDoc, compute

NOW = datetime(2026, 11, 9, 15, 0).timestamp()
H = 3600.0


def doc(cid, ago, source="claude-code", path=None, mtime_ago=None, title=None, line=1):
    """ago: 마지막 메시지가 몇 초 전인지. 노트는 mtime_ago(없으면 ago)."""
    upd = NOW - ago
    mt = NOW - (mtime_ago if mtime_ago is not None else ago)
    return QueueDoc(cid, source, title or cid, "proj", path or f"C:/archive/{cid.replace(':', '_')}.md",
                    upd, mt, line)


def ids(items):
    return [i.id for i in items]


# ---- 열림 판정 ---------------------------------------------------------------
def test_14_day_boundary():
    docs = [doc("claude-code:a", 13 * DAY + 23 * H), doc("claude-code:b", 14 * DAY + 1 * H)]
    res = compute(docs, {}, NOW, days=14)
    assert ids(res.focus) == ["claude-code:a"]
    assert res.rest == [] and res.closed == []


def test_sorted_latest_first_and_focus_split():
    docs = [doc(f"claude-code:{i}", i * H) for i in range(8)]
    res = compute(list(reversed(docs)), {}, NOW, focus=5)
    assert ids(res.focus) == [f"claude-code:{i}" for i in range(5)]
    assert ids(res.rest) == [f"claude-code:{i}" for i in range(5, 8)]
    assert res.open_count == 8


def test_focus_larger_than_count():
    res = compute([doc("claude-code:x", H)], {}, NOW, focus=5)
    assert ids(res.focus) == ["claude-code:x"] and res.rest == []


def test_empty_queue():
    res = compute([], {}, NOW)
    assert res.open_count == 0 and res.days == 14


@pytest.mark.parametrize("source", ["codex", "chatgpt", "claude-ai-project", "claude-ai-memory", "codex-md"])
def test_excluded_sources(source):
    res = compute([doc(f"{source}:1", H, source=source), doc("claude-ai:2", H, source="claude-ai")], {}, NOW)
    assert ids(res.focus) == ["claude-ai:2"]


def test_included_sources():
    docs = [doc("claude-code:1", H), doc("claude-ai:2", 2 * H, source="claude-ai"),
            doc("note:c:/notes/a.md", 3 * H, source="note", path="C:/notes/a.md")]
    assert len(compute(docs, {}, NOW).focus) == 3


def test_note_trace_uses_file_mtime():
    """오래된 날짜 노트를 오늘 고치면 열린 일, 날짜가 최근이어도 파일이 오래됐으면 숨김."""
    old_date_new_file = doc("note:c:/n/old.md", 300 * DAY, source="note", path="C:/n/old.md", mtime_ago=H)
    new_date_old_file = doc("note:c:/n/new.md", H, source="note", path="C:/n/new.md", mtime_ago=30 * DAY)
    res = compute([old_date_new_file, new_date_old_file], {}, NOW)
    assert ids(res.focus) == ["note:c:/n/old.md"]
    assert res.focus[0].trace_ts == pytest.approx(NOW - H)


# ---- 경로 제외 ---------------------------------------------------------------
def test_note_exclude_dirs_and_imported(tmp_path):
    notes, arch = tmp_path / "vault", tmp_path / "archive"
    f = Filters.build([notes], ["template", "gohome/", ""], arch)
    docs = [
        doc("note:a", H, "note", str(notes / "work" / "a.md")),
        doc("note:t", H, "note", str(notes / "template" / "t.md")),
        doc("note:g", H, "note", str(notes / "gohome" / "2026" / "g.md")),
        doc("note:tx", H, "note", str(notes / "templates-old" / "x.md")),   # 이름만 비슷한 폴더는 남김
        doc("claude-ai:imp", H, "claude-ai", str(arch / "imported" / "x.md")),
        doc("claude-ai:ok", H, "claude-ai", str(arch / "claude-ai" / "2026" / "y.md")),
    ]
    res = compute(docs, {}, NOW, filters=f)
    assert sorted(ids(res.focus)) == ["claude-ai:ok", "note:a", "note:tx"]


def test_journal_files_excluded(tmp_path):
    vault = tmp_path / "vault"
    f = Filters.build([vault], [], None, str(vault))
    docs = [
        doc("note:j", H, "note", str(vault / "2026" / "11" / "2026-11-09.md")),
        doc("note:k", H, "note", str(vault / "2026" / "11" / "회의록.md")),     # 일지 형식이 아닌 파일은 남김
        doc("note:l", H, "note", str(vault / "projects" / "2026-11-09.md")),   # 위치가 다르면 남김
    ]
    assert sorted(ids(compute(docs, {}, NOW, filters=f).focus)) == ["note:k", "note:l"]


def test_journal_dir_off_keeps_dated_notes(tmp_path):
    vault = tmp_path / "vault"
    f = Filters.build([vault], [], None, "")
    d = doc("note:j", H, "note", str(vault / "2026" / "11" / "2026-11-09.md"))
    assert ids(compute([d], {}, NOW, filters=f).focus) == ["note:j"]


# ---- 직접 닫기 ---------------------------------------------------------------
def _at(ago):
    return datetime.fromtimestamp(NOW - ago).astimezone().isoformat(timespec="seconds")


@pytest.mark.parametrize("kind", ["done", "drop"])
def test_closed_hidden_and_listed(kind):
    docs = [doc("claude-code:a", 2 * H), doc("claude-code:b", 3 * H)]
    closed = {"claude-code:a": {"kind": kind, "at": _at(H)}}
    res = compute(docs, closed, NOW)
    assert ids(res.focus) == ["claude-code:b"]
    assert ids(res.closed) == ["claude-code:a"]
    assert res.closed[0].closed_kind == kind


@pytest.mark.parametrize("kind", ["done", "drop"])
def test_reopens_on_new_trace(kind):
    docs = [doc("claude-code:a", 10 * 60)]     # 닫은 뒤(1시간 전) 10분 전에 새 메시지
    closed = {"claude-code:a": {"kind": kind, "at": _at(H)}}
    res = compute(docs, closed, NOW)
    assert ids(res.focus) == ["claude-code:a"]
    assert res.focus[0].closed_kind == "" and res.closed == []


def test_closed_list_only_recent_days():
    docs = [doc("claude-code:a", 13 * DAY)]
    closed = {"claude-code:a": {"kind": "done", "at": _at(12 * DAY)}}
    assert ids(compute(docs, closed, NOW, days=14).closed) == ["claude-code:a"]
    # 흔적은 14일 안이지만 닫은 시각이 이상하게 오래된 경우는 없음. 닫은 기록이 깨졌으면 열린 일로 본다
    bad = {"claude-code:a": {"kind": "weird", "at": "x"}}
    assert ids(compute(docs, bad, NOW).focus) == ["claude-code:a"]


def test_closed_order_latest_closed_first():
    docs = [doc("claude-code:a", 5 * H), doc("claude-code:b", 6 * H)]
    closed = {"claude-code:a": {"kind": "done", "at": _at(4 * H)}, "claude-code:b": {"kind": "drop", "at": _at(H)}}
    assert ids(compute(docs, closed, NOW).closed) == ["claude-code:b", "claude-code:a"]


def test_close_reopen_prune_helpers():
    closed = {}
    queue.close(closed, "claude-code:a", "done")
    assert closed["claude-code:a"]["kind"] == "done"
    with pytest.raises(ValueError):
        queue.close(closed, "x", "later")
    queue.reopen(closed, "claude-code:a")
    assert closed == {}
    closed = {"old": {"kind": "done", "at": _at(40 * DAY)}, "new": {"kind": "drop", "at": _at(DAY)},
              "bad": {"kind": "done"}}
    assert queue.prune(closed, NOW, 28) == 2
    assert list(closed) == ["new"]


def test_relative_time():
    assert queue.relative_time(NOW - 10, NOW) == "방금"
    assert queue.relative_time(NOW - 5 * 60, NOW) == "5분 전"
    assert queue.relative_time(NOW - 3 * H, NOW) == "3시간 전"
    assert queue.relative_time(NOW - 3 * DAY, NOW) == "3일 전"


# ---- 색인 읽기와 Core ---------------------------------------------------------
def _fill(conn, rows):
    """docs/messages에 직접 넣는다. rows: (conv_id, source, updated_ts, md_mtime, [(line, is_branch)])"""
    with conn:
        for cid, src, upd, mt, msgs in rows:
            cur = conn.execute(
                "INSERT INTO docs(conv_id, path, title, source, project, updated, updated_ts, status, md_mtime,"
                " md_size, msg_count) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (cid, f"C:/a/{abs(hash(cid))}.md", cid, src, "p", "", upd, "present", mt, 10, len(msgs)))
            for n, (line, br) in enumerate(msgs, 1):
                conn.execute("INSERT INTO messages(doc_id, ordinal, role, line_no, body_line, is_branch, text)"
                             " VALUES(?,?,?,?,?,?,?)", (cur.lastrowid, n, "user", line, line + 2, br, "t"))


@pytest.fixture
def db(tmp_path):
    idx = Index(tmp_path / "index.db")
    idx.open().close()
    conn = connect(tmp_path / "index.db")
    yield conn
    conn.close()


def test_load_docs_filters_and_last_line(db):
    _fill(db, [
        ("claude-ai:a", "claude-ai", NOW - H, NOW - 30 * DAY, [(10, 0), (20, 0), (40, 1)]),   # 가지 줄 40은 무시
        ("claude-code:old", "claude-code", NOW - 20 * DAY, NOW, [(5, 0)]),                  # 채팅은 mtime 무시
        ("note:n", "note", NOW - 300 * DAY, NOW - H, [(1, 0), (9, 0)]),
        ("codex:c", "codex", NOW - H, NOW - H, [(3, 0)]),
    ])
    docs = {d.conv_id: d for d in queue.load_docs(db, NOW - 14 * DAY)}
    assert set(docs) == {"claude-ai:a", "note:n"}
    assert docs["claude-ai:a"].line == 20
    assert docs["note:n"].line == 1


def test_core_close_persists_and_reopen(core_env, db):
    core = core_env
    _fill(db, [("claude-code:a", "claude-code", NOW - H, 0, [(7, 0)]),
               ("claude-code:b", "claude-code", NOW - 2 * H, 0, [(7, 0)])])
    assert ids(core.compute_queue(db, NOW).focus) == ["claude-code:a", "claude-code:b"]
    core.close_item("claude-code:a", "done")
    saved = json.loads(core.store.state_path.read_text(encoding="utf-8"))
    assert saved["queue_closed"]["claude-code:a"]["kind"] == "done"
    # 닫은 시각(실제 지금)이 흔적보다 늦으므로 닫힘
    res = core.compute_queue(db, NOW)
    assert "claude-code:a" not in ids(res.focus)
    core.reopen_item("claude-code:a")
    assert ids(core.compute_queue(db, NOW).focus) == ["claude-code:a", "claude-code:b"]


def test_core_uses_config(core_env, db, tmp_path):
    core = core_env
    vault = tmp_path / "vault"
    core.config.update({"queue_days": 3, "queue_focus": 1, "note_dirs": [str(vault)],
                        "queue_note_exclude": ["template"], "journal_dir": str(vault)})
    with db:
        for cid, p, ago in [("note:a", vault / "a.md", H), ("note:t", vault / "template" / "t.md", H),
                            ("note:j", vault / "2026" / "11" / "2026-11-09.md", H),
                            ("note:old", vault / "old.md", 4 * DAY), ("note:b", vault / "b.md", 2 * H)]:
            db.execute("INSERT INTO docs(conv_id, path, title, source, updated_ts, md_mtime) VALUES(?,?,?,?,?,?)",
                       (cid, str(p), cid, "note", 0, NOW - ago))
    res = core.compute_queue(db, NOW)
    assert ids(res.focus) == ["note:a"] and ids(res.rest) == ["note:b"] and res.days == 3


# ---- 성능 -----------------------------------------------------------------
def test_queue_2000_docs_fast(db):
    rows = []
    for i in range(2000):
        src = ("claude-code", "claude-ai", "note", "codex")[i % 4]
        rows.append((f"{src}:{i}", src, NOW - (i % 40) * DAY / 2, NOW - (i % 40) * DAY / 2,
                     [(j * 10, 0) for j in range(1, 30)]))
    _fill(db, rows)
    closed = {f"claude-code:{i}": {"kind": "done", "at": _at(0)} for i in range(0, 400, 4)}
    best = 1e9
    for _ in range(3):
        t0 = time.perf_counter()
        res = compute(queue.load_docs(db, NOW - 14 * DAY), closed, NOW, filters=Filters.build([], [], None))
        best = min(best, (time.perf_counter() - t0) * 1000)
    assert res.open_count > 500
    assert best < 50, f"{best:.1f}ms"


# ---- 창 (화면 없이) -------------------------------------------------------------
@pytest.fixture
def window(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    qtw = pytest.importorskip("PySide6.QtWidgets")
    app = qtw.QApplication.instance() or qtw.QApplication([])
    from app.window import SearchWindow
    w = SearchWindow()
    yield w
    w.close()
    w.deleteLater()
    app.processEvents()


def _kinds(w):
    from app.window import ROLE_KIND
    return [w.list.item(i).data(ROLE_KIND) for i in range(w.list.count())]


def test_window_queue_rows_toggle_and_keys(window):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent

    w = window
    docs = [doc(f"claude-code:{i}", i * H) for i in range(7)]
    closed_docs = [doc("claude-code:z", 9 * H)]
    res = compute(docs + closed_docs, {"claude-code:z": {"kind": "drop", "at": _at(8 * H)}}, NOW)
    w.set_queue(res, "s", NOW)
    assert _kinds(w) == ["focus"] * 5 + ["rest", "closed"]
    # 접은 줄을 Enter로 펼침
    w.list.setCurrentRow(5)
    w._emit("open")
    assert _kinds(w) == ["focus"] * 5 + ["rest", "row", "row", "closed"]
    got = []
    w.action.connect(lambda k, item, _i: got.append((k, item.id)))
    w.list.setCurrentRow(0)
    w.edit.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_F4, Qt.NoModifier))
    w.edit.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_F4, Qt.ShiftModifier))
    w._emit("open")
    # 닫은 일에서 F4 = 다시 열기
    w._toggle("closed")
    w.list.setCurrentRow(w.list.count() - 1)
    w.edit.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_F4, Qt.NoModifier))
    assert got == [("done", "claude-code:0"), ("drop", "claude-code:0"), ("open", "claude-code:0"),
                   ("reopen", "claude-code:z")]


def test_window_empty_queue_and_search_mode(window):
    w = window
    w.set_queue(compute([], {}, NOW), "s", NOW)
    assert _kinds(w) == ["empty"]
    got = []
    w.action.connect(lambda *a: got.append(a))
    w._emit("open")
    w._item_key("done")
    assert got == []
    w.set_results([], "결과 없음")
    assert w.mode == "search" and w.list.count() == 0
