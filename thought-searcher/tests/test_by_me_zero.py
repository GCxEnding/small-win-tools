"""by:me, 내 질문 칩, 한영 자동 보정, 0건 안내. 합성 데이터만 쓴다."""
import os
from datetime import datetime, timedelta, timezone

import pytest

from conftest import KST

from app import hangul
from app.archive import Archive
from app.index import Index, connect
from app.model import Conversation, Message
from app.query import parse, strip_tokens, token_kind
from app.search import Searcher
from app.zero import ZeroHint, eul_reul, search_all, without, zero_hint

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def d(mo, day, h=10):
    return datetime(2026, mo, day, h, 0, tzinfo=KST)


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    qtw = pytest.importorskip("PySide6.QtWidgets")
    app = qtw.QApplication.instance() or qtw.QApplication([])
    yield app
    app.processEvents()


def _conv(root, cid, title, msgs, source="claude-ai", project=""):
    """msgs: [(role, 본문, 시각)]"""
    c = Conversation(f"{source}:{cid}", source, title, project, msgs[0][2], msgs[-1][2], "",
                     [Message(f"m{i}", role, t, text) for i, (role, text, t) in enumerate(msgs)])
    Archive(root, KST).write(c)


def _searcher(tmp_path, convs, notes=None):
    root = tmp_path / "a"
    root.mkdir(parents=True)
    for c in convs:
        _conv(root, c[0], c[1], c[2], **(c[3] if len(c) > 3 else {}))
    idx = Index(tmp_path / "i.db")
    if notes:
        idx.note_roots = [notes]
    idx.sync(root)
    return Searcher(connect(idx.db_path), now=lambda: NOW)


def ids(hits):
    return sorted(h.conv_id.split(":", 1)[1] for h in hits)


# ---- 검색어 문법 -------------------------------------------------------------------
def test_parse_by_me_and_token_helpers():
    assert parse("배포 by:me").by_me and parse("배포 by:나").by_me and parse("by:ME").by_me
    q = parse("배포 by:me")
    assert [t.text for t in q.terms] == ["배포"] and "by:me" in q.filter_labels()
    assert not parse("배포 by:you").by_me and [t.text for t in parse("by:you").terms] == ["by:you"]
    assert token_kind("src:ai") == "source" and token_kind("proj:x") == "project" and token_kind("after:2026-10") == "period"
    assert token_kind("before:2026-10-02") == "period" and token_kind("by:나") == "mine" and token_kind("-롤백") == "exclude"
    assert token_kind('-"a b"') == "exclude" and token_kind("배포") is None and token_kind("src:zzz") is None
    assert token_kind("after:xx") is None


def test_strip_tokens_removes_only_the_kind():
    t = '배포 src:ai proj:x after:2026-10 by:me -롤백 "구문 둘" -"a b" src:code'
    assert strip_tokens(t, {"source"}) == '배포 proj:x after:2026-10 by:me -롤백 "구문 둘" -"a b"'
    assert strip_tokens(t, {"period"}) == '배포 src:ai proj:x by:me -롤백 "구문 둘" -"a b" src:code'
    assert strip_tokens(t, {"mine"}) == '배포 src:ai proj:x after:2026-10 -롤백 "구문 둘" -"a b" src:code'
    assert strip_tokens(t, {"exclude"}) == '배포 src:ai proj:x after:2026-10 by:me "구문 둘" src:code'
    assert strip_tokens(t, {"source", "period", "project", "mine", "exclude"}) == '배포 "구문 둘"'
    assert strip_tokens("", {"source"}) == ""


