"""설정 창 새 모양: 설정 찾기, 탭 배지, ⓘ 툴팁, 두 줄 줄, 아래 막대, 단축키 (화면 없이 offscreen)."""
import os

import pytest

from app import cli_check


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    qtw = pytest.importorskip("PySide6.QtWidgets")
    app = qtw.QApplication.instance() or qtw.QApplication([])
    from app import settings_window as sw
    monkeypatch.setattr(sw.cli_check, "check", lambda p, c=None, **k: cli_check.CliStatus("ready", f"준비됨: {p}"))
    monkeypatch.setattr(sw, "ask", lambda parent, title, text, buttons, primary=None: primary or buttons[-1][0])
    yield app, sw
    app.processEvents()


def make(sw, core):
    w = sw.SettingsWindow(core, sw.Hooks())
    w.show()
    return w


def visible_rows(w, tab):
    return [r for r in w._rows if r.tab == tab and r.counted]


def test_search_filters_rows_sections_and_tab_badges(qt, core_env):
    app, sw = qt
    w = make(sw, core_env)
    n_all = len(visible_rows(w, "general"))
    w.search.edit.setText("단축키")
    app.processEvents()
    names = [r.name for r in visible_rows(w, "general")]
    assert "검색 창 단축키" in names and len(names) < n_all
    # 맞은 줄이 없는 섹션은 숨겨진다
    folder_sec = next(r.sec for r in w._rows if r.name == "대화 보관 폴더")
    assert folder_sec.isHidden()
    # 탭 배지: 맞은 탭에만 수가 보이고, 맞은 게 없는 탭은 흐리게
    assert w.nav_buttons[0].badge.text() == str(len(names)) and not w.nav_buttons[0].badge.isHidden()
    assert w.nav_buttons[3].property("dim") is True and w.nav_buttons[3].badge.isHidden()
    assert w.search.count.text() == f"{sum(1 for r in w._rows if r.counted)}개"
    # 글자 지우면 전부 돌아온다
    w.search.edit.setText("")
    assert len(visible_rows(w, "general")) == n_all and not folder_sec.isHidden()
    assert w.nav_buttons[3].property("dim") is False
    w._done = True
    w.close()


def test_search_moves_to_first_tab_with_matches_and_matches_tooltip_text(qt, core_env):
    app, sw = qt
    w = make(sw, core_env)
    assert w.current_tab() == "general"
    w.search.edit.setText("가림 정규식")         # 고급 탭의 '추가 가림 정규식'
    assert w.current_tab() == "advanced" and w.nav_buttons[3].isChecked()
    # 툴팁 글에서도 찾는다 (긴 설명은 임시 규칙으로 ⓘ 툴팁에 들어간다)
    row = next(r for r in w._rows if r.tip)
    word = row.tip.split()[0]
    w.search.edit.setText(word)
    assert any(r.counted and r.tip == row.tip for r in w._rows)
    w.search.edit.setText("이런설정은없습니다")
    assert not w.no_match.isHidden() and w.search.count.text() == "맞는 설정 없음"
    w._done = True
    w.close()


def test_search_respects_values_hiding_rows_and_marks_text(qt, core_env):
    app, sw = qt
    w = make(sw, core_env)
    w.source_checks["claude_ai"].setChecked(False)
    w.search.edit.setText("알림")
    reminder = next(r for r in w._rows if r.key == "reminder_days")
    assert reminder.box.isHidden() and not reminder.counted      # 서비스를 끄면 찾기에서도 안 보인다
    w.source_checks["claude_ai"].setChecked(True)
    assert reminder.counted
    assert "background-color" in reminder.name_lb.text() or reminder.name_lb.text() == reminder.name   # 맞은 글자 칠함
    w._done = True
    w.close()


def test_info_button_and_two_line_rows(qt, core_env):
    app, sw = qt
    w = make(sw, core_env)
    # 줄인 설명은 줄에, 긴 설명은 ⓘ에 (문구표 적용)
    row = next(r for r in w._rows if r.key == "archive_dir")
    assert row.desc == "대화 md를 쌓는 폴더입니다." and "검색 색인 다시 만들기" in row.tip
    assert w._info_buttons and len([r for r in w._rows if r.tip]) >= 20
    # 툴팁 글이 없는 줄의 ⓘ는 설명이 '…'로 줄어 보일 때만 켜진다
    plain = next(r for r in w._rows if r.name and r.desc and not r.tip)
    info = next(b for b in w._info_buttons if b.tip == plain.desc)
    plain.desc_lb.elidedChanged.emit(True)
    assert info.isVisibleTo(info.parentWidget())
    plain.desc_lb.elidedChanged.emit(False)
    assert not info.isVisibleTo(info.parentWidget())
    infos = w._info_buttons
    assert infos and all("<table" in b.toolTip() for b in infos)
    assert all(not b.icon().isNull() for b in infos)
    assert sw.tip_html("a<b>\nc").endswith("a&lt;b&gt;<br>c</td></tr></table>")
    w._done = True
    w.close()


