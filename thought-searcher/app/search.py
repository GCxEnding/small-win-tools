"""검색과 순위 (UI 의존 없음)."""
from __future__ import annotations

import math
import os
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
    time: datetime | None = None      # 이 메시지의 시각 (로컬 시간대). 모르면 None


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
    # 채팅 시각: 맞은 메시지 중 가장 늦은 메시지의 시각 (기간 조건이 있으면 기간 안에서).
    # 단어 없는 검색과 제목에만 맞은 대화는 대화 마지막 시각(updated_ts).
    chat_time: datetime | None = None


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


def journal_prefix(path) -> str:
    """일지 폴더 -> 색인 path와 비교할 앞부분 (소문자, \\ 구분, 끝에 \\)."""
    p = str(path or "").strip()
    if not p:
        return ""
    return os.path.abspath(p).replace("/", "\\").rstrip("\\").lower() + "\\"


class Searcher:
    def __init__(self, conn: sqlite3.Connection, weights: dict | None = None, max_results: int = 50,
                 now=None):
        self.conn = conn
        self.w = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.max_results = max_results
        self._now = now
        self.last_ms = 0.0
        self.last_query: Query | None = None
        self.journal_dir: str = ""        # src:journal(일지)이 찾는 폴더. main.py가 설정에서 넣는다
        self._cache: dict[str, list[int]] = {}
        self._cache_ver = None

    def now(self) -> datetime:
        return self._now() if self._now else datetime.now(timezone.utc)

    # ---- 후보 -----------------------------------------------------------
    @staticmethod
    def _bounds(q: Query) -> tuple[float | None, float | None]:
        """after:/before: -> (시작 포함, 끝 미포함) UTC 초. 날짜는 로컬 시간대 0시."""
        tz = local_tz()
        a = datetime(q.after.year, q.after.month, q.after.day, tzinfo=tz).timestamp() if q.after else None
        b = datetime(q.before.year, q.before.month, q.before.day, tzinfo=tz).timestamp() if q.before else None
        return a, b

    @staticmethod
    def _doc_period(q: Query) -> tuple[list[str], list]:
        """대화 단위 기간 조건: 마지막 시각(updated_ts)이 after 이후, 첫 시각(created)이 before 이전."""
        sql, args = [], []
        tz = local_tz()
        if q.after:
            sql.append("d.updated_ts >= ?")
            args.append(datetime(q.after.year, q.after.month, q.after.day, tzinfo=tz).timestamp())
        if q.before:
            sql.append("d.created < ?")
            # created는 ISO 문자열(시간대 포함). 비교를 위해 시각으로 바꾼 updated_ts 대신 문자열 날짜를 쓴다
            args.append(q.before.isoformat())
        return sql, args

    def _filters(self, q: Query, doc_period: bool = True) -> tuple[str, list]:
        """doc_period=False면 기간 조건을 뺀다 (단어가 있는 검색은 메시지 기준으로 따로 거른다)."""
        sql, args = [], []
        if q.sources:
            srcs = [s for s in q.sources if s != "journal"]
            parts = [f"d.source IN ({','.join('?' * len(srcs))})"] if srcs else []
            args += srcs
            if "journal" in q.sources:
                # 일지는 따로 색인하지 않는다: 일지 폴더 안의 노트 문서로 찾는다 (일지 폴더가 노트 폴더에 들어 있을 때)
                root = journal_prefix(self.journal_dir)
                if root:
                    parts.append("(d.source = 'note' AND instr(lower(replace(d.path, '/', '\\')), ?) = 1)")
                    args.append(root)
            sql.append("(" + " OR ".join(parts) + ")" if parts else "0")
        for p in q.projects:
            sql.append("instr(d.project_norm, ?) > 0")
            args.append(p)
        if doc_period:
            psql, pargs = self._doc_period(q)
            sql += psql
            args += pargs
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

    def search(self, text: str, limit: int | None = None, sort: str = "relevance") -> list[Hit]:
        """sort: "relevance"(순위) | "recent"(채팅 시각 늦은 순). 후보는 같고 자르기 전에 정렬만 다르다.
        단어 없는 검색은 sort와 상관없이 대화 마지막 시각 순."""
        t0 = time.perf_counter()
        recent = sort == "recent"
        q = parse(text)
        self.last_query = q
        limit = limit or self.max_results
        # 단어가 있고 기간 조건이 있으면 대화 마지막 시각 대신 맞은 메시지의 시각으로 거른다
        per_msg = bool(q.terms and (q.after or q.before))
        period = self._bounds(q) if per_msg else None
        fsql, fargs = self._filters(q, doc_period=not per_msg)
        where = f" AND {fsql}" if fsql else ""
        times: dict[int, float] | None = None
        if q.terms:
            dsql, dargs = self._doc_period(q) if per_msg else ([], [])
            # doc_ok: 대화 단위 기간 조건을 통과하나 (제목에만 맞은 대화를 거를 때만 쓴다)
            doc_ok = f", ({' AND '.join(dsql)})" if dsql else ""
            slim = self.conn.execute(
                f"""SELECT d.id, d.updated_ts, d.msg_first, d.msg_last, -bm25(conv_fts, ?, ?){doc_ok}
                    FROM conv_fts JOIN docs d ON d.id = conv_fts.rowid
                    WHERE conv_fts MATCH ?{where}""",
                [self.w["title"], self.w["body"], *dargs, q.fts_expr(), *fargs]).fetchall()
            mt = self._matched_times(q, period or (None, None)) if (per_msg or recent) else {}
            if per_msg:
                slim = self._in_period(slim, q, mt)
            if recent:
                # 채팅 시각 늦은 순 (맞은 메시지가 없는 대화는 마지막 시각). 같으면 점수 높은 쪽
                ranked = sorted(((r, r[4]) for r in slim), key=lambda x: (-mt.get(x[0][0], x[0][1] or 0.0), -x[1]))
                ranked = ranked[:limit]
            else:
                ranked = self._rank(slim, q, limit)
            full = {r[0]: r for r in self.conn.execute(
                f"""SELECT d.id, d.conv_id, d.path, d.title, d.source, d.project, d.updated, d.status,
                           d.updated_ts, d.msg_first, d.msg_last FROM docs d
                    WHERE d.id IN ({",".join("?" * len(ranked))})""", [r[0] for r, _s in ranked])}
            hits = [(full[r[0]], sc) for r, sc in ranked if r[0] in full]
            times = self._msg_times([r[0] for r, _s in hits])
        else:
            rows = self.conn.execute(
                f"""SELECT d.id, d.conv_id, d.path, d.title, d.source, d.project, d.updated, d.status,
                           d.updated_ts, d.msg_first, d.msg_last, 0.0
                    FROM docs d WHERE 1=1{where} ORDER BY d.updated_ts DESC LIMIT ?""",
                [*fargs, limit]).fetchall()
            hits = [(r, 0.0) for r in rows]
        out = [self._make_hit(r, score, q, times, period, recent) for r, score in hits]
        self.last_ms = (time.perf_counter() - t0) * 1000
        return out

    def _matched_times(self, q: Query, period) -> dict[int, float]:
        """{대화 id: 맞은 메시지(검색어 중 하나라도 들어 있는 메시지) 중 가장 늦은 시각}.
        period=(시작, 끝)이 있으면 그 안의 메시지만 센다. 맞은 메시지가 없는 대화는 들어 있지 않다."""
        lo, hi = period
        sql = ["m.id IN (SELECT rowid FROM msg_fts WHERE msg_fts MATCH ?)"]
        args: list = [" OR ".join(t.fts() for t in q.terms)]
        if lo is not None:
            sql.append("m.created_ts >= ?")
            args.append(lo)
        if hi is not None:
            sql.append("m.created_ts < ?")
            args.append(hi)
        return {d: ts for d, ts in self.conn.execute(
            f"SELECT m.doc_id, max(m.created_ts) FROM messages m WHERE {' AND '.join(sql)} GROUP BY m.doc_id", args)
            if ts is not None}

    def _in_period(self, rows, q: Query, ok: dict[int, float]) -> list:
        """맞은 메시지 중 하나 이상이 기간 안인 대화만 남긴다 (ok: _matched_times의 결과).
        맞은 메시지가 하나도 없는 대화(단어가 제목에만 맞음)는 대화 단위 조건(rows[5])으로 판단한다."""
        todo = [r for r in rows if r[0] not in ok and r[5]]
        have: set[int] = set()
        if todo:
            lists = [self._rowids(t.fts()) for t in q.terms]
            have = {r[0] for r in todo if r[2] is not None and any(_any_in(ids, r[2], r[3]) for ids in lists)}
        return [r for r in rows if r[0] in ok or (r[5] and r[0] not in have)]
    def _msg_times(self, doc_ids: list[int]) -> dict[int, float]:
        """결과로 나갈 대화들의 메시지 시각 (한 번에 가져온다). {message id: created_ts}"""
        out: dict[int, float] = {}
        for i in range(0, len(doc_ids), 400):
            part = doc_ids[i:i + 400]
            for mid, ts in self.conn.execute(
                    f"SELECT id, created_ts FROM messages WHERE doc_id IN ({','.join('?' * len(part))})", part):
                if ts is not None:
                    out[mid] = ts
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
    def _make_hit(self, r, score: float, q: Query, times: dict[int, float] | None = None,
                  period: tuple[float | None, float | None] | None = None, recent: bool = False) -> Hit:
        """times: 이 대화들의 {메시지 id: 시각} (단어 검색일 때). period: 기간이 있으면 (시작, 끝)."""
        regs = [x for x in (term_regex(t.text, t.prefix) for t in q.terms) if x]
        regs += [re.compile(re.escape(t), re.IGNORECASE) for t in q.title_terms]
        hit = Hit(conv_id=r[1], path=Path(r[2]), title=r[3], source=r[4], project=r[5],
                  updated=parse_iso(r[6]), status=r[7], score=score)
        hit.title_highlights = find_spans(hit.title, regs)
        doc_id, first, last = r[0], r[9], r[10]
        upd_ts = r[8] or 0.0
        chat_ts = upd_ts
        hit.chat_time = datetime.fromtimestamp(upd_ts, local_tz()) if upd_ts > 0 else None
        if first is None:
            return hit

        def at(mid: int) -> float:
            return times.get(mid, upd_ts) if times else upd_ts

        def inside(mid: int) -> bool:
            if not period:
                return True
            t = at(mid)
            return (period[0] is None or t >= period[0]) and (period[1] is None or t < period[1])
        counts: dict[int, int] = {}
        for t in q.terms:
            ids = self._rowids(t.fts())
            for mid in ids[bisect_left(ids, first):bisect_right(ids, last)]:
                counts[mid] = counts.get(mid, 0) + 1
        if period:
            counts = {mid: c for mid, c in counts.items() if inside(mid)}
        hit.match_total = len(counts)
        if counts:
            if recent:       # 최신순: 늦은 메시지부터 (같은 시각이면 뒤에 있는 것부터)
                order = sorted(counts, key=lambda mid: (-at(mid), -mid))[:MAX_MATCHES]
            else:
                order = sorted(counts, key=lambda mid: (-counts[mid], mid))[:MAX_MATCHES]
            chat_ts = max(at(mid) for mid in counts)
        elif period and times:
            # 제목에만 맞은 대화: 맞은 메시지가 없으니 기간 안의 첫 메시지를 보여 준다 (없으면 첫 메시지)
            order = [next((mid for mid in range(first, last + 1) if mid in times and inside(mid)), first)]
        else:
            order = [first]
        if q.terms and chat_ts > 0:
            hit.chat_time = datetime.fromtimestamp(chat_ts, local_tz())
        rows = {m[0]: m for m in self.conn.execute(
            f"SELECT id, ordinal, line_no, body_line, text FROM messages WHERE id IN ({','.join('?' * len(order))})",
            order)}
        for mid in order:
            m = rows.get(mid)
            if not m:
                continue
            preview, hl, line = make_preview(m[4], m[3], regs)
            ts = at(mid)
            hit.matches.append(MatchedMessage(ordinal=m[1], line_no=line, preview=preview, highlights=hl,
                                              message_id=mid, hits=counts.get(mid, 0),
                                              time=datetime.fromtimestamp(ts, local_tz()) if ts > 0 else None))
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