# ---- by:me -------------------------------------------------------------------------
def test_by_me_inclusion_and_exclusion(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "2026-11-06.md").write_text("---\ndate: 2026-11-06\n---\n# 메모\n\n레디스 정리 노트\n", encoding="utf-8")
    s = _searcher(tmp_path, [
        ("aaaa0001", "내가 물음", [("user", "레디스 설정이 궁금합니다", d(11, 1)), ("assistant", "답변입니다", d(11, 1, 11))]),
        ("bbbb0001", "답에만 있음", [("user", "다른 질문", d(11, 2)), ("assistant", "레디스는 이렇게 씁니다", d(11, 2, 11))]),
        ("cccc0001", "나뉜 질문", [("user", "레디스 질문", d(11, 3)), ("assistant", "네", d(11, 3, 11)),
                                ("user", "캐시도 궁금합니다", d(11, 3, 12))]),
        ("dddd0001", "답에 나뉨", [("user", "레디스 질문", d(11, 4)), ("assistant", "캐시 답변", d(11, 4, 11))]),
        ("eeee0001", "카프카 정리", [("user", "그냥 질문", d(11, 5)), ("assistant", "답", d(11, 5, 11))]),
        ("pppp0001", "프로젝트 문서", [("assistant", "레디스 지침 문서", d(11, 6))], {"source": "claude-ai-project"}),
    ], notes=vault)
    assert {"aaaa0001", "bbbb0001", "cccc0001", "dddd0001"} <= set(ids(s.search("레디스")))
    got = ids(s.search("레디스 by:me"))
    assert got == ["aaaa0001", "cccc0001", "dddd0001"]               # 노트, 프로젝트 문서, 답에만 있는 대화는 빠진다
    assert ids(s.search("레디스 by:나")) == got
    # 단어가 서로 다른 사용자 메시지에 있어도 된다 / 사용자 메시지와 답에 나뉘면 빠진다
    assert ids(s.search("레디스 캐시 by:me")) == ["cccc0001"]
    assert "dddd0001" in ids(s.search("레디스 캐시"))
    # 제목에만 있는 단어는 세지 않는다
    assert ids(s.search("카프카")) == ["eeee0001"] and s.search("카프카 by:me") == []
    # 다른 조건과 같이: 개수만 세는 길도 같은 답
    assert s.count("레디스 by:me") == 3 and s.count("레디스") >= 4
    assert s.count("레디스 by:me after:2026-11-03") == 2


def test_by_me_matches_preview_and_chat_time_use_user_messages_only(tmp_path):
    s = _searcher(tmp_path, [
        ("ffff0001", "엘라스틱", [("user", "엘라스틱 질문", d(11, 1)), ("assistant", "엘라스틱 답변 엘라스틱", d(11, 8)),
                              ("user", "엘라스틱 또 질문", d(11, 3))]),
    ])
    plain = s.search("엘라스틱", sort="recent")[0]
    mine = s.search("엘라스틱 by:me", sort="recent")[0]
    assert [m.ordinal for m in plain.matches] == [2, 3, 1] and plain.chat_time == d(11, 8)
    assert [m.ordinal for m in mine.matches] == [3, 1] and mine.match_total == 2
    assert mine.chat_time == d(11, 3)                                  # 답변 시각은 세지 않는다
    rel = s.search("엘라스틱 by:me", sort="relevance")[0]
    assert sorted(m.ordinal for m in rel.matches) == [1, 3]


# ---- 칩 ----------------------------------------------------------------------------
def test_mine_chip_token_reset_and_typed_display(qt):
    from datetime import date
    from app.window import SearchWindow
    w = SearchWindow()
    c = w.chips
    got = []
    w.searchRequested.connect(got.append)
    c.mine_button.click()
    assert c.mine and c.tokens(date(2026, 11, 12)) == ["by:me"] and c.active() and not c.clear_button.isHidden()
    assert got and got[-1].endswith("by:me")
    assert c.compose("배포", date(2026, 11, 12)) == "배포 by:me"
    from PySide6.QtCore import Qt
    assert c.mine_button.focusPolicy() == Qt.NoFocus
    w.popup()
    assert not c.mine and not c.mine_button.isChecked() and c.tokens() == []
    # 손으로 친 by:me는 칩만 켜 보이고 토큰을 더 붙이지 않는다
    w.edit.setText("배포 by:me")
    assert c.mine_button.isChecked() and not c.mine and c.tokens(date(2026, 11, 12)) == []
    w.edit.setText("배포")
    assert not c.mine_button.isChecked()
    w.hide()
    w.deleteLater()


