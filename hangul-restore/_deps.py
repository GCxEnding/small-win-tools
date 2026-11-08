"""실행에 필요한 라이브러리 확인. 없으면 물어본 뒤 pip로 설치한다.

PySide6보다 먼저 import되어야 하므로 표준 라이브러리만 쓴다.
설치는 처음 한 번만, 사용자가 '예'를 눌렀을 때만 인터넷(PyPI)을 쓴다.
"""
from __future__ import annotations

import ctypes
import importlib
import importlib.util
import site
import subprocess
import sys
from pathlib import Path

# (import 이름, pip 패키지). QtCore/QtGui/QtWidgets만 쓰므로 Essentials로 충분하다.
REQUIRED = [("PySide6", "PySide6-Essentials>=6.6")]

MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONERROR = 0x10
MB_ICONQUESTION = 0x20
IDYES = 6

# 새 콘솔 창에서 pip를 돌리고, 실패하면 창이 바로 닫히지 않게 잡아 둔다.
_PIP_RUNNER = r"""
import subprocess, sys
print("필요한 라이브러리를 설치합니다:", " ".join(sys.argv[1:]))
print()
rc = subprocess.call([sys.executable, "-m", "pip", "install", *sys.argv[1:]])
if rc != 0:
    print()
    print("설치에 실패했습니다. 위 메시지를 확인해 주세요.")
    input("Enter를 누르면 창을 닫습니다...")
sys.exit(rc)
"""


def _missing() -> list[str]:
    return [pkg for mod, pkg in REQUIRED if importlib.util.find_spec(mod) is None]


def _console_python() -> str:
    """pythonw.exe로 실행됐으면 같은 폴더의 python.exe를 쓴다 (진행 상황을 보여 주려고)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.exists():
            return str(console)
    return str(exe)


def _message(title: str, text: str, flags: int) -> int:
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def _refresh_import_paths() -> None:
    """pip가 사용자 폴더(--user)로 설치했을 수 있으니 그 경로도 잡아 준다."""
    user_site = site.getusersitepackages()
    if Path(user_site).is_dir() and user_site not in sys.path:
        site.addsitedir(user_site)
    importlib.invalidate_caches()


def ensure(tool_name: str) -> bool:
    """필요한 라이브러리가 준비되면 True. 사용자가 거절했거나 설치에 실패하면 False."""
    missing = _missing()
    if not missing:
        return True

    manual = f'"{_console_python()}" -m pip install {" ".join(missing)}'
    answer = _message(
        tool_name,
        "실행에 필요한 라이브러리가 설치되어 있지 않습니다.\n\n"
        f"  {', '.join(missing)}\n\n"
        "지금 설치할까요? (인터넷 연결 필요, 처음 한 번만, 약 80MB)\n"
        "진행 상황은 새 콘솔 창에 표시됩니다.",
        MB_YESNO | MB_ICONQUESTION,
    )
    if answer != IDYES:
        _message(tool_name, f"설치를 취소했습니다. 직접 설치하려면:\n\n{manual}", MB_OK)
        return False

    rc = subprocess.call(
        [_console_python(), "-c", _PIP_RUNNER, *missing],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    _refresh_import_paths()
    still_missing = _missing()
    if rc == 0 and not still_missing:
        return True

    _message(
        tool_name,
        "라이브러리 설치에 실패했습니다.\n\n"
        f"직접 설치해 보세요:\n{manual}\n\n"
        "인터넷이 막힌 PC라면 README의 '오프라인 설치'를 참고해 주세요.",
        MB_OK | MB_ICONERROR,
    )
    return False
