"""정렬(최신/정확도), 날짜 묶음 줄, 결과 줄과 미리보기의 채팅 시각. 합성 데이터만 쓴다."""
import os
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import KST

from app import settings as S
from app.archive import Archive
from app.index import Index, connect
from app.model import Conversation, Message
from app.search import Hit, Searcher
from app.store import DEFAULT_CONFIG

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    qtw = pytest.importorskip("PySide6.QtWidgets")
    app = qtw.QApplication.instance() or qtw.QApplication([])
    yield app
    app.processEvents()


def _conv(root, cid, title, msgs):
    c = Conversation(f"claude-ai:{cid}", "claude-ai", title, "", msgs[0][1], msgs[-1][1], "",
                     [Message(f"m{i}", "user" if i % 2 == 0 else "assistant", t, text)
                      for i, (text, t) in enumerate(msgs)])
    Archive(root, KST).write(c)


@pytest.fixture
def searcher(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    d = lambda mo, day, h=10: datetime(2026, mo, day, h, 0, tzinfo=KST)    # noqa: E731
    # A: 제목에도 본문에도 많이 맞지만 오래됨 / B: 한 번만 맞았지만 최근 / C: 중간
    _conv(root, "aaaa0001", "레디스 레디스 정리", [("레디스 레디스 설정", d(9, 1)), ("레디스 답변", d(9, 1, 11)),
                                              ("레디스 다시 레디스", d(9, 2))])
    _conv(root, "bbbb0001", "잡담 메모", [("점심 이야기 레디스", d(11, 10)), ("네 그렇군요", d(11, 10, 11))])
    _conv(root, "cccc0001", "캐시 메모", [("레디스 한 번 레디스 두 번 레디스", d(10, 20)), ("답", d(10, 20, 11))])
    # D: 한 대화 안에서 맞은 메시지 여러 개 (많이 맞은 것은 앞쪽, 가장 늦은 것은 한 번만)
    _conv(root, "dddd0001", "순서 확인", [("엘라스틱 엘라스틱 엘라스틱", d(10, 1)), ("답", d(10, 1, 11)),
                                       ("엘라스틱 엘라스틱", d(10, 5)), ("답", d(10, 5, 11)), ("엘라스틱", d(10, 9))])
    idx = Index(tmp_path / "i.db")
    idx.sync(root)
    s = Searcher(connect(idx.db_path), now=lambda: NOW)
    yield s
    s.conn.close()


def ids(hits):
    return [h.conv_id.split(":")[1] for h in hits]


# ---- 엔진 -------------------------------------------------------------------------
def test_recent_and_relevance_share_candidates_but_differ_in_order(searcher):
    rel = searcher.search("레디스", sort="relevance")
    rec = searcher.search("레디스", sort="recent")
    assert set(ids(rel)) == set(ids(rec)) == {"aaaa0001", "bbbb0001", "cccc0001"}
    assert ids(rel)[0] == "aaaa0001"                                   # 제목에도 맞아 정확도 1위
    assert ids(rec) == ["bbbb0001", "cccc0001", "aaaa0001"]            # 채팅 시각 늦은 순
    assert [h.chat_time for h in rec] == sorted((h.chat_time for h in rec), reverse=True)
    assert ids(searcher.search("레디스")) == ids(rel)                  # 기본값은 정확도(예전 그대로)


def test_recent_cuts_after_sorting(searcher):
    assert ids(searcher.search("레디스", limit=2, sort="recent")) == ["bbbb0001", "cccc0001"]
    assert "bbbb0001" not in ids(searcher.search("레디스", limit=2, sort="relevance"))   # 약하게 맞은 최근 대화는 잘림


def test_recent_orders_matches_latest_first(searcher):
    rel = searcher.search("엘라스틱", sort="relevance")[0]
    rec = searcher.search("엘라스틱", sort="recent")[0]
    assert [m.ordinal for m in rel.matches] == [1, 3, 5]               # 많이 맞은 순 (지금 순서)
    assert [m.ordinal for m in rec.matches] == [5, 3, 1]               # 늦은 순
    assert [m.time for m in rec.matches] == sorted((m.time for m in rec.matches), reverse=True)
    assert rec.match_total == 3 and rec.chat_time == rec.matches[0].time


def test_recent_with_period_and_no_words(searcher):
    rec = searcher.search("레디스 after:2026-10-01", sort="recent")
    assert ids(rec) == ["bbbb0001", "cccc0001"]
    # 단어 없는 검색은 정렬과 상관없이 대화 마지막 시각 순
    assert ids(searcher.search("after:2026-10-01", sort="recent")) == ids(searcher.search("after:2026-10-01"))


# ---- 설정 -------------------------------------------------------------------------
def test_search_sort_setting():
    assert DEFAULT_CONFIG["search_sort"] == "recent"
    assert S.field_error("search_sort", "recent") == "" and S.field_error("search_sort", "relevance") == ""
    assert S.field_error("search_sort", "latest")
    assert S.read_search_sort({}) == "recent" and S.read_search_sort({"search_sort": "RELEVANCE"}) == "relevance"
    assert S.read_search_sort({"search_sort": "x"}) == "recent"
    assert S.FIELD["search_sort"].tab == "general"


# ---- 화면 도우미 ------------------------------------------------------------------
def _hit(chat: datetime | None, updated: datetime | None, title="제목") -> Hit:
    return Hit(conv_id=f"claude-ai:{title}", path=Path("missing.md"), title=title, source="claude-ai", project="", updated=updated,
               status="present", score=0.0, chat_time=chat)


def local(y, mo, d, h=10):
    return datetime(y, mo, d, h, 0).astimezone()


def test_row_when_shows_last_only_when_date_differs():
    from app.window import row_when
    assert row_when(_hit(local(2026, 11, 6), local(2026, 11, 10))) == ("11-06", "· 마지막 11-10")
    assert row_when(_hit(local(2026, 11, 6, 9), local(2026, 11, 6, 18))) == ("11-06", "")
    assert row_when(_hit(None, local(2026, 11, 10))) == ("11-10", "")
    assert row_when(_hit(None, None)) == ("", "")


def test_date_group_boundaries():
    from app.window import date_group
    today = date(2026, 11, 12)                      # 목요일, 이번 주 월요일은 11-09
    assert date_group(local(2026, 11, 12, 0), today) == "오늘"
    assert date_group(local(2026, 11, 11), today) == "이번 주"
    assert date_group(local(2026, 11, 9, 0), today) == "이번 주"
    assert date_group(local(2026, 11, 8), today) == "이번 달"
    assert date_group(local(2026, 11, 1, 0), today) == "이번 달"
    assert date_group(local(2026, 10, 31), today) == "그 전"
    assert date_group(None, today) == "그 전"
    assert date_group(local(2026, 11, 9), date(2026, 11, 9)) == "오늘"        # 월요일이면 이번 주 묶음은 비어 있다


def test_role_label_has_message_time():
    from app.window import msg_stamp, role_label
    dt = datetime(2026, 11, 9, 10, 1, tzinfo=KST)
    stamp = f"{dt.astimezone():%m-%d %H:%M}"
    assert role_label("user", "2026-11-09T10:01:00+09:00") == f"나 · {stamp}"
    assert role_label("assistant", dt) == f"AI · {stamp}"
    assert role_label("user", "") == "나" and msg_stamp("-") == ""


# ---- 창 ---------------------------------------------------------------------------
def _grouped_hits():
    return [_hit(local(2026, 11, 12), local(2026, 11, 12), "오늘 하나"), _hit(local(2026, 11, 12, 8), local(2026, 11, 12, 8), "오늘 둘"),
            _hit(local(2026, 11, 10), local(2026, 11, 10), "주 하나"),
            _hit(local(2026, 11, 3), local(2026, 11, 3), "달 하나"), _hit(local(2026, 11, 2), local(2026, 11, 2), "달 둘"),
            _hit(local(2026, 10, 1), local(2026, 10, 1), "전 하나")]


def _kinds(w):
    from app.window import ROLE_KIND, ROLE_TEXT
    return [(w.list.item(i).data(ROLE_KIND), w.list.item(i).data(ROLE_TEXT)) for i in range(w.list.count())]


def test_group_rows_only_when_grouped_and_skipped_by_keys(qt):
    from app.window import K_GROUP, K_HIT, SearchWindow
    w = SearchWindow()
    w.today = lambda: date(2026, 11, 12)
    w.set_results(_grouped_hits(), "6건", grouped=True)
    k = [x[0] for x in _kinds(w)]
    assert [t for kind, t in _kinds(w) if kind == K_GROUP] == ["오늘", "이번 주", "이번 달", "그 전"]
    assert k == [K_GROUP, K_HIT, K_HIT, K_GROUP, K_HIT, K_GROUP, K_HIT, K_HIT, K_GROUP, K_HIT]
    assert w.list.currentRow() == 1                               # 처음 고르는 줄은 묶음 줄이 아니라 첫 결과
    for i, kind in enumerate(k):
        if kind == K_GROUP:
            assert not (w.list.item(i).flags() & Qt_ItemIsSelectable())
    rows = []
    for _ in range(5):
        w._navigate(1)
        rows.append(w.list.currentRow())
    assert rows == [2, 4, 6, 7, 9]                                # 묶음 줄(3, 5, 8)을 건너뜀
    w._navigate(1)
    assert w.list.currentRow() == 9                               # 끝에서 멈춤
    w._navigate(-1)
    assert w.list.currentRow() == 7
    w._navigate(8)                                                # PageDown: 고를 수 있는 줄만 세어 끝까지
    assert w.list.currentRow() == 9
    w._navigate(-8)                                               # PageUp: 맨 위 결과에서 멈춤 (묶음 줄로 올라가지 않음)
    assert w.list.currentRow() == 1
    w._navigate(-1)
    assert w.list.currentRow() == 1
    # Enter, 복사는 묶음 줄에서 아무 일도 하지 않는다
    got = []
    w.action.connect(lambda *a: got.append(a))
    w.list.setCurrentRow(3)
    if w.list.currentRow() == 3:         # 억지로 묶음 줄을 현재 줄로 만들어도 Enter는 아무 일도 하지 않는다
        w._emit("open")
        w._emit("copy_conv")
        assert got == []
    w.deleteLater()


def Qt_ItemIsSelectable():
    from PySide6.QtCore import Qt
    return Qt.ItemIsSelectable


def test_no_group_rows_in_relevance_or_plain_lists(qt):
    from app.window import K_GROUP, SearchWindow
    w = SearchWindow()
    w.today = lambda: date(2026, 11, 12)
    w.set_results(_grouped_hits(), "6건")                         # grouped 기본값 False: 정확도순, 칩만 켠 목록 등
    assert w.list.count() == 6 and all(kind != K_GROUP for kind, _t in _kinds(w))
    w._navigate(1)
    assert w.list.currentRow() == 1
    w.deleteLater()


def test_popup_resets_sort_to_setting_default_and_ctrl_r_toggles(qt):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from app.window import SearchWindow
    w = SearchWindow()
    got = []
    w.searchRequested.connect(got.append)
    w.set_default_sort("recent")
    w.popup()
    assert w.sort == "recent" and w.chips.sort_buttons["recent"].isChecked()
    n = len(got)
    QTest.keyClick(w.edit, Qt.Key_R, Qt.ControlModifier)          # Ctrl+R: 바로 다시 검색
    assert w.sort == "relevance" and w.chips.sort_buttons["relevance"].isChecked() and len(got) == n + 1
    QTest.keyClick(w.edit, Qt.Key_R, Qt.ControlModifier)
    assert w.sort == "recent" and len(got) == n + 2
    w.chips.sort_buttons["relevance"].click()                    # 단추로도 바뀜
    assert w.sort == "relevance" and len(got) == n + 3
    w.chips.sort_buttons["relevance"].click()                    # 같은 쪽을 다시 눌러도 다시 검색하지 않음
    assert len(got) == n + 3
    w.chips.src_buttons["code"].click()
    w.chips.clear()                                              # '모두 지우기'는 정렬을 건드리지 않음
    assert w.sort == "relevance"
    w.popup()                                                    # 열 때 기본값으로
    assert w.sort == "recent"
    w.set_default_sort("relevance")
    assert w.sort == "recent"                                    # 설정을 바꿔도 열려 있는 검색은 그대로
    w.popup()
    assert w.sort == "relevance"
    w.set_default_sort("bogus")
    w.popup()
    assert w.sort == "recent"
    for b in w.chips.sort_buttons.values():
        assert b.focusPolicy() == Qt.NoFocus
    w.hide()
    w.deleteLater()


def test_sort_segment_keeps_idle_min_width(qt):
    """정렬 단추를 달아도, 칩을 하나도 켜지 않았을 때 칩 줄의 최소 폭은 예전(첫 줄 기준)보다 커지지 않는다."""
    from app.window import SearchWindow
    w = SearchWindow(projects=lambda: ["small-win-tools"])
    row1 = w.chips.layout().itemAt(0).layout().minimumSize().width()
    row2 = w.chips.layout().itemAt(1).layout().minimumSize().width()
    assert row2 <= row1
    w.deleteLater()

def test_preview_shows_message_times(qt, searcher):
    from app.window import SearchWindow
    w = SearchWindow()
    w.resize(980, 560)
    hits = searcher.search("엘라스틱", sort="recent")
    w.set_results(hits, "1건")
    qt.processEvents()
    w._refresh_preview()
    h = hits[0]
    assert "마지막 " in w.pane.meta.text()
    first = h.matches[0]
    assert w.pane.index.text().startswith(f"맞은 메시지 1 / 3 · {first.time:%m-%d %H:%M}")
    labels = []
    for i in range(w.pane.body_lay.count()):
        fr = w.pane.body_lay.itemAt(i).widget()
        lab = fr.findChild(type(w.pane.title), "pvRole") if fr is not None else None
        if lab is not None:
            labels.append(lab.text())
    assert labels and all(" · " in t and t.split(" · ")[0] in ("나", "AI") for t in labels)
    w.deleteLater()
