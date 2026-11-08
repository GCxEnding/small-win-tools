"""알려진 형식의 비밀 값 가림. md에 쓰기 전에만 적용한다."""
from __future__ import annotations

import re

DEFAULT_PATTERNS: list[tuple[str, str]] = [
    ("pem", r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"),
    ("anthropic", r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("openai", r"(?<![A-Za-z0-9])sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{32,}"),
    ("github", r"(?<![A-Za-z0-9])(?:gh[opusr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    ("aws", r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"),
    ("slack", r"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9\-]{10,}"),
    ("google", r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}"),
    ("jwt", r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"),
]


def mask(kind: str) -> str:
    return f"***가림:{kind}***"


class Redactor:
    def __init__(self, extra_patterns: list[str] | None = None):
        self.patterns: list[tuple[str, re.Pattern]] = [(k, re.compile(p)) for k, p in DEFAULT_PATTERNS]
        self.errors: list[str] = []
        for p in extra_patterns or []:
            try:
                self.patterns.append(("custom", re.compile(str(p))))
            except re.error as e:
                self.errors.append(f"extra_redact_patterns 정규식 오류 {p!r}: {e}")

    def __call__(self, text: str) -> str:
        if not text:
            return text
        for kind, pat in self.patterns:
            text = pat.sub(mask(kind), text)
        return text
