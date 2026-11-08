from app.tokenize import core_chars, normalize, token_string, tokens


def test_hangul_bigram_ignores_spaces():
    assert tokens("로그 배포") == ["로그", "그배", "배포"]
    assert tokens("로그배포") == tokens("로그 배포")


def test_inside_word():
    assert "배포" in tokens("배포를")


def test_mixed():
    assert tokens("nginx설정") == ["nginx", "설정"]


def test_latin_words_and_case():
    assert tokens("LogPick log_cut DB2") == ["logpick", "log_cut", "db2"]


def test_nfkc():
    assert normalize("ＡＢＣ１") == "abc1"
    assert tokens("ＡＢＣ") == ["abc"]
    assert tokens("㈜") == tokens("(주)")


def test_single_char():
    assert tokens("가") == []          # 1글자 한글은 색인하지 않음
    assert tokens("a") == ["a"]
    assert core_chars("-가!") == "가"


def test_punctuation_breaks_run():
    assert tokens("로그,배포") == ["로그", "배포"]


def test_newline_between_hangul_joins():
    assert tokens("로그\n배포") == ["로그", "그배", "배포"]


def test_token_string():
    assert token_string("nginx 설정") == "nginx 설정"


def test_kana_and_hanzi():
    assert tokens("東京タワー") == ["東京", "京タ", "タワ", "ワー"]
