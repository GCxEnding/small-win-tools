"""0건 안내: 결과가 없을 때 조건을 하나씩 빼 보고 가장 많이 나오는 조건 하나를 알려 준다 (UI 의존 없음).

조건 종류: source(출처 칩, src:) / period(기간 칩, after: before:) / project(프로젝트 칩, proj:) /
mine(내 질문 칩, by:me) / exclude(-제외어). 수만 세므로 Hit를 만들지 않는다 (Searcher.count_query).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .hangul import NJONG, SBASE, fix_layout, found_message, is_syllable
from .query import Query, parse
from .search import Hit, Searcher

ORDER = ("source", "period", "project", "mine", "exclude")
NAME = {"source": "출처", "period": "기간", "project": "프로젝트", "mine": "내 질문", "exclude": "제외어",
        "all": "모든 조건"}


def present(q: Query) -> list[str]:
    """검색어에 걸려 있는 조건 종류 (칩이 붙인 토큰도 포함)."""
    have = {
        "source": bool(q.sources), "period": bool(q.after or q.before), "project": bool(q.projects),
        "mine": q.by_me, "exclude": bool(q.excludes or q.title_excludes),
    }
    return [k for k in ORDER if have[k]]


def without(q: Query, kinds) -> Query:
    kinds = set(kinds)
    cut = {}
    if "source" in kinds:
        cut["sources"] = []
    if "period" in kinds:
        cut.update(after=None, before=None)
    if "project" in kinds:
        cut["projects"] = []
    if "mine" in kinds:
        cut["by_me"] = False
    if "exclude" in kinds:
        cut.update(excludes=[], title_excludes=[])
    return replace(q, **cut)


def eul_reul(word: str) -> str:
    """'을' 또는 '를' (마지막 글자의 받침 유무)."""
    ch = word[-1:]
    if ch and is_syllable(ch) and (ord(ch) - SBASE) % NJONG:
        return "을"
    return "를"


@dataclass
class ZeroHint:
    kind: str       # ORDER 중 하나 또는 "all"
    count: int

    @property
    def name(self) -> str:
        return NAME[self.kind]

    @property
    def text(self) -> str:
        return f"{self.name}{eul_reul(self.name)} 제외하면 {self.count}건입니다"


def zero_hint(searcher: Searcher, q: Query) -> ZeroHint | None:
    """조건을 하나씩 빼 센다. 가장 많이 나오는 조건(같으면 ORDER 앞쪽), 모두 0이면 조건을 전부 뺀 수.
    조건이 없거나 다 빼도 0건이면 None."""
    kinds = present(q)
    if not kinds:
        return None
    counts = [(searcher.count_query(without(q, [k])), -i, k) for i, k in enumerate(kinds)]
    best = max(counts)
    if best[0] > 0:
        return ZeroHint(best[2], best[0])
    if len(kinds) > 1:
        n = searcher.count_query(without(q, kinds))
        if n > 0:
            return ZeroHint("all", n)
    return None


@dataclass
class Outcome:
    hits: list[Hit] = field(default_factory=list)
    note: str = ""                    # 한영 보정으로 찾았을 때 '… 찾았습니다'
    hint: ZeroHint | None = None      # 끝내 0건일 때 조건 안내


def search_all(searcher: Searcher, text: str, sort: str = "relevance") -> Outcome:
    """검색 -> (0건이고 단어가 있으면) 한영 자판 오타 보정 -> (그래도 0건이면) 0건 안내.
    보정과 안내는 0건일 때만 한다. 검색칸 글자는 바뀌지 않는다 (고친 낱말로 다시 찾을 뿐)."""
    q = parse(text)
    hits = searcher.search(text, sort=sort)
    out = Outcome(hits)
    if not hits and q.has_text:
        fix = fix_layout(text)
        if fix:
            again = searcher.search(fix[0], sort=sort)
            if again:
                return Outcome(again, found_message(fix[1]))
    if not out.hits:
        out.hint = zero_hint(searcher, q)
    return out
