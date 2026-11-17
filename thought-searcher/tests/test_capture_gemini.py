"""Gemini 자동 수집 파일 (userscript/gemini-sync.user.js). 합성 수집 파일만 쓴다.
턴 모양은 2026-11-17 실제 batchexecute 응답과 같은 칸 위치로 만든다 (app/importers/gemini.py 설명)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.archive import read_front_file
from app.importers import ImportFailed
from app.importers import claude_capture as cc
from app.importers import gemini

T0 = 1794280000


def cand(rcid, text):
    return [rcid, [text], None, None, None, None, None, None, [2], "ko"]


def gturn(rid, prompt, answers, t, chosen=None):
    """사이트가 주는 턴 하나. answers: [(후보 id, 글)]"""
    resp = [[cand(r, a) for r, a in answers], None, None, chosen or answers[0][0], None, None, None, None, "KR", True]
    return [["c_g1", rid], None, [[prompt, None, None, None, [[]]], 1, None, 1, "m1"], resp, [t, 500000000]]


def gem_data(turns=None, title="Gemini 대화", updated=None):
    turns = turns if turns is not None else [
        # 사이트는 최신 턴부터 준다
        gturn("r_2", "두 번째 질문", [("rc_b", "두 번째 답")], T0 + 60),
        gturn("r_1", "첫 질문", [("rc_x", "다시 실행 전 답"), ("rc_a", "첫 답")], T0, chosen="rc_a"),
    ]
    return {"id": "c_g1", "title": title, "updated": updated or [T0 + 60, 0], "turns": turns}


def write_gem(folder, data):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"gemini_{data['id'][2:]}.json"
    p.write_text(json.dumps({"format": cc.FORMAT, "site": "gemini", "captured_at": "2026-11-17T01:00:00Z",
                             "project": None, "data": data}, ensure_ascii=False), encoding="utf-8")
    return p


def test_read_gemini_capture_orders_turns_and_keeps_chosen_answer(tmp_path):
    conv = cc.read_capture(write_gem(tmp_path, gem_data()))
    assert conv.conv_id == "gemini:g1" and conv.source == "gemini" and conv.title == "Gemini 대화"
    assert conv.url == "https://gemini.google.com/app/g1"
    assert [m.text for m in conv.messages if m.on_main_branch] == ["첫 질문", "첫 답", "두 번째 질문", "두 번째 답"]
    assert [m.text for m in conv.messages if not m.on_main_branch] == ["다시 실행 전 답"]
    assert [m.role for m in conv.messages if m.on_main_branch] == ["user", "assistant"] * 2
    assert conv.created == datetime.fromtimestamp(T0 + 0.5, tz=timezone.utc)
    assert conv.updated == datetime.fromtimestamp(T0 + 60.5, tz=timezone.utc)


def test_gemini_title_falls_back_to_first_prompt():
    conv = gemini.convert_capture(gem_data(title=""))
    assert conv.title == "첫 질문"


def test_gemini_skips_turns_it_cannot_read():
    broken = ["이상한 턴"]                                       # 칸 위치가 바뀐 턴: 건너뜀
    no_answer = [["c_g1", "r_3"], None, [["답 없는 질문"]], [[]], [T0 + 90, 0]]
    conv = gemini.convert_capture(gem_data(turns=gem_data()["turns"] + [broken, no_answer]))
    texts = [m.text for m in conv.messages]
    assert "답 없는 질문" in texts and len(texts) == 6
    assert gemini.convert_capture(gem_data(turns=[])) is None


def test_gemini_capture_errors(tmp_path):
    d = gem_data()
    del d["turns"]
    with pytest.raises(ImportFailed):
        cc.read_capture(write_gem(tmp_path, d))
    with pytest.raises(ImportFailed):
        cc.read_capture(write_gem(tmp_path, {**gem_data(), "id": ""}))


def test_site_of_and_patterns(tmp_path):
    assert cc.site_of("gemini_g1.json") == "gemini" and cc.site_of("chatgpt_x.json") == "chatgpt"
    assert cc.capture_uuid("gemini_g1.json") == ""              # 수집 제외는 claude.ai만
    write_gem(tmp_path, gem_data())
    assert [p.name for p in cc.capture_files(tmp_path)] == ["gemini_g1.json"]


def test_core_imports_gemini_and_reports_status(core_env):
    core = core_env
    d = core.capture_dir
    write_gem(d, gem_data())
    r = core.import_captures()
    assert r.new == 1 and r.failed == []
    md = core.archive().find("gemini:g1")
    assert md is not None and md.parent.parent.name == "gemini"
    assert read_front_file(md)["source"] == "gemini"
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    (d / "_status_gemini.json").write_text(json.dumps({
        "format": cc.STATUS_FORMAT, "site": "gemini", "last_ok": (now - timedelta(hours=5)).isoformat(),
        "error": None}), encoding="utf-8")
    assert core.capture_site_status("gemini").endswith("대화 1개")
    assert any(x.startswith("Gemini 자동 수집") for x in core.capture_status_line().splitlines())
    msg_ = core.capture_notice(now)
    assert msg_.startswith("Gemini 자동 수집이 5시간째") and "Gemini 탭" in msg_


def test_gemini_off_ignores_capture(core_env):
    core = core_env
    core.config["sources"] = {**core.sources, "gemini": False}
    write_gem(core.capture_dir, gem_data())
    assert core.pending_captures() == [] and core.import_captures().new == 0
    core.config["sources"] = {**core.sources, "gemini": True}
    assert core.import_captures().new == 1


def test_search_alias():
    from app.query import parse
    q = parse("질문 src:gemini")
    assert q.sources == ["gemini"] and "src:gemini" in q.filter_labels()
    assert parse("src:gem").sources == ["gemini"]
