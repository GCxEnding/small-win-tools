"""메시지 시각 색인(created_ts)과 메시지 기준 기간 검색, 채팅 시각. 합성 데이터만 쓴다."""
import sqlite3
from datetime import datetime, timedelta, timezone

from conftest import KST

from app.archive import Archive
from app.index import SCHEMA_VERSION, Index, connect
from app.model import Conversation, Message
from app.search import Searcher

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
YEAR_AGO = datetime(2025, 11, 7, 10, 0, tzinfo=KST)
YESTERDAY = datetime(2026, 11, 6, 15, 30, tzinfo=KST)


def _conv(root, cid, title, msgs):
    """msgs: [(본문, 시각)]. 대화 마지막 시각(updated)은 마지막 메시지 시각."""
    c = Conversation(f"claude-ai:{cid}", "claude-ai", title, "", msgs[0][1], msgs[-1][1], "",
                     [Message(f"m{i}", "user" if i % 2 == 0 else "assistant", t, text)
                      for i, (text, t) in enumerate(msgs)])
    Archive(root, KST).write(c)


def _searcher(tmp_path, convs):
    root = tmp_path / "a"
    root.mkdir()
    for c in convs:
        _conv(root, *c)
    idx = Index(tmp_path / "i.db")
    idx.sync(root)
    return Searcher(connect(idx.db_path), now=lambda: NOW)


def ids(hits):
    return [h.conv_id for h in hits]


def test_old_match_with_new_unrelated_message_is_excluded(tmp_path):
    s = _searcher(tmp_path, [
        ("aaaa0001", "옛날 대화", [("쿠버네티스 배포 질문", YEAR_AGO), ("점심 메뉴 이야기", YESTERDAY)]),
        ("aaaa0002", "최근 대화", [("쿠버네티스 배포 질문", YESTERDAY), ("점심 메뉴 이야기", YESTERDAY + timedelta(minutes=1))]),
    ])
    assert set(ids(s.search("쿠버네티스"))) == {"claude-ai:aaaa0001", "claude-ai:aaaa0002"}
    # 대화 마지막 시각은 둘 다 어제지만, 맞은 메시지가 1주 안에 있는 것은 하나뿐이다
    assert ids(s.search("쿠버네티스 after:2026-10-31")) == ["claude-ai:aaaa0002"]
    assert ids(s.search("쿠버네티스 before:2026-01-01")) == ["claude-ai:aaaa0001"]
    assert ids(s.search("쿠버네티스 after:2025-11-01 before:2025-12-01")) == ["claude-ai:aaaa0001"]


def test_chat_time_is_matched_message_time_not_doc_updated(tmp_path):
    t1, t2 = datetime(2026, 10, 1, 10, 0, tzinfo=KST), datetime(2026, 10, 5, 9, 0, tzinfo=KST)
    s = _searcher(tmp_path, [
        ("bbbb0001", "캐시 설정", [("레디스 설정", t1), ("답변 드립니다", t1 + timedelta(minutes=1)),
                               ("레디스 다시", t2), ("잡담입니다", YESTERDAY)]),
    ])
    h = s.search("레디스")[0]
    assert h.chat_time == t2
    assert h.updated == YESTERDAY            # 문서 시각은 그대로
    # 기간이 있으면 그 안에서 고른다
    h = s.search("레디스 before:2026-10-03")[0]
    assert h.chat_time == t1
    assert h.chat_time.tzinfo is not None


def test_matches_are_restricted_to_the_period(tmp_path):
    t1, t2 = datetime(2026, 10, 1, 10, 0, tzinfo=KST), datetime(2026, 10, 5, 9, 0, tzinfo=KST)
    s = _searcher(tmp_path, [
        ("cccc0001", "캐시 설정", [("레디스 설정", t1), ("답변", t1 + timedelta(minutes=1)), ("레디스 다시", t2)]),
    ])
    all_ = s.search("레디스")[0]
    assert [m.ordinal for m in all_.matches] == [1, 3] and all_.match_total == 2
    late = s.search("레디스 after:2026-10-03")[0]
    assert [m.ordinal for m in late.matches] == [3] and late.match_total == 1
    early = s.search("레디스 before:2026-10-03")[0]
    assert [m.ordinal for m in early.matches] == [1] and early.match_total == 1


