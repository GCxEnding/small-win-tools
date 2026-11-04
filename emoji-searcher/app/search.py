"""검색과 정렬. UI에 의존하지 않으므로 화면 없이 테스트할 수 있다.

점수 구조 (단어 하나당)
  매칭 품질: 정확 일치 100 > 앞부분 일치 60 > 단어 경계 일치 50 > 부분 포함 30   (초성 매칭은 0.9배)
  출처 가산: 개인 태그 +15, 이름 +8, AI 태그 +5(+앞쪽 태그일수록 최대 +4), CLDR 키워드 +4
  보정: 두 출처 이상에 같은 말 +1, 성별 변형 -3, 그룹 동점 깨기 최대 +0.5
  사용 기록 가산: 최대 +14 (횟수 최대 8 + 최근성 최대 6)

  정확 일치의 최저점(100 - 3 - 1 = 96)은 부분 포함의 최고점(30 + 15 + 1 + 0.5 + 14 = 60.5)보다
  훨씬 높으므로, 사용 기록이 아무리 많아도 정확 일치가 항상 부분 포함보다 위에 온다.
"""
from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import hangul

EXACT, PREFIX, WORD_PREFIX, CONTAINS = 100.0, 60.0, 50.0, 30.0
CHOSEONG_FACTOR = 0.9
BONUS = {"user": 15.0, "name": 8.0, "tag": 5.0, "keyword": 4.0}
TAG_POS_MAX = 4.0          # AI 태그 순서 가산: 첫 태그 +4, 둘째 +3 ... (최대 5+4=9 < 개인 태그 15)
MULTI_SOURCE_BONUS = 1.0   # 같은 말이 CLDR 키워드와 AI 태그 등 두 곳 이상에 있으면 +1
VARIANT_PENALTY = 3.0      # 성별 변형(👨‍🔬, 🙋‍♀️ 등)은 기본형보다 아래로
USAGE_COUNT_MAX, USAGE_RECENT_MAX, RECENT_HALF_DAYS = 8.0, 6.0, 14.0
# 점수가 같을 때만 의미 있는 아주 작은 가산: 노트 제목 표시로 자주 쓰는 그룹을 앞으로
GROUP_TIEBREAK = {"Symbols": 0.5, "Objects": 0.4, "Travel & Places": 0.3, "Activities": 0.2}

_GENDER_SIGNS = ("♀", "♂")
_MAN_WOMAN = ("\U0001F468", "\U0001F469")


def _is_variant(emoji: str) -> bool:
    if "‍" not in emoji:
        return False
    return any(s in emoji for s in _GENDER_SIGNS) or emoji.startswith(_MAN_WOMAN)


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "emoji_tags.json"


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


@dataclass
class Result:
    emoji: str
    name_ko: str
    name_en: str
    score: float
    matched: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class _Entry:
    emoji: str
    name_ko: str
    name_en: str
    group: str
    order: int
    tags_ko: list[str]


