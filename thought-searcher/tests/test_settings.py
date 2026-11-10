"""설정 창 로직 (SPEC-settings.md 12번 test_settings.py). Qt 없이."""
import copy
import json

import pytest

from app import settings as S
from app.core import Core
from app.store import DEFAULT_CONFIG, Store


def cfg(**kw):
    c = copy.deepcopy(DEFAULT_CONFIG)
    c.update(kw)
    return c


# ---- 칸 정의 ---------------------------------------------------------------
def test_fields_cover_all_default_keys():
    keys = set(DEFAULT_CONFIG) - S.NOT_IN_WINDOW
    assert set(S.FIELD) == keys, "설정 창에 빠진 키가 있거나 없는 키를 정의함"
    assert S.NOT_IN_WINDOW == {"setup_done"}
    assert {f.tab for f in S.FIELDS} == set(S.TABS)


def test_defaults_pass_validation():
    assert S.validate(cfg()) == {}
    for f in S.FIELDS:
        assert S.field_error(f.key, DEFAULT_CONFIG[f.key]) == "", f.key


# ---- validate --------------------------------------------------------------
@pytest.mark.parametrize("key,lo,hi", [("queue_days", 1, 90), ("queue_focus", 0, 20), ("max_results", 10, 500),
                                       ("code_collect_minutes", 5, 240), ("reminder_days", 0, 60),
                                       ("capture_stale_hours", 1, 72), ("ask_tail_messages", 1, 200),
                                       ("ask_max_chars", 1000, 100000), ("ask_timeout_seconds", 10, 600)])
def test_number_ranges(key, lo, hi):
    assert S.validate(cfg(**{key: lo})) == {}
    assert S.validate(cfg(**{key: hi})) == {}
    assert key in S.validate(cfg(**{key: lo - 1}))
    assert key in S.validate(cfg(**{key: hi + 1}))
    assert "정수" in S.validate(cfg(**{key: "abc"}))[key]
    assert key in S.validate(cfg(**{key: 1.5}))


def test_weights_are_floats_with_ranges():
    w = {**DEFAULT_CONFIG["weights"], "title": 2.5}
    assert S.validate(cfg(weights=w)) == {}
    bad = {**DEFAULT_CONFIG["weights"], "recency_half_life_days": 0}
    assert "recency_half_life_days" in S.validate(cfg(weights=bad))["weights"]


def test_paths_must_exist_only_when_changed(tmp_path):
    old = cfg()
    new = cfg(watch_dir=str(tmp_path / "없음"))
    assert "폴더가 없습니다" in S.validate(new, old)["watch_dir"]
    assert S.validate(new, new) == {}                                   # 손대지 않은 값은 막지 않음
    assert S.validate(cfg(watch_dir=str(tmp_path)), old) == {}
    assert S.validate(cfg(watch_dir=""), old) == {}                     # 빈 값 = 기본값


def test_disabled_service_paths_not_checked(tmp_path):
    old = cfg()
    new = cfg(codex_dir=str(tmp_path / "없음"), sources={**DEFAULT_CONFIG["sources"], "codex": False})
    assert S.validate(new, old) == {}
    new["sources"]["codex"] = True
    assert "codex_dir" in S.validate(new, old)


def test_archive_and_note_dirs(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    errs = S.validate(cfg(archive_dir=str(a), note_dirs=[str(a)]), cfg())
    assert "archive_dir" in errs and "note_dirs" in errs
    assert S.validate(cfg(archive_dir=str(a / "inner"), note_dirs=[str(a)]), cfg()) == {}   # 노트 폴더 안은 허용
    assert "두 번" in S.validate(cfg(note_dirs=[str(b), str(b) + "\\"]), cfg())["note_dirs"]
    assert "없습니다" in S.validate(cfg(note_dirs=[str(tmp_path / "x")]), cfg())["note_dirs"]
    # 보관 폴더가 없으면 validate는 통과시키고 archive_missing이 알려 준다 ('만들까요?')
    new = cfg(archive_dir=str(tmp_path / "새 보관"))
    assert S.validate(new, cfg()) == {} and S.archive_missing(new).endswith("새 보관")
    assert S.archive_missing(cfg()) == ""


@pytest.mark.parametrize("rel,ok", [("template", True), ("a/b", True), ("..", False), ("a/../b", False),
                                    ("C:\\x", False), ("/abs", False)])
def test_queue_exclude_relative_only(rel, ok):
    assert ("queue_note_exclude" not in S.validate(cfg(queue_note_exclude=[rel]))) == ok


def test_regex_error_has_line_number():
    e = S.validate(cfg(extra_redact_patterns=["ok\\d+", "(괄호", "x"]))["extra_redact_patterns"]
    assert e.startswith("2번째 줄:")


def test_open_command_and_url_and_provider():
    assert "{path}" in S.validate(cfg(open_command=["code", "-g"]))["open_command"]
    assert "open_command" in S.validate(cfg(open_command=[]))
    assert "https://" in S.validate(cfg(export_page_url="http://claude.ai"))["export_page_url"]
    assert "ask_provider" in S.validate(cfg(ask_provider="gemini"))
    assert S.validate(cfg(ask_provider="off")) == {}
    assert "queue_sources" in S.validate(cfg(queue_sources=["claude-ai", "slack"]))


def test_cli_path_must_exist_if_path(tmp_path):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"")
    assert S.validate(cfg(ask_command_codex=[str(exe)]), cfg()) == {}
    assert "ask_command_codex" in S.validate(cfg(ask_command_codex=[str(tmp_path / "x.exe")]), cfg())
    assert S.validate(cfg(ask_command=["claude-다른이름"]), cfg()) == {}     # 이름만이면 PATH에서 찾음


