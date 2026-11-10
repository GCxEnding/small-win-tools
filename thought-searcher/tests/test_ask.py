"""'어디까지 했지?' 요약 (SPEC-queue.md 3-C, 12번 test_ask.py). 실제 claude 대신 가짜 실행 파일을 쓴다."""
import json
import sys
import textwrap
from datetime import date, datetime

import pytest

from app import ask
from app.ask import AskError, Limits, SummaryStore, build_command, build_material
from app.journal import JournalEntry
from app.queue import QueueItem

TODAY = date(2026, 11, 9)
NOW = datetime(2026, 11, 9, 15, 0).timestamp()


def chat_md(n=6, branch=True, long_first=0):
    """보관 md 형식의 합성 대화. 메시지 i의 본문은 '메시지 i'."""
    out = ["---", "id: claude-code:s1", "source: claude-code", "title: 큐 만들기", "project: demo",
           "format_version: 1", "---", "", "# 큐 만들기", ""]
    for i in range(1, n + 1):
        role = "user" if i % 2 else "assistant"
        body = ("가" * long_first + f" 메시지 {i}") if (i == n and long_first) else f"메시지 {i}"
        out += [f"<!-- bs:msg {i} {role} 2026-11-09T10:{i:02d}:00+09:00 -->", f"## {role} (10:{i:02d})", "",
                body, ""]
    if branch:
        out += ["## 부록: 다른 가지", "", f"<!-- bs:msg {n + 1} user 2026-11-08T10:00:00+09:00 branch -->",
                "## 다른 가지", "", "가지 메시지", ""]
    return "\n".join(out)


def item_for(path, source="claude-code", journal=(), title="큐 만들기", trace=NOW):
    return QueueItem(f"{source}:s1", source, title, "demo", str(path), 1, trace, journal=list(journal))


def entry(day, state="/", text="큐 만들기", children=()):
    return JournalEntry(day, "j.md", 8, state, text, text, [], False, list(children), 0.0)


# ---- 재료 ---------------------------------------------------------------
def test_material_chat_tail_and_branch_excluded(tmp_path):
    p = tmp_path / "c.md"
    p.write_text(chat_md(6), encoding="utf-8")
    m = build_material(item_for(p), Limits(tail_messages=3), TODAY)
    assert "제목: 큐 만들기" in m and "출처: Claude Code 대화" in m and "프로젝트: demo" in m
    assert "메시지 4" in m and "메시지 6" in m and "메시지 3" not in m
    assert "가지 메시지" not in m
    assert m.index("메시지 4") < m.index("메시지 6")           # 오래된 것부터
    assert "[사용자 2026-11-09 10:05]" in m and "[AI 2026-11-09 10:06]" in m


def test_material_cut_drops_oldest_first(tmp_path):
    p = tmp_path / "c.md"
    p.write_text(chat_md(20), encoding="utf-8")
    m = build_material(item_for(p), Limits(tail_messages=20, max_chars=400), TODAY)
    assert len(m) <= 400
    assert "메시지 20" in m and "메시지 1\n" not in m and "제목: 큐 만들기" in m


def test_material_single_long_message_keeps_tail(tmp_path):
    p = tmp_path / "c.md"
    p.write_text(chat_md(2, long_first=5000), encoding="utf-8")
    m = build_material(item_for(p), Limits(max_chars=1000), TODAY)
    assert len(m) <= 1000 and m.rstrip().endswith("메시지 2") and "…" in m


def test_material_journal_recent_3_days_with_children(tmp_path):
    p = tmp_path / "c.md"
    p.write_text(chat_md(2), encoding="utf-8")
    es = [entry(date(2026, 11, 5), text="오래된 기록"), entry(date(2026, 11, 7), "x", "사흘째 기록"),
          entry(date(2026, 11, 9), "/", "오늘 기록", ["\t- 하위 내용", "\t- [ ] #할일 남은 것"])]
    m = build_material(item_for(p, journal=es), Limits(), TODAY)
    assert "오래된 기록" not in m
    assert "[일지 2026-11-07 완료] 사흘째 기록" in m and "[일지 2026-11-09 진행] 오늘 기록" in m
    assert "- 하위 내용" in m and "#할일 남은 것" in m


