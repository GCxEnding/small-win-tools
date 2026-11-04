"""포커스 복귀, 클립보드, Ctrl+V 전송 (Win32 SendInput)."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20
SW_RESTORE = 9

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL, VK_V = 0x11, 0x56
VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x12, 0x5B, 0x5C

# 붙여넣기 대상으로 보지 않는 창 (작업 표시줄, 트레이 넘침 창 등)
SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
                 "TopLevelWindowForOverflowXamlIsland", "Progman", "WorkerW"}

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def is_paste_target(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd)) and window_class(hwnd) not in SHELL_CLASSES


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _token_elevated(process_handle) -> bool | None:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        val = wintypes.DWORD(0)
        size = wintypes.DWORD(0)
        if not advapi32.GetTokenInformation(token, TokenElevation, ctypes.byref(val),
                                            ctypes.sizeof(val), ctypes.byref(size)):
            return None
        return bool(val.value)
    finally:
        kernel32.CloseHandle(token)


def self_elevated() -> bool:
    return bool(_token_elevated(kernel32.GetCurrentProcess()))


def process_elevated(pid: int) -> bool:
    """대상 프로세스가 관리자 권한인지. 토큰을 열 수 없으면 관리자 권한으로 본다."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return True
    try:
        r = _token_elevated(h)
        return True if r is None else r
    finally:
        kernel32.CloseHandle(h)


def input_blocked(hwnd: int) -> bool:
    """UIPI 때문에 입력을 보낼 수 없는 창인지 (대상이 관리자 권한이고 우리는 아님)."""
    return not self_elevated() and process_elevated(window_pid(hwnd))


def _key(vk: int, up: bool = False) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP if up else 0, time=0, dwExtraInfo=0)
    return inp


def send_ctrl_v() -> bool:
    seq = []
    # 혹시 눌린 채로 남은 조합키를 먼저 뗀다 (Shift/Alt/Win이 섞이면 다른 동작이 됨)
    for vk in (VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN):
        if user32.GetAsyncKeyState(vk) & 0x8000:
            seq.append(_key(vk, up=True))
    seq += [_key(VK_CONTROL), _key(VK_V), _key(VK_V, True), _key(VK_CONTROL, True)]
    arr = (INPUT * len(seq))(*seq)
    return user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT)) == len(seq)


def activate(hwnd: int, timeout: float = 0.4) -> bool:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.01)
        user32.SetForegroundWindow(hwnd)
    return user32.GetForegroundWindow() == hwnd


def paste_into(hwnd: int) -> str:
    """클립보드는 이미 채워져 있다고 가정. 결과: 'pasted' | 'gone' | 'blocked' | 'nofocus' | 'failed'."""
    if not is_paste_target(hwnd):
        return "gone"
    if input_blocked(hwnd):
        activate(hwnd)  # 포커스만 돌려 두면 사용자가 바로 Ctrl+V 할 수 있다
        return "blocked"
    if not activate(hwnd):
        return "nofocus"
    time.sleep(0.03)  # 대상 창이 포커스를 받아들일 짧은 여유
    return "pasted" if send_ctrl_v() else "failed"
