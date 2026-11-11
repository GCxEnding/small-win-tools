"""창 크기 저장 (ui_state.py, 검색 창 크기 조절). 화면 없이 offscreen."""
import json
import os

import pytest

from app import ui_state as U


def test_load_missing_and_broken(tmp_path):
    p = tmp_path / "ui_state.json"
    assert U.load(p) == {} and U.load(None) == {}
    p.write_text("{깨짐", encoding="utf-8")
    assert U.load(p) == {}
    assert (tmp_path / "ui_state.json.bak").read_text(encoding="utf-8") == "{깨짐"
    p.write_text("[1]", encoding="utf-8")
    assert U.load(p) == {}


def test_search_state_drops_bad_values():
    ok = {"search_window": {"w": 900, "h": 600, "split": 0.35}}
    assert U.search_state(ok) == {"w": 900, "h": 600, "split": 0.35}
    bad = {"search_window": {"w": 100, "h": "큼", "split": 5}}
    assert U.search_state(bad) == {}
    assert U.search_state({"search_window": {"w": True}}) == {}
    assert U.search_state({}) == {} and U.search_state({"search_window": 3}) == {}


def test_with_search_state_keeps_other_keys():
    out = U.with_search_state({"other": 1, "search_window": {"w": 1}}, {"w": 800, "h": 500, "junk": 1})
    assert out == {"other": 1, "search_window": {"w": 800, "h": 500}}


def test_fit_size_shrinks_to_screen_but_keeps_minimum():
    assert U.fit_size(2000, 1400, 1920, 1040) == (1920, 1040)
    assert U.fit_size(900, 600, 1920, 1040) == (900, 600)
    assert U.fit_size(900, 600, 400, 300) == (U.MIN_W, U.MIN_H)


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    qtw = pytest.importorskip("PySide6.QtWidgets")
    app = qtw.QApplication.instance() or qtw.QApplication([])
    yield app
    app.processEvents()


def test_window_restores_and_saves_only_user_resize(qt, tmp_path):
    from app.window import SearchWindow
    p = tmp_path / "ui_state.json"
    p.write_text(json.dumps({"other": 1, "search_window": {"w": 900, "h": 600}}), encoding="utf-8")
    w = SearchWindow(state_path=p)
    assert (w.width(), w.height()) == (900, 600) and w.minimumWidth() == U.MIN_W
    w.resize(700, 500)
    w.save_state()
    assert json.loads(p.read_text(encoding="utf-8"))["search_window"] == {"w": 900, "h": 600}   # 프로그램이 바꾼 크기는 저장 안 함
    w.user_resized()                                 # 테두리를 끌어 바꾼 것으로 본다
    w.save_state()
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved == {"other": 1, "search_window": {"w": 700, "h": 500}}
    w.close()


def test_window_without_state_path_never_writes(qt, tmp_path):
    from app.window import SearchWindow
    w = SearchWindow()
    w.user_resized()
    w.save_state()
    assert w.state_path is None
    w.close()


def test_grips_cover_border_and_corner_mark(qt):
    from app.window import CORNER_MARK, EDGE, SearchWindow
    w = SearchWindow()
    w.resize(700, 500)
    w.show()
    qt.processEvents()
    left, right, top, bottom, tl, tr, bl, br = w._grips
    assert left.width() == EDGE and right.x() == 700 - EDGE and top.height() == EDGE and bottom.y() == 500 - EDGE
    assert br.width() == CORNER_MARK and br.mark and not bl.mark
    w.close()
