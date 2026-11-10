"""쓰는 서비스 끄기 (SPEC-settings.md 3-C, 12번 test_sources.py). 합성 데이터만."""
import copy
from datetime import datetime, timedelta, timezone

import pytest
from conftest import FIXTURES, KST, make_export_zips
from test_capture import conv_data, gpt_data, write_capture, write_gpt, write_status
from test_codex import NATIVE, NATIVE_ITEMS, make_codex
from test_importer_chatgpt import _conv, _zip


def turn(core, **flags):
    """설정 창 저장과 같은 길로 sources를 바꾼다."""
    new = copy.deepcopy(core.config)
    new["sources"] = {**core.sources, **flags}
    core.update_config(new)


def claude_zip(tmp_path):
    return next(z for z in make_export_zips(tmp_path / "exp") if z.name.startswith("conversations"))


# ---- claude.ai --------------------------------------------------------------
def test_claude_ai_off_skips_zip_without_history_then_on_imports(core_env, tmp_path):
    core = core_env
    z = claude_zip(tmp_path)
    turn(core, claude_ai=False)
    out = core.import_zip(z)
    assert out.result == "off" and core.state["zips"] == {}
    assert not core.known_zip(z)
    turn(core, claude_ai=True)                                  # 다시 켜면 다음 확인 때 가져옴
    assert core.import_zip(z).result == "ok"
    assert len(core.state["zips"]) == 1


def test_claude_ai_off_no_reminder_no_capture_no_notices(core_env):
    core = core_env
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    core.state["first_run"] = (now - timedelta(days=30)).isoformat()
    assert core.reminder_due(now) is not None
    d = core.capture_dir
    write_capture(d, conv_data())
    write_capture(core.watch_dir, conv_data("c-misplaced"))      # 잘못 저장된 수집 파일
    write_status(d, (now - timedelta(hours=10)).isoformat())
    turn(core, claude_ai=False)
    assert core.reminder_due(now) is None
    assert core.pending_captures() == []
    r = core.import_captures()
    assert r.new == 0 and core.state["capture_files"] == {}      # 이력에도 남기지 않음
    assert core.capture_notice(now) is None                       # 멈춤, 잘못 저장 알림 모두 없음
    assert "claude.ai 자동 수집" not in core.status_text()
    assert "claude.ai zip" not in core.status_text()
    turn(core, claude_ai=True)
    assert core.import_captures().new == 1


def test_reminder_days_zero_means_off(core_env):
    core = core_env
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    core.state["first_run"] = (now - timedelta(days=30)).isoformat()
    core.config["reminder_days"] = 0
    assert core.reminder_due(now) is None
    core.config["reminder_days"] = 7
    assert core.reminder_due(now) is not None


# ---- ChatGPT ----------------------------------------------------------------
def test_chatgpt_off_ignores_zip_and_capture(core_env, tmp_path):
    core = core_env
    z = _zip(tmp_path / "gpt.zip", [_conv()])
    write_gpt(core.capture_dir, gpt_data())
    write_capture(core.capture_dir, conv_data())
    turn(core, chatgpt=False)
    assert core.import_zip(z).result == "off" and core.state["zips"] == {}
    r = core.import_captures()
    assert r.new == 1 and list(core.state["capture_files"]) == ["claude-ai_c1.json"]   # claude.ai만
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    (core.capture_dir / "_status_chatgpt.json").write_text(
        '{"format": "thought-searcher.capture-status/1", "last_ok": "2026-11-09T00:00:00Z"}', encoding="utf-8")
    assert core.capture_notice(now) is None                     # ChatGPT 멈춤 알림 없음
    turn(core, chatgpt=True)
    assert core.import_zip(z).result == "ok"
    assert core.import_captures().new == 1


# ---- Claude Code, Codex ---------------------------------------------------------
@pytest.fixture
def code_and_codex(core_env, tmp_path):
    core = core_env
    proj = core.projects_dir / "D--demo"
    proj.mkdir(parents=True)
    (proj / "sess-1.jsonl").write_bytes((FIXTURES / "code_session.jsonl").read_bytes())
    make_codex(core.codex_dir, [NATIVE], {NATIVE[0]: NATIVE_ITEMS})
    return core


def test_claude_code_off_collects_nothing_from_code(code_and_codex):
    core = code_and_codex
    turn(core, claude_code=False, codex=False)
    r = core.collect_code()
    assert (r.new, r.changed) == (0, 0)
    assert core.state.get("code_files", {}) == {} and not core.store.raw_dir.exists()
    assert "Claude Code 수집" not in core.status_text() and "Codex 수집" not in core.status_text()


def test_codex_only(code_and_codex):
    core = code_and_codex
    turn(core, claude_code=False)
    r = core.collect_code()
    assert r.new == 1
    assert core.archive().find("codex:t-native") is not None
    assert not core.store.raw_dir.exists()                        # Claude Code 원본 복사도 안 함
    assert "마지막 Codex 수집" in core.status_text()
    turn(core, claude_code=True)
    assert core.collect_code().new == 1                           # 켜면 다음 수집에서 들어옴


def test_all_off_status_says_notes_only(core_env):
    core = core_env
    turn(core, claude_ai=False, chatgpt=False, claude_code=False, codex=False)
    assert "노트 폴더만" in core.status_text()
    assert core.collect_code().new == 0


def test_capture_site_status_lines(core_env):
    core = core_env
    assert core.capture_site_status("chatgpt") == "아직 수집 기록 없음"
    write_capture(core.capture_dir, conv_data())
    core.import_captures()
    write_status(core.capture_dir, datetime(2026, 11, 10, 5, 20, tzinfo=timezone.utc).isoformat())
    assert core.capture_site_status("claude-ai") == "마지막 성공 11-10 14:20, 대화 1개"
    write_status(core.capture_dir, datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc).isoformat(), error="로그아웃됨")
    assert core.capture_site_status("claude-ai") == "오류: 로그아웃됨 (11-10 13:00)"
    assert KST.utcoffset(None) == timedelta(hours=9)