def test_chip_row_layout_and_sort_order(qt):
    from app.window import SearchWindow
    w = SearchWindow()
    c = w.chips
    row1, row2 = c.layout().itemAt(0).layout(), c.layout().itemAt(1).layout()
    assert row1.indexOf(c.clear_button) == row1.count() - 1                 # 모두 지우기는 첫째 줄 끝 (일지 뒤)
    assert row1.indexOf(c.src_buttons["journal"]) < row1.indexOf(c.clear_button)
    assert row2.indexOf(c.clear_button) < 0
    seg = row2.itemAt(row2.count() - 1).layout()                             # 둘째 줄 맨 끝은 정렬 단추
    assert [seg.itemAt(i).widget().text() for i in range(seg.count())] == ["최신", "정확도"]
    assert list(c.sort_buttons) == ["recent", "relevance"]
    assert row2.indexOf(c.mine_button) < row2.indexOf(seg) and row2.indexOf(c.mine_button) > row2.indexOf(c.proj_button)
    from app import settings as S
    assert list(S.SEARCH_SORT_LABEL.items()) == [("recent", "최신"), ("relevance", "정확도")]
    w.deleteLater()


def test_chip_bar_min_width_with_all_chips_on(qt):
    """칩을 다 켜고 '모두 지우기'가 보여도 칩 줄이 창 최소 폭(560px) 근처에 머문다 (예전엔 칩을 켜면 626px)."""
    from app import ui_state
    from app.window import SOURCE_CHIPS, SearchWindow
    w = SearchWindow(projects=lambda: ["small-win-tools"])
    w.resize(900, 560)
    w.show()
    c = w.chips

    def width():
        c._render()
        c.layout().invalidate()
        c.layout().activate()
        qt.processEvents()
        return c.minimumSizeHint().width()
    off = width()
    c.project = "아주아주아주 긴 프로젝트 이름"
    c.period = 7
    c._clicked.update(v for _l, v in SOURCE_CHIPS)
    c.mine = True
    on = width()
    assert not c.clear_button.isHidden()
    # 실제 Windows 글꼴에서는 약 521px(창 최소 폭 560 안). 시험은 글꼴이 없는 offscreen이라 글자가 넓게 잡혀 여유를 둔다
    assert off <= on <= ui_state.MIN_W + 60
    w.hide()
    w.deleteLater()

# ---- 한영 보정 ---------------------------------------------------------------------
def test_hangul_conversions():
    assert hangul.hangul_to_latin("ㅜㅎㅑㅜㅌ") == "nginx"
    assert hangul.hangul_to_latin("ㅜ햐ㅜㅌ") == "nginx"                 # 음절이 섞인 오타
    assert hangul.hangul_to_latin("배포") is None                       # 진짜 한글 낱말은 건드리지 않는다
    assert hangul.latin_word_to_hangul("qovh") == "배포"
    assert hangul.latin_word_to_hangul("nginx") is None and hangul.latin_word_to_hangul("docker") is None
    assert hangul.latin_word_to_hangul("QOVH") is None
    assert hangul.fix_layout("ㅜㅎㅑㅜㅌ 설정 \"ㅜㅎㅑㅜㅌ\" src:ai -qovh") == ('nginx 설정 "ㅜㅎㅑㅜㅌ" src:ai -qovh', ["nginx"])
    assert hangul.fix_layout("배포 nginx") is None
    assert hangul.found_message(["nginx"]) == "nginx로 찾았습니다"
    assert hangul.found_message(["배포"]) == "배포로 찾았습니다" and hangul.found_message(["한글"]) == "한글로 찾았습니다"
    assert hangul.found_message(["설정"]) == "설정으로 찾았습니다"


