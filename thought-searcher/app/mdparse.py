"""md -> frontmatter + 메시지 목록 (색인용). 메시지는 '<!-- bs:msg ... -->' 표식으로 나눈다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .archive import APPENDIX, read_front

_MARK_RE = re.compile(r"^<!-- bs:msg (\d+) (user|assistant) (\S+)( branch)? -->$")


@dataclass
class ParsedMessage:
    ordinal: int
    role: str
    created: str
    is_branch: bool
    line_no: int          # 제목 줄(## ...)의 1부터 세는 줄 번호
    heading: str
    text: str             # 제목 줄 다음부터의 본문 (md 원문)
    body_line: int        # text 첫 줄의 줄 번호


@dataclass
class ParsedDoc:
    meta: dict[str, str]
    messages: list[ParsedMessage] = field(default_factory=list)

    @property
    def conv_id(self) -> str:
        return self.meta.get("id", "")

    @property
    def title(self) -> str:
        return self.meta.get("title", "")


def parse_text(text: str) -> ParsedDoc | None:
    text = text.replace("\r\n", "\n")
    meta = read_front(text)
    if not meta or not meta.get("id") or not meta.get("source") or not meta.get("format_version"):
        return None
    lines = text.split("\n")
    marks = [(i, m) for i, line in enumerate(lines) if line.startswith("<!-- bs:msg ")
             for m in [_MARK_RE.match(line)] if m]
    doc = ParsedDoc(meta)
    for k, (i, m) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        is_branch = bool(m.group(4))
        head_i = i + 1
        heading = lines[head_i] if head_i < end else ""
        body = lines[head_i + 1:end]
        # 다음 표식이 부록 첫 메시지면 부록 제목 줄은 본문이 아니다
        if k + 1 < len(marks) and marks[k + 1][1].group(4) and not is_branch:
            j = len(body) - 1
            while j >= 0 and body[j] == "":
                j -= 1
            if j >= 0 and body[j] == APPENDIX:
                body = body[:j]
        start = 0
        while start < len(body) and body[start] == "":
            start += 1
        body = body[start:]
        while body and body[-1] == "":
            body.pop()
        doc.messages.append(ParsedMessage(
            ordinal=int(m.group(1)), role=m.group(2), created=m.group(3), is_branch=is_branch,
            line_no=head_i + 1, heading=heading, text="\n".join(body), body_line=head_i + 2 + start,
        ))
    return doc


def parse_file(path: Path) -> ParsedDoc | None:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return parse_text(text)
