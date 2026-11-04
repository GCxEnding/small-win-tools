"""창 제목 해석(활동 키), 제외, 마스킹. UI 의존 없음."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULTS_DIR = Path(__file__).resolve().parent.parent / "defaults"

CODE = "코드"
OTHER = "기타"
NO_PROJECT = "(프로젝트 없음)"
UNKNOWN = "(알 수 없음)"
EXCLUDED = "제외됨"

# VS Code / Kiro 가 저장 안 된 파일 앞에 붙이는 표시
_DIRTY_MARK = re.compile(r"^\s*[●•○◌*]\s*")
# en dash(U+2013), em dash(U+2014) 구분자를 ' - ' 로 통일
_DASH_SEP = re.compile(r"\s+[–—]\s+")


@dataclass(frozen=True)
class ActivityKey:
    category: str
    target: str
    file: str | None = None  # 코드 분류에서만 사용

    @property
    def label(self) -> str:
        """요약 목록용 '분류: 대상' (파일 제외)."""
        if self.category == EXCLUDED:
            return EXCLUDED
        return f"{self.category}: {self.target}"

    @property
    def flow_label(self) -> str:
        """흐름용 '분류 대상'."""
        if self.category == EXCLUDED:
            return EXCLUDED
        return f"{self.category} {self.target}"


@dataclass
class Rule:
    process: str
    category: str
    name: str
    patterns: list[re.Pattern]
    app_only: bool = False


def normalize_title(title: str) -> str:
    title = _DIRTY_MARK.sub("", title or "")
    title = _DASH_SEP.sub(" - ", title)
    return title.strip()


def program_name(proc: str) -> str:
    return proc[:-4] if proc.lower().endswith(".exe") else proc


def parse_rules(raw) -> list[Rule]:
    """JSON 목록 -> Rule 목록. 형식이 틀리면 ValueError."""
    if not isinstance(raw, list):
        raise ValueError("rules.json 최상위는 목록이어야 합니다.")
    rules: list[Rule] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{i + 1}번째 규칙이 객체가 아닙니다.")
        proc = item.get("process")
        cat = item.get("category")
        if not isinstance(proc, str) or not proc or not isinstance(cat, str) or not cat:
            raise ValueError(f"{i + 1}번째 규칙에 process/category가 없습니다.")
        pats = item.get("patterns", [])
        if not isinstance(pats, list) or not all(isinstance(p, str) for p in pats):
            raise ValueError(f"{i + 1}번째 규칙의 patterns는 문자열 목록이어야 합니다.")
        try:
            compiled = [re.compile(p) for p in pats]
        except re.error as e:
            raise ValueError(f"{i + 1}번째 규칙({proc})의 정규식 오류: {e}") from None
        name = item.get("name") or program_name(proc)
        rules.append(Rule(proc.lower(), cat, str(name), compiled, bool(item.get("app_only", False))))
    return rules


def load_default_rules() -> list[Rule]:
    with (DEFAULTS_DIR / "rules.json").open(encoding="utf-8") as f:
        return parse_rules(json.load(f))


def _group(m: re.Match, name: str) -> str | None:
    if name in m.re.groupindex:
        v = m.group(name)
        if v and v.strip():
            return v.strip()
    return None


def resolve(proc: str, title: str, rules: list[Rule]) -> ActivityKey:
    """프로세스명 + 창 제목 -> 활동 키. 위에서부터 첫 번째로 맞는 규칙 적용."""
    proc = proc or UNKNOWN
    lp = proc.lower()
    rule = next((r for r in rules if r.process == lp), None)
    if rule is None:
        return ActivityKey(OTHER, proc)
    if rule.app_only:
        return ActivityKey(rule.category, rule.name)

    text = normalize_title(title)
    is_code = rule.category == CODE
    for pat in rule.patterns:
        m = pat.search(text)
        if not m:
            continue
        if is_code:
            return ActivityKey(CODE, _group(m, "project") or NO_PROJECT, _group(m, "file"))
        return ActivityKey(rule.category, _group(m, "target") or rule.name)
    if is_code:
        return ActivityKey(CODE, NO_PROJECT)
    return ActivityKey(rule.category, rule.name)


# ---- 제외 / 마스킹 ---------------------------------------------------------
def compile_patterns(pats) -> list[re.Pattern]:
    """config의 정규식 목록. 잘못된 항목은 ValueError."""
    if not pats:
        return []
    if not isinstance(pats, list):
        raise ValueError("정규식 목록이어야 합니다.")
    out = []
    for p in pats:
        try:
            out.append(re.compile(str(p)))
        except re.error as e:
            raise ValueError(f"정규식 오류 {p!r}: {e}") from None
    return out


@dataclass
class Privacy:
    exclude_processes: frozenset[str]
    exclude_titles: list[re.Pattern]
    mask_titles: list[re.Pattern]

    @classmethod
    def from_config(cls, config: dict) -> "Privacy":
        return cls(
            frozenset(str(p).lower() for p in config.get("exclude_processes", []) or []),
            compile_patterns(config.get("exclude_title_patterns")),
            compile_patterns(config.get("mask_title_patterns")),
        )

    def is_excluded(self, proc: str, title: str) -> bool:
        if (proc or "").lower() in self.exclude_processes:
            return True
        return any(p.search(title or "") for p in self.exclude_titles)

    def mask(self, title: str) -> str:
        for p in self.mask_titles:
            title = p.sub("***", title)
        return title
