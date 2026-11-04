import json
from pathlib import Path

import pytest

from app.rules import (ActivityKey, Privacy, load_default_rules, normalize_title, parse_rules,
                       resolve)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RULES = load_default_rules()
TITLES = json.loads((FIXTURES / "sample_titles.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", TITLES, ids=[f"{c['proc']}|{c['title']}" for c in TITLES])
def test_sample_titles(case):
    key = resolve(case["proc"], case["title"], RULES)
    assert key.label == case["expect"]
    assert key.file == case["file"]


@pytest.mark.parametrize("sep", [" - ", " – ", " — "])
def test_three_separators(sep):
    key = resolve("idea64.exe", f"workflow-core{sep}ApprService.java", RULES)
    assert key == ActivityKey("코드", "workflow-core", "ApprService.java")


def test_dirty_mark_removed():
    assert normalize_title("● ApprService.java - workflow-core - Kiro") == "ApprService.java - workflow-core - Kiro"
    key = resolve("Kiro.exe", "● ApprService.java - workflow-core - Kiro", RULES)
    assert key.file == "ApprService.java"


def test_process_case_insensitive():
    assert resolve("CODE.EXE", "a.py - proj - Visual Studio Code", RULES).target == "proj"


def test_first_matching_rule_wins():
    rules = parse_rules([
        {"process": "tool.exe", "category": "서버", "patterns": ["^(?P<target>first)"]},
        {"process": "tool.exe", "category": "DB", "patterns": ["^(?P<target>.+)$"]},
    ])
    assert resolve("tool.exe", "first-title", rules) == ActivityKey("서버", "first")
    # 첫 규칙의 패턴이 안 맞아도 그 규칙이 적용되고 대상은 프로그램 이름
    assert resolve("tool.exe", "other", rules) == ActivityKey("서버", "tool")


def test_first_matching_pattern_wins():
    rules = parse_rules([{"process": "putty.exe", "category": "서버", "name": "PuTTY",
                          "patterns": ["@(?P<target>[\\w.-]+)", "^(?P<target>.+?) - PuTTY$"]}])
    assert resolve("putty.exe", "u@host-a - PuTTY", rules).target == "host-a"


def test_unmatched_process_uses_process_name():
    assert resolve("mspaint.exe", "제목 없음 - 그림판", RULES) == ActivityKey("기타", "mspaint.exe")


def test_code_without_project():
    rules = parse_rules([{"process": "ide.exe", "category": "코드", "patterns": ["^x (?P<project>.+)$"]}])
    assert resolve("ide.exe", "nothing", rules) == ActivityKey("코드", "(프로젝트 없음)")


def test_app_only_ignores_title():
    assert resolve("chrome.exe", "고객사 포털 - Chrome", RULES) == ActivityKey("웹", "Chrome")


def test_bad_rules_raise():
    with pytest.raises(ValueError):
        parse_rules({"process": "x"})
    with pytest.raises(ValueError):
        parse_rules([{"process": "x.exe", "category": "c", "patterns": ["("]}])


def test_exclude_and_mask():
    p = Privacy.from_config({
        "exclude_processes": ["KeePassXC.exe"],
        "exclude_title_patterns": ["(?i)inprivate"],
        "mask_title_patterns": ["acme(?:-corp)?"],
    })
    assert p.is_excluded("keepassxc.exe", "anything")
    assert p.is_excluded("msedge.exe", "새 탭 - [InPrivate] - Edge")
    assert not p.is_excluded("chrome.exe", "새 탭")
    assert p.mask("acme-corp 결재 - workflow-core") == "*** 결재 - workflow-core"


def test_bad_privacy_pattern_raises():
    with pytest.raises(ValueError):
        Privacy.from_config({"mask_title_patterns": ["("]})
