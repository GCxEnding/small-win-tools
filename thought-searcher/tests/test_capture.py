"""claude.ai 자동 수집 파일 가져오기 (SPEC-queue.md 3-D, 3-E). 합성 수집 파일만 쓴다."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.archive import read_front_file
from app.importers import ImportFailed
from app.importers import claude_capture as cc

ROOT = "00000000-0000-4000-8000-000000000000"


def msg(uid, parent, sender, text, t):
    return {"uuid": uid, "parent_message_uuid": parent, "sender": sender, "text": text,
            "content": [{"type": "text", "text": text}], "created_at": t, "updated_at": t,
            "attachments": [], "files": [], "index": 0, "truncated": False}


def conv_data(uuid="c1", name="수집 대화", updated="2026-11-10T01:00:00Z", leaf=None, extra=()):
    ms = [msg("m1", ROOT, "human", "질문 하나", "2026-11-10T00:00:00Z"),
          msg("m2", "m1", "assistant", "답 하나", "2026-11-10T00:01:00Z"),
          # 같은 질문의 다른 답(가지). 가장 늦지만 지금 보는 가지는 m2
          msg("m3", "m1", "assistant", "다른 가지 답", "2026-11-10T00:05:00Z")]
    ms += list(extra)
    return {"uuid": uuid, "name": name, "created_at": "2026-11-10T00:00:00Z", "updated_at": updated,
            "current_leaf_message_uuid": leaf or "m2", "chat_messages": ms, "model": "x", "summary": ""}


def write_capture(folder, data, project=None, fmt=cc.FORMAT):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"claude-ai_{data['uuid']}.json"
    p.write_text(json.dumps({"format": fmt, "site": "claude-ai", "captured_at": "2026-11-10T01:00:00Z",
                             "project": project, "data": data}, ensure_ascii=False), encoding="utf-8")
    return p


def write_status(folder, last_ok, error=None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / cc.STATUS_NAME).write_text(json.dumps({
        "format": cc.STATUS_FORMAT, "last_run": last_ok, "last_ok": last_ok, "saved": 1, "error": error}),
        encoding="utf-8")


# ---- 파일 하나 ---------------------------------------------------------------
def test_read_capture_uses_current_leaf_and_project(tmp_path):
    p = write_capture(tmp_path, conv_data(), project="생각 검색기")
    conv = cc.read_capture(p)
    assert conv.conv_id == "claude-ai:c1" and conv.title == "수집 대화" and conv.project == "생각 검색기"
    main = [m.text for m in conv.messages if m.on_main_branch]
    branch = [m.text for m in conv.messages if not m.on_main_branch]
    assert main == ["질문 하나", "답 하나"] and branch == ["다른 가지 답"]


def test_read_capture_without_leaf_falls_back_to_latest(tmp_path):
    d = conv_data()
    del d["current_leaf_message_uuid"]
    conv = cc.read_capture(write_capture(tmp_path, d))
    assert [m.text for m in conv.messages if m.on_main_branch] == ["질문 하나", "다른 가지 답"]
    assert conv.project == ""


def test_read_capture_errors(tmp_path):
    bad = write_capture(tmp_path, conv_data(), fmt="something-else/1")
    with pytest.raises(ImportFailed):
        cc.read_capture(bad)
    half = tmp_path / "claude-ai_half.json"
    half.write_text('{"format": "thought-searcher.capture/1", "data": {', encoding="utf-8")
    with pytest.raises(cc.NotReady):
        cc.read_capture(half)
    empty = write_capture(tmp_path, {**conv_data("c9"), "chat_messages": []})
    assert cc.read_capture(empty) is None


# ---- Core -------------------------------------------------------------------
@pytest.fixture
def cap(core_env):
    core = core_env
    return core, core.capture_dir


def test_capture_dir_default_and_config(core_env, tmp_path):
    assert core_env.capture_dir == tmp_path / "dl" / "claude-sync"
    core_env.config["capture_dir"] = str(tmp_path / "elsewhere")
    assert core_env.capture_dir == tmp_path / "elsewhere"


def test_import_new_then_unchanged_then_changed(cap):
    core, d = cap
    p = write_capture(d, conv_data(), project="데모")
    assert core.pending_captures() == [p]
    r = core.import_captures()
    assert (r.new, r.changed, r.failed) == (1, 0, [])
    md = core.archive().find("claude-ai:c1")
    front = read_front_file(md)
    assert front["source"] == "claude-ai" and front["project"] == "데모"
    assert (core.capture_raw_dir / p.name).is_file()
    assert core.state["capture_files"][p.name]["updated"].startswith("2026-11-10T01:00:00")
    assert core.pending_captures() == []
    assert core.import_captures().new == 0
    # 대화가 이어짐: 같은 파일을 덮어씀
    more = msg("m4", "m2", "human", "이어진 질문", "2026-11-10T02:00:00Z")
    p = write_capture(d, conv_data(updated="2026-11-10T02:00:00Z", leaf="m4", extra=[more]), project="데모")
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))
    r = core.import_captures()
    assert (r.new, r.changed) == (0, 1)
    assert "이어진 질문" in md.read_text(encoding="utf-8")
    assert core.state.get("last_zip_import", "") == ""      # 주간 내보내기 알림 기준은 그대로


def test_older_capture_does_not_overwrite_newer_md(cap):
    core, d = cap
    write_capture(d, conv_data(updated="2026-11-10T05:00:00Z"))
    core.import_captures()
    md = core.archive().find("claude-ai:c1")
    before = md.read_text(encoding="utf-8")
    other = d.parent / "old"
    p = write_capture(other, conv_data(name="옛 제목", updated="2026-11-09T00:00:00Z"))
    core.config["capture_dir"] = str(other)
    r = core.import_captures()
    assert (r.new, r.changed) == (0, 0)
    assert md.read_text(encoding="utf-8") == before
    assert p.name in core.state["capture_files"]


def test_half_written_file_retried_and_bad_format_recorded(cap):
    core, d = cap
    d.mkdir(parents=True)
    half = d / "claude-ai_half.json"
    half.write_text("{", encoding="utf-8")
    bad = write_capture(d, conv_data("c2"), fmt="other/1")
    r = core.import_captures()
    assert r.not_ready == 1 and len(r.failed) == 1
    assert core.pending_captures() == [half]               # 덜 써진 것만 다음에 다시
    assert "error" in core.state["capture_files"][bad.name]


def test_status_line_and_stale_notice(cap):
    core, d = cap
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    assert core.capture_notice(now) is None                 # 수집한 적 없는 PC
    assert core.capture_status_line() == "자동 수집: 없음"
    write_status(d, (now - timedelta(hours=1)).isoformat())
    assert core.capture_notice(now) is None
    assert "마지막 성공" in core.capture_status_line()
    write_status(d, (now - timedelta(hours=5)).isoformat(), error="auth: 로그아웃 상태입니다.")
    msg_ = core.capture_notice(now)
    assert "5시간째 멈춰" in msg_ and "로그아웃" in msg_
    assert core.capture_notice(now + timedelta(hours=2)) is None   # 하루 한 번
    assert core.capture_notice(now + timedelta(hours=25)) is not None
    assert "오류: auth" in core.capture_status_line()


def test_misplaced_capture_notice_once(cap):
    core, d = cap
    write_capture(core.watch_dir, conv_data())               # 하위 폴더 대신 다운로드 폴더 바로 아래
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    assert "Tampermonkey" in core.capture_notice(now)
    assert core.capture_notice(now) is None


def test_files_made_by_ai_become_attachments(tmp_path):
    a = msg("m2", "m1", "assistant", "파일 드립니다", "2026-11-10T00:01:00Z")
    a["content"] = [
        {"type": "tool_use", "name": "present_files", "input": {"filepaths": ["/mnt/user-data/outputs/a.md"]}},
        {"type": "tool_result", "name": "SendUserFile", "content": [],
         "file_deliveries": [{"file_uuid": "u", "path": "/mnt/user-data/outputs/br/독후감.md"},
                             {"file_uuid": "u2", "path": "/mnt/user-data/outputs/a.md"}]},
        {"type": "text", "text": "파일 드립니다"}]
    a["files"] = [{"file_name": "이미있음.png"}]
    d = conv_data()
    d["chat_messages"][1] = a
    conv = cc.read_capture(write_capture(tmp_path, d))
    text = next(m.text for m in conv.messages if m.native_id == "m2")
    assert text.splitlines()[0] == "파일 드립니다"
    assert [ln for ln in text.splitlines() if ln.startswith("📎")] == [
        "📎 첨부: 이미있음.png", "📎 첨부: a.md", "📎 첨부: 독후감.md"]


# ---- ChatGPT ----------------------------------------------------------------
def gpt_data(cid="g1", title="GPT 대화", update_time=1794283200.0, iso=False):
    def node(nid, parent, role, text, t, children):
        return {"id": nid, "parent": parent, "children": children,
                "message": None if role is None else {
                    "id": nid, "author": {"role": role}, "create_time": t, "recipient": "all",
                    "content": {"content_type": "text", "parts": [text]}, "metadata": {}}}
    t0 = 1794280000.0
    mapping = {
        "root": node("root", None, None, "", None, ["u1"]),
        "u1": node("u1", "root", "user", "GPT 질문", t0, ["a1", "a2"]),
        "a1": node("a1", "u1", "assistant", "옛 답", t0 + 10, []),
        "a2": node("a2", "u1", "assistant", "새 답", t0 + 20, []),
    }
    d = {"conversation_id": cid, "title": title, "create_time": t0, "update_time": update_time,
         "current_node": "a2", "mapping": mapping}
    if iso:   # 응답 시각이 문자열로 와도 받는다
        d["create_time"] = "2026-11-10T00:00:00.000000Z"
        d["update_time"] = "2026-11-10T01:00:00.000000Z"
        for n in mapping.values():
            if n["message"]:
                n["message"]["create_time"] = "2026-11-10T00:00:10Z"
    return d


def write_gpt(folder, data):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"chatgpt_{data['conversation_id']}.json"
    p.write_text(json.dumps({"format": cc.FORMAT, "site": "chatgpt", "captured_at": "2026-11-10T01:00:00Z",
                             "project": None, "data": data}, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.mark.parametrize("iso", [False, True])
def test_read_chatgpt_capture(tmp_path, iso):
    conv = cc.read_capture(write_gpt(tmp_path, gpt_data(iso=iso)))
    assert conv.conv_id == "chatgpt:g1" and conv.source == "chatgpt" and conv.title == "GPT 대화"
    assert [m.text for m in conv.messages if m.on_main_branch] == ["GPT 질문", "새 답"]
    assert [m.text for m in conv.messages if not m.on_main_branch] == ["옛 답"]
    if iso:
        assert conv.updated == datetime(2026, 11, 10, 1, 0, tzinfo=timezone.utc)


def test_chatgpt_capture_without_mapping_fails(tmp_path):
    d = gpt_data()
    del d["mapping"]
    with pytest.raises(ImportFailed):
        cc.read_capture(write_gpt(tmp_path, d))


def test_core_imports_both_sites_and_reports_each(cap):
    core, d = cap
    write_capture(d, conv_data())
    write_gpt(d, gpt_data())
    r = core.import_captures()
    assert r.new == 2 and core.archive().find("chatgpt:g1") is not None
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    write_status(d, (now - timedelta(minutes=10)).isoformat())
    (d / "_status_chatgpt.json").write_text(json.dumps({
        "format": cc.STATUS_FORMAT, "site": "chatgpt", "last_ok": (now - timedelta(hours=4)).isoformat(),
        "error": None}), encoding="utf-8")
    lines = core.capture_status_line().splitlines()
    assert lines[0].startswith("claude.ai 자동 수집") and "대화 1개" in lines[0]
    assert lines[1].startswith("ChatGPT 자동 수집") and "대화 1개" in lines[1]
    msg_ = core.capture_notice(now)
    assert msg_.startswith("ChatGPT 자동 수집이 4시간째") and "ChatGPT 탭" in msg_
    assert core.capture_notice(now) is None
