import sqlite3
from datetime import date

import pytest

from app.query import parse


def test_words_are_and():
    q = parse("로그 배포")
    assert [t.tokens for t in q.terms] == [["로그"], ["배포"]]
    assert q.fts_expr() == '"로그" AND "배포"'


def test_english_prefix():
    q = parse("log")
    assert q.terms[0].prefix
    assert q.fts_expr() == '"log" *'


def test_hangul_word_phrase_no_prefix():
    q = parse("배포를")
    assert q.terms[0].tokens == ["배포", "포를"] and not q.terms[0].prefix
    assert q.fts_expr() == '"배포 포를"'


def test_phrase():
    q = parse('"로그 배포" nginx')
    assert q.terms[0].phrase and q.terms[0].tokens == ["로그", "그배", "배포"]
    assert q.terms[1].tokens == ["nginx"]
    assert not q.terms[0].prefix


def test_unclosed_phrase():
    q = parse('"로그 배포')
    assert q.terms[0].phrase


def test_exclude():
    q = parse("배포 -롤백 -\"예전 가지\"")
    assert [t.tokens for t in q.terms] == [["배포"]]
    assert [t.tokens for t in q.excludes] == [["롤백"], ["예전", "전가", "가지"]]


def test_filters():
    q = parse("src:code proj:Small after:2026-10 before:2026-11-05 배포")
    assert q.sources == ["claude-code"]
    assert q.projects == ["small"]
    assert q.after == date(2026, 10, 1)
    assert q.before == date(2026, 11, 5)
    assert [t.tokens for t in q.terms] == [["배포"]]


@pytest.mark.parametrize("src,expect", [("ai", "claude-ai"), ("project", "claude-ai-project"),
                                        ("memory", "claude-ai-memory")])
def test_source_aliases(src, expect):
    assert parse(f"src:{src}").sources == [expect]


def test_unknown_filter_is_text():
    q = parse("foo:bar src:nothing after:yesterday")
    assert [t.tokens for t in q.terms] == [["foo", "bar"], ["src", "nothing"], ["after", "yesterday"]]
    assert not q.sources and q.after is None


def test_single_char_title_only():
    q = parse("배 a 로그")
    assert q.title_terms == ["배", "a"]
    assert [t.tokens for t in q.terms] == [["로그"]]


def test_empty_and_specials():
    for text in ("", "   ", "!!! *** ()", '"" -'):
        q = parse(text)
        assert not q.terms and not q.title_terms and not q.excludes


def test_filters_only():
    q = parse("src:ai after:2026-01")
    assert not q.has_text and q.sources == ["claude-ai"]


def test_combination():
    q = parse('src:code "nginx 설정" -롤백 배포 x')
    assert q.sources == ["claude-code"]
    assert len(q.terms) == 2 and len(q.excludes) == 1 and q.title_terms == ["x"]


@pytest.mark.parametrize("text", ['a* OR b', 'NEAR(a b)', '"', 'AND', 'x"y', "col:val", "^start", "a AND OR NOT b",
                                  "-", "--", "(", "{x}", "a:*"])
def test_fts_special_chars_never_break(text):
    q = parse(text)
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
    con.execute("INSERT INTO t VALUES ('a b and or not near col val start')")
    if q.terms:
        con.execute("SELECT * FROM t WHERE t MATCH ?", (q.fts_expr(),)).fetchall()
    if q.excludes:
        con.execute("SELECT * FROM t WHERE t MATCH ?", (q.exclude_expr(),)).fetchall()


def test_filter_labels():
    q = parse("src:code proj:abc -롤백")
    assert q.filter_labels() == ["src:code", "proj:abc", "-롤백"]
