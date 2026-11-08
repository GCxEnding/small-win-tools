"""한글다움 점수와 손실 판정.

점수는 글자별 가중치의 합이다. 같은 바이트를 서로 다르게 해석한 후보끼리 비교하므로
평균이 아니라 합을 쓴다(깨진 글자는 대개 원래보다 글자 수가 많고 점수가 낮다).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "syllable_freq.json"

LOST_MARK = "\u25a1"      # □ : 복원하지 못한 글자 자리
REPLACEMENT = "\ufffd"    # \ufffd : 이미 대체 문자로 바뀐 바이트

# ---- 가중치 -----------------------------------------------------------
W_COMMON = 2.0            # 자주 쓰는 음절
W_KSX = 0.25              # KS X 1001 완성형 2,350자 (자주 쓰는 음절 제외)
W_RARE = -1.5             # 그 외 현대 한글 음절 (깨진 결과에 흔함)
W_LOST = -1.2             # □
W_FFFD = -2.0             # \ufffd
W_CONTROL = -2.5          # 제어 문자, 사설 영역
W_HANJA = -1.0
W_KANA = -1.5
W_FOREIGN_NEW = -1.0      # 한자/가나가 원래 입력에 없던 경우 추가 감산
W_LATIN_EXT = -1.0        # Latin-1 확장, cp1252 기호
W_OTHER_SCRIPT = -1.2     # 그리스·키릴·아랍 등 (깨진 결과에 흔함)
PATH_PENALTY = 0.15       # 경로 한 단계마다
W_QMARK_BROKEN = -1.5     # 깨진 글자 옆의 '?' (잃은 바이트를 '?'로 바꾼 흔적)

CP1252_PUNCT = set("‘’“”…–—•")  # ‘’“”…–—•
CP1252_SPECIALS = set("€‚ƒ„†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ…")


@lru_cache(maxsize=1)
def _tiers() -> tuple[frozenset, frozenset]:
    try:
        raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        common, ksx = frozenset(raw["common"]), frozenset(raw["ksx1001"])
        if len(ksx) >= 2000:
            return common, ksx
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # 데이터 파일이 없거나 깨졌으면 코덱으로 다시 만든다 (자주 쓰는 음절 구분은 없음)
    ksx = set()
    for cp in range(0xAC00, 0xD7A4):
        b = chr(cp).encode("cp949")
        if 0xB0 <= b[0] <= 0xC8 and 0xA1 <= b[1] <= 0xFE:
            ksx.add(chr(cp))
    return frozenset(), frozenset(ksx)


def hangul_tier(ch: str) -> int:
    """1=자주 쓰는 음절, 2=KS X 1001, 3=희귀 음절, 0=한글 음절 아님."""
    if not ("가" <= ch <= "힣"):
        return 0
    common, ksx = _tiers()
    if ch in common:
        return 1
    if ch in ksx:
        return 2
    return 3


def is_hanja(o: int) -> bool:
    return 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x3134F


def is_kana(o: int) -> bool:
    return 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF or 0xFF66 <= o <= 0xFF9F


_W: dict[str, float] = {}


def char_weight(ch: str) -> float:
    """입력과 무관한 글자 가중치."""
    w = _W.get(ch)
    if w is None:
        w = _W[ch] = _weight(ch)
    return w


def _weight(ch: str) -> float:
    o = ord(ch)
    if o < 0x80:
        return 0.0 if (0x20 <= o < 0x7F or ch in "\t\n\r") else W_CONTROL
    if 0xAC00 <= o <= 0xD7A3:
        return {1: W_COMMON, 2: W_KSX}.get(hangul_tier(ch), W_RARE)
    if ch == LOST_MARK:
        return W_LOST
    if ch == REPLACEMENT:
        return W_FFFD
    if o < 0xA0:
        return W_CONTROL
    if o <= 0xFF:
        return -0.3 if ch in "\xa0\xb7" else W_LATIN_EXT
    if 0x3131 <= o <= 0x318E:          # 호환 자모 ㄱ~ㅣ
        return -0.2
    if is_hanja(o):
        return W_HANJA
    if is_kana(o):
        return W_KANA
    if 0xE000 <= o <= 0xF8FF or o >= 0xF0000:
        return W_CONTROL
    if 0xD800 <= o <= 0xDFFF:
        return -3.0
    if 0x0300 <= o <= 0x036F:          # 결합 부호
        return -1.5
    if o < 0x2000:                     # Latin 확장, 그리스, 키릴, 아랍, 한글 자모(조합형) 등
        return W_OTHER_SCRIPT
    if ch in CP1252_PUNCT:
        return -0.2
    if 0x2000 <= o <= 0x206F:
        return -0.3
    if 0x2070 <= o <= 0x2BFF:          # 기호, 화살표, 수학, 도형, 원문자
        return -0.3
    if 0x3000 <= o <= 0x303F:          # CJK 기호와 문장 부호
        return -0.2
    if 0x3200 <= o <= 0x33FF:
        return -0.4
    if 0xFF01 <= o <= 0xFF5E:          # 전각 ASCII
        return -0.3
    if 0x1F000 <= o <= 0x1FAFF:        # 이모지
        return -0.5
    return -1.0


def is_suspicious(ch: str) -> bool:
    """깨짐을 의심할 글자인가 (정상 한글·ASCII·흔한 기호가 아니면 의심)."""
    return char_weight(ch) < -0.45


def score(text: str, input_chars: frozenset | set = frozenset()) -> float:
    total = 0.0
    for ch in text:
        w = char_weight(ch)
        if w <= W_HANJA and ch not in input_chars:
            o = ord(ch)
            if is_hanja(o) or is_kana(o):
                w += W_FOREIGN_NEW
        total += w
    if "?" in text:
        total += W_QMARK_BROKEN * _broken_qmarks(text)
    if "%" in text or "&" in text or "\\" in text:
        total += _escape_penalty(text)
    return total


# 아직 풀지 않은 이스케이프는 조금씩 감산한다 (4단계 이상 인코딩에서 3단계까지 푼 결과가 원문보다 앞에 오도록).
W_PCT = -0.2              # %XX (같은 토큰에 2개 이상일 때)
W_ESC = -0.3              # \uXXXX, &#...;
_PCT_RX = re.compile(r"%(?:[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4})")
_ESC_RX = re.compile(r"\\+(?:u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})|&#(?:[0-9]{1,7}|[xX][0-9a-fA-F]{1,6});")
_TOKEN_RX = re.compile(r"[^ \t\r\n]+")


def _escape_penalty(text: str) -> float:
    total = 0.0
    if "%" in text:
        for tok in _TOKEN_RX.findall(text):
            n = len(_PCT_RX.findall(tok)) if "%" in tok else 0
            if n >= 2:
                total += W_PCT * n
    if "\\" in text or "&#" in text:
        total += W_ESC * len(_ESC_RX.findall(text))
    return total


def _broken_qmarks(text: str) -> int:
    """깨진 비ASCII 글자에 붙어 있는 '?' 연속의 글자 수."""
    n = 0
    for m in _QRUN.finditer(text):
        a, b = m.start(), m.end()
        left = text[a - 1] if a > 0 else ""
        right = text[b] if b < len(text) else ""
        if any(c and ord(c) >= 0x80 and is_suspicious(c) for c in (left, right)):
            n += b - a
    return n


_QRUN = re.compile(r"\?+")


# ---- 손실 판정 ----------------------------------------------------------
def mark_lost(text: str) -> str:
    return text.replace(REPLACEMENT, LOST_MARK)


def count_lost(result: str, original: str) -> int:
    lost = result.count(LOST_MARK) + result.count(REPLACEMENT)
    return max(0, lost - original.count(LOST_MARK))


def korean_len(text: str) -> int:
    """손실 비율의 분모: ASCII와 공백을 뺀 글자 수 (복원 대상이 된 부분)."""
    return sum(1 for ch in text if ord(ch) >= 0x80 and not ch.isspace())


def loss_labels(lost: int, result: str) -> list[str]:
    if lost <= 0:
        return []
    labels = ["일부 손실", f"{lost}글자 손실"]
    if lost * 2 > max(1, korean_len(result)):
        labels.append("복원 불가에 가까움")
    return labels
