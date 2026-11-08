import pytest

from app.redact import Redactor

CASES = [
    ("anthropic", "sk-ant-api03-" + "A1b2C3d4" * 5),
    ("openai", "sk-" + "a1B2c3D4e5" * 5),
    ("openai", "sk-proj-" + "Zz09_-ab" * 6),
    ("github", "ghp_" + "a" * 36),
    ("github", "gho_" + "B1" * 18),
    ("github", "github_pat_" + "11ABCDEFG0" * 3),
    ("aws", "AKIA" + "ABCDEFGHIJ012345"),
    ("slack", "xoxb-1234567890-abcdefghij"),
    ("google", "AIza" + "S" * 35),
    ("jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"),
]


@pytest.mark.parametrize("kind,secret", CASES)
def test_patterns(kind, secret):
    out = Redactor()(f"값은 {secret} 입니다")
    assert secret not in out
    assert f"***가림:{kind}***" in out


def test_pem_block():
    text = "앞\n-----BEGIN OPENSSH PRIVATE KEY-----\nabc\ndef\n-----END OPENSSH PRIVATE KEY-----\n뒤"
    assert Redactor()(text) == "앞\n***가림:pem***\n뒤"


@pytest.mark.parametrize("text", [
    "sk-learn 으로 학습합니다", "task-ant 작업", "AKIA 는 접두어입니다", "ghp_short", "eyJ 로 시작하는 단어",
    "uuid 12345678-aaaa-4bbb-8ccc-1234567890ab", "git commit -m 'fix'", "https://claude.ai/chat/abc",
    "-----BEGIN CERTIFICATE----- 공개 인증서는 가리지 않음",
])
def test_no_false_positive(text):
    assert Redactor()(text) == text


def test_extra_patterns():
    r = Redactor([r"사번\d{6}", "[잘못된"])
    assert r("내 사번123456 입니다") == "내 ***가림:custom*** 입니다"
    assert r.errors and "잘못된" in r.errors[0]
