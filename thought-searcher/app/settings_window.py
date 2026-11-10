"""설정 창과 시작 안내 (SPEC-settings.md 3-A, 3-B, 3-E, 3-I, 3-J, 3-K).

검사, 바뀐 키 계산, 기본값 규칙은 settings.py, CLI 확인은 cli_check.py에 있고 여기는 화면만 다룬다.
저장 뒤 트레이 앱 쪽 적용(단축키, 타이머, 감시 폴더, 검색 가중치)은 Hooks로 main.py에 맡긴다.
"""
from __future__ import annotations

import copy
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QCursor, QFont, QGuiApplication
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QScrollArea, QSpinBox,
                               QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from . import cli_check
from . import settings as S
from .store import expand
from .watcher import downloads_dir
from .window import TEXT_FONTS, Theme

TITLE = "생각 검색기 설정"
SETUP_TITLE = "생각 검색기 시작하기"
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "userscript"
SCRIPTS = {"claude-ai": "claude-sync.user.js", "chatgpt": "chatgpt-sync.user.js"}
SITES = {"claude-ai": ("claude.ai", "claude_ai", "claude.ai"), "chatgpt": ("ChatGPT", "chatgpt", "chatgpt.com")}
TAMPERMONKEY_URL = "https://www.tampermonkey.net/"
CHROME_DOWNLOADS = "chrome://settings/downloads"
CHROME_PERFORMANCE = "chrome://settings/performance"
CLOUD_WARNING = "회사 PC 보관본을 개인 클라우드에 두지 마세요"
CHANGED_OUTSIDE = "config.json이 창을 연 뒤 바뀌었습니다. 덮어쓸까요?"
INVALID_NOTE = "config.json 값이 잘못돼 기본값을 보여 줍니다"


@dataclass
class Hooks:
    """트레이 앱(main.py)이 넘기는 동작. 기본값은 아무것도 하지 않음(테스트, 단독 실행용)."""
    open_url: Callable[[str], None] = lambda url: None
    try_hotkey: Callable[[str], tuple] = lambda key: (True, "")       # 새 키 시험 등록(성공하면 바로 교체)
    recording: Callable[[bool], None] = lambda on: None                # 단축키 칸 기록 중: 전역 키 잠시 해제
    applied: Callable[[set, dict], None] = lambda changed, old: None   # 저장 뒤 앱 쪽 적용
    setup_finished: Callable[[bool, set, dict], None] = lambda finished, changed, old: None


# ---- 작은 위젯 ---------------------------------------------------------------
class Note(QLabel):
    """칸 아래 한 줄. 오류(빨강) > 경고 > 안내 순으로 하나만 보여 준다."""

    def __init__(self, theme: Theme):
        super().__init__("")
        self.t = theme
        self.setWordWrap(True)
        self._error = self._warn = self._note = ""
        self.hide()

    def error(self, msg: str = "") -> None:
        self._error = msg
        self._render()

    def warn(self, msg: str = "") -> None:
        self._warn = msg
        self._render()

    def note(self, msg: str = "") -> None:
        self._note = msg
        self._render()

    def _render(self) -> None:
        text = self._error or self._warn or self._note
        color = self.t.warn.name() if (self._error or self._warn) else self.t.sub.name()
        self.setStyleSheet(f"color:{color};")
        self.setText(("⚠ " if self._warn and not self._error else "") + text)
        self.setVisible(bool(text))


class PathEdit(QWidget):
    changed = Signal()

    def __init__(self, title: str, placeholder: str = "", file: bool = False, open_button: bool = True):
        super().__init__()
        self.title, self.file = title, file
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(lambda _t: self.changed.emit())
        lay.addWidget(self.edit, 1)
        b = QPushButton("찾아보기...")
        b.clicked.connect(self._browse)
        lay.addWidget(b)
        if open_button:
            o = QPushButton("열기")
            o.clicked.connect(self._open)
            lay.addWidget(o)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, v: str) -> None:
        self.edit.setText(str(v or ""))

    def set_placeholder(self, p: str) -> None:
        self.edit.setPlaceholderText(p)

    def target(self) -> str:
        return expand(self.value() or self.edit.placeholderText())

    def _browse(self) -> None:
        start = self.target()
        if not os.path.exists(start):
            start = str(Path.home())
        if self.file:
            f, _ = QFileDialog.getOpenFileName(self, self.title, start, "실행 파일 (*.exe *.cmd *.bat);;모든 파일 (*)")
            if f:
                self.edit.setText(str(Path(f)))
        else:
            d = QFileDialog.getExistingDirectory(self, self.title, start)
            if d:
                self.edit.setText(str(Path(d)))

    def _open(self) -> None:
        p = self.target()
        if p and os.path.isdir(p):
            os.startfile(p)
        else:
            QMessageBox.information(self, TITLE, f"폴더가 없습니다: {p or '(비어 있음)'}")


