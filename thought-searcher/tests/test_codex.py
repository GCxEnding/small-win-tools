import json
import sqlite3
from datetime import datetime, timezone

from conftest import KST

from app.archive import Archive, read_front_file
from app.codex import collect, convert_thread, imported_sessions, read_threads
from app.model import Conversation, Message
from app.search import search

T = 1793000000   # 초


def _user(text):
    return json.dumps({"type": "userMessage", "id": "x", "content": [{"type": "text", "text": text, "text_elements": []}]})


def _agent(text):
    return json.dumps({"type": "agentMessage", "id": "y", "text": text, "phase": None})


def make_codex(home, threads, items, imports=None):
    """threads: [(id, title, cwd, created, updated)], items: {id: [(type, json)]}"""
    home.mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(home / "state_5.sqlite")
    s.execute("CREATE TABLE threads(id TEXT, rollout_path TEXT, created_at INT, updated_at INT, source TEXT,"
              " cwd TEXT, title TEXT, archived INT)")
    for tid, title, cwd, c, u in threads:
        s.execute("INSERT INTO threads VALUES(?,?,?,?,?,?,?,0)", (tid, "", c, u, "vscode", cwd, title))
    s.commit()
    s.close()
    h = sqlite3.connect(home / "thread_history_1.sqlite")
    h.execute("CREATE TABLE thread_items(thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal INT,"
              " created_at_ms INT, item_json TEXT, item_type TEXT)")
    for tid, rows in items.items():
        for i, (it, js) in enumerate(rows):
            h.execute("INSERT INTO thread_items VALUES(?,?,?,?,?,?,?)",
                      (tid, "t1", f"item-{i}", i * 2, (T + i) * 1000, js, it))
    h.commit()
    h.close()
    (home / "state_4.sqlite").write_bytes(b"")          # 예전 번호는 무시해야 함
    if imports is not None:
        (home / "external_agent_session_imports.json").write_text(json.dumps({"records": [
            {"imported_thread_id": tid, "source_path": f"C:\\Users\\u\\.claude\\projects\\D--x\\{sid}.jsonl",
             "title": "t"} for tid, sid in imports.items()]}), encoding="utf-8")
    return home


NATIVE = ("t-native", "카프카 컨슈머 정리", "D:\\work\\stream-app", T, T + 50)
NATIVE_ITEMS = [
    ("userMessage", _user("컨슈머 그룹 리밸런싱이 자꾸 일어나")),
    ("agentMessage", _agent("session.timeout.ms 를 먼저 보세요.")),
    ("agentMessage", _agent("[external_agent_tool_call: Bash]\ninput: ls")),
    ("agentMessage", _agent("max.poll.interval.ms 도 같이요.")),
    ("userMessage", _user("<local-command-stdout>x</local-command-stdout>")),
    ("userMessage", _user("[Request interrupted by user]")),
]


def test_convert_filters_tools_and_merges(tmp_path):
    home = make_codex(tmp_path / ".codex", [NATIVE], {"t-native": NATIVE_ITEMS})
    threads, items = read_threads(home)
    c = convert_thread(threads[0], items["t-native"])
    assert c.conv_id == "codex:t-native" and c.source == "codex" and c.project == "stream-app"
    assert [m.role for m in c.messages] == ["user", "assistant"]
    assert c.messages[1].text == "session.timeout.ms 를 먼저 보세요.\n\nmax.poll.interval.ms 도 같이요."
    assert c.created == datetime.fromtimestamp(T, tz=timezone.utc)


def test_imported_sessions_map(tmp_path):
    home = make_codex(tmp_path / ".codex", [], {}, imports={"t-imp": "abc-123"})
    assert imported_sessions(home) == {"t-imp": "abc-123"}


def test_collect_skips_claude_code_duplicates(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    a = Archive(arch, KST)
    t0 = datetime.fromtimestamp(T, tz=timezone.utc)
    a.write(Conversation("claude-code:abc-123", "claude-code", "이미 있는 세션", "p", t0, t0, "",
                         [Message("m", "user", t0, "본문")]))
    imp_dup = ("t-dup", "옮겨 온 세션", "D:\\p", T, T)
    imp_orphan = ("t-orphan", "원본이 지워진 세션", "D:\\p", T, T)
    rows = [("userMessage", _user("질문")), ("agentMessage", _agent("답"))]
    home = make_codex(tmp_path / ".codex", [NATIVE, imp_dup, imp_orphan],
                      {"t-native": NATIVE_ITEMS, "t-dup": rows, "t-orphan": rows},
                      imports={"t-dup": "abc-123", "t-orphan": "gone-999"})
    state = {}
    r = collect(home, a, state)
    assert (r.new, r.skipped_dup) == (2, 1)
    assert a.find("codex:t-dup") is None and a.find("codex:t-orphan") is not None
    assert sorted(p.name.split("_")[0] for p in (arch / "codex").rglob("*.md")) == ["2026-10-26", "2026-10-26"]
    # 다시 돌려도 변화 없음
    r2 = collect(home, a, state)
    assert (r2.new, r2.changed) == (0, 0)


def test_collect_marks_deleted_threads_missing(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    a = Archive(arch, KST)
    home = make_codex(tmp_path / "c1", [NATIVE], {"t-native": NATIVE_ITEMS})
    collect(home, a, {})
    empty = make_codex(tmp_path / "c2", [], {})
    assert collect(empty, a, {}).missing == 1
    assert read_front_file(a.find("codex:t-native"))["source_status"] == "missing"


def test_no_codex_folder_is_quiet(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    r = collect(tmp_path / "없음", Archive(arch, KST), {})
    assert (r.new, r.changed, r.missing) == (0, 0, 0)


def test_core_collect_and_search(core_env, tmp_path):
    make_codex(tmp_path / "codex", [NATIVE], {"t-native": NATIVE_ITEMS})
    res = core_env.collect_code()
    assert res.new == 1
    hits = search("리밸런싱 src:codex", db_path=core_env.index.db_path)
    assert [h.conv_id for h in hits] == ["codex:t-native"]
    assert "Codex 1" in core_env.status_text()
