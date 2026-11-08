import ast
import collections
import json
import time
from pathlib import Path

import pytest

from restore import analyze, restore
from restore.hints import hint_for, parse_rules

from gen_corruptions import lossless_cases

ROOT = Path(__file__).resolve().parent.parent
REAL = json.loads((Path(__file__).parent / "real_cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", REAL, ids=[c["input"] for c in REAL])
def test_real_cases_first(case):
    cands = restore(case["input"], {})
    assert cands[0].result == case["expected"]
    if "path" in case:
        assert cands[0].path_ids == case["path"]


def test_spec_two_step_path_text():
    top = restore("%E5%AF%83%EA%B3%97%EC%98%B1")[0]
    assert top.path_text == "URL 디코딩 (UTF-8) → UTF-8 바이트를 CP949로 읽음 (되돌림)"
    assert top.hint and "MS949" in top.hint


def test_generated_accuracy():
    cases = lossless_cases()
    top1 = top3 = 0
    fails = collections.Counter()
    for c in cases:
        results = [x.result for x in analyze(c.input).candidates]
        top1 += results[0] == c.expected
        top3 += c.expected in results[:3]
        if results[0] != c.expected:
            fails[c.kind] += 1
    print(f"\n자동 생성 {len(cases)}건: 1위 {top1 / len(cases):.2%}, 상위 3위 {top3 / len(cases):.2%}, 실패 {dict(fails)}")
    assert top1 / len(cases) >= 0.95
    assert top3 / len(cases) >= 0.99


def test_depth_limit():
    from gen_corruptions import url
    s = "결재"
    four = url(url(url(url(s))))           # 4단계: 3단계까지만 풀고 중간 결과를 후보로 보여 준다
    a = analyze(four)
    found = {c.result: c for c in a.candidates}
    assert url(s) in found and len(found[url(s)].path_ids) == 3
    assert a.status == "원문보다 나은 후보를 찾지 못했습니다 (아래 후보는 참고용)"


def test_truncation_notice():
    a = analyze("가" * 300, {"max_input_chars": 100})
    assert len(a.text) == 100
    assert a.notice and "100" in a.notice


def test_empty_input():
    a = analyze("")
    assert a.candidates == [] and a.status


def test_no_candidate_message():
    a = analyze("\ufffd")
    # 단독 \ufffd는 어떤 가정으로도 살릴 정보가 없다 (□로 바꾸는 후보만 가능)
    assert a.candidates


def test_performance_2kb():
    line = "2026-11-05 ERROR userNm=" + "홍길동".encode("utf-8").decode("cp949", "replace") + " msg=%EA%B2%B0%EC%9E%AC\n"
    text = (line * 100)[:2048]
    analyze(text)          # 첫 실행의 표 로딩 제외
    t = time.perf_counter()
    analyze(text)
    ms = (time.perf_counter() - t) * 1000
    print(f"\n2KB 입력 처리: {ms:.0f}ms")
    assert ms < 200


def test_hints_rules():
    rules = parse_rules({"rules": [{"steps": ["url_utf8"], "min_count": 2, "hint": "이중"},
                                   {"steps": "url_utf8", "hint": "한 번"}]})
    assert hint_for(["url_utf8", "url_utf8"], rules) == "이중"
    assert hint_for(["url_utf8"], rules) == "한 번"
    assert hint_for(["html_entity"], rules) is None
    assert hint_for([], rules) is None
    with pytest.raises(ValueError):
        parse_rules({"rules": [{"steps": []}]})


def test_core_uses_only_stdlib():
    import sys
    allowed = set(sys.stdlib_module_names) | {"restore"}
    for f in (ROOT / "restore").glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                names = [node.module]
            else:
                continue
            for n in names:
                assert n.split(".")[0] in allowed, f"{f.name}: {n}"
