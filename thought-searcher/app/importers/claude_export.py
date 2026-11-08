"""claude.ai 데이터 내보내기 가져오기.

실제 내보내기(2026-11 확인)는 zip 여러 개로 나뉘어 온다.
  conversations-000.zip : conversations.json
  projects-000.zip      : projects/<uuid>.json
  memories-000.zip      : memories/<account uuid>.json
  (그 외 artifact_data, frames, light_metadata, claude_code_cloud 는 읽지 않음)
한 zip에 모두 들어 있는 형식(conversations.json, projects.json, memories.json)도 받는다.
zip 안 항목의 수정 시각은 1980년으로 고정이라, 내보내기 시각은 안에 든 updated_at의 최댓값으로 정한다.
"""
from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator

from ..model import Conversation, Message
from ..timeutil import parse_iso
from .base import ImportFailed, SkipFn

ROOT_PARENT = "00000000-0000-4000-8000-000000000000"
SRC_CHAT = "claude-ai"
SRC_PROJECT = "claude-ai-project"
SRC_MEMORY = "claude-ai-memory"
TITLE_LEN = 60


def first_line_title(text: str, limit: int = TITLE_LEN) -> str:
    return " ".join((text or "").split())[:limit].strip()


class _Bundle:
    """zip(또는 펼친 폴더) 안의 관심 파일 찾기."""

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
            if self._zip:
                raw = self._zip.read(name)
            else:
                raw = (self.path / name).read_bytes()
            return json.loads(raw.decode("utf-8-sig"))
        except (KeyError, OSError, zipfile.BadZipFile, UnicodeDecodeError, ValueError) as e:
            raise ImportFailed(f"{name} 읽기 실패: {e}") from e

    def _find(self, single: str, folder: str) -> list[str]:
        out = []
        for n in self.names:
            p = PurePosixPath(n)
            if p.name == single:
                out.append(n)
            elif p.suffix == ".json" and len(p.parts) >= 2 and p.parts[-2] == folder:
                out.append(n)
        return sorted(out)

    def conversations(self) -> list[str]:
        return [n for n in self.names if PurePosixPath(n).name == "conversations.json"]

    def projects(self) -> list[str]:
        return self._find("projects.json", "projects")

    def memories(self) -> list[str]:
        return self._find("memories.json", "memories")


