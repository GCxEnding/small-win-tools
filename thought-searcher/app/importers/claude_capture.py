"""claude.ai, ChatGPT 자동 수집 파일 가져오기 (SPEC-queue.md 3-D).

Tampermonkey 스크립트(userscript/claude-sync.user.js)가 다운로드 폴더의 claude-sync/ 에
대화 하나당 claude-ai_<uuid>.json 하나를 덮어쓴다. 형식:
  {"format": "thought-searcher.capture/1", "site": "claude-ai", "captured_at": ISO,
   "project": 이름 또는 null, "data": 대화 본문 API 응답 그대로}
data는 내보내기 conversations.json의 대화 하나와 거의 같아서 claude_export.convert_conversation을 그대로 쓴다
(2026-11-10 실제 수집 파일로 확인: chat_messages, parent_message_uuid, content 블록이 같음).

ChatGPT는 userscript/chatgpt-sync.user.js가 같은 폴더에 chatgpt_<id>.json (site "chatgpt")으로 저장한다.
data는 대화 본문 API(/backend-api/conversation/<id>) 응답이고, 내보내기 conversations.json의 대화 하나와
같은 mapping 트리라 chatgpt.convert_conversation을 쓴다. 시각이 ISO 문자열로 오면 숫자로 바꿔 넘긴다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..model import Conversation
from ..timeutil import parse_iso
from .base import ImportFailed
from . import chatgpt
from .claude_export import convert_conversation

FORMAT = "thought-searcher.capture/1"
STATUS_FORMAT = "thought-searcher.capture-status/1"
PATTERNS = ("claude-ai_*.json", "chatgpt_*.json")
STATUS_NAMES = {"claude-ai": "_status.json", "chatgpt": "_status_chatgpt.json"}
SITE_LABEL = {"claude-ai": "claude.ai", "chatgpt": "ChatGPT"}
STATUS_NAME = STATUS_NAMES["claude-ai"]
_UUID = re.compile(r"[0-9A-Za-z-]{8,64}")     # 파일 이름에 넣으므로 경로 글자(/ \ .)는 막는다


def capture_files(folder: Path) -> list[Path]:
    out: list[Path] = []
    for pat in PATTERNS:
        out += Path(folder).glob(pat)
    return sorted(out)


def site_of(name: str) -> str:
    return "chatgpt" if name.startswith("chatgpt_") else "claude-ai"


class NotReady(Exception):
    """파일이 아직 다 써지지 않음 (JSON이 깨짐). 다음 확인 때 다시 읽는다."""


def _load(path: Path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise NotReady(f"읽기 실패: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise NotReady(f"JSON이 아직 완성되지 않음: {e}") from e


def _delivered_files(m: dict) -> list[dict]:
    """AI가 만들어 건넨 파일. 내보내기에서는 메시지 files에 오지만 사이트 API에서는 도구 블록 안에만 있다
    (present_files 입력의 filepaths, 도구 결과의 file_deliveries)."""
    names: list[str] = []
    for b in m.get("content") or []:
        if not isinstance(b, dict):
            continue
        paths = []
        if b.get("type") == "tool_use" and b.get("name") == "present_files":
            paths = list((b.get("input") or {}).get("filepaths") or [])
        for fdel in b.get("file_deliveries") or []:
            if isinstance(fdel, dict):
                paths.append(fdel.get("path"))
        for p in paths:
            name = str(p or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
            if name and name not in names:
                names.append(name)
    return [{"file_name": n} for n in names]


def _fill_files(data: dict) -> dict:
    msgs = []
    for m in data.get("chat_messages") or []:
        if isinstance(m, dict) and m.get("sender") == "assistant":
            have = {str(f.get("file_name")) for f in m.get("files") or [] if isinstance(f, dict)}
            extra = [f for f in _delivered_files(m) if f["file_name"] not in have]
            if extra:
                m = {**m, "files": list(m.get("files") or []) + extra}
        msgs.append(m)
    return {**data, "chat_messages": msgs}


def _epoch(v):
    if isinstance(v, str):
        dt = parse_iso(v)
        return dt.timestamp() if dt else None
    return v


def _chatgpt_data(data: dict) -> dict:
    """API 응답의 시각이 ISO 문자열이면 내보내기처럼 숫자(초)로."""
    out = {**data, "create_time": _epoch(data.get("create_time")), "update_time": _epoch(data.get("update_time"))}
    mapping = {}
    for nid, node in (data.get("mapping") or {}).items():
        msg = (node or {}).get("message")
        if isinstance(msg, dict) and isinstance(msg.get("create_time"), str):
            node = {**node, "message": {**msg, "create_time": _epoch(msg["create_time"])}}
        mapping[nid] = node
    out["mapping"] = mapping
    return out


def read_capture(path: Path) -> Conversation | None:
    """수집 파일 하나를 대화로. 메시지가 없으면 None. 형식이 다르면 ImportFailed, 덜 써졌으면 NotReady."""
    d = _load(path)
    site = d.get("site") if isinstance(d, dict) else None
    if not isinstance(d, dict) or d.get("format") != FORMAT or site not in STATUS_NAMES:
        raise ImportFailed(f"수집 파일 형식이 아님: {Path(path).name}")
    data = d.get("data")
    ok = isinstance(data, dict) and (data.get("uuid") if site == "claude-ai" else isinstance(data.get("mapping"), dict))
    if not ok:
        raise ImportFailed(f"대화 본문이 없음: {Path(path).name}")
    try:
        if site == "chatgpt":
            conv = chatgpt.convert_conversation(_chatgpt_data(data))
        else:
            conv = convert_conversation(_fill_files(data))
    except (KeyError, ValueError, TypeError) as e:
        raise ImportFailed(f"{Path(path).name}: {e}") from e
    if conv is not None:
        proj = " ".join(str(d.get("project") or "").split())
        if proj:
            conv.project = proj
    return conv


def read_status(folder: Path, site: str = "claude-ai") -> dict | None:
    """스크립트가 남긴 상태 파일. 없거나 깨졌거나 형식이 다르면 None."""
    try:
        d = _load(Path(folder) / STATUS_NAMES[site])
    except NotReady:
        return None
    if not isinstance(d, dict) or d.get("format") != STATUS_FORMAT:
        return None
    return d


def last_ok(status: dict | None) -> datetime | None:
    return parse_iso((status or {}).get("last_ok"))


# ---- 수집 제외 (claude.ai) ------------------------------------------------------
# 사용자가 Tampermonkey 메뉴에서 뺀 대화, 프로젝트. 스크립트가 상태 파일(_status.json)의 "exclude"에 쓴다:
#   {"conversations": [{"uuid", "title", "project"}], "projects": [{"uuid", "name"}]}
# conversations에는 직접 뺀 대화와, 뺀 프로젝트에 속해 스크립트가 찾은 대화가 같이 들어 있다
# (claude.ai 내보내기 zip에는 대화마다 프로젝트 정보가 없어서 앱은 대화 uuid로만 거른다).
@dataclass
class Exclude:
    conversations: dict[str, str] = field(default_factory=dict)    # uuid -> 제목 (기록용)
    projects: dict[str, str] = field(default_factory=dict)         # uuid -> 이름 (기록용)

    def to_json(self) -> dict:
        return {"conversations": dict(self.conversations), "projects": dict(self.projects)}

    @classmethod
    def from_json(cls, d) -> "Exclude":
        d = d if isinstance(d, dict) else {}
        return cls({str(k): str(v) for k, v in (d.get("conversations") or {}).items()},
                   {str(k): str(v) for k, v in (d.get("projects") or {}).items()})

    def __bool__(self) -> bool:
        return bool(self.conversations or self.projects)


def read_exclude(status: dict | None) -> Exclude | None:
    """상태 파일의 제외 목록. 키가 없으면(예전 스크립트) None, 비어 있으면 빈 Exclude."""
    if not isinstance(status, dict) or not isinstance(status.get("exclude"), dict):
        return None
    raw = status["exclude"]
    out = Exclude()
    for c in raw.get("conversations") or []:
        if isinstance(c, dict) and _UUID.fullmatch(str(c.get("uuid") or "")):
            out.conversations[str(c["uuid"])] = str(c.get("title") or "")
    for p in raw.get("projects") or []:
        if isinstance(p, dict) and _UUID.fullmatch(str(p.get("uuid") or "")):
            out.projects[str(p["uuid"])] = str(p.get("name") or "")
    return out


def capture_uuid(name: str) -> str:
    """'claude-ai_<uuid>.json' -> uuid (아니면 빈 문자열)."""
    if name.startswith("claude-ai_") and name.endswith(".json"):
        u = name[len("claude-ai_"):-len(".json")]
        return u if _UUID.fullmatch(u) else ""
    return ""
