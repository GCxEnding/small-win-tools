"""요약 AI CLI 찾기와 상태 확인 (SPEC-settings.md 3-J-3~5, 12번 test_cli_check.py). 실제 CLI는 부르지 않는다."""
import json
import os
import sys
import textwrap
import time

import pytest

from app import cli_check

FAKE = textwrap.dedent("""
    import json, os, sys, time
    mode = os.environ.get("FAKE_CLI", "ok")
    args = sys.argv[1:]
    if mode == "slow":
        time.sleep(5)
    if args == ["--version"]:
        print(os.environ.get("FAKE_VERSION", "2.1.319 (Claude Code)"))
        sys.exit(0)
    if args in (["auth", "status"], ["login", "status"]):
        if mode == "logout":
            print(json.dumps({"loggedIn": False}) if args[0] == "auth" else "Not logged in")
            sys.exit(1)
        if mode == "json-false":
            print(json.dumps({"loggedIn": False}))
            sys.exit(0)
        if args[0] == "auth":
            print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
        else:
            print("Logged in using ChatGPT")
        sys.exit(0)
    sys.exit(3)
""")


@pytest.fixture
def fake(tmp_path):
    p = tmp_path / "fake_cli.py"
    p.write_text(FAKE, encoding="utf-8")
    return [sys.executable, str(p)]


def test_claude_ready(fake, monkeypatch):
    monkeypatch.delenv("FAKE_CLI", raising=False)
    st = cli_check.check("claude", fake)
    assert st.state == "ready" and st.line == "준비됨: Claude Code 2.1.319, claude.ai 로그인"


def test_codex_ready(fake, monkeypatch):
    monkeypatch.setenv("FAKE_VERSION", "codex-cli 0.163.0-alpha.10.2")
    st = cli_check.check("codex", fake)
    assert st.state == "ready" and st.line == "준비됨: Codex 0.163.0-alpha.10.2, ChatGPT 로그인"


@pytest.mark.parametrize("provider,mode,hint", [("claude", "logout", "claude 를 실행"),
                                                ("codex", "logout", "codex login"),
                                                ("claude", "json-false", "claude 를 실행")])
def test_login_needed(fake, monkeypatch, provider, mode, hint):
    monkeypatch.setenv("FAKE_CLI", mode)
    st = cli_check.check(provider, fake)
    assert st.state == "login" and st.line.startswith("로그인 필요: 터미널에서") and hint in st.line


def test_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    st = cli_check.check("claude", [str(tmp_path / "없음" / "claude.exe")])
    assert st.state == "missing" and st.line.startswith("찾지 못함: Claude Code CLI")
    st = cli_check.check("codex", [], localappdata=tmp_path / "빈곳")
    assert st.state == "missing" and "Codex CLI" in st.line


def test_timeout(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLI", "slow")
    t0 = time.monotonic()
    st = cli_check.check("claude", fake, timeout=1)
    assert st.state == "timeout" and "시간 초과" in st.line
    assert time.monotonic() - t0 < 4


def _exe(path, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    os.utime(path, (mtime, mtime))
    return path


def test_codex_bundled_search(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "nopath"))
    la = tmp_path / "la"
    binr = la / "OpenAI" / "Codex" / "bin"
    (binr / "hash-empty").mkdir(parents=True)                         # 빈 해시 폴더
    old = _exe(binr / "hash-old" / "codex.exe", 1_700_000_000)
    assert cli_check.resolve("codex", [], la) == [str(old)]
    new = _exe(binr / "hash-new" / "codex.exe", 1_800_000_000)
    assert cli_check.resolve("codex", [], la) == [str(new)]          # 가장 늦게 고친 것
    mine = _exe(tmp_path / "my" / "codex.exe", 1)
    assert cli_check.resolve("codex", [str(mine)], la) == [str(mine)]   # 지정한 경로가 우선
    assert cli_check.resolve("codex", [str(tmp_path / "gone.exe")], la) is None   # 지정했는데 없으면 찾지 못함


def test_codex_on_path_before_bundle(tmp_path, monkeypatch):
    pathdir = tmp_path / "path"
    _exe(pathdir / "codex.exe", 1)
    monkeypatch.setenv("PATH", str(pathdir))
    monkeypatch.setenv("PATHEXT", ".EXE")
    la = tmp_path / "la"
    _exe(la / "OpenAI" / "Codex" / "bin" / "h" / "codex.exe", 1_800_000_000)
    got = cli_check.resolve("codex", [], la)
    assert got and os.path.normcase(got[0]) == os.path.normcase(str(pathdir / "codex.exe"))


def test_models_cache(tmp_path):
    home = tmp_path / ".codex"
    home.mkdir()
    assert [m.slug for m in cli_check.codex_models(home)] == ["gpt-6-luna"]       # 파일 없음
    (home / "models_cache.json").write_text("{깨짐", encoding="utf-8")
    assert [m.slug for m in cli_check.codex_models(home)] == ["gpt-6-luna"]
    (home / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-reserve", "visibility": "hide", "display_name": "R"},
        {"slug": "gpt-6-luna", "visibility": "list", "display_name": "GPT-6-Luna",
         "description": "Fast and affordable model for easier tasks."},
        {"slug": "gpt-5.6-terra", "visibility": "list", "display_name": "GPT-5.6-Terra", "description": ""},
        {"visibility": "list"},
    ]}), encoding="utf-8")
    ms = cli_check.codex_models(home)
    assert [m.slug for m in ms] == ["gpt-6-luna", "gpt-5.6-terra"]
    assert ms[0].description.startswith("Fast and affordable")
    assert cli_check.CHEAPEST == {"claude": "haiku", "codex": "gpt-6-luna"}
