"""화면 없이 실행.

  python -m app.cli import <zip>...      zip 가져오기
  python -m app.cli collect              Claude Code 세션 수집
  python -m app.cli reindex              보관 폴더와 색인 대조
  python -m app.cli rebuild-index        색인 다시 만들기
  python -m app.cli rebuild              원본에서 전부 다시 변환
  python -m app.cli search <검색어>       검색
  python -m app.cli status               상태 보기
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import Core
from .index import connect, fts5_available
from .search import Searcher


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="thought-searcher")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import")
    p.add_argument("paths", nargs="+")
    p.add_argument("--force", action="store_true")
    sub.add_parser("collect")
    sub.add_parser("reindex")
    sub.add_parser("rebuild-index")
    sub.add_parser("rebuild")
    sub.add_parser("status")
    p = sub.add_parser("search")
    p.add_argument("query", nargs="*")
    p.add_argument("-n", type=int, default=10)
    a = ap.parse_args(argv)

    if not fts5_available():
        print("이 Python의 sqlite3에 FTS5가 없습니다. python.org 배포판 Python 3.10 이상을 쓰세요.", file=sys.stderr)
        return 2
    core = Core()
    if a.cmd in ("import", "collect", "rebuild") and not core.archive_ok():
        print(f"보관 폴더가 없습니다: {core.archive_dir or '(설정 안 됨)'} (config.json의 archive_dir)", file=sys.stderr)
        return 1
    if a.cmd == "import":
        for path in a.paths:
            out = core.import_zip(Path(path), force=a.force)
            print(f"{path}: {out.result} {out.counts} {out.reason}".rstrip())
    elif a.cmd == "collect":
        r = core.collect_code()
        print(f"복사 {r.copied}, 새로 {r.new}, 바뀜 {r.changed}, 그대로 {r.same}, 원본 없음 {r.missing}")
    elif a.cmd == "reindex":
        r = core.sync_index()
        print(r)
    elif a.cmd == "rebuild-index":
        print(core.rebuild_index())
    elif a.cmd == "rebuild":
        print(core.rebuild_all())
    elif a.cmd == "status":
        print(core.status_text())
    elif a.cmd == "search":
        core.sync_index()
        conn = connect(core.store.index_path)
        s = Searcher(conn, core.config.get("weights"), int(core.config.get("max_results", 50)))
        hits = s.search(" ".join(a.query), a.n)
        for i, h in enumerate(hits, 1):
            m = h.matches[0] if h.matches else None
            print(f"{i:2}. [{h.source}] {h.title} | {h.project} | {h.updated:%Y-%m-%d} | {h.score:.2f}"
                  f"{' (원본 없음)' if h.status == 'missing' else ''}")
            if m:
                print(f"    {m.preview[:100]}  [{h.path.name}:{m.line_no}] {len(h.matches)}/{h.match_total}")
        print(f"({len(hits)}건, {s.last_ms:.0f}ms)")
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
