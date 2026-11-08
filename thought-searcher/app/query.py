"""검색어 파서.

문법: 단어(대화 단위 AND), "구문", -제외어, 필터(src:, proj:, after:, before:), 1글자는 제목에서만.
FTS 질의는 항상 큰따옴표로 감싼 토큰으로 만들어 FTS5 문법 문자가 그대로 들어와도 오류가 나지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .tokenize import core_chars, is_latin_token, normalize, tokens

SOURCE_ALIASES = {
    "ai": "claude-ai", "claude-ai": "claude-ai", "claude.ai": "claude-ai",
    "code": "claude-code", "claude-code": "claude-code", "cc": "claude-code",
    "project": "claude-ai-project", "proj": "claude-ai-project", "p": "claude-ai-project",
    "memory": "claude-ai-memory", "mem": "claude-ai-memory", "m": "claude-ai-memory",
}

_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$")


@dataclass
class Term:
    text: str            # 정규화된 원문 (강조 표시용)
    tokens: list[str]
    prefix: bool         # 마지막 토큰을 접두어로 찾음
    phrase: bool = False

    def fts(self) -> str:
        expr = '"' + " ".join(self.tokens) + '"'
        return expr + " *" if self.prefix else expr


@dataclass
class Query:
    terms: list[Term] = field(default_factory=list)
    excludes: list[Term] = field(default_factory=list)
    title_terms: list[str] = field(default_factory=list)       # 1글자: 제목 부분 일치
    title_excludes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    after: date | None = None
    before: date | None = None

    @property
    def has_text(self) -> bool:
        return bool(self.terms or self.title_terms)

    def fts_expr(self) -> str:
        return " AND ".join(t.fts() for t in self.terms)

    def exclude_expr(self) -> str:
        return " OR ".join(t.fts() for t in self.excludes)

    def filter_labels(self) -> list[str]:
        out = []
        rev = {"claude-ai": "ai", "claude-code": "code", "claude-ai-project": "project",
               "claude-ai-memory": "memory"}
        out += [f"src:{rev.get(s, s)}" for s in self.sources]
        out += [f"proj:{p}" for p in self.projects]
        if self.after:
            out.append(f"after:{self.after.isoformat()}")
        if self.before:
            out.append(f"before:{self.before.isoformat()}")
        out += [f"-{t.text}" for t in self.excludes] + [f"-{t}" for t in self.title_excludes]
        return out


def _parse_date(value: str) -> date | None:
    m = _DATE_RE.match(value)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), m.group(3)
    try:
        if d is not None:
            return date(y, mo, int(d))
        return date(y, mo, 1)
    except ValueError:
        return None


def _split(q: str) -> list[tuple[str, bool, bool]]:
    """(내용, 구문 여부, 제외 여부) 목록."""
    out = []
    i, n = 0, len(q)
    while i < n:
        ch = q[i]
        if ch.isspace():
            i += 1
            continue
        neg = False
        if ch == "-" and i + 1 < n and not q[i + 1].isspace():
            neg = True
            i += 1
            ch = q[i]
        if ch == '"':
            j = q.find('"', i + 1)
            if j < 0:
                j = n
            out.append((q[i + 1:j], True, neg))
            i = j + 1
            continue
        j = i
        while j < n and not q[j].isspace():
            j += 1
        out.append((q[i:j], False, neg))
        i = j
    return out


def _term(text: str, phrase: bool) -> Term | None:
    toks = tokens(text)
    if not toks:
        return None
    prefix = (not phrase) and is_latin_token(toks[-1])
    return Term(text=normalize(text).strip(), tokens=toks, prefix=prefix, phrase=phrase)


def parse(q: str) -> Query:
    query = Query()
    for text, phrase, neg in _split(q or ""):
        if not phrase and not neg and ":" in text:
            key, _, value = text.partition(":")
            key = key.lower()
            if key == "src" and value.lower() in SOURCE_ALIASES:
                src = SOURCE_ALIASES[value.lower()]
                if src not in query.sources:
                    query.sources.append(src)
                continue
            if key == "proj" and value:
                query.projects.append(normalize(value))
                continue
            if key in ("after", "before"):
                d = _parse_date(value)
                if d:
                    setattr(query, key, d)
                    continue
            # 알 수 없는 필터는 일반 검색어
        core = core_chars(text)
        if not core:
            continue  # 특수 문자뿐
        if len(core) == 1 and not phrase:
            (query.title_excludes if neg else query.title_terms).append(core)
            continue
        term = _term(text, phrase)
        if term is None:
            # 예: '가 나'처럼 1글자 조각만 있는 구문 -> 제목 부분 일치로
            (query.title_excludes if neg else query.title_terms).append(core)
            continue
        (query.excludes if neg else query.terms).append(term)
    return query
