"""복원 연산. 각 연산은 str -> str | None (적용할 수 없으면 None).

오독 되돌리기는 "원래 B 인코딩 바이트를 A로 잘못 읽었다"는 가정으로
텍스트를 A로 다시 인코딩한 뒤 B로 읽는다. 이미 \ufffd(또는 '?')로 바뀐 바이트는
'모르는 바이트'로 두고, 남은 바이트로 맞출 수 있는 글자만 살린 뒤 나머지는 □로 표시한다.
"""
from __future__ import annotations

import base64
import binascii
import codecs
import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

from .score import LOST_MARK, REPLACEMENT, char_weight, hangul_tier, is_suspicious

# ---- 공통: 디코딩 실패 바이트를 □로 -------------------------------------
_LOST_HANDLER = "hangul_restore_lost"


def _lost_handler(exc):
    if isinstance(exc, UnicodeDecodeError):
        return LOST_MARK, exc.end
    raise exc


codecs.register_error(_LOST_HANDLER, _lost_handler)

# Windows/Java는 cp1252의 빈 자리(81 8D 8F 90 9D)를 C1 제어 문자로 그대로 통과시킨다
_CP1252_HOLES = {0x81, 0x8D, 0x8F, 0x90, 0x9D}


def _encode_char(ch: str, enc: str) -> bytes | None:
    try:
        if enc == "latin-1":
            o = ord(ch)
            return bytes((o,)) if o < 256 else None
        if enc == "cp1252":
            o = ord(ch)
            if o in _CP1252_HOLES:
                return bytes((o,))
            return ch.encode("cp1252")
        if enc == "euc-kr":
            # Python euc-kr 코덱은 확장 한글을 8바이트 조합 표현으로 바꾸므로 cp949로 인코딩 후 범위를 본다
            b = ch.encode("cp949")
            if len(b) == 2 and not (0xA1 <= b[0] <= 0xFE and 0xA1 <= b[1] <= 0xFE):
                return None
            return b
        return ch.encode(enc)
    except UnicodeEncodeError:
        return None


def _encode_text(text: str, enc: str) -> bytes | None:
    if enc in ("cp949", "utf-8"):
        try:
            return text.encode(enc)
        except UnicodeEncodeError:
            return None
    if enc == "latin-1":
        try:
            return text.encode("latin-1")
        except UnicodeEncodeError:
            return None
    out = bytearray()
    for ch in text:
        b = ch.encode("ascii") if ch < "\x80" else _encode_char(ch, enc)
        if b is None:
            return None
        out += b
    return bytes(out)


# ---- 잃은 바이트가 있는 경우: 동적 계획법으로 글자 맞추기 ----------------
HOLE = -1        # 확실히 잃은 바이트 (\ufffd, □)
MAYBE = -2       # '?' : 원래 '?'였거나, 인코딩 중 잃은 바이트

# 오독한 쪽 인코딩별로 \ufffd 하나가 삼킨 바이트 수 후보와 비용.
# UTF-8 디코더는 '유효한 앞부분'을 통째로 \ufffd 하나로 바꾸므로 1~3바이트가 될 수 있다.
HOLE_OPTIONS = {
    "utf-8": ((1, 0.0), (2, 0.15), (3, 0.6)),
    "cp949": ((1, 0.1), (2, 0.4)),
    "euc-kr": ((1, 0.1), (2, 0.4)),
    "latin-1": ((1, 0.1),),
    "cp1252": ((1, 0.1),),
}
MAYBE_COST = 0.3         # 깨진 단어 안의 '?'를 잃은 바이트로 볼 때
MAYBE_LITERAL_COST = 0.8 # 깨진 단어 안의 '?'를 원래 '?'로 볼 때 (대개 잃은 바이트다)
# 정렬을 고를 때 □ 하나의 비용. 점수표의 □(-1.2)보다 가볍게 둔다: 남은 바이트를 억지로 짝지어
# 드문 음절·한자를 만드는 정렬보다, 흔한 음절 하나를 맞추고 나머지를 □로 두는 정렬이 대개 맞다.
LOST_COST = 0.5
INVALID_COST = 3.0


