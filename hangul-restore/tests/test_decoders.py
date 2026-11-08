from restore import decoders as d
from restore.score import LOST_MARK


def test_misread_examples():
    assert d.reverse_misread("寃곗옱", "cp949", "utf-8") == "결재"
    assert d.reverse_misread("°áÀç", "latin-1", "cp949") == "결재"
    assert d.reverse_misread("°áÀç ¿äÃ» ¿Ï·á", "latin-1", "cp949") == "결재 요청 완료"
    assert d.reverse_misread("ê²°ì\x9e¬", "latin-1", "utf-8") == "결재"
    assert d.reverse_misread("ê²°ìž¬", "cp1252", "utf-8") == "결재"


def test_misread_not_applicable():
    assert d.reverse_misread("plain ascii", "cp949", "utf-8") is None
    assert d.reverse_misread("결재", "latin-1", "cp949") is None        # Latin-1로 인코딩 불가
    # UTF-8로 잘못 읽었다면 깨진 바이트는 \ufffd가 됐어야 한다. \ufffd가 없는데 CP949로 안 읽히면 가정이 틀림
    assert d.reverse_misread("°áÀç", "utf-8", "cp949") is None


def test_lossy_utf8_read_as_cp949():
    # '홍길동'의 UTF-8 첫 바이트가 \ufffd로 바뀐 경우: 첫 글자만 잃는다
    assert d.reverse_misread("\ufffd솉湲몃룞", "cp949", "utf-8") == LOST_MARK + "길동"
    broken = "결재 요청 완료".encode("utf-8").decode("cp949", "replace")
    assert d.reverse_misread(broken, "cp949", "utf-8") == "결재 □□ □□"


def test_lossy_cp949_read_as_utf8():
    # 실제 파일에서 본 모양: '사용여부'
    assert d.reverse_misread("\ufffd\ufffd뿩\ufffd\ufffd", "utf-8", "cp949") == "□□여□"
    assert d.reverse_misread("\ufffd볻", "utf-8", "cp949") == "□내"


def test_question_mark_holes():
    # Java가 \ufffd를 다시 MS949로 쓰며 '?'로 바꾼 경우
    assert d.reverse_misread("寃곗?", "cp949", "utf-8") == "결□"
    # 정상 문장 끝의 '?'는 잃은 바이트로 보지 않는다
    assert d.suspicious_question_marks("결재했나요?") == set()


def test_nfc_normalized_hanja_still_restores():
    import unicodedata
    broken = "결재 요청 완료 사용자 관리 화면".encode("utf-8").decode("cp949", "replace")
    nfc = unicodedata.normalize("NFC", broken)
    assert nfc != broken     # 호환 한자가 들어 있어 정규화로 바뀌는 입력
    assert d.reverse_misread(nfc, "cp949", "utf-8") == d.reverse_misread(broken, "cp949", "utf-8")


def test_url():
    assert d.url_decode("%EA%B2%B0%EC%9E%AC", "utf-8") == "결재"
    assert d.url_decode("%B0%E1%C0%E7", "cp949") == "결재"
    assert d.url_decode("%B0%E1%C0%E7", "utf-8") is None
    assert d.url_decode("API+%ED%98%B8%EC%B6%9C+%EC%8B%A4%ED%8C%A8", "utf-8") == "API 호출 실패"
    assert d.url_decode("%uACB0%uC7AC", "utf-8") == "결재"
    assert d.url_decode("50% 완료", "utf-8") is None
    assert d.url_decode("100%", "utf-8") is None


def esc(*hexes: str, prefix: str = "u") -> str:
    """역슬래시+u+16진수 이스케이프 문자열을 조립한다 (도구가 이스케이프를 미리 풀어 버리는 일을 피하려고)."""
    return "".join(BS + prefix + h for h in hexes)


BS = chr(92)


def test_unicode_escape():
    assert d.unicode_unescape(esc("acb0", "C7AC")) == "결재"
    assert d.unicode_unescape(esc("0000ACB0", prefix="U")) == "결"
    assert d.unicode_unescape(esc("d83d", "de00")) == chr(0x1F600)            # 서로게이트 쌍
    assert d.unicode_unescape("x" + BS + esc("acb0")) == "x결"                 # 이중 이스케이프
    # 16진수 부족, 홀로 남은 서로게이트는 원문 유지
    assert d.unicode_unescape(BS + "u12 끝") is None
    assert d.unicode_unescape(esc("d83d") + " 홀로") is None
    assert d.unicode_unescape(esc("acb0", "d83d")) == "결" + esc("d83d")


def test_html_entity():
    assert d.html_unescape("&#44208;&#51116;") == "결재"
    assert d.html_unescape("&#xACB0;") == "결"
    assert d.html_unescape("a &amp; b") == "a & b"
    assert d.html_unescape("AT&T") is None


def test_base64_only_korean():
    assert d.base64_decode("6rKw7J6sIOyalOyyrSDsmYTro4w=", "utf-8") == "결재 요청 완료"
    assert d.base64_decode("6rKw7J6sIOyalOyyrSDsmYTro4w", "utf-8") == "결재 요청 완료"   # 패딩 누락
    assert d.base64_decode("sOHA5w==", "cp949") == "결재"
    for word in ("test", "admin", "password", "SR0100", "HEADWORD_USE_YN", "Authorization"):
        assert d.base64_decode(word, "utf-8") is None
        assert d.base64_decode(word, "cp949") is None


def test_base64_wrapping_url():
    import base64
    tok = base64.b64encode(b"%EA%B2%B0%EC%9E%AC").decode()
    assert d.base64_decode(tok, "utf-8") == "%EA%B2%B0%EC%9E%AC"


def test_decoder_ids_unique():
    ids = [x.id for x in d.ALL]
    assert len(ids) == len(set(ids))
