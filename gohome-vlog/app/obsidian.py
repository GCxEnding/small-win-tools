"""Obsidian 볼트로 요약 내보내기. Qt에 의존하지 않는 순수 함수 모음."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .store import atomic_write_text

HEADER = "%% gohome-vlog가 자동으로 만드는 파일입니다. 직접 고치면 덮어써집니다. %%"


def export_path(vault: Path, folder: str, day: date) -> Path:
    """볼트 안 내보내기 파일 경로. folder가 절대 경로이거나 볼트 밖을 가리키면 ValueError."""
    vault = Path(vault)
    sub = Path(folder)
    if sub.is_absolute() or sub.drive or sub.root:
        raise ValueError(f"obsidian_folder는 볼트 안의 상대 경로여야 합니다: {folder}")
    if ".." in sub.parts:
        raise ValueError(f"obsidian_folder가 볼트 밖을 가리킵니다: {folder}")
    return vault / sub / f"{day.isoformat()}.md"


def render(summary_md: str) -> str:
    """주석 한 줄 + 빈 줄 + 본문. 시각 등 매번 바뀌는 값은 넣지 않는다."""
    return f"{HEADER}\n\n{summary_md.rstrip()}\n"


def write_export(vault: Path, folder: str, day: date, summary_md: str) -> bool:
    """파일을 썼으면 True, 내용이 같아 쓰지 않았으면 False."""
    vault = Path(vault)
    if not vault.is_dir() or not (vault / ".obsidian").is_dir():
        raise ValueError(f"Obsidian 볼트가 아닙니다: {vault}")
    path = export_path(vault, folder, day)
    text = render(summary_md)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    atomic_write_text(path, text, durable=False)
    return True


def delete_export(vault: Path, folder: str, day: date) -> None:
    export_path(vault, folder, day).unlink(missing_ok=True)
