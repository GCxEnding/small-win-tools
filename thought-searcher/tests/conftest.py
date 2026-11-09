import sys
import zipfile
from datetime import date, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXPORT_DIR = FIXTURES / "claude_export_small"
KST = timezone(timedelta(hours=9))
TODAY = date(2026, 11, 7)


def zip_folder(folder: Path, dest: Path) -> Path:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(folder).as_posix())
    return dest


def make_export_zips(dest_dir: Path, src: Path = EXPORT_DIR) -> list[Path]:
    """claude.ai 내보내기처럼 출처별 zip 여러 개를 만든다."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    return [zip_folder(sub, dest_dir / f"{sub.name}.zip") for sub in sorted(src.iterdir()) if sub.is_dir()]


@pytest.fixture
def kst():
    return KST


@pytest.fixture
def archive_root(tmp_path):
    d = tmp_path / "archive"
    d.mkdir()
    return d


@pytest.fixture
def core_env(tmp_path, monkeypatch):
    """임시 APPDATA/LOCALAPPDATA와 보관 폴더를 쓰는 Core."""
    import json

    from app.core import Core
    from app.store import Store

    roam, local, arch, proj = (tmp_path / n for n in ("roam", "local", "archive", "projects"))
    for d in (roam, local, arch, proj):
        d.mkdir()
    (roam / "config.json").write_text(json.dumps({
        "archive_dir": str(arch), "code_projects_dir": str(proj), "watch_dir": str(tmp_path / "dl"),
        "codex_dir": str(tmp_path / "codex")}),
        encoding="utf-8")
    core = Core(Store(roam, local), tz=KST)
    return core
