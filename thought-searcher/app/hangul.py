"""한영 자판 오타 보정 (검색 결과가 0건일 때만 쓴다).

- 영문 자판으로 친 한글 자모/음절(`ㅜㅎㅑㅜㅌ`, `ㅜ햐ㅜㅌ`) -> 영문(`nginx`)
- 한글 자판으로 쳤어야 할 영문(`qovh`) -> 한글(`배포`)

아래 두벌식 표와 `is_keyboard_latin`, `latin_to_hangul`은 emoji-searcher/app/hangul.py를 복사한 것이다
(도구끼리 import하지 않는 저장소 규칙). 그 위에 한글 -> 영문 방향(`hangul_to_latin`)과 검색어 단위 보정
(`fix_layout`)을 더했다.
"""
from __future__ import annotations

import re

SBASE, SLAST = 0xAC00, 0xD7A3
NJUNG, NJONG = 21, 28

CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ",
        "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]

# 호환 자모 자음 (ㄱ ~ ㅎ, 겹자음 포함)
CONSONANTS = {chr(c) for c in range(0x3131, 0x314F)}
COMPAT_JAMO = {chr(c) for c in range(0x3131, 0x3164)}

# 두벌식 배열
KEYMAP = {
    "q": "ㅂ", "w": "ㅈ", "e": "ㄷ", "r": "ㄱ", "t": "ㅅ", "y": "ㅛ", "u": "ㅕ", "i": "ㅑ", "o": "ㅐ", "p": "ㅔ",
    "a": "ㅁ", "s": "ㄴ", "d": "ㅇ", "f": "ㄹ", "g": "ㅎ", "h": "ㅗ", "j": "ㅓ", "k": "ㅏ", "l": "ㅣ",
    "z": "ㅋ", "x": "ㅌ", "c": "ㅊ", "v": "ㅍ", "b": "ㅠ", "n": "ㅜ", "m": "ㅡ",
}
SHIFT_KEYMAP = {"Q": "ㅃ", "W": "ㅉ", "E": "ㄸ", "R": "ㄲ", "T": "ㅆ", "O": "ㅒ", "P": "ㅖ"}

VOWEL_COMBO = {
    ("ㅗ", "ㅏ"): "ㅘ", ("ㅗ", "ㅐ"): "ㅙ", ("ㅗ", "ㅣ"): "ㅚ",
    ("ㅜ", "ㅓ"): "ㅝ", ("ㅜ", "ㅔ"): "ㅞ", ("ㅜ", "ㅣ"): "ㅟ", ("ㅡ", "ㅣ"): "ㅢ",
}
JONG_COMBO = {
    ("ㄱ", "ㅅ"): "ㄳ", ("ㄴ", "ㅈ"): "ㄵ", ("ㄴ", "ㅎ"): "ㄶ", ("ㄹ", "ㄱ"): "ㄺ", ("ㄹ", "ㅁ"): "ㄻ",
    ("ㄹ", "ㅂ"): "ㄼ", ("ㄹ", "ㅅ"): "ㄽ", ("ㄹ", "ㅌ"): "ㄾ", ("ㄹ", "ㅍ"): "ㄿ", ("ㄹ", "ㅎ"): "ㅀ",
    ("ㅂ", "ㅅ"): "ㅄ",
}
_JONG_INDEX = {j: i for i, j in enumerate(JONG) if j}
_CHO_INDEX = {c: i for i, c in enumerate(CHO)}
_JUNG_INDEX = {v: i for i, v in enumerate(JUNG)}


def is_syllable(ch: str) -> bool:
    return SBASE <= ord(ch) <= SLAST


def is_keyboard_latin(text: str) -> bool:
    """공백을 뺀 모든 글자가 영문 알파벳이면 True."""
    s = "".join(text.split())
    return bool(s) and all(("a" <= ch <= "z") or ("A" <= ch <= "Z") for ch in s)


def _compose(cho: str, jung: str, jong: str = "") -> str:
    return chr(SBASE + (_CHO_INDEX[cho] * NJUNG + _JUNG_INDEX[jung]) * NJONG + _JONG_INDEX.get(jong, 0))


def _assemble(jamo: list[str]) -> str:
    out: list[str] = []
    i, n = 0, len(jamo)

    def is_v(k: int) -> bool:
        return k < n and jamo[k] in _JUNG_INDEX

    def is_c(k: int) -> bool:
        return k < n and jamo[k] in CONSONANTS

    while i < n:
        j = jamo[i]
        if j in _CHO_INDEX and is_v(i + 1):
            cho = j
            jung = jamo[i + 1]
            i += 2
            if is_v(i) and (jung, jamo[i]) in VOWEL_COMBO:
                jung = VOWEL_COMBO[(jung, jamo[i])]
                i += 1
            jong = ""
            if is_c(i) and jamo[i] in _JONG_INDEX and not is_v(i + 1):
                jong = jamo[i]
                i += 1
                if is_c(i) and (jong, jamo[i]) in JONG_COMBO and not is_v(i + 1):
                    jong = JONG_COMBO[(jong, jamo[i])]
                    i += 1
            out.append(_compose(cho, jung, jong))
        elif j in _JUNG_INDEX and is_v(i + 1) and (j, jamo[i + 1]) in VOWEL_COMBO:
            out.append(VOWEL_COMBO[(j, jamo[i + 1])])
            i += 2
        else:
            out.append(j)
            i += 1
    return "".join(out)