def suspicious_question_marks(text: str) -> set[int]:
    """'?' 중 깨진 단어 안에 있는 것 (잃은 바이트일 수 있는 것)의 위치."""
    if "?" not in text:
        return set()
    out: set[int] = set()
    n = len(text)
    i = 0
    while i < n:
        if text[i] in " \t\r\n":
            i += 1
            continue
        j = i
        while j < n and text[j] not in " \t\r\n":
            j += 1
        word = text[i:j]
        if "?" in word and any(ord(c) >= 0x80 and is_suspicious(c) for c in word):
            for k in range(i, j):
                # 비ASCII 글자와 붙어 있는 '?' 연속만
                if text[k] == "?":
                    a = k
                    while a > i and text[a - 1] == "?":
                        a -= 1
                    b = k
                    while b + 1 < j and text[b + 1] == "?":
                        b += 1
                    if (a > i and ord(text[a - 1]) >= 0x80) or (b + 1 < j and ord(text[b + 1]) >= 0x80):
                        out.add(k)
        i = j
    return out


def has_holes(text: str) -> bool:
    return REPLACEMENT in text or LOST_MARK in text or bool(suspicious_question_marks(text))


_HANJA_ALTS: dict[str, tuple[bytes, ...]] | None = None


def hanja_alternatives() -> dict[str, tuple[bytes, ...]]:
    """KS X 1001에는 같은 한자가 여러 코드로 들어 있다(호환 한자 268자).
    중간에 NFC 정규화를 거치면 어느 코드였는지 잃으므로, 같은 글자로 정규화되는 코드를 모두 후보로 둔다."""
    global _HANJA_ALTS
    if _HANJA_ALTS is None:
        groups: dict[str, list[bytes]] = {}
        for b1 in range(0xCA, 0xFE):
            for b2 in range(0xA1, 0xFF):
                try:
                    ch = bytes((b1, b2)).decode("cp949")
                except UnicodeDecodeError:
                    continue
                groups.setdefault(unicodedata.normalize("NFC", ch), []).append(bytes((b1, b2)))
        _HANJA_ALTS = {k: tuple(v) for k, v in groups.items() if len(v) > 1}
    return _HANJA_ALTS


def _has_alternatives(text: str, enc: str) -> bool:
    if enc not in ("cp949", "euc-kr"):
        return False
    alts = hanja_alternatives()
    return any(ch in alts for ch in text)


def _tokens(text: str, enc: str) -> list | None:
    """바이트 열. 정수=아는 바이트, HOLE/MAYBE=모르는 바이트, tuple=가능한 바이트 열 후보들."""
    maybe = suspicious_question_marks(text)
    alts = hanja_alternatives() if enc in ("cp949", "euc-kr") else {}
    out: list = []
    for i, ch in enumerate(text):
        if ch == REPLACEMENT or ch == LOST_MARK:
            out.append(HOLE)
        elif ch == "?" and i in maybe:
            out.append(MAYBE)
        elif ch < "\x80":
            out.append(ord(ch))
        elif ch in alts:
            out.append(alts[ch])
        else:
            b = _encode_char(ch, enc)
            if b is None:
                return None
            out.extend(b)
    return out


def _cost(ch: str) -> float:
    return -char_weight(ch)


_PAIR_CACHE: dict[tuple[int, int], str | None] = {}


def _cp949_pair(b1: int, b2: int) -> str | None:
    key = (b1, b2)
    if key not in _PAIR_CACHE:
        try:
            _PAIR_CACHE[key] = bytes(key).decode("cp949")
        except UnicodeDecodeError:
            _PAIR_CACHE[key] = None
    return _PAIR_CACHE[key]


def _is_cp949_trail(b: int) -> bool:
    return 0x41 <= b <= 0x5A or 0x61 <= b <= 0x7A or 0x81 <= b <= 0xFE


def _is_cont(b) -> bool:
    return b is None or 0x80 <= b <= 0xBF


class _Holes:
    """토큰 열에서 바이트를 꺼내는 도우미.
    상태 = (다음 토큰 위치, 앞 토큰에서 아직 안 쓴 바이트들(None=모름))."""

    def __init__(self, tokens: list, options):
        self.t = tokens
        self.opts = options

    def draw(self, i: int, pend: tuple, k: int):
        """k바이트를 꺼내는 모든 방법: (바이트들, 다음 i, 다음 pend, 비용)."""
        if k == 0:
            return [((), i, pend, 0.0)]
        if pend:
            head = pend[0]
            return [((head,) + bs, ni, np, c) for bs, ni, np, c in self.draw(i, pend[1:], k - 1)]
        if i >= len(self.t):
            return []
        t = self.t[i]
        if type(t) is int and t >= 0:
            return [((t,) + bs, ni, np, c) for bs, ni, np, c in self.draw(i + 1, (), k - 1)]
        res = []
        if type(t) is tuple:                     # 같은 글자의 여러 코드 후보
            for alt in t:
                for bs, ni, np, c in self.draw(i + 1, tuple(alt[1:]), k - 1):
                    res.append(((alt[0],) + bs, ni, np, c))
            return res
        extra = 0.0
        if t == MAYBE:
            res += [((0x3F,) + bs, ni, np, c + MAYBE_LITERAL_COST) for bs, ni, np, c in self.draw(i + 1, (), k - 1)]
            extra = MAYBE_COST
        for length, lc in self.opts:
            for bs, ni, np, c in self.draw(i + 1, (None,) * (length - 1), k - 1):
                res.append(((None,) + bs, ni, np, c + lc + extra))
        return res


