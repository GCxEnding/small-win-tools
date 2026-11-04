"""한글 초성 추출과 두벌식 영문 자판 -> 한글 변환 (외부 라이브러리 없음)."""
from __future__ import annotations

SBASE, SLAST = 0xAC00, 0xD7A3
NJUNG, NJONG = 21, 28

CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ",
        "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]

# 호환 자모 자음 (ㄱ ~ ㅎ, 겹자음 포함)
CONSONANTS = {chr(c) for c in range(0x3131, 0x314F)}

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


def choseong(text: str) -> str:
    """'배포' -> 'ㅂㅍ'. 한글 음절이 아닌 글자는 공백만 빼고 그대로 둔다."""
    out = []
    for ch in text:
        if is_syllable(ch):
            out.append(CHO[(ord(ch) - SBASE) // (NJUNG * NJONG)])
        elif not ch.isspace():
            out.append(ch)
    return "".join(out)


def is_choseong_only(text: str) -> bool:
    """공백을 뺀 모든 글자가 한글 자음(ㄱ~ㅎ)이면 True."""
    s = "".join(text.split())
    return bool(s) and all(ch in CONSONANTS for ch in s)


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
