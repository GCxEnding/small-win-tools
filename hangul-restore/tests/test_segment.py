from restore import analyze
from restore.segment import find_segments

from gen_corruptions import lossless_cases


def kinds(text):
    return [(s.kind, s.text(text)) for s in find_segments(text)]


def test_segments_basic():
    assert kinds("ERROR userNm=\ufffd솉湲몃룞 id=1004") == [("text", "\ufffd솉湲몃룞")]
    assert kinds("결재 요청 완료") == []
    assert kinds("a=%EA%B2%B0%EC%9E%AC&b=1") == [("url", "a=%EA%B2%B0%EC%9E%AC&b=1")]
    assert kinds("50% 완료") == []
    e = chr(92) + "uacb0" + chr(92) + "uc7ac"
    assert kinds("msg=" + e + " end") == [("escape", e)]
    assert kinds("t=&#44208;&#51116;") == [("entity", "&#44208;&#51116;")]
    assert kinds("token 6rKw7J6sIOyalOyyrSDsmYTro4w= end") == [("base64", "6rKw7J6sIOyalOyyrSDsmYTro4w=")]
    assert kinds("test admin") == []


def test_spec_mixed_example():
    top = analyze("ERROR userNm=\ufffd솉湲몃룞 id=1004").candidates[0]
    assert top.result == "ERROR userNm=□길동 id=1004"
    assert "일부 손실" in top.labels and top.lost_chars == 1


def test_mixed_keeps_normal_parts():
    cases = [c for c in lossless_cases() if c.kind.startswith("mixed:")]
    assert len(cases) > 100
    for c in cases:
        top = analyze(c.input).candidates[0]
        assert top.result.startswith(c.meta["prefix"]) and top.result.endswith(c.meta["suffix"]), c.input
        assert top.result == c.expected, (c.input, top.result)


def test_normal_text_next_to_broken_text_survives():
    text = "결재 寃곗옱 완료"
    assert analyze(text).candidates[0].result == "결재 결재 완료"


def test_two_segments_details():
    top = analyze("寃곗옱 / °áÀç").candidates[0]
    assert top.result == "결재 / 결재"
    assert len(top.details) == 2
