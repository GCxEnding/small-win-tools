"""정상 구간 / 의심 구간 나누기.

의심 구간
- text  : 공백 없이 이어진 비ASCII 글자 묶음 중 깨짐 의심 글자가 하나라도 있는 것
- url   : %XX(%uXXXX) 연속
- escape: \\uXXXX 연속
- entity: &#...; 연속
- base64: Base64 형태 토큰 (8자 이상)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .decoders import BASE64_MIN_LEN, BASE64_TOKEN, ENTITY_RUN, ESCAPE_RUN, URL_RUN, suspicious_question_marks
from .score import hangul_tier, is_suspicious

ASCII_SPACE = " \t\r\n\f\v"
_TOKEN = re.compile(r"[^ \t\r\n\f\v]+")


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    kind: str

    def text(self, s: str) -> str:
        return s[self.start:self.end]


def _latinish(ch: str) -> bool:
    """Latin-1/CP1252로 잘못 읽은 결과에 나오는 글자."""
    o = ord(ch)
    return 0x80 <= o <= 0xFF or ch in "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ"


def _text_runs(text: str) -> list[Segment]:
    maybe = suspicious_question_marks(text)
    n = len(text)
    runs: list[Segment] = []
    i = 0
    while i < n:
        ch = text[i]
        if ord(ch) < 0x80 and i not in maybe:
            i += 1
            continue
        j = i
        while j < n and (ord(text[j]) >= 0x80 or j in maybe):
            j += 1
        # CP949 확장 한글의 둘째 바이트는 ASCII 영문자일 수 있다 (Latin-1로 읽은 경우 'Œc' 같은 모양)
        while j < n and text[j].isascii() and text[j].isalpha():
            body = text[i:j]
            if not (all(_latinish(c) for c in body) and len(body) % 2 == 1):
                break
            j += 1
            while j < n and _latinish(text[j]):
                j += 1
        run = text[i:j]
        if any(is_suspicious(c) for c in run if c != "?"):
            runs.append(Segment(i, j, "text"))
        i = j
    return runs


def find_segments(text: str) -> list[Segment]:
    spans: list[Segment] = []
    # URL: 공백 없는 토큰 안에 %XX가 2개 이상이면 토큰 전체 ('HTTP%20500%20%EC..', 끝의 '%253F'처럼 섞인 경우)
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        runs = list(URL_RUN.finditer(tok))
        if sum(r.group(0).count("%") for r in runs) >= 2 or any("%u" in r.group(0) for r in runs):
            spans.append(Segment(m.start(), m.end(), "url"))
    for kind, rx in (("escape", ESCAPE_RUN), ("entity", ENTITY_RUN), ("base64", BASE64_TOKEN)):
        for m in rx.finditer(text):
            if kind == "base64" and len(m.group(0)) < BASE64_MIN_LEN:
                continue
            spans.append(Segment(m.start(), m.end(), kind))
    spans += _text_runs(text)
    # 겹치면 먼저 시작하고 긴 것을 남긴다
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    out: list[Segment] = []
    for s in spans:
        if out and s.start < out[-1].end:
            continue
        out.append(s)
    return out


def trimmed(seg_text: str) -> tuple[int, int] | None:
    """앞뒤의 정상 한글을 뺀 안쪽 범위. 뺄 것이 없으면 None."""
    a, b = 0, len(seg_text)
    while a < b and hangul_tier(seg_text[a]) in (1, 2):
        a += 1
    while b > a and hangul_tier(seg_text[b - 1]) in (1, 2):
        b -= 1
    if (a, b) == (0, len(seg_text)) or a >= b:
        return None
    return a, b
