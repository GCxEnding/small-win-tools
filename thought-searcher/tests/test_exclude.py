"""claude.ai 수집 제외 (Tampermonkey 메뉴에서 뺀 대화, 프로젝트). 2026-11-11 CG 요청.

스크립트가 _status.json의 "exclude"에 목록을 쓰면 앱은
- 기존 md(대화, 프로젝트 문서), 다운로드 폴더의 수집 파일, 원본 사본, 요약, 큐 기록을 지우고
- 앞으로 오는 수집 파일과 내보내기 zip에서도 뺀다.
"""
import json
import os

from conftest import make_export_zips
from test_capture import conv_data, write_capture

from app.importers import claude_capture as cc

U1 = "aaaaaaaa-0000-4000-8000-000000000001"
U2 = "bbbbbbbb-0000-4000-8000-000000000002"
U3 = "cccccccc-0000-4000-8000-000000000003"
P1 = "p1000000-0000-4000-8000-000000000001"


def write_status(folder, conversations=(), projects=(), stamp=0):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / cc.STATUS_NAME
    p.write_text(json.dumps({
        "format": cc.STATUS_FORMAT, "last_run": "2026-11-11T00:00:00Z", "last_ok": "2026-11-11T00:00:00Z",
        "saved": 0, "error": None,
        "exclude": {"conversations": [{"uuid": u, "title": "개인", "project": None} for u in conversations],
                    "projects": [{"uuid": u, "name": "개인 프로젝트"} for u in projects]}}), encoding="utf-8")
    if stamp:
        os.utime(p, (p.stat().st_atime, p.stat().st_mtime + stamp))
    return p


def test_read_exclude():
    assert cc.read_exclude({"format": cc.STATUS_FORMAT}) is None              # 예전 스크립트
    ex = cc.read_exclude({"exclude": {"conversations": [{"uuid": U1, "title": "t"}, {"uuid": "../x"}],
                                      "projects": [{"uuid": P1, "name": "n"}]}})
    assert ex.conversations == {U1: "t"} and ex.projects == {P1: "n"}       # 이상한 uuid는 버림
    assert cc.capture_uuid(f"claude-ai_{U1}.json") == U1 and cc.capture_uuid("chatgpt_x.json") == ""


def test_excluding_removes_existing_traces(core_env):
    core = core_env
    d = core.capture_dir
    p1 = write_capture(d, conv_data(U1))
    write_capture(d, conv_data(U2))
    assert core.import_captures().new == 2
    md1 = core.archive().find(f"claude-ai:{U1}")
    assert md1.is_file() and (core.capture_raw_dir / p1.name).is_file()
    core.summaries.put(f"claude-ai:{U1}", 0, "개인 요약", "claude:haiku")
    core.close_item(f"claude-ai:{U1}", "done")
    assert not core.exclusions_pending()
    write_status(d, conversations=[U1])
    assert core.exclusions_pending()
    r = core.import_captures()
    assert r.removed == 1 and not md1.exists() and not p1.exists() and not (core.capture_raw_dir / p1.name).exists()
    assert core.archive().find(f"claude-ai:{U2}") is not None                   # 다른 대화는 그대로
    assert core.summaries.get(f"claude-ai:{U1}") is None
    assert f"claude-ai:{U1}" not in core.state["queue_closed"]
    from app.index import connect
    conn = connect(core.store.index_path)
    assert conn.execute("SELECT count(*) FROM docs WHERE conv_id=?", (f"claude-ai:{U1}",)).fetchone()[0] == 0
    assert not core.exclusions_pending()                                        # 한 번만


def test_excluded_capture_file_is_never_imported(core_env):
    core = core_env
    d = core.capture_dir
    write_status(d, conversations=[U3])
    p = write_capture(d, conv_data(U3))
    r = core.import_captures()
    assert r.new == 0 and not p.exists() and core.archive().find(f"claude-ai:{U3}") is None


def test_list_survives_missing_status_file(core_env):
    core = core_env
    s = write_status(core.capture_dir, conversations=[U1])
    core.import_captures()
    s.unlink()
    assert U1 in core.capture_exclude.conversations                             # state.json에 남겨 둔 목록


def test_zip_import_skips_excluded(core_env, tmp_path):
    core = core_env
    c1, c2 = "c1000000-0000-4000-8000-000000000001", "c2000000-0000-4000-8000-000000000002"
    write_status(core.capture_dir, conversations=[c1], projects=[P1])
    for z in make_export_zips(tmp_path / "zips"):
        core.import_zip(z)
    arch = core.archive()
    assert arch.find(f"claude-ai:{c1}") is None and arch.find(f"claude-ai:{c2}") is not None
    assert arch.find(f"claude-ai-project:{P1}") is None
    mem = arch.find("claude-ai-memory:main").read_text(encoding="utf-8")
    assert "프로젝트 메모리" not in mem and "fluentbit" not in mem                  # 뺀 프로젝트의 메모리 항목
    assert "Claude 메모리" in mem                                                  # 나머지 메모리는 그대로


def test_unexcluded_conversation_comes_back(core_env):
    core = core_env
    d = core.capture_dir
    write_status(d, conversations=[U1])
    core.import_captures()
    write_status(d, conversations=[], stamp=5)                                   # 메뉴에서 되돌림
    write_capture(d, conv_data(U1))                                               # 스크립트가 다시 받음
    assert core.import_captures().new == 1
