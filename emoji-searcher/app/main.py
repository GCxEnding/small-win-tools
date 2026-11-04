"""트레이 상주, 단일 실행, 앱 수명."""
from __future__ import annotations

import ctypes
import os
import sys
import traceback
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import paste
from .hotkey import HotkeyManager
from .search import Searcher, load_entries
from .store import Store
from .window import EMOJI_FONT, SearchWindow

MUTEX_NAME = "Local\\GCxEnding.small-win-tools.emoji-searcher"
ERROR_ALREADY_EXISTS = 183
APP_NAME = "emoji-searcher"


def acquire_single_instance():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def make_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        f = QFont(EMOJI_FONT)
        f.setPixelSize(int(size * 0.8))
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, "🔍")
        p.end()
        icon.addPixmap(pm)
    return icon


class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.store = Store()
        self.target_hwnd = 0
        self.warnings: list[str] = []

        cfg = self.store.load_config()
        self.config = cfg.data
        self._warn(cfg.warning)
        usage = self.store.load_usage()
        self.usage = usage.data
        self._warn(usage.warning)
        tags = self.store.load_user_tags()
        self._warn(tags.warning)
        self.searcher = Searcher(load_entries(), tags.data, self.usage)

        self.window = SearchWindow()
        self.window.queryChanged.connect(self.on_query)
        self.window.chosen.connect(self.on_chosen)

        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        for text, slot in (("열기", self.open_from_tray), ("데이터 폴더 열기", self.open_data_dir),
                           ("개인 태그 다시 읽기", self.reload_user_tags)):
            act = QAction(text, menu)
            act.triggered.connect(slot)
            menu.addAction(act)
        menu.addSeparator()
        quit_act = QAction("종료", menu)
        quit_act.triggered.connect(self.quit)
        menu.addAction(quit_act)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        self.hotkey = HotkeyManager(qapp)
        self.hotkey.activated.connect(self.toggle)
        self.register_hotkey()

        for w in self.warnings:
            self.notify(w, QSystemTrayIcon.Warning)

    # ---- helpers ------------------------------------------------------
    def _warn(self, msg: str | None) -> None:
        if msg:
            self.warnings.append(msg)

    def notify(self, msg: str, icon=QSystemTrayIcon.Information) -> None:
        self.tray.showMessage(APP_NAME, msg, icon, 4000)

    def register_hotkey(self) -> None:
        main_key = str(self.config.get("hotkey") or "")
        fb = str(self.config.get("fallback_hotkey") or "")
        ok, why = self.hotkey.register(main_key) if main_key else (False, "설정 없음")
        if ok:
            return
        if fb:
            ok2, why2 = self.hotkey.register(fb)
            if ok2:
                self.notify(f"{main_key} 등록 실패({why}).\n대신 {fb} 로 등록했습니다.", QSystemTrayIcon.Warning)
                return
            why = f"{why} / {fb}: {why2}"
        self.notify(f"단축키를 등록하지 못했습니다({why}).\n트레이 메뉴 '열기'로 사용하세요.", QSystemTrayIcon.Warning)

    # ---- actions ------------------------------------------------------
    def toggle(self) -> None:
        if self.window.isVisible():
            self.window.hide()
            return
        hwnd = paste.foreground_window()
        if hwnd != int(self.window.winId()):
            self.target_hwnd = hwnd if paste.is_paste_target(hwnd) else 0
        self.window.popup(str(self.config.get("position", "cursor")))

    def open_from_tray(self) -> None:
        # 트레이를 누르면 포그라운드가 작업 표시줄로 바뀌므로 붙여넣을 대상이 없다 -> 복사만
        self.target_hwnd = 0
        self.window.popup(str(self.config.get("position", "cursor")))

    def on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_from_tray()

    def open_data_dir(self) -> None:
        self.store.ensure()
        os.startfile(self.store.root)

    def reload_user_tags(self) -> None:
        res = self.store.load_user_tags()
        self.searcher.set_user_tags(res.data)
        if res.warning:
            self.notify(res.warning, QSystemTrayIcon.Warning)
        else:
            self.notify(f"개인 태그 {len(res.data)}개 이모지를 다시 읽었습니다.")

    def on_query(self, text: str) -> None:
        limit = int(self.config.get("max_results", 30))
        self.window.set_results(self.searcher.search(text, limit), text)

    def on_chosen(self, emoji: str) -> None:
        QApplication.clipboard().setText(emoji)
        self.window.hide()
        try:
            self.store.record_use(self.usage, emoji, datetime.now())
        except OSError as e:
            self.notify(f"사용 기록 저장 실패: {e}", QSystemTrayIcon.Warning)
        self.searcher.set_usage(self.usage)
        target = self.target_hwnd
        self.target_hwnd = 0
        # 창이 완전히 숨겨지고 클립보드가 반영된 뒤 붙여넣는다
        QTimer.singleShot(30, lambda: self._paste(emoji, target))

    def _paste(self, emoji: str, target: int) -> None:
        if not target:
            self.notify(f"{emoji} 클립보드에 복사됨")
            return
        result = paste.paste_into(target)
        if result == "pasted":
            return
        reason = {"gone": "붙여넣을 창이 닫혔습니다.",
                  "blocked": "대상 창이 관리자 권한이라 자동 입력이 막혔습니다. Ctrl+V로 붙여넣으세요.",
                  "nofocus": "대상 창으로 포커스를 돌리지 못했습니다.",
                  "failed": "키 입력 전송에 실패했습니다."}.get(result, "")
        self.notify(f"{emoji} 클립보드에 복사됨\n{reason}")

    def quit(self) -> None:
        self.hotkey.unregister()
        self.tray.hide()
        self.qapp.quit()


def _install_error_log() -> None:
    log = Store().root / "error.log"

    def hook(etype, value, tb):
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}]\n")
                f.write("".join(traceback.format_exception(etype, value, tb)))
        except OSError:
            pass
        sys.__excepthook__(etype, value, tb)

    sys.excepthook = hook


def main() -> int:
    _install_error_log()
    mutex = acquire_single_instance()
    if mutex is None:
        return 0
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 1
    app = App(qapp)  # noqa: F841  (수명 유지)
    return qapp.exec()
