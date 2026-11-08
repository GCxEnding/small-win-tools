"""Windows 셸 창 판별: 클릭한 곳이 Win+V 클립보드 기록, 시작 메뉴 같은 셸 패널인지."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

# Win+V(클립보드 기록), Win+.(이모지), 시작 메뉴, 알림 센터, 검색
SHELL_OVERLAYS = {
    "textinputhost.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "searchhost.exe",
    "searchapp.exe",
}
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_ESCAPE = 0x1B
GA_ROOT = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.WindowFromPoint.argtypes = [wintypes.POINT]
    _user32.WindowFromPoint.restype = wintypes.HWND
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
except (AttributeError, OSError):      # Windows가 아닌 곳 (테스트 등)
    _user32 = _kernel32 = None


def key_down(vk: int) -> bool:
    if _user32 is None:
        return False
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def win_key_down() -> bool:
    return key_down(VK_LWIN) or key_down(VK_RWIN)


def process_under_cursor() -> str:
    """커서 아래 최상위 창의 실행 파일 이름 (소문자). 알 수 없으면 ''."""
    if _user32 is None:
        return ""
    pt = wintypes.POINT()
    if not _user32.GetCursorPos(ctypes.byref(pt)):
        return ""
    return _process_of(_user32.WindowFromPoint(pt))


def foreground_process() -> str:
    """지금 키보드 입력을 받는 창의 실행 파일 이름 (소문자)."""
    if _user32 is None:
        return ""
    return _process_of(_user32.GetForegroundWindow())


def _process_of(hwnd) -> str:
    if not hwnd:
        return ""
    root = _user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(root, ctypes.byref(pid))
    if not pid.value:
        return ""
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(h)
    return ""


def is_shell_overlay_click() -> bool:
    """Win 키를 누른 채이거나, Win+V 같은 셸 패널 위를 클릭한 경우."""
    return win_key_down() or process_under_cursor() in SHELL_OVERLAYS


def esc_closes_popup() -> bool:
    """팝업이 비활성일 때 Esc로 닫을지. Win+V 같은 셸 패널을 Esc로 닫는 중이면 팝업은 그대로 둔다."""
    return foreground_process() not in SHELL_OVERLAYS
