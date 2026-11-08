"""트레이 상주, 단일 실행, 전역 단축키, 클립보드."""
from __future__ import annotations

import ctypes
import os
import sys
import traceback
from datetime import datetime

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from restore import Analysis, analyze

from .hotkey import HotkeyManager
from .store import Store
from .window import MSG_NO_CLIPBOARD, RestoreWindow

MUTEX_NAME = "Local\\GCxEnding.small-win-tools.hangul-restore"
ERROR_ALREADY_EXISTS = 183
APP_NAME = "hangul-restore"
CLIPBOARD_RETRIES = 4
CLIPBOARD_RETRY_MS = 120


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
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2f6fdb"))
        r = max(2, size // 5)
        p.drawRoundedRect(QRect(0, 0, size, size), r, r)
        f = QFont()
        f.setFamilies(["Malgun Gothic"])
        f.setBold(True)
        f.setPixelSize(int(size * 0.68))
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(pm.rect(), Qt.AlignCenter, "한")
        p.end()
        icon.addPixmap(pm)
    return icon


def clipboard_text() -> str:
    md = QApplication.clipboard().mimeData()
    if md is None or not md.hasText():
        return ""
    return md.text()


class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.store = Store()
        loaded = self.store.load()
        self.config, self.rules = loaded.config, loaded.rules

        self.window = RestoreWindow()
        self.window.textEdited.connect(self.recompute)
        self.window.chosen.connect(self.on_chosen)

        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip(f"{APP_NAME} - 깨진 한글 복원")
        menu = QMenu()
        for text, slot in (("열기", self.open), ("데이터 폴더 열기", self.open_data_dir),
                           ("설정·힌트 다시 읽기", self.reload)):
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
        for w in loaded.warnings:
            self.notify(w, QSystemTrayIcon.Warning)

    # ---- helpers ------------------------------------------------------
    def notify(self, msg: str, icon=QSystemTrayIcon.Information) -> None:
        self.tray.showMessage(APP_NAME, msg, icon, 4000)

    def core_config(self) -> dict:
        cfg = dict(self.config)
        cfg["hint_rules"] = self.rules
        return cfg

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
        # 창이 떠 있어도 다른 창을 보고 있었다면(비활성) 새 클립보드로 다시 연다
        if self.window.isVisible() and self.window.isActiveWindow():
            self.window.hide()
        else:
            self.open()

    def open(self) -> None:
        text = clipboard_text()
        self.window.set_input(text)
        self.recompute(text, MSG_NO_CLIPBOARD if not text else None)
        self.window.popup()

    def recompute(self, text: str, extra: str | None = None) -> None:
        if not text:
            self.window.set_analysis(Analysis("", []), extra or "입력이 비어 있습니다")
            return
        self.window.set_analysis(analyze(text, self.core_config()), extra)

    def on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open()

    def open_data_dir(self) -> None:
        self.store.ensure()
        os.startfile(self.store.root)

    def reload(self) -> None:
        old_keys = (self.config.get("hotkey"), self.config.get("fallback_hotkey"))
        loaded = self.store.load()
        self.config, self.rules = loaded.config, loaded.rules
        if (self.config.get("hotkey"), self.config.get("fallback_hotkey")) != old_keys:
            self.register_hotkey()
        if loaded.warnings:
            for w in loaded.warnings:
                self.notify(w, QSystemTrayIcon.Warning)
        else:
            self.notify(f"설정과 힌트 규칙 {len(self.rules)}개를 다시 읽었습니다.")

    def on_chosen(self, result: str) -> None:
        self.window.hide()
        self._copy(result, CLIPBOARD_RETRIES)

    def _copy(self, text: str, tries: int) -> None:
        """다른 프로그램이 클립보드를 잡고 있으면 실패할 수 있어 확인 후 짧게 재시도한다."""
        cb = QApplication.clipboard()
        cb.setText(text)
        if cb.text() == text:
            return
        if tries > 1:
            QTimer.singleShot(CLIPBOARD_RETRY_MS, lambda: self._copy(text, tries - 1))
        else:
            self.notify("클립보드에 복사하지 못했습니다. 다른 프로그램이 클립보드를 쓰고 있을 수 있습니다.",
                        QSystemTrayIcon.Warning)

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