def _chars_cp949(h: _Holes, i: int, u: int):
    out = []
    for (b1,), si, su, c1 in h.draw(i, u, 1):
        if b1 is None:
            out.append((si, su, LOST_MARK, c1 + LOST_COST + 0.8))       # 홀로 남은 바이트
            for (b2,), ni, nu, c2 in h.draw(si, su, 1):
                if b2 is None or _is_cp949_trail(b2):
                    out.append((ni, nu, LOST_MARK, c1 + c2 + LOST_COST))
        elif b1 < 0x80:
            ch = chr(b1)
            out.append((si, su, ch, c1 + _cost(ch)))
        elif 0x81 <= b1 <= 0xFE:
            for (b2,), ni, nu, c2 in h.draw(si, su, 1):
                if b2 is None:
                    out.append((ni, nu, LOST_MARK, c1 + c2 + LOST_COST))
                elif _is_cp949_trail(b2):
                    ch = _cp949_pair(b1, b2)
                    if ch is None:
                        out.append((ni, nu, LOST_MARK, c1 + c2 + INVALID_COST))
                    else:
                        out.append((ni, nu, ch, c1 + c2 + _cost(ch)))
            out.append((si, su, LOST_MARK, c1 + INVALID_COST + 0.5))      # 뒷바이트 없는 앞바이트
        else:
            out.append((si, su, LOST_MARK, c1 + INVALID_COST))
    return out


def _utf8_len(b: int) -> int:
    if 0xC2 <= b <= 0xDF:
        return 2
    if 0xE0 <= b <= 0xEF:
        return 3
    if 0xF0 <= b <= 0xF4:
        return 4
    return 0


def _chars_utf8(h: _Holes, i: int, u: int):
    out = []
    for (b1,), si, su, c1 in h.draw(i, u, 1):
        if b1 is None:
            for n, extra in ((1, 0.3), (2, 0.15), (3, 0.0)):
                for bs, ni, nu, c2 in h.draw(si, su, n - 1):
                    if all(_is_cont(b) for b in bs):
                        out.append((ni, nu, LOST_MARK, c1 + c2 + LOST_COST + extra))
        elif b1 < 0x80:
            ch = chr(b1)
            out.append((si, su, ch, c1 + _cost(ch)))
        else:
            n = _utf8_len(b1)
            if n:
                for bs, ni, nu, c2 in h.draw(si, su, n - 1):
                    if not all(_is_cont(b) for b in bs):
                        continue
                    if None in bs:
                        out.append((ni, nu, LOST_MARK, c1 + c2 + LOST_COST))
                        continue
                    try:
                        ch = bytes((b1,) + bs).decode("utf-8")
                        out.append((ni, nu, ch, c1 + c2 + _cost(ch)))
                    except UnicodeDecodeError:
                        out.append((ni, nu, LOST_MARK, c1 + c2 + INVALID_COST))
                out.append((si, su, LOST_MARK, c1 + INVALID_COST + 0.5))  # 잘린 시퀀스
            else:
                out.append((si, su, LOST_MARK, c1 + INVALID_COST))
    return out