def test_no_services_is_warning_not_error():
    off = cfg(sources={s: False for s in S.SERVICES})
    assert S.validate(off) == {}
    assert "노트 폴더만" in S.warnings(off)["sources"]


# ---- 보여 줄 값 -------------------------------------------------------------
def test_shown_invalid_value_falls_back_to_default():
    assert S.shown("queue_days", {"queue_days": "abc"}) == (14, True)
    assert S.shown("queue_days", {"queue_days": 7}) == (7, False)
    assert S.shown("queue_days", {}) == (14, False)
    w, bad = S.shown("weights", {"weights": {"title": "x", "body": 2}})
    assert bad and w["title"] == 10.0 and w["body"] == 2.0


# ---- diff, 저장 -------------------------------------------------------------
def test_diff_only_changed_keys():
    old = cfg()
    assert S.diff(old, copy.deepcopy(old)) == set()
    new = copy.deepcopy(old)
    new["weights"]["recency"] = 0.5
    new["queue_days"] = 7
    assert S.diff(old, new) == {"weights", "queue_days"}


def test_to_save_keeps_unknown_keys_roundtrip(tmp_path):
    roam = tmp_path / "roam"
    roam.mkdir()
    raw = {"archive_dir": str(tmp_path), "my_hand_key": {"x": 1}, "queue_days": 14}
    (roam / "config.json").write_text(json.dumps(raw), encoding="utf-8")
    core = Core(Store(roam, tmp_path / "local"))
    new = copy.deepcopy(core.config)
    assert core.update_config(new) == set()
    assert json.loads((roam / "config.json").read_text(encoding="utf-8")) == raw    # 아무것도 안 바꾸면 그대로
    new = copy.deepcopy(core.config)
    new["queue_days"] = 7
    assert core.update_config(new) == {"queue_days"}
    saved = json.loads((roam / "config.json").read_text(encoding="utf-8"))
    assert saved == {**raw, "queue_days": 7}                       # 기본값 키를 덧붙이지 않고 손으로 넣은 키 보존
    assert core.config["queue_days"] == 7 and core.config is new


def test_update_config_rebuilds_redactor(core_env):
    core = core_env
    old = core.redactor
    new = copy.deepcopy(core.config)
    new["extra_redact_patterns"] = ["사번\\d{6}"]
    assert "extra_redact_patterns" in core.update_config(new)
    assert core.redactor is not old and core.redactor("사번123456 끝") == "***가림:custom*** 끝"


def test_broken_config_rewritten_only_on_save(tmp_path):
    roam = tmp_path / "roam"
    roam.mkdir()
    (roam / "config.json").write_text("{깨짐", encoding="utf-8")
    core = Core(Store(roam, tmp_path / "local"))
    assert core.store.config_broken and (roam / "config.json.bak").exists()
    assert (roam / "config.json").read_text(encoding="utf-8") == "{깨짐"     # 저장 전에는 덮어쓰지 않음
    new = copy.deepcopy(core.config)
    new["queue_days"] = 9
    core.update_config(new)
    saved = json.loads((roam / "config.json").read_text(encoding="utf-8"))
    assert saved["queue_days"] == 9 and saved["hotkey"] == "ctrl+alt+h"
    assert not core.store.config_broken


# ---- 기존 config, 첫 실행 ------------------------------------------------------------
def test_existing_config_without_new_keys_keeps_old_behavior(tmp_path):
    roam = tmp_path / "roam"
    roam.mkdir()
    (roam / "config.json").write_text(json.dumps({"archive_dir": str(tmp_path)}), encoding="utf-8")
    core = Core(Store(roam, tmp_path / "local"), create_config=False)
    assert core.sources == {s: True for s in S.SERVICES}
    assert S.read_queue_sources(core.config) == ("claude-ai", "claude-code", "note")
    assert core.ask_provider == "claude"
    assert not core.store.config_missing                         # 시작 안내 안 뜸


