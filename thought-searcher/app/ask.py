"""'어디까지 했지?' 요약 (SPEC-queue.md 3-C). Qt 없음.

사용자가 큐에서 일 하나를 고르고 F2를 눌렀을 때만 로컬 `claude -p`를 실행한다.
앱 코드는 네트워크 모듈을 쓰지 않는다. 재료는 표준 입력으로 넘기고, 결과는 summaries.json에 둔다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .mdparse import parse_file
from .queue import STATE_LABEL
from .store import atomic_json

SOURCE_LABEL = {"claude-code": "Claude Code 대화", "claude-ai": "claude.ai 대화", "note": "노트",
                "journal": "업무 일지 항목"}
ROLE_LABEL = {"user": "사용자", "assistant": "AI"}
JOURNAL_DAYS = 3                       # 재료에 넣는 연결된 일지 항목: 최근 3일치
MAX_LINES = 12                         # 답이 길게 와도 이만큼만 저장
# 요약 호출이 Claude Code 세션 기록을 남기지 않고 도구도 쓰지 않게 (2026-11-09 확인, Claude Code 2.1.3xx)
CLI_FLAGS = ["--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config", "--tools", ""]
# 앱이 Claude Code 안에서 실행됐을 때 중첩 실행으로 보이지 않게 지우는 환경 변수
_STRIP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
              "CLAUDE_CODE_HOST_SESSION_ID")

# 답의 세 덩어리와 덩어리마다 남기는 항목 수 (프롬프트와 같은 수)
SECTIONS = ("어디까지 했나", "남은 일", "다음 한 걸음")
SECTION_CAPS = (3, 3, 1)
NO_RECORD = "기록에 없음"

PROMPT = """아래는 사용자가 하던 일 하나의 기록입니다. 기록만 보고 아래 형식 그대로 씁니다.

어디까지 했나
1. (끝낸 것, 정한 것)
2. ...
남은 일
1. (아직 안 된 것, 막힌 것)
다음 한 걸음
1. (바로 할 수 있는 행동 하나)

규칙
- 항목 하나는 한 줄, 30자 안팎의 명사형 개조식입니다. "~했습니다" 같은 문장으로 쓰지 않습니다.
  좋은 예: "1단계 커밋 및 화면 확인 완료", "2단계 구현 및 일지 확인 완료 (커밋 필요)", "앱 재시작 후 F2로 확인"
  나쁜 예: "1단계는 커밋 789dd08(main, 푸시 안 함)으로 반영하고 화면 확인을 마쳤습니다."
- 원인, 이유, 배경, 설명은 쓰지 않습니다. 무엇을 했고 무엇이 남았는지만 씁니다.
- '어디까지 했나'와 '남은 일'은 각각 3개 이하, '다음 한 걸음'은 1개만 씁니다.
- 머리말, 맺음말, 굵은 글씨를 쓰지 않습니다. 괄호는 "(커밋 필요)"처럼 짧은 상태 표시에만 씁니다.
- 파일 이름, 경로, 커밋 번호, 테스트 개수 같은 세부는 쓰지 않습니다.
- 기록에서 알 수 없는 덩어리는 "1. 기록에 없음"이라고 씁니다. 추측하지 않습니다.

=== 기록 ===
"""


class AskError(Exception):
    """요약 실패. 메시지는 항목 아래 한 줄로 보여 준다."""


# ---- 작업 폴더와 수집 제외 ---------------------------------------------------
def project_dir_name(cwd: Path | str) -> str:
    """Claude Code가 세션을 저장하는 프로젝트 폴더 이름 (영숫자 밖의 글자는 '-')."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


# ---- 재료 ---------------------------------------------------------------
@dataclass
class Limits:
    tail_messages: int = 20
    max_chars: int = 12000


