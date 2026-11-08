import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import EXPORT_DIR, KST, TODAY, make_export_zips, zip_folder

from app.archive import Archive, atomic_write, read_front_file, slugify
from app.model import Conversation, Message

C1 = "claude-ai:c1000000-0000-4000-8000-000000000001"
C5 = "claude-ai:c5000000-0000-4000-8000-000000000005"


def _mtimes(root):
    return {p: p.stat().st_mtime_ns for p in root.rglob("*.md")}


def _newer_export(tmp_path):
    """c1에 메시지가 하나 늘고 c5가 사라진, 더 최신 내보내기."""
    src = tmp_path / "newer_src"
    data = json.loads((EXPORT_DIR / "conversations-000" / "conversations.json").read_text("utf-8"))
    data = [c for c in data if c.get("uuid") != C5.split(":")[1]]
    c1 = next(c for c in data if c.get("uuid") == C1.split(":")[1])
    c1["updated_at"] = "2026-11-01T00:00:00.000000Z"
    c1["chat_messages"].append({"uuid": "c1-m7", "parent_message_uuid": "c1-m6", "sender": "human",
                                "created_at": "2026-11-01T00:00:00.000000Z", "text": "추가 질문",
                                "content": [{"type": "text", "text": "추가 질문"}], "attachments": [], "files": []})
    (src / "conversations-000").mkdir(parents=True)
    (src / "conversations-000" / "conversations.json").write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    return zip_folder(src / "conversations-000", tmp_path / "newer.zip")


def test_same_zip_twice_writes_nothing(core_env, tmp_path):
    zips = make_export_zips(tmp_path / "z")
    for z in zips:
        core_env.import_zip(z)
    before = _mtimes(core_env.archive_dir)
    # 같은 해시: 건너뜀
    assert core_env.import_zip(zips[0]).result == "skipped"
    # 해시가 달라도(다시 압축) 내용이 같으면 쓰지 않음
    rezip = make_export_zips(tmp_path / "z2")
    import zipfile
    for z in rezip:
        with zipfile.ZipFile(z, "a") as zz:
            zz.writestr("readme.txt", "다른 해시")
    outs = [core_env.import_zip(z) for z in rezip]
    assert all(o.counts.get("new", 0) == 0 and o.counts.get("changed", 0) == 0 for o in outs if o.result == "ok")
    assert _mtimes(core_env.archive_dir) == before


def test_older_zip_changes_nothing(core_env, tmp_path):
    zips = make_export_zips(tmp_path / "z")
    newer = _newer_export(tmp_path)
    assert core_env.import_zip(newer).counts["new"] == 4
    a = core_env.archive()
    for z in zips:
        core_env.import_zip(z)
    p1 = a.find(C1)
    assert "추가 질문" in p1.read_text("utf-8")          # 오래된 zip이 덮어쓰지 않음
    # 오래된 zip에만 있는 c5는 새로 생기지만, 오래된 zip이라 missing 판정은 하지 않음
    assert read_front_file(a.find(C1))["source_status"] == "present"


def test_missing_and_return(core_env, tmp_path):
    zips = make_export_zips(tmp_path / "z")
    conv_zip = next(z for z in zips if z.stem.startswith("conversations"))
    core_env.import_zip(conv_zip)
    newer = _newer_export(tmp_path)
    out = core_env.import_zip(newer)
    assert out.counts["missing"] == 1
    a = core_env.archive()
    meta = read_front_file(a.find(C5))
    assert meta["source_status"] == "missing" and meta["missing_since"]
    # 다시 나타나면 present (더 최신 스냅숏에 다시 포함)
    data = json.loads((EXPORT_DIR / "conversations-000" / "conversations.json").read_text("utf-8"))
    for c in data:
        if isinstance(c.get("updated_at"), str):
            c["updated_at"] = "2026-11-02T00:00:00.000000Z"
    src = tmp_path / "back" / "conversations-000"
    src.mkdir(parents=True)
    (src / "conversations.json").write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    core_env.import_zip(zip_folder(src, tmp_path / "back.zip"))
    meta = read_front_file(a.find(C5))
    assert meta["source_status"] == "present" and meta["missing_since"] == ""