def _items(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _is_claude_conversations(data) -> bool:
    if not isinstance(data, list):
        return False
    for c in data[:5]:
        if not isinstance(c, dict):
            return False
        if "mapping" in c:          # ChatGPT 내보내기
            return False
        if "chat_messages" in c and "uuid" in c:
            return True
    return not data   # 빈 목록은 claude.ai로 본다


def _is_project(d) -> bool:
    return isinstance(d, dict) and "uuid" in d and ("docs" in d or "prompt_template" in d)


def _is_memory(d) -> bool:
    return isinstance(d, dict) and any(k in d for k in ("conversations_memory", "memory_files", "project_memories"))


class ClaudeExportImporter:
    name = "claude-ai"

    # ---- 판별 ---------------------------------------------------------
    def detect(self, path: Path) -> bool:
        path = Path(path)
        if not (path.is_dir() or zipfile.is_zipfile(path)):
            return False
        try:
            with _Bundle(path) as b:
                for n in b.conversations():
                    try:
                        if _is_claude_conversations(b.read_json(n)):
                            return True
                    except ImportFailed:
                        return True   # 우리 파일 이름인데 깨짐 -> 가져오기에서 failed로 기록
                for n in b.projects()[:3]:
                    try:
                        if any(_is_project(x) for x in _items(b.read_json(n))):
                            return True
                    except ImportFailed:
                        return True
                for n in b.memories()[:3]:
                    try:
                        if any(_is_memory(x) for x in _items(b.read_json(n))):
                            return True
                    except ImportFailed:
                        return True
        except ImportFailed:
            return False
        return False

    def is_full_snapshot(self) -> bool:
        return True

    def snapshot_sources(self, path: Path) -> set[str]:
        with _Bundle(Path(path)) as b:
            out = set()
            if b.conversations():
                out.add(SRC_CHAT)
            if b.projects():
                out.add(SRC_PROJECT)
            return out

    def snapshot_time(self, path: Path) -> datetime | None:
        best: datetime | None = None

        def see(v):
            nonlocal best
            dt = parse_iso(v)
            if dt and (best is None or dt > best):
                best = dt

        with _Bundle(Path(path)) as b:
            for n in b.conversations():
                for c in _items(b.read_json(n)):
                    if isinstance(c, dict):
                        see(c.get("updated_at"))
            for n in b.projects():
                for p in _items(b.read_json(n)):
                    if isinstance(p, dict):
                        see(p.get("updated_at"))
            for n in b.memories():
                for m in _items(b.read_json(n)):
                    for f in (m.get("memory_files") or []) if isinstance(m, dict) else []:
                        if isinstance(f, dict):
                            see(f.get("updated_at"))
        if best is None and Path(path).is_file():
            best = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        return best

    # ---- 읽기 ---------------------------------------------------------
    def iter_conversations(self, path: Path, on_skip: SkipFn | None = None) -> Iterator[Conversation]:
        skip = on_skip or (lambda msg: None)
        with _Bundle(Path(path)) as b:
            project_names: dict[str, str] = {}
            projects_raw = []
            for n in b.projects():
                for p in _items(b.read_json(n)):
                    projects_raw.append(p)
                    if isinstance(p, dict) and p.get("uuid"):
                        project_names[str(p["uuid"])] = str(p.get("name") or "")
            for n in b.conversations():
                data = b.read_json(n)
                if not isinstance(data, list):
                    raise ImportFailed(f"{n} 형식이 목록이 아님")
                for raw in data:
                    try:
                        conv = convert_conversation(raw)
                    except (KeyError, TypeError, ValueError, AttributeError) as e:
                        uid = raw.get("uuid", "?") if isinstance(raw, dict) else "?"
                        skip(f"claude.ai 대화 {uid} 형식 오류: {e}")
                        continue
                    if conv is not None:
                        yield conv
            for p in projects_raw:
                try:
                    conv = convert_project(p)
                except (KeyError, TypeError, ValueError, AttributeError) as e:
                    uid = p.get("uuid", "?") if isinstance(p, dict) else "?"
                    skip(f"claude.ai 프로젝트 {uid} 형식 오류: {e}")
                    continue
                if conv is not None:
                    yield conv
            for n in b.memories():
                for m in _items(b.read_json(n)):
                    try:
                        conv = convert_memory(m, project_names)
                    except (KeyError, TypeError, ValueError, AttributeError) as e:
                        skip(f"claude.ai 메모리 형식 오류: {e}")
                        continue
                    if conv is not None:
                        yield conv


def _need_time(v, what: str) -> datetime:
    dt = parse_iso(v)
    if dt is None:
        raise ValueError(f"{what} 시각이 없음")
    return dt


def _message_text(m: dict, with_files: bool = True) -> str:
    content = m.get("content")
    if isinstance(content, list) and content:
        parts = [str(b.get("text") or "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        text = "\n\n".join(p.strip("\n") for p in parts if p.strip())
    else:
        text = str(m.get("text") or "")   # 예전 형식
    text = text.strip("\n")
    if not with_files:
        return text
    names = []
    for a in list(m.get("attachments") or []) + list(m.get("files") or []):
        if isinstance(a, dict):
            fn = str(a.get("file_name") or "").strip()
            if fn and fn not in names:
                names.append(fn)
    if names:
        att = "\n".join(f"📎 첨부: {fn}" for fn in names)
        text = f"{text}\n\n{att}" if text else att
    return text


def convert_conversation(raw: dict) -> Conversation | None:
    uid = str(raw["uuid"])
    created = _need_time(raw.get("created_at"), "created_at")
    updated = parse_iso(raw.get("updated_at")) or created
    msgs_raw = [m for m in raw.get("chat_messages") or [] if isinstance(m, dict) and m.get("uuid")]
    if not msgs_raw:
        return None

    entries = []   # (uuid, parent, created, index, raw)
    for i, m in enumerate(msgs_raw):
        mc = parse_iso(m.get("created_at")) or created
        entries.append((str(m["uuid"]), m.get("parent_message_uuid"), mc, i, m))
    by_id = {e[0]: e for e in entries}
    has_tree = all("parent_message_uuid" in e[4] for e in entries)

    if has_tree:
        latest = max(entries, key=lambda e: (e[2], e[3]))
        path_ids = []
        seen = set()
        cur = latest
        while cur is not None and cur[0] not in seen:
            seen.add(cur[0])
            path_ids.append(cur[0])
            parent = cur[1]
            cur = by_id.get(parent) if parent and parent != ROOT_PARENT else None
        path_ids.reverse()
        main = [by_id[i] for i in path_ids]
        branch = sorted((e for e in entries if e[0] not in seen), key=lambda e: (e[2], e[3]))
    else:
        main = sorted(entries, key=lambda e: (e[2], e[3]))
        branch = []

    messages: list[Message] = []
    for group, on_main in ((main, True), (branch, False)):
        for uid_m, _p, mc, _i, m in group:
            sender = m.get("sender")
            role = {"human": "user", "assistant": "assistant"}.get(sender)
            if role is None:
                continue
            text = _message_text(m)
            if not text.strip():
                continue
            messages.append(Message(native_id=uid_m, role=role, created=mc, text=text, on_main_branch=on_main))
    if not messages:
        return None

    title = " ".join(str(raw.get("name") or "").split())
    if not title:
        first_user = ""
        for e in list(main) + list(branch):
            if e[4].get("sender") == "human":
                first_user = _message_text(e[4], with_files=False)
                if first_user.strip():
                    break
        title = first_line_title(first_user) or "(제목 없음)"
    return Conversation(
        conv_id=f"{SRC_CHAT}:{uid}", source=SRC_CHAT, title=title, project="",
        created=created, updated=max(updated, created), url=f"https://claude.ai/chat/{uid}",
        messages=messages,
    )


def convert_project(p: dict) -> Conversation | None:
    uid = str(p["uuid"])
    created = _need_time(p.get("created_at"), "created_at")
    updated = parse_iso(p.get("updated_at")) or created
    name = " ".join(str(p.get("name") or "").split()) or "(이름 없음)"
    msgs: list[Message] = []
    desc = str(p.get("description") or "").strip("\n")
    if desc.strip():
        msgs.append(Message(f"{uid}:description", "assistant", created, desc, label="프로젝트 설명"))
    tmpl = str(p.get("prompt_template") or "").strip("\n")
    if tmpl.strip():
        msgs.append(Message(f"{uid}:prompt", "assistant", created, tmpl, label="프로젝트 지침"))
    for d in p.get("docs") or []:
        if not isinstance(d, dict):
            continue
        body = str(d.get("content") or "").strip("\n")
        fn = str(d.get("filename") or "(이름 없는 문서)")
        if not body.strip():
            continue
        dc = parse_iso(d.get("created_at")) or created
        msgs.append(Message(str(d.get("uuid") or fn), "assistant", dc, body, label=f"문서: {fn}"))
    if not msgs:
        return None
    return Conversation(
        conv_id=f"{SRC_PROJECT}:{uid}", source=SRC_PROJECT, title=name, project=name,
        created=created, updated=max(updated, created), url=f"https://claude.ai/project/{uid}",
        messages=msgs,
    )


def convert_memory(m: dict, project_names: dict[str, str]) -> Conversation | None:
    if not isinstance(m, dict):
        raise TypeError("메모리 항목이 객체가 아님")
    times = [t for t in (parse_iso(f.get("updated_at")) for f in m.get("memory_files") or []
                         if isinstance(f, dict)) if t]
    when = max(times) if times else datetime(2000, 1, 1, tzinfo=timezone.utc)
    msgs: list[Message] = []
    cm = str(m.get("conversations_memory") or "").strip("\n")
    if cm.strip():
        msgs.append(Message("conversations_memory", "assistant", when, cm, label="대화 메모리"))
    for pid, body in sorted((m.get("project_memories") or {}).items()):
        body = str(body or "").strip("\n")
        if not body.strip():
            continue
        pname = project_names.get(pid) or pid[:8]
        msgs.append(Message(f"project:{pid}", "assistant", when, body, label=f"프로젝트 메모리: {pname}"))
    for f in sorted((x for x in m.get("memory_files") or [] if isinstance(x, dict)),
                    key=lambda x: str(x.get("path") or "")):
        body = str(f.get("content") or "").strip("\n")
        if not body.strip():
            continue
        fp = str(f.get("path") or "")
        msgs.append(Message(f"file:{fp}", "assistant", parse_iso(f.get("updated_at")) or when, body,
                            label=f"메모리 파일: {fp}"))
    if not msgs:
        return None
    return Conversation(
        conv_id=f"{SRC_MEMORY}:main", source=SRC_MEMORY, title="Claude 메모리", project="",
        created=min(times) if times else when, updated=when, url="", messages=msgs,
    )