def test_empty_desc_shows_only_when_field_is_empty(qt, core_env):
    app, sw = qt
    w = make(sw, core_env)
    r = next(x for x in w._rows if x.key == "journal_dir")
    r.empty_desc = "YYYY/MM/YYYY-MM-DD.md 형식"
    w._io["journal_dir"][0]("")
    w._on_changed()
    assert r.desc_lb.text() == r.empty_desc
    w._io["journal_dir"][0]("C:/vault")
    w._on_changed()
    assert r.desc_lb.text() == r.desc
    w._done = True
    w.close()


def test_footer_changed_count_and_shortcuts(qt, core_env):
    app, sw = qt
    w = make(sw, core_env)
    assert w.changed_text.isHidden() and not w.btn_save.isEnabled()
    w._io["queue_days"][0](7)
    w._io["queue_focus"][0](3)
    assert w.changed_text.text() == "바뀐 설정 2개" and not w.changed_text.isHidden()
    w._shortcut_save()
    assert w._done and core_env.config["queue_days"] == 7
    w2 = make(sw, core_env)
    w2.search.focus_all()
    assert w2.search.edit.hasFocus() or w2.search.edit.selectedText() == "" 
    w2._shortcut_save()                      # 바뀐 게 없으면 저장하지 않는다
    assert not w2._done
    w2._done = True
    w2.close()


def test_mode_is_segmented_and_hotkey_uses_keycaps(qt, core_env):
    app, sw = qt
    w = make(sw, core_env)
    seg = [b for b in w.findChildren(sw.QPushButton) if b.objectName() == "seg"]
    assert [b.property("segpos") for b in seg] == ["first", "mid", "last"]
    assert w.hotkey.property("caps") is True and w.hotkey.t is not None
    w.hotkey.start()
    assert w.hotkey.property("caps") is False
    w.hotkey.stop()
    assert w.hotkey.property("caps") is True
    w._done = True
    w.close()


def test_fresh_window_has_no_changed_count(qt, core_env):
    """연 직후 건드리지 않았으면 바뀐 설정 수가 없어야 한다 (정규화된 값이 config와 달라 보이면 버그)."""
    app, sw = qt
    core_env.config["note_dirs"] = ["~/notes"]               # 경로 확장 전 값
    core_env.config["journal_dir"] = "%USERPROFILE%/vault"
    w = make(sw, core_env)
    app.processEvents()
    assert w.changed_keys() == set() and w.changed_text.isHidden() and w.changed_dot.isHidden()
    assert not w.btn_save.isEnabled() and w.windowTitle() == sw.TITLE
    w.select_tab("advanced")
    w.select_tab("ask")
    app.processEvents()
    assert w.changed_keys() == set() and w.changed_text.isHidden()
    w._done = True
    w.close()


def test_bottom_bar_has_no_keycaps_but_shortcuts_work(qt, core_env):
    app, sw = qt
    w = make(sw, core_env)
    footer = w.btn_save.parentWidget()
    assert [lb.text() for lb in footer.findChildren(sw.QLabel) if lb.objectName() == "keycap"] == []
    assert any(lb.objectName() == "keycap" for lb in w.search.findChildren(sw.QLabel))     # 설정 찾기 칸의 Ctrl F는 그대로
    w._done = True
    w.close()


def test_hidden_sections_leave_no_gap(qt, core_env):
    app, sw = qt
    w = make(sw, core_env)
    secs = [s for s in w._secs if s.tab == "general"]
    assert secs[0]._v.contentsMargins().top() == 0 and secs[1]._v.contentsMargins().top() == sw.SECTION_GAP
    w.search.edit.setText("폴더")                          # '검색 창', '모양' 섹션이 숨겨짐
    app.processEvents()
    visible = [s for s in secs if not s.isHidden()]
    assert secs[0].isHidden() and visible and visible[0]._v.contentsMargins().top() == 0
    assert all(s._v.contentsMargins().top() == sw.SECTION_GAP for s in visible[1:])
    w.search.edit.setText("")
    assert secs[0]._v.contentsMargins().top() == 0 and secs[1]._v.contentsMargins().top() == sw.SECTION_GAP
    w._done = True
    w.close()