def test_non_latest_zip_does_not_mark_missing(core_env, tmp_path):
    newer = _newer_export(tmp_path)
    core_env.import_zip(newer)
    zips = make_export_zips(tmp_path / "z")
    conv_zip = next(z for z in zips if z.stem.startswith("conversations"))
    # 오래된 zip에는 newer에 없던 것이 없다. 반대로 newer의 대화가 오래된 zip에 다 있으니 missing 0이어야 하고,
    # 판정 자체를 하지 않아야 한다: 스냅숏 시각이 그대로인지 확인
    snap_before = dict(core_env.state["snapshots"])
    out = core_env.import_zip(conv_zip)
    assert out.counts["missing"] == 0
    assert core_env.state["snapshots"] == snap_before


def _conv(cid="claude-ai:aaaaaaaa-1111-0000-0000-000000000000", title="첫 제목", text="본문"):
    t = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
    return Conversation(cid, "claude-ai", title, "", t, t, "", [Message("m1", "user", t, text)])


def test_title_change_renames(archive_root):
    a = Archive(archive_root, KST, today=lambda: TODAY)
    r1 = a.write(_conv())
    assert r1.status == "new" and r1.path.name == "2026-10-01_첫-제목_aaaaaaaa.md"
    r2 = a.write(_conv(title="바뀐 제목"))
    assert r2.status == "changed" and r2.path.name == "2026-10-01_바뀐-제목_aaaaaaaa.md"
    assert not r1.path.exists() and len(list(archive_root.rglob("*.md"))) == 1
    assert a.write(_conv(title="바뀐 제목")).status == "same"


def test_id_prefix_collision(archive_root):
    a = Archive(archive_root, KST, today=lambda: TODAY)
    r1 = a.write(_conv("claude-ai:aaaaaaaa-1111-0000-0000-000000000000", "같은 제목"))
    r2 = a.write(_conv("claude-ai:aaaaaaaa-2222-0000-0000-000000000000", "같은 제목"))
    assert r1.path != r2.path and r2.path.stem.endswith("_aaaaaaaa-222")
    assert a.write(_conv("claude-ai:aaaaaaaa-2222-0000-0000-000000000000", "같은 제목")).status == "same"
    # 새 Archive(앱 재시작)에서도 같은 파일을 찾는다
    b = Archive(archive_root, KST, today=lambda: TODAY)
    assert b.find("claude-ai:aaaaaaaa-1111-0000-0000-000000000000") == r1.path
    assert b.find("claude-ai:aaaaaaaa-2222-0000-0000-000000000000") == r2.path


def test_atomic_write_leaves_no_temp(tmp_path, monkeypatch):
    p = tmp_path / "a.md"
    atomic_write(p, "첫\n")
    import os
    real = os.replace

    def boom(a, b):
        raise OSError("강제 종료 흉내")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write(p, "둘\n")
    monkeypatch.setattr(os, "replace", real)
    assert p.read_text("utf-8") == "첫\n"          # 원본은 깨지지 않음
    assert p.read_bytes() == "첫\n".encode()