def load_entries(path: Path = DATA_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _match_tier(q: str, term: str) -> float:
    if term == q:
        return EXACT
    if term.startswith(q):
        return PREFIX
    pos = term.find(q)
    if pos < 0:
        return 0.0
    if term[pos - 1] in " -_:":
        return WORD_PREFIX
    return CONTAINS


class Searcher:
    def __init__(self, entries: list[dict], user_tags: dict | None = None,
                 usage: dict | None = None, now: datetime | None = None):
        self._base_entries = entries
        self._now = now
        self.usage: dict = usage or {}
        self.set_user_tags(user_tags or {})

    # ---- index --------------------------------------------------------
    def set_user_tags(self, user_tags: dict) -> None:
        self.user_tags = {unicodedata.normalize("NFC", k): v for k, v in user_tags.items()}
        self._build()

    def set_usage(self, usage: dict) -> None:
        self.usage = usage

    def _build(self) -> None:
        entries: list[_Entry] = []
        by_emoji: dict[str, int] = {}
        # term -> {entry_idx: [bonus, display, kinds]}
        raw_index: dict[str, dict[int, list]] = {}

        def add(idx: int, raw: str, kind: str, extra: float = 0.0) -> None:
            t = normalize(raw)
            if not t:
                return
            slot = raw_index.setdefault(t, {})
            bonus = BONUS[kind] + extra
            if idx not in slot:
                slot[idx] = [bonus, raw.strip(), {kind}]
            else:
                rec = slot[idx]
                rec[2].add(kind)
                if rec[0] < bonus:
                    rec[0], rec[1] = bonus, raw.strip()

        for e in self._base_entries:
            idx = len(entries)
            entries.append(_Entry(e["emoji"], e.get("name_ko", ""), e.get("name_en", ""),
                                  e.get("group", ""), idx, list(e.get("tags_ko", []))))
            by_emoji[e["emoji"]] = idx
            by_emoji.setdefault(e["emoji"].replace("️", ""), idx)
            for k in ("name_ko", "name_en"):
                add(idx, e.get(k, ""), "name")
            for t in e.get("keywords_ko", []) + e.get("keywords_en", []):
                add(idx, t, "keyword")
            # AI 태그는 앞에 둔 것일수록 핵심 연상어
            for lang in ("tags_ko", "tags_en"):
                for pos, t in enumerate(e.get(lang, [])):
                    add(idx, t, "tag", max(0.0, TAG_POS_MAX - pos))

        for emoji, words in self.user_tags.items():
            idx = by_emoji.get(emoji, by_emoji.get(emoji.replace("️", "")))
            if idx is None:
                idx = len(entries)
                entries.append(_Entry(emoji, "", "", "개인", idx, []))
                by_emoji[emoji] = idx
            for w in words:
                add(idx, w, "user")
            entries[idx].tags_ko = list(words) + [t for t in entries[idx].tags_ko if t not in words]

        index: dict[str, dict[int, tuple[float, str]]] = {}
        for t, slots in raw_index.items():
            index[t] = {}
            for idx, (bonus, display, kinds) in slots.items():
                if len(kinds) >= 2:
                    bonus += MULTI_SOURCE_BONUS
                if _is_variant(entries[idx].emoji):
                    bonus -= VARIANT_PENALTY
                bonus += GROUP_TIEBREAK.get(entries[idx].group, 0.0)
                index[t][idx] = (bonus, display)

        self._entries = entries
        self._by_emoji = by_emoji
        self._terms = list(index.items())
        self._cho_terms = [(hangul.choseong(t), t, slots) for t, slots in self._terms
                           if any(hangul.is_syllable(c) for c in t)]

    # ---- scoring ------------------------------------------------------
    def _usage_bonus(self, emoji: str) -> float:
        rec = self.usage.get(emoji)
        if not rec:
            return 0.0
        count = max(0, int(rec.get("count", 0)))
        bonus = min(USAGE_COUNT_MAX, math.log2(count + 1) * 2.0)
        try:
            last = datetime.fromisoformat(rec.get("last_used", ""))
            days = max(0.0, ((self._now or datetime.now()) - last).total_seconds() / 86400)
            bonus += USAGE_RECENT_MAX * math.exp(-days / RECENT_HALF_DAYS)
        except (TypeError, ValueError):
            pass
        return bonus

    def _score_token(self, token: str) -> dict[int, tuple[float, str]]:
        variants = [token]
        conv = hangul.latin_to_hangul(token)
        if conv and conv != token:
            variants.append(normalize(conv))
        best: dict[int, tuple[float, str]] = {}

        def offer(idx: int, score: float, display: str) -> None:
            if idx not in best or best[idx][0] < score:
                best[idx] = (score, display)

        for q in variants:
            for term, slots in self._terms:
                tier = _match_tier(q, term)
                if not tier:
                    continue
                tie = min(len(term) - len(q), 50) * 0.02
                for idx, (bonus, display) in slots.items():
                    offer(idx, tier + bonus - tie, display)
            if hangul.is_choseong_only(q):
                cq = q.replace(" ", "")
                for cho, term, slots in self._cho_terms:
                    tier = _match_tier(cq, cho)
                    if not tier:
                        continue
                    tie = min(len(cho) - len(cq), 50) * 0.02
                    for idx, (bonus, display) in slots.items():
                        offer(idx, tier * CHOSEONG_FACTOR + bonus - tie, display)
        return best

    # ---- public -------------------------------------------------------
    def recent(self, limit: int) -> list[Result]:
        def key(item):
            e, rec = item
            return (str(rec.get("last_used", "")), int(rec.get("count", 0)))

        out = []
        for emoji, rec in sorted(self.usage.items(), key=key, reverse=True):
            idx = self._by_emoji.get(emoji)
            ent = self._entries[idx] if idx is not None else None
            out.append(Result(emoji, ent.name_ko if ent else "", ent.name_en if ent else "",
                              0.0, [], (ent.tags_ko[:4] if ent else [])))
            if len(out) >= limit:
                break
        return out

    def search(self, query: str, limit: int = 30) -> list[Result]:
        q = normalize(query)
        if not q:
            return self.recent(limit)
        tokens = q.split()
        combined: dict[int, list] | None = None
        for tok in tokens:
            scored = self._score_token(tok)
            if combined is None:
                combined = {i: [s, [d]] for i, (s, d) in scored.items()}
            else:
                combined = {i: [v[0] + scored[i][0], v[1] + [scored[i][1]]]
                            for i, v in combined.items() if i in scored}
            if not combined:
                return []

        results = []
        for idx, (total, matched) in (combined or {}).items():
            ent = self._entries[idx]
            score = total / len(tokens) + self._usage_bonus(ent.emoji)
            uniq = list(dict.fromkeys(matched))
            extra = [t for t in ent.tags_ko if t not in uniq]
            results.append((score, -ent.order, Result(ent.emoji, ent.name_ko, ent.name_en, score,
                                                      uniq, (uniq + extra)[:4])))
        results.sort(key=lambda r: (r[0], r[1]), reverse=True)
        return [r[2] for r in results[:limit]]
