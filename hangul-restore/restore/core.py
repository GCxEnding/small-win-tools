"""복원 진입점: 구간별 탐색 + 전체 탐색 후보를 모아 점수순으로 돌려준다."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import decoders
from .hints import Rule, hint_for
from .score import PATH_PENALTY, count_lost, loss_labels, mark_lost, score
from .search import bfs
from .segment import Segment, find_segments, trimmed

DEFAULT_CONFIG = {
    "max_depth": 3,
    "max_candidates": 5,
    "max_input_chars": 20000,
}
WHOLE_PENALTY = 0.05       # 동점이면 구간별 복원(정상 구간을 건드리지 않은 쪽)을 앞에 둔다
SEGMENT_OPTIONS = 4        # 구간마다 남겨 둘 후보 수
MIX_PENALTY = 1.0          # 구간마다 다른 복원 경로를 섞을 때 (경로 종류 하나 늘 때마다)
MSG_NOT_BROKEN = "깨진 부분을 찾지 못했습니다"
MSG_NO_CANDIDATE = "복원 후보를 찾지 못했습니다"
MSG_ONLY_WORSE = "원문보다 나은 후보를 찾지 못했습니다 (아래 후보는 참고용)"
MSG_EMPTY = "입력이 비어 있습니다"


@dataclass
class Candidate:
    result: str
    score: float
    path: list[str]                      # 사람이 읽는 경로 (연산 이름)
    lost_chars: int = 0
    labels: list[str] = field(default_factory=list)
    hint: str | None = None
    path_ids: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)   # 구간별 복원 내역
    is_original: bool = False

    @property
    def path_text(self) -> str:
        return " → ".join(self.path) if self.path else "(변환 없음)"


@dataclass
class Analysis:
    text: str                            # 실제로 처리한 입력 (길면 잘림)
    candidates: list[Candidate]
    status: str | None = None            # "깨진 부분을 찾지 못했습니다" 등
    notice: str | None = None            # 입력이 잘렸다는 안내 등
    segments: list[Segment] = field(default_factory=list)


@dataclass
class _Entry:
    score: float
    path: tuple[str, ...]
    details: list[str]
    original: bool = False


def _elide(s: str, n: int = 24) -> str:
    s = s.replace("\r", "").replace("\n", "⏎")
    return s if len(s) <= n else s[: n - 1] + "…"


def _labels(path: tuple[str, ...]) -> list[str]:
    return [decoders.BY_ID[p].label if p in decoders.BY_ID else p for p in path]


def _config(config) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(config, dict):
        cfg.update(config)
    for key, lo in (("max_depth", 1), ("max_candidates", 1), ("max_input_chars", 100)):
        try:
            cfg[key] = max(lo, int(cfg[key]))
        except (TypeError, ValueError):
            cfg[key] = DEFAULT_CONFIG[key]
    return cfg


def analyze(text: str, config=None) -> Analysis:
    cfg = _config(config)
    rules: list[Rule] | None = cfg.get("hint_rules")
    if not text:
        return Analysis(text, [], MSG_EMPTY)
    notice = None
    if len(text) > cfg["max_input_chars"]:
        text = text[: cfg["max_input_chars"]]
        notice = f"입력이 길어 앞 {cfg['max_input_chars']:,}자만 처리했습니다"
    depth = cfg["max_depth"]
    input_chars = frozenset(text)
    base = score(text, input_chars)

    pool: dict[str, _Entry] = {text: _Entry(base, (), [], True)}

    def offer(result: str, sc: float, path: tuple[str, ...], details: list[str]) -> None:
        cur = pool.get(result)
        if cur is None or (not cur.original and sc > cur.score + 1e-9):
            pool[result] = _Entry(sc, path, details)

    # ---- 구간별 ----------------------------------------------------------
    segs = find_segments(text)
    cache: dict[str, list[tuple[str, tuple[str, ...], float]]] = {}

    def options(sub: str):
        if sub in cache:
            return cache[sub]
        opts = {sub: ((), score(sub, input_chars))}

        def add(r: str, path: tuple[str, ...], sc: float) -> None:
            sc -= PATH_PENALTY * len(path)
            if r not in opts or sc > opts[r][1]:
                opts[r] = (path, sc)

        for f in bfs(sub, input_chars, depth):
            add(f.result, f.path, f.score)
        tr = trimmed(sub)
        if tr:
            a, b = tr
            edge = score(sub[:a], input_chars) + score(sub[b:], input_chars)
            for f in bfs(sub[a:b], input_chars, depth):
                add(sub[:a] + f.result + sub[b:], f.path, f.score + edge)
        ranked = sorted(((r, p, s) for r, (p, s) in opts.items()), key=lambda x: (-x[2], len(x[1])))
        cache[sub] = ranked[:SEGMENT_OPTIONS]
        return cache[sub]

    seg_opts = [options(s.text(text)) for s in segs]

    seg_base = [score(s.text(text), input_chars) for s in segs]

    def combine(choice: list[int]) -> None:
        parts, pos, details = [], 0, []
        dominant, gain_max = (), float("-inf")
        total = base
        paths = set()
        for seg, opts, k, sb in zip(segs, seg_opts, choice, seg_base):
            r, path, sc = opts[k]
            parts.append(text[pos:seg.start])
            parts.append(r)
            pos = seg.end
            if path:
                paths.add(path)
                details.append(f"'{_elide(seg.text(text))}' → '{_elide(mark_lost(r))}' : {' → '.join(_labels(path))}")
                gain = sc + PATH_PENALTY * len(path) - sb       # 경로 감산은 아래에서 한 번만
                total += gain
                if gain > gain_max:
                    dominant, gain_max = path, gain
        if not dominant:
            return
        parts.append(text[pos:])
        # 한 줄 안의 깨짐은 대개 원인이 하나다. 구간마다 다른 경로를 쓰면 감산한다.
        total -= PATH_PENALTY * len(dominant) + MIX_PENALTY * (len(paths) - 1)
        offer("".join(parts), total, dominant, details if len(details) > 1 else [])

    if segs:
        best = [0] * len(segs)
        combine(best)
        # 같은 경로로 통일한 조합 (구간별 1위가 서로 다른 가정을 섞었을 때 대비)
        for path in {p for opts in seg_opts for _, p, _ in opts if p}:
            choice = []
            for opts in seg_opts:
                idx = next((k for k, (_, p, _) in enumerate(opts) if p == path), None)
                if idx is None:
                    idx = next(k for k, (_, p, _) in enumerate(opts) if not p) if any(not p for _, p, _ in opts) else 0
                choice.append(idx)
            combine(choice)
        # 대안: 구간 하나씩 차선 후보로 바꿔 본다 (1위가 틀릴 때 대비)
        alts = [(opts[0][2] - opts[1][2], i) for i, opts in enumerate(seg_opts) if len(opts) > 1]
        for _, i in sorted(alts)[: cfg["max_candidates"] * 2]:
            for k in range(1, len(seg_opts[i])):
                choice = list(best)
                choice[i] = k
                combine(choice)

    # ---- 전체를 한 덩어리로 ----------------------------------------------
    if not (len(segs) == 1 and segs[0].start == 0 and segs[0].end == len(text)):
        for f in bfs(text, input_chars, depth):
            offer(f.result, f.score - PATH_PENALTY * len(f.path) - WHOLE_PENALTY, f.path, [])

    # ---- 정리 ------------------------------------------------------------
    ranked = sorted(pool.items(), key=lambda kv: (-kv[1].score, not kv[1].original, len(kv[1].path)))
    cands: list[Candidate] = []
    for result, e in ranked[: cfg["max_candidates"]]:
        if e.original:
            cands.append(Candidate(result, e.score, [], 0, ["원문"], None, [], [], True))
            continue
        shown = mark_lost(result)
        lost = count_lost(shown, text)
        cands.append(Candidate(shown, e.score, _labels(e.path), lost, loss_labels(lost, shown),
                               hint_for(e.path, rules), list(e.path), e.details))
    status = None
    if cands and cands[0].is_original:
        if not segs:
            status = MSG_NOT_BROKEN
        else:
            status = MSG_ONLY_WORSE if len(cands) > 1 else MSG_NO_CANDIDATE
    return Analysis(text, cands, status, notice, segs)


def restore(text: str, config=None) -> list[Candidate]:
    return analyze(text, config).candidates
