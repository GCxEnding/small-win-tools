"""검색과 순위 (UI 의존 없음)."""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .query import Query, Term, parse
from .timeutil import local_tz, parse_iso
from .tokenize import is_cjk, normalize

DEFAULT_WEIGHTS = {"title": 10.0, "body": 1.0, "same_message_bonus": 0.3, "recency": 0.2,
                   "recency_half_life_days": 180}
MAX_MATCHES = 50
PREVIEW_LEN = 160
PREVIEW_LEAD = 40


@dataclass
class MatchedMessage:
    ordinal: int
    line_no: int
    preview: str
    highlights: list[tuple[int, int]]
    message_id: int = 0
    hits: int = 0


@dataclass
class Hit:
    conv_id: str
    path: Path
    title: str
    source: str
    project: str
    updated: datetime | None
    status: str
    score: float
    matches: list[MatchedMessage] = field(default_factory=list)
    match_total: int = 0
    title_highlights: list[tuple[int, int]] = field(default_factory=list)


def term_regex(term_text: str, prefix: bool) -> re.Pattern | None:
    """강조용 정규식. 한글 사이 공백은 있어도 없어도 맞는다."""
    chars: list[tuple[str, bool]] = []   # (글자, 앞에 구분 문자가 있었나)
    gap = False
    for c in normalize(term_text):
        if c.isalnum() or c == "_" or is_cjk(c):
            chars.append((c, gap))
            gap = False
        else:
            gap = True
    if not chars:
        return None
    parts = []
    for i, (c, _g) in enumerate(chars):
        if i:
            prev = chars[i - 1][0]
            if is_cjk(prev) and is_cjk(c):
                parts.append(r"\s*")
            elif chars[i][1] or is_cjk(prev) != is_cjk(c):
                parts.append(r"[\W_]*?")
        parts.append(re.escape(c))
    pat = "".join(parts)
    if prefix:
        pat += r"\w*"
    try:
        return re.compile(pat, re.IGNORECASE)
    except re.error:
        return None


def find_spans(text: str, regs: list[re.Pattern]) -> list[tuple[int, int]]:
    spans = []
    for r in regs:
        for m in r.finditer(text):
            if m.end() > m.start():
                spans.append((m.start(), m.end()))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def make_preview(text: str, body_line: int, regs: list[re.Pattern]) -> tuple[str, list[tuple[int, int]], int]:
    """본문에서 처음 맞은 줄을 미리보기로. (미리보기, 강조 구간, md 줄 번호)"""
    lines = text.split("\n")
    pick = None
    for i, line in enumerate(lines):
        if regs and find_spans(line, regs):
            pick = i
            break
    if pick is None:
        pick = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
    line = lines[pick] if lines else ""
    spans = find_spans(line, regs) if regs else []
    start = 0
    if spans and spans[0][0] > PREVIEW_LEAD:
        start = spans[0][0] - PREVIEW_LEAD
    raw = line[start:start + PREVIEW_LEN]
    lead = len(raw) - len(raw.lstrip())
    preview = raw.strip()
    if start > 0:
        preview = "…" + preview
        shift = start + lead - 1
    else:
        shift = start + lead
    hl = [(max(0, s - shift), min(len(preview), e - shift)) for s, e in spans
          if e - shift > 0 and s - shift < len(preview)]
    return preview, hl, body_line + pick


def _any_in(sorted_ids: list[int], lo: int, hi: int) -> bool:
    i = bisect_left(sorted_ids, lo)
    return i < len(sorted_ids) and sorted_ids[i] <= hi