def latin_to_hangul(text: str) -> str | None:
    """두벌식 기준으로 한글 자판에서 쳤어야 할 글자로 바꾼다. 'qnf' -> '불', 'qovh' -> '배포'.

    영문 알파벳과 공백 외의 글자가 있으면 None.
    """
    if not is_keyboard_latin(text):
        return None
    words = []
    for word in text.split():
        jamo = [SHIFT_KEYMAP.get(ch) or KEYMAP[ch.lower()] for ch in word]
        words.append(_assemble(jamo))
    return " ".join(words)


# ---- 여기부터 thought-searcher에서 더한 것 -----------------------------------------------
_KEY_OF = {v: k for k, v in KEYMAP.items()}
_KEY_OF.update({"ㅃ": "q", "ㅉ": "w", "ㄸ": "e", "ㄲ": "r", "ㅆ": "t", "ㅒ": "o", "ㅖ": "p"})   # 검색은 대소문자 무시
_SPLIT = {v: k for k, v in VOWEL_COMBO.items()}
_SPLIT.update({v: k for k, v in JONG_COMBO.items()})


def _keys(jamo: str) -> str | None:
    if jamo in _KEY_OF:
        return _KEY_OF[jamo]
    if jamo in _SPLIT:
        a, b = _SPLIT[jamo]
        return _KEY_OF[a] + _KEY_OF[b]
    return None


def hangul_to_latin(word: str) -> str | None:
    """영문 자판으로 친 한글(`ㅜㅎㅑㅜㅌ`, `ㅜ햐ㅜㅌ`) -> `nginx`. 정상적인 한글 낱말은 건드리지 않는다.

    낱자 자모가 하나도 없는 낱말(완성된 음절뿐)은 진짜 한글 낱말로 보고 None."""
    if len(word) < 2 or not any(ch in COMPAT_JAMO for ch in word):
        return None
    out = []
    for ch in word:
        if is_syllable(ch):
            idx = ord(ch) - SBASE
            parts = [CHO[idx // (NJUNG * NJONG)], JUNG[(idx % (NJUNG * NJONG)) // NJONG], JONG[idx % NJONG]]
            for p in parts:
                if p:
                    k = _keys(p)
                    if k is None:
                        return None
                    out.append(k)
        elif ch in COMPAT_JAMO:
            k = _keys(ch)
            if k is None:
                return None
            out.append(k)
        else:
            return None
    res = "".join(out)
    return res if len(res) >= 2 else None


def latin_word_to_hangul(word: str) -> str | None:
    """한글 자판 오타처럼 보이는 영문 소문자 낱말 -> 한글. 결과가 완성된 음절뿐일 때만 (`qovh` -> `배포`)."""
    if len(word) < 2 or not (word.isascii() and word.isalpha() and word.islower()):
        return None
    res = latin_to_hangul(word)
    if not res or not all(is_syllable(ch) for ch in res):
        return None
    return res


def josa_ro(word: str) -> str:
    """'로' 또는 '으로'. 영문은 '로', 한글은 받침이 없거나 ㄹ이면 '로'."""
    ch = word[-1:]
    if ch and is_syllable(ch):
        jong = (ord(ch) - SBASE) % NJONG
        return "로" if jong in (0, 8) else "으로"
    return "로"


_TOKEN = re.compile(r'-?"[^"]*(?:"|$)|\S+')


def fix_layout(text: str) -> tuple[str, list[str]] | None:
    """검색어의 낱말(검색 문법 조각과 따옴표 구문 밖)을 하나씩 보고 한영 오타를 고친다.
    (고친 검색어, 고친 낱말들). 고칠 것이 없으면 None."""
    changed: list[str] = []

    def fix(m: re.Match) -> str:
        tok = m.group(0)
        if tok[0] in '-"' or ":" in tok:
            return tok
        new = hangul_to_latin(tok) or latin_word_to_hangul(tok)
        if new is None or new == tok:
            return tok
        changed.append(new)
        return new

    out = _TOKEN.sub(fix, text or "")
    return (out, changed) if changed else None


def found_message(words: list[str]) -> str:
    """'nginx로 찾았습니다'."""
    joined = " ".join(words)
    return f"{joined}{josa_ro(joined)} 찾았습니다"
