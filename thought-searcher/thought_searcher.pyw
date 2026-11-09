"""thought-searcher(생각 검색기) 진입점. pythonw로 실행하면 콘솔 없이 트레이에 상주한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _deps  # noqa: E402  (PySide6보다 먼저: 없으면 설치를 제안한다)

if not _deps.ensure("thought-searcher"):
    sys.exit(1)

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
