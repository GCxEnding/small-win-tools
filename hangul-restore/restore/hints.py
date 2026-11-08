"""복원 경로 -> 원인 힌트 (규칙 파일 hints.json)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HINTS_PATH = Path(__file__).resolve().parent.parent / "defaults" / "hints.json"


@dataclass(frozen=True)
class Rule:
    steps: frozenset[str]
    hint: str
    min_count: int = 1

    def matches(self, path: tuple[str, ...] | list[str]) -> bool:
        return sum(1 for p in path if p in self.steps) >= self.min_count


def parse_rules(raw) -> list[Rule]:
    """hints.json 내용 -> 규칙 목록. 형식이 틀리면 ValueError."""
    if isinstance(raw, dict):
        raw = raw.get("rules")
    if not isinstance(raw, list):
        raise ValueError("'rules' 목록이 없습니다")
    rules = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"rules[{i}]가 객체가 아닙니다")
        steps = item.get("steps")
        hint = item.get("hint")
        if isinstance(steps, str):
            steps = [steps]
        if not isinstance(steps, list) or not steps or not isinstance(hint, str) or not hint.strip():
            raise ValueError(f"rules[{i}]에 steps(목록)와 hint(문자열)가 필요합니다")
        rules.append(Rule(frozenset(map(str, steps)), hint.strip(), max(1, int(item.get("min_count", 1)))))
    return rules


_DEFAULT: list[Rule] | None = None


def default_rules() -> list[Rule]:
    global _DEFAULT
    if _DEFAULT is None:
        try:
            _DEFAULT = parse_rules(json.loads(DEFAULT_HINTS_PATH.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            _DEFAULT = []
    return _DEFAULT


def hint_for(path, rules: list[Rule] | None = None) -> str | None:
    """규칙 파일 순서대로 보고 처음 맞는 힌트. 없으면 None."""
    if not path:
        return None
    for rule in default_rules() if rules is None else rules:
        if rule.matches(path):
            return rule.hint
    return None
