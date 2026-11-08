"""깨진 한글 복원 코어. UI 의존 없음, 표준 라이브러리만 사용."""
from .core import Analysis, Candidate, analyze, restore

__all__ = ["Analysis", "Candidate", "analyze", "restore"]
