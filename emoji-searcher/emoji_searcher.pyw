"""emoji-searcher 진입점. pythonw로 실행하면 콘솔 없이 트레이에 상주한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
