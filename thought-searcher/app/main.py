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

from .core import Core, setup_logging
from .hotkey import HotkeyManager
from .index import connect, fts5_available
from .search import Hit, Searcher
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


class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.core = Core()
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

        self.window = SearchWindow()
        self.window.searchRequested.connect(self.on_query)
        self.window.action.connect(self.on_action)

        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip(APP_NAME)
        self.tray.messageClicked.connect(self.on_message_clicked)
        self.tray.activated.connect(self.on_tray_activated)
        self.menu = QMenu()
        self._add("검색 (Ctrl+Alt+H)", self.show_search)
        self.menu.addSeparator()
        self._add("지금 가져오기", self.import_now)
        self._add("claude.ai 내보내기 받으러 가기", self.open_export_page)
        self.menu.addSeparator()
        self._add("대화 보관 폴더 열기", self.open_archive)
        self._add("상태 보기", self.show_status)
        adv = self.menu.addMenu("고급")
        self._add("zip 파일 직접 고르기...", self.import_zip_dialog, adv)
        self._add("대화 보관 폴더 바꾸기...", self.choose_archive, adv)
        adv.addSeparator()
        self._add("노트 폴더 추가...", self.add_note_dir, adv)
        self.note_menu = adv.addMenu("노트 폴더 빼기")
        self.note_menu.aboutToShow.connect(self._fill_note_menu)
        adv.addSeparator()
        self._add("검색 색인 다시 만들기", self.rebuild_index, adv)
        self._add("대화 md 전부 다시 만들기", self.rebuild_all, adv)
        self.menu.addSeparator()
        self._add("종료", self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.hotkey = HotkeyManager(qapp)
        self.hotkey.activated.connect(self.toggle)
        key = str(self.core.config.get("hotkey") or "ctrl+alt+h")
        ok, why = self.hotkey.register(key)
        if not ok:
            self.notify(f"단축키 {key} 등록 실패({why}).\n트레이 메뉴 '검색'으로 사용하세요.", QSystemTrayIcon.Warning)

        for w in list(self.core.warnings):
            self.notify(w, QSystemTrayIcon.Warning)

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
    def _add(self, text, slot, menu=None):
        menu = menu or self.menu
        act = QAction(text, menu)
        act.triggered.connect(slot)
        menu.addAction(act)

    def notify(self, msg: str, icon=QSystemTrayIcon.Information, kind: str = "") -> None:
        self._notice_kind = kind
        log.info("알림: %s", msg.replace("\n", " / "))
        self.tray.showMessage(APP_NAME, msg, icon, 6000)

    def _watch_folder(self):
        try:
            d = str(self.core.watch_dir)
            if self.fs.directories():
                self.fs.removePaths(self.fs.directories())
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
                msg = (f"보관 폴더가 없습니다: {d}\n가져오기를 멈췄습니다. 트레이 메뉴 '고급 > 대화 보관 폴더 바꾸기'로 고르세요."
                       if d else "보관 폴더가 설정되지 않아 가져오기를 멈췄습니다. 트레이 메뉴 '고급 > 대화 보관 폴더 바꾸기'로 고르세요.")
                self.tray.setToolTip(f"{APP_NAME} ⚠ 보관 폴더 없음")
                if self._archive_was_ok is not None or d:
                    self.notify(msg, QSystemTrayIcon.Warning)
                self.core._warn(msg.split("\n")[0])
            else:
                self.tray.setToolTip(APP_NAME)
                if self._archive_was_ok is False:
                    self.start_jobs()
            self._archive_was_ok = ok
        return ok

    # ---- 시작 ---------------------------------------------------------
    def start_jobs(self):
        if not self.update_archive_state():
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

    # ---- 진행 표시 ---------------------------------------------------------
    JOB_LABELS = {"collect": "Claude Code 대화 가져오는 중", "sync": "검색 색인 확인 중", "notes": "노트 폴더 확인 중",
                  "rebuild-index": "검색 색인 다시 만드는 중", "rebuild-all": "대화 md 다시 만드는 중"}

    def on_job_started(self, name: str):
        if name.startswith("zip:"):
            self.set_busy(f"zip 가져오는 중 ({Path(name[4:]).name})")
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
        if not self.update_archive_state():
            return
        if self._batch is not None:
            self.notify("이미 가져오는 중입니다. 끝나면 알려 드릴게요.")
            return
        self._batch = {"names": {"collect", "sync"}, "new": 0, "changed": 0, "zips": 0, "failed": []}
        self.worker.submit("sync", lambda: self.core.sync_index(self._progress))   # 직접 넣은 md 반영
        self.worker.submit("collect", self._collect)
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
        self.notify("가져오는 중입니다" + (f" (Claude Code 대화 + 새 zip {n}개)" if n else " (Claude Code 대화)") +
                    ". 끝나면 알려 드릴게요.")

    def collect_now(self):
        if self.update_archive_state():
            self.worker.submit("collect", self._collect)
        self.worker.submit("notes", self.core.sync_notes)

    # ---- 노트 폴더 ----------------------------------------------------------
    def add_note_dir(self):
        d = QFileDialog.getExistingDirectory(None, "노트 폴더 선택 (md를 그대로 읽어 검색에 넣을 곳)", str(Path.home()))
        if not d:
            return
        if not self.core.add_note_dir(Path(d)):
            self.notify("이미 등록된 노트 폴더입니다.")
            return
        self.notify(f"노트 폴더를 추가했습니다: {d}\n파일은 읽기만 하고 고치지 않습니다.")
        self.worker.submit("notes", self.core.sync_notes)

    def _fill_note_menu(self):
        self.note_menu.clear()
        dirs = self.core.note_dirs
        if not dirs:
            act = QAction("(등록된 폴더 없음)", self.note_menu)
            act.setEnabled(False)
            self.note_menu.addAction(act)
            return
        for p in dirs:
            self._add(str(p), lambda _=False, p=p: self.remove_note_dir(p), self.note_menu)

    def remove_note_dir(self, path: Path):
        self.core.remove_note_dir(path)
        self.notify(f"노트 폴더를 뺐습니다: {path}\n검색에서만 빠지고 파일은 그대로입니다.")
        self.worker.submit("notes", self.core.sync_notes)

    def poll_zips(self):
        if not self.core.archive_ok():
            self.update_archive_state()
            return
        if self._archive_was_ok is False:
            self.update_archive_state()
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
        elif name == "collect" and result is not None:
            b["new"] += result.new
            b["changed"] += result.changed
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
        if self.window.isVisible():
            self.on_query(self._last_query)

    # ---- 알림 ------------------------------------------------------------
    def check_reminder(self):
        msg = self.core.reminder_due()
        if msg:
            self.core.mark_reminded()
            self.notify(msg, kind="reminder")

    def on_message_clicked(self):
        if self._notice_kind == "reminder":
            self.open_export_page()

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
        try:
            hits = self.searcher.search(text)
        except Exception as e:  # noqa: BLE001
            log.exception("검색 실패")
            self.window.set_results([], f"검색 오류: {e}")
            return
        self.window.set_results(hits, self._compose_status(len(hits)))

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

    def on_action(self, kind: str, hit: Hit, idx: int):
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
            self.notify("대화 보관 폴더가 없습니다. '고급 > 대화 보관 폴더 바꾸기'로 고르세요.", QSystemTrayIcon.Warning)

    def choose_archive(self, first: bool = False):
        start = str(self.core.archive_dir or Path.home())
        d = QFileDialog.getExistingDirectory(None, "보관 폴더 선택 (대화 md를 저장할 곳)", start)
        if not d:
            self.update_archive_state()
            return
        self.core.set_archive_dir(Path(d))
        self._archive_was_ok = None
        self.start_jobs()

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
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    if not fts5_available():
        QMessageBox.critical(None, APP_NAME, "이 Python의 sqlite3에 FTS5가 없습니다.\n"
                                             "python.org 배포판 Python 3.10 이상으로 실행하세요.")
        return 2
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 1
    log.info("시작 %s", datetime.now().isoformat(timespec="seconds"))
    app = App(qapp)  # noqa: F841  (수명 유지)
    return qapp.exec()
