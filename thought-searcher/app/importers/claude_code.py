"""Claude Code 세션(jsonl) 가져오기. 사람 입력과 Claude 답변 텍스트만 md에 담는다(도구 호출, 결과는 버림).

path가 폴더면 '<폴더>/<프로젝트>/<sessionId>.jsonl'(메인 세션)을 모두, 파일이면 그 파일 하나를 읽는다.
서브에이전트 세션(<sessionId>/subagents/*.jsonl)은 md로 만들지 않는다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Iterator

from ..model import Conversation, Message
from ..timeutil import parse_iso
from .base import SkipFn

SOURCE = "claude-code"
TITLE_LEN = 60

# 대화가 아닌 사용자 줄 (명령 출력, 안내문 등)
_NOISE_RE = re.compile(
    r"^\s*<(local-command-stdout|local-command-stderr|local-command-caveat|bash-stdout|bash-stderr|"
    r"task-notification|system-reminder|user-prompt-submit-hook|tool-use-error)\b")
_SYSREM_RE = re.compile(r"<system-reminder>[\s\S]*?</system-reminder>\s*")
_TAG_RE = {k: re.compile(rf"<{k}>([\s\S]*?)</{k}>") for k in ("command-name", "command-args", "command-message",
                                                                 "bash-input")}

def _one_line(s: str, limit: int) -> str:
    return " ".join(str(s).split())[:limit]


def user_text(raw: str) -> str:
    """사람 입력 문자열 -> md 본문. 대화가 아니면 ''."""
    raw = _SYSREM_RE.sub("", raw or "")
    if not raw.strip() or _NOISE_RE.match(raw):
        return ""
    name = _TAG_RE["command-name"].search(raw)
    cmsg = _TAG_RE["command-message"].search(raw)
    if raw.lstrip().startswith("<command-") and (name or cmsg):
        cmd = (name.group(1) if name else cmsg.group(1)).strip()
        if not cmd.startswith("/"):
            cmd = "/" + cmd
        args = _TAG_RE["command-args"].search(raw)
        a = args.group(1).strip() if args else ""
        return f"{cmd} {a}".rstrip() if a else cmd
    bash = _TAG_RE["bash-input"].search(raw)
    if bash and raw.lstrip().startswith("<bash-input>"):
        return f"! {bash.group(1).strip()}"
    return raw.strip("\n")


def _quote(text: str) -> str:
    lines = ["> [이전 대화 요약]", ">"]
    lines += [f"> {ln}" if ln else ">" for ln in text.strip("\n").split("\n")]
    return "\n".join(lines)


def _project_name(cwd: str, folder: str) -> str:
    if cwd:
        n = PureWindowsPath(cwd).name if ("\\" in cwd or ":" in cwd) else Path(cwd).name
        if n:
            return n
    return folder


def main_sessions(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("*/*.jsonl") if p.is_file())


def parse_session(path: Path, on_skip: SkipFn | None = None) -> Conversation | None:
    session_id = path.stem
    custom_title = summary = ai_title = ""
    cwd = ""
    messages: list[Message] = []
    cur: dict | None = None      # 이어 붙이는 중인 assistant 메시지
    times: list[datetime] = []

    def flush():
        nonlocal cur
        if cur and cur["parts"]:
            text = "\n\n".join(cur["parts"])
            messages.append(Message(cur["id"], "assistant", cur["created"], text))
        cur = None

    try:
        raw_lines = path.read_bytes().split(b"\n")
    except OSError:
        return None
    for raw in raw_lines:
        if not raw.strip():
            continue
        try:
            o = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue   # 쓰는 중인 마지막 줄 등: 그 줄만 건너뜀
        if not isinstance(o, dict):
            continue
        t = o.get("type")
        if t == "custom-title":
            custom_title = str(o.get("customTitle") or "") or custom_title
            continue
        if t == "summary":
            summary = str(o.get("summary") or "") or summary
            continue
        if t == "ai-title":
            ai_title = str(o.get("aiTitle") or "") or ai_title
            continue
        if t not in ("user", "assistant"):
            continue   # 모르는 type, 시스템 줄, 큐 기록 등
        if o.get("isSidechain") or o.get("isMeta"):
            continue
        if not cwd and o.get("cwd"):
            cwd = str(o["cwd"])
        ts = parse_iso(o.get("timestamp"))
        if ts is None:
            continue
        msg = o.get("message") if isinstance(o.get("message"), dict) else {}
        content = msg.get("content")
        if t == "assistant":
            if o.get("isApiErrorMessage"):
                continue
            blocks = content if isinstance(content, list) else ([{"type": "text", "text": content}]
                                                                 if isinstance(content, str) else [])
            parts = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                # 텍스트만 남긴다. 도구 호출(tool_use), thinking은 잡음이라 버린다
                if b.get("type") == "text" and str(b.get("text") or "").strip():
                    parts.append(str(b["text"]).strip("\n"))
            if not parts:
                continue
            if cur is None:
                cur = {"id": str(o.get("uuid") or ""), "created": ts, "parts": []}
            cur["parts"].extend(parts)
            times.append(ts)
            continue
        # user
        if isinstance(content, str):
            texts = [content]
        elif isinstance(content, list):
            texts = [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        else:
            texts = []
        if o.get("isCompactSummary"):
            body = "\n\n".join(x for x in texts if x.strip())
            if not body.strip():
                continue
            flush()
            messages.append(Message(str(o.get("uuid") or ""), "user", ts, _quote(body)))
            times.append(ts)
            continue
        body = "\n\n".join(u for u in (user_text(x) for x in texts) if u.strip())
        if not body.strip():
            continue   # tool_result 만 있는 줄 등
        flush()
        messages.append(Message(str(o.get("uuid") or ""), "user", ts, body))
        times.append(ts)
    flush()
    if not messages:
        return None
    title = custom_title or summary or ai_title
    if not title:
        first = next((m.text for m in messages if m.role == "user" and not m.text.startswith("> [")), "")
        title = _one_line(first, TITLE_LEN).strip()
    title = " ".join(title.split()) or "(제목 없음)"
    return Conversation(
        conv_id=f"{SOURCE}:{session_id}", source=SOURCE, title=title,
        project=_project_name(cwd, path.parent.name), created=min(times), updated=max(times), url="",
        messages=messages,
    )


class ClaudeCodeImporter:
    name = SOURCE

    def detect(self, path: Path) -> bool:
        path = Path(path)
        if path.is_file():
            return path.suffix == ".jsonl"
        return path.is_dir() and any(path.glob("*/*.jsonl"))

    def iter_conversations(self, path: Path, on_skip: SkipFn | None = None) -> Iterator[Conversation]:
        path = Path(path)
        files = [path] if path.is_file() else main_sessions(path)
        for f in files:
            conv = parse_session(f, on_skip)
            if conv is not None:
                yield conv

    def snapshot_time(self, path: Path) -> datetime | None:
        return None

    def is_full_snapshot(self) -> bool:
        return False

    def snapshot_sources(self, path: Path) -> set[str]:
        return set()
