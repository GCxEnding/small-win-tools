"""설정 창 화면 (화면 없이 offscreen). 실제 CLI 확인은 가짜로 바꾼다."""
import copy
import json
import os

import pytest

from app import cli_check
from app import settings as S
from app.store import DEFAULT_CONFIG


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    qtw = pytest.importorskip("PySide6.QtWidgets")
    app = qtw.QApplication.instance() or qtw.QApplication([])
    from app import settings_window as sw
    monkeypatch.setattr(sw.cli_check, "check", lambda p, c=None, **k: cli_check.CliStatus("ready", f"준비됨: {p}"))
    asked = []
    monkeypatch.setattr(sw.QMessageBox, "question", lambda *a, **k: (asked.append(a[2]), sw.QMessageBox.StandardButton.Yes)[1])
    monkeypatch.setattr(sw.QMessageBox, "warning", lambda *a, **k: (asked.append(a[2]), sw.QMessageBox.StandardButton.Yes)[1])
    yield app, sw, asked
    app.processEvents()


def make(sw, core, **kw):
    calls = {"applied": [], "hotkey": [], "setup": []}
    hooks = sw.Hooks(try_hotkey=lambda k: (calls["hotkey"].append(k), (True, ""))[1],
                     applied=lambda ch, old: calls["applied"].append(set(ch)),
                     setup_finished=lambda f, ch, old: calls["setup"].append((f, set(ch))))
    w = sw.SettingsWindow(core, hooks, **kw)
    return w, calls


def test_open_shows_current_values_and_is_clean(qt, core_env):
    _app, sw, _ = qt
    w, _ = make(sw, core_env)
    assert not w.dirty() and w.windowTitle() == sw.TITLE and not w.btn_save.isEnabled()
    assert w.build_new() == core_env.config
    assert w.collect()["archive_dir"] == core_env.config["archive_dir"]
    assert w.tabs.count() == 4 and [w.tabs.tabText(i) for i in range(4)] == ["일반", "수집", "요약 AI", "고급"]
    w.close()


def test_change_save_writes_only_changed_key(qt, core_env):
    _app, sw, _ = qt
    core = core_env
    before = json.loads(core.store.config_path.read_text(encoding="utf-8"))
    w, calls = make(sw, core)
    w._io["queue_days"][0](7)
    assert w.dirty() and w.windowTitle().endswith("*") and w.btn_save.isEnabled()
    assert w.save()
    saved = json.loads(core.store.config_path.read_text(encoding="utf-8"))
    assert saved == {**before, "queue_days": 7}
    assert calls["applied"] == [{"queue_days"}] and calls["hotkey"] == []


def test_errors_block_save_and_jump_to_tab(qt, core_env, tmp_path):
    _app, sw, _ = qt
    w, calls = make(sw, core_env)
    w._io["watch_dir"][0](str(tmp_path / "없는 폴더"))
    w.tabs.setCurrentIndex(0)
    assert not w.save()
    assert S.TABS[w.tabs.currentIndex()] == "collect"
    assert "폴더가 없습니다" in w._notes["watch_dir"].text() and calls["applied"] == []
    w._done = True
    w.close()


def test_hotkey_record_and_register_test(qt, core_env):
    _app, sw, _ = qt
    w, calls = make(sw, core_env)
    w._on_hotkey_recorded("win+v")
    assert "고를 수 없습니다" in w._notes["hotkey"].text() and w.hotkey.value() == "ctrl+alt+h"
    w._on_hotkey_recorded("ctrl+alt+k")
    assert w.hotkey.value() == "ctrl+alt+k" and "hangul-restore" in w._notes["hotkey"].text()
    w.hooks.try_hotkey = lambda k: (False, "이미 등록됨")
    assert not w.save()
    assert "다른 프로그램이 쓰고 있어" in w._notes["hotkey"].text()
    assert core_env.config["hotkey"] == "ctrl+alt+h"                # 저장 안 함
    w.hooks.try_hotkey = lambda k: (calls["hotkey"].append(k), (True, ""))[1]
    assert w.save() and calls["hotkey"] == ["ctrl+alt+k"] and core_env.config["hotkey"] == "ctrl+alt+k"


