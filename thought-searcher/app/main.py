"""트레이 상주, 단일 실행, 메뉴, 스케줄, 알림."""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QSystemTrayIcon

from . import hotkey as hk
from . import settings as S
from . import theme as T
from .ask import OFF_MESSAGE, AskError
from .core import Core, setup_logging
from .hotkey import HotkeyManager
from .index import connect, fts5_available
from .query import parse as parse_query
from .queue import QueueItem, QueueResult
from .tokenize import normalize
from .search import DEFAULT_WEIGHTS, Hit, Searcher
from .settings_window import Hooks, SettingsWindow
from .store import Store
from .watcher import ZipPoller
from .window import SearchWindow

APP_NAME = "생각 검색기"
MUTEX_NAME = "Local\\GCxEnding.small-win-tools.thought-searcher"
ERROR_ALREADY_EXISTS = 183
POLL_MS = 2000
REMINDER_CHECK_MS = 60 * 60 * 1000
log = logging.getLogger("thought-searcher")


def acquire_single_instance():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def make_icon(warn: bool = False, busy: bool = False) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        f = QFont("Segoe UI Emoji")
        f.setPixelSize(int(size * 0.8))
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, "🧠")
        if warn or busy:
            f.setPixelSize(int(size * 0.55))
            p.setFont(f)
            p.drawText(pm.rect(), Qt.AlignRight | Qt.AlignBottom, "⚠" if warn else "⏳")
        p.end()
        icon.addPixmap(pm)
    return icon


def swap_hotkey(mgr: HotkeyManager, text: str) -> tuple[bool, str]:
    """새 키를 먼저 등록해 보고, 성공하면 옛 키를 해제한다 (SPEC-settings.md 3-E-4). 실패하면 옛 키 그대로.
    hotkey.py는 emoji-searcher 복사본이라 고치지 않고 여기서 ID를 번갈아 쓴다(같은 ID로 두 번 등록하지 않게)."""
    if mgr.registered and S.same_hotkey(mgr.registered, text):
        return True, ""
    try:
        mods, vk = hk.parse_hotkey(text)
    except ValueError as e:
        return False, str(e)
    old_id = mgr.HOTKEY_ID
    new_id = HotkeyManager.HOTKEY_ID + 1 if old_id == HotkeyManager.HOTKEY_ID else HotkeyManager.HOTKEY_ID
    if not hk.user32.RegisterHotKey(mgr.hwnd, new_id, mods | hk.MOD_NOREPEAT, vk):
        err = ctypes.get_last_error()
        return False, ctypes.FormatError(err).strip() if err else "등록 실패"
    if mgr.registered:
        hk.user32.UnregisterHotKey(mgr.hwnd, old_id)
    mgr.HOTKEY_ID = new_id        # 인스턴스 값: 이후 unregister()가 이 ID를 해제한다
    mgr.registered = text
    return True, ""


PROJECT_MENU_MAX = 40


def filter_queue(res, q, focus: int):
    """큐 결과를 검색어의 필터(src:, after:, before:, proj:)로 거른다. 일지 항목은 src:journal."""
    srcs = set(q.sources)
    after = datetime.combine(q.after, datetime.min.time()).timestamp() if q.after else None
    before = datetime.combine(q.before, datetime.min.time()).timestamp() if q.before else None

    def keep(it) -> bool:
        if srcs and it.source not in srcs:
            return False
        if after is not None and it.trace_ts < after:
            return False
        if before is not None and it.trace_ts >= before:
            return False
        proj = normalize(it.project or "")
        return all(p in proj for p in q.projects)

    items = [it for it in (*res.focus, *res.rest) if keep(it)]
    n = max(0, focus)
    return QueueResult(items[:n], items[n:], [it for it in res.closed if keep(it)], res.days)


def project_names(conn, limit: int = PROJECT_MENU_MAX) -> list[str]:
    rows = conn.execute(
        "SELECT project FROM docs WHERE project IS NOT NULL AND trim(project) != '' AND source != 'note' "
        "GROUP BY project ORDER BY max(updated_ts) DESC LIMIT ?", (limit,)).fetchall()
    return [r[0] for r in rows]


class Bridge(QObject):
    """작업 스레드 -> GUI 스레드."""
    done = Signal(str, object)
    progress = Signal(int, int)
    started = Signal(str)
    step = Signal(str)