def test_period_uses_any_matched_message(tmp_path):
    """검색어가 서로 다른 메시지에 나뉘어도, 그중 하나(검색어 중 하나에 맞은 메시지)가 기간 안이면 남긴다."""
    t_old = datetime(2026, 9, 1, 10, 0, tzinfo=KST)
    s = _searcher(tmp_path, [
        ("dddd0001", "나뉜 대화", [("레디스 질문", t_old), ("답변", t_old + timedelta(minutes=1)), ("캐시 질문", YESTERDAY)]),
    ])
    h = s.search("레디스 캐시 after:2026-11-01")
    assert ids(h) == ["claude-ai:dddd0001"]
    assert [m.ordinal for m in h[0].matches] == [3]
    assert h[0].chat_time == YESTERDAY


def test_title_only_match_falls_back_to_doc_time(tmp_path):
    t_old = datetime(2026, 9, 1, 10, 0, tzinfo=KST)
    s = _searcher(tmp_path, [
        ("eeee0001", "프로메테우스 정리", [("지표 수집 이야기", t_old), ("그래프 이야기", YESTERDAY)]),
        ("eeee0002", "프로메테우스 옛 정리", [("지표 수집 이야기", t_old), ("그래프 이야기", t_old + timedelta(hours=1))]),
    ])
    h = s.search("프로메테우스 after:2026-11-01")
    assert ids(h) == ["claude-ai:eeee0001"]                  # 대화 마지막 시각 기준
    assert h[0].chat_time == YESTERDAY
    assert h[0].matches and h[0].matches[0].ordinal == 2     # 맞은 메시지가 없으니 기간 안의 첫 메시지
    # 기간이 없으면 대화 마지막 시각이 채팅 시각
    assert {x.conv_id: x.chat_time for x in s.search("프로메테우스")}["claude-ai:eeee0002"] == t_old + timedelta(hours=1)


def test_title_match_does_not_rescue_out_of_period_body_match(tmp_path):
    """제목과 본문에 다 맞고 본문 메시지가 모두 기간 밖이면, 대화 마지막 시각이 최근이어도 제외."""
    s = _searcher(tmp_path, [
        ("ffff0001", "쿠버네티스 메모", [("쿠버네티스 질문", YEAR_AGO), ("잡담", YESTERDAY)]),
    ])
    assert s.search("쿠버네티스 after:2026-10-31") == []


def test_no_words_behaviour_unchanged(tmp_path):
    s = _searcher(tmp_path, [
        ("gggg0001", "옛날 대화", [("쿠버네티스 배포 질문", YEAR_AGO), ("점심 메뉴 이야기", YESTERDAY)]),
        ("gggg0002", "아주 옛날", [("쿠버네티스", YEAR_AGO), ("잡담", YEAR_AGO + timedelta(hours=1))]),
    ])
    # 단어 없이 칩만: 지금처럼 대화 마지막 시각 기준
    h = s.search("after:2026-10-31")
    assert ids(h) == ["claude-ai:gggg0001"]
    assert h[0].chat_time == YESTERDAY
    assert [m.ordinal for m in h[0].matches] == [1]          # 첫 메시지 (바뀌지 않음)


def test_message_times_are_indexed(tmp_path):
    s = _searcher(tmp_path, [("hhhh0001", "대화", [("하나", YEAR_AGO), ("둘", YESTERDAY)])])
    rows = s.conn.execute("SELECT ordinal, created_ts FROM messages ORDER BY ordinal").fetchall()
    assert [r[1] for r in rows] == [YEAR_AGO.timestamp(), YESTERDAY.timestamp()]


