"""ChatGPT 데이터 내보내기 가져오기.

내보내기 zip(이름은 <해시>-<날짜>-<해시>.zip)에는 conversations.json, export_manifest.json,
첨부 원본(file_*.dat) 등이 들어 있다. 파일 이름이 일정하지 않아 내용으로만 판별한다.
conversations.json: 대화 목록. 각 대화의 mapping은 노드 id -> {message, parent}인 트리이고,
current_node에서 parent를 따라 올라간 경로가 화면에 보이는 본 가지다.
사용자/어시스턴트의 글(text, multimodal_text)만 담고, 생각 과정(thoughts, reasoning_recap),
도구 호출(code, execution_output 등), 숨김 메시지는 뺀다.
"""
from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator

from ..model import Conversation, Message
from .base import ImportFailed, SkipFn

SRC = "chatgpt"
TITLE_LEN = 60
TEXT_TYPES = ("text", "multimodal_text")


def _ts(v) -> datetime | None:
    if isinstance(v, (int, float)) and v > 0:
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _conv_files(names: list[str]) -> list[str]:
    """conversations.json 또는 나뉜 conversations-000.json 형식."""
    out = []
    for n in names:
        p = PurePosixPath(n).name
        if p == "conversations.json" or (p.startswith("conversations-") and p.endswith(".json")):
            out.append(n)
    return sorted(out)


class _Bundle:
    def __init__(self, path: Path):
        self.path = path
        self._zip: zipfile.ZipFile | None = None
        if path.is_dir():
            self.names = [p.relative_to(path).as_posix() for p in path.rglob("*.json")]
        else:
            try:
                self._zip = zipfile.ZipFile(path)
            except (zipfile.BadZipFile, OSError) as e:
                raise ImportFailed(f"zip을 열 수 없음: {e}") from e
            self.names = [n for n in self._zip.namelist() if not n.endswith("/")]

    def close(self):
        if self._zip:
            self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def read_json(self, name: str):
        try:
            raw = self._zip.read(name) if self._zip else (self.path / name).read_bytes()
            return json.loads(raw.decode("utf-8-sig"))
        except (KeyError, OSError, zipfile.BadZipFile, UnicodeDecodeError, ValueError) as e:
            raise ImportFailed(f"{name} 읽기 실패: {e}") from e

    def conversations(self) -> list[str]:
        return _conv_files(self.names)


def _is_chatgpt(data) -> bool:
    if not isinstance(data, list) or not data:
        return False
    return all(isinstance(c, dict) and isinstance(c.get("mapping"), dict) for c in data[:5])


def _message_text(msg: dict) -> str:
    content = msg.get("content") or {}
    parts = content.get("parts") or []
    texts = []
    images = 0
    for p in parts:
        if isinstance(p, str):
            if p.strip():
                texts.append(p.strip("\n"))
        elif isinstance(p, dict):
            if p.get("content_type") == "image_asset_pointer":
                images += 1
            elif isinstance(p.get("text"), str) and p["text"].strip():
                texts.append(p["text"].strip("\n"))
    text = "\n\n".join(texts)
    names = []
    for a in (msg.get("metadata") or {}).get("attachments") or []:
        if isinstance(a, dict):
            fn = str(a.get("name") or "").strip()
            if fn and fn not in names:
                names.append(fn)
    if names:
        att = "\n".join(f"📎 첨부: {fn}" for fn in names)
        text = f"{text}\n\n{att}" if text else att
    elif images:
        att = "\n".join("📎 첨부: (이미지)" for _ in range(images))
        text = f"{text}\n\n{att}" if text else att
    return text


def _visible(msg: dict | None) -> tuple[str, str] | None:
    """보여 줄 메시지면 (role, text)."""
    if not isinstance(msg, dict):
        return None
    role = ((msg.get("author") or {}).get("role"))
    if role not in ("user", "assistant"):
        return None
    content = msg.get("content") or {}
    if content.get("content_type") not in TEXT_TYPES:
        return None
    md = msg.get("metadata") or {}
    if md.get("is_visually_hidden_from_conversation") or md.get("is_user_system_message"):
        return None
    if msg.get("recipient") not in (None, "all"):
        return None   # 도구에게 보내는 호출
    text = _message_text(msg)
    if not text.strip():
        return None
    return role, text


