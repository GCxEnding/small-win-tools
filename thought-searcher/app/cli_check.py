"""요약 AI CLI 찾기와 상태 확인 (SPEC-settings.md 3-J). Qt 없음.

상태 확인은 버전과 로그인 상태만 묻는다(AI 호출 없음, 토큰 0). 설치나 로그인을 대신하지 않는다.
- Claude: ask_command(기본 claude) -> PATH. `claude --version`, `claude auth status`(JSON, 종료 코드 0)
- Codex: ask_command_codex -> PATH의 codex -> %LOCALAPPDATA%\\OpenAI\\Codex\\bin\\*\\codex.exe 중 가장 늦게 고친 것.
  `codex --version`, `codex login status`(종료 코드 0, 'Logged in using ChatGPT')
로그인 확인 출력 형식은 버전마다 바뀔 수 있어 종료 코드 0을 1차 기준으로, 문구는 보조로 쓴다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .ask import clean_env
from .settings import as_command
from .store import expand

CHECK_TIMEOUT = 15.0
NAME = {"claude": "Claude Code", "codex": "Codex"}
EXE = {"claude": "claude", "codex": "codex"}
LOGIN_HINT = {"claude": "claude 를 실행해 로그인하세요", "codex": "codex login 을 실행해 로그인하세요"}
LOGIN_ARGS = {"claude": ["auth", "status"], "codex": ["login", "status"]}
_VERSION = re.compile(r"\d+(?:\.\d+)+[^\s()]*")


# ---- 모델 목록 (3-J-5) -------------------------------------------------------
@dataclass
class Model:
    slug: str
    name: str = ""
    description: str = ""


CHEAPEST = {"claude": "haiku", "codex": "gpt-6-luna"}
CLAUDE_MODELS = [Model("haiku", "Claude Haiku", "가장 빠르고 저렴한 모델"), Model("sonnet", "Claude Sonnet", ""),
                 Model("opus", "Claude Opus", "")]
CODEX_FALLBACK = [Model("gpt-6-luna", "GPT-6-Luna", "")]
CODEX_EFFORTS = ("low", "medium")


def codex_models(codex_home: Path | str | None = None) -> list[Model]:
    """Codex가 받아 둔 models_cache.json의 목록(visibility == list). 없거나 깨졌으면 기본 하나."""
    home = Path(expand(str(codex_home))) if codex_home else Path.home() / ".codex"
    try:
        data = json.loads((home / "models_cache.json").read_text(encoding="utf-8-sig"))
        models = data.get("models") if isinstance(data, dict) else None
    except (OSError, ValueError):
        models = None
    out = []
    for m in models or []:
        if isinstance(m, dict) and m.get("visibility") == "list" and isinstance(m.get("slug"), str) and m["slug"]:
            out.append(Model(m["slug"], str(m.get("display_name") or ""), str(m.get("description") or "")))
    return out or [Model(x.slug, x.name, x.description) for x in CODEX_FALLBACK]


# ---- 실행 파일 찾기 (3-J-3) -------------------------------------------------------
def _is_path(s: str) -> bool:
    return "\\" in s or "/" in s


def _resolve(cmd: list[str]) -> list[str] | None:
    first = expand(cmd[0]).strip()
    if not first:
        return None
    if _is_path(first):
        return [first, *cmd[1:]] if Path(first).is_file() else None
    found = shutil.which(first)
    return [found, *cmd[1:]] if found else None


def bundled_codex(localappdata: str | Path | None = None) -> Path | None:
    """Codex 데스크톱 앱이 넣은 codex.exe 중 가장 늦게 고친 것 (해시 폴더가 여러 개, 일부는 빈 폴더)."""
    base = localappdata if localappdata is not None else os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    best = None
    for p in (Path(base) / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"):
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if p.is_file() and (best is None or mt > best[0]):
            best = (mt, p)
    return best[1] if best else None


def resolve(provider: str, configured, localappdata: str | Path | None = None) -> list[str] | None:
    """실행할 명령(첫 칸은 실제 경로). 찾지 못하면 None. 지정한 경로가 있으면 그것만 본다."""
    cmd = as_command(configured)
    if provider == "claude":
        return _resolve(cmd or ["claude"])
    if cmd:
        return _resolve(cmd)
    found = shutil.which("codex")
    if found:
        return [found]
    p = bundled_codex(localappdata)
    return [str(p)] if p else None


# ---- 상태 확인 (3-J-4) ---------------------------------------------------------
@dataclass
class CliStatus:
    state: str            # ready | login | missing | timeout | error
    line: str
    exe: str = ""
    version: str = ""


def _run(cmd: list[str], timeout: float, provider: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=max(0.5, timeout), stdin=subprocess.DEVNULL, env=clean_env(provider),
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _first_line(text: str | None) -> str:
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def _login_label(provider: str, out: str) -> str | None:
    """로그인 방식 한 줄. 출력이 '로그인 안 됨'을 분명히 말하면 None."""
    if provider == "claude":
        try:
            d = json.loads(out)
        except ValueError:
            return "로그인됨"
        if isinstance(d, dict):
            if d.get("loggedIn") is False:
                return None
            method = str(d.get("authMethod") or "").strip()
            return f"{method} 로그인" if method else "로그인됨"
        return "로그인됨"
    line = _first_line(out)
    if re.search(r"not logged in", line, re.IGNORECASE):
        return None
    m = re.search(r"logged in using (.+)$", line, re.IGNORECASE)
    return f"{m.group(1).strip()} 로그인" if m else "로그인됨"


def check(provider: str, configured=None, timeout: float = CHECK_TIMEOUT,
          localappdata: str | Path | None = None) -> CliStatus:
    name = NAME[provider]
    cmd = resolve(provider, configured, localappdata)
    if not cmd:
        return CliStatus("missing", f"찾지 못함: {name} CLI가 설치돼 있지 않거나 PATH에 없습니다. "
                                    "아래 CLI 경로에 직접 지정할 수 있습니다")
    exe = cmd[0]
    deadline = time.monotonic() + timeout
    try:
        v = _run([*cmd, "--version"], deadline - time.monotonic(), provider)
        if v.returncode != 0:
            msg = _first_line(v.stderr) or _first_line(v.stdout) or f"종료 코드 {v.returncode}"
            return CliStatus("error", f"실행 실패: {msg[:160]}", exe)
        m = _VERSION.search(_first_line(v.stdout))
        version = m.group(0) if m else _first_line(v.stdout)[:40]
        lg = _run([*cmd, *LOGIN_ARGS[provider]], deadline - time.monotonic(), provider)
    except subprocess.TimeoutExpired:
        return CliStatus("timeout", f"확인 시간 초과 ({timeout:.0f}초)", exe)
    except OSError as e:
        return CliStatus("error", f"실행 실패: {e}", exe)
    label = _login_label(provider, lg.stdout or "") if lg.returncode == 0 else None
    if label is None:
        return CliStatus("login", f"로그인 필요: 터미널에서 {LOGIN_HINT[provider]}", exe, version)
    return CliStatus("ready", f"준비됨: {name} {version}, {label}".replace(" ,", ","), exe, version)
