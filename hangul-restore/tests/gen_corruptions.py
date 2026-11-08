"""정상 문장을 일부러 깨뜨려 테스트 케이스를 만든다. 정답은 원문이므로 확실하다.

    python tests/gen_corruptions.py          # 종류별 개수와 예시 출력
"""
from __future__ import annotations

import base64
import codecs
import random
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, quote_plus

CORPUS = Path(__file__).resolve().parent / "corpus.txt"
CP1252_HOLES = {0x81, 0x8D, 0x8F, 0x90, 0x9D}


@dataclass
class Case:
    input: str
    expected: str
    kind: str
    lossy: bool = False
    lost: int = 0                     # 손실 케이스: 실제로 잃은 글자 수
    meta: dict = field(default_factory=dict)


def load_corpus() -> list[str]:
    lines = CORPUS.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


# ---- 깨뜨리는 연산 ------------------------------------------------------
def decode_as(data: bytes, enc: str, errors: str = "strict") -> str:
    """바이트를 enc로 (잘못) 읽는다. cp1252의 빈 자리는 Windows/Java처럼 C1 문자로 통과."""
    if enc == "cp1252":
        return "".join(chr(b) if b in CP1252_HOLES else bytes((b,)).decode("cp1252") for b in data)
    return data.decode(enc, errors)


def misread(text: str, src: str, as_enc: str) -> str | None:
    try:
        return decode_as(text.encode(src), as_enc)
    except UnicodeDecodeError:
        return None


_recorded: list[tuple[int, int]] = []


def _record(exc):
    _recorded.append((exc.start, exc.end))
    return "\ufffd", exc.end


codecs.register_error("gen_record", _record)


def lossy_misread(text: str, src: str, as_enc: str) -> tuple[str, int]:
    """errors=replace로 잘못 읽고, 바이트가 대체된 원래 글자 수를 센다."""
    data = text.encode(src)
    _recorded.clear()
    out = data.decode(as_enc, "gen_record")
    bad = set()
    for a, b in _recorded:
        bad.update(range(a, b))
    lost, pos = 0, 0
    for ch in text:
        n = len(ch.encode(src))
        if any(p in bad for p in range(pos, pos + n)):
            lost += 1
        pos += n
    return out, lost


def url(text: str, enc: str = "utf-8", plus: bool = False) -> str:
    return (quote_plus if plus else quote)(text, safe="", encoding=enc)


def escape(text: str, upper: bool = False) -> str:
    fmt = "\\u{:04X}" if upper else "\\u{:04x}"
    return "".join(ch if ord(ch) < 0x80 else fmt.format(ord(ch)) for ch in text)


def entity(text: str, hexa: bool = False) -> str:
    fmt = "&#x{:X};" if hexa else "&#{};"
    return "".join(ch if ord(ch) < 0x80 else fmt.format(ord(ch)) for ch in text)


def b64(text: str, enc: str = "utf-8", urlsafe: bool = False, strip_pad: bool = False) -> str:
    raw = text.encode(enc)
    s = (base64.urlsafe_b64encode if urlsafe else base64.b64encode)(raw).decode("ascii")
    return s.rstrip("=") if strip_pad else s


# ---- 케이스 생성 ------------------------------------------------------
def _single(s: str):
    yield "utf8>cp949", misread(s, "utf-8", "cp949")
    yield "cp949>latin1", misread(s, "cp949", "latin-1")
    yield "cp949>cp1252", misread(s, "cp949", "cp1252")
    yield "utf8>latin1", misread(s, "utf-8", "latin-1")
    yield "utf8>cp1252", misread(s, "utf-8", "cp1252")
    yield "url_utf8", url(s)
    yield "url_utf8_plus", url(s, plus=True)
    yield "url_cp949", url(s, "cp949")
    yield "escape", escape(s)
    yield "escape_upper", escape(s, upper=True)
    yield "entity_dec", entity(s)
    yield "entity_hex", entity(s, hexa=True)
    yield "base64_utf8", b64(s)
    yield "base64_cp949", b64(s, "cp949")
    yield "base64_urlsafe_nopad", b64(s, urlsafe=True, strip_pad=True)


def _double(s: str):
    m = misread(s, "utf-8", "cp949")
    if m is not None:
        yield "url(utf8>cp949)", url(m)
        yield "escape(utf8>cp949)", escape(m)
    yield "url(cp949>latin1)", url(misread(s, "cp949", "latin-1"))
    yield "url(url)", url(url(s))
    yield "base64(url)", b64(url(s))
    yield "utf8>latin1 x2", misread(misread(s, "utf-8", "latin-1"), "utf-8", "latin-1")
    yield "entity(cp949>latin1)", entity(misread(s, "cp949", "latin-1"))


def _triple(s: str):
    m = misread(s, "utf-8", "cp949")
    if m is not None:
        yield "base64(url(utf8>cp949))", b64(url(m))
        yield "url(url(utf8>cp949))", url(url(m))
    yield "url(url(url))", url(url(url(s)))


WRAPS = [
    ("ERROR userNm=", " id=1004"),
    ("[INFO] title: ", ""),
    ("", " (code=500)"),
    ("msg=\"", "\" at line 12"),
]


def lossless_cases(sentences: list[str] | None = None) -> list[Case]:
    sentences = sentences or load_corpus()
    rng = random.Random(1004)
    cases: list[Case] = []
    for s in sentences:
        for gen, depth in ((_single, 1), (_double, 2), (_triple, 3)):
            for kind, broken in gen(s):
                if broken is None or broken == s:
                    continue
                cases.append(Case(broken, s, kind, meta={"depth": depth}))
        # 섞인 입력: 영문 로그 접두/접미 + 깨진 한글
        pre, post = rng.choice(WRAPS)
        for kind in ("utf8>cp949", "cp949>latin1", "url_utf8", "escape"):
            broken = dict(_single(s))[kind]
            if broken is not None:
                cases.append(Case(pre + broken + post, pre + s + post, "mixed:" + kind,
                                  meta={"prefix": pre, "suffix": post}))
    return cases


def lossy_cases(sentences: list[str] | None = None) -> list[Case]:
    """errors=replace로 바이트를 잃게 만든 케이스. '?'로 대체된 변형도 만든다."""
    sentences = sentences or load_corpus()
    cases: list[Case] = []
    for s in sentences:
        for src, as_enc, kind in (("utf-8", "cp949", "utf8>cp949"), ("cp949", "utf-8", "cp949>utf8")):
            try:
                s.encode(src).decode(as_enc)
                continue                  # 손실 없이 읽히면 손실 케이스가 아니다
            except UnicodeDecodeError:
                pass
            broken, lost = lossy_misread(s, src, as_enc)
            if lost == 0:
                continue
            cases.append(Case(broken, s, "lossy:" + kind, True, lost))
            if as_enc == "cp949":     # Java는 \ufffd를 다시 MS949로 쓸 때 '?'로 바꾼다
                cases.append(Case(broken.replace("\ufffd", "?"), s, "lossy?:" + kind, True, lost))
    return cases


if __name__ == "__main__":
    import collections
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ll, ly = lossless_cases(), lossy_cases()
    for name, cs in (("손실 없음", ll), ("손실", ly)):
        cnt = collections.Counter(c.kind for c in cs)
        print(f"== {name}: {len(cs)}건")
        for k, v in sorted(cnt.items()):
            ex = next(c for c in cs if c.kind == k)
            print(f"  {k:28s} {v:4d}  {ex.input[:50]!r}")
