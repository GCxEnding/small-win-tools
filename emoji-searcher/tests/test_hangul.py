import pytest

from app import hangul


@pytest.mark.parametrize("text, expect", [
    ("배포", "ㅂㅍ"),
    ("경고", "ㄱㄱ"),
    ("까치 날다", "ㄲㅊㄴㄷ"),
    ("A배b", "Aㅂb"),
])
def test_choseong(text, expect):
    assert hangul.choseong(text) == expect


@pytest.mark.parametrize("text, expect", [
    ("ㅂㅍ", True), ("ㄱ ㄱ", True), ("ㄲㅆ", True),
    ("배ㅍ", False), ("ㅏ", False), ("", False), ("abc", False),
])
def test_is_choseong_only(text, expect):
    assert hangul.is_choseong_only(text) is expect


@pytest.mark.parametrize("latin, expect", [
    ("qnf", "불"),
    ("qovh", "배포"),
    ("rk", "가"),
    ("dkssud", "안녕"),
    ("dlfr", "읽"),          # 겹받침 ㄺ
    ("dlfrdj", "읽어"),
    ("dlfrj", "일거"),       # 받침이 다음 음절 초성으로 넘어감
    ("qkfqrl", "밟기"),      # 겹받침 ㄼ
    ("Rhcl", "꼬치"),         # Shift -> 쌍자음 ㄲ
    ("Tkfkd", "싸랑"),
    ("rhkwk", "과자"),       # 겹모음 ㅘ
    ("dnjsgkf", "원할"),     # 겹모음 ㅝ
    ("dml", "의"),
    ("rk tk", "가 사"),
    ("k", "ㅏ"),             # 모음만
    ("rr", "ㄱㄱ"),          # 자음만
])
def test_latin_to_hangul(latin, expect):
    assert hangul.latin_to_hangul(latin) == expect


@pytest.mark.parametrize("text", ["배포", "abc1", "a-b", "", "  "])
def test_latin_to_hangul_rejects_non_latin(text):
    assert hangul.latin_to_hangul(text) is None