def test_unusable_message_time_falls_back_to_doc_updated(tmp_path):
    root = tmp_path / "a"
    (root / "imported").mkdir(parents=True)
    (root / "imported" / "x.md").write_text(
        "---\nid: codex-md:2026-11-01-x\nsource: codex-md\ntitle: 시각 없는 메모\nproject: demo\n"
        "created: 2026-11-01T10:00:00+09:00\nupdated: 2026-11-03T10:30:00+09:00\nformat_version: 1\n---\n\n"
        "# 시각 없는 메모\n\n<!-- bs:msg 1 user - -->\n## 🧑 사용자\n\n젠킨스 파이프라인\n", encoding="utf-8", newline="\n")
    idx = Index(tmp_path / "i.db")
    idx.sync(root)
    conn = connect(idx.db_path)
    ts, upd = conn.execute("SELECT m.created_ts, d.updated_ts FROM messages m JOIN docs d ON d.id=m.doc_id").fetchone()
    assert ts == upd == datetime(2026, 11, 3, 10, 30, tzinfo=KST).timestamp()
    h = Searcher(conn, now=lambda: NOW).search("젠킨스 after:2026-11-02")
    assert ids(h) == ["codex-md:2026-11-01-x"] and h[0].chat_time == datetime(2026, 11, 3, 10, 30, tzinfo=KST)
    assert Searcher(conn, now=lambda: NOW).search("젠킨스 after:2026-11-04") == []


def test_notes_use_doc_time(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "2026-11-06.md").write_text("---\ndate: 2026-11-06\n---\n# 일지\n\n## 업무\n배포 점검\n\n## 메모\n로그 정리\n",
                                         encoding="utf-8")
    root = tmp_path / "a"
    root.mkdir()
    idx = Index(tmp_path / "i.db")
    idx.note_roots = [vault]
    idx.sync(root)
    conn = connect(idx.db_path)
    rows = conn.execute("SELECT m.created_ts, d.updated_ts FROM messages m JOIN docs d ON d.id=m.doc_id").fetchall()
    assert rows and all(a == b and a > 0 for a, b in rows)      # 구역마다 시각이 없으니 문서 시각
    s = Searcher(conn, now=lambda: NOW)
    h = s.search("배포 after:2026-11-05")
    assert len(h) == 1 and h[0].chat_time == h[0].updated
    assert s.search("배포 after:2026-11-07") == []


def test_schema_v1_index_is_rebuilt_from_md(tmp_path):
    """스키마 1(created_ts 없음) 색인 파일은 열 때 새로 만들어지고, 다음 대조에서 md로 채워진다."""
    assert SCHEMA_VERSION == 2
    root = tmp_path / "a"
    root.mkdir()
    _conv(root, "iiii0001", "대화", [("쿠버네티스 질문", YEAR_AGO), ("점심", YESTERDAY)])
    db = tmp_path / "i.db"
    old = sqlite3.connect(db)
    old.executescript(
        "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
        "INSERT INTO meta VALUES('schema_version','1');"
        "CREATE TABLE docs(id INTEGER PRIMARY KEY, conv_id TEXT);"
        "CREATE TABLE messages(id INTEGER PRIMARY KEY, doc_id INTEGER, ordinal INTEGER, role TEXT, line_no INTEGER,"
        " body_line INTEGER, is_branch INTEGER, text TEXT);"
        "INSERT INTO docs VALUES(1,'x'); INSERT INTO messages VALUES(1,1,1,'user',1,2,0,'t');")
    old.commit()
    old.close()
    idx = Index(db)
    conn = idx.open()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
    assert "created_ts" in cols
    assert conn.execute("SELECT count(*) FROM docs").fetchone()[0] == 0
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
    conn.close()
    res = idx.sync(root)                  # 앱 시작 때 start_jobs가 하는 일
    assert res.added == 1
    s = Searcher(connect(db), now=lambda: NOW)
    assert ids(s.search("쿠버네티스 before:2026-01-01")) == ["claude-ai:iiii0001"]
