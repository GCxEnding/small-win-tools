"""검색용 분할 (문서와 질의 공용).

- NFKC 정규화 + 소문자화
- 한글/한자/가나 연속 구간: 2글자씩 겹쳐 자른다(bigram). 구간 사이 공백은 무시하고 이어 붙인다.
- 영문/숫자: [a-z0-9_]+ 단어 단위
"""
from __future__ import annotations

import re
import unicodedata

CJK_CHARS = (
    "\u1100-\u11ff\u3040-\u309f\u30a0-\u30ff\u3130-\u318f\u31f0-\u31ff"
    "\u3400-\u4dbf\u4e00-\u9fff\ua960-\ua97f\uac00-\ud7a3\ud7b0-\ud7ff\uf900-\ufaff"
)
_CJK = f"[{CJK_CHARS}]"
# 공백으로만 떨어진 CJK 구간은 하나로 본다
_TOKEN_RE = re.compile(rf"([a-z0-9_]+)|({_CJK}+(?:\s+{_CJK}+)*)")
_SPACE_RE = re.compile(r"\s+")
_CJK_RE = re.compile(_CJK)


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def is_cjk(ch: str) -> bool:
    return bool(_CJK_RE.match(ch))


def tokens(text: str) -> list[str]:
    out: list[str] = []
    add, extend = out.append, out.extend
    for latin, run in _TOKEN_RE.findall(normalize(text)):
        if latin:
            add(latin)
            continue
        if not run.isalpha():          # 공백이 섞인 구간: 공백을 빼고 이어 붙인다
            run = _SPACE_RE.sub("", run)
        n = len(run)
        if n == 2:
            add(run)
        elif n > 2:
            extend([run[i:i + 2] for i in range(n - 1)])
        # 1글자 구간은 색인하지 않는다 (1글자 검색은 제목에서만)
    return out


def token_string(text: str) -> str:
    """FTS5 열에 넣을 문자열."""
    return " ".join(tokens(text))


def is_latin_token(tok: str) -> bool:
    c = tok[0]
    return "a" <= c <= "z" or "0" <= c <= "9" or c == "_"


def core_chars(text: str) -> str:
    """검색에 의미 있는 글자(영문, 숫자, CJK)만 남긴다."""
    n = normalize(text)
    return "".join(ch for ch in n if ("a" <= ch <= "z") or ("0" <= ch <= "9") or is_cjk(ch))
