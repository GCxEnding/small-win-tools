"""2초마다 도는 확인이 메모리를 쌓지 않는지 (2026-11-16 주말 동안 2GB까지 늘었던 누수)."""
import gc
import sys
import tracemalloc

import pytest

from app.watcher import downloads_dir


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 알려진 폴더 API")
def test_downloads_dir_does_not_grow_memory():
    first = downloads_dir()
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    for _ in range(2000):            # 약 1시간치 확인
        assert downloads_dir() == first
    gc.collect()
    grown = tracemalloc.get_traced_memory()[0] - before
    tracemalloc.stop()
    assert grown < 200_000, f"{grown} bytes"   # 고치기 전에는 수 MB