def _journal_block(entries, today: date) -> str:
    since = today - timedelta(days=JOURNAL_DAYS - 1)
    parts = []
    for e in sorted(entries or [], key=lambda e: (e.day, e.line)):
        if e.day < since:
            continue
        head = f"[일지 {e.day:%Y-%m-%d} {STATE_LABEL.get(e.state, '')}] {e.text}"
        parts.append("\n".join([head, *[c.rstrip() for c in e.children]]))
    return "\n".join(parts)


def _cut_head(text: str, n: int) -> str:
    """앞(오래된 쪽)을 잘라 n자 이하로."""
    if len(text) <= n:
        return text
    return "…" + text[len(text) - max(0, n - 1):]


def build_material(item, limits: Limits, today: date | None = None) -> str:
    """요약 재료. 넘치면 오래된 쪽(앞)부터 자른다. 머리(제목 등)와 일지는 남긴다."""
    today = today or date.today()
    head = [f"제목: {item.title}", f"출처: {SOURCE_LABEL.get(item.source, item.source)}"]
    if item.project:
        head.append(f"프로젝트: {item.project}")
    head_text = "\n".join(head)
    journal = _journal_block(getattr(item, "journal", None), today)
    if journal:
        journal = _cut_head(journal, limits.max_chars // 3)
    budget = limits.max_chars - len(head_text) - len(journal) - 40

    body = ""
    if item.source in ("claude-code", "claude-ai"):
        doc = parse_file(Path(item.path))
        if doc is None:
            raise AskError("대화 md를 읽지 못했습니다")
        msgs = [m for m in doc.messages if not m.is_branch][-max(1, limits.tail_messages):]
        blocks = [f"[{ROLE_LABEL.get(m.role, m.role)} {m.created[:16].replace('T', ' ')}]\n{m.text.strip()}"
                  for m in msgs]
        # 오래된 메시지부터 버리고, 남은 첫 메시지가 그래도 길면 그 앞부분을 자른다
        while len(blocks) > 1 and sum(len(b) + 2 for b in blocks) > budget:
            blocks.pop(0)
        body = "\n\n".join(blocks)
        body = _cut_head(body, max(0, budget))
        body = "=== 마지막 메시지들 (오래된 것부터) ===\n" + body
    elif item.source == "note":
        try:
            text = Path(item.path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            raise AskError(f"노트를 읽지 못했습니다: {e}") from e
        body = "=== 노트 본문 끝부분 ===\n" + _cut_head(text.strip(), max(0, budget))
    parts = [head_text]
    if journal:
        parts.append("=== 연결된 업무 일지 (최근 3일) ===\n" + journal)
    if body:
        parts.append(body)
    return "\n\n".join(parts)


# ---- 실행 ---------------------------------------------------------------
def build_command(ask_command: list[str], model: str) -> list[str]:
    cmd = [str(c) for c in (ask_command or ["claude"])]
    exe = shutil.which(cmd[0])
    if exe:
        cmd[0] = exe
    return [*cmd, "-p", "--model", model or "haiku", *CLI_FLAGS]


def run_claude(cmd: list[str], prompt: str, cwd: Path, timeout: float) -> str:
    cwd.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, cwd=str(cwd), env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as e:
        raise AskError("claude 명령을 찾지 못했습니다 (설정 ask_command 확인)") from e
    except subprocess.TimeoutExpired as e:
        raise AskError(f"시간 초과 ({timeout:.0f}초)") from e
    except OSError as e:
        raise AskError(f"claude 실행 실패: {e}") from e
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        msg = _last_line(proc.stderr) or _last_line(proc.stdout) or "알 수 없는 오류"
        raise AskError(f"claude 오류 종료 (코드 {proc.returncode}): {msg}")
    if not out:
        raise AskError("claude가 빈 답을 돌려줬습니다" + (f": {_last_line(proc.stderr)}" if proc.stderr else ""))
    return out


def _last_line(text: str | None) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:200] if lines else ""


_BULLET = re.compile(r"^\s*(?:[-*•·]+|\d+\s*[.)]|[①-⑩])\s*")
_DECOR = re.compile(r"\*\*|__|`")


def _heading(line: str) -> tuple[int, str] | None:
    """'## **남은 일:** 요약' 같은 줄이면 (덩어리 번호, 뒤에 붙은 내용)."""
    s = _BULLET.sub("", _DECOR.sub("", line)).lstrip("# ").strip()
    for i, name in enumerate(SECTIONS):
        if s.startswith(name):
            rest = s[len(name):].strip()
            if rest and rest[0] not in ":：":
                return None                # '남은 일 정리' 같은 항목 글
            return i, rest.lstrip(":：").strip()
    return None


def parse_sections(text: str) -> list[list[str]] | None:
    """답을 세 덩어리의 항목 목록으로. 덩어리 머리가 하나도 없으면 None."""
    secs: list[list[str]] = [[] for _ in SECTIONS]
    cur = -1
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        h = _heading(line)
        if h:
            cur, rest = h
            if rest:
                secs[cur].append(rest)
            continue
        if cur < 0:
            continue                       # 머리 앞의 머리말은 버림
        item = _BULLET.sub("", _DECOR.sub("", line)).strip()
        if item:
            secs[cur].append(item)
    if cur < 0:
        return None
    return [[x for x in s if x][:cap] or [NO_RECORD] for s, cap in zip(secs, SECTION_CAPS)]


def clean_answer(text: str) -> str:
    """세 덩어리 형식으로 다시 쓴다: 머리 한 줄, 항목은 덩어리마다 1부터 번호."""
    secs = parse_sections(text)
    if secs is None:                       # 형식을 안 지킨 답: 빈 줄만 정리
        lines = [ln.rstrip() for ln in (text or "").strip().splitlines()]
        out = []
        for ln in lines:
            if not ln and (not out or not out[-1]):
                continue
            out.append(ln)
        return "\n".join(out[:MAX_LINES]).strip()
    out = []
    for name, items in zip(SECTIONS, secs):
        out.append(name)
        out += [f"{n}. {x}" for n, x in enumerate(items, 1)]
    return "\n".join(out)


def headline(text: str) -> str:
    """큐 줄에 보여 줄 한 줄: '다음: (다음 한 걸음)', 형식이 아니면 첫 줄."""
    secs = parse_sections(text)
    if secs and secs[2][0] != NO_RECORD:
        return f"다음: {secs[2][0]}"
    if secs and secs[0][0] != NO_RECORD:
        return secs[0][0]
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def summarize(item, *, ask_command: list[str], model: str, limits: Limits, cwd: Path, timeout: float,
              today: date | None = None) -> str:
    material = build_material(item, limits, today)
    return clean_answer(run_claude(build_command(ask_command, model), PROMPT + material, cwd, timeout))


# ---- 저장소 ---------------------------------------------------------------
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


def _ts(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


class SummaryStore:
    """summaries.json: {id: {"trace_at", "text", "model", "at"}}"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = data if isinstance(data, dict) else {}
        except FileNotFoundError:
            self.data = {}
        except (OSError, ValueError):
            bak = self.path.with_name(self.path.name + ".bak")
            try:
                os.replace(self.path, bak)
            except OSError:
                pass
            self.data = {}

    def get(self, item_id: str) -> dict | None:
        rec = self.data.get(item_id)
        return rec if isinstance(rec, dict) and rec.get("text") else None

    def put(self, item_id: str, trace_ts: float, text: str, model: str, now: float | None = None) -> None:
        self.data[item_id] = {"trace_at": _iso(trace_ts), "text": text, "model": model,
                              "at": _iso(now if now is not None else datetime.now().timestamp())}
        atomic_json(self.path, self.data)

    def is_stale(self, item_id: str, trace_ts: float) -> bool:
        """요약을 만든 뒤 새 흔적이 생겼는지 (1초 넘게 늦은 흔적)."""
        rec = self.get(item_id)
        if not rec:
            return False
        t = _ts(rec.get("trace_at"))
        return t is None or trace_ts > t + 1