class Worker:
    """수집, 가져오기, 색인 작업을 순서대로 하나씩 처리하는 백그라운드 스레드."""

    def __init__(self, bridge: Bridge):
        self.q: queue.Queue = queue.Queue()
        self.bridge = bridge
        self.pending: set[str] = set()
        self.t = threading.Thread(target=self._run, name="thought-worker", daemon=True)
        self.t.start()

    def submit(self, name: str, fn, dedupe: bool = True) -> None:
        if dedupe and name in self.pending:
            return
        self.pending.add(name)
        self.q.put((name, fn))

    def _run(self):
        while True:
            name, fn = self.q.get()
            self.bridge.started.emit(name)
            try:
                result = fn()
            except Exception as e:  # noqa: BLE001
                log.exception("작업 실패: %s", name)
                result = e
            self.pending.discard(name)
            self.bridge.done.emit(name, result)


class AskBridge(QObject):
    """요약 작업 스레드 -> 화면 스레드."""
    finished = Signal(str, object, object)    # (id, 요약 또는 None, 실패 사유 또는 None)


class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.core = Core(create_config=False)
        # config.json이 없는 첫 실행: 시작 안내가 끝날 때까지 수집하지 않는다 (SPEC-settings.md 3-K)
        self._setup_pending = self.core.store.config_missing
        self.settings_win: SettingsWindow | None = None
        self._paused_hotkey = ""
        self.bridge = Bridge()
        self.bridge.done.connect(self.on_job_done)
        self.bridge.progress.connect(self.on_progress)
        self.bridge.started.connect(self.on_job_started)
        self.bridge.step.connect(self.set_busy)
        self._busy = ""
        self._batch: dict | None = None    # '지금 가져오기'로 시작한 작업 묶음
        self.worker = Worker(self.bridge)
        self.poller = ZipPoller()
        self._notice_kind = ""
        self._last_query = ""
        self._archive_was_ok = None

        self.core.index.open().close()   # 깨졌거나 버전이 다르면 여기서 새로 만든다
        self.search_conn = connect(self.core.store.index_path)
        self.searcher = Searcher(self.search_conn, self.core.config.get("weights"),
                                 int(self.core.config.get("max_results", 50)))

        self.theme = T.from_config(self.core.config)
        T.apply_app(qapp, self.theme)
        self.window = SearchWindow(self.theme, state_path=self.core.store.ui_state_path,
                                   projects=self.project_names)
        try:                              # 시스템 모드: Windows 앱 모드가 바뀌면 따라간다 (Qt 6.5+)
            qapp.styleHints().colorSchemeChanged.connect(lambda _s: self.apply_theme())
        except AttributeError:
            pass
        self.window.searchRequested.connect(self.on_query)
        self.window.action.connect(self.on_action)
        self.window.settingsRequested.connect(self._settings_from_search)
        self.window.set_ask_enabled(self.core.ask_provider != "off")
        self.ask_bridge = AskBridge()
        self.ask_bridge.finished.connect(self.on_ask_finished)
        self._asking: set[str] = set()

        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip(APP_NAME)
        self.tray.messageClicked.connect(self.on_message_clicked)
        self.tray.activated.connect(self.on_tray_activated)
        self.menu = QMenu()
        self.act_search = self._add("검색", self.show_search)
        self._add("설정...", lambda: self.open_settings())
        self.menu.addSeparator()
        self._add("지금 가져오기", self.import_now)
        self.act_export = self._add("claude.ai 내보내기 받으러 가기", self.open_export_page)
        self.menu.addSeparator()
        self._add("대화 보관 폴더 열기", self.open_archive)
        self._add("상태 보기", self.show_status)
        adv = self.menu.addMenu("고급")
        self._add("zip 파일 직접 고르기...", self.import_zip_dialog, adv)
        adv.addSeparator()
        self._add("검색 색인 다시 만들기", self.rebuild_index, adv)
        self._add("대화 md 전부 다시 만들기", self.rebuild_all, adv)
        self.menu.addSeparator()
        self._add("종료", self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.hotkey = HotkeyManager(qapp)
        self.hotkey.activated.connect(self.toggle)
        key = str(self.core.config.get("hotkey") or S.DEFAULT_HOTKEY)
        ok, why = self.hotkey.register(key)
        if not ok:
            self.notify(f"단축키 {S.display_hotkey(key)} 등록 실패({why}).\n트레이 메뉴 '검색'으로 사용하세요. "
                        "설정 > 일반에서 바꿀 수 있습니다.", QSystemTrayIcon.Warning, kind="hotkey")
        self._refresh_menu()

        for w in list(self.core.warnings):
            self.notify(w, QSystemTrayIcon.Warning)

        if self._setup_pending:
            QTimer.singleShot(1000, lambda: self.open_settings(setup=True))
        else:
            self.start_jobs()

        self.fs = QFileSystemWatcher()
        self._watch_folder()
        self.fs.directoryChanged.connect(lambda _p: self.poll_zips())
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_zips)
        self.poll_timer.start(POLL_MS)
        self.collect_timer = QTimer()
        self.collect_timer.timeout.connect(self.collect_now)
        self.collect_timer.start(max(1, int(self.core.config.get("code_collect_minutes") or 30)) * 60_000)
        self.reminder_timer = QTimer()
        self.reminder_timer.timeout.connect(self.check_reminder)
        self.reminder_timer.start(REMINDER_CHECK_MS)
        QTimer.singleShot(8000, self.check_reminder)

    # ---- 도우미 ---------------------------------------------------------
    def _add(self, text, slot, menu=None) -> QAction:
        menu = menu or self.menu
        act = QAction(text, menu)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _refresh_menu(self) -> None:
        """검색 메뉴의 단축키 글자, 쓰는 서비스에 따른 메뉴 숨김."""
        key = self.hotkey.registered or str(self.core.config.get("hotkey") or S.DEFAULT_HOTKEY)
        self.act_search.setText(f"검색 ({S.display_hotkey(key)})")
        self.act_export.setVisible(self.core.service_on("claude_ai"))

    def notify(self, msg: str, icon=QSystemTrayIcon.Information, kind: str = "") -> None:
        self._notice_kind = kind
        log.info("알림: %s", msg.replace("\n", " / "))
        self.tray.showMessage(APP_NAME, msg, icon, 6000)

    def _watch_folder(self):
        try:
            if self.fs.directories():
                self.fs.removePaths(self.fs.directories())
            for d in (str(self.core.watch_dir), str(self.core.capture_dir)):
                if os.path.isdir(d):
                    self.fs.addPath(d)
        except Exception:  # noqa: BLE001
            log.exception("감시 폴더 등록 실패")

    def update_archive_state(self) -> bool:
        ok = self.core.archive_ok()
        if ok != self._archive_was_ok:
            self.tray.setIcon(make_icon(warn=not ok))
            if not ok:
                d = self.core.archive_dir
                msg = (f"보관 폴더가 없습니다: {d}\n가져오기를 멈췄습니다. 트레이 메뉴 '설정...'에서 고르세요."
                       if d else "보관 폴더가 설정되지 않아 가져오기를 멈췄습니다. 트레이 메뉴 '설정...'에서 고르세요.")
                self.tray.setToolTip(f"{APP_NAME} ⚠ 보관 폴더 없음")
                if self._archive_was_ok is not None or d:
                    self.notify(msg, QSystemTrayIcon.Warning, kind="archive")
                self.core._warn(msg.split("\n")[0])
            else:
                self.tray.setToolTip(APP_NAME)
                if self._archive_was_ok is False:
                    self.start_jobs()
            self._archive_was_ok = ok
        return ok

    # ---- 시작 ---------------------------------------------------------
    def start_jobs(self):
        if self._setup_pending or not self.update_archive_state():
            return
        self.worker.submit("sync", lambda: self.core.sync_index(self._progress))
        self.worker.submit("collect", self._collect)
        n_old = self.core.old_format_count()
        if n_old:
            self.notify(f"예전 형식 md {n_old}개가 있습니다. 트레이 메뉴 '고급 > 대화 md 전부 다시 만들기'를 실행하세요.")

    def _progress(self, done: int, total: int):
        self.bridge.progress.emit(done, total)

    def _collect(self):
        return self.core.collect_code(
            progress=lambda i, n: self.bridge.step.emit(f"Claude Code 대화 가져오는 중 ({i}/{n})"))

    def _code_label(self) -> str:
        """켠 서비스 기준의 'Claude Code, Codex 대화' 글자. 둘 다 껐으면 빈 문자열."""
        src = self.core.sources
        names = [n for n, on in (("Claude Code", src["claude_code"]), ("Codex", src["codex"])) if on]
        return f"{', '.join(names)} 대화" if names else ""

    # ---- 진행 표시 ---------------------------------------------------------
    JOB_LABELS = {"sync": "검색 색인 확인 중", "notes": "노트 폴더 확인 중",
                  "rebuild-index": "검색 색인 다시 만드는 중", "rebuild-all": "대화 md 다시 만드는 중",
                  "capture": "자동 수집 파일 가져오는 중"}

    def on_job_started(self, name: str):
        if name.startswith("zip:"):
            self.set_busy(f"zip 가져오는 중 ({Path(name[4:]).name})")
        elif name == "collect":
            self.set_busy(f"{self._code_label() or '대화'} 가져오는 중")
        else:
            self.set_busy(self.JOB_LABELS.get(name, "작업 중"))

    def set_busy(self, text: str):
        """트레이 아이콘(⏳), 툴팁, 검색 창 상태 줄에 진행 상황을 보여 준다. 빈 문자열이면 끝."""
        self._busy = text
        if text:
            self.tray.setIcon(make_icon(busy=True))
            self.tray.setToolTip(f"{APP_NAME} - {text}")
        else:
            self.tray.setIcon(make_icon(warn=not self.core.archive_ok()))
            self.tray.setToolTip(APP_NAME if self.core.archive_ok() else f"{APP_NAME} ⚠ 보관 폴더 없음")
        if self.window.isVisible():
            self.window.status.setText(self._compose_status(self.window.list.count()))

    # ---- 작업 ------------------------------------------------------------
    def import_now(self):
        """Code 세션 수집 + 감시 폴더의 아직 안 가져온 zip 즉시 확인."""
        if self._setup_pending:
            self.notify("시작 안내를 마치면 가져오기를 시작합니다.")
            return
        if not self.update_archive_state():
            return
        if self._batch is not None:
            self.notify("이미 가져오는 중입니다. 끝나면 알려 드릴게요.")
            return
        self._batch = {"names": {"collect", "sync", "capture"}, "new": 0, "changed": 0, "zips": 0, "failed": []}
        self.worker.submit("sync", lambda: self.core.sync_index(self._progress))   # 직접 넣은 md 반영
        self.worker.submit("collect", self._collect)
        self.worker.submit("capture", self.core.import_captures)
        n = 0
        now = time.time()
        for p in sorted(self.core.watch_dir.glob("*.zip")):
            try:
                if now - p.stat().st_mtime < 5 or self.core.known_zip(p):
                    continue
            except OSError:
                continue
            self.poller.mark_done(p)
            self._batch["names"].add(f"zip:{p}")
            self.worker.submit(f"zip:{p}", lambda p=p: self.core.import_zip(p))
            n += 1
        parts = [p for p in (self._code_label(), f"새 zip {n}개" if n else "") if p]
        self.notify("가져오는 중입니다" + (f" ({' + '.join(parts)})" if parts else "") + ". 끝나면 알려 드릴게요.")

    def collect_now(self):
        if self._setup_pending:
            return
        if self.update_archive_state():
            self.worker.submit("collect", self._collect)
        self.worker.submit("notes", self.core.sync_notes)

    def poll_zips(self):
        if self._setup_pending:
            return
        if not self.core.archive_ok():
            self.update_archive_state()
            return
        if self._archive_was_ok is False:
            self.update_archive_state()
        if "capture" not in self.worker.pending and (self.core.pending_captures() or self.core.exclusions_pending()):
            self.worker.submit("capture", self.core.import_captures)   # 폴더 감시가 없어도 2초 확인으로 잡힘
        for p in self.poller.poll(self.core.watch_dir):
            self.poller.mark_done(p)
            if self.core.known_zip(p):
                continue
            self.worker.submit(f"zip:{p}", lambda p=p: self.core.import_zip(p))

    def import_zip_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(None, "가져올 zip 파일", str(self.core.watch_dir), "zip (*.zip)")
        for f in files:
            self.worker.submit(f"zip:{f}", lambda f=f: self.core.import_zip(Path(f)), dedupe=False)

    def rebuild_index(self):
        if not self.update_archive_state():
            return
        self.core.index.progress = (0, 0)
        self.worker.submit("rebuild-index", lambda: self.core.rebuild_index(self._progress))

    def rebuild_all(self):
        if not self.update_archive_state():
            return
        self.notify("내보내기 zip과 Code 세션에서 대화 md를 다시 만듭니다.")
        self.worker.submit("rebuild-all", self.core.rebuild_all)

    def on_progress(self, done: int, total: int):
        if self.worker.pending & {"rebuild-index", "sync"} and done < total:
            self.core.index.progress = (done, total)
            self.set_busy(f"검색 색인 만드는 중 ({done}/{total})")
        else:
            self.core.index.progress = None
        if self.window.isVisible():
            self.on_query(self._last_query)

    def on_job_done(self, name: str, result):
        try:
            self._job_done(name, result)
        finally:
            if not self.worker.pending:
                self.set_busy("")

    def _batch_done(self, name: str, result) -> bool:
        """'지금 가져오기' 묶음이면 결과를 모으고, 묶음이 다 끝나면 완료 알림 하나만 띄운다."""
        b = self._batch
        if b is None or name not in b["names"]:
            return False
        b["names"].discard(name)
        if isinstance(result, Exception):
            b["failed"].append(str(result))
        elif name in ("collect", "capture") and result is not None:
            b["new"] += result.new
            b["changed"] += result.changed
            b["failed"] += list(getattr(result, "failed", []))[:3]
        elif name.startswith("zip:"):
            if result.result == "ok":
                b["zips"] += 1
                b["new"] += result.counts.get("new", 0)
                b["changed"] += result.counts.get("changed", 0)
            elif result.result == "failed":
                b["failed"].append(result.reason)
        if not b["names"]:
            self._batch = None
            if b["failed"]:
                self.notify("가져오기를 마쳤지만 실패한 것이 있습니다: " + "; ".join(b["failed"])[:200],
                            QSystemTrayIcon.Warning)
            elif b["new"] or b["changed"]:
                self.notify(f"가져오기 완료: 새 대화 {b['new']}개, 바뀐 대화 {b['changed']}개")
            else:
                self.notify("가져오기 완료: 새로 바뀐 대화가 없습니다.")
        return True

    def _job_done(self, name: str, result):
        if self._batch_done(name, result):
            if self.window.isVisible():
                self.on_query(self._last_query)
            return
        if isinstance(result, Exception):
            self.core._warn(f"{name} 실패: {result}")
            self.notify(f"작업 실패({name}): {result}", QSystemTrayIcon.Warning)
            return
        if name.startswith("zip:"):
            if result.result in ("ok", "failed"):
                self.notify(result.message(), QSystemTrayIcon.Information if result.result == "ok"
                            else QSystemTrayIcon.Warning)
            elif result.result == "no_archive":
                self.poller.done.clear()   # 폴더가 돌아오면 다시 시도
        elif name == "rebuild-index":
            self.core.index.progress = None
            self.notify("색인을 다시 만들었습니다.")
        elif name == "rebuild-all":
            r = result
            msg = f"다시 변환 완료: zip {r['zips']}개"
            if r["zip_missing"]:
                msg += f" (파일이 없어 건너뜀 {r['zip_missing']}개)"
            self.notify(msg)
        elif name == "sync":
            self.core.index.progress = None
        elif name == "capture" and result.failed:
            for f in result.failed[:3]:
                self.core._warn(f"claude.ai 수집 파일: {f}")
            self.notify("claude.ai 수집 파일을 읽지 못했습니다: " + "; ".join(result.failed)[:200],
                        QSystemTrayIcon.Warning)
        if self.window.isVisible():
            self.on_query(self._last_query)

    # ---- 알림 ------------------------------------------------------------
    def check_reminder(self):
        if self._setup_pending:
            return
        msg = self.core.reminder_due()
        if msg:
            self.core.mark_reminded()
            self.notify(msg, kind="reminder")
            return
        msg = self.core.capture_notice()
        if msg:
            self.notify(msg, QSystemTrayIcon.Warning)

    def on_message_clicked(self):
        if self._notice_kind == "reminder":
            self.open_export_page()
        elif self._notice_kind in ("archive", "hotkey"):
            self.open_settings("general")

    # ---- 설정 창 (SPEC-settings.md) ---------------------------------------------
    def _settings_from_search(self):
        self.window.hide()
        self.open_settings()

    def open_settings(self, tab: str | None = None, setup: bool = False):
        """창은 하나만. 이미 열려 있으면 앞으로 가져온다."""
        w = self.settings_win
        if w is not None:
            try:
                if w.isVisible():
                    if tab and not w.setup_mode:
                        w.select_tab(tab)
                    w.raise_()
                    w.activateWindow()
                    return
            except RuntimeError:          # 이미 지워진 창
                pass
        hooks = Hooks(open_url=lambda url: QDesktopServices.openUrl(QUrl(url)), try_hotkey=self._try_hotkey,
                      recording=self._hotkey_recording, applied=self.apply_settings,
                      setup_finished=self._setup_finished)
        busy = T.BusyNote(self.theme, "설정 창 여는 중…")    # 만드는 데 몇 초 걸린다
        try:
            w = SettingsWindow(self.core, hooks, setup=setup, tab=tab or "general")
        finally:
            busy.done()
        w.finished.connect(lambda _r: setattr(self, "settings_win", None))
        self.settings_win = w
        T.show_without_flash(w)            # 처음 그리기 전 빈 회색 창이 보이지 않게
        w.raise_()
        w.activateWindow()

    def _try_hotkey(self, text: str) -> tuple[bool, str]:
        ok, why = swap_hotkey(self.hotkey, text)
        if ok:
            log.info("단축키 교체: %s", text)
            self._refresh_menu()
        return ok, why

    def _hotkey_recording(self, on: bool):
        """설정 창 단축키 칸이 기록 중이면 전역 키를 잠시 풀어 같은 조합도 기록되게 한다."""
        if on and self.hotkey.registered:
            self._paused_hotkey = self.hotkey.registered
            self.hotkey.unregister()
        elif not on and self._paused_hotkey:
            key, self._paused_hotkey = self._paused_hotkey, ""
            ok, why = self.hotkey.register(key)
            if not ok:
                log.warning("단축키 다시 등록 실패 %s: %s", key, why)

    def apply_settings(self, changed: set, old: dict, start: bool = True):
        """저장 즉시 적용 (SPEC-settings.md 3-F). 바뀐 키만. 본체 쪽(Redactor, 노트 폴더)은 Core.update_config가 했다."""
        if not changed:
            return
        new = self.core.config
        log.info("설정 바뀜: %s", ", ".join(sorted(changed)))
        if changed & {"hotkey", "sources"}:
            self._refresh_menu()
        if changed & {"sources", "watch_dir", "capture_dir"}:
            self._watch_folder()
            self.poller.done.clear()          # 새로 켠 서비스의 zip을 다시 보게
        if "code_collect_minutes" in changed:
            self.collect_timer.start(max(1, self.core._int_cfg("code_collect_minutes", 30)) * 60_000)
        if changed & {"weights", "max_results"}:
            self.searcher.w = {**DEFAULT_WEIGHTS, **(new.get("weights") or {})}
            self.searcher.max_results = self.core._int_cfg("max_results", 50)
        if "ask_provider" in changed:
            self.window.set_ask_enabled(self.core.ask_provider != "off")
        if changed & {"theme_mode", "theme_accent"}:
            self.apply_theme()
        if start and not self._setup_pending:
            if "archive_dir" in changed:
                self._archive_was_ok = None
                self.start_jobs()
            if "note_dirs" in changed:
                self.worker.submit("notes", self.core.sync_notes)
            was, now = S.read_sources(old), self.core.sources
            if any(now[s] and not was[s] for s in S.SERVICES) and self._batch is None:
                self.import_now()             # 새로 켠 서비스: '지금 가져오기'와 같은 작업
        if self.window.isVisible():
            self.on_query(self._last_query)

    def apply_theme(self):
        """설정의 모드, 강조색(시스템 모드면 지금 Windows 앱 모드)으로 앱 전체를 다시 칠한다."""
        self.theme = T.from_config(self.core.config)
        T.apply_app(self.qapp, self.theme)
        self.window.set_theme(self.theme)
        w = self.settings_win
        if w is not None:
            try:
                w.system_theme_changed()
            except RuntimeError:          # 이미 지워진 창
                pass

    def _setup_finished(self, finished: bool, changed: set, old: dict):
        self._setup_pending = False
        self.apply_settings(changed, old, start=False)
        self._archive_was_ok = None
        self.start_jobs()
        self.worker.submit("notes", self.core.sync_notes)
        if finished:
            key = S.display_hotkey(self.hotkey.registered or str(self.core.config.get("hotkey") or S.DEFAULT_HOTKEY))
            self.notify(f"준비됐습니다. {key}로 검색 창을 엽니다.")
        else:
            self.notify("설정은 트레이 메뉴 '설정...'에서 바꿀 수 있습니다.")

    def open_export_page(self):
        QDesktopServices.openUrl(QUrl(str(self.core.config.get("export_page_url"))))

    # ---- 검색 ------------------------------------------------------------
    def toggle(self):
        if self.window.isVisible():
            self.window.hide()
        else:
            self.show_search()

    def show_search(self):
        self.window.popup()

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_search()

    def on_query(self, text: str):
        self._last_query = text
        if not text.strip():
            self.show_queue()
            return
        q = parse_query(text)
        if not q.has_text and not q.excludes and not q.title_excludes:
            # 단어 없이 칩(필터)만: 열린 일 큐를 그 조건으로 거른다 (일지 항목도 남는다).
            # 거른 큐가 비면(메모리, 프로젝트 문서처럼 큐에 오르지 않는 출처 등) 아래 검색으로 넘어간다
            if self.show_queue(filters=q):
                return
        try:
            self.searcher.journal_dir = str(self.core.journal_dir or "")
            hits = self.searcher.search(text)
        except Exception as e:  # noqa: BLE001
            log.exception("검색 실패")
            self.window.set_results([], f"검색 오류: {e}")
            return
        self.window.set_results(hits, self._compose_status(len(hits)))

    def project_names(self) -> list[str]:
        """프로젝트 칩 메뉴: 색인의 프로젝트 이름, 최근에 쓴 것부터 (노트는 폴더 경로라 뺀다)."""
        return project_names(self.search_conn)

    def _compose_status(self, n_hits: int) -> str:
        if n_hits:
            status = f"{n_hits}건 · {self.searcher.last_ms:.0f}ms"
        else:
            q = self.searcher.last_query
            labels = q.filter_labels() if q else []
            status = "결과 없음" + (f"   필터: {' '.join(labels)}" if labels else "")
        if self._busy:
            status = f"⏳ {self._busy}   ·   {status}"
        if not self.core.archive_ok():
            status += "   ⚠ 보관 폴더 없음"
        return status

    def show_queue(self, keep: str | None = None, filters=None) -> bool:
        """열린 일 큐. filters(검색어 Query)가 있으면 출처, 기간, 프로젝트로 거른다.
        거른 결과가 비면 그리지 않고 False (호출한 쪽이 검색으로 넘어간다)."""
        now = time.time()
        t0 = time.perf_counter()
        days = None
        if filters is not None and filters.after:
            after_ts = datetime.combine(filters.after, datetime.min.time()).timestamp()
            days = int((now - after_ts) // 86400) + 1
        try:
            res = self.core.compute_queue(self.search_conn, now, days)
        except Exception as e:  # noqa: BLE001
            log.exception("큐 계산 실패")
            self.window.set_results([], f"열린 일 계산 오류: {e}")
            return True
        if filters is not None:
            res = filter_queue(res, filters, self.core._int_cfg("queue_focus", 5, lo=0))
            if not res.open_count and not res.closed:
                return False
        ms = (time.perf_counter() - t0) * 1000
        status = f"열린 일 {res.open_count}개 · 최근 {res.days}일 · {ms:.0f}ms"
        if filters is not None:
            status += f"   필터: {' '.join(filters.filter_labels())}"
        if self._busy:
            status = f"⏳ {self._busy}   ·   {status}"
        if not self.core.archive_ok():
            status += "   ⚠ 보관 폴더 없음"
        self.window.set_queue(res, status, now, keep)
        return True

    def on_queue_action(self, kind: str, item: QueueItem):
        if kind == "open":
            self.window.hide()
            self.open_md(Path(item.path), item.line)
        elif kind == "copy_conv":
            try:
                text = Path(item.path).read_text(encoding="utf-8")
            except OSError as e:
                self.notify(f"파일을 읽지 못했습니다: {e}", QSystemTrayIcon.Warning)
                return
            QApplication.clipboard().setText(text)
            self.window.hide()
            self.notify("복사됨 (대화 전체)")
        elif kind in ("done", "drop"):
            self.core.close_item(item.id, kind)
            self.show_queue(keep=None)
        elif kind == "reopen":
            self.core.reopen_item(item.id)
            self.show_queue(keep=item.id)
        elif kind == "summary":
            self.start_summary(item)

    # ---- 요약 (F2) ---------------------------------------------------------
    def start_summary(self, item: QueueItem):
        if item.id in self._asking:
            return
        if self.core.ask_provider == "off":
            self.window.set_ask_state(item.id, OFF_MESSAGE)
            return
        self._asking.add(item.id)
        self.window.set_ask_state(item.id, f"⏳ 요약 중... ({self.core.ask_model_label()})")
        threading.Thread(target=self._summary_thread, args=(item,), name="ask", daemon=True).start()

    def _summary_thread(self, item: QueueItem):
        try:
            text = self.core.summarize(item)
            self.ask_bridge.finished.emit(item.id, text, None)
        except AskError as e:
            self.ask_bridge.finished.emit(item.id, None, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("요약 실패")
            self.ask_bridge.finished.emit(item.id, None, f"오류: {e}")

    def on_ask_finished(self, item_id: str, text, err):
        self._asking.discard(item_id)
        if err:
            log.warning("요약 실패 %s: %s", item_id, err)
            self.window.set_ask_state(item_id, f"⚠ 요약 실패: {err}")
            self.notify(f"요약 실패: {err}", QSystemTrayIcon.Warning)
            return
        self.window.set_ask_state(item_id, None)
        if self.window.isVisible() and self.window.mode == "queue":
            self.show_queue(keep=item_id)

    def on_action(self, kind: str, hit, idx: int):
        if isinstance(hit, QueueItem):
            self.on_queue_action(kind, hit)
            return
        m = hit.matches[min(idx, len(hit.matches) - 1)] if hit.matches else None
        if kind == "open":
            self.window.hide()
            self.open_md(hit.path, m.line_no if m else 1)
        elif kind == "copy_msg" and m:
            text = self.searcher.message_text(m.message_id)
            QApplication.clipboard().setText(text)
            self.window.hide()
            self.notify("복사됨 (메시지)")
        elif kind == "copy_conv":
            try:
                text = hit.path.read_text(encoding="utf-8")
            except OSError as e:
                self.notify(f"md를 읽지 못했습니다: {e}", QSystemTrayIcon.Warning)
                return
            QApplication.clipboard().setText(text)
            self.window.hide()
            self.notify("복사됨 (대화 전체)")

    def open_md(self, path: Path, line: int):
        cmd = self.core.config.get("open_command") or []
        try:
            if not cmd:
                raise FileNotFoundError("open_command 없음")
            args = [str(a).replace("{path}", str(path)).replace("{line}", str(line)) for a in cmd]
            exe = shutil.which(args[0]) or args[0]
            subprocess.Popen([exe, *args[1:]], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log.warning("open_command 실패(%s), 기본 프로그램으로 엽니다", e)
            try:
                os.startfile(str(path))
            except OSError as e2:
                self.notify(f"md를 열지 못했습니다: {e2}", QSystemTrayIcon.Warning)

    # ---- 메뉴 ------------------------------------------------------------
    def open_archive(self):
        d = self.core.archive_dir
        if d and d.is_dir():
            os.startfile(str(d))
        else:
            self.notify("대화 보관 폴더가 없습니다. 트레이 메뉴 '설정...'에서 고르세요.", QSystemTrayIcon.Warning,
                        kind="archive")

    def show_status(self):
        box = QMessageBox()
        box.setWindowTitle(f"{APP_NAME} 상태")
        box.setText(self.core.status_text())
        box.setWindowFlag(Qt.WindowStaysOnTopHint)
        box.exec()

    def quit(self):
        self.hotkey.unregister()
        self.tray.hide()
        self.qapp.quit()


def _install_error_log(store: Store) -> None:
    def hook(etype, value, tb):
        log.error("처리되지 않은 예외\n%s", "".join(traceback.format_exception(etype, value, tb)))
        sys.__excepthook__(etype, value, tb)

    sys.excepthook = hook


def main() -> int:
    store = Store()
    setup_logging(store)
    _install_error_log(store)
    mutex = acquire_single_instance()
    if mutex is None:
        return 0
    qapp = QApplication(sys.argv)
    T.install_fast_tips(qapp)          # 툴팁 0.2초 (App이 팔레트를 그 뒤에 입힌다)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setStyle("Fusion")       # Windows 기본 스타일은 입력칸 테두리 등 스타일시트 일부를 무시한다 (theme.py)
    if not fts5_available():
        QMessageBox.critical(None, APP_NAME, "이 Python의 sqlite3에 FTS5가 없습니다.\n"
                                             "python.org 배포판 Python 3.10 이상으로 실행하세요.")
        return 2
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 1
    log.info("시작 %s", datetime.now().isoformat(timespec="seconds"))
    app = App(qapp)  # noqa: F841  (수명 유지)
    return qapp.exec()