class ListEdit(QWidget):
    """목록 + 추가 / 빼기. mode: dir(폴더 고르기), text(한 줄씩 직접 입력). pick: 추가 때 부를 함수."""
    changed = Signal()

    def __init__(self, mode: str, title: str = "", pick: Callable[[], str | None] | None = None):
        super().__init__()
        self.mode, self.title, self.pick = mode, title, pick
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMaximumHeight(96)
        self.list.itemChanged.connect(lambda _i: self.changed.emit())
        lay.addWidget(self.list, 1)
        col = QVBoxLayout()
        add = QPushButton("추가..." if mode == "dir" or pick else "추가")
        add.clicked.connect(self._add)
        rm = QPushButton("빼기")
        rm.clicked.connect(self._remove)
        col.addWidget(add)
        col.addWidget(rm)
        col.addStretch(1)
        lay.addLayout(col)

    def values(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            s = self.list.item(i).text().strip()
            if s:
                out.append(s)
        return out

    def set_values(self, vs) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for v in vs or []:
            self._append(str(v))
        self.list.blockSignals(False)

    def _append(self, text: str) -> QListWidgetItem:
        it = QListWidgetItem(text)
        if self.mode == "text":
            it.setFlags(it.flags() | Qt.ItemIsEditable)
        self.list.addItem(it)
        return it

    def _add(self) -> None:
        if self.mode == "text":
            it = self._append("")
            self.list.setCurrentItem(it)
            self.list.editItem(it)
            return
        if self.pick:
            v = self.pick()
        else:
            d = QFileDialog.getExistingDirectory(self, self.title, str(Path.home()))
            v = str(Path(d)) if d else None
        if v and v not in self.values():
            self._append(v)
            self.changed.emit()

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self.changed.emit()


class HotkeyEdit(QLineEdit):
    """누르면 '키를 누르세요' 상태가 되고 다음에 누른 조합을 기록한다 (3-E-1)."""
    recorded = Signal(str)       # 누른 조합 ('ctrl+alt+j' 꼴, 검사 전)
    recording = Signal(bool)
    PROMPT = "키를 누르세요 (Esc 취소, Backspace 기본값)"
    _MOD_KEYS = {Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R,
                 Qt.Key_AltGr}

    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setAttribute(Qt.WA_InputMethodEnabled, False)    # 한글 IME가 키를 가로채지 않게
        self._value = ""
        self.active = False

    def value(self) -> str:
        return self._value

    def set_value(self, v: str) -> None:
        self._value = str(v or "")
        if not self.active:
            self.setText(S.display_hotkey(self._value))

    def start(self) -> None:
        if not self.active:
            self.active = True
            self.setText(self.PROMPT)
            self.recording.emit(True)

    def stop(self) -> None:
        if self.active:
            self.active = False
            self.setText(S.display_hotkey(self._value))
            self.recording.emit(False)

    def mousePressEvent(self, e):
        self.setFocus()
        self.start()

    def focusOutEvent(self, e):
        self.stop()
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        if not self.active:
            if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and not mods:
                self.start()
            else:
                e.ignore()
            return
        e.accept()
        names = [n for flag, n in ((Qt.ControlModifier, "ctrl"), (Qt.AltModifier, "alt"),
                                   (Qt.ShiftModifier, "shift"), (Qt.MetaModifier, "win")) if mods & flag]
        if k == Qt.Key_Escape and not names:
            self.stop()
            return
        if k == Qt.Key_Backspace and not names:
            self.recorded.emit(S.DEFAULT_HOTKEY)
            return
        if k in self._MOD_KEYS:
            self.setText(S.display_hotkey("+".join(names)) + "+ ..." if names else self.PROMPT)
            return
        name = S.VK_NAME.get(e.nativeVirtualKey()) or f"키{e.nativeVirtualKey()}"
        self.recorded.emit("+".join(names + [name]))


class _CheckBridge(QObject):
    done = Signal(str, object)    # (provider, CliStatus)


class _WheelGuard(QObject):
    """숫자 칸, 목록 상자는 클릭해 초점이 있을 때만 휠로 값이 바뀐다. 아니면 휠은 화면 스크롤로 넘긴다."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Wheel and not obj.hasFocus():
            p = obj.parentWidget()
            while p is not None and not isinstance(p, QScrollArea):
                p = p.parentWidget()
            if p is not None:
                QApplication.sendEvent(p.verticalScrollBar(), e)
            return True
        return False


def guard_wheel(root: QWidget, guard: QObject) -> None:
    for w in root.findChildren(QAbstractSpinBox) + root.findChildren(QComboBox):
        w.setFocusPolicy(Qt.StrongFocus)      # 휠로 초점을 가져가지 않게 (기본은 WheelFocus)
        w.installEventFilter(guard)


# ---- 창 ----------------------------------------------------------------------
class SettingsWindow(QDialog):
    def __init__(self, core, hooks: Hooks | None = None, setup: bool = False, tab: str = "general"):
        super().__init__(None)
        self.core = core
        self.hooks = hooks or Hooks()
        self.setup_mode = setup
        self.t = Theme()
        font = QFont()
        font.setFamilies(TEXT_FONTS)
        font.setPointSize(10)
        self.setFont(font)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumSize(560, 480)
        self.resize(680, 660)
        self._io: dict[str, tuple[Callable, Callable]] = {}
        self._notes: dict[str, Note] = {}
        self._boxes: dict[str, QWidget] = {}
        self._scrolls: dict[str, QScrollArea] = {}
        self._loading = False
        self._done = False
        self.forced: set[str] = set()
        self.initial: dict = {}
        self._cli_status: dict[str, cli_check.CliStatus] = {}
        self._checking: set[str] = set()
        self._status_labels: dict[str, list[QLabel]] = {"claude": [], "codex": []}
        self._guides: list[tuple[str, QWidget]] = []
        self._bridge = _CheckBridge()
        self._bridge.done.connect(self._on_check_done)
        self._sig = core.store.config_signature()

        root = QVBoxLayout(self)
        self.broken = QLabel("config.json을 읽지 못해 기본값으로 동작 중입니다. 저장하면 지금 화면 내용으로 새로 씁니다 "
                             "(깨진 파일은 config.json.bak에 있음)")
        self.broken.setWordWrap(True)
        self.broken.setStyleSheet(f"color:{self.t.warn.name()}; font-weight:bold;")
        self.broken.setVisible(bool(core.store.config_broken) and not setup)
        root.addWidget(self.broken)
        buttons = QHBoxLayout()
        if setup:
            self.setWindowTitle(SETUP_TITLE)
            self._build_setup(root)
            self.btn_prev = QPushButton("이전")
            self.btn_next = QPushButton("다음")
            self.btn_skip = QPushButton("건너뛰기")
            self.btn_prev.clicked.connect(lambda: self._go(-1))
            self.btn_next.clicked.connect(lambda: self._go(1))
            self.btn_skip.clicked.connect(self.reject)
            buttons.addWidget(self.btn_skip)
            buttons.addStretch(1)
            buttons.addWidget(self.btn_prev)
            buttons.addWidget(self.btn_next)
            self.btn_next.setDefault(True)
            self._go(0)
        else:
            self.tabs = QTabWidget()
            for key in S.TABS:
                getattr(self, f"_build_{key}")()
            root.addWidget(self.tabs, 1)
            self.btn_save = QPushButton("저장")
            self.btn_cancel = QPushButton("취소")
            self.btn_save.clicked.connect(self.save)
            self.btn_cancel.clicked.connect(self.reject)
            buttons.addStretch(1)
            buttons.addWidget(self.btn_save)
            buttons.addWidget(self.btn_cancel)
            self.btn_save.setDefault(False)
            self.btn_save.setAutoDefault(False)
            self.btn_cancel.setAutoDefault(False)
            self.populate(core.config)
            self.tabs.currentChanged.connect(self._on_tab)
            self.select_tab(tab)
        root.addLayout(buttons)
        self._wheel_guard = _WheelGuard(self)
        guard_wheel(self, self._wheel_guard)
        self._center()

    # ---- 공통 도우미 --------------------------------------------------------
    def _center(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.move(g.left() + (g.width() - self.width()) // 2, g.top() + (g.height() - self.height()) // 2)

    def _help(self, text: str, warn: bool = False) -> QLabel:
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setTextFormat(Qt.PlainText)
        lb.setStyleSheet(f"color:{(self.t.warn if warn else self.t.sub).name()};")
        return lb

    def _page(self, tab: str | None = None, title: str = "") -> QVBoxLayout:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignTop)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)    # 긴 안내 줄은 옆으로 넘치지 않고 줄바꿈
        sc.setFrameShape(QFrame.NoFrame)
        sc.setWidget(w)
        if tab:
            self._scrolls[tab] = sc
            self.tabs.addTab(sc, S.TAB_LABEL[tab])
        else:
            self.pages.addWidget(sc)
            if title:
                h = QLabel(title)
                f = QFont(self.font())
                f.setPointSizeF(f.pointSizeF() * 1.25)
                f.setBold(True)
                h.setFont(f)
                lay.addWidget(h)
        return lay

    def _item(self, lay: QVBoxLayout, title: str, body, help: str = "", key: str | None = None,
              warn: str = "") -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 4, 0, 8)
        v.setSpacing(3)
        if title:
            t = QLabel(title)
            f = QFont(self.font())
            f.setBold(True)
            t.setFont(f)
            v.addWidget(t)
        if isinstance(body, QWidget):
            v.addWidget(body)
        elif body is not None:
            v.addLayout(body)
        if help:
            v.addWidget(self._help(help))
        if warn:
            v.addWidget(self._help(warn, warn=True))
        if key:
            n = Note(self.t)
            self._notes[key] = n
            v.addWidget(n)
            self._boxes[key] = box
        lay.addWidget(box)
        return box

    def _bind(self, key: str, setter: Callable, getter: Callable) -> None:
        self._io[key] = (setter, getter)

    def _spin(self, key: str) -> QSpinBox:
        f = S.FIELD[key]
        sp = QSpinBox()
        sp.setRange(int(f.lo), int(f.hi))
        if key == "ask_max_chars":
            sp.setSingleStep(1000)
        sp.setMaximumWidth(120)
        sp.valueChanged.connect(self._on_changed)
        self._bind(key, lambda v, sp=sp: sp.setValue(int(v)), sp.value)
        return sp

    def _path(self, key: str, title: str, placeholder: str = "") -> PathEdit:
        pe = PathEdit(title, placeholder)
        pe.changed.connect(self._on_changed)
        self._bind(key, pe.set_value, pe.value)
        return pe

    def _checks(self, names: dict[str, str]) -> tuple[QHBoxLayout, dict[str, QCheckBox]]:
        row = QHBoxLayout()
        boxes = {}
        for k, label in names.items():
            cb = QCheckBox(label)
            cb.toggled.connect(self._on_changed)
            row.addWidget(cb)
            boxes[k] = cb
        row.addStretch(1)
        return row, boxes

    # ---- 일반 탭 -------------------------------------------------------------
    def _build_general(self) -> None:
        lay = self._page("general")
        self.hotkey = HotkeyEdit()
        self.hotkey.setMaximumWidth(260)
        self.hotkey.recorded.connect(self._on_hotkey_recorded)
        self.hotkey.recording.connect(self.hooks.recording)
        self._bind("hotkey", self.hotkey.set_value, self.hotkey.value)
        self._item(lay, "검색 창 단축키", self.hotkey,
                   f"칸을 누르고 새 조합을 누릅니다. 저장할 때 바로 등록해 봅니다. Backspace는 기본값({S.display_hotkey(S.DEFAULT_HOTKEY)}).",
                   "hotkey")
        self.archive = self._path("archive_dir", "보관 폴더 선택 (대화 md를 저장할 곳)", str(self.core.default_archive))
        self._item(lay, "대화 보관 폴더", self.archive,
                   "비면 기본 위치를 씁니다. 기존 md는 옮기지 않습니다. 필요하면 직접 옮긴 뒤 트레이 '고급 > 검색 색인 다시 만들기'.",
                   "archive_dir", warn=CLOUD_WARNING)
        self.notes = ListEdit("dir", "노트 폴더 선택 (md를 그대로 읽어 검색에 넣을 곳)")
        self.notes.changed.connect(self._on_changed)
        self._bind("note_dirs", self.notes.set_values, self.notes.values)
        self._item(lay, "노트 폴더", self.notes, "내 md 폴더(Obsidian 볼트 등)를 그대로 검색에 넣습니다. 파일은 읽기만 합니다.",
                   "note_dirs")
        self.journal = self._path("journal_dir", "업무 일지 보관함 루트 선택")
        off = QPushButton("끄기")
        off.clicked.connect(lambda: self.journal.set_value(""))
        self.journal.layout().addWidget(off)
        self._item(lay, "업무 일지 폴더", self.journal,
                   "YYYY/MM/YYYY-MM-DD.md 형식의 '## 업무' 구역을 읽습니다. 형식이 다르면 비워 두고 노트 폴더로만 넣으세요.",
                   "journal_dir")
        row = QHBoxLayout()
        row.addWidget(QLabel("열린 일 기간(일)"))
        row.addWidget(self._spin("queue_days"))
        row.addSpacing(20)
        row.addWidget(QLabel("크게 보여 줄 개수"))
        row.addWidget(self._spin("queue_focus"))
        row.addStretch(1)
        box = self._item(lay, "열린 일 큐 (검색어가 비었을 때 보이는 최근 일 목록)", row,
                         "이 기간 안에 흔적이 있는 일만 올라옵니다. 위쪽에 크게 보여 줄 개수를 넘는 일은 '나머지 N개' 줄에 접혀 있습니다.",
                         "queue_days")
        self._notes["queue_focus"] = self._notes["queue_days"]
        self._boxes["queue_focus"] = box
        qrow, self.queue_checks = self._checks(S.QUEUE_LABEL)
        self._bind("queue_sources", self._set_queue_sources,
                   lambda: [s for s in S.QUEUE_CHOICES if self.queue_checks[s].isChecked()])
        self._item(lay, "큐에 올릴 출처", qrow,
                   "프로젝트 문서, 메모리, imported 폴더는 올리지 않습니다. 업무 일지 항목은 일지 폴더가 있으면 늘 올라옵니다.",
                   "queue_sources")
        self.queue_ex = ListEdit("dir", pick=self._pick_note_subdir)
        self.queue_ex.changed.connect(self._on_changed)
        self._bind("queue_note_exclude", self.queue_ex.set_values, self.queue_ex.values)
        self._item(lay, "큐에서 뺄 노트 폴더", self.queue_ex, "노트 폴더 안의 폴더만 고를 수 있습니다(노트 폴더 기준 상대 경로로 저장).",
                   "queue_note_exclude")

    def _set_queue_sources(self, v) -> None:
        for s, cb in self.queue_checks.items():
            cb.setChecked(s in (v or []))

    def _pick_note_subdir(self) -> str | None:
        roots = [Path(expand(p)) for p in self.notes.values()]
        if not roots:
            QMessageBox.information(self, TITLE, "먼저 노트 폴더를 추가하세요.")
            return None
        d = QFileDialog.getExistingDirectory(self, "큐에서 뺄 폴더 (노트 폴더 안)", str(roots[0]))
        if not d:
            return None
        p = Path(d).resolve()
        for r in roots:
            try:
                rel = p.relative_to(r.resolve())
            except (ValueError, OSError):
                continue
            if rel.as_posix() in ("", "."):
                QMessageBox.information(self, TITLE, "노트 폴더 자체는 뺄 수 없습니다. 노트 폴더 목록에서 빼세요.")
                return None
            return rel.as_posix()
        QMessageBox.warning(self, TITLE, "노트 폴더 밖의 폴더는 고를 수 없습니다.")
        return None

    def _on_hotkey_recorded(self, raw: str) -> None:
        norm, err, warn = S.check_hotkey(raw)
        n = self._notes["hotkey"]
        if err:
            n.warn("")
            n.error(err)                   # 기록 상태를 유지한다 (다른 조합을 누르게)
            return
        n.error("")
        n.warn(warn)
        self.hotkey.set_value(norm)
        self.hotkey.stop()
        self._on_changed()

    # ---- 수집 탭 -------------------------------------------------------------
    def _build_collect(self) -> None:
        lay = self._page("collect")
        row, self.source_checks = self._checks(S.SERVICE_LABEL)
        self._bind("sources", self._set_sources, self._get_sources)
        self._item(lay, "쓰는 서비스", row, "끈 서비스는 수집도 알림도 하지 않습니다. 이미 보관된 md는 그대로 검색됩니다.", "sources")
        self.watch = self._path("watch_dir", "다운로드(감시) 폴더 선택", str(downloads_dir()))
        self.watch.changed.connect(self._update_capture_placeholder)
        self._item(lay, "다운로드(감시) 폴더", self.watch, "내보내기 zip이 들어오는 곳입니다. 비면 시스템 다운로드 폴더.", "watch_dir")
        self.capture = self._path("capture_dir", "자동 수집 파일 폴더 선택")
        self._item(lay, "자동 수집 파일 폴더", self.capture, "수집 스크립트가 대화 파일을 저장하는 곳입니다. 비면 <감시 폴더>\\claude-sync.",
                   "capture_dir")
        self.projects = self._path("code_projects_dir", "Claude Code 세션 폴더 선택",
                                   expand(str(S.default_of("code_projects_dir"))))
        self._item(lay, "Claude Code 세션 폴더", self.projects, "Claude Code를 켰을 때만 씁니다.", "code_projects_dir")
        self.codex_home = self._path("codex_dir", "Codex 폴더 선택", expand(str(S.default_of("codex_dir"))))
        self._item(lay, "Codex 폴더", self.codex_home, "Codex를 켰을 때만 씁니다.", "codex_dir")
        self._item(lay, "수집 주기(분)", self._spin("code_collect_minutes"),
                   "Claude Code, Codex 대화와 노트 폴더를 이 간격으로 모읍니다.", "code_collect_minutes")
        rrow = QHBoxLayout()
        self.reminder = QSpinBox()
        self.reminder.setRange(1, 60)
        self.reminder.setMaximumWidth(120)
        self.reminder.valueChanged.connect(self._on_changed)
        self.reminder_off = QCheckBox("끄기")
        self.reminder_off.toggled.connect(lambda on: (self.reminder.setEnabled(not on), self._on_changed()))
        rrow.addWidget(self.reminder)
        rrow.addWidget(self.reminder_off)
        rrow.addStretch(1)
        self._bind("reminder_days", self._set_reminder, lambda: 0 if self.reminder_off.isChecked() else self.reminder.value())
        self._item(lay, "claude.ai 내보내기 알림(일)", rrow, "마지막 zip 가져오기 뒤 이만큼 지나면 하루 한 번 알려 드립니다.",
                   "reminder_days")
        self._item(lay, "자동 수집 멈춤 알림(시간)", self._spin("capture_stale_hours"),
                   "수집 스크립트가 이만큼 멈추면 하루 한 번 알려 드립니다.", "capture_stale_hours")
        for site in SCRIPTS:
            g = self._script_guide(site)
            lay.addWidget(g)
            self._guides.append((site, g))

    def _set_sources(self, v) -> None:
        for s, cb in self.source_checks.items():
            cb.setChecked(bool((v or {}).get(s, True)))

    def _get_sources(self) -> dict:
        return {s: self.source_checks[s].isChecked() for s in S.SERVICES}

    def _set_reminder(self, v) -> None:
        v = int(v)
        self.reminder_off.setChecked(v == 0)
        self.reminder.setValue(v if v > 0 else 7)
        self.reminder.setEnabled(v > 0)

    def _update_capture_placeholder(self) -> None:
        if hasattr(self, "capture"):
            base = self.watch.value() or str(downloads_dir())
            self.capture.set_placeholder(str(Path(expand(base)) / "claude-sync"))

    def _script_guide(self, site: str) -> QWidget:
        """수집 스크립트 설치 단계, 스크립트 복사, 상태 한 줄 (3-I)."""
        label, _svc, host = SITES[site]
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        v = QVBoxLayout(box)
        t = QLabel(f"{label} 수집 스크립트 설치 (Tampermonkey)")
        f = QFont(self.font())
        f.setBold(True)
        t.setFont(f)
        v.addWidget(t)
        v.addWidget(self._help(f"{label} 탭이 열려 있는 동안 바뀐 대화만 받아 둡니다. 순서대로 한 번만 하면 됩니다."))
        copied = self._help("")
        copied.hide()

        def copy_text(text: str, what: str):
            QApplication.clipboard().setText(text)
            copied.setText(f"복사됨: {what}")
            copied.show()

        def copy_script():
            p = SCRIPT_DIR / SCRIPTS[site]
            try:
                text = p.read_text(encoding="utf-8")
            except OSError as e:
                QMessageBox.warning(self, TITLE, f"스크립트를 읽지 못했습니다: {e}")
                return
            copy_text(text, f"{SCRIPTS[site]} 내용")

        steps = [
            ("1. 브라우저에 Tampermonkey 확장을 설치합니다.", "링크 열기", lambda: self.hooks.open_url(TAMPERMONKEY_URL)),
            ("2. Tampermonkey 설정 > 일반 > 설정 모드: 고급", None, None),
            ("3. 다운로드 BETA > 다운로드 모드: 브라우저 API, 허용 확장자에 .json 추가", None, None),
            ("4. 크롬 설정 > 다운로드 > '다운로드 전에 각 파일의 저장 위치 확인' 끄기", "주소 복사",
             lambda: copy_text(CHROME_DOWNLOADS, f"{CHROME_DOWNLOADS} (크롬 주소창에 붙여 넣으세요)")),
            (f"5. 크롬 메모리 절약 모드를 쓰면 {host}를 '항상 활성 상태로 유지할 사이트'에 추가", "주소 복사",
             lambda: copy_text(CHROME_PERFORMANCE, f"{CHROME_PERFORMANCE} (크롬 주소창에 붙여 넣으세요)")),
            ("6. Tampermonkey 대시보드 > 새 스크립트에 붙여 넣고 저장", "스크립트 복사", copy_script),
        ]
        grid = QGridLayout()
        for i, (text, btn, fn) in enumerate(steps):
            lb = QLabel(text)
            lb.setWordWrap(True)
            grid.addWidget(lb, i, 0)
            if btn:
                b = QPushButton(btn)
                b.clicked.connect(fn)
                grid.addWidget(b, i, 1)
        grid.setColumnStretch(0, 1)
        v.addLayout(grid)
        v.addWidget(copied)
        status = QLabel(f"상태: {self.core.capture_site_status(site)}")
        status.setWordWrap(True)
        v.addWidget(status)
        v.addWidget(self._help("회사 크롬 정책으로 확장 설치가 막혀 있으면 zip 내보내기로 가져오세요."))
        return box

    # ---- 요약 AI 탭 -----------------------------------------------------------
    def _build_ask(self) -> None:
        lay = self._page("ask")
        row = QHBoxLayout()
        self.provider_group = QButtonGroup(self)
        self.provider_radios = {}
        for p, label in (("claude", "Claude"), ("codex", "GPT (Codex)"), ("off", "끄기")):
            rb = QRadioButton(label)
            rb.toggled.connect(self._on_changed)
            self.provider_group.addButton(rb)
            self.provider_radios[p] = rb
            row.addWidget(rb)
        row.addStretch(1)
        self._bind("ask_provider", lambda v: self.provider_radios.get(v, self.provider_radios["claude"]).setChecked(True),
                   lambda: next((p for p, rb in self.provider_radios.items() if rb.isChecked()), "claude"))
        self._item(lay, "요약 AI", row, "큐에서 F2를 눌렀을 때만 이 PC의 CLI를 실행합니다. CLI 설치와 로그인은 직접 합니다.",
                   "ask_provider")
        # Claude
        self.claude_box = QWidget()
        cl = QVBoxLayout(self.claude_box)
        cl.setContentsMargins(0, 0, 0, 0)
        self.claude_model = self._model_combo("ask_model", cli_check.CLAUDE_MODELS, "claude")
        self._item(cl, "모델 (Claude)", self.claude_model, "목록에 없는 이름(전체 모델 이름)도 직접 넣을 수 있습니다.", "ask_model")
        cl.addWidget(self._status_row("claude"))
        self.claude_cmd = PathEdit("claude 실행 파일 선택", self._found("claude", ["claude"]), file=True, open_button=False)
        self.claude_cmd.changed.connect(self._on_changed)
        self._bind("ask_command",
                   lambda v: self.claude_cmd.set_value("" if S.as_command(v) in ([], ["claude"]) else S.join_command(v)),
                   lambda: S.split_command(self.claude_cmd.value()) or ["claude"])
        self._item(cl, "CLI 경로 (Claude Code)", self.claude_cmd, "비면 PATH에서 claude를 찾습니다.", "ask_command")
        lay.addWidget(self.claude_box)
        # GPT (Codex)
        self.codex_box = QWidget()
        cx = QVBoxLayout(self.codex_box)
        cx.setContentsMargins(0, 0, 0, 0)
        self.codex_model = self._model_combo("ask_model_codex", cli_check.codex_models(self.core.codex_dir), "codex")
        self.codex_desc = self._help("")
        self.codex_model.currentTextChanged.connect(self._update_codex_desc)
        mbox = QVBoxLayout()
        mbox.addWidget(self.codex_model)
        mbox.addWidget(self.codex_desc)
        self._item(cx, "모델 (GPT)", mbox, "목록은 이 PC의 Codex가 받아 둔 models_cache.json에서 읽습니다(앱이 네트워크로 받지 않음).",
                   "ask_model_codex")
        self.effort = QComboBox()
        self.effort.addItems(list(cli_check.CODEX_EFFORTS))
        self.effort.setMaximumWidth(160)
        self.effort.currentTextChanged.connect(self._on_changed)
        self._bind("ask_codex_effort", self._set_effort, lambda: self.effort.currentText())
        self._item(cx, "추론 정도 (GPT)", self.effort, "low가 가장 빠르고 적게 씁니다. 요약에는 low로 충분합니다.", "ask_codex_effort")
        cx.addWidget(self._status_row("codex"))
        self.codex_cmd = PathEdit("codex 실행 파일 선택", self._found("codex", []), file=True, open_button=False)
        self.codex_cmd.changed.connect(self._on_changed)
        self._bind("ask_command_codex", lambda v: self.codex_cmd.set_value(S.join_command(v)),
                   lambda: S.split_command(self.codex_cmd.value()))
        self._item(cx, "CLI 경로 (Codex)", self.codex_cmd,
                   "비면 PATH의 codex, 그다음 Codex 데스크톱 앱 폴더(%LOCALAPPDATA%\\OpenAI\\Codex\\bin)에서 찾습니다.",
                   "ask_command_codex")
        lay.addWidget(self.codex_box)
        self.off_note = self._help("F2를 누르면 '요약 AI가 꺼져 있습니다' 한 줄만 보여 줍니다. 큐의 F2 안내도 숨깁니다.")
        lay.addWidget(self.off_note)

    def _found(self, provider: str, configured) -> str:
        cmd = cli_check.resolve(provider, configured)
        return f"자동: {os.path.normpath(cmd[0])}" if cmd else "자동으로 찾지 못함"

    def _model_combo(self, key: str, models: list, provider: str) -> QComboBox:
        cb = QComboBox()
        cb.setEditable(True)
        cb.setMaximumWidth(360)
        cheap = cli_check.CHEAPEST[provider]
        for m in models:
            cb.addItem(f"{m.slug} (가장 저렴)" if m.slug == cheap else m.slug, m.slug)
            if m.description:
                cb.setItemData(cb.count() - 1, m.description, Qt.ToolTipRole)
        cb.currentTextChanged.connect(self._on_changed)

        def set_value(v, cb=cb):
            i = cb.findData(str(v))
            if i >= 0:
                cb.setCurrentIndex(i)
            else:
                cb.setEditText(str(v))

        def get_value(cb=cb):
            text = cb.currentText().strip()
            i = cb.findText(text)
            return str(cb.itemData(i)) if i >= 0 and cb.itemData(i) else text

        self._bind(key, set_value, get_value)
        return cb

    def _update_codex_desc(self, _t=None) -> None:
        i = self.codex_model.findText(self.codex_model.currentText().strip())
        desc = self.codex_model.itemData(i, Qt.ToolTipRole) if i >= 0 else ""
        self.codex_desc.setText(str(desc or ""))
        self.codex_desc.setVisible(bool(desc))

    def _set_effort(self, v) -> None:
        v = str(v or "low")
        if self.effort.findText(v) < 0:
            self.effort.addItem(v)          # config.json에 손으로 넣은 high 등은 지운다고 보지 않고 목록에 더함
        self.effort.setCurrentText(v)

    def _status_row(self, provider: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 6)
        h.addWidget(QLabel("CLI 상태:"))
        lb = QLabel("확인 전")
        lb.setWordWrap(True)
        self._status_labels[provider].append(lb)
        h.addWidget(lb, 1)
        b = QPushButton("다시 확인")
        b.clicked.connect(lambda: self._start_check(provider, force=True))
        h.addWidget(b)
        return w

    def _configured_cmd(self, provider: str):
        key = "ask_command" if provider == "claude" else "ask_command_codex"
        if key in self._io:
            return self._io[key][1]()
        return self.core.config.get(key)

    def _start_check(self, provider: str, force: bool = False) -> None:
        """CLI 상태 확인 (버전, 로그인만. 토큰 0). 작업 스레드에서, 제한 시간 15초."""
        if provider not in self._status_labels or provider in self._checking:
            return
        if not force and provider in self._cli_status:
            self._show_status(provider)
            return
        self._checking.add(provider)
        for lb in self._status_labels[provider]:
            lb.setText("확인 중...")
            lb.setStyleSheet("")
        configured = self._configured_cmd(provider)
        bridge = self._bridge

        def run():
            st = cli_check.check(provider, configured)
            try:
                bridge.done.emit(provider, st)
            except RuntimeError:
                pass                       # 창이 먼저 닫힘

        threading.Thread(target=run, name="cli-check", daemon=True).start()

    def _on_check_done(self, provider: str, st) -> None:
        self._checking.discard(provider)
        self._cli_status[provider] = st
        self._show_status(provider)

    def _show_status(self, provider: str) -> None:
        st = self._cli_status.get(provider)
        if not st:
            return
        color = "" if st.state == "ready" else f"color:{self.t.warn.name()};"
        for lb in self._status_labels[provider]:
            lb.setText(st.line)
            lb.setStyleSheet(color)

    # ---- 고급 탭 --------------------------------------------------------------
    def _build_advanced(self) -> None:
        lay = self._page("advanced")
        lay.addWidget(self._help("보통은 바꿀 필요가 없습니다."))
        row = QHBoxLayout()
        self.open_cmd = QLineEdit()
        self.open_cmd.textChanged.connect(self._on_changed)
        row.addWidget(self.open_cmd, 1)
        d = QPushButton("기본값")
        d.clicked.connect(lambda: self.open_cmd.setText(S.join_command(S.default_of("open_command"))))
        row.addWidget(d)
        self._bind("open_command", lambda v: self.open_cmd.setText(S.join_command(v)),
                   lambda: S.split_command(self.open_cmd.text()))
        self._item(lay, "md 여는 명령", row,
                   "{path}는 md 경로, {line}은 줄 번호로 바뀝니다. 공백이 든 경로는 큰따옴표로 묶습니다. "
                   "실행에 실패하면 기본 연결 프로그램으로 엽니다.", "open_command")
        self._item(lay, "검색 결과 최대 개수", self._spin("max_results"), "", "max_results")
        grid = QGridLayout()
        self.weight_spins = {}
        for i, (wk, name, lo, hi) in enumerate(S.WEIGHTS):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(2)
            sp.setSingleStep(0.1 if hi <= 10 else 1.0)
            sp.setMaximumWidth(120)
            sp.valueChanged.connect(self._on_changed)
            self.weight_spins[wk] = sp
            grid.addWidget(QLabel(name), i // 2, (i % 2) * 2)
            grid.addWidget(sp, i // 2, (i % 2) * 2 + 1)
        wd = QPushButton("기본값")
        wd.clicked.connect(lambda: self._set_weights(S.default_of("weights")))
        grid.addWidget(wd, 2, 3)
        grid.setColumnStretch(4, 1)
        self._bind("weights", self._set_weights, lambda: {wk: float(sp.value()) for wk, sp in self.weight_spins.items()})
        self._item(lay, "순위 가중치", grid, "BM25 관련도에 더하는 값입니다. 반감기는 최근 가산이 절반이 되는 날 수.", "weights")
        self.redact = ListEdit("text")
        self.redact.changed.connect(self._on_changed)
        self._bind("extra_redact_patterns", self.redact.set_values, self.redact.values)
        self._item(lay, "추가 가림 정규식", self.redact,
                   "한 줄에 정규식 하나. 다음에 쓰는 md부터 가립니다. 이미 쓴 md는 다시 만들지 않습니다 "
                   "(필요하면 트레이 '고급 > 대화 md 전부 다시 만들기').", "extra_redact_patterns")
        row = QHBoxLayout()
        for key, label in (("ask_tail_messages", "메시지 수"), ("ask_max_chars", "상한(자)"),
                           ("ask_timeout_seconds", "제한 시간(초)")):
            row.addWidget(QLabel(label))
            row.addWidget(self._spin(key))
            row.addSpacing(12)
        row.addStretch(1)
        box = self._item(lay, "요약 재료와 제한 시간", row, "F2 요약에 넘기는 마지막 메시지 수, 글자 수 상한, CLI 제한 시간.",
                         "ask_tail_messages")
        for k in ("ask_max_chars", "ask_timeout_seconds"):
            self._notes[k] = self._notes["ask_tail_messages"]
            self._boxes[k] = box
        self.export_url = QLineEdit()
        self.export_url.textChanged.connect(self._on_changed)
        self._bind("export_page_url", self.export_url.setText, lambda: self.export_url.text().strip())
        self._item(lay, "내보내기 페이지 주소", self.export_url, "트레이 'claude.ai 내보내기 받으러 가기'가 여는 주소.",
                   "export_page_url")
        row = QHBoxLayout()
        for text, fn in (("config.json 열기", self._open_config),
                         ("데이터 폴더 열기 (APPDATA)", lambda: self._open_dir(self.core.store.root)),
                         ("데이터 폴더 열기 (LOCALAPPDATA)", lambda: self._open_dir(self.core.store.local))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self._item(lay, "설정 파일", row, "config.json을 직접 고쳤다면 이 창을 닫고 다시 여세요.")

    def _set_weights(self, v) -> None:
        for wk, sp in self.weight_spins.items():
            sp.setValue(float((v or {}).get(wk, S.default_of("weights")[wk])))

    def _open_config(self) -> None:
        p = self.core.store.config_path
        if p.exists():
            os.startfile(str(p))
        else:
            QMessageBox.information(self, TITLE, "config.json이 아직 없습니다. 저장하면 만들어집니다.")

    def _open_dir(self, p: Path) -> None:
        if Path(p).is_dir():
            os.startfile(str(p))
        else:
            QMessageBox.information(self, TITLE, f"폴더가 없습니다: {p}")

    # ---- 값 채우기, 모으기 -------------------------------------------------------
    def populate(self, cfg: dict) -> None:
        """config 값으로 칸을 채운다. 잘못된 값은 기본값을 보여 주고 저장할 때 그 값으로 쓴다."""
        self._loading = True
        self.forced = set()
        for n in set(self._notes.values()):
            n.note("")
            n.error("")
            n.warn("")
        for f in S.FIELDS:
            v, bad = S.shown(f.key, cfg)
            if bad:
                self.forced.add(f.key)
                self._notes[f.key].note(INVALID_NOTE)
            self._io[f.key][0](v)
        self._loading = False
        self._update_capture_placeholder()
        self._update_codex_desc()
        self.initial = self.collect()
        self._on_changed()
        self._on_tab(self.tabs.currentIndex())

    def collect(self) -> dict:
        return {k: get() for k, (_set, get) in self._io.items()}

    def changed_keys(self) -> set[str]:
        cur = self.collect()
        return {k for k in cur if cur[k] != self.initial.get(k)}

    def build_new(self) -> dict:
        """지금 config에서 출발해 화면에서 바뀐 키(와 잘못돼 기본값을 보여 준 키)만 바꾼 새 dict."""
        new = copy.deepcopy(self.core.config)
        cur = self.collect()
        keys = set(cur) if self.core.store.config_broken else (self.changed_keys() | self.forced)
        for k in keys:
            new[k] = copy.deepcopy(cur[k])
        return new

    def dirty(self) -> bool:
        return bool(self.initial) and bool(self.changed_keys())

    def _on_changed(self, *_a) -> None:
        if self._loading or self.setup_mode or not self.initial:
            return                     # 칸을 만드는 중(setRange 등)에 오는 신호는 무시
        src = self._get_sources()
        self.projects.setEnabled(src["claude_code"])
        self.codex_home.setEnabled(src["codex"])
        self._boxes["reminder_days"].setVisible(src["claude_ai"])
        for site, g in self._guides:
            g.setVisible(src[SITES[site][1]])
        prov = self._io["ask_provider"][1]()
        self.claude_box.setVisible(prov == "claude")
        self.codex_box.setVisible(prov == "codex")
        self.off_note.setVisible(prov == "off")
        if prov in ("claude", "codex") and self.tabs.currentIndex() == S.TABS.index("ask"):
            self._start_check(prov)
        d = self.dirty()
        self.setWindowTitle(TITLE + (" *" if d else ""))
        self.btn_save.setEnabled(d or bool(self.forced) or bool(self.core.store.config_broken))

    def select_tab(self, tab: str | None) -> None:
        if not self.setup_mode and tab in S.TABS:
            self.tabs.setCurrentIndex(S.TABS.index(tab))
            self._on_tab(self.tabs.currentIndex())

    def _on_tab(self, idx: int) -> None:
        if S.TABS[idx] == "ask":
            prov = self._io["ask_provider"][1]()
            if prov in ("claude", "codex"):
                self._start_check(prov)

    # ---- 저장 ----------------------------------------------------------------
    def _show_errors(self, errs: dict[str, str]) -> None:
        for n in set(self._notes.values()):
            n.error("")
        first = None
        for f in S.FIELDS:
            for k, msg in errs.items():
                if k.split(".", 1)[0] == f.key:
                    self._notes[f.key].error(msg)
                    first = first or f.key
        if first:
            tab = S.tab_of(first)
            self.tabs.setCurrentIndex(S.TABS.index(tab))
            box = self._boxes.get(first)
            if box:
                self._scrolls[tab].ensureWidgetVisible(box)

    def save(self) -> bool:
        """검사 -> (보관 폴더 만들기) -> 경고 -> 외부 변경 -> 단축키 등록 시험 -> 저장 -> 적용 -> 닫기."""
        old = self.core.config
        new = self.build_new()
        errs = S.validate(new, old)
        self._show_errors(errs)
        if errs:
            return False
        miss = S.archive_missing(new)
        if miss and new.get("archive_dir") != old.get("archive_dir"):
            ans = QMessageBox.question(self, TITLE, f"보관 폴더가 없습니다: {miss}\n폴더를 만들까요?")
            if ans != QMessageBox.StandardButton.Yes:
                self._show_errors({"archive_dir": f"폴더가 없습니다: {miss}"})
                return False
            try:
                Path(miss).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                self._show_errors({"archive_dir": f"폴더를 만들지 못했습니다: {e}"})
                return False
        ws = list(S.warnings(new).values())
        ws = [w for w in ws if "쓰는 키" not in w]        # 단축키 경고는 칸 아래에 이미 보임
        prov = S.read_provider(new)
        st = self._cli_status.get(prov)
        if prov in ("claude", "codex") and st and st.state == "missing":
            ws.append(f"{cli_check.NAME[prov]} CLI를 찾지 못했습니다. F2를 누르면 실패 사유로 다시 알려 드립니다")
        if ws:
            ans = QMessageBox.warning(self, TITLE, "\n".join(ws) + "\n\n이대로 저장할까요?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return False
        if self.core.store.config_signature() != self._sig:
            box = QMessageBox(self)
            box.setWindowTitle(TITLE)
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(CHANGED_OUTSIDE)
            over = box.addButton("덮어쓰기", QMessageBox.ButtonRole.AcceptRole)
            reload_ = box.addButton("다시 읽기", QMessageBox.ButtonRole.ActionRole)
            box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is reload_:
                before = self.core.config
                changed = self.core.reload_config()
                self.hooks.applied(changed, before)
                self._sig = self.core.store.config_signature()
                self.broken.setVisible(bool(self.core.store.config_broken))
                self.populate(self.core.config)
                return False
            if box.clickedButton() is not over:
                return False
        if not S.same_hotkey(str(new.get("hotkey") or ""), str(old.get("hotkey") or "")):
            ok, why = self.hooks.try_hotkey(str(new["hotkey"]))
            if not ok:
                msg = f"{S.display_hotkey(new['hotkey'])}는 다른 프로그램이 쓰고 있어 등록하지 못했습니다"
                self._show_errors({"hotkey": msg + (f" ({why})" if why else "")})
                return False
        try:
            changed = self.core.update_config(new)
        except OSError as e:
            if "hotkey" in new and not S.same_hotkey(str(new["hotkey"]), str(old.get("hotkey") or "")):
                self.hooks.try_hotkey(str(old.get("hotkey") or S.DEFAULT_HOTKEY))   # 되돌림
            QMessageBox.warning(self, TITLE, f"config.json을 저장하지 못했습니다: {e}")
            return False
        self._done = True
        self.hooks.applied(changed, old)
        self.accept()
        return True

    def reject(self) -> None:
        """취소, Esc, X. 바꾼 것이 있으면 묻는다. 시작 안내에서는 건너뛰기와 같다."""
        if self._done:
            super().reject()
            return
        if self.setup_mode:
            self._skip()
            return
        if self.dirty():
            ans = QMessageBox.question(self, TITLE, "저장하지 않고 닫을까요?")
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._done = True
        super().reject()

    # ---- 시작 안내 (3-K) ----------------------------------------------------------
    def _build_setup(self, root: QVBoxLayout) -> None:
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        guess = S.guess_sources()
        # 1. 쓰는 서비스
        lay = self._page(title="1. 쓰는 서비스")
        lay.addWidget(self._help("쓰는 것만 고르세요. 끈 서비스는 수집도 알림도 하지 않습니다. 나중에 설정에서 바꿀 수 있습니다."))
        self.setup_sources = {}
        for s in S.SERVICES:
            cb = QCheckBox(S.SERVICE_LABEL[s])
            cb.setChecked(guess[s])
            self.setup_sources[s] = cb
            lay.addWidget(cb)
        lay.addWidget(self._help("Claude Code, Codex는 이 PC에 쓴 흔적이 있으면 미리 체크해 두었습니다. "
                                 "claude.ai, ChatGPT는 브라우저에서 쓰므로 직접 고르세요."))
        # 2. 보관 폴더
        lay = self._page(title="2. 대화 보관 폴더")
        lay.addWidget(self._help("모은 대화를 md 파일로 쌓을 곳입니다."))
        self.setup_archive = ""
        self.setup_archive_label = QLabel(str(self.core.default_archive))
        self.setup_archive_label.setWordWrap(True)
        self.setup_archive_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.setup_archive_label)
        row = QHBoxLayout()
        keep = QPushButton("그대로 쓰기")
        keep.clicked.connect(lambda: self._set_setup_archive(""))
        change = QPushButton("바꾸기...")
        change.clicked.connect(self._choose_setup_archive)
        row.addWidget(keep)
        row.addWidget(change)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self._help(CLOUD_WARNING, warn=True))
        # 3. 요약 AI
        lay = self._page(title="3. 요약 AI (F2)")
        lay.addWidget(self._help("큐에서 F2를 누르면 '어디까지 했지?'를 요약합니다. 이 PC에 설치된 CLI를 씁니다."))
        self.setup_provider = {}
        self.setup_provider_touched = False
        grp = QButtonGroup(self)
        for p, label in (("claude", "Claude (Claude Code CLI)"), ("codex", "GPT (Codex CLI)"), ("off", "끄기")):
            rb = QRadioButton(label)
            rb.clicked.connect(self._on_setup_provider)
            grp.addButton(rb)
            self.setup_provider[p] = rb
            lay.addWidget(rb)
        self.setup_model = self._help("")
        lay.addWidget(self.setup_model)
        for p in ("claude", "codex"):
            lay.addWidget(self._status_row(p))
        lay.addWidget(self._help("설치와 로그인은 직접 합니다(터미널에서 claude 또는 codex login). 모델을 바꾸려면 설정 > 요약 AI."))
        # 4. 노트 폴더와 수집 스크립트
        lay = self._page(title="4. 노트 폴더와 수집 스크립트")
        self.setup_notes = ListEdit("dir", "노트 폴더 선택 (md를 그대로 읽어 검색에 넣을 곳)")
        self._item(lay, "노트 폴더 (선택)", self.setup_notes, "내 md 폴더(Obsidian 볼트 등)를 넣으면 같이 검색됩니다. 파일은 읽기만 합니다.")
        self.setup_guides = []
        for site in SCRIPTS:
            g = self._script_guide(site)
            lay.addWidget(g)
            self.setup_guides.append((site, g))
        self._page_idx = 0

    def _set_setup_archive(self, path: str) -> None:
        self.setup_archive = path
        self.setup_archive_label.setText(path or str(self.core.default_archive))

    def _choose_setup_archive(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "보관 폴더 선택 (대화 md를 저장할 곳)", str(Path.home()))
        if d:
            self._set_setup_archive(str(Path(d)))

    def _setup_sources_value(self) -> dict:
        return {s: cb.isChecked() for s, cb in self.setup_sources.items()}

    def _setup_provider_value(self) -> str:
        return next((p for p, rb in self.setup_provider.items() if rb.isChecked()), "off")

    def _on_setup_provider(self) -> None:
        self.setup_provider_touched = True
        self._refresh_setup_ask()

    def _refresh_setup_ask(self) -> None:
        p = self._setup_provider_value()
        for prov, labels in self._status_labels.items():
            for lb in labels:
                lb.parentWidget().setVisible(prov == p)
        if p in ("claude", "codex"):
            self.setup_model.setText(f"모델: {cli_check.CHEAPEST[p]} (가장 저렴)")
            self._start_check(p)
        else:
            self.setup_model.setText("F2를 누르면 '요약 AI가 꺼져 있습니다' 한 줄만 보여 줍니다.")

    def _go(self, step: int) -> None:
        last = self.pages.count() - 1
        if step > 0 and self._page_idx == last:
            self._finish()
            return
        self._page_idx = max(0, min(last, self._page_idx + step))
        self.pages.setCurrentIndex(self._page_idx)
        if self._page_idx == 2:
            if not self.setup_provider_touched:
                self.setup_provider[S.setup_provider(self._setup_sources_value())].setChecked(True)
            self._refresh_setup_ask()
        if self._page_idx == 3:
            src = self._setup_sources_value()
            for site, g in self.setup_guides:
                g.setVisible(src[SITES[site][1]])
        self.btn_prev.setEnabled(self._page_idx > 0)
        self.btn_next.setText("마치기" if self._page_idx == last else "다음")

    def _finish(self) -> None:
        cfg = S.setup_config(self._setup_sources_value(), self.setup_archive, self.setup_notes.values(),
                             self._setup_provider_value())
        errs = S.validate(cfg)
        if errs:
            QMessageBox.warning(self, SETUP_TITLE, "\n".join(errs.values()))
            return
        self._save_setup(cfg, True)

    def _skip(self) -> None:
        self._save_setup(S.skip_config(), False)

    def _save_setup(self, cfg: dict, finished: bool) -> None:
        old = self.core.config
        try:
            changed = self.core.update_config(cfg)
        except OSError as e:
            QMessageBox.warning(self, SETUP_TITLE, f"config.json을 저장하지 못했습니다: {e}\n다음 실행 때 다시 묻습니다.")
            changed = set()
        self._done = True
        self.hooks.setup_finished(finished, changed, old)
        self.accept()