def test_read_rules_for_odd_values():
    assert S.read_sources({}) == {s: True for s in S.SERVICES}
    assert S.read_sources({"sources": {"chatgpt": False}}) == {**{s: True for s in S.SERVICES}, "chatgpt": False}
    assert S.read_sources({"sources": "x"}) == {s: True for s in S.SERVICES}
    assert S.read_queue_sources({"queue_sources": ["note", "codex"]}) == ("codex", "note")
    assert S.read_provider({"ask_provider": "이상함"}) == "claude"


def test_missing_config_means_setup_and_is_not_created(tmp_path):
    roam = tmp_path / "roam"
    core = Core(Store(roam, tmp_path / "local"), create_config=False)
    assert core.store.config_missing and not (roam / "config.json").exists()
    core.update_config(S.skip_config())
    saved = json.loads((roam / "config.json").read_text(encoding="utf-8"))
    assert saved == {**DEFAULT_CONFIG, "setup_done": True}      # 건너뛰기 = 지금 기본값 + setup_done
    # 다음 실행: config.json이 있으므로 시작 안내 안 뜸
    again = Core(Store(roam, tmp_path / "local"), create_config=False)
    assert not again.store.config_missing


def test_cli_core_still_creates_config(tmp_path):
    roam = tmp_path / "roam"
    Core(Store(roam, tmp_path / "local"))
    assert (roam / "config.json").exists()


# ---- 시작 안내 기본값 ----------------------------------------------------------
def test_setup_defaults_from_install_traces(tmp_path):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    g = S.guess_sources(home)
    assert g == {"claude_ai": False, "chatgpt": False, "claude_code": True, "codex": False}
    assert S.setup_provider(g) == "claude"
    home2 = tmp_path / "home2"
    (home2 / ".codex").mkdir(parents=True)
    g2 = S.guess_sources(home2)
    assert g2["codex"] and not g2["claude_code"] and S.setup_provider(g2) == "codex"
    nothing = S.guess_sources(tmp_path / "empty")
    assert not any(nothing.values()) and S.setup_provider(nothing) == "off"
    colleague = {**nothing, "chatgpt": True}
    c = S.setup_config(colleague)
    assert c["ask_provider"] == "codex" and c["queue_sources"] == ["chatgpt", "note"]
    assert c["sources"] == {"claude_ai": False, "chatgpt": True, "claude_code": False, "codex": False}
    assert c["setup_done"] is True
    assert S.setup_config({"codex": True})["queue_sources"] == ["codex", "note"]


# ---- 단축키 ---------------------------------------------------------------
@pytest.mark.parametrize("raw,norm", [("Ctrl+Alt+H", "ctrl+alt+h"), ("alt+control+j", "ctrl+alt+j"),
                                      ("shift + win + F5", "shift+win+f5"), ("ctrl+.", "ctrl+."),
                                      ("ctrl+alt+space", "ctrl+alt+space")])
def test_hotkey_normalize(raw, norm):
    assert S.normalize_hotkey(raw) == norm


@pytest.mark.parametrize("raw", ["ctrl+alt", "h", "ctrl+a+b", "ctrl+alt+esc", "", "ctrl++"])
def test_hotkey_rejects_bad_shapes(raw):
    with pytest.raises(ValueError):
        S.normalize_hotkey(raw)


def test_hotkey_reserved_and_other_tools():
    for k in ("win+v", "Win+;", "win+shift+s", "ctrl+space", "shift+space"):
        assert S.check_hotkey(k)[1], k
    norm, err, warn = S.check_hotkey("Win+.")
    assert norm == "win+." and not err and "emoji-searcher" in warn
    assert "hangul-restore" in S.check_hotkey("ctrl+alt+k")[2]
    assert S.check_hotkey("ctrl+alt+j") == ("ctrl+alt+j", "", "")
    assert "hotkey" in S.validate(cfg(hotkey="win+v")) and "hotkey" not in S.validate(cfg(hotkey="win+."))
    assert S.display_hotkey("ctrl+alt+h") == "Ctrl+Alt+H"


def test_hotkey_names_match_hotkey_module():
    """settings의 키 이름이 hotkey.parse_hotkey와 같은 가상 키 코드가 되는지."""
    hk = pytest.importorskip("app.hotkey")
    for vk, name in S.VK_NAME.items():
        assert hk.parse_hotkey(f"ctrl+{name}") == (hk.MOD_CONTROL, vk), name
    mods, _ = hk.parse_hotkey(S.normalize_hotkey("Win+Shift+Alt+Ctrl+x"))
    assert mods == hk.MOD_CONTROL | hk.MOD_ALT | hk.MOD_SHIFT | hk.MOD_WIN


def test_command_split_join():
    assert S.split_command('code -g "{path}:{line}"') == ["code", "-g", "{path}:{line}"]
    assert S.split_command(r'"C:\Program Files\x\x.exe" {path}') == [r"C:\Program Files\x\x.exe", "{path}"]
    args = [r"C:\Program Files\x.exe", "-g", "{path}:{line}"]
    assert S.split_command(S.join_command(args)) == args