class Searcher:
    def __init__(self, conn: sqlite3.Connection, weights: dict | None = None, max_results: int = 50,
                 now=None):
        self.conn = conn
        self.w = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.max_results = max_results
        self._now = now
        self.last_ms = 0.0
        self.last_query: Query | None = None
        self._cache: dict[str, list[int]] = {}
        self._cache_ver = None

    def now(self) -> datetime:
        return self._now() if self._now else datetime.now(timezone.utc)

    # ---- 후보 -----------------------------------------------------------
    def _filters(self, q: Query) -> tuple[str, list]:
        sql, args = [], []
        if q.sources:
            sql.append(f"d.source IN ({','.join('?' * len(q.sources))})")
            args += q.sources
        for p in q.projects:
            sql.append("instr(d.project_norm, ?) > 0")
            args.append(p)
        tz = local_tz()
        if q.after:
            sql.append("d.updated_ts >= ?")
            args.append(datetime(q.after.year, q.after.month, q.after.day, tzinfo=tz).timestamp())
        if q.before:
            sql.append("d.created < ?")
            # created는 ISO 문자열(시간대 포함). 비교를 위해 시각으로 바꾼 updated_ts 대신 문자열 날짜를 쓴다
            args.append(q.before.isoformat())
        for t in q.title_terms:
            sql.append("instr(d.title_norm, ?) > 0")
            args.append(t)
        for t in q.title_excludes:
            sql.append("instr(d.title_norm, ?) = 0")
            args.append(t)
        if q.excludes:
            sql.append("d.id NOT IN (SELECT rowid FROM conv_fts WHERE conv_fts MATCH ?)")
            args.append(q.exclude_expr())
        return (" AND ".join(sql), args)

    def search(self, text: str, limit: int | None = None) -> list[Hit]:
        t0 = time.perf_counter()
        q = parse(text)
        self.last_query = q
        limit = limit or self.max_results
        fsql, fargs = self._filters(q)
        where = f" AND {fsql}" if fsql else ""
        if q.terms:
            slim = self.conn.execute(
                f"""SELECT d.id, d.updated_ts, d.msg_first, d.msg_last, -bm25(conv_fts, ?, ?)
                    FROM conv_fts JOIN docs d ON d.id = conv_fts.rowid
                    WHERE conv_fts MATCH ?{where}""",
                [self.w["title"], self.w["body"], q.fts_expr(), *fargs]).fetchall()
            ranked = self._rank(slim, q, limit)
            full = {r[0]: r for r in self.conn.execute(
                f"""SELECT d.id, d.conv_id, d.path, d.title, d.source, d.project, d.updated, d.status,
                           d.updated_ts, d.msg_first, d.msg_last FROM docs d
                    WHERE d.id IN ({",".join("?" * len(ranked))})""", [r[0] for r, _s in ranked])}
            hits = [(full[r[0]], sc) for r, sc in ranked if r[0] in full]
        else:
            rows = self.conn.execute(
                f"""SELECT d.id, d.conv_id, d.path, d.title, d.source, d.project, d.updated, d.status,
                           d.updated_ts, d.msg_first, d.msg_last, 0.0
                    FROM docs d WHERE 1=1{where} ORDER BY d.updated_ts DESC LIMIT ?""",
                [*fargs, limit]).fetchall()
            hits = [(r, 0.0) for r in rows]
        out = [self._make_hit(r, score, q) for r, score in hits]
        self.last_ms = (time.perf_counter() - t0) * 1000
        return out

    def _rank(self, rows, q: Query, limit: int):
        if not rows:
            return []
        now = self.now().timestamp()
        half = max(1.0, float(self.w["recency_half_life_days"])) * 86400
        rec_w = float(self.w["recency"])
        bonus_w = float(self.w["same_message_bonus"])

        def base(r):
            age = max(0.0, now - (r[1] or 0))
            return r[4] * (1 + rec_w * math.pow(0.5, age / half))

        scored = sorted(((base(r), r) for r in rows), key=lambda x: -x[0])
        same: set[int] = set()
        if len(q.terms) >= 2 and bonus_w > 0:
            # 모든 단어가 한 메시지에 같이 나오는 대화: 메시지 색인을 한 번 훑고 대화 범위로 나눈다
            both = self._rowids(q.fts_expr())
            if both:
                for _s, r in scored:
                    if r[2] is not None and _any_in(both, r[2], r[3]):
                        same.add(r[0])
        final = sorted(((s * (1 + (bonus_w if r[0] in same else 0)), r) for s, r in scored),
                       key=lambda x: -x[0])
        return [(r, s) for s, r in final[:limit]]

    # ---- 결과 만들기 ----------------------------------------------------
    def _make_hit(self, r, score: float, q: Query) -> Hit:
        regs = [x for x in (term_regex(t.text, t.prefix) for t in q.terms) if x]
        regs += [re.compile(re.escape(t), re.IGNORECASE) for t in q.title_terms]
        hit = Hit(conv_id=r[1], path=Path(r[2]), title=r[3], source=r[4], project=r[5],
                  updated=parse_iso(r[6]), status=r[7], score=score)
        hit.title_highlights = find_spans(hit.title, regs)
        doc_id, first, last = r[0], r[9], r[10]
        if first is None:
            return hit
        counts: dict[int, int] = {}
        for t in q.terms:
            ids = self._rowids(t.fts())
            for mid in ids[bisect_left(ids, first):bisect_right(ids, last)]:
                counts[mid] = counts.get(mid, 0) + 1
        hit.match_total = len(counts)
        if counts:
            order = sorted(counts, key=lambda mid: (-counts[mid], mid))[:MAX_MATCHES]
        else:
            order = [first]
        rows = {m[0]: m for m in self.conn.execute(
            f"SELECT id, ordinal, line_no, body_line, text FROM messages WHERE id IN ({','.join('?' * len(order))})",
            order)}
        for mid in order:
            m = rows.get(mid)
            if not m:
                continue
            preview, hl, line = make_preview(m[4], m[3], regs)
            hit.matches.append(MatchedMessage(ordinal=m[1], line_no=line, preview=preview, highlights=hl,
                                              message_id=mid, hits=counts.get(mid, 0)))
        return hit

    def _rowids(self, expr: str) -> list[int]:
        """FTS 식에 맞는 메시지 rowid(오름차순). 색인이 바뀌지 않았으면 캐시를 쓴다."""
        ver = self.conn.execute("PRAGMA data_version").fetchone()[0]
        if ver != self._cache_ver:
            self._cache.clear()
            self._cache_ver = ver
        ids = self._cache.get(expr)
        if ids is None:
            ids = [r[0] for r in self.conn.execute("SELECT rowid FROM msg_fts WHERE msg_fts MATCH ?", (expr,))]
            if len(self._cache) >= 32:
                self._cache.pop(next(iter(self._cache)))
            self._cache[expr] = ids
        return ids

    def message_text(self, message_id: int) -> str:
        row = self.conn.execute("SELECT text FROM messages WHERE id=?", (message_id,)).fetchone()
        return row[0] if row else ""


def search(query: str, limit: int = 50, db_path: Path | None = None, weights: dict | None = None) -> list[Hit]:
    """한 번 쓰고 버리는 검색 (CLI, 테스트용)."""
    from .index import connect
    conn = connect(Path(db_path)) if db_path else None
    if conn is None:
        raise ValueError("db_path가 필요합니다")
    try:
        return Searcher(conn, weights, limit).search(query, limit)
    finally:
        conn.close()

