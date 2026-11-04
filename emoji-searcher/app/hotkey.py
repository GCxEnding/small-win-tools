"""전역 단축키 (Win32 RegisterHotKey)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QWidget

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

MODIFIERS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}
SPECIAL_KEYS = {
    ".": 0xBE, ",": 0xBC, ";": 0xBA, "/": 0xBF, "`": 0xC0, "-": 0xBD, "=": 0xBB,
    "[": 0xDB, "]": 0xDD, "\\": 0xDC, "'": 0xDE, "space": 0x20,
}


def parse_hotkey(text: str) -> tuple[int, int]:
    """'win+.' -> (MOD_WIN, VK_OEM_PERIOD). 잘못된 문자열이면 ValueError."""
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+")]
    # '+' 자체를 키로 쓰는 경우 ("ctrl++")
    if text.strip().endswith("++"):
        parts = parts[:-2] + ["="]
    if not parts or not parts[-1]:
        raise ValueError(f"단축키 형식 오류: {text!r}")
    *mods, key = parts
    m = 0
    for name in mods:
        if name not in MODIFIERS:
            raise ValueError(f"알 수 없는 조합키: {name!r}")
        m |= MODIFIERS[name]
    if key in SPECIAL_KEYS:
        vk = SPECIAL_KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    else:
        raise ValueError(f"알 수 없는 키: {key!r}")
    return m, vk


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner: "HotkeyManager"):
        super().__init__()
        self.owner = owner
        self._last = None

    def nativeEventFilter(self, event_type, message):
        if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and msg.hWnd == self.owner.hwnd:
            # 같은 메시지가 두 필터 경로로 들어올 수 있어 시각+ID로 중복 제거
            key = (msg.time, msg.wParam)
            if key != self._last:
                self._last = key
                self.owner.activated.emit()
            return True, 0
        return False, 0


class HotkeyManager(QObject):
    activated = Signal()
    HOTKEY_ID = 0xE51

    def __init__(self, app):
        super().__init__()
        self._sink = QWidget()  # 메시지를 받을 숨은 네이티브 창
        self.hwnd = int(self._sink.winId())
        self._filter = _Filter(self)
        app.installNativeEventFilter(self._filter)
        self.registered: str | None = None

    def register(self, text: str) -> tuple[bool, str]:
        """성공 여부와 실패 이유를 돌려준다."""
        self.unregister()
        try:
            mods, vk = parse_hotkey(text)
        except ValueError as e:
            return False, str(e)
        if user32.RegisterHotKey(self.hwnd, self.HOTKEY_ID, mods | MOD_NOREPEAT, vk):
            self.registered = text
            return True, ""
        err = ctypes.get_last_error()
        return False, ctypes.FormatError(err).strip() if err else "등록 실패"

    def unregister(self) -> None:
        if self.registered:
            user32.UnregisterHotKey(self.hwnd, self.HOTKEY_ID)
            self.registered = None