def test_layout_fix_only_when_zero_results(tmp_path):
    s = _searcher(tmp_path, [
        ("gggg0001", "서버", [("user", "nginx 설정과 배포 순서", d(11, 1)), ("assistant", "네", d(11, 1, 11))]),
        ("gggg0002", "오타 문서", [("user", "qovh 라는 이름의 도구", d(11, 2)), ("assistant", "네", d(11, 2, 11))]),
    ])
    out = search_all(s, "ㅜㅎㅑㅜㅌ", "recent")                         # 영문 자판으로 친 nginx
    assert ids(out.hits) == ["gggg0001"] and out.note == "nginx로 찾았습니다" and out.hint is None
    out = search_all(s, "ㅜ햐ㅜㅌ", "recent")
    assert ids(out.hits) == ["gggg0001"] and out.note == "nginx로 찾았습니다"
    s2 = _searcher(tmp_path / "x", [("hhhh0001", "문서", [("user", "배포 스크립트", d(11, 1)), ("assistant", "네", d(11, 1, 11))])])
    out = search_all(s2, "qovh", "recent")                              # 한글 자판 오타: qovh -> 배포
    assert ids(out.hits) == ["hhhh0001"] and out.note == "배포로 찾았습니다"
    # 결과가 있으면 보정하지 않는다 ('qovh'가 실제로 들어 있는 문서)
    out = search_all(s, "qovh", "recent")
    assert ids(out.hits) == ["gggg0002"] and out.note == ""
    # 보정해도 0건이면 그대로 0건, 보정 알림도 없다
    out = search_all(s2, "ㅋㅋㅋㅋㅋ", "recent")
    assert out.hits == [] and out.note == "" and out.hint is None
    # 따옴표 구문과 문법 조각은 고치지 않는다
    out = search_all(s2, '"qovh"', "recent")
    assert out.hits == [] and out.note == ""


# ---- 0건 안내 ----------------------------------------------------------------------
@pytest.fixture
def zs(tmp_path):
    def conv(cid, src, proj, when):
        return (cid, f"문서 {cid}", [("user", "레디스 질문입니다", when), ("assistant", "네", when + timedelta(hours=1))],
                {"source": src, "project": proj})
    s = _searcher(tmp_path, [
        conv("zzzz0001", "claude-ai", "alpha", d(11, 5)), conv("zzzz0002", "claude-ai", "alpha", d(9, 1)),
        conv("zzzz0003", "claude-code", "alpha", d(9, 2)), conv("zzzz0004", "claude-ai", "beta", d(11, 6)),
    ])
    yield s
    s.conn.close()


def test_zero_hint_picks_the_condition_with_most_results(zs):
    h = zero_hint(zs, parse("레디스 src:code after:2026-11-01"))
    assert (h.kind, h.count, h.text) == ("source", 2, "출처를 제외하면 2건입니다")
    h = zero_hint(zs, parse("레디스 proj:beta after:2026-12-01"))
    assert (h.kind, h.count, h.text) == ("period", 1, "기간을 제외하면 1건입니다")
    h = zero_hint(zs, parse("레디스 src:code proj:beta"))                # 출처 1건, 프로젝트 1건: 앞쪽 조건
    assert (h.kind, h.count) == ("source", 1)
    h = zero_hint(zs, parse("레디스 src:code proj:alpha by:me -롤백"))
    assert h.kind in ("source", "mine", "exclude") and h.count >= 1


def test_zero_hint_all_conditions_fallback_and_none(zs):
    h = zero_hint(zs, parse("레디스 src:code proj:beta after:2026-12-01"))     # 하나만 빼서는 여전히 0건
    assert (h.kind, h.count, h.text) == ("all", 4, "모든 조건을 제외하면 4건입니다")
    assert zero_hint(zs, parse("없는단어 src:code")) is None                    # 조건을 빼도 0건
    assert zero_hint(zs, parse("없는단어")) is None                             # 조건이 없음
    assert zero_hint(zs, parse("레디스")) is None


