import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import FIXTURES, KST, TODAY, make_export_zips

from app.archive import Archive
from app.importers.claude_code import parse_session
from app.importers.claude_export import ClaudeExportImporter
from app.index import SCHEMA_VERSION, Index, connect
from app.model import Conversation, Message
from app.redact import Redactor
from app.search import Searcher

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
GOLDEN = Path(__file__).resolve().parent / "golden_queries.example.json"


def build_synthetic_archive(root: Path, tmp: Path) -> None:
    a = Archive(root, KST, Redactor(), today=lambda: TODAY)
    imp = ClaudeExportImporter()
    for z in make_export_zips(tmp / "zips"):
        if imp.detect(z):
            for c in imp.iter_conversations(z):
                a.write(c)
    a.write(parse_session(FIXTURES / "code_session.jsonl"))


@pytest.fixture
def synth(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    build_synthetic_archive(root, tmp_path)
    idx = Index(tmp_path / "index.db")
    idx.sync(root)
    conn = connect(idx.db_path)
    yield root, idx, Searcher(conn, now=lambda: NOW)
    conn.close()


def ids(hits):
    return [h.conv_id for h in hits]


def test_index_from_md_only(synth):
    root, idx, s = synth
    assert len(s.search("")) == 8      # 대화 5 + 프로젝트 + 메모리 + Code
    assert s.search("")[0].conv_id == "claude-code:code_session"   # 최근순


def test_recreate_is_identical(synth, tmp_path):
    root, idx, s = synth
    queries = [q["query"] for q in json.loads(GOLDEN.read_text("utf-8"))]
    before = [[(h.conv_id, round(h.score, 6), [(m.ordinal, m.line_no) for m in h.matches]) for h in s.search(q)]
              for q in queries]
    s.conn.close()
    idx.delete_db()
    idx.sync(root)
    s2 = Searcher(connect(idx.db_path), now=lambda: NOW)
    after = [[(h.conv_id, round(h.score, 6), [(m.ordinal, m.line_no) for m in h.matches]) for h in s2.search(q)]
             for q in queries]
    assert before == after
    s2.conn.close()
    s.conn = connect(idx.db_path)


def test_rebuild_same_as_sync(synth):
    root, idx, s = synth
    before = ids(s.search("배포"))
    idx.rebuild(root)
    assert ids(s.search("배포")) == before


def test_conversation_level_and(synth):
    _, _, s = synth
    # '톰캣'은 사람 입력, 'AccessLogValve'는 답변: 서로 다른 메시지
    assert ids(s.search("톰캣 accesslogvalve")) == ["claude-ai:c2000000-0000-4000-8000-000000000002"]


def test_exclude(synth):
    _, _, s = synth
    with_ = ids(s.search("grafana"))
    without = ids(s.search("grafana -패널"))
    assert "claude-ai:c5000000-0000-4000-8000-000000000005" in with_
    assert without == []
    assert ids(s.search("logpick -롤백")) == ["claude-code:code_session"]


def test_english_prefix(synth):
    _, _, s = synth
    assert set(ids(s.search("logp"))) == {"claude-ai:c1000000-0000-4000-8000-000000000001",
                                          "claude-code:code_session"}
    assert ids(s.search("LOGPICK")) == ids(s.search("logpick"))


def test_hangul_spacing_ignored(synth):
    _, _, s = synth
    a = ids(s.search('"로그 배포"'))
    b = ids(s.search("로그배포"))
    assert a == b and "claude-ai:c1000000-0000-4000-8000-000000000001" in a


def test_filters(synth):
    _, _, s = synth
    assert ids(s.search("src:code")) == ["claude-code:code_session"]
    assert ids(s.search("src:project 로그")) == ["claude-ai-project:p1000000-0000-4000-8000-000000000001"]
    assert ids(s.search("src:memory")) == ["claude-ai-memory:main"]
    assert ids(s.search("proj:demo")) == ["claude-code:code_session"]
    assert ids(s.search("grafana before:2026-01")) == ["claude-ai:c5000000-0000-4000-8000-000000000005"]
    assert "claude-ai:c5000000-0000-4000-8000-000000000005" not in ids(s.search("grafana after:2026-01"))


def test_single_char_title_only(synth):
    _, _, s = synth
    # '톰'은 본문에도 있지만 제목에서만 찾는다
    assert ids(s.search("톰")) == ["claude-ai:c2000000-0000-4000-8000-000000000002"]
    assert ids(s.search("키")) == ["claude-ai:c3000000-0000-4000-8000-000000000003"]
    assert ids(s.search("롤")) == []


def test_specials_and_fts_syntax(synth):
    _, _, s = synth
    assert len(s.search("!!! ***")) == 8
    for q in ['NEAR(a b)', 'a* OR', '"', 'AND OR NOT', "x:y:z", "(", '-"']:
        s.search(q)   # 오류 없이


def test_secret_is_not_searchable(synth):
    _, _, s = synth
    assert ids(s.search("AKIAABCDEFGHIJKLMNOP")) == []
    assert ids(s.search("가림 aws")) == ["claude-ai:c3000000-0000-4000-8000-000000000003"]


def test_representative_line_matches_md(synth):
    _, _, s = synth
    for q in ("server_name", "롤백 스크립트", "fluentbit", "nginx설정", "패널"):
        for h in s.search(q):
            lines = h.path.read_text("utf-8").split("\n")
            m = h.matches[0]
            line = lines[m.line_no - 1].lower()
            core = q.replace('"', "").split()[0].lower()
            assert core in line.replace(" ", "") or core in line, (q, h.conv_id, line)
            # 강조 구간이 미리보기 안의 검색어를 가리킨다
            assert m.highlights
            s0, e0 = m.highlights[0]
            assert m.preview[s0:e0]


def test_match_navigation_data(synth):
    _, _, s = synth
    h = s.search("logpick")
    c1 = next(x for x in h if x.conv_id.endswith("c1000000-0000-4000-8000-000000000001"))
    assert c1.match_total == 2 and len(c1.matches) == 2
    assert c1.matches[0].ordinal < c1.matches[1].ordinal


def test_golden_queries(synth):
    _, _, s = synth
    golden = json.loads(GOLDEN.read_text("utf-8"))
    assert len(golden) >= 10
    for g in golden:
        got = ids(s.search(g["query"]))[: g.get("top", 5)]
        for e in g["expect"]:
            assert e in got, (g["query"], e, got)


# ---- 순위 ---------------------------------------------------------------
def _write(root, cid, title, msgs, when):
    a = Archive(root, KST)
    c = Conversation(f"claude-ai:{cid}", "claude-ai", title, "", when, when, "",
                     [Message(f"m{i}", "user" if i % 2 == 0 else "assistant", when + timedelta(minutes=i), t)
                      for i, t in enumerate(msgs)])
    a.write(c)


@pytest.fixture
def ranked(tmp_path):
    root = tmp_path / "a"
    root.mkdir()

    def make(docs):
        for d in docs:
            _write(root, *d)
        idx = Index(tmp_path / "r.db")
        idx.sync(root)
        return Searcher(connect(idx.db_path), now=lambda: NOW)
    return make


FILL = "아무 상관 없는 문장이 길게 이어집니다 날씨 이야기 점심 메뉴 이야기"


def test_title_boost(ranked):
    t = NOW - timedelta(days=10)
    s = ranked([("aaaa0001", "회의록 정리", [f"쿠버네티스 {FILL}", FILL], t),
                ("aaaa0002", "쿠버네티스 정리", [f"쿠버네티스 {FILL}", FILL], t)])
    assert ids(s.search("쿠버네티스"))[0] == "claude-ai:aaaa0002"


def test_same_message_bonus(ranked):
    t = NOW - timedelta(days=10)
    s = ranked([("bbbb0001", "메모 하나", [f"레디스 {FILL}", f"캐시 {FILL}"], t),
                ("bbbb0002", "메모 둘", [f"레디스 캐시 {FILL}", FILL], t)])
    assert ids(s.search("레디스 캐시"))[0] == "claude-ai:bbbb0002"


def test_recency_does_not_flip_relevance(ranked):
    s = ranked([("cccc0001", "메모 하나", [f"엘라스틱 엘라스틱 엘라스틱 {FILL}", FILL], NOW - timedelta(days=900)),
                ("cccc0002", "메모 둘", [f"엘라스틱 {FILL} {FILL}", FILL], NOW - timedelta(days=1))])
    assert ids(s.search("엘라스틱"))[0] == "claude-ai:cccc0001"


def test_recency_breaks_ties(ranked):
    s = ranked([("dddd0001", "메모 하나", [f"카프카 {FILL}", FILL], NOW - timedelta(days=400)),
                ("dddd0002", "메모 둘", [f"카프카 {FILL}", FILL], NOW - timedelta(days=3))])
    assert ids(s.search("카프카"))[0] == "claude-ai:dddd0002"


# ---- 대조와 예외 ---------------------------------------------------------
def test_sync_handles_add_change_remove(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    t = NOW - timedelta(days=1)
    _write(root, "eeee0001", "첫 문서", ["프로메테우스"], t)
    idx = Index(tmp_path / "i.db")
    r = idx.sync(root)
    assert r.added == 1
    p = next(root.rglob("*.md"))
    p.write_text(p.read_text("utf-8").replace("프로메테우스", "알럿매니저"), "utf-8")
    assert idx.sync(root).updated == 1
    s = Searcher(connect(idx.db_path), now=lambda: NOW)
    assert ids(s.search("알럿매니저")) == ["claude-ai:eeee0001"] and ids(s.search("프로메테우스")) == []
    p.unlink()
    assert idx.sync(root).removed == 1
    assert s.search("") == []


def test_ignores_foreign_md_and_duplicates(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    (root / "claude-ai").mkdir()
    (root / "claude-ai" / "내 메모.md").write_text("# 그냥 메모\n프로메테우스", "utf-8")
    t = NOW - timedelta(days=1)
    _write(root, "ffff0001", "원본", ["원본 내용 그라파나"], t)
    p = next(x for x in root.rglob("*_ffff0001.md"))
    dup = p.with_name(p.stem + "-PC2.md")
    text = p.read_text("utf-8")
    newer = text.replace("updated: 2026-11-06T21:00:00+09:00", "updated: 2026-11-06T22:00:00+09:00")
    newer = newer.replace("원본 내용 그라파나", "사본 내용 그라파나")
    assert newer != text
    dup.write_text(newer, "utf-8")
    idx = Index(tmp_path / "i.db")
    r = idx.sync(root)
    assert r.ignored == 1 and r.duplicates == ["claude-ai:ffff0001"]
    s = Searcher(connect(idx.db_path), now=lambda: NOW)
    hits = s.search("그라파나")
    assert len(hits) == 1 and hits[0].path == dup       # updated가 최신인 것
    assert dup.exists() and p.exists()                   # 파일은 지우지 않음


def test_corrupt_db_rebuilt(tmp_path):
    db = tmp_path / "i.db"
    db.write_bytes(b"this is not sqlite" * 100)
    idx = Index(db)
    conn = idx.open()
    assert conn.execute("SELECT count(*) FROM docs").fetchone()[0] == 0
    conn.close()


def test_schema_version_mismatch_rebuilt(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    _write(root, "gggg0001", "문서", ["내용"], NOW)
    idx = Index(tmp_path / "i.db")
    idx.sync(root)
    c = connect(idx.db_path)
    c.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
    c.commit()
    c.close()
    conn = idx.open()
    assert conn.execute("SELECT count(*) FROM docs").fetchone()[0] == 0
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(SCHEMA_VERSION)
    conn.close()
    idx.sync(root)
    assert len(Searcher(connect(idx.db_path)).search("")) == 1


def test_missing_status_shown(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    _write(root, "hhhh0001", "문서", ["내용 하나"], NOW)
    a = Archive(root, KST, today=lambda: TODAY)
    p = next(root.rglob("*.md"))
    a.set_status(p, "missing")
    idx = Index(tmp_path / "i.db")
    idx.sync(root)
    h = Searcher(connect(idx.db_path)).search("")
    assert h[0].status == "missing"


def test_partial_results_during_rebuild(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    for i in range(450):
        _write(root, f"k{i:07d}", f"문서 {i}", ["공통단어 내용"], NOW - timedelta(days=i % 30))
    idx = Index(tmp_path / "i.db")
    seen = []

    def progress(done, total):
        c = connect(idx.db_path)
        n = c.execute("SELECT count(*) FROM docs").fetchone()[0]
        c.close()
        seen.append((done, total, n))
    idx.rebuild(root, progress)
    assert seen[0][2] > 0 and seen[0][2] < 450           # 중간에도 일부 결과가 보임
    assert seen[-1] == (450, 450, 450)


def test_imported_md_indexed(tmp_path):
    """보관 폴더 imported/ 에 사람이 넣은 md(MD_IMPORT.md 형식)도 검색된다."""
    root = tmp_path / "a"
    (root / "imported" / "옆자리").mkdir(parents=True)
    (root / "imported" / "옆자리" / "x.md").write_text(
        "---\nid: codex-md:2026-11-01-deploy\nsource: codex-md\ntitle: 배포 스크립트 정리\nproject: demo\n"
        "created: 2026-11-01T10:00:00+09:00\nupdated: 2026-11-01T10:30:00+09:00\nformat_version: 1\n---\n\n"
        "# 배포 스크립트 정리\n\n<!-- bs:msg 1 user 2026-11-01T10:00:00+09:00 -->\n## 🧑 사용자\n\n"
        "젠킨스 파이프라인 고쳐 줘\n\n<!-- bs:msg 2 assistant 2026-11-01T10:01:00+09:00 -->\n## 🤖 Codex\n\n"
        "stage 순서를 바꿨습니다\n", encoding="utf-8", newline="\n")
    idx = Index(tmp_path / "i.db")
    idx.sync(root)
    h = Searcher(connect(idx.db_path), now=lambda: NOW).search("젠킨스 stage")
    assert [x.conv_id for x in h] == ["codex-md:2026-11-01-deploy"]
    assert h[0].matches[0].line_no == 16
