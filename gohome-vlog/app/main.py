"""트레이 상주, 단일 실행, 메뉴, 알림, 스케줄."""
from __future__ import annotations

import ctypes
import os
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from . import obsidian, win32
from .collector import Collector
from .rules import Privacy
from .store import Store, business_day, day_bounds, day_start_time, parse_hhmm
from .summary import build_summary

APP_NAME = "gohome"
MUTEX_NAME = "Local\\GCxEnding.small-win-tools.gohome-vlog"
ERROR_ALREADY_EXISTS = 183
ALARM_TEXT = "오늘 브이로그 다 찍었습니다. 이제 집에 가셔도 됩니다.\n(이 알림을 누르면 요약을 클립보드에 복사합니다)"
# 앱을 알림 시각보다 늦게 켰을 때, 이 시간 안이면 알림을 띄운다
LATE_ALARM_WINDOW = timedelta(hours=2)
CLIPBOARD_RETRIES = 5


def acquire_single_instance():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def make_icon(paused: bool) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont("Segoe UI Emoji")
        f.setPixelSize(int(size * 0.8))
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, "🏠")
        if paused:
            # 회색 덮개 + 일시 정지 막대
            p.fillRect(pm.rect(), QColor(80, 80, 80, 150))
            w, h = max(2, size // 6), int(size * 0.55)
            y = (size - h) // 2
            p.fillRect(int(size * 0.28), y, w, h, QColor(255, 255, 255))
            p.fillRect(int(size * 0.72) - w, y, w, h, QColor(255, 255, 255))
        p.end()
        icon.addPixmap(pm)
    return icon


class _SessionFilter(QAbstractNativeEventFilter):
    """숨은 창으로 들어오는 잠금/해제, 절전/복귀 메시지."""

    def __init__(self, app: "App"):
        super().__init__()
        self.app = app
        self._last = None

    def nativeEventFilter(self, event_type, message):
        if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        if msg.hWnd != self.app.sink_hwnd:
            return False, 0
        if msg.message not in (win32.WM_WTSSESSION_CHANGE, win32.WM_POWERBROADCAST):
            return False, 0
        key = (msg.message, msg.wParam, msg.time)
        if key == self._last:
            return False, 0
        self._last = key
        self.app.on_system_event(msg.message, msg.wParam)
        return False, 0


class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.store = Store()
        self.store.ensure()
        self.warnings: list[str] = []
        self._obs_last: datetime | None = None  # 마지막 내보내기 시도 시각
        self._obs_error: str | None = None  # 이미 알린 내보내기 오류
        self._load_settings()

        self.collector = Collector(self.store, self.config, self.privacy, self.starts_at, win32.Win32Api())

        # 지난 실행이 남긴 진행 구간 확정, 지난 업무일 원본 요약 후 삭제
        self.store.recover_current(self.starts_at)
        self.day = business_day(datetime.now(), self.starts_at)
        self._finalize_past()
        self._load_day_state()

        # 잠금/절전 알림을 받을 숨은 네이티브 창
        self.sink = QWidget()
        self.sink_hwnd = int(self.sink.winId())
        self._filter = _SessionFilter(self)
        qapp.installNativeEventFilter(self._filter)
        if not win32.register_session_notification(self.sink_hwnd):
            self.warnings.append("화면 잠금 알림 등록에 실패했습니다. 잠금 구간은 자리 비움으로 처리됩니다.")

        self.icon_normal, self.icon_paused = make_icon(False), make_icon(True)
        self.tray = QSystemTrayIcon(self.icon_normal)
        self.tray.setToolTip(APP_NAME)
        self.tray.messageClicked.connect(self.on_message_clicked)
        self._last_msg_kind = None
        self._build_menu()
        self.tray.show()

        self.timer = QTimer()
        # 초 단위 정밀도면 충분: OS가 다른 타이머와 묶어 깨울 수 있어 CPU 깨움이 줄어든다
        self.timer.setTimerType(Qt.VeryCoarseTimer)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(int(float(self.config.get("poll_seconds", 5)) * 1000))
        self.on_tick()

        for w in self.warnings:
            self.notify(w, QSystemTrayIcon.Warning)

    # ---- 설정 ----------------------------------------------------------
    def _load_settings(self) -> None:
        cfg = self.store.load_config()
        rules = self.store.load_rules()
        self.config = cfg.data
        self.rules = rules.data
        for w in (cfg.warning, rules.warning):
            if w:
                self.warnings.append(w)
        try:
            self.privacy = Privacy.from_config(self.config)
        except ValueError as e:
            self.warnings.append(f"제외/마스킹 설정 오류, 해당 항목 없이 동작합니다: {e}")
            self.privacy = Privacy(frozenset(), [], [])
        self.starts_at = day_start_time(self.config)
        self.obsidian_vault = str(self.config.get("obsidian_vault") or "").strip()
        self.obsidian_folder = str(self.config.get("obsidian_folder") or "gohome").strip()
        try:
            self.obsidian_interval = timedelta(minutes=max(1.0, float(self.config.get("obsidian_interval_minutes", 10))))
        except (TypeError, ValueError):
            self.obsidian_interval = timedelta(minutes=10)

    def reload_rules(self) -> None:
        self.warnings = []
        self._load_settings()
        self.collector.apply_config(self.config)
        self.collector.privacy = self.privacy
        self.collector.starts_at = self.starts_at
        self.timer.setInterval(int(float(self.config.get("poll_seconds", 5)) * 1000))
        self.obsidian_act.setEnabled(bool(self.obsidian_vault))
        self._obs_error = None  # 설정을 고쳤을 수 있으니 오류를 다시 알릴 수 있게 한다
        self._export(self.day, self.today_summary())
        if self.warnings:
            for w in self.warnings:
                self.notify(w, QSystemTrayIcon.Warning)
        else:
            self.notify(f"규칙 {len(self.rules)}개와 설정을 다시 읽었습니다.")

    # ---- 메뉴 ----------------------------------------------------------
    def _build_menu(self) -> None:
        menu = QMenu()

        def add(m, text, slot):
            act = QAction(text, m)
            act.triggered.connect(slot)
            m.addAction(act)
            return act

        add(menu, "오늘 요약 복사", self.copy_summary)
        add(menu, "요약 폴더 열기", self.open_summary_dir)
        self.obsidian_act = add(menu, "Obsidian 파일 열기", self.open_obsidian_file)
        self.obsidian_act.setEnabled(bool(self.obsidian_vault))
        menu.addSeparator()
        self.pause_menu = menu.addMenu("일시 정지")
        add(self.pause_menu, "30분", lambda: self.pause(30))
        add(self.pause_menu, "1시간", lambda: self.pause(60))
        add(self.pause_menu, "다시 시작할 때까지", lambda: self.pause(None))
        self.resume_act = add(menu, "재개", self.resume)
        self.resume_act.setEnabled(False)
        menu.addSeparator()
        add(menu, "오늘 기록 삭제", self.delete_today)
        add(menu, "규칙 다시 읽기", self.reload_rules)
        menu.addSeparator()
        add(menu, "종료", self.quit)
        self.menu = menu
        self.tray.setContextMenu(menu)

    def _refresh_pause_ui(self) -> None:
        paused = self.collector.paused
        self.tray.setIcon(self.icon_paused if paused else self.icon_normal)
        self.resume_act.setEnabled(paused)
        until = self.collector.pause_until
        if paused:
            tip = f"{APP_NAME} (일시 정지{f' ~ {until:%H:%M}' if until else ''})"
        else:
            tip = APP_NAME
        self.tray.setToolTip(tip)

    def notify(self, msg: str, icon=QSystemTrayIcon.Information, kind: str | None = None) -> None:
        self._last_msg_kind = kind
        self.tray.showMessage(APP_NAME, msg, icon, 8000 if kind else 4000)

    # ---- 요약 ----------------------------------------------------------
    def _summary_text(self, day: date, records: list[dict], now: datetime) -> str:
        return build_summary(records, self.config, now, self.rules)

    def today_summary(self) -> str:
        now = datetime.now()
        records = self.store.read_records(self.day) + self.collector.snapshot(now)
        return self._summary_text(self.day, records, now)

    def save_today_summary(self) -> str:
        text = self.today_summary()
        try:
            self.store.write_summary(self.day, text)
        except OSError as e:
            self.notify(f"요약 파일 저장 실패: {e}", QSystemTrayIcon.Warning)
        self._export(self.day, text)
        return text

    def copy_summary(self) -> None:
        self._copy(self.save_today_summary())

    def _copy(self, text: str, attempt: int = 0) -> None:
        """클립보드가 다른 프로그램에 잠겨 있으면 잠깐씩 재시도."""
        cb = QApplication.clipboard()
        cb.setText(text)
        if cb.text() == text:
            self.notify("오늘 요약을 클립보드에 복사했습니다.")
            return
        if attempt + 1 < CLIPBOARD_RETRIES:
            QTimer.singleShot(200, lambda: self._copy(text, attempt + 1))
        else:
            self.notify("클립보드를 사용할 수 없어 복사하지 못했습니다. 요약 파일은 저장되었습니다.",
                        QSystemTrayIcon.Warning)

    def open_summary_dir(self) -> None:
        self.store.ensure()
        os.startfile(self.store.summary_dir)

    # ---- Obsidian 내보내기 -----------------------------------------------
    def _export(self, day: date, text: str) -> Path | None:
        """볼트에 요약을 내보낸다. 설정이 없으면 아무것도 안 한다. 성공하면 파일 경로를 돌려준다."""
        if not self.obsidian_vault:
            return None
        self._obs_last = datetime.now()
        vault = Path(self.obsidian_vault)
        try:
            obsidian.write_export(vault, self.obsidian_folder, day, text)
            path = obsidian.export_path(vault, self.obsidian_folder, day)
        except (ValueError, OSError) as e:
            self._report_export_error(f"Obsidian 내보내기 실패: {e}")
            return None
        self._obs_error = None
        return path

    def _report_export_error(self, msg: str) -> None:
        if msg == self._obs_error:
            return
        self._obs_error = msg
        if hasattr(self, "tray"):
            self.notify(msg, QSystemTrayIcon.Warning)
        else:  # 트레이가 만들어지기 전(시작 중)에는 시작 경고로 모은다
            self.warnings.append(msg)

    def _export_if_due(self) -> None:
        if not self.obsidian_vault:
            return
        if self._obs_last is None or datetime.now() - self._obs_last >= self.obsidian_interval:
            self._export(self.day, self.today_summary())

    def open_obsidian_file(self) -> None:
        path = self._export(self.day, self.today_summary())
        if path is not None:
            os.startfile(path)

    def _finalize_past(self) -> None:
        def summarize(day, records):
            _, end = day_bounds(day, self.starts_at)
            text = self._summary_text(day, records, end)
            self._export(day, text)
            return text

        try:
            self.store.finalize_past_days(self.day, summarize)
            self.store.purge_summaries(self.day, int(self.config.get("summary_keep_days", 7)))
        except OSError as e:
            self.warnings.append(f"지난 기록 정리 실패: {e}")

    # ---- 알림 / 퇴근 감지 상태 -------------------------------------------
    def _load_day_state(self) -> None:
        st = self.store.load_state()
        if st.get("day") == self.day.isoformat():
            self.alarm_done = bool(st.get("alarm_done"))
            self.leave_done = bool(st.get("leave_done"))
        else:
            self.alarm_done = self.leave_done = False

    def _save_day_state(self) -> None:
        try:
            self.store.save_state({"day": self.day.isoformat(), "alarm_done": self.alarm_done,
                                   "leave_done": self.leave_done})
        except OSError:
            pass

    def _alarm_at(self) -> datetime:
        t = parse_hhmm(self.config.get("alarm_time", "17:50"), "17:50")
        at = datetime.combine(self.day, t)
        if t < self.starts_at:
            at += timedelta(days=1)
        return at

    def _left_work(self, now: datetime) -> bool:
        reason = self.collector.idle_reason()
        if reason in ("lock", "sleep"):
            return True
        leave = timedelta(minutes=float(self.config.get("leave_idle_minutes", 30)))
        return reason == "away" and self.collector.idle_duration(now) >= leave

    def check_schedule(self) -> None:
        now = datetime.now()
        # 업무일 경계: 전 업무일 요약을 마지막으로 만들고 원본 삭제
        today = business_day(now, self.starts_at)
        if today != self.day:
            self.collector.checkpoint(now)
            self.day = today
            self._finalize_past()
            self.alarm_done = self.leave_done = False
            self._save_day_state()

        if not self.alarm_done and now >= self._alarm_at():
            self.alarm_done = True
            self.save_today_summary()
            if now - self._alarm_at() <= LATE_ALARM_WINDOW:
                self.notify(ALARM_TEXT, kind="alarm")
            # 알림 시각에 이미 자리 비움/잠금이면 퇴근 감지 즉시 충족
            if self.collector.idle_reason() in ("away", "lock", "sleep"):
                self.leave_done = True
            self._save_day_state()
            return

        if self.alarm_done and not self.leave_done and self._left_work(now):
            self.leave_done = True
            self.save_today_summary()  # 최종본. 클립보드는 건드리지 않는다
            self._save_day_state()

    # ---- 이벤트 --------------------------------------------------------
    def on_tick(self) -> None:
        self.collector.tick()
        if self.collector.paused != (self.resume_act.isEnabled()):
            self._refresh_pause_ui()
        self.check_schedule()
        self._export_if_due()

    def on_system_event(self, message: int, wparam: int) -> None:
        if message == win32.WM_WTSSESSION_CHANGE:
            if wparam == win32.WTS_SESSION_LOCK:
                self.collector.on_lock()
            elif wparam == win32.WTS_SESSION_UNLOCK:
                self.collector.on_unlock()
        elif message == win32.WM_POWERBROADCAST:
            if wparam == win32.PBT_APMSUSPEND:
                self.collector.on_suspend()
            elif wparam in (win32.PBT_APMRESUMEAUTOMATIC, win32.PBT_APMRESUMESUSPEND):
                self.collector.on_resume()
        self.check_schedule()

    def on_message_clicked(self) -> None:
        if self._last_msg_kind == "alarm":
            self._last_msg_kind = None
            self.copy_summary()

    def pause(self, minutes: int | None) -> None:
        self.collector.pause(minutes)
        self._refresh_pause_ui()

    def resume(self) -> None:
        self.collector.resume()
        self._refresh_pause_ui()

    def delete_today(self) -> None:
        ans = QMessageBox.question(
            None, APP_NAME,
            "오늘 기록(원본과 오늘 요약 파일)을 지금 삭제할까요?"
            + (" (Obsidian에 내보낸 오늘 파일 포함)" if self.obsidian_vault else "")
            + "\n되돌릴 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self.collector.discard_current()
        self.store.delete_day(self.day)
        if self.obsidian_vault:
            try:
                obsidian.delete_export(Path(self.obsidian_vault), self.obsidian_folder, self.day)
            except (ValueError, OSError) as e:
                self._report_export_error(f"Obsidian 파일 삭제 실패: {e}")
        self.notify("오늘 기록을 삭제했습니다.")

    def quit(self) -> None:
        self.timer.stop()
        try:
            self.collector.stop()
        except OSError:
            pass
        try:
            self._export(self.day, self.today_summary())
        except Exception:  # 종료 처리를 깨지 않는다
            pass
        win32.unregister_session_notification(self.sink_hwnd)
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
    qapp.aboutToQuit.connect(lambda: app.collector.stop())
    return qapp.exec()
