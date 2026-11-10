"""claude.ai 자동 수집 파일 가져오기 (SPEC-queue.md 3-D).

Tampermonkey 스크립트(userscript/claude-sync.user.js)가 다운로드 폴더의 claude-sync/ 에
대화 하나당 claude-ai_<uuid>.json 하나를 덮어쓴다. 형식:
  {"format": "thought-searcher.capture/1", "site": "claude-ai", "captured_at": ISO,
   "project": 이름 또는 null, "data": 대화 본문 API 응답 그대로}
data는 내보내기 conversations.json의 대화 하나와 거의 같아서 claude_export.convert_conversation을 그대로 쓴다
(2026-11-10 실제 수집 파일로 확인: chat_messages, parent_message_uuid, content 블록이 같음).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..model import Conversation
from ..timeutil import parse_iso
from .base import ImportFailed
from .claude_export import convert_conversation

FORMAT = "thought-searcher.capture/1"
STATUS_FORMAT = "thought-searcher.capture-status/1"
PATTERN = "claude-ai_*.json"
STATUS_NAME = "_status.json"


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


def read_capture(path: Path) -> Conversation | None:
    """수집 파일 하나를 대화로. 메시지가 없으면 None. 형식이 다르면 ImportFailed, 덜 써졌으면 NotReady."""
    d = _load(path)
    if not isinstance(d, dict) or d.get("format") != FORMAT or d.get("site") != "claude-ai":
        raise ImportFailed(f"수집 파일 형식이 아님: {Path(path).name}")
    data = d.get("data")
    if not isinstance(data, dict) or not data.get("uuid"):
        raise ImportFailed(f"대화 본문이 없음: {Path(path).name}")
    try:
        conv = convert_conversation(_fill_files(data))
    except (KeyError, ValueError, TypeError) as e:
        raise ImportFailed(f"{Path(path).name}: {e}") from e
    if conv is not None:
        proj = " ".join(str(d.get("project") or "").split())
        if proj:
            conv.project = proj
    return conv


def read_status(folder: Path) -> dict | None:
    """스크립트가 남긴 _status.json. 없거나 깨졌거나 형식이 다르면 None."""
    try:
        d = _load(Path(folder) / STATUS_NAME)
    except NotReady:
        return None
    if not isinstance(d, dict) or d.get("format") != STATUS_FORMAT:
        return None
    return d


def last_ok(status: dict | None) -> datetime | None:
    return parse_iso((status or {}).get("last_ok"))