def _dp(tokens: list, target: str, options) -> str:
    h = _Holes(tokens, options)
    step = _chars_cp949 if target == "cp949" else _chars_utf8
    n = len(tokens)
    best: list[dict[tuple, tuple]] = [dict() for _ in range(n + 1)]
    best[0][()] = (0.0, None, "")
    for i in range(n + 1):
        # 같은 i 안에서는 남은 바이트가 줄어드는 방향으로만 이동하므로 긴 것부터 처리한다
        done: set = set()
        while True:
            todo = [p for p in best[i] if p not in done]
            if not todo:
                break
            pend = max(todo, key=len)
            done.add(pend)
            if i == n and not pend:
                continue
            cur = best[i][pend]
            for ni, np, ch, c in step(h, i, pend):
                nc = cur[0] + c
                old = best[ni].get(np)
                if old is None or nc < old[0] - 1e-9:
                    best[ni][np] = (nc, (i, pend), ch)
    end = best[n].get(())
    if end is None:
        return LOST_MARK
    chars = []
    state = (n, ())
    while True:
        cost, prev, ch = best[state[0]][state[1]]
        if prev is None:
            break
        chars.append(ch)
        state = prev
    return "".join(reversed(chars))


def _safe_boundary(b: int, target: str) -> bool:
    """이 바이트 앞뒤에서 글자가 끊긴다고 확신할 수 있나."""
    if target == "utf-8":
        return b < 0x80
    return b < 0x41 or 0x5B <= b <= 0x60 or 0x7B <= b < 0x80


def decode_tokens(tokens: list[int], target: str, options) -> str:
    """구멍 없는 구간은 빠른 디코딩, 구멍 있는 구간만 동적 계획법."""
    out: list[str] = []
    chunk: list[int] = []

    def flush():
        if not chunk:
            return
        if any(type(t) is tuple or t < 0 for t in chunk):
            out.append(_dp(chunk, target, options))
        else:
            out.append(bytes(chunk).decode(target, errors=_LOST_HANDLER))
        chunk.clear()

    for t in tokens:
        if type(t) is int and t >= 0 and _safe_boundary(t, target):
            flush()
            out.append(chr(t))
        else:
            chunk.append(t)
    flush()
    return "".join(out)


def reverse_misread(text: str, misread_as: str, original: str) -> str | None:
    """original 인코딩 바이트를 misread_as로 잘못 읽은 텍스트를 되돌린다."""
    if text.isascii():
        return None
    if has_holes(text) or _has_alternatives(text, misread_as):
        tokens = _tokens(text, misread_as)
        if tokens is None:
            return None
        result = decode_tokens(tokens, original, HOLE_OPTIONS[misread_as])
    else:
        data = _encode_text(text, misread_as)
        if data is None:
            return None
        # UTF-8로 잘못 읽었다면 깨진 바이트는 모두 \ufffd가 됐을 것이다. \ufffd가 없는데 원래 인코딩으로
        # 읽히지 않으면 가정이 틀린 것. (다른 경우는 바이트 단위로 잘린 문자열일 수 있어 □로 살린다)
        errors = "strict" if misread_as == "utf-8" else _LOST_HANDLER
        try:
            result = data.decode(original, errors=errors)
        except UnicodeDecodeError:
            return None
    return None if result == text else result


# ---- URL 디코딩 -------------------------------------------------------
_PCT = r"%(?:[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4})"
URL_RUN = re.compile(rf"\+*{_PCT}(?:{_PCT}|\+)*")
_URL_PART = re.compile(r"%([0-9A-Fa-f]{2})|%u([0-9A-Fa-f]{4})|\+")


def _url_run(run: str, enc: str) -> str | None:
    out: list[str] = []
    buf = bytearray()

    def flush() -> bool:
        if buf:
            try:
                out.append(bytes(buf).decode(enc))
            except UnicodeDecodeError:
                return False
            buf.clear()
        return True

    for m in _URL_PART.finditer(run):
        if m.group(1):
            buf.append(int(m.group(1), 16))
        elif m.group(2):
            if not flush():
                return None
            out.append(chr(int(m.group(2), 16)))
        else:
            buf.append(0x20)
    if not flush():
        return None
    return "".join(out)


_NON_SPACE = re.compile(r"[^ \t\r\n\f\v]+")


def url_decode(text: str, enc: str) -> str | None:
    if "%" not in text:
        return None
    changed = False

    def repl(m):
        nonlocal changed
        r = _url_run(m.group(0), enc)
        if r is None or r == m.group(0):
            return m.group(0)
        changed = True
        return r

    def token(m):
        tok = m.group(0)
        if "%" not in tok:
            return tok
        out = URL_RUN.sub(repl, tok)
        # 폼 인코딩(application/x-www-form-urlencoded) 토큰이면 떨어져 있는 '+'도 공백
        if out != tok and "+" in out and sum(r.group(0).count("%") for r in URL_RUN.finditer(tok)) >= 2:
            out = out.replace("+", " ")
        return out

    result = _NON_SPACE.sub(token, text)
    return result if changed else None