def test_zero_hint_counts_without_building_hits(zs, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("Hit를 만들면 안 된다")
    monkeypatch.setattr(Searcher, "_make_hit", boom)
    assert zero_hint(zs, parse("레디스 src:code after:2026-11-01")).count == 2
    assert zs.count("레디스 proj:alpha") == 3


def test_search_all_returns_hint_when_still_zero(zs):
    out = search_all(zs, "레디스 src:code after:2026-11-01", "recent")
    assert out.hits == [] and out.hint.text == "출처를 제외하면 2건입니다" and out.note == ""


def test_eul_reul_by_final_consonant():
    assert [eul_reul(n) for n in ("출처", "기간", "프로젝트", "내 질문", "제외어", "모든 조건")] == ["를", "을", "를", "을", "를", "을"]
    assert ZeroHint("mine", 3).text == "내 질문을 제외하면 3건입니다"
    assert ZeroHint("exclude", 1).text == "제외어를 제외하면 1건입니다"
    assert without(parse("a b src:ai by:me"), ["mine"]).by_me is False and without(parse("a src:ai"), ["source"]).sources == []


# ---- 창: 안내 줄을 누르거나 Enter ----------------------------------------------------
def _hint_window(qt, kind="source", text="배포 src:code proj:x -롤백"):
    from app.window import SearchWindow
    w = SearchWindow()
    got = []
    w.searchRequested.connect(got.append)
    w.edit.setText(text)
    got.clear()
    w._timer.stop()
    w.set_results([], "결과 없음", hint=ZeroHint(kind, 5))
    return w, got


def test_hint_row_is_selectable_and_enter_removes_typed_token(qt):
    from app.window import K_HINT, ROLE_KIND, ROLE_TEXT
    w, got = _hint_window(qt)
    assert w.list.count() == 1 and w.list.item(0).data(ROLE_KIND) == K_HINT
    assert w.list.item(0).data(ROLE_TEXT) == "출처를 제외하면 5건입니다" and w.list.currentRow() == 0
    w._emit("copy_msg")
    w._emit("copy_conv")
    assert got == []                                                    # 복사 키는 아무 일도 하지 않는다
    w._emit("open")                                                     # Enter: 검색칸의 src:code가 지워지고 다시 찾는다
    assert w.edit.text() == "배포 proj:x -롤백" and got and got[-1] == "배포 proj:x -롤백"
    w.deleteLater()


def test_hint_click_turns_off_chip_and_typed_proj_exclude_all(qt):
    w, got = _hint_window(qt, "source", "배포")
    w.chips.src_buttons["code"].click()
    w.chips.src_buttons["ai"].click()
    assert w.chips.active()
    got.clear()
    w.set_results([], "결과 없음", hint=ZeroHint("source", 2))
    w._on_clicked(w.list.item(0))                                       # 클릭: 출처 칩 둘 다 끈다
    assert not w.chips._clicked and w.chips.compose("배포") == "배포" and got and got[-1] == "배포"
    w.chips.mine_button.click()
    w.chips.period_buttons[7].click()
    w.edit.setText("배포 proj:x after:2026-10-01 -롤백 by:me")
    w._timer.stop()
    w.set_results([], "결과 없음", hint=ZeroHint("all", 9))
    w._emit("open")                                                     # 모든 조건: 칩과 손으로 친 조각 모두
    assert not w.chips.active() and w.edit.text() == "배포" and got[-1] == "배포"
    w.set_results([], "결과 없음", hint=ZeroHint("exclude", 3))
    w.edit.setText("배포 -롤백 src:ai")
    w._timer.stop()
    w._emit("open")
    assert w.edit.text() == "배포 src:ai"
    w.deleteLater()


def test_hint_row_only_without_hits(qt):
    from app.window import SearchWindow
    w = SearchWindow()
    w.set_results([], "결과 없음")
    assert w.list.count() == 0
    w.deleteLater()
