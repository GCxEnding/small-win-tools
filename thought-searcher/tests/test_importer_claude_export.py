import json
import zipfile

from conftest import EXPORT_DIR, FIXTURES, KST, TODAY, make_export_zips, zip_folder

from app.archive import Archive
from app.importers import detect
from app.importers.claude_export import ClaudeExportImporter
from app.redact import Redactor

EXPECTED = FIXTURES / "claude_export_small.expected"


def _tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*.md"))}


def _import_all(zips, archive):
    imp = ClaudeExportImporter()
    skipped = []
    for z in zips:
        if imp.detect(z):
            for c in imp.iter_conversations(z, skipped.append):
                archive.write(c)
    return skipped


def test_matches_expected_exactly(tmp_path):
    zips = make_export_zips(tmp_path / "zips")
    arch = tmp_path / "archive"
    arch.mkdir()
    skipped = _import_all(zips, Archive(arch, KST, Redactor(), today=lambda: TODAY))
    got, exp = _tree(arch), _tree(EXPECTED)
    assert sorted(got) == sorted(exp)
    for k in exp:
        assert got[k] == exp[k], k
    assert len(skipped) == 1 and "c8000000" in skipped[0]   # 형식 오류 대화만 건너뜀


def test_files_are_utf8_lf_no_bom():
    for p in EXPECTED.rglob("*.md"):
        b = p.read_bytes()
        assert not b.startswith(b"\xef\xbb\xbf") and b"\r\n" not in b


def test_branch_main_path_and_appendix():
    imp = ClaudeExportImporter()
    convs = {c.conv_id: c for c in imp.iter_conversations(EXPORT_DIR / "conversations-000")}
    c = convs["claude-ai:c1000000-0000-4000-8000-000000000001"]
    assert [m.native_id for m in c.messages if m.on_main_branch] == ["c1-m1", "c1-m2", "c1-m5", "c1-m6"]
    assert [m.native_id for m in c.messages if not m.on_main_branch] == ["c1-m3", "c1-m4"]


def test_no_parent_info_is_chronological():
    from app.importers.claude_export import convert_conversation
    raw = {"uuid": "u", "name": "t", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
           "chat_messages": [
               {"uuid": "b", "sender": "assistant", "created_at": "2026-01-01T00:01:00Z", "text": "둘째"},
               {"uuid": "a", "sender": "human", "created_at": "2026-01-01T00:00:00Z", "text": "첫째"}]}
    c = convert_conversation(raw)
    assert [m.text for m in c.messages] == ["첫째", "둘째"] and all(m.on_main_branch for m in c.messages)


def test_zero_message_and_blank_conversations_skipped():
    ids = {c.conv_id for c in ClaudeExportImporter().iter_conversations(EXPORT_DIR / "conversations-000")}
    assert not any(i.startswith("claude-ai:c6") or i.startswith("claude-ai:c7") for i in ids)
    assert len(ids) == 5


def test_untitled_uses_first_user_text():
    convs = {c.conv_id: c for c in ClaudeExportImporter().iter_conversations(EXPORT_DIR / "conversations-000")}
    t = convs["claude-ai:c2000000-0000-4000-8000-000000000002"].title
    assert t.startswith("톰캣 느린 요청 로그") and len(t) <= 60 and "📎" not in t


def test_detect_split_and_combined(tmp_path):
    imp = ClaudeExportImporter()
    zips = {z.stem: z for z in make_export_zips(tmp_path / "z")}
    assert imp.detect(zips["conversations-000"])
    assert imp.detect(zips["projects-000"])
    assert imp.detect(zips["memories-000"])
    assert not imp.detect(zips["light_metadata-000"])
    # 한 zip에 모두 든 형식
    combo = tmp_path / "combo.zip"
    with zipfile.ZipFile(combo, "w") as z:
        z.writestr("conversations.json", (EXPORT_DIR / "conversations-000" / "conversations.json").read_text("utf-8"))
        z.writestr("projects.json", json.dumps([json.loads(next((EXPORT_DIR / "projects-000" / "projects").glob("*.json"))
                                                           .read_text("utf-8"))]))
        z.writestr("users.json", "[]")
    assert imp.detect(combo)
    ids = {c.conv_id for c in imp.iter_conversations(combo)}
    assert "claude-ai-project:p1000000-0000-4000-8000-000000000001" in ids and len(ids) == 6


def test_detect_rejects_other_zips(tmp_path):
    imp = ClaudeExportImporter()
    chatgpt = tmp_path / "chatgpt.zip"
    with zipfile.ZipFile(chatgpt, "w") as z:
        z.writestr("conversations.json", json.dumps([{"title": "x", "mapping": {}, "create_time": 1}]))
    other = tmp_path / "photos.zip"
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("a.txt", "hello")
    notzip = tmp_path / "fake.zip"
    notzip.write_bytes(b"not a zip")
    for p in (chatgpt, other, notzip):
        assert not imp.detect(p)
    assert detect(chatgpt).name == "chatgpt"   # ChatGPT 가져오기가 맡음
    assert detect(other) is None and detect(notzip) is None


def test_broken_json_detected_then_fails(tmp_path):
    import pytest

    from app.importers import ImportFailed
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("conversations.json", "[{broken")
    imp = ClaudeExportImporter()
    assert imp.detect(bad)
    with pytest.raises(ImportFailed):
        list(imp.iter_conversations(bad))


def test_snapshot_time_from_content(tmp_path):
    imp = ClaudeExportImporter()
    z = zip_folder(EXPORT_DIR / "conversations-000", tmp_path / "c.zip")
    assert imp.snapshot_time(z).isoformat() == "2026-10-15T00:00:00+00:00"
    assert imp.snapshot_sources(z) == {"claude-ai"}
