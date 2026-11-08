"""디버그용: python -m restore "寃곗옱"  (인자가 없으면 표준 입력을 읽는다)"""
from __future__ import annotations

import sys
import time

from .core import analyze


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if argv:
        text = " ".join(argv)
    else:
        sys.stdin.reconfigure(encoding="utf-8")
        text = sys.stdin.read().rstrip("\r\n")
    t0 = time.perf_counter()
    a = analyze(text)
    ms = (time.perf_counter() - t0) * 1000
    if a.notice:
        print(f"[안내] {a.notice}")
    if a.status:
        print(f"[{a.status}]")
    for i, c in enumerate(a.candidates, 1):
        labels = f" [{', '.join(c.labels)}]" if c.labels else ""
        print(f"{i}. {c.result}{labels}")
        print(f"   경로: {c.path_text}   점수: {c.score:.2f}")
        for d in c.details:
            print(f"   - {d}")
        if c.hint:
            print(f"   힌트: {c.hint}")
    print(f"({ms:.0f}ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
