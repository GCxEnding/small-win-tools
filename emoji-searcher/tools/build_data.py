"""emoji_tags.json 생성 스크립트 (개발할 때만 실행).

원천
  - Unicode emoji-test.txt 의 fully-qualified 항목 (E 버전 <= --max-version, 피부색 변형 제외)
  - Unicode CLDR annotations / annotationsDerived (ko, en): 이름과 키워드
  - tools/ai_tags/*.txt: Claude가 그룹 단위로 만든 연상 태그

ai_tags 파일 형식 (한 줄에 이모지 하나, # 은 주석)
  🚀|배포,출시,릴리즈|deploy,launch,release

태그가 없는 변형(성별/가족 등)은 기본형의 태그를 물려받는다.
원천 파일은 tools/.cache/ 에 내려받아 두고 재사용한다(실행 중인 앱은 네트워크를 쓰지 않는다).

사용법
  python tools/build_data.py                  # 기본 Emoji 15.0까지
  python tools/build_data.py --max-version 14.0
  python tools/build_data.py --refresh        # 원천 파일 다시 받기
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / ".cache"
AI_TAGS_DIR = Path(__file__).resolve().parent / "ai_tags"
OUT = ROOT / "data" / "emoji_tags.json"

CLDR_VERSION = "47.0.0"
SOURCES = {
    "emoji-test.txt": "https://unicode.org/Public/emoji/latest/emoji-test.txt",
    "ko.json": f"https://cdn.jsdelivr.net/npm/cldr-annotations-full@{CLDR_VERSION}/annotations/ko/annotations.json",
    "en.json": f"https://cdn.jsdelivr.net/npm/cldr-annotations-full@{CLDR_VERSION}/annotations/en/annotations.json",
    "ko-derived.json": f"https://cdn.jsdelivr.net/npm/cldr-annotations-derived-full@{CLDR_VERSION}/annotationsDerived/ko/annotations.json",
    "en-derived.json": f"https://cdn.jsdelivr.net/npm/cldr-annotations-derived-full@{CLDR_VERSION}/annotationsDerived/en/annotations.json",
}

SKIN_TONES = {chr(c) for c in range(0x1F3FB, 0x1F400)}
ZWJ = "‍"
VS16 = "️"
FEMALE = ZWJ + "♀" + VS16
MALE = ZWJ + "♂" + VS16
MAN, WOMAN, PERSON = "\U0001F468", "\U0001F469", "\U0001F9D1"

GENDER_TAGS = {
    "f": (["여자", "여성"], ["woman", "female"]),
    "m": (["남자", "남성"], ["man", "male"]),
}

LINE_RE = re.compile(r"^([0-9A-F ]+?)\s*;\s*([a-z-]+)\s*#\s*(\S+)\s+E(\d+\.\d+)\s+(.*)$")


def fetch(refresh: bool) -> None:
    CACHE.mkdir(exist_ok=True)
    for name, url in SOURCES.items():
        path = CACHE / name
        if path.exists() and not refresh:
            continue
        print(f"download {url}")
        with urllib.request.urlopen(url, timeout=60) as r:
            path.write_bytes(r.read())


def parse_emoji_test(max_version: float) -> list[dict]:
    items = []
    group = subgroup = ""
    for line in (CACHE / "emoji-test.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("# group:"):
            group = line.split(":", 1)[1].strip()
            continue
        if line.startswith("# subgroup:"):
            subgroup = line.split(":", 1)[1].strip()
            continue
        if not line.strip() or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        cps, status, _, ver, name = m.groups()
        if status != "fully-qualified" or float(ver) > max_version:
            continue
        emoji = "".join(chr(int(c, 16)) for c in cps.split())
        if SKIN_TONES & set(emoji):
            continue
        if group == "Component":
            continue
        items.append({"emoji": emoji, "name": name.strip(), "group": group, "subgroup": subgroup})
    return items


def load_cldr(name: str) -> dict:
    data = json.loads((CACHE / name).read_text(encoding="utf-8"))
    root = data.get("annotations") or data.get("annotationsDerived")
    return root["annotations"]


def cldr_lookup(tables: list[dict], emoji: str) -> dict | None:
    keys = [emoji, emoji.replace(VS16, "")]
    for t in tables:
        for k in keys:
            if k in t:
                return t[k]
    return None


def load_ai_tags() -> dict[str, tuple[list[str], list[str]]]:
    tags: dict[str, tuple[list[str], list[str]]] = {}
    for path in sorted(AI_TAGS_DIR.glob("*.txt")):
        for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) != 3:
                sys.exit(f"{path.name}:{no}: 형식 오류 -> {raw!r}")
            emoji = unicodedata.normalize("NFC", parts[0].strip())
            ko = [t.strip() for t in parts[1].split(",") if t.strip()]
            en = [t.strip() for t in parts[2].split(",") if t.strip()]
            if emoji in tags:
                old_ko, old_en = tags[emoji]
                ko, en = old_ko + ko, old_en + en
            tags[emoji] = (ko, en)
    # 파일에는 FE0F 유무가 섞일 수 있으므로 둘 다 키로 등록
    for k in list(tags):
        tags.setdefault(k.replace(VS16, ""), tags[k])
    return tags


def base_forms(emoji: str) -> list[tuple[str, str | None]]:
    """성별 변형 -> (기본형 후보, 성별) 목록."""
    out: list[tuple[str, str | None]] = []
    gender = None
    e = emoji
    if e.endswith(FEMALE):
        e, gender = e[: -len(FEMALE)], "f"
    elif e.endswith(MALE):
        e, gender = e[: -len(MALE)], "m"
    if gender:
        out.append((e, gender))
        if not e.endswith(VS16):
            out.append((e + VS16, gender))
    if ZWJ in emoji and (emoji.startswith(MAN) or emoji.startswith(WOMAN)):
        g = "m" if emoji.startswith(MAN) else "f"
        out.append((PERSON + emoji[1:], g))
    return out


def dedup(seq):
    seen, out = set(), []
    for s in seq:
        s = unicodedata.normalize("NFC", s.strip())
        k = s.lower()
        if s and k not in seen:
            seen.add(k)
            out.append(s)
    return out


def flag_name(tts: str) -> str:
    # "깃발: 대한민국" -> "대한민국", "flag: South Korea" -> "South Korea"
    return tts.split(":", 1)[1].strip() if ":" in tts else tts


def build(max_version: float, allow_missing: bool) -> int:
    items = parse_emoji_test(max_version)
    ko_tables = [load_cldr("ko.json"), load_cldr("ko-derived.json")]
    en_tables = [load_cldr("en.json"), load_cldr("en-derived.json")]
    ai = load_ai_tags()

    out, missing, seen = [], [], set()
    for it in items:
        e = it["emoji"]
        if e in seen:
            continue
        seen.add(e)
        ko = cldr_lookup(ko_tables, e) or {}
        en = cldr_lookup(en_tables, e) or {}
        name_ko = (ko.get("tts") or [""])[0]
        name_en = (en.get("tts") or [it["name"]])[0]
        kw_ko = list(ko.get("default", []))
        kw_en = list(en.get("default", []))

        tags_ko: list[str] = []
        tags_en: list[str] = []
        if e in ai:
            tags_ko, tags_en = list(ai[e][0]), list(ai[e][1])
        else:
            for base, g in base_forms(e):
                if base in ai:
                    tags_ko, tags_en = list(ai[base][0]), list(ai[base][1])
                    if g:
                        tags_ko += GENDER_TAGS[g][0]
                        tags_en += GENDER_TAGS[g][1]
                    break

        sub = it["subgroup"]
        if sub in ("country-flag", "subdivision-flag"):
            nk, ne = flag_name(name_ko), flag_name(name_en)
            kw_ko.append(nk)
            kw_en.append(ne)
            tags_ko = [nk, f"{nk} 국기", "국기", "나라", "여행"] + tags_ko
            tags_en = [ne, f"{ne} flag", "flag", "country", "travel"] + tags_en
        elif sub == "keycap":
            k = flag_name(name_ko)
            tags_ko = [k, f"숫자 {k}" if k.isdigit() else k, "키캡", "번호"] + tags_ko
            tags_en = [k, "keycap", "number"] + tags_en
        elif sub == "family" and not tags_ko:
            tags_ko = ["가족", "가정", "부모", "아이", "육아", "집"]
            tags_en = ["family", "parents", "kids", "home", "household"]

        tags_ko, tags_en = dedup(tags_ko), dedup(tags_en)
        if not tags_ko or not tags_en:
            missing.append(f"{e} {it['group']}/{sub} {it['name']}")

        out.append({
            "emoji": e,
            "name_ko": name_ko or name_en,
            "name_en": name_en,
            "group": it["group"],
            "keywords_ko": dedup(kw_ko),
            "keywords_en": dedup(kw_en),
            "tags_ko": tags_ko,
            "tags_en": tags_en,
        })

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write("[\n")
        f.write(",\n".join(json.dumps(e, ensure_ascii=False) for e in out))
        f.write("\n]\n")
    print(f"{len(out)}개 이모지 -> {OUT.relative_to(ROOT)}")
    if missing:
        print(f"AI 태그 없는 항목 {len(missing)}개:")
        for m in missing:
            print("  " + m)
        if not allow_missing:
            return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-version", type=float, default=15.0, help="포함할 최대 Emoji 버전 (기본 15.0)")
    ap.add_argument("--refresh", action="store_true", help="원천 파일을 다시 내려받는다")
    ap.add_argument("--allow-missing", action="store_true", help="AI 태그가 빠진 항목이 있어도 성공 처리")
    args = ap.parse_args()
    fetch(args.refresh)
    return build(args.max_version, args.allow_missing)


if __name__ == "__main__":
    sys.exit(main())
