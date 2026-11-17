"""Gemini(gemini.google.com) 자동 수집 파일을 대화로 바꾼다.

userscript/gemini-sync.user.js가 사이트 내부 RPC(batchexecute) 응답을 그대로 담아 저장한다:
  data = {"id": "c_<hex>", "title": 제목, "updated": [초, 나노초], "turns": [턴, ...]}
턴은 이름 없는 중첩 배열이라 칸 위치로 읽는다 (2026-11-17 실제 응답으로 확인, 모델 3.5 Flash-Lite):
  턴[0] = [대화 id, 턴 id]
  턴[2][0][0] = 내가 쓴 글
  턴[3][0] = 답 후보 목록. 후보[0] = 후보 id, 후보[1][0] = 답(마크다운)
  턴[3][3] = 화면에 보이는 후보 id ('다시 실행'으로 후보가 여럿일 때)
  턴[4] = [초, 나노초]
사이트는 최신 턴부터 주므로 시각으로 다시 정렬한다. 위치가 바뀌어 글을 못 찾으면 그 턴은 건너뛴다.
첨부, 생성 이미지, 생각 과정은 담지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..model import Conversation, Message

SRC = "gemini"
TITLE_LEN = 60


def _at(v, *path):
    """중첩 배열에서 path 위치 값. 없거나 형식이 다르면 None."""
    for i in path:
        if not isinstance(v, list) or not -len(v) <= i < len(v):
            return None
        v = v[i]
    return v


def _ts(v) -> datetime | None:
    sec = _at(v, 0)
    if not isinstance(sec, (int, float)) or sec <= 0:
        return None
    nanos = _at(v, 1)
    extra = nanos / 1e9 if isinstance(nanos, (int, float)) else 0.0
    try:
        return datetime.fromtimestamp(float(sec) + extra, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _text(v) -> str:
    return v.strip("\n") if isinstance(v, str) else ""


def _answers(turn) -> list[tuple[str, str, bool]]:
    """(후보 id, 글, 보이는 후보인지). 보이는 후보 id가 없으면 첫 후보."""
    cands = [c for c in (_at(turn, 3, 0) or []) if isinstance(c, list)]
    chosen = _at(turn, 3, 3)
    ids = [c[0] if c and isinstance(c[0], str) else "" for c in cands]
    if chosen not in ids:
        chosen = ids[0] if ids else None
    out = []
    for cid, c in zip(ids, cands):
        text = _text(_at(c, 1, 0))
        if text.strip():
            out.append((cid, text, cid == chosen))
    out.sort(key=lambda a: not a[2])        # 보이는 후보를 먼저
    return out


def convert_capture(data: dict) -> Conversation | None:
    raw_id = str(data.get("id") or "")
    native = raw_id[2:] if raw_id.startswith("c_") else raw_id
    if not native:
        raise ValueError("대화 id가 없음")
    turns = data.get("turns")
    if not isinstance(turns, list):
        raise ValueError("turns가 없음")
    timed = []
    for i, t in enumerate(turns):
        when = _ts(_at(t, 4))
        if when is not None:
            timed.append((when, -i, t))     # 같은 시각이면 사이트 순서의 반대(오래된 것 먼저)
    timed.sort(key=lambda x: (x[0], x[1]))

    messages: list[Message] = []
    for when, _i, t in timed:
        rid = _at(t, 0, 1)
        rid = rid if isinstance(rid, str) and rid else f"turn{len(messages)}"
        prompt = _text(_at(t, 2, 0, 0))
        if prompt.strip():
            messages.append(Message(native_id=rid, role="user", created=when, text=prompt))
        for cid, text, main in _answers(t):
            messages.append(Message(native_id=cid or f"{rid}-a", role="assistant", created=when, text=text,
                                    on_main_branch=main))
    if not messages:
        return None
    created = messages[0].created
    updated = max(_ts(data.get("updated")) or created, messages[-1].created)
    title = " ".join(str(data.get("title") or "").split())
    if not title:
        first = next((m.text for m in messages if m.role == "user"), "")
        title = " ".join(first.split())[:TITLE_LEN].strip() or "(제목 없음)"
    return Conversation(
        conv_id=f"{SRC}:{native}", source=SRC, title=title, project="",
        created=created, updated=updated, url=f"https://gemini.google.com/app/{native}",
        messages=messages,
    )
