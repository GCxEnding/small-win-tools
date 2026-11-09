"""가져오기 모듈 인터페이스와 등록 목록.

새 출처는 이 폴더에 파일 하나를 만들고 아래 REGISTRY에 한 줄 추가한다.
본체(archive, index, watcher)는 원본 형식을 모른다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Protocol

from ..model import Conversation

SkipFn = Callable[[str], None]


class ImportFailed(Exception):
    """원본 전체를 읽을 수 없음 (zip 깨짐, JSON 파싱 실패 등)."""


class Importer(Protocol):
    name: str                                       # "claude-ai", "claude-code", "chatgpt" 등

    def detect(self, path: Path) -> bool: ...       # zip 또는 폴더 내용으로 판별

    def iter_conversations(self, path: Path, on_skip: SkipFn | None = None) -> Iterator[Conversation]: ...

    def snapshot_time(self, path: Path) -> datetime | None: ...   # 전체 스냅숏이면 내보내기 시각

    def is_full_snapshot(self) -> bool: ...

    def snapshot_sources(self, path: Path) -> set[str]: ...
    """이 스냅숏이 '전부'를 담고 있는 출처들. 여기 속하면서 스냅숏에 없는 대화는 missing 처리 대상."""


def registry() -> list[Importer]:
    from .claude_code import ClaudeCodeImporter
    from .chatgpt import ChatGPTImporter
    from .claude_export import ClaudeExportImporter
    from .claude_memory_md import ClaudeMemoryMdImporter
    return [
        ClaudeExportImporter(),
        ClaudeMemoryMdImporter(),
        ChatGPTImporter(),
        ClaudeCodeImporter(),
        # 새 출처는 여기에 한 줄
    ]


def detect(path: Path, importers: list[Importer] | None = None) -> Importer | None:
    for imp in importers if importers is not None else registry():
        try:
            if imp.detect(path):
                return imp
        except Exception:  # noqa: BLE001  detect는 절대 앱을 죽이지 않는다
            continue
    return None