# ---- \u 이스케이프 -----------------------------------------------------
ESCAPE_RUN = re.compile(r"(?:\\+(?:u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}))+")
_ESC_PART = re.compile(r"(\\+)(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})")


def _escape_run(run: str) -> str:
    parts = [(m.group(0), int(m.group(2)[1:], 16)) for m in _ESC_PART.finditer(run)]
    out = []
    i = 0
    while i < len(parts):
        raw, cp = parts[i]
        if 0xD800 <= cp <= 0xDBFF and i + 1 < len(parts) and 0xDC00 <= parts[i + 1][1] <= 0xDFFF:
            low = parts[i + 1][1]
            out.append(chr(0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00)))
            i += 2
            continue
        if 0xD800 <= cp <= 0xDFFF or cp > 0x10FFFF:
            out.append(raw)       # 홀로 남은 서로게이트, 범위 밖: 원문 유지
        else:
            out.append(chr(cp))
        i += 1
    return "".join(out)


def unicode_unescape(text: str) -> str | None:
    if "\\" not in text:
        return None
    result = ESCAPE_RUN.sub(lambda m: _escape_run(m.group(0)), text)
    return None if result == text else result


# ---- HTML 엔티티 -------------------------------------------------------
ENTITY_RUN = re.compile(r"(?:&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});)+")


def html_unescape(text: str) -> str | None:
    if "&" not in text:
        return None
    result = ENTITY_RUN.sub(lambda m: html.unescape(m.group(0)), text)
    return None if result == text else result


# ---- Base64 ----------------------------------------------------------
BASE64_TOKEN = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{4,}={0,2}(?![A-Za-z0-9+/=_-])")
BASE64_MIN_LEN = 8          # 패딩 포함. 'test', 'admin' 같은 짧은 영단어 오탐 방지


def _b64_bytes(token: str) -> bytes | None:
    core = token.rstrip("=")
    if len(core) % 4 == 1:
        return None
    if "-" in core or "_" in core:
        if "+" in core or "/" in core:
            return None
        core = core.replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(core + "=" * (-len(core) % 4), validate=True)
    except (binascii.Error, ValueError):
        return None


def is_valid_korean(text: str, ksx_only: bool = False) -> bool:
    """Base64 결과로 인정할 만한 한글 텍스트인가."""
    hangul = rare = 0
    for ch in text:
        o = ord(ch)
        if o < 0x80:
            if not (0x20 <= o < 0x7F or ch in "\t\n\r"):
                return False
            continue
        tier = hangul_tier(ch)
        if tier:
            hangul += 1
            if tier == 3:
                if ksx_only:
                    return False
                rare += 1
        elif char_weight(ch) < -0.45:
            return False
    return hangul >= 2 and rare * 4 <= hangul


def _is_encoded_ascii(text: str) -> bool:
    """URL/이스케이프/엔티티가 들어 있는 ASCII (Base64 안에 한 번 더 인코딩된 경우)."""
    if not text.isascii() or not text.isprintable():
        return False
    return bool(URL_RUN.search(text) or ESCAPE_RUN.search(text) or ENTITY_RUN.search(text))


def base64_decode(text: str, enc: str) -> str | None:
    changed = False

    def repl(m):
        nonlocal changed
        if len(m.group(0)) < BASE64_MIN_LEN:
            return m.group(0)
        data = _b64_bytes(m.group(0))
        if not data:
            return m.group(0)
        try:
            s = data.decode(enc)
        except UnicodeDecodeError:
            return m.group(0)
        if is_valid_korean(s, ksx_only=(enc == "cp949")) or _is_encoded_ascii(s):
            changed = True
            return s
        return m.group(0)

    result = BASE64_TOKEN.sub(repl, text)
    return result if changed else None


# ---- 연산 목록 ---------------------------------------------------------
@dataclass(frozen=True)
class Decoder:
    id: str
    label: str
    kind: str            # "misread"(점수가 좋아질 때만 채택) | "format"(구조적 해제)
    fn: Callable[[str], "str | None"]
    prior: Callable[[str], float] | None = None    # 이 가정이 입력 모양과 얼마나 안 맞는지 (감산)


ADJACENT_HOLE_PENALTY = -1.5


