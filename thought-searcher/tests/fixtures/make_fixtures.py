"""합성 fixture 생성기. 실제 대화는 쓰지 않는다 (모두 지어낸 내용).

  python tests/fixtures/make_fixtures.py
실제 claude.ai 내보내기 구조(2026-11)를 흉내 낸다: 출처별로 zip이 나뉘고, 메시지에 parent_message_uuid가 있다.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPORT = HERE / "claude_export_small"
ROOT = "00000000-0000-4000-8000-000000000000"
ACCOUNT = "aaaaaaaa-0000-4000-8000-000000000001"


def blk_text(t):
    return {"start_timestamp": None, "stop_timestamp": None, "flags": None, "type": "text", "text": t,
            "citations": []}


def blk_thinking(t):
    return {"type": "thinking", "thinking": t, "summaries": [], "cut_off": False}


def blk_tool_use(name, inp):
    return {"type": "tool_use", "id": "toolu_x", "name": name, "input": inp}


def blk_tool_result(t):
    return {"type": "tool_result", "tool_use_id": "toolu_x", "name": "", "content": [{"type": "text", "text": t}],
            "is_error": False}


def msg(uid, parent, sender, ts, blocks, files=(), attachments=()):
    texts = [b["text"] for b in blocks if b["type"] == "text"]
    return {"uuid": uid, "text": "\n\n".join(texts), "content": blocks, "sender": sender, "created_at": ts,
            "updated_at": ts, "attachments": list(attachments), "files": list(files),
            "parent_message_uuid": parent}


def conv(uid, name, created, updated, messages):
    return {"uuid": uid, "name": name, "summary": "", "created_at": created, "updated_at": updated,
            "account": {"uuid": ACCOUNT}, "chat_messages": messages}


def conversations():
    # 1. 가지 있는 대화: 두 번째 사람 입력을 고쳐 다시 보냄 -> 이전 가지는 부록으로
    c1 = "c1000000-0000-4000-8000-000000000001"
    branchy = conv(c1, "nginx 설정 배포 정리", "2026-10-01T01:00:00.000000Z", "2026-10-01T01:20:00.000000Z", [
        msg("c1-m1", ROOT, "human", "2026-10-01T01:00:00.000000Z",
            [blk_text("nginx설정 파일을 서버에 배포하는 순서를 알려줘")]),
        msg("c1-m2", "c1-m1", "assistant", "2026-10-01T01:00:30.000000Z",
            [blk_thinking("생각 중인 내용은 버린다"), blk_text("배포 순서는 다음과 같습니다.\n\n1. `nginx -t`로 문법 확인\n2. reload")]),
        msg("c1-m3", "c1-m2", "human", "2026-10-01T01:05:00.000000Z",
            [blk_text("롤백은 어떻게 해? 예전 가지 질문")]),
        msg("c1-m4", "c1-m3", "assistant", "2026-10-01T01:05:20.000000Z",
            [blk_text("예전 가지 답변: 백업 파일을 되돌립니다.")]),
        msg("c1-m5", "c1-m2", "human", "2026-10-01T01:10:00.000000Z",
            [blk_text("롤백 스크립트 logpick 으로 로그 확인하는 법도")]),
        msg("c1-m6", "c1-m5", "assistant", "2026-10-01T01:10:30.000000Z",
            [blk_tool_use("web_search", {"query": "logpick"}), blk_tool_result("검색 결과는 버린다"),
             blk_text("logpick 으로 로그 배포 이력을 확인할 수 있습니다.")]),
    ])
    # 2. 제목 없는 대화 (첨부 포함)
    c2 = "c2000000-0000-4000-8000-000000000002"
    untitled = conv(c2, "", "2026-10-05T03:00:00.000000Z", "2026-10-05T03:02:00.000000Z", [
        msg("c2-m1", ROOT, "human", "2026-10-05T03:00:00.000000Z",
            [blk_text("톰캣 느린 요청 로그를 1분 단위로 모으는 방법이 궁금합니다. 대시보드에도 넣고 싶어요")],
            files=[{"file_uuid": "f1", "file_name": "slow-requests.txt"}, {"file_uuid": "f2", "file_name": None}],
            attachments=[{"file_name": "server.xml", "file_size": 10, "file_type": "text/xml",
                          "extracted_content": "추출된 내용은 버린다"}]),
        msg("c2-m2", "c2-m1", "assistant", "2026-10-05T03:01:00.000000Z",
            [blk_text("AccessLogValve 의 %D 값을 쓰면 됩니다.")]),
    ])
    # 3. 비밀 값이 든 대화
    c3 = "c3000000-0000-4000-8000-000000000003"
    secret = conv(c3, "API 키 설정 도움", "2026-10-10T05:00:00.000000Z", "2026-10-10T05:01:00.000000Z", [
        msg("c3-m1", ROOT, "human", "2026-10-10T05:00:00.000000Z", [blk_text(
            "키가 sk-ant-api03-FAKEFAKEFAKEFAKEFAKEFAKE0123456789 이고 AWS 는 AKIAABCDEFGHIJKLMNOP 입니다.\n"
            "깃허브 토큰 ghp_abcdefghijklmnopqrstuvwxyz0123456789 도 같이 넣었어요.\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n"
            "-----END RSA PRIVATE KEY-----")]),
        msg("c3-m2", "c3-m1", "assistant", "2026-10-10T05:00:40.000000Z",
            [blk_text("키는 환경 변수로 옮기세요. 일반 문장 sk-learn 과 task-ant 는 가리지 않습니다.")]),
    ])
    # 4. 본문에 표식 문자열과 부록 제목이 든 대화
    c4 = "c4000000-0000-4000-8000-000000000004"
    tricky = conv(c4, "md 표식 이스케이프 시험", "2026-10-12T07:00:00.000000Z", "2026-10-12T07:00:30.000000Z", [
        msg("c4-m1", ROOT, "human", "2026-10-12T07:00:00.000000Z",
            [blk_text("본문에 <!-- bs:msg 9 user x --> 가 있으면?\n## 부록: 다른 가지\n## 그냥 제목")]),
        msg("c4-m2", "c4-m1", "assistant", "2026-10-12T07:00:30.000000Z",
            [blk_text("Grafana 대시보드 패널로 보여 줄 수 있습니다.")]),
    ])
    # 5. 오래된 대화 (최신 가산 시험용)
    c5 = "c5000000-0000-4000-8000-000000000005"
    old = conv(c5, "Grafana 대시보드 처음 만들기", "2025-03-01T00:00:00.000000Z", "2025-03-01T00:10:00.000000Z", [
        msg("c5-m1", ROOT, "human", "2025-03-01T00:00:00.000000Z",
            [blk_text("Grafana 대시보드를 처음 만듭니다. 패널 추가 방법은?")]),
        msg("c5-m2", "c5-m1", "assistant", "2025-03-01T00:05:00.000000Z",
            [blk_text("Add panel 을 누르고 쿼리를 고르세요. Grafana 변수도 쓸 수 있습니다.")]),
    ])
    # 6. 메시지 0개 (md를 만들지 않음), 7. 내용이 빈 메시지만 (md를 만들지 않음)
    empty = conv("c6000000-0000-4000-8000-000000000006", "빈 대화", "2026-10-15T00:00:00Z", "2026-10-15T00:00:00Z", [])
    blank = conv("c7000000-0000-4000-8000-000000000007", "", "2026-10-15T00:00:00Z", "2026-10-15T00:00:00Z", [
        msg("c7-m1", ROOT, "human", "2026-10-15T00:00:00Z", []),
    ])
    # 8. 형식 오류 (created_at 없음) -> 이 대화만 건너뜀
    broken = {"uuid": "c8000000-0000-4000-8000-000000000008", "name": "깨진 대화", "chat_messages": "oops"}
    return [branchy, untitled, secret, tricky, old, empty, blank, broken]


def project():
    return {"uuid": "p1000000-0000-4000-8000-000000000001", "name": "사내 로그 수집", "description": "로그 수집 프로젝트",
            "is_private": True, "is_starter_project": False,
            "prompt_template": "항상 한국어로 답한다. 로그 배포 절차를 먼저 확인한다.",
            "created_at": "2026-09-01T00:00:00.000000+00:00", "updated_at": "2026-10-20T00:00:00.000000+00:00",
            "creator": {"uuid": ACCOUNT, "full_name": "테스트"},
            "docs": [{"uuid": "d1", "filename": "수집-설계.md", "content": "# 수집 설계\n\nfluentbit 으로 모은다.",
                      "created_at": "2026-09-02T00:00:00.000000+00:00"}]}


def memories():
    return {"conversations_memory": "사용자는 옵시디언으로 업무 일지를 쓴다.",
            "project_memories": {"p1000000-0000-4000-8000-000000000001": "로그 수집 프로젝트는 fluentbit 를 쓴다."},
            "memory_files": [{"path": "/areas/homelab.md", "content": "라즈베리파이 홈랩 메모",
                              "updated_at": "2026-10-25T00:00:00.000000+00:00"}],
            "account_uuid": ACCOUNT}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


# ---- Claude Code 세션 ------------------------------------------------------
SID = "5e550000-0000-4000-8000-00000000c0de"


def code_lines() -> list[str]:
    base = {"isSidechain": False, "userType": "external", "cwd": "D:\\VS Sources\\demo-proj", "sessionId": SID,
            "version": "2.1.300", "gitBranch": "main"}

    def user(uid, ts, content, **kw):
        return {**base, "parentUuid": None, "type": "user", "uuid": uid, "timestamp": ts,
                "message": {"role": "user", "content": content}, **kw}

    def asst(uid, ts, blocks, **kw):
        return {**base, "parentUuid": None, "type": "assistant", "uuid": uid, "timestamp": ts,
                "message": {"role": "assistant", "content": blocks}, **kw}

    long_cmd = "git commit -m \"" + "가" * 150 + "\" && git push origin main && echo " + "x" * 100
    rows = [
        {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-11-01T01:00:00.000Z", "sessionId": SID,
         "content": "큐 기록은 버린다"},
        user("u1", "2026-11-01T01:00:00.000Z", "로그 배포 스크립트의 nginx설정 부분을 고쳐 줘"),
        {**base, "type": "attachment", "uuid": "at1", "timestamp": "2026-11-01T01:00:00.100Z",
         "attachment": {"type": "file", "filename": "x"}},
        asst("a1", "2026-11-01T01:00:05.000Z", [{"type": "thinking", "thinking": "버린다", "signature": "s"}]),
        asst("a2", "2026-11-01T01:00:06.000Z", [{"type": "text", "text": "먼저 파일을 확인하겠습니다."}]),
        asst("a3", "2026-11-01T01:00:07.000Z", [{"type": "tool_use", "id": "t1", "name": "Read",
                                                  "input": {"file_path": "D:\\VS Sources\\demo-proj\\deploy.sh"}}]),
        user("u2", "2026-11-01T01:00:08.000Z", [{"type": "tool_result", "tool_use_id": "t1",
                                                  "content": "도구 결과는 버린다"}], toolUseResult={}),
        asst("a4", "2026-11-01T01:00:09.000Z", [{"type": "tool_use", "id": "t2", "name": "Bash",
                                                  "input": {"command": long_cmd, "description": "커밋"}}]),
        user("u3", "2026-11-01T01:00:10.000Z", [{"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]),
        asst("a5", "2026-11-01T01:00:11.000Z", [
            {"type": "tool_use", "id": "t3", "name": "Grep", "input": {"pattern": "server_name", "path": "conf"}},
            {"type": "tool_use", "id": "t4", "name": "Edit",
             "input": {"file_path": "D:\\VS Sources\\demo-proj\\nginx.conf", "old_string": "a", "new_string": "b"}},
            {"type": "tool_use", "id": "t5", "name": "WebFetch",
             "input": {"url": "https://nginx.org/en/docs/", "prompt": "요약"}},
            {"type": "tool_use", "id": "t6", "name": "TaskList", "input": {}},
        ]),
        asst("a6", "2026-11-01T01:00:20.000Z", [{"type": "text", "text": "nginx.conf 의 server_name 을 고쳤습니다."}]),
        user("u4", "2026-11-01T01:01:00.000Z", "<local-command-caveat>Caveat: 버린다</local-command-caveat>",
             isMeta=True),
        user("u5", "2026-11-01T01:01:01.000Z",
             "<command-name>/compact</command-name>\n            <command-message>compact</command-message>\n"
             "            <command-args>로그 위주로</command-args>"),
        user("u6", "2026-11-01T01:01:02.000Z", "<local-command-stdout>Compacted </local-command-stdout>"),
        user("u7", "2026-11-01T01:01:03.000Z",
             "This session is being continued from a previous conversation.\n\n요약: nginx 설정을 고쳤다.",
             isCompactSummary=True, isVisibleInTranscriptOnly=True),
        {**user("s1", "2026-11-01T01:01:04.000Z", "사이드체인 질문은 버린다"), "isSidechain": True},
        {**asst("s2", "2026-11-01T01:01:05.000Z", [{"type": "text", "text": "사이드체인 답도 버린다"}]),
         "isSidechain": True},
        {**base, "type": "system", "subtype": "stop_hook_summary", "uuid": "sy1", "timestamp": "2026-11-01T01:01:06.000Z"},
        {"type": "future-unknown-type", "foo": "bar", "sessionId": SID},
        user("u8", "2026-11-01T01:02:00.000Z", [
            {"type": "text", "text": "<system-reminder>\n버린다\n</system-reminder>\n이제 커밋해 줘. 문서에 <!-- bs:msg 3 user --> 도 있음"},
            {"type": "image", "source": {"type": "base64", "data": "AAAA"}}]),
        asst("a7", "2026-11-01T01:02:10.000Z", [{"type": "text", "text": "커밋했습니다.\n\n## 결과\n- logpick 확인"}]),
        {"type": "ai-title", "aiTitle": "AI가 붙인 제목", "sessionId": SID},
        {"type": "custom-title", "customTitle": "nginx 배포 스크립트 수정", "sessionId": SID},
    ]
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    lines.append('{"parentUuid":"a7","isSidechain":false,"type":"assistant","message":{"content":[{"type":"te')
    return lines


def main():
    convs = conversations()
    write_json(EXPORT / "conversations-000" / "conversations.json", convs)
    write_json(EXPORT / "projects-000" / "projects" / "p1000000-0000-4000-8000-000000000001.json", project())
    write_json(EXPORT / "memories-000" / "memories" / f"{ACCOUNT}.json", memories())
    write_json(EXPORT / "light_metadata-000" / "users.json", [{"uuid": ACCOUNT, "full_name": "테스트"}])
    (HERE / "code_session.jsonl").write_text("\n".join(code_lines()), encoding="utf-8", newline="\n")
    print("fixtures written")


if __name__ == "__main__":
    main()