def convert_conversation(raw: dict) -> Conversation | None:
    cid = str(raw.get("conversation_id") or raw.get("id") or "")
    if not cid:
        raise ValueError("대화 id가 없음")
    mapping = raw.get("mapping")
    if not isinstance(mapping, dict):
        raise ValueError("mapping이 없음")
    created = _ts(raw.get("create_time"))
    if created is None:
        raise ValueError("create_time이 없음")
    updated = _ts(raw.get("update_time")) or created

    # 본 가지: current_node에서 parent를 따라 루트까지
    main_ids: list[str] = []
    seen: set[str] = set()
    cur = raw.get("current_node")
    while cur and cur in mapping and cur not in seen:
        seen.add(cur)
        main_ids.append(cur)
        cur = (mapping[cur] or {}).get("parent")
    main_ids.reverse()

    order = {nid: i for i, nid in enumerate(mapping)}

    def when(nid: str) -> datetime:
        msg = (mapping.get(nid) or {}).get("message") or {}
        return _ts(msg.get("create_time")) or created

    branch_ids = sorted((n for n in mapping if n not in seen), key=lambda n: (when(n), order[n]))

    messages: list[Message] = []
    for ids, on_main in ((main_ids, True), (branch_ids, False)):
        for nid in ids:
            node = mapping.get(nid) or {}
            v = _visible(node.get("message"))
            if v is None:
                continue
            role, text = v
            mid = str((node.get("message") or {}).get("id") or nid)
            messages.append(Message(native_id=mid, role=role, created=when(nid), text=text, on_main_branch=on_main))
    if not messages:
        return None

    title = " ".join(str(raw.get("title") or "").split())
    if not title:
        first = next((m.text for m in messages if m.role == "user"), "")
        title = " ".join(first.split("📎")[0].split())[:TITLE_LEN].strip() or "(제목 없음)"
    return Conversation(
        conv_id=f"{SRC}:{cid}", source=SRC, title=title, project="",
        created=created, updated=max(updated, created), url=f"https://chatgpt.com/c/{cid}",
        messages=messages,
    )


class ChatGPTImporter:
    name = SRC

    def detect(self, path: Path) -> bool:
        path = Path(path)
        if not (path.is_dir() or zipfile.is_zipfile(path)):
            return False
        try:
            with _Bundle(path) as b:
                for n in b.conversations():
                    try:
                        if _is_chatgpt(b.read_json(n)):
                            return True
                    except ImportFailed:
                        continue
        except ImportFailed:
            return False
        return False

    def is_full_snapshot(self) -> bool:
        return True

    def snapshot_sources(self, path: Path) -> set[str]:
        return {SRC}

    def snapshot_time(self, path: Path) -> datetime | None:
        best: datetime | None = None
        with _Bundle(Path(path)) as b:
            for n in b.conversations():
                data = b.read_json(n)
                for c in data if isinstance(data, list) else []:
                    if isinstance(c, dict):
                        t = _ts(c.get("update_time")) or _ts(c.get("create_time"))
                        if t and (best is None or t > best):
                            best = t
        if best is None and Path(path).is_file():
            best = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        return best

    def iter_conversations(self, path: Path, on_skip: SkipFn | None = None) -> Iterator[Conversation]:
        skip = on_skip or (lambda msg: None)
        with _Bundle(Path(path)) as b:
            for n in b.conversations():
                data = b.read_json(n)
                if not isinstance(data, list):
                    raise ImportFailed(f"{n} 형식이 목록이 아님")
                for raw in data:
                    try:
                        conv = convert_conversation(raw)
                    except (KeyError, TypeError, ValueError, AttributeError) as e:
                        uid = (raw.get("conversation_id") or raw.get("id") or "?") if isinstance(raw, dict) else "?"
                        skip(f"ChatGPT 대화 {uid} 형식 오류: {e}")
                        continue
                    if conv is not None:
                        yield conv