def adjacent_holes(text: str) -> int:
    """잃은 바이트 표시(\ufffd, □, 깨진 단어 안의 '?')가 연달아 붙은 횟수."""
    maybe = suspicious_question_marks(text) if "?" in text else set()
    n = 0
    prev = False
    for i, ch in enumerate(text):
        cur = ch == REPLACEMENT or ch == LOST_MARK or i in maybe
        if cur and prev:
            n += 1
        prev = cur
    return n


def _cjk_prior(text: str) -> float:
    """CP949 디코더는 잘못된 바이트 하나만 \ufffd로 바꾸고 다음 바이트부터 다시 읽으므로 \ufffd가
    연달아 나오는 일이 드물다. 연속된 \ufffd는 'CP949를 UTF-8로 읽음' 쪽 증거라 이 가정은 감산한다."""
    return ADJACENT_HOLE_PENALTY * adjacent_holes(text) if has_holes(text) else 0.0


def _utf8_prior(text: str) -> float:
    """CP949 바이트를 UTF-8로 읽었는데 \ufffd가 하나도 없다면 모든 바이트가 우연히 올바른 UTF-8이었다는 뜻이다.
    한두 글자가 아니면 거의 일어나지 않으므로 감산한다 (Latin-1 오독 결과를 이 경로로 엉뚱하게 푸는 것 방지)."""
    if has_holes(text):
        return 0.0
    return -3.0 if sum(1 for c in text if ord(c) >= 0x80) >= 2 else 0.0


def _latin_prior(text: str) -> float:
    """Latin-1 디코딩은 \ufffd를 만들지 않는다 (CP1252도 빈 자리 5개뿐). \ufffd가 있으면 이 가정은 감산한다."""
    return -1.0 * text.count(REPLACEMENT)


def _misread(id_: str, label: str, misread_as: str, original: str) -> Decoder:
    prior = {"cp949": _cjk_prior, "euc-kr": _cjk_prior, "utf-8": _utf8_prior,
             "latin-1": _latin_prior, "cp1252": _latin_prior}.get(misread_as)
    return Decoder(id_, label, "misread", lambda t: reverse_misread(t, misread_as, original), prior)


MISREAD = [
    _misread("utf8_as_cp949", "UTF-8 바이트를 CP949로 읽음 (되돌림)", "cp949", "utf-8"),
    _misread("cp949_as_latin1", "CP949 바이트를 Latin-1로 읽음 (되돌림)", "latin-1", "cp949"),
    _misread("cp949_as_cp1252", "CP949 바이트를 CP1252로 읽음 (되돌림)", "cp1252", "cp949"),
    _misread("cp949_as_utf8", "CP949 바이트를 UTF-8로 읽음 (되돌림)", "utf-8", "cp949"),
    _misread("utf8_as_latin1", "UTF-8 바이트를 Latin-1로 읽음 (되돌림)", "latin-1", "utf-8"),
    _misread("utf8_as_cp1252", "UTF-8 바이트를 CP1252로 읽음 (되돌림)", "cp1252", "utf-8"),
    _misread("utf8_as_euckr", "UTF-8 바이트를 EUC-KR로 읽음 (되돌림)", "euc-kr", "utf-8"),
]

FORMAT = [
    Decoder("url_utf8", "URL 디코딩 (UTF-8)", "format", lambda t: url_decode(t, "utf-8")),
    Decoder("url_cp949", "URL 디코딩 (CP949)", "format", lambda t: url_decode(t, "cp949")),
    Decoder("unicode_escape", "\\u 이스케이프 해제", "format", unicode_unescape),
    Decoder("html_entity", "HTML 엔티티 해제", "format", html_unescape),
    Decoder("base64_utf8", "Base64 디코딩 (UTF-8)", "format", lambda t: base64_decode(t, "utf-8")),
    Decoder("base64_cp949", "Base64 디코딩 (CP949)", "format", lambda t: base64_decode(t, "cp949")),
]

ALL = FORMAT + MISREAD
BY_ID = {d.id: d for d in ALL}


def ordered_for(text: str) -> list[Decoder]:
    """시도 순서. 결과가 같으면 먼저 찾은 경로를 남기므로 순서가 곧 동점 처리 규칙이다.
    \ufffd가 연달아 있으면 CP949→UTF-8 오독(손실형)의 특징이라 그 연산을 먼저 둔다."""
    if REPLACEMENT * 2 in text:
        first = [d for d in MISREAD if d.id == "cp949_as_utf8"]
        return FORMAT + first + [d for d in MISREAD if d.id != "cp949_as_utf8"]
    return ALL
