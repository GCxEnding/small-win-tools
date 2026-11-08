from restore import analyze
from restore.score import count_lost, hangul_tier, loss_labels, score

from gen_corruptions import load_corpus, lossy_cases

ENGLISH = [
    "NullPointerException at line 42",
    "SELECT * FROM approval WHERE doc_id = 1004",
    "Connection reset by peer",
    "test", "admin", "password1234", "SR0100", "user_id=hong&mode=edit",
    "The quick brown fox jumps over the lazy dog.",
    "50% complete", "a+b=c", "Base64 encoded value",
]


def test_tiers():
    assert hangul_tier("결") == 1
    assert hangul_tier("곗") == 2
    assert hangul_tier("옱") == 3
    assert hangul_tier("A") == 0


def test_order_of_interpretations():
    assert score("결재") > score("寃곗옱")
    assert score("결재") > score("°áÀç")
    assert score("□□") > score("\ufffd\ufffd\ufffd\ufffd")
    assert score("결재") > score("決裁")


def test_loss_labels():
    assert loss_labels(0, "결재") == []
    assert loss_labels(1, "□길동") == ["일부 손실", "1글자 손실"]
    assert "복원 불가에 가까움" in loss_labels(3, "□□여□")
    assert count_lost("□길동", "\ufffd솉湲몃룞") == 1


def test_normal_input_is_first_and_unbeaten():
    sentences = load_corpus()[:88] + ENGLISH
    assert len(sentences) >= 100
    for s in sentences:
        a = analyze(s)
        top = a.candidates[0]
        assert top.is_original and top.result == s, (s, top.result)
        assert all(c.score < top.score for c in a.candidates[1:]), s


def test_normal_status_message():
    assert analyze("결재 요청 완료").status == "깨진 부분을 찾지 못했습니다"
    assert analyze("test").status == "깨진 부분을 찾지 못했습니다"


def test_lossy_cases_labelled():
    cases = lossy_cases()
    assert len(cases) > 100
    misses = []
    for c in cases:
        top = analyze(c.input).candidates[0]
        if top.is_original or "일부 손실" not in top.labels or abs(top.lost_chars - c.lost) > 1:
            misses.append((c.kind, c.input, top.result, top.lost_chars, c.lost))
    assert not misses, misses[:5]


def test_mostly_lost_label():
    top = analyze("IS '\ufffd\ufffd뿩\ufffd\ufffd Y, N'").candidates[0]
    assert top.result == "IS '□□여□ Y, N'"
    assert top.lost_chars == 3
    assert "복원 불가에 가까움" in top.labels
    assert top.path_ids == ["cp949_as_utf8"]
    assert "원본이 손실" in top.hint
