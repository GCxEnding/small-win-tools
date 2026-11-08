"""다운로드 폴더 감시와 zip 처리 이력. (Qt 타이머는 main.py가 돌리고, 여기는 판단만 한다)"""
from __future__ import annotations

import ctypes
import hashlib
import os
import time
from ctypes import wintypes
from pathlib import Path

STABLE_SECONDS = 5.0
IGNORE_SUFFIXES = (".crdownload", ".part", ".tmp", ".download")


def downloads_dir() -> Path:
    """Windows 알려진 폴더 Downloads (리디렉션 반영)."""
    try:
        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]
        fid = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        ptr = ctypes.c_wchar_p()
        shell32 = ctypes.WinDLL("shell32")
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                                                 ctypes.POINTER(ctypes.c_wchar_p)]
        if shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(ptr)) == 0:
            path = ptr.value
            ctypes.WinDLL("ole32").CoTaskMemFree(ptr)
            if path:
                return Path(path)
    except (OSError, AttributeError):
        pass
    return Path.home() / "Downloads"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def can_open(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            f.read(1)
        return True
    except OSError:
        return False


class ZipPoller:
    """새 zip을 찾고, 크기가 STABLE_SECONDS 이상 그대로이며 열 수 있을 때 '준비됨'으로 돌려준다."""

    def __init__(self, stable_seconds: float = STABLE_SECONDS, clock=time.monotonic):
        self.stable = stable_seconds
        self.clock = clock
        self.seen: dict[str, tuple[int, float, float]] = {}   # 경로 -> (크기, mtime, 그 크기가 처음 보인 시각)
        self.done: set[tuple[str, int, float]] = set()        # 이번 실행에서 처리한 (경로, 크기, mtime)

    def poll(self, folder: Path) -> list[Path]:
        now = self.clock()
        ready = []
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return []
        alive = set()
        for e in entries:
            name = e.name.lower()
            if not name.endswith(".zip") or name.endswith(IGNORE_SUFFIXES):
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            if not e.is_file():
                continue
            key = e.path
            alive.add(key)
            if (key, st.st_size, st.st_mtime) in self.done:
                continue
            prev = self.seen.get(key)
            if prev is None or prev[0] != st.st_size or prev[1] != st.st_mtime:
                self.seen[key] = (st.st_size, st.st_mtime, now)
                continue
            if now - prev[2] >= self.stable and can_open(Path(e.path)):
                ready.append(Path(e.path))
        for k in list(self.seen):
            if k not in alive:
                del self.seen[k]
        return ready

    def mark_done(self, path: Path) -> None:
        try:
            st = path.stat()
        except OSError:
            return
        self.done.add((str(path), st.st_size, st.st_mtime))
        self.seen.pop(str(path), None)
