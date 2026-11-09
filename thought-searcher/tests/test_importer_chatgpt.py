import json
import zipfile

from conftest import make_export_zips

from app.archive import read_front_file
from app.importers import detect
from app.importers.chatgpt import ChatGPTImporter, convert_conversation
from app.importers.claude_export import ClaudeExportImporter
from app.search import search

T0 = 1793000000.0   # 2026-10 무렵


def _node(nid, parent, role, text=None, t=0.0, ctype="text", parts=None, **extra):
    msg = None
    if role:
        msg = {"id": nid, "author": {"role": role}, "create_time": T0 + t,
               "content": {"content_type": ctype, "parts": parts if parts is not None else [text]},
               "metadata": extra.pop("metadata", {}), **extra}
    return {"id": nid, "message": msg, "parent": parent}


def _conv(cid="g1000000-0000-4000-8000-000000000001", title="nginx 리버스 프록시 정리", nodes=None, current="n6"):
    nodes = nodes or [
        _node("root", None, None),
        _node("n0", "root", "system", "", 0),
        _node("n1", "n0", "user", "nginx 프록시 설정 알려줘", 1),
        _node("n2", "n1", "assistant", "생각 중", 2, ctype="thoughts", parts=[]),
        _node("n3", "n1", "assistant", "예전 답변(다시 생성 전)", 3),
        _node("n4", "n1", "assistant", "proxy_pass 를 쓰면 됩니다", 4),
        _node("n5", "n4", "user", "", 5, ctype="multimodal_text",
              parts=[{"content_type": "image_asset_pointer", "asset_pointer": "file-service://x"}, "이 화면 봐줘"],
              metadata={"attachments": [{"id": "f1", "name": "화면.png"}]}),
        _node("n7", "n5", "assistant", "도구 호출", 5.5, ctype="code", parts=None, recipient="python"),
        _node("n6", "n5", "assistant", "화면을 보니 upstream 이름이 틀렸어요", 6),
        _node("n8", "n6", "user", "숨김", 7, metadata={"is_visually_hidden_from_conversation": True}),
    ]
    return {"conversation_id": cid, "id": cid, "title": title, "create_time": T0, "update_time": T0 + 10,
            "current_node": current, "mapping": {n["id"]: n for n in nodes}}


def _zip(path, convs):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("conversations.json", json.dumps(convs, ensure_ascii=False))
        z.writestr("export_manifest.json", json.dumps({"version": 1, "export_files": []}))
        z.writestr("file_0001.dat", b"\x89PNG")
    return path


def test_detect_by_content_not_name(tmp_path):
    z = _zip(tmp_path / "9d35abc-2026-11-08-00-07-20-3f25.zip", [_conv()])
    assert ChatGPTImporter().detect(z)
    assert not ClaudeExportImporter().detect(z)
    assert detect(z).name == "chatgpt"
    for cz in make_export_zips(tmp_path / "claude"):
        assert not ChatGPTImporter().detect(cz)


def test_main_branch_and_filters():
    c = convert_conversation(_conv())
    main = [m for m in c.messages if m.on_main_branch]
    branch = [m for m in c.messages if not m.on_main_branch]
    assert [m.native_id for m in main] == ["n1", "n4", "n5", "n6"]
    assert [m.native_id for m in branch] == ["n3"]          # 다시 생성 전 답변은 다른 가지
    assert main[2].role == "user" and main[2].text == "이 화면 봐줘\n\n📎 첨부: 화면.png"
    assert c.conv_id == "chatgpt:g1000000-0000-4000-8000-000000000001"
    assert c.url.startswith("https://chatgpt.com/c/") and c.source == "chatgpt"


def test_untitled_uses_first_user_text_and_empty_skipped():
    c = convert_conversation(_conv(title=""))
    assert c.title == "nginx 프록시 설정 알려줘"
    empty = _conv(nodes=[_node("root", None, None), _node("a", "root", "system", "x", 0)], current="a")
    assert convert_conversation(empty) is None


def test_bad_conversation_is_skipped_not_fatal(tmp_path):
    bad = {"conversation_id": "bad", "mapping": {}, "title": "t"}   # create_time 없음
    z = _zip(tmp_path / "g.zip", [bad, _conv()])
    skipped = []
    convs = list(ChatGPTImporter().iter_conversations(z, skipped.append))
    assert len(convs) == 1 and len(skipped) == 1 and "bad" in skipped[0]


def test_core_import_and_search(core_env, tmp_path):
    other = _conv(cid="g2000000-0000-4000-8000-000000000002", title="두번째", current="b2", nodes=[
        _node("b0", None, None), _node("b1", "b0", "user", "톰캣 로그", 1), _node("b2", "b1", "assistant", "access log", 2)])
    z = _zip(tmp_path / "x.zip", [_conv(), other])
    out = core_env.import_zip(z)
    assert out.result == "ok" and out.importer == "chatgpt" and out.counts["new"] == 2
    files = sorted((core_env.archive_dir / "chatgpt").rglob("*.md"))
    assert len(files) == 2
    assert read_front_file(files[0])["source"] == "chatgpt"
    hits = search("upstream src:gpt", db_path=core_env.index.db_path)
    assert [h.conv_id for h in hits] == ["chatgpt:g1000000-0000-4000-8000-000000000001"]
    assert search("upstream src:ai", db_path=core_env.index.db_path) == []
    # 다음 내보내기에서 사라진 대화는 missing
    newer = _conv()
    newer["update_time"] = T0 + 100
    core_env.import_zip(_zip(tmp_path / "y.zip", [newer]))
    gone = core_env.archive().find("chatgpt:g2000000-0000-4000-8000-000000000002")
    assert read_front_file(gone)["source_status"] == "missing"
