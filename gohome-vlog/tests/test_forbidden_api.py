"""소스 전체에서 입력 가로채기 계열 API 이름이 나오지 않는지 검사한다.

금지어는 조각을 합쳐서 만든다. 이 파일 자신이 검사에 걸리지 않게 하기 위해서다.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent

FORBIDDEN = [
    # SetWindowsHookEx, SetWindowsHookExA/W
    re.compile("SetWindows" + "HookEx"),
    re.compile("Register" + "RawInput" + "Devices"),
    re.compile("Get" + "RawInput" + "Data"),
    re.compile("Get" + "AsyncKey" + "State"),
    re.compile("Get" + "Key" + "State"),
    # 입력 후킹 라이브러리 import
    re.compile(r"^\s*import\s+" + "key" + r"board\b"),
    re.compile(r"^\s*import\s+" + "py" + r"nput\b"),
    re.compile(r"^\s*from\s+" + "py" + r"nput\b"),
    re.compile(r"^\s*from\s+" + "key" + r"board\b"),
]


def _source_files():
    for pattern in ("*.py", "*.pyw"):
        for path in ROOT.rglob(pattern):
            if TESTS_DIR in path.parents:
                continue
            if any(part in (".git", "__pycache__", ".venv", "venv") for part in path.parts):
                continue
            yield path


def test_no_forbidden_api_names():
    files = list(_source_files())
    assert files, "검사할 소스 파일이 하나도 없음"

    hits = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for rx in FORBIDDEN:
                if rx.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
                    break

    assert not hits, "금지 API 사용 의심:\n" + "\n".join(hits)
