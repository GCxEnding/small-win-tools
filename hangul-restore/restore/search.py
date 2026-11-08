"""복원 연산 조합 탐색 (BFS, 최대 max_depth단계).

- 같은 결과 문자열은 가장 먼저(가장 짧은 경로로) 찾은 것만 남긴다.
- 결과가 입력과 같으면 버린다.
- 오독 되돌리기(misread)는 점수가 좋아질 때만 채택한다. □가 생긴 뒤에는 더 잇지 않는다.
  URL/이스케이프/엔티티/Base64(format)는 구조를 푸는 연산이라 중간 결과의 점수가 잠시 나빠져도
  (예: URL → 寃곗옱 → 결재) 다음 단계로 넘긴다.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import decoders
from .score import LOST_MARK, score

FRONTIER_LIMIT = 24      # 단계마다 이어서 탐색할 상태 수 상한
IMPROVE_EPS = 0.01


@dataclass(frozen=True)
class Found:
    result: str
    path: tuple[str, ...]      # 연산 id
    score: float               # 경로 감산 전 점수 (prior 포함)
    prior: float = 0.0         # 경로에 쌓인 가정 감산


def bfs(text: str, input_chars: frozenset, max_depth: int = 3) -> list[Found]:
    seen: dict[str, Found] = {text: Found(text, (), score(text, input_chars))}
    frontier = [seen[text]]
    found: list[Found] = []
    root_lost = text.count(LOST_MARK)
    for _ in range(max_depth):
        nxt: list[Found] = []
        for node in frontier:
            # 손실(□)이 생긴 결과를 다시 오독 되돌리기 하면 □끼리 뭉쳐 점수만 좋아지므로 막는다
            lossy = node.result.count(LOST_MARK) > root_lost
            for dec in decoders.ordered_for(node.result):
                if lossy and dec.kind == "misread":
                    continue
                r = dec.fn(node.result)
                if r is None or r == node.result or r in seen:
                    continue
                # 점수 = 결과의 한글다움 + 지금까지 거친 가정들의 감산(prior)
                sc = score(r, input_chars) + node.prior + (dec.prior(node.result) if dec.prior else 0.0)
                if dec.kind == "misread" and sc <= node.score + IMPROVE_EPS:
                    continue
                f = Found(r, node.path + (dec.id,), sc, sc - score(r, input_chars))
                seen[r] = f
                found.append(f)
                nxt.append(f)
        if not nxt:
            break
        nxt.sort(key=lambda f: f.score, reverse=True)
        frontier = nxt[:FRONTIER_LIMIT]
    return found
