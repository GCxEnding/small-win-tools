"""가져오기 모듈이 내놓는 공통 모델."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class Message:
    native_id: str
    role: Literal["user", "assistant"]
    created: datetime            # 시간대 포함
    text: str                    # md 본문 그대로 (도구 호출 요약 줄 포함)
    on_main_branch: bool = True
    label: str = ""              # 지정하면 제목 줄을 '📄 <label>'로 쓴다 (프로젝트 문서, 메모리)


@dataclass
class Conversation:
    conv_id: str                 # "<source>:<native id>"
    source: str                  # "claude-ai" | "claude-code" | "claude-ai-project" | "claude-ai-memory"
    title: str
    project: str
    created: datetime
    updated: datetime
    url: str
    messages: list[Message] = field(default_factory=list)

    @property
    def native_id(self) -> str:
        return self.conv_id.split(":", 1)[1]