def test_material_note_tail_and_journal_only(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("머리\n" + "본문 " * 2000 + "\n마지막 줄", encoding="utf-8")
    m = build_material(item_for(p, source="note"), Limits(max_chars=600), TODAY)
    assert len(m) <= 600 and m.endswith("마지막 줄") and "머리" not in m
    j = build_material(item_for("j.md", source="journal", journal=[entry(TODAY)]), Limits(), TODAY)
    assert "출처: 업무 일지 항목" in j and "[일지 2026-11-09 진행] 큐 만들기" in j


def test_material_missing_md_raises(tmp_path):
    with pytest.raises(AskError):
        build_material(item_for(tmp_path / "없음.md"), Limits(), TODAY)


# ---- 명령과 실행 -------------------------------------------------------------
FAKE = textwrap.dedent("""
    import json, os, sys, time
    mode = os.environ.get("FAKE_MODE", "ok")
    data = sys.stdin.buffer.read().decode("utf-8").replace("\\r\\n", "\\n")   # 실제 claude처럼 UTF-8로 읽음 (콘솔 인코딩과 무관)
    with open(os.environ["FAKE_LOG"], "w", encoding="utf-8") as f:
        json.dump({"argv": sys.argv[1:], "stdin": data, "cwd": os.getcwd(),
                   "claudecode": "CLAUDECODE" in os.environ}, f, ensure_ascii=False)
    if mode == "ok":
        sys.stdout.reconfigure(encoding="utf-8")
        print("어디까지 했나: 큐 화면까지 했습니다.\\n\\n\\n남은 일: 요약입니다.\\n다음 한 걸음: F2를 누릅니다.")
    elif mode == "fail":
        sys.stderr.write("경고 줄\\nNot logged in · Please run /login\\n")
        sys.exit(1)
    elif mode == "slow":
        time.sleep(5)
    elif mode == "empty":
        pass
""")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE, encoding="utf-8")
    log = tmp_path / "fake_log.json"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("CLAUDECODE", "1")         # 앱이 Claude Code 안에서 돌 때를 흉내
    return [sys.executable, str(script)], log


def test_build_command():
    cmd = build_command(["claude-없는-명령"], "haiku")
    assert cmd[:4] == ["claude-없는-명령", "-p", "--model", "haiku"]
    assert "--no-session-persistence" in cmd and cmd[-2:] == ["--tools", ""]
    assert build_command(["x"], "")[3] == "haiku"


def test_run_success_stdin_cwd_env(fake, tmp_path):
    cmd, log = fake
    work = tmp_path / "ask"
    out = ask.run_claude(build_command(cmd, "sonnet"), "프롬프트 본문", work, 30)
    assert out.startswith("어디까지 했나")
    got = json.loads(log.read_text(encoding="utf-8"))
    assert got["stdin"] == "프롬프트 본문"
    assert got["argv"][:3] == ["-p", "--model", "sonnet"]
    assert got["argv"][-2:] == ["--tools", ""]
    assert got["cwd"].lower() == str(work).lower() and work.is_dir()
    assert got["claudecode"] is False


@pytest.mark.parametrize("mode,msg", [("fail", "코드 1): Not logged in"), ("empty", "빈 답")])
def test_run_errors(fake, tmp_path, monkeypatch, mode, msg):
    cmd, _ = fake
    monkeypatch.setenv("FAKE_MODE", mode)
    with pytest.raises(AskError, match=msg.replace("(", r"\(").replace(")", r"\)")):
        ask.run_claude(build_command(cmd, "haiku"), "x", tmp_path / "ask", 30)


def test_run_timeout(fake, tmp_path, monkeypatch):
    cmd, _ = fake
    monkeypatch.setenv("FAKE_MODE", "slow")
    with pytest.raises(AskError, match="시간 초과"):
        ask.run_claude(build_command(cmd, "haiku"), "x", tmp_path / "ask", 1)


def test_run_missing_command(tmp_path):
    with pytest.raises(AskError, match="찾지 못했습니다"):
        ask.run_claude([str(tmp_path / "no-claude.exe"), "-p"], "x", tmp_path / "ask", 5)


def test_clean_answer_free_text_fallback():
    assert ask.clean_answer("\n a\n\n\n b \n") == "a\n\n b"
    assert len(ask.clean_answer("\n".join(str(i) for i in range(30))).splitlines()) == ask.MAX_LINES


