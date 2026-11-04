"""ctypes Win32 래퍼. 명세 6장에 적힌 API만 쓴다 (입력 내용을 읽는 API는 쓰지 않는다).

- 활성 창: GetForegroundWindow, GetWindowTextW, GetWindowThreadProcessId,
  OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION), QueryFullProcessImageNameW
- 자리 비움: GetLastInputInfo (마지막 입력 '시각'만 반환)
- 잠금/절전: WTSRegisterSessionNotification, WM_POWERBROADCAST
"""
from __future__ import annotations

import ctypes
import ntpath
from ctypes import wintypes

UNKNOWN = "(알 수 없음)"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
NOTIFY_FOR_THIS_SESSION = 0

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x4
PBT_APMRESUMESUSPEND = 0x7
PBT_APMRESUMEAUTOMATIC = 0x12


def _window_title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _window_pid(hwnd) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _process_name(pid: int) -> str:
    if not pid:
        return UNKNOWN
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return UNKNOWN
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return UNKNOWN
        return ntpath.basename(buf.value) or UNKNOWN
    finally:
        kernel32.CloseHandle(h)


class Win32Api:
    """collector가 쓰는 실제 구현. 테스트에서는 같은 메서드를 가진 가짜로 교체한다.

    프로세스 이름은 (hwnd, pid)가 바뀔 때만 다시 조회한다. 같은 창이면 OpenProcess를
    5초마다 반복하지 않아 보안 프로그램(DLP, 백신)의 프로세스 감시 부담도 줄어든다.
    """

    def __init__(self):
        self._last_window: tuple[int, int] | None = None
        self._last_proc = UNKNOWN

    def foreground(self) -> tuple[str, str] | None:
        """(프로세스명, 창 제목). 활성 창이 없으면 None. 읽기 실패는 (알 수 없음)."""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        try:
            title = _window_title(hwnd)
        except OSError:
            title = UNKNOWN
        try:
            key = (int(hwnd), _window_pid(hwnd))
            if key != self._last_window:
                self._last_proc = _process_name(key[1])
                # 읽기 실패는 캐시하지 않고 다음 폴링에서 다시 시도
                self._last_window = key if self._last_proc != UNKNOWN else None
            proc = self._last_proc
        except OSError:
            proc = UNKNOWN
        return proc, title

    def idle_seconds(self) -> float:
        """마지막 입력 후 지난 초. 입력 내용과 무관."""
        info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        elapsed = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF  # 49.7일 순환 대비
        return elapsed / 1000.0


def register_session_notification(hwnd: int) -> bool:
    return bool(wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION))


def unregister_session_notification(hwnd: int) -> None:
    wtsapi32.WTSUnRegisterSessionNotification(hwnd)