def test_slugify():
    assert slugify('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"
    assert slugify("CON") == "_CON"
    assert slugify("nul.txt") == "_nul.txt"
    assert slugify("  공백  여러   개 ") == "공백-여러-개"
    assert slugify("🚀 배포") == "🚀-배포"
    assert len(slugify("가" * 100)) == 60
    assert slugify("...") == "제목-없음"


def test_archive_missing_raises(tmp_path):
    from app.archive import ArchiveMissing
    a = Archive(tmp_path / "nope", KST)
    with pytest.raises(ArchiveMissing):
        a.write(_conv())
    assert not (tmp_path / "nope").exists()       # 폴더를 새로 만들지 않음


def test_no_archive_zip_not_recorded(core_env, tmp_path):
    import shutil
    shutil.rmtree(core_env.archive_dir)
    z = make_export_zips(tmp_path / "z")[0]
    assert core_env.import_zip(z).result == "no_archive"
    assert core_env.state["zips"] == {}
    assert not core_env.archive_dir.exists()


def test_failed_zip_recorded(core_env, tmp_path):
    import zipfile
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("conversations.json", "[{broken")
    out = core_env.import_zip(bad)
    assert out.result == "failed"
    rec = next(iter(core_env.state["zips"].values()))
    assert rec["result"] == "failed" and rec["reason"]
    assert list(core_env.archive_dir.rglob("*.md")) == []


def test_ignored_zip_recorded(core_env, tmp_path):
    import zipfile
    z = tmp_path / "photos.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("a.txt", "x")
    assert core_env.import_zip(z).result == "ignored"
    assert next(iter(core_env.state["zips"].values()))["result"] == "ignored"


def test_code_collect_copy_and_missing(core_env):
    from conftest import FIXTURES
    proj = core_env.projects_dir / "D--demo"
    (proj / "sess-1" / "subagents").mkdir(parents=True)
    src = FIXTURES / "code_session.jsonl"
    (proj / "sess-1.jsonl").write_bytes(src.read_bytes())
    (proj / "sess-1" / "subagents" / "agent-a.jsonl").write_bytes(src.read_bytes())
    r = core_env.collect_code()
    assert r.new == 1 and r.copied == 2
    raw = core_env.store.raw_dir
    assert (raw / "D--demo" / "sess-1.jsonl").exists()
    assert (raw / "D--demo" / "sess-1" / "subagents" / "agent-a.jsonl").exists()
    md = list((core_env.archive_dir / "claude-code").rglob("*.md"))
    assert len(md) == 1
    # 다시 수집: 아무것도 안 바뀜
    r2 = core_env.collect_code()
    assert r2.copied == 0 and r2.new == 0 and r2.changed == 0
    # 원본이 30일 정리로 사라짐 -> md 유지 + missing, 복사본 유지
    (proj / "sess-1.jsonl").unlink()
    r3 = core_env.collect_code()
    assert r3.missing == 1
    meta = read_front_file(md[0])
    assert meta["source_status"] == "missing" and meta["missing_since"]
    assert (raw / "D--demo" / "sess-1.jsonl").exists()


def test_code_session_grows_rewrites(core_env):
    from conftest import FIXTURES
    proj = core_env.projects_dir / "D--demo"
    proj.mkdir(parents=True)
    lines = (FIXTURES / "code_session.jsonl").read_text("utf-8").split("\n")[:-1]
    f = proj / "s.jsonl"
    f.write_text("\n".join(lines[:3]), encoding="utf-8")
    core_env.collect_code()
    f.write_text("\n".join(lines), encoding="utf-8")
    r = core_env.collect_code()
    assert r.changed == 1


def test_rebuild_all_is_stable(core_env, tmp_path):
    for z in make_export_zips(tmp_path / "z"):
        core_env.import_zip(z)
    before = _mtimes(core_env.archive_dir)
    out = core_env.rebuild_all()
    assert out["zips"] == 3
    assert _mtimes(core_env.archive_dir) == before


def test_reminder(core_env):
    now = datetime(2026, 11, 7, 12, 0, tzinfo=KST)
    core_env.state["first_run"] = now.isoformat()
    core_env.state["last_zip_import"] = ""
    assert core_env.reminder_due(now) is None                     # 첫 실행 당일
    assert core_env.reminder_due(now + timedelta(days=1)) is not None
    core_env.state["last_zip_import"] = (now - timedelta(days=8)).isoformat()
    msg = core_env.reminder_due(now)
    assert msg == "claude.ai 내보내기를 받을 때가 됐어요 (마지막: 10월 30일)"
    core_env.mark_reminded(now)
    assert core_env.reminder_due(now + timedelta(hours=2)) is None   # 하루 1번
    assert core_env.reminder_due(now + timedelta(days=1)) is not None
    core_env.state["last_zip_import"] = (now - timedelta(days=2)).isoformat()
    assert core_env.reminder_due(now + timedelta(days=1)) is None


def test_broken_config_and_state(tmp_path):
    from app.store import Store
    roam = tmp_path / "r"
    roam.mkdir()
    (roam / "config.json").write_text("{broken", encoding="utf-8")
    (roam / "state.json").write_text("[1,", encoding="utf-8")
    s = Store(roam, tmp_path / "l")
    c = s.load_config()
    assert c.warning and c.data["hotkey"] == "ctrl+alt+h"
    assert (roam / "config.json.bak").exists()
    assert (roam / "config.json").read_text("utf-8") == "{broken"      # config는 덮어쓰지 않음
    st = s.load_state()
    assert st.warning and st.data["zips"] == {}
    assert (roam / "state.json.bak").exists()


def test_message_count_and_copy_safety(archive_root):
    a = Archive(archive_root, KST)
    c = _conv(text="<!-- bs:msg 2 user x -->\n본문")
    r = a.write(c)
    text = r.path.read_text("utf-8")
    assert text.count("<!-- bs:msg ") == 1 and "<!-- bs\\:msg 2" in text


def test_default_archive_without_asking(tmp_path):
    from app.core import Core
    from app.store import Store
    core = Core(Store(tmp_path / "roam", tmp_path / "local"), tz=KST)
    assert core.config["archive_dir"] == ""
    assert core.archive_dir == tmp_path / "local" / "archive"
    assert core.archive_ok()


def test_old_data_folder_moved(tmp_path, monkeypatch):
    from app import store
    (tmp_path / "brain-searcher").mkdir()
    (tmp_path / "brain-searcher" / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("THOUGHT_SEARCHER_APPDATA", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    d = store.roaming_dir()
    assert d == tmp_path / "thought-searcher" and (d / "state.json").exists()
    assert not (tmp_path / "brain-searcher").exists()


def test_render_version_forces_rerender(core_env):
    from conftest import FIXTURES
    proj = core_env.projects_dir / "D--demo"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_bytes((FIXTURES / "code_session.jsonl").read_bytes())
    core_env.collect_code()
    md = next((core_env.archive_dir / "claude-code").rglob("*.md"))
    md.write_text(md.read_text("utf-8").replace("고쳤습니다", "옛 규칙"), encoding="utf-8", newline="\n")
    assert core_env.collect_code().changed == 0          # 원본이 그대로면 다시 만들지 않음
    core_env.state["code_render_version"] = 1            # 규칙이 바뀐 상황
    assert core_env.collect_code().changed == 1
    assert "옛 규칙" not in md.read_text("utf-8")


def test_only_tool_subfolders_scanned(tmp_path):
    """보관 폴더가 드라이브 최상위여도 도구 하위 폴더 밖의 md는 보지 않는다."""
    from app.archive import md_files
    (tmp_path / "VS Sources" / "repo").mkdir(parents=True)
    (tmp_path / "VS Sources" / "repo" / "x.md").write_text("---\nid: claude-ai:x\nsource: claude-ai\nformat_version: 1\n---\n")
    (tmp_path / "claude-ai" / "2026").mkdir(parents=True)
    (tmp_path / "claude-ai" / "2026" / "a.md").write_text("x")
    assert [p.name for p in md_files(tmp_path)] == ["a.md"]


def test_same_content_zip_other_name_known(core_env, tmp_path):
    import shutil
    z = make_export_zips(tmp_path / "z")[0]
    core_env.import_zip(z)
    copy = tmp_path / "z" / "다른이름.zip"
    shutil.copy2(z, copy)
    assert not core_env.known_zip(copy)
    assert core_env.import_zip(copy).result == "skipped"
    assert core_env.known_zip(copy) and core_env.known_zip(z)