def test_clean_answer_sections_renumbered():
    raw = ("요약입니다.\n\n## **어디까지 했나:** 큐 화면 구현\n- 일지 연결\n* `ask.py` 추가\n4. 넷째\n\n"
           "남은 일\n1) 남은 일 정리\n\n다음 한 걸음:\n① F2로 확인\n② 둘째는 버림\n")
    assert ask.clean_answer(raw) == ("어디까지 했나\n1. 큐 화면 구현\n2. 일지 연결\n3. ask.py 추가\n"
                                     "남은 일\n1. 남은 일 정리\n다음 한 걸음\n1. F2로 확인")


def test_clean_answer_missing_section_and_headline():
    out = ask.clean_answer("어디까지 했나\n1. 큐 구현\n다음 한 걸음\n1. 커밋")
    assert out.splitlines()[2:4] == ["남은 일", "1. 기록에 없음"]
    assert ask.headline(out) == "다음: 커밋"
    assert ask.headline("어디까지 했나\n1. 큐 구현\n다음 한 걸음\n1. 기록에 없음") == "큐 구현"
    assert ask.headline("옛 형식 첫 줄\n둘째 줄") == "옛 형식 첫 줄"


# ---- 저장소 ---------------------------------------------------------------
def test_store_put_get_stale_reload(tmp_path):
    st = SummaryStore(tmp_path / "s" / "summaries.json")
    assert st.get("a") is None and not st.is_stale("a", NOW)
    st.put("a", NOW, "요약", "haiku", now=NOW + 10)
    rec = json.loads((tmp_path / "s" / "summaries.json").read_text(encoding="utf-8"))["a"]
    assert set(rec) == {"trace_at", "text", "model", "at"} and rec["model"] == "haiku"
    st2 = SummaryStore(tmp_path / "s" / "summaries.json")
    assert st2.get("a")["text"] == "요약"
    assert not st2.is_stale("a", NOW)
    assert st2.is_stale("a", NOW + 60)


def test_store_broken_file_backed_up(tmp_path):
    p = tmp_path / "summaries.json"
    p.write_text("{깨짐", encoding="utf-8")
    st = SummaryStore(p)
    assert st.data == {} and (tmp_path / "summaries.json.bak").exists()


# ---- Core ---------------------------------------------------------------
def test_core_summarize_saves_and_attaches(core_env, fake, tmp_path):
    cmd, log = fake
    core = core_env
    core.config["ask_command"] = cmd
    p = tmp_path / "c.md"
    p.write_text(chat_md(4), encoding="utf-8")
    it = item_for(p, trace=NOW)
    text = core.summarize(it)
    assert text.splitlines() == ["어디까지 했나", "1. 큐 화면까지 했습니다.", "남은 일", "1. 요약입니다.",
                                 "다음 한 걸음", "1. F2를 누릅니다."]
    got = json.loads(log.read_text(encoding="utf-8"))
    assert got["stdin"].startswith(ask.PROMPT) and "메시지 4" in got["stdin"]
    assert got["cwd"].lower() == str(core.ask_dir).lower()
    assert (core.store.local / "summaries.json").exists()
    fresh = item_for(p, trace=NOW)
    core.attach_summary(fresh)
    assert fresh.summary == "다음: F2를 누릅니다." and not fresh.summary_stale
    later = item_for(p, trace=NOW + 3600)
    core.attach_summary(later)
    assert later.summary_stale


def test_ask_project_excluded_from_collection(core_env):
    from conftest import FIXTURES
    core = core_env
    src = (FIXTURES / "code_session.jsonl").read_bytes()
    ask_proj = core.projects_dir / ask.project_dir_name(core.ask_dir)
    other = core.projects_dir / "D--demo"
    for d in (ask_proj, other):
        d.mkdir(parents=True)
        (d / "sess-1.jsonl").write_bytes(src)
    r = core.collect_code()
    assert r.new == 1
    assert not (core.store.raw_dir / ask_proj.name).exists()
    assert (core.store.raw_dir / "D--demo" / "sess-1.jsonl").exists()


def test_project_dir_name():
    assert ask.project_dir_name(r"C:\Users\me\AppData\Local\thought-searcher\ask") == \
        "C--Users-me-AppData-Local-thought-searcher-ask"
    assert ask.project_dir_name(r"D:\4.프로그램") == "D--4-----"