def test_sources_toggle_hides_fields(qt, core_env):
    _app, sw, _ = qt
    w, _ = make(sw, core_env)
    w.show()
    w.source_checks["claude_ai"].setChecked(False)
    w.source_checks["codex"].setChecked(False)
    assert w._boxes["reminder_days"].isHidden() and not w.codex_home.isEnabled()
    assert [g.isHidden() for _s, g in w._guides] == [True, False]
    w._io["ask_provider"][0]("codex")
    assert w.claude_box.isHidden() and not w.codex_box.isHidden()
    w._done = True
    w.close()


def test_invalid_value_shown_as_default_and_written(qt, core_env):
    _app, sw, _ = qt
    core = core_env
    core.config["queue_days"] = "abc"
    w, _ = make(sw, core)
    assert w.collect()["queue_days"] == 14 and sw.INVALID_NOTE in w._notes["queue_days"].text()
    assert w.btn_save.isEnabled() and not w.dirty()
    assert w.save() and core.config["queue_days"] == 14


def test_external_change_reload(qt, core_env, monkeypatch):
    _app, sw, _ = qt
    core = core_env
    w, calls = make(sw, core)
    data = json.loads(core.store.config_path.read_text(encoding="utf-8"))
    data["max_results"] = 99
    core.store.config_path.write_text(json.dumps(data), encoding="utf-8")
    os.utime(core.store.config_path, ns=(1, 1))
    w._io["queue_days"][0](8)
    clicked = {}

    def fake_exec(box):
        clicked["b"] = next(b for b in box.buttons() if b.text() == "다시 읽기")
        return 0
    monkeypatch.setattr(sw.QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(sw.QMessageBox, "clickedButton", lambda box: clicked["b"])
    assert not w.save()
    assert core.config["max_results"] == 99 and w.collect()["max_results"] == 99
    assert calls["applied"] and "max_results" in calls["applied"][0]
    assert w.collect()["queue_days"] == core.config["queue_days"]     # 다시 읽으면 화면 값도 파일 값으로


def test_setup_skip_and_finish(qt, tmp_path, monkeypatch):
    _app, sw, _ = qt
    from app.core import Core
    from app.store import Store
    monkeypatch.setattr(sw.S, "guess_sources", lambda home=None: {"claude_ai": False, "chatgpt": False,
                                                                  "claude_code": False, "codex": False})
    roam = tmp_path / "roam"
    core = Core(Store(roam, tmp_path / "local"), create_config=False)
    w, calls = make(sw, core, setup=True)
    w.reject()                                                    # X, Esc, 건너뛰기
    assert calls["setup"] and calls["setup"][0][0] is False
    assert json.loads((roam / "config.json").read_text(encoding="utf-8")) == {**DEFAULT_CONFIG, "setup_done": True}
    roam2 = tmp_path / "roam2"
    core2 = Core(Store(roam2, tmp_path / "local2"), create_config=False)
    w2, calls2 = make(sw, core2, setup=True)
    w2.setup_sources["chatgpt"].setChecked(True)
    for _ in range(3):
        w2._go(1)
    assert w2.setup_provider["codex"].isChecked() and w2.btn_next.text() == "마치기"
    assert [g.isHidden() for _s, g in w2.setup_guides] == [True, False]
    w2._go(1)
    saved = json.loads((roam2 / "config.json").read_text(encoding="utf-8"))
    assert saved["sources"] == {"claude_ai": False, "chatgpt": True, "claude_code": False, "codex": False}
    assert saved["ask_provider"] == "codex" and saved["queue_sources"] == ["chatgpt", "note"] and saved["setup_done"]
    assert calls2["setup"][0][0] is True


def test_unchanged_save_keeps_file(qt, core_env):
    _app, sw, _ = qt
    core = core_env
    raw = core.store.config_path.read_text(encoding="utf-8")
    w, _ = make(sw, core)
    new = w.build_new()
    assert S.diff(core.config, new) == set()
    core.update_config(copy.deepcopy(new))
    assert json.loads(core.store.config_path.read_text(encoding="utf-8")) == json.loads(raw)
    w.close()


def test_wheel_without_focus_does_not_change_numbers(qt, core_env):
    _app, sw, _ = qt
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    w, _ = make(sw, core_env)
    w.show()
    sp = w.weight_spins["title"]
    before = sp.value()

    def wheel():
        e = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
        _app.sendEvent(sp, e)
    wheel()
    assert sp.value() == before and sp.focusPolicy() == Qt.StrongFocus
    sp.setFocus()
    _app.processEvents()
    if sp.hasFocus():                                   # offscreen에서 초점을 받으면 휠로 바뀜
        wheel()
        assert sp.value() != before
    w._done = True
    w.close()
