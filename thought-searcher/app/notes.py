"""노트 폴더: 사용자가 등록한 폴더의 일반 md를 형식 변환 없이 그대로 색인한다.

- 파일은 읽기만 한다(복사, 수정, 삭제 안 함). 보관 폴더에도 쓰지 않는다.
- 파일 하나 = 문서 하나. id는 `note:<절대 경로(소문자, / 구분)>`, source는 `note`.
- 제목: frontmatter `title` > 파일 이름.
- 날짜: frontmatter `date`/`created` > 파일 이름의 YYYY-MM-DD 또는 YYYYMMDD > 파일 수정 시각.
  날짜가 정해진 노트(일지 등)는 그 날짜를 created/updated로 쓴다. 나중에 고쳐도 일지 날짜로 정렬된다.
- 본문은 제목 줄(#~######)마다 구역으로 나눠 메시지처럼 색인한다. 코드 블록 안의 #은 제목이 아니다.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, tzinfo
from pathlib import Path

from .mdparse import ParsedDoc, ParsedMessage
from .timeutil import fmt_iso, local_tz, parse_iso

SOURCE = "note"
SKIP_DIRS = {"node_modules", "__pycache__"}
MAX_BYTES = 2_000_000          # 이보다 큰 md는 노트로 보지 않는다
_HEAD_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)")


def note_id(path: Path) -> str:
    return SOURCE + ":" + os.path.normcase(os.path.abspath(path)).replace("\\", "/").lower()


def _inside(p: Path, parent: Path) -> bool:
    try:
        p.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def iter_note_files(roots: list[Path], exclude: list[Path] | None = None) -> list[tuple[Path, Path]]:
    """(md 경로, 그 노트 폴더) 목록. 점으로 시작하는 폴더(.obsidian, .git 등)와 exclude 아래는 뺀다."""
    out: list[tuple[Path, Path]] = []
    seen: set[str] = set()
    excl = [Path(e) for e in exclude or [] if e]
    for root in roots:
        root = Path(root)
        if not root.is_dir() or any(_inside(root, e) for e in excl):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
                                 and not any(_inside(Path(dirpath) / d, e) for e in excl))
            for fn in sorted(filenames):
                if not fn.lower().endswith(".md") or fn.startswith("."):
                    continue
                p = Path(dirpath) / fn
                key = note_id(p)
                if key in seen:
                    continue
                seen.add(key)
                out.append((p, root))
    return out


def _front(lines: list[str]) -> tuple[dict[str, str], int]:
    """frontmatter와 본문 시작 줄 번호(0부터)."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    for i in range(1, min(len(lines), 200)):
        if lines[i].strip() == "---":
            meta = {}
            for line in lines[1:i]:
                k, sep, v = line.partition(":")
                if sep and k.strip() and not k.startswith((" ", "\t", "-")):
                    v = v.strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]
                    meta[k.strip().lower()] = v
            return meta, i + 1
    return {}, 0


def _date_from(value: str, tz: tzinfo) -> datetime | None:
    if not value:
        return None
    dt = parse_iso(value) if "T" in value else None
    if dt:
        return dt
    m = _DATE_RE.search(value)
    if not m:
        return None
    try:
        d = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=tz)


def parse_note(path: Path, root: Path | None = None, tz: tzinfo | None = None) -> ParsedDoc | None:
    tz = tz or local_tz()
    path = Path(path)
    try:
        st = path.stat()
        if st.st_size > MAX_BYTES:
            return None
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
    except OSError:
        return None
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    meta, start = _front(lines)

    sections: list[tuple[int, str, int]] = []   # (제목 줄 번호 0부터 또는 -1, 제목 글, 본문 시작 줄)
    fence = False
    cur_head, cur_line, cur_body = -1, "", start
    for i in range(start, len(lines)):
        line = lines[i]
        if _FENCE_RE.match(line):
            fence = not fence
            continue
        if fence:
            continue
        m = _HEAD_RE.match(line)
        if m:
            sections.append((cur_head, cur_line, cur_body))
            cur_head, cur_line, cur_body = i, line, i + 1
    sections.append((cur_head, cur_line, cur_body))
    ends = [s[0] for s in sections[1:]] + [len(lines)]

    title = meta.get("title") or path.stem   # Obsidian처럼 파일 이름이 제목 (첫 # 제목은 '주간업무보고'처럼 겹치기 쉬움)
    mtime = datetime.fromtimestamp(st.st_mtime, tz=tz)
    when = (_date_from(meta.get("date", ""), tz) or _date_from(meta.get("created", ""), tz)
            or _date_from(path.stem, tz))
    created = when or mtime
    updated = when or mtime
    project = ""
    if root is not None:
        try:
            rel_parent = path.parent.resolve().relative_to(Path(root).resolve())
            project = Path(root).name + ("" if str(rel_parent) == "." else "/" + rel_parent.as_posix())
        except (ValueError, OSError):
            project = Path(root).name

    doc = ParsedDoc({
        "id": note_id(path), "source": SOURCE, "title": " ".join(title.split()), "project": project,
        "created": fmt_iso(created, tz), "updated": fmt_iso(updated, tz), "url": "",
        "source_status": "present", "format_version": "1",
    })
    n = 0
    for (head_i, head, body_i), end in zip(sections, ends):
        body = lines[body_i:end]
        lead = 0
        while lead < len(body) and not body[lead].strip():
            lead += 1
        body = body[lead:]
        while body and not body[-1].strip():
            body.pop()
        if not body:
            continue
        n += 1
        line_no = (head_i + 1) if head_i >= 0 else (body_i + lead + 1)
        doc.messages.append(ParsedMessage(
            ordinal=n, role="user", created=doc.meta["created"], is_branch=False,
            line_no=line_no, heading=head, text="\n".join(body), body_line=body_i + lead + 1,
        ))
    return doc
