import json

from conftest import FIXTURES, KST

from app.archive import render
from app.importers.claude_code import ClaudeCodeImporter, parse_session, user_text
from app.redact import Redactor

SESSION = FIXTURES / "code_session.jsonl"


def test_matches_expected_exactly():
    conv = parse_session(SESSION)
    got = render(conv, KST, redact=Redactor())
    assert got == (FIXTURES / "code_session.expected.md").read_text(encoding="utf-8")


def test_title_and_project():
    conv = parse_session(SESSION)
    assert conv.title == "nginx 배포 스크립트 수정"     # custom-title 우선
    assert conv.project == "demo-proj"                   # cwd 마지막 폴더
    assert conv.conv_id == "claude-code:code_session"


def test_excludes_noise():
    text = "\n".join(m.text for m in parse_session(SESSION).messages)
    for bad in ("도구 결과는 버린다", "버린다", "사이드체인", "큐 기록", "Compacted", "Caveat", "AAAA"):
        assert bad not in text, bad


def test_no_tool_lines():
    text = "\n".join(m.text for m in parse_session(SESSION).messages)
    for bad in ("🔧", "deploy.sh", "git commit", "WebFetch", "TaskList"):
        assert bad not in text, bad


def test_slash_command_and_compact():
    texts = [m.text for m in parse_session(SESSION).messages]
    assert "/compact 로그 위주로" in texts
    assert any(t.startswith("> [이전 대화 요약]") for t in texts)
    assert user_text("<command-message>x</command-message>\n<command-name>/review</command-name>\n"
                     "<command-args></command-args>") == "/review"


def test_assistant_blocks_merged():
    msgs = parse_session(SESSION).messages
    assert [m.role for m in msgs] == ["user", "assistant", "user", "user", "user", "assistant"]
    assert msgs[1].text == "먼저 파일을 확인하겠습니다.\n\nnginx.conf 의 server_name 을 고쳤습니다."


def test_broken_last_line_and_unknown_type(tmp_path):
    p = tmp_path / "s.jsonl"
    lines = [json.dumps({"type": "user", "uuid": "1", "timestamp": "2026-01-01T00:00:00Z", "cwd": "C:\\a\\b",
                         "message": {"content": "질문"}}),
             json.dumps({"type": "brand-new-type", "x": 1}),
             "{not json",
             json.dumps({"type": "assistant", "uuid": "2", "timestamp": "2026-01-01T00:00:01Z",
                         "message": {"content": [{"type": "text", "text": "답"}]}}),
             '{"type":"assistant","message":{"content":[{"type":"te']
    p.write_text("\n".join(lines), encoding="utf-8")
    conv = parse_session(p)
    assert [m.text for m in conv.messages] == ["질문", "답"]
    assert conv.title == "질문" and conv.project == "b"


def test_title_fallbacks(tmp_path):
    p = tmp_path / "s.jsonl"
    rows = [{"type": "summary", "summary": "요약 제목"},
            {"type": "user", "uuid": "1", "timestamp": "2026-01-01T00:00:00Z", "message": {"content": "질문"}}]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert parse_session(p).title == "요약 제목"
    p.write_text(json.dumps(rows[1]), encoding="utf-8")
    assert parse_session(p).title == "질문"


def test_empty_session_is_none(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"type": "queue-operation"}), encoding="utf-8")
    assert parse_session(p) is None


def test_folder_only_main_sessions(tmp_path):
    proj = tmp_path / "projects" / "D--x"
    (proj / "abc" / "subagents").mkdir(parents=True)
    (proj / "abc.jsonl").write_text(SESSION.read_text(encoding="utf-8"), encoding="utf-8")
    (proj / "abc" / "subagents" / "agent-1.jsonl").write_text(SESSION.read_text(encoding="utf-8"), encoding="utf-8")
    imp = ClaudeCodeImporter()
    assert imp.detect(tmp_path / "projects")
    assert [c.conv_id for c in imp.iter_conversations(tmp_path / "projects")] == ["claude-code:abc"]
