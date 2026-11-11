"""설정 창과 시작 안내 (SPEC-settings.md 3-A, 3-B, 3-E, 3-I, 3-J, 3-K).

검사, 바뀐 키 계산, 기본값 규칙은 settings.py, CLI 확인은 cli_check.py, 색과 스타일은 theme.py에 있고
여기는 화면 구성만 다룬다. 저장 뒤 트레이 앱 쪽 적용(단축키, 타이머, 감시 폴더, 검색 가중치, 테마)은
Hooks로 main.py에 맡긴다.

화면 구성 (docs/redesign-plan.md): 위 설정 찾기 칸, 왼쪽 사이드바(208px) + 오른쪽 페이지, 아래 막대(바뀐 설정 수, 취소, 저장).
페이지는 섹션(_section) 단위: 제목 아래 카드 하나, 카드 안은 줄(_row) 단위.
줄은 두 줄까지다. 보통은 "왼쪽 이름(+ⓘ) / 설명 한 줄, 오른쪽 입력칸"이고, 넓은 칸(목록, 여러 줄 입력)만
stacked로 "이름 + ⓘ + 설명 한 줄" 아래에 입력칸을 둔다. 긴 설명은 ⓘ 툴팁에 담는다.
"""
from __future__ import annotations

import copy
import html
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetrics, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QRadioButton,
                               QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QToolButton, QToolTip, QVBoxLayout,
                               QWidget)

from . import cli_check
from . import settings as S
from . import theme as T
from .store import expand
from .watcher import downloads_dir
from .window import TEXT_FONTS, ElideLabel

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
SIDEBAR_W = 208
SECTION_GAP = 36
PATH_W = 380          # 경로 칸(입력 + 찾아보기 + 열기) 폭
NUM_W = 118           # 숫자 칸 폭
AUTO_TIP_LEN = 46     # 설명이 이보다 길면 한 줄에 줄여 보이고 전체는 ⓘ 툴팁에 둔다 (문구 확정 전 임시 규칙)
TIP_W = 340           # ⓘ 툴팁 폭
ROW_PAD_X, ROW_PAD_Y = 16, 12


@dataclass
class Hooks:
    """트레이 앱(main.py)이 넘기는 동작. 기본값은 아무것도 하지 않음(테스트, 단독 실행용)."""
    open_url: Callable[[str], None] = lambda url: None
    try_hotkey: Callable[[str], tuple] = lambda key: (True, "")       # 새 키 시험 등록(성공하면 바로 교체)
    recording: Callable[[bool], None] = lambda on: None                # 단축키 칸 기록 중: 전역 키 잠시 해제
    applied: Callable[[set, dict], None] = lambda changed, old: None   # 저장 뒤 앱 쪽 적용
    setup_finished: Callable[[bool, set, dict], None] = lambda finished, changed, old: None


def set_tone(w: QWidget, tone: str) -> None:
    """글자 톤 바꾸기. "error"면 빨강(theme.py의 error), 빈 값이면 원래 색."""
    if w.property("tone") == tone:
        return
    w.setProperty("tone", tone)
    w.style().unpolish(w)
    w.style().polish(w)


def _label(text: str, name: str, wrap: bool = True) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName(name)
    lb.setWordWrap(wrap)
    lb.setTextFormat(Qt.PlainText)
    return lb


def _wrap(layout: QLayout) -> QWidget:
    w = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    w.setLayout(layout)
    return w


def _button(text: str, kind: str = "") -> QPushButton:
    """kind: "" 보조 버튼, primary(저장), secondary(취소 등 아래 버튼), link(강조색 글자 링크), chip(고르기)."""
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if kind in ("link", "chip", "nav"):
        b.setCursor(Qt.PointingHandCursor)
    b.setAutoDefault(False)
    return b


# ---- 확인 창 -----------------------------------------------------------------
class Confirm(QDialog):
    """QMessageBox 대신 쓰는 확인 창. 테마를 따르고 단추는 한국어, 아이콘이 없어 Windows 알림 소리가 나지 않는다."""

    def __init__(self, parent, title: str, text: str, buttons: list[tuple[str, str]], primary: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.choice = ""                       # Esc, X로 닫으면 빈 값
        win = parent.window() if parent is not None else None
        self.t = getattr(win, "t", None) or T.make()
        if win is not None:
            self.setFont(win.font())
        self.setPalette(T.palette(self.t))
        self.setStyleSheet(T.dialog_qss(self.t))
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 18)
        v.setSpacing(20)
        lb = _label(text, "name")
        lb.setMinimumWidth(340)
        lb.setMaximumWidth(560)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(lb)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        for key, label in buttons:
            b = _button(label, "primary" if key == primary else "secondary")
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            row.addWidget(b)
            if key == primary:
                b.setDefault(True)
                b.setFocus()
        v.addLayout(row)

    def _pick(self, key: str) -> None:
        self.choice = key
        self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        T.style_titlebar(self, self.t)


def ask(parent, title: str, text: str, buttons: list[tuple[str, str]], primary: str | None = None) -> str:
    """단추 (키, 글자) 목록을 보여 주고 고른 키를 돌려준다. 닫으면 "". primary를 안 주면 마지막 단추."""
    d = Confirm(parent, title, text, buttons, primary or buttons[-1][0])
    d.exec()
    return d.choice


def tell(parent, title: str, text: str) -> None:
    ask(parent, title, text, [("ok", "확인")])


# ---- 작은 위젯 ---------------------------------------------------------------
class Note(QLabel):
    """칸 아래 한 줄. 오류 > 경고 > 안내 순으로 하나만 보여 준다. 오류와 경고는 빨강, 안내는 보조색."""

    def __init__(self):
        super().__init__("")
        self.setObjectName("desc")
        self.setWordWrap(True)
        self.setTextFormat(Qt.PlainText)
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
        set_tone(self, "error" if (self._error or self._warn) else "")
        self.setText(text)
        self.setVisible(bool(text))


class NumEdit(QFrame):
    """화살표 없는 숫자 칸. 숫자는 오른쪽 정렬, 단위는 칸 안 오른쪽. 테두리는 이 틀이 그린다."""

    def __init__(self, spin: QAbstractSpinBox, unit: str = "", width: int = NUM_W):
        super().__init__()
        self.setObjectName("numBox")
        self.spin = spin
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        spin.setFrame(False)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 10, 6)
        h.setSpacing(5)
        h.addWidget(spin, 1)
        if unit:
            self.unit = _label(unit, "unit", wrap=False)
            h.addWidget(self.unit)
        self.setFixedWidth(width)
        spin.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.setProperty("focus", e.type() == QEvent.FocusIn)
            self.style().unpolish(self)
            self.style().polish(self)
        return False

    def mousePressEvent(self, e):
        self.spin.setFocus()
        self.spin.selectAll()


class PathEdit(QWidget):
    changed = Signal()

    def __init__(self, title: str, placeholder: str = "", file: bool = False, open_button: bool = True):
        super().__init__()
        self.title, self.file = title, file
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(lambda _t: self.changed.emit())
        lay.addWidget(self.edit, 1)
        b = _button("찾아보기...")
        b.clicked.connect(self._browse)
        lay.addWidget(b)
        if open_button:
            o = _button("열기")
            o.clicked.connect(self._open)
            lay.addWidget(o)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, v: str) -> None:
        self.edit.setText(str(v or ""))
        self.edit.setCursorPosition(0)        # 긴 경로는 앞부분(드라이브)부터 보이게

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
            tell(self, TITLE, f"폴더가 없습니다: {p or '(비어 있음)'}")


class ListEdit(QWidget):
    """폴더 목록 + 추가 / 빼기. pick: 추가 때 부를 함수 (없으면 폴더 고르기)."""
    changed = Signal()

    def __init__(self, title: str = "", pick: Callable[[], str | None] | None = None):
        super().__init__()
        self.title, self.pick = title, pick
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.list = QListWidget()
        self.list.setMaximumHeight(104)
        self.list.itemChanged.connect(lambda _i: self.changed.emit())
        lay.addWidget(self.list, 1)
        col = QVBoxLayout()
        col.setSpacing(6)
        add = _button("추가...")
        add.clicked.connect(self._add)
        rm = _button("빼기")
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
            self.list.addItem(QListWidgetItem(str(v)))
        self.list.blockSignals(False)

    def _add(self) -> None:
        if self.pick:
            v = self.pick()
        else:
            d = QFileDialog.getExistingDirectory(self, self.title, str(Path.home()))
            v = str(Path(d)) if d else None
        if v and v not in self.values():
            self.list.addItem(QListWidgetItem(v))
            self.changed.emit()

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self.changed.emit()


class LinesEdit(QPlainTextEdit):
    """한 줄에 하나씩 쓰는 여러 줄 입력칸 (추가 가림 정규식). 빈 줄과 앞뒤 공백은 뺀다."""
    changed = Signal()

    def __init__(self, placeholder: str = ""):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabChangesFocus(True)
        self.setFixedHeight(104)
        self.textChanged.connect(self.changed.emit)

    def values(self) -> list[str]:
        return [s.strip() for s in self.toPlainText().splitlines() if s.strip()]

    def set_values(self, vs) -> None:
        self.blockSignals(True)
        self.setPlainText("\n".join(str(v) for v in vs or []))
        self.blockSignals(False)


class HotkeyEdit(QLineEdit):
    """누르면 '키를 누르세요' 상태가 되고 다음에 누른 조합을 기록한다 (3-E-1)."""
    recorded = Signal(str)       # 누른 조합 ('ctrl+alt+j' 꼴, 검사 전)
    recording = Signal(bool)
    PROMPT = "키를 누르세요 (Esc 취소, Backspace 기본값)"
    _MOD_KEYS = {Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R,
                 Qt.Key_AltGr}

    def __init__(self):
        super().__init__()
        self.setObjectName("hotkey")
        self.setReadOnly(True)
        self.setAttribute(Qt.WA_InputMethodEnabled, False)    # 한글 IME가 키를 가로채지 않게
        self._value = ""
        self.active = False
        self.t: T.Theme | None = None          # 키캡을 칠할 색 (창이 채운다)
        self._set_caps(True)

    def _set_caps(self, on: bool) -> None:
        """평소에는 글자를 숨기고 키캡 모양으로 그린다. 기록 중에는 안내 글자를 그대로 보인다."""
        self.setProperty("caps", on)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def value(self) -> str:
        return self._value

    def set_value(self, v: str) -> None:
        self._value = str(v or "")
        if not self.active:
            self.setText(S.display_hotkey(self._value))
            self.update()

    def start(self) -> None:
        if not self.active:
            self.active = True
            self.setText(self.PROMPT)
            self._set_caps(False)
            self.recording.emit(True)

    def stop(self) -> None:
        if self.active:
            self.active = False
            self.setText(S.display_hotkey(self._value))
            self._set_caps(True)
            self.recording.emit(False)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.active or self.t is None or not self._value:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        x, h = 10, fm.height() + 8
        y = (self.height() - h) // 2
        for part in S.display_hotkey(self._value).split("+"):
            w = fm.horizontalAdvance(part) + 18
            rect = QRect(x, y, w, h)
            p.setPen(QPen(self.t.input_border, 1))
            p.setBrush(self.t.button)
            p.drawRoundedRect(rect.adjusted(0, 0, 0, 0), 5, 5)
            p.setPen(QPen(self.t.input_border, 2))              # 아래쪽이 조금 두꺼운 키캡 선
            p.drawLine(rect.left() + 4, rect.bottom(), rect.right() - 4, rect.bottom())
            p.setPen(self.t.text)
            p.drawText(rect.adjusted(0, 0, 0, -1), Qt.AlignCenter, part)
            x += w + 6

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


class Section(QWidget):
    """섹션: 제목(+ 옆 설명, 오른쪽 링크) 아래에 카드 하나. 카드 안에 줄이 쌓인다(줄 위에 얇은 구분선)."""

    def __init__(self, title: str, caption: str = "", link: tuple[str, Callable] | None = None, intro: str = "",
                 first: bool = False):
        super().__init__()
        self.tab = ""                    # 속한 탭 (설정 찾기에서 첫 보이는 섹션을 가리는 데 씀)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0 if first else SECTION_GAP, 0, 0)
        self._v = v
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 10)
        head.setSpacing(12)
        head.addWidget(_label(title, "sectionTitle", wrap=False), 0, Qt.AlignBottom)
        if caption:
            head.addWidget(_label(caption, "caption", wrap=False), 0, Qt.AlignBottom)
        head.addStretch(1)
        if link:
            self.link = _button(link[0], "link")
            self.link.clicked.connect(link[1])
            head.addWidget(self.link, 0, Qt.AlignBottom)
        v.addLayout(head)
        if intro:
            lb = _label(intro, "desc")
            lb.setContentsMargins(0, 0, 0, 10)
            v.addWidget(lb)
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setAttribute(Qt.WA_StyledBackground, True)
        self.rows = QVBoxLayout(self.card)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(0)
        v.addWidget(self.card)


    def set_first(self, first: bool) -> None:
        """페이지에서 첫 보이는 섹션이면 위 간격을 없앤다 (숨은 섹션 뒤에 큰 빈칸이 남지 않게)."""
        self._v.setContentsMargins(0, 0 if first else SECTION_GAP, 0, 0)


class InfoButton(QToolButton):
    """이름 옆 ⓘ. 올려 두면(또는 누르면) 자세한 설명 툴팁이 뜬다."""

    def __init__(self, tip: str):
        super().__init__()
        self.setObjectName("info")
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.WhatsThisCursor)
        self.setIconSize(QSize(14, 14))
        self.setAutoRaise(True)
        self.tip = tip
        self.setToolTip(tip_html(tip))
        self.setToolTipDuration(60000)

    def mousePressEvent(self, e):
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())), self.toolTip(), self)
        e.accept()


def tip_html(text: str) -> str:
    """툴팁 글을 일정한 폭(TIP_W)에서 줄바꿈되는 표로 감싼다 (Qt 툴팁은 순수 글자면 줄바꿈하지 않는다)."""
    return f'<table width="{TIP_W}"><tr><td>{html.escape(text).replace(chr(10), "<br>")}</td></tr></table>'


class NavButton(QPushButton):
    """사이드바 탭. 찾기 중에는 오른쪽에 맞은 수 배지가 붙는다 (text()는 탭 이름 그대로)."""

    def __init__(self, text: str):
        super().__init__(text)
        self.badge = QLabel("", self)
        self.badge.setObjectName("navBadge")
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.badge.hide()

    def set_count(self, n: int | None) -> None:
        """n: 맞은 수. None이면 찾기를 안 하는 중 (배지, 흐림 없음)."""
        self.badge.setVisible(bool(n))
        if n:
            self.badge.setText(str(n))
            self.badge.adjustSize()
            self._place()
        dim = n == 0
        if self.property("dim") != dim:
            self.setProperty("dim", dim)
            self.style().unpolish(self)
            self.style().polish(self)

    def _place(self) -> None:
        self.badge.move(self.width() - self.badge.width() - 10, (self.height() - self.badge.height()) // 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()


class SearchBox(QFrame):
    """설정 찾기 칸: 강조색 돋보기, 입력, 오른쪽에 (비었을 때) Ctrl F 키캡 또는 (입력 중) 맞은 수."""

    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("searchBox")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 2, 12, 2)
        h.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("설정 찾기")
        self.edit.setClearButtonEnabled(False)
        self.edit.textChanged.connect(self._on_text)
        self.count = QLabel("")
        self.count.setObjectName("searchCount")
        self.keys = QWidget()
        kh = QHBoxLayout(self.keys)
        kh.setContentsMargins(0, 0, 0, 0)
        kh.setSpacing(4)
        for k in ("Ctrl", "F"):
            cap = QLabel(k)
            cap.setObjectName("keycap")
            kh.addWidget(cap)
        h.addWidget(self.icon)
        h.addWidget(self.edit, 1)
        h.addWidget(self.count)
        h.addWidget(self.keys)
        self.count.hide()

    def text(self) -> str:
        return self.edit.text().strip()

    def set_count(self, n: int) -> None:
        typing = bool(self.text())
        self.keys.setVisible(not typing)
        self.count.setVisible(typing)
        self.count.setText(f"{n}개" if n else "맞는 설정 없음")

    def focus_all(self) -> None:
        self.edit.setFocus()
        self.edit.selectAll()

    def _on_text(self, _t: str) -> None:
        self.keys.setVisible(not self.text())
        self.changed.emit(self.text())


@dataclass
class RowRef:
    """설정 찾기에 쓰는 줄 정보."""
    tab: str
    sec: "Section"
    box: QWidget
    line: QWidget              # 줄 위 구분선 (카드의 첫 보이는 줄에서는 숨긴다)
    name: str
    desc: str
    tip: str
    name_lb: QLabel | None
    desc_lb: ElideLabel | None
    key: str | None = None
    empty_desc: str = ""       # 칸이 비어 있을 때만 설명 줄에 보일 글
    counted: bool = True

    @property
    def haystack(self) -> str:
        return " ".join(s for s in (self.name, self.desc, self.tip, self.empty_desc) if s).lower()

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
        self.t = T.from_config(core.config)
        font = QFont()
        font.setFamilies(TEXT_FONTS)
        font.setPointSizeF(10.5)
        self.setFont(font)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._io: dict[str, tuple[Callable, Callable]] = {}
        self._notes: dict[str, Note] = {}
        self._boxes: dict[str, QWidget] = {}
        self._scrolls: dict[str, QScrollArea] = {}
        self._sections: list[QVBoxLayout] = []   # 섹션이 하나라도 들어간 페이지 (첫 섹션은 위 간격 없음)
        self._secs: list[Section] = []           # 만든 섹션 전부 (설정 찾기에서 보임/숨김)
        self._rows: list[RowRef] = []            # 만든 줄 전부 (설정 찾기 대상)
        self._nat: dict[QWidget, bool] = {}      # 설정값에 따라 줄, 섹션이 보여야 하나 (찾기 필터와 따로 기억)
        self._info_buttons: list[InfoButton] = []
        self._build_tab = ""
        self.search: SearchBox | None = None
        self._loading = False
        self._done = False
        self._tab = "general"
        self.forced: set[str] = set()
        self.initial: dict = {}
        self._cli_status: dict[str, cli_check.CliStatus] = {}
        self._checking: set[str] = set()
        self._status_labels: dict[str, list[QLabel]] = {"claude": [], "codex": []}
        self._status_rows: dict[str, list[QWidget]] = {"claude": [], "codex": []}
        self._guides: list[tuple[str, QWidget]] = []
        self._nav_icons: list[tuple[QPushButton, str]] = []
        self._swatches: dict[str, QPushButton] = {}
        self._bridge = _CheckBridge()
        self._bridge.done.connect(self._on_check_done)
        self._sig = core.store.config_signature()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.broken = _label("config.json을 읽지 못해 기본값으로 동작 중입니다. 저장하면 지금 화면 내용으로 새로 씁니다 "
                             "(깨진 파일은 config.json.bak에 있음)", "banner")
        self.broken.setVisible(bool(core.store.config_broken) and not setup)
        root.addWidget(self.broken)
        footer = QFrame()
        footer.setObjectName("footer")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 12, 24, 12)
        buttons.setSpacing(8)
        if setup:
            self.setWindowTitle(SETUP_TITLE)
            self.setMinimumSize(640, 480)
            self.resize(760, 640)
            self._build_setup(root)
            self.btn_prev = _button("이전", "secondary")
            self.btn_next = _button("다음", "primary")
            self.btn_skip = _button("건너뛰기", "secondary")
            self.btn_prev.clicked.connect(lambda: self._go(-1))
            self.btn_next.clicked.connect(lambda: self._go(1))
            self.btn_skip.clicked.connect(self.reject)
            buttons.addWidget(self.btn_skip)
            buttons.addStretch(1)
            buttons.addWidget(self.btn_prev)
            buttons.addWidget(self.btn_next)
            self._go(0)
        else:
            self.setMinimumSize(760, 520)
            self.resize(920, 740)
            # 머리: 설정 찾기 칸
            self.search = SearchBox()
            self.search.setMaximumWidth(680)
            self.search.changed.connect(lambda _t: self._refresh_filter())
            head = QFrame()
            head.setObjectName("searchHead")
            hh = QHBoxLayout(head)
            hh.setContentsMargins(24, 14, 24, 14)
            hh.addWidget(self.search, 1)
            hh.addStretch(1)
            root.addWidget(head)
            body = QHBoxLayout()
            body.setContentsMargins(0, 0, 0, 0)
            body.setSpacing(0)
            body.addWidget(self._build_sidebar())
            right = QVBoxLayout()
            right.setContentsMargins(0, 0, 0, 0)
            right.setSpacing(0)
            self.no_match = _label("", "pageDesc")
            self.no_match.setContentsMargins(42, 20, 42, 0)
            self.no_match.hide()
            right.addWidget(self.no_match)
            self.stack = QStackedWidget()
            right.addWidget(self.stack, 1)
            body.addLayout(right, 1)
            root.addLayout(body, 1)
            for key in S.TABS:
                getattr(self, f"_build_{key}")()
            for lay in self._sections:
                lay.addStretch(1)                 # 내용이 창보다 짧으면 남는 높이는 맨 아래로
            # 아래 막대: 바뀐 설정 수 | 취소, 저장 (Esc, Ctrl+S 단축키는 키 안내 없이 동작)
            self.changed_dot = QLabel()
            self.changed_dot.setObjectName("changedDot")
            self.changed_dot.setFixedSize(8, 8)
            self.changed_text = QLabel("")
            self.changed_text.setObjectName("changedText")
            self.changed_dot.hide()
            self.changed_text.hide()
            self.btn_cancel = _button("취소", "secondary")
            self.btn_save = _button("저장", "primary")
            self.btn_save.clicked.connect(self.save)
            self.btn_cancel.clicked.connect(self.reject)
            buttons.addWidget(self.changed_dot, 0, Qt.AlignVCenter)
            buttons.addWidget(self.changed_text)
            buttons.addStretch(1)
            buttons.addWidget(self.btn_cancel)
            buttons.addWidget(self.btn_save)
            QShortcut(QKeySequence("Ctrl+S"), self, activated=self._shortcut_save)
            QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.focus_all)
        root.addWidget(footer)
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)           # Enter로 엉뚱한 버튼이 눌리지 않게
        if setup:
            self.btn_next.setDefault(True)
            self._apply_theme(self.t)
        else:
            self.populate(core.config)        # 테마도 여기서 칠한다 (_preview_theme)
            self.select_tab(tab)
        self._wheel_guard = _WheelGuard(self)
        guard_wheel(self, self._wheel_guard)
        self._center()

    # ---- 테마 ---------------------------------------------------------------
    def _apply_theme(self, t: T.Theme) -> None:
        self.t = t
        self.setPalette(T.palette(t))
        self.setStyleSheet(T.dialog_qss(t))
        for b, name in self._nav_icons:
            b.setIcon(T.icon(name, t.text, 16))
        for acc, b in self._swatches.items():
            b.setIcon(T.swatch(T.accent_color(acc, t.dark)))
        for b in self._info_buttons:
            b.setIcon(T.icon("info", t.sub, 14))
        if self.search is not None:
            self.search.icon.setPixmap(T.icon("search", t.accent, 18).pixmap(18, 18))
        if hasattr(self, "hotkey"):
            self.hotkey.t = t
            self.hotkey.update()
        if self._rows and self.search is not None:
            self._refresh_filter()                # 맞은 글자 바탕색이 테마를 따라 바뀐다
        if self.isVisible():
            T.style_titlebar(self, t)

    def _preview_theme(self, *_a) -> None:
        """모드, 강조색을 고르면 저장 전에 이 창에 먼저 칠해 본다 (취소하면 저장 안 됨)."""
        if "theme_mode" not in self._io:
            return
        self._apply_theme(T.make(self._io["theme_mode"][1](), self._io["theme_accent"][1]()))

    def system_theme_changed(self) -> None:
        """Windows 앱 모드가 바뀜 (main.py가 부름). 시스템 모드를 고른 상태면 다시 칠한다."""
        if self.setup_mode:
            self._apply_theme(T.from_config(self.core.config))
        else:
            self._preview_theme()

    def showEvent(self, e):
        super().showEvent(e)
        T.style_titlebar(self, self.t)

    # ---- 공통 도우미 --------------------------------------------------------
    def _center(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.move(g.left() + (g.width() - self.width()) // 2, g.top() + (g.height() - self.height()) // 2)


    def _shortcut_save(self) -> None:
        if not self.setup_mode and self.btn_save.isEnabled():
            self.save()

    def _help(self, text: str, warn: bool = False) -> QLabel:
        lb = _label(text, "desc")
        if warn:
            set_tone(lb, "error")
        return lb

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(SIDEBAR_W)
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 22, 12, 12)
        v.setSpacing(2)
        v.addWidget(_label("설정", "sideCaption", wrap=False))
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for i, key in enumerate(S.TABS):
            b = NavButton(S.TAB_LABEL[key])
            b.setObjectName("nav")
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoDefault(False)
            b.setCheckable(True)
            b.setIconSize(QSize(16, 16))
            b.clicked.connect(lambda _=False, k=key: self.select_tab(k))
            self.nav.addButton(b, i)
            self.nav_buttons.append(b)
            self._nav_icons.append((b, key))
            v.addWidget(b)
        v.addStretch(1)
        return side

    def _page(self, tab: str | None = None, title: str = "", desc: str = "") -> QVBoxLayout:
        self._build_tab = tab or ""
        w = QWidget()
        w.setObjectName("content")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(42, 34, 42, 40)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignTop)
        lay.addWidget(_label(title, "pageTitle", wrap=False))
        if desc:
            lay.addSpacing(6)
            lay.addWidget(_label(desc, "pageDesc"))
        lay.addSpacing(30)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)    # 긴 안내 줄은 옆으로 넘치지 않고 줄바꿈
        sc.setFrameShape(QFrame.NoFrame)
        sc.setWidget(w)
        if tab:
            self._scrolls[tab] = sc
            self.stack.addWidget(sc)
        else:
            self.pages.addWidget(sc)
        return lay

    def _section(self, lay: QVBoxLayout, title: str, caption: str = "", link=None, intro: str = "") -> Section:
        first = not any(x is lay for x in self._sections)
        if first:
            self._sections.append(lay)        # 붙잡아 둔다 (id 재사용 방지)
        sec = Section(title, caption, link, intro, first=first)
        sec.tab = self._build_tab
        lay.addWidget(sec)
        self._secs.append(sec)
        return sec

    def _row(self, sec: Section, title: str, control=None, desc: str = "", key: str | None = None,
             stacked: bool = False, after: str = "", warn: str = "", extras: tuple = (), tip: str = "",
             empty_desc: str = "", plain: bool = False) -> QWidget:
        """줄 하나. 두 줄까지: 보통은 왼쪽 `이름(굵게) + ⓘ` / `설명 한 줄`, 오른쪽 입력칸.
        stacked: `이름 + ⓘ + 설명 한 줄` 아래에 입력칸 (목록, 여러 줄 입력, 강조색 등 넓은 칸).
        tip: ⓘ 툴팁 글. 설명이 AUTO_TIP_LEN보다 길고 tip이 없으면 설명 전체를 툴팁에 두고 한 줄로 줄여 보인다
        (문구 확정 전 임시 규칙). empty_desc: 이 칸이 비어 있을 때만 설명 줄에 보일 글 (key 필요).
        plain: 이름을 굵지 않게, 줄바꿈하며 보인다 (설치 단계처럼 문장인 줄). after/warn/extras/알림은 아래에 붙는다."""
        if isinstance(control, QLayout):
            control = _wrap(control)
        if isinstance(control, PathEdit):         # 경로 칸은 넓다: 이름 아래에 가로로 펼친다
            stacked = True
            control.setMinimumWidth(0)
            control.setMaximumWidth(16777215)
        box = QWidget()
        box.setObjectName("rowBox")
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        line = QFrame()
        line.setObjectName("hline")
        line.setFixedHeight(1)
        v.addWidget(line)
        if not tip and not plain and len(desc) > AUTO_TIP_LEN:
            tip = desc
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        name_lb = None
        if title:
            if plain:
                name_lb = _label(title, "name")
                head.addWidget(name_lb, 1)
            else:
                name_lb = ElideLabel(title)
                name_lb.setObjectName("rowName")
                name_lb.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
                head.addWidget(name_lb, 0)
        if tip and title and not plain:
            info = InfoButton(tip)
            info.setIcon(T.icon("info", self.t.sub, 14))
            self._info_buttons.append(info)
            head.addWidget(info, 0, Qt.AlignVCenter)
        desc_lb = None
        if desc and not plain:
            desc_lb = ElideLabel(desc)
            desc_lb.setObjectName("desc")
            desc_lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        elif desc:
            desc_lb = _label(desc, "desc")           # plain 줄: 줄바꿈하며 전부 보인다
        tail: list[QWidget] = []
        if after:
            tail.append(_label(after, "desc"))
        if warn:
            tail.append(self._help(warn, warn=True))
        tail.extend(extras)
        if key:
            n = Note()
            self._notes[key] = n
            self._boxes[key] = box
            tail.append(n)
        if stacked:
            col = QVBoxLayout()
            col.setContentsMargins(ROW_PAD_X, ROW_PAD_Y, ROW_PAD_X, ROW_PAD_Y)
            col.setSpacing(8)
            if desc_lb is not None and not plain:
                head.addWidget(desc_lb, 1)
            else:
                head.addStretch(1)
            if title or desc_lb is not None:
                col.addLayout(head)
            if desc_lb is not None and plain:
                col.addWidget(desc_lb)
            if control is not None:
                col.addWidget(control)
            for w in tail:
                col.addWidget(w)
            v.addLayout(col)
        else:
            text = QVBoxLayout()
            text.setSpacing(2)
            if title:
                if not plain:
                    head.addStretch(1)
                text.addLayout(head)
            if desc_lb is not None:
                text.addWidget(desc_lb)
            for w in tail:
                text.addWidget(w)
            h = QHBoxLayout()
            h.setContentsMargins(ROW_PAD_X, ROW_PAD_Y, ROW_PAD_X, ROW_PAD_Y)
            h.setSpacing(24)
            h.addLayout(text, 1)
            if control is not None:
                h.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
            v.addLayout(h)
        sec.rows.addWidget(box)
        self._rows.append(RowRef(self._build_tab, sec, box, line, title, desc, tip, name_lb, desc_lb, key, empty_desc))
        return box
    def _bind(self, key: str, setter: Callable, getter: Callable) -> None:
        self._io[key] = (setter, getter)

    def _spin(self, key: str, unit: str = "", width: int = NUM_W) -> NumEdit:
        f = S.FIELD[key]
        sp = QSpinBox()
        sp.setRange(int(f.lo), int(f.hi))
        if key == "ask_max_chars":
            sp.setSingleStep(1000)
            sp.setGroupSeparatorShown(True)
        sp.valueChanged.connect(self._on_changed)
        self._bind(key, lambda v, sp=sp: sp.setValue(int(v)), sp.value)
        return NumEdit(sp, unit, width)

    def _path(self, key: str, title: str, placeholder: str = "") -> PathEdit:
        pe = PathEdit(title, placeholder)
        pe.setFixedWidth(PATH_W)
        pe.changed.connect(self._on_changed)
        self._bind(key, pe.set_value, pe.value)
        return pe

    def _checks(self, names: dict[str, str]) -> tuple[QWidget, dict[str, QCheckBox]]:
        row = QHBoxLayout()
        row.setSpacing(16)
        boxes = {}
        for k, label in names.items():
            cb = QCheckBox(label)
            cb.toggled.connect(self._on_changed)
            row.addWidget(cb)
            boxes[k] = cb
        row.addStretch(1)
        return _wrap(row), boxes

    def _chips(self, key: str, labels: dict[str, str], default: str, swatch: bool = False,
               segment: bool = False) -> QWidget:
        """하나만 고르는 단추 묶음 (모드, 강조색). 고르면 바로 이 창에 미리 칠한다.
        segment: 서로 붙은 버튼(세그먼트) 모양."""
        row = QHBoxLayout()
        row.setSpacing(0 if segment else 6)
        grp = QButtonGroup(self)
        btns: dict[str, QPushButton] = {}
        for i, (k, label) in enumerate(labels.items()):
            b = _button(label, "seg" if segment else "chip")
            if segment:
                b.setProperty("segpos", "first" if i == 0 else ("last" if i == len(labels) - 1 else "mid"))
                b.setCursor(Qt.PointingHandCursor)
            b.setCheckable(True)
            if swatch:
                b.setIconSize(QSize(12, 12))
                self._swatches[k] = b
            b.clicked.connect(self._on_changed)
            b.clicked.connect(self._preview_theme)
            grp.addButton(b)
            btns[k] = b
            row.addWidget(b)
        self._bind(key, lambda v: btns.get(v, btns[default]).setChecked(True),
                   lambda: next((k for k, b in btns.items() if b.isChecked()), default))
        return _wrap(row)

    # ---- 일반 탭 -------------------------------------------------------------
    def _build_general(self) -> None:
        lay = self._page("general", "일반")
        sec = self._section(lay, "검색 창")
        self.hotkey = HotkeyEdit()
        self.hotkey.setFixedWidth(240)
        self.hotkey.recorded.connect(self._on_hotkey_recorded)
        self.hotkey.recording.connect(self.hooks.recording)
        self._bind("hotkey", self.hotkey.set_value, self.hotkey.value)
        self._row(sec, "검색 창 단축키", self.hotkey,
                  f"칸을 누르고 새 조합을 누릅니다. 저장할 때 바로 등록해 봅니다. Backspace는 기본값"
                  f"({S.display_hotkey(S.DEFAULT_HOTKEY)}).", "hotkey")

        sec = self._section(lay, "모양", "검색 창, 설정 창, 시작 안내에 같이 씁니다")
        self._row(sec, "모드", self._chips("theme_mode", S.THEME_MODE_LABEL, "system", segment=True),
                  "시스템은 Windows 앱 모드(라이트/다크)를 따라갑니다.", "theme_mode")
        self._row(sec, "강조색", self._chips("theme_accent", S.THEME_ACCENT_LABEL, "ink_blue", swatch=True),
                  "저장 버튼, 링크, 입력 중인 칸 테두리에 씁니다.", "theme_accent", stacked=True)

        sec = self._section(lay, "폴더")
        self.archive = self._path("archive_dir", "보관 폴더 선택 (대화 md를 저장할 곳)", str(self.core.default_archive))
        self._row(sec, "대화 보관 폴더", self.archive,
                  "비면 기본 위치를 씁니다. 기존 md는 옮기지 않습니다. 필요하면 직접 옮긴 뒤 트레이 '고급 > 검색 색인 다시 만들기'.",
                  "archive_dir", warn=CLOUD_WARNING)
        self.notes = ListEdit("노트 폴더 선택 (md를 그대로 읽어 검색에 넣을 곳)")
        self.notes.changed.connect(self._on_changed)
        self._bind("note_dirs", self.notes.set_values, self.notes.values)
        self._row(sec, "노트 폴더", self.notes, "내 md 폴더(Obsidian 볼트 등)를 그대로 검색에 넣습니다. 파일은 읽기만 합니다.",
                  "note_dirs", stacked=True)
        self.journal = self._path("journal_dir", "업무 일지 보관함 루트 선택")
        off = _button("끄기")
        off.clicked.connect(lambda: self.journal.set_value(""))
        self.journal.layout().addWidget(off)
        self._row(sec, "업무 일지 폴더", self.journal,
                  "YYYY/MM/YYYY-MM-DD.md 형식의 '## 업무' 구역을 읽습니다. 형식이 다르면 비워 두고 노트 폴더로만 넣으세요.",
                  "journal_dir")

        sec = self._section(lay, "열린 일 큐", "검색어가 비었을 때 보이는 최근 일 목록")
        self._row(sec, "열린 일 기간", self._spin("queue_days", "일"), "이 기간 안에 흔적이 있는 일만 올라옵니다.", "queue_days")
        self._row(sec, "크게 보여 줄 개수", self._spin("queue_focus", "개"),
                  "위쪽에 크게 보여 줍니다. 넘는 일은 '나머지 N개' 줄에 접혀 있습니다.", "queue_focus")
        qrow, self.queue_checks = self._checks(S.QUEUE_LABEL)
        self._bind("queue_sources", self._set_queue_sources,
                   lambda: [s for s in S.QUEUE_CHOICES if self.queue_checks[s].isChecked()])
        self._row(sec, "큐에 올릴 출처", qrow,
                  "프로젝트 문서, 메모리, imported 폴더는 올리지 않습니다. 업무 일지 항목은 일지 폴더가 있으면 늘 올라옵니다.",
                  "queue_sources", stacked=True)
        self.queue_ex = ListEdit(pick=self._pick_note_subdir)
        self.queue_ex.changed.connect(self._on_changed)
        self._bind("queue_note_exclude", self.queue_ex.set_values, self.queue_ex.values)
        self._row(sec, "큐에서 뺄 노트 폴더", self.queue_ex, "노트 폴더 안의 폴더만 고를 수 있습니다(노트 폴더 기준 상대 경로로 저장).",
                  "queue_note_exclude", stacked=True)

    def _set_queue_sources(self, v) -> None:
        for s, cb in self.queue_checks.items():
            cb.setChecked(s in (v or []))

    def _pick_note_subdir(self) -> str | None:
        roots = [Path(expand(p)) for p in self.notes.values()]
        if not roots:
            tell(self, TITLE, "먼저 노트 폴더를 추가하세요.")
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
                tell(self, TITLE, "노트 폴더 자체는 뺄 수 없습니다. 노트 폴더 목록에서 빼세요.")
                return None
            return rel.as_posix()
        tell(self, TITLE, "노트 폴더 밖의 폴더는 고를 수 없습니다.")
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
        lay = self._page("collect", "수집")
        sec = self._section(lay, "서비스")
        row, self.source_checks = self._checks(S.SERVICE_LABEL)
        self._bind("sources", self._set_sources, self._get_sources)
        self._row(sec, "쓰는 서비스", row, "끈 서비스는 수집도 알림도 하지 않습니다. 이미 보관된 md는 그대로 검색됩니다.",
                  "sources", stacked=True)

        sec = self._section(lay, "폴더")
        self.watch = self._path("watch_dir", "다운로드(감시) 폴더 선택", str(downloads_dir()))
        self.watch.changed.connect(self._update_capture_placeholder)
        self._row(sec, "다운로드(감시) 폴더", self.watch, "내보내기 zip이 들어오는 곳입니다. 비면 시스템 다운로드 폴더.", "watch_dir")
        self.capture = self._path("capture_dir", "자동 수집 파일 폴더 선택")
        self._row(sec, "자동 수집 파일 폴더", self.capture, "수집 스크립트가 대화 파일을 저장하는 곳입니다. 비면 <감시 폴더>\\claude-sync.",
                  "capture_dir")
        self.projects = self._path("code_projects_dir", "Claude Code 세션 폴더 선택",
                                   expand(str(S.default_of("code_projects_dir"))))
        self._row(sec, "Claude Code 세션 폴더", self.projects, "Claude Code를 켰을 때만 씁니다.", "code_projects_dir")
        self.codex_home = self._path("codex_dir", "Codex 폴더 선택", expand(str(S.default_of("codex_dir"))))
        self._row(sec, "Codex 폴더", self.codex_home, "Codex를 켰을 때만 씁니다.", "codex_dir")

        sec = self._section(lay, "주기와 알림")
        self._row(sec, "수집 주기", self._spin("code_collect_minutes", "분"),
                  "Claude Code, Codex 대화와 노트 폴더를 이 간격으로 모읍니다.", "code_collect_minutes")
        self.reminder = QSpinBox()
        self.reminder.setRange(1, 60)
        self.reminder.valueChanged.connect(self._on_changed)
        self.reminder_off = QCheckBox("끄기")
        self.reminder_off.toggled.connect(lambda on: (self.reminder_box.setEnabled(not on), self._on_changed()))
        self.reminder_box = NumEdit(self.reminder, "일")
        rrow = QHBoxLayout()
        rrow.setSpacing(12)
        rrow.addWidget(self.reminder_off)
        rrow.addWidget(self.reminder_box)
        self._bind("reminder_days", self._set_reminder, lambda: 0 if self.reminder_off.isChecked() else self.reminder.value())
        self._row(sec, "claude.ai 내보내기 알림", rrow, "마지막 zip 가져오기 뒤 이만큼 지나면 하루 한 번 알려 드립니다.",
                  "reminder_days")
        self._row(sec, "자동 수집 멈춤 알림", self._spin("capture_stale_hours", "시간"),
                  "수집 스크립트가 이만큼 멈추면 하루 한 번 알려 드립니다.", "capture_stale_hours")
        for site in SCRIPTS:
            self._guides.append((site, self._script_guide(lay, site)))

    def _set_sources(self, v) -> None:
        for s, cb in self.source_checks.items():
            cb.setChecked(bool((v or {}).get(s, True)))

    def _get_sources(self) -> dict:
        return {s: self.source_checks[s].isChecked() for s in S.SERVICES}

    def _set_reminder(self, v) -> None:
        v = int(v)
        self.reminder_off.setChecked(v == 0)
        self.reminder.setValue(v if v > 0 else 7)
        self.reminder_box.setEnabled(v > 0)

    def _update_capture_placeholder(self) -> None:
        if hasattr(self, "capture"):
            base = self.watch.value() or str(downloads_dir())
            self.capture.set_placeholder(str(Path(expand(base)) / "claude-sync"))

    def _script_guide(self, lay: QVBoxLayout, site: str) -> Section:
        """수집 스크립트 설치 단계, 스크립트 복사, 상태 한 줄 (3-I). 섹션 하나."""
        label, _svc, host = SITES[site]
        sec = self._section(lay, f"{label} 수집 스크립트", "Tampermonkey",
                            intro=f"{label} 탭이 열려 있는 동안 바뀐 대화만 받아 둡니다. 순서대로 한 번만 하면 됩니다.")
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
                tell(self, TITLE, f"스크립트를 읽지 못했습니다: {e}")
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
        for text, btn, fn in steps:
            b = None
            if btn:
                b = _button(btn)
                b.setAutoDefault(False)
                b.clicked.connect(fn)
            self._row(sec, text, b)
        self._row(sec, "상태", None, self.core.capture_site_status(site),
                  after="회사 크롬 정책으로 확장 설치가 막혀 있으면 zip 내보내기로 가져오세요.", extras=(copied,))
        return sec

    # ---- 요약 AI 탭 -----------------------------------------------------------
    def _build_ask(self) -> None:
        lay = self._page("ask", "요약 AI")
        sec = self._section(lay, "요약 AI", "큐에서 F2를 눌렀을 때")
        row = QHBoxLayout()
        row.setSpacing(16)
        self.provider_group = QButtonGroup(self)
        self.provider_radios = {}
        for p, label in (("claude", "Claude"), ("codex", "GPT (Codex)"), ("off", "끄기")):
            rb = QRadioButton(label)
            rb.toggled.connect(self._on_changed)
            self.provider_group.addButton(rb)
            self.provider_radios[p] = rb
            row.addWidget(rb)
        self._bind("ask_provider", lambda v: self.provider_radios.get(v, self.provider_radios["claude"]).setChecked(True),
                   lambda: next((p for p, rb in self.provider_radios.items() if rb.isChecked()), "claude"))
        self.off_note = self._help("F2를 누르면 '요약 AI가 꺼져 있습니다' 한 줄만 보여 줍니다. 큐의 F2 안내도 숨깁니다.")
        self._row(sec, "쓰는 AI", row, "F2를 눌렀을 때만 이 PC의 CLI를 실행합니다. CLI 설치와 로그인은 직접 합니다.",
                  "ask_provider", extras=(self.off_note,))
        # Claude
        self.claude_box = self._section(lay, "Claude", "Claude Code CLI")
        self.claude_model = self._model_combo("ask_model", cli_check.CLAUDE_MODELS, "claude")
        self._row(self.claude_box, "모델", self.claude_model, "목록에 없는 이름(전체 모델 이름)도 직접 넣을 수 있습니다.",
                  "ask_model")
        self._status_row(self.claude_box, "claude")
        self.claude_cmd = PathEdit("claude 실행 파일 선택", self._found("claude", ["claude"]), file=True, open_button=False)
        self.claude_cmd.setFixedWidth(PATH_W)
        self.claude_cmd.changed.connect(self._on_changed)
        self._bind("ask_command",
                   lambda v: self.claude_cmd.set_value("" if S.as_command(v) in ([], ["claude"]) else S.join_command(v)),
                   lambda: S.split_command(self.claude_cmd.value()) or ["claude"])
        self._row(self.claude_box, "CLI 경로", self.claude_cmd, "비면 PATH에서 claude를 찾습니다.", "ask_command")
        # GPT (Codex)
        self.codex_box = self._section(lay, "GPT", "Codex CLI")
        self.codex_model = self._model_combo("ask_model_codex", cli_check.codex_models(self.core.codex_dir), "codex")
        self.codex_desc = self._help("")
        self.codex_model.currentTextChanged.connect(self._update_codex_desc)
        self._row(self.codex_box, "모델", self.codex_model,
                  "목록은 이 PC의 Codex가 받아 둔 models_cache.json에서 읽습니다(앱이 네트워크로 받지 않음).",
                  "ask_model_codex", extras=(self.codex_desc,))
        self.effort = QComboBox()
        self.effort.addItems(list(cli_check.CODEX_EFFORTS))
        self.effort.setFixedWidth(160)
        self.effort.currentTextChanged.connect(self._on_changed)
        self._bind("ask_codex_effort", self._set_effort, lambda: self.effort.currentText())
        self._row(self.codex_box, "추론 정도", self.effort, "low가 가장 빠르고 적게 씁니다. 요약에는 low로 충분합니다.",
                  "ask_codex_effort")
        self._status_row(self.codex_box, "codex")
        self.codex_cmd = PathEdit("codex 실행 파일 선택", self._found("codex", []), file=True, open_button=False)
        self.codex_cmd.setFixedWidth(PATH_W)
        self.codex_cmd.changed.connect(self._on_changed)
        self._bind("ask_command_codex", lambda v: self.codex_cmd.set_value(S.join_command(v)),
                   lambda: S.split_command(self.codex_cmd.value()))
        self._row(self.codex_box, "CLI 경로", self.codex_cmd,
                  "비면 PATH의 codex, 그다음 Codex 데스크톱 앱 폴더(%LOCALAPPDATA%\\OpenAI\\Codex\\bin)에서 찾습니다.",
                  "ask_command_codex")

    def _found(self, provider: str, configured) -> str:
        cmd = cli_check.resolve(provider, configured)
        return f"자동: {os.path.normpath(cmd[0])}" if cmd else "자동으로 찾지 못함"

    def _model_combo(self, key: str, models: list, provider: str) -> QComboBox:
        cb = QComboBox()
        cb.setEditable(True)
        cb.setFixedWidth(PATH_W - 60)
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

    def _status_row(self, sec: Section, provider: str) -> QWidget:
        lb = self._help("확인 전")
        self._status_labels[provider].append(lb)
        b = _button("다시 확인")
        b.clicked.connect(lambda: self._start_check(provider, force=True))
        name = "CLI 상태" if not self.setup_mode else f"{cli_check.NAME[provider]} CLI 상태"
        box = self._row(sec, name, b, extras=(lb,))
        self._status_rows[provider].append(box)
        return box

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
            set_tone(lb, "")
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
        for lb in self._status_labels[provider]:
            lb.setText(st.line)
            set_tone(lb, "" if st.state == "ready" else "error")

    # ---- 고급 탭 --------------------------------------------------------------
    def _build_advanced(self) -> None:
        lay = self._page("advanced", "고급", "보통은 바꿀 필요가 없습니다.")
        sec = self._section(lay, "검색")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.open_cmd = QLineEdit()
        self.open_cmd.setObjectName("mono")
        self.open_cmd.setFixedWidth(250)
        self.open_cmd.textChanged.connect(self._on_changed)
        row.addWidget(self.open_cmd)
        d = _button("기본값", "link")
        d.clicked.connect(lambda: self.open_cmd.setText(S.join_command(S.default_of("open_command"))))
        row.addWidget(d)
        self._bind("open_command", lambda v: self.open_cmd.setText(S.join_command(v)),
                   lambda: S.split_command(self.open_cmd.text()))
        self._row(sec, "md 여는 명령", row,
                  "{path}는 md 경로, {line}은 줄 번호로 바뀝니다. 공백이 든 경로는 큰따옴표로 묶습니다. "
                  "실행에 실패하면 기본 연결 프로그램으로 엽니다.", "open_command")
        self._row(sec, "검색 결과 최대 개수", self._spin("max_results", "개"), "", "max_results")

        sec = self._section(lay, "순위 가중치", "BM25 관련도에 더하는 값",
                            link=("기본값으로", lambda: self._set_weights(S.default_of("weights"))))
        self.weight_spins = {}
        for wk, name, lo, hi in S.WEIGHTS:
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            half_life = wk == "recency_half_life_days"
            sp.setDecimals(0 if half_life else 2)
            sp.setSingleStep(1.0 if hi > 10 else 0.1)
            sp.valueChanged.connect(self._on_changed)
            self.weight_spins[wk] = sp
            self._row(sec, name, NumEdit(sp, "일" if half_life else ""),
                      "최근 가산이 절반이 되는 날 수" if half_life else "")
        self._bind("weights", self._set_weights, lambda: {wk: float(sp.value()) for wk, sp in self.weight_spins.items()})
        n = Note()
        self._notes["weights"] = n
        self._boxes["weights"] = sec
        sec.rows.addWidget(n)

        sec = self._section(lay, "가림 규칙")
        self.redact = LinesEdit("한 줄에 정규식 하나")
        self.redact.changed.connect(self._on_changed)
        self._bind("extra_redact_patterns", self.redact.set_values, self.redact.values)
        self._row(sec, "추가 가림 정규식", self.redact, key="extra_redact_patterns", stacked=True,
                  after="다음에 쓰는 md부터 가립니다. 이미 만든 md를 다시 만들려면 트레이 메뉴의 "
                        "고급 › 대화 md 전부 다시 만들기를 쓰세요.")

        sec = self._section(lay, "F2 요약", "요약에 넘기는 재료와 시간")
        self._row(sec, "마지막 메시지 수", self._spin("ask_tail_messages", "개"), "", "ask_tail_messages")
        self._row(sec, "글자 수 상한", self._spin("ask_max_chars", "자", NUM_W + 16), "", "ask_max_chars")
        self._row(sec, "제한 시간", self._spin("ask_timeout_seconds", "초"), "CLI가 이 시간 안에 답하지 않으면 멈춥니다.",
                  "ask_timeout_seconds")

        sec = self._section(lay, "파일과 주소")
        self.export_url = QLineEdit()
        self.export_url.setFixedWidth(320)
        self.export_url.textChanged.connect(self._on_changed)
        self._bind("export_page_url", self.export_url.setText, lambda: self.export_url.text().strip())
        self._row(sec, "내보내기 페이지 주소", self.export_url, "트레이의 'claude.ai 내보내기 받으러 가기'가 여는 주소",
                  "export_page_url")
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, fn in (("config.json 열기", self._open_config),
                         ("데이터 폴더 열기 (APPDATA)", lambda: self._open_dir(self.core.store.root)),
                         ("데이터 폴더 열기 (LOCALAPPDATA)", lambda: self._open_dir(self.core.store.local))):
            b = _button(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self._row(sec, "설정 파일과 데이터 폴더", row, "config.json을 직접 고쳤다면 이 창을 닫고 다시 여세요.", stacked=True)

    def _set_weights(self, v) -> None:
        for wk, sp in self.weight_spins.items():
            sp.setValue(float((v or {}).get(wk, S.default_of("weights")[wk])))

    def _open_config(self) -> None:
        p = self.core.store.config_path
        if p.exists():
            os.startfile(str(p))
        else:
            tell(self, TITLE, "config.json이 아직 없습니다. 저장하면 만들어집니다.")

    def _open_dir(self, p: Path) -> None:
        if Path(p).is_dir():
            os.startfile(str(p))
        else:
            tell(self, TITLE, f"폴더가 없습니다: {p}")

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
        self._on_tab(self._tab)
        self._preview_theme()

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
        prov = self._io["ask_provider"][1]()
        self._nat[self._boxes["reminder_days"]] = src["claude_ai"]
        for site, g in self._guides:
            self._nat[g] = src[SITES[site][1]]
        self._nat[self.claude_box] = prov == "claude"
        self._nat[self.codex_box] = prov == "codex"
        self.off_note.setVisible(prov == "off")
        self._refresh_empty_descs()
        self._refresh_filter()
        if prov in ("claude", "codex") and self._tab == "ask":
            self._start_check(prov)
        n = len(self.changed_keys())
        self.setWindowTitle(TITLE + (" *" if n else ""))
        self.changed_dot.setVisible(n > 0)
        self.changed_text.setVisible(n > 0)
        self.changed_text.setText(f"바뀐 설정 {n}개")
        self.btn_save.setEnabled(n > 0 or bool(self.forced) or bool(self.core.store.config_broken))

    # ---- 설정 찾기 -------------------------------------------------------------
    def _refresh_empty_descs(self) -> None:
        """칸이 비어 있을 때만 보일 설명(empty_desc)이 있는 줄은 비었는지에 따라 설명 줄 글을 바꾼다."""
        for r in self._rows:
            if r.empty_desc and r.desc_lb is not None and r.key in self._io:
                empty = not self._io[r.key][1]()
                r.desc_lb.setText(r.empty_desc if empty else r.desc)

    def _refresh_filter(self) -> None:
        """찾기 칸 글자에 맞는 줄만 남긴다. 줄이 없는 섹션은 숨기고, 사이드바 탭에 맞은 수를 붙인다.
        설정값 때문에 숨겨진 줄(_nat)은 찾기와 상관없이 계속 숨긴다."""
        if self.search is None or self.setup_mode:
            return
        terms = self.search.text().lower().split()
        mark = self.t.mark_bg.name()
        counts = {k: 0 for k in S.TABS}
        by_sec: dict[Section, list[RowRef]] = {}
        for r in self._rows:
            nat = self._nat.get(r.box, True) and self._nat.get(r.sec, True)
            r.counted = nat and all(t in r.haystack for t in terms)
            r.box.setVisible(r.counted)
            by_sec.setdefault(r.sec, []).append(r)
            if terms and r.counted:
                counts[r.tab] += 1
            marks = terms if r.counted else []
            for lb in (r.name_lb, r.desc_lb):
                if isinstance(lb, ElideLabel):
                    lb.set_marks(marks, mark)
        first_in_tab: set[str] = set()
        for sec in self._secs:
            rows = by_sec.get(sec, [])
            vis = self._nat.get(sec, True) and (not terms or any(r.counted for r in rows))
            sec.setVisible(vis)
            if vis:
                sec.set_first(sec.tab not in first_in_tab)       # 보이는 첫 섹션만 위 간격 없음
                first_in_tab.add(sec.tab)
            first = True
            for r in rows:
                if r.counted:
                    r.line.setVisible(not first)         # 카드의 첫 줄 위에는 구분선이 없다
                    first = False
        total = sum(counts.values())
        for i, key in enumerate(S.TABS):
            self.nav_buttons[i].set_count(counts[key] if terms else None)
        self.search.set_count(total)
        self.no_match.setVisible(bool(terms) and total == 0)
        self.no_match.setText(f"'{self.search.text()}'와 맞는 설정이 없습니다")
        if terms and total and counts[self._tab] == 0:
            self.select_tab(next(k for k in S.TABS if counts[k]))      # 지금 탭에 없으면 맞은 첫 탭으로

    def current_tab(self) -> str:
        return self._tab

    def select_tab(self, tab: str | None) -> None:
        if self.setup_mode or tab not in S.TABS:
            return
        self._tab = tab
        i = S.TABS.index(tab)
        self.stack.setCurrentIndex(i)
        self.nav_buttons[i].setChecked(True)
        self._on_tab(tab)

    def _on_tab(self, tab: str) -> None:
        if tab == "ask":
            prov = self._io["ask_provider"][1]()
            if prov in ("claude", "codex"):
                self._start_check(prov)

    # ---- 저장 ----------------------------------------------------------------
    def _show_errors(self, errs: dict[str, str]) -> None:
        if errs and self.search is not None and self.search.text():
            self.search.edit.clear()               # 찾는 중에 가려진 줄에 오류가 있을 수 있다
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
            self.select_tab(tab)
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
            ans = ask(self, TITLE, f"보관 폴더가 없습니다: {miss}\n폴더를 만들까요?", [("no", "취소"), ("yes", "만들기")])
            if ans != "yes":
                self._show_errors({"archive_dir": f"폴더가 없습니다: {miss}"})
                return False
            try:
                Path(miss).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                self._show_errors({"archive_dir": f"폴더를 만들지 못했습니다: {e}"})
                return False
        ws = list(S.warnings(new).values())
        ws = [w for w in ws if "쓰는 키" not in w]        # 단축키 경고는 칸 아래에 이미 보임
        # CLI를 못 찾은 것은 묻지 않는다: 한쪽 CLI만 쓰는 PC가 보통이고, CLI 상태 줄과 F2 실패 사유로 이미 보인다
        if ws:
            ans = ask(self, TITLE, "\n".join(ws) + "\n\n이대로 저장할까요?", [("back", "돌아가기"), ("save", "저장")])
            if ans != "save":
                return False
        if self.core.store.config_signature() != self._sig:
            ans = ask(self, TITLE, CHANGED_OUTSIDE, [("cancel", "취소"), ("reload", "다시 읽기"), ("over", "덮어쓰기")])
            if ans == "reload":
                before = self.core.config
                changed = self.core.reload_config()
                self.hooks.applied(changed, before)
                self._sig = self.core.store.config_signature()
                self.broken.setVisible(bool(self.core.store.config_broken))
                self.populate(self.core.config)
                return False
            if ans != "over":
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
            tell(self, TITLE, f"config.json을 저장하지 못했습니다: {e}")
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
            ans = ask(self, TITLE, "바꾼 내용을 저장하지 않고 닫을까요?", [("no", "계속 고치기"), ("yes", "닫기")])
            if ans != "yes":
                return
        self._done = True
        super().reject()

    # ---- 시작 안내 (3-K) ----------------------------------------------------------
    def _build_setup(self, root: QVBoxLayout) -> None:
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        guess = S.guess_sources()
        # 1. 쓰는 서비스
        lay = self._page(title="1. 쓰는 서비스",
                         desc="쓰는 것만 고르세요. 끈 서비스는 수집도 알림도 하지 않습니다. 나중에 설정에서 바꿀 수 있습니다.")
        sec = self._section(lay, "쓰는 서비스")
        col = QVBoxLayout()
        col.setSpacing(10)
        self.setup_sources = {}
        for s in S.SERVICES:
            cb = QCheckBox(S.SERVICE_LABEL[s])
            cb.setChecked(guess[s])
            self.setup_sources[s] = cb
            col.addWidget(cb)
        self._row(sec, "", col, stacked=True,
                  after="Claude Code, Codex는 이 PC에 쓴 흔적이 있으면 미리 체크해 두었습니다. "
                        "claude.ai, ChatGPT는 브라우저에서 쓰므로 직접 고르세요.")
        # 2. 보관 폴더
        lay = self._page(title="2. 대화 보관 폴더", desc="모은 대화를 md 파일로 쌓을 곳입니다.")
        sec = self._section(lay, "보관 폴더")
        self.setup_archive = ""
        self.setup_archive_label = _label(str(self.core.default_archive), "name")
        self.setup_archive_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row = QHBoxLayout()
        row.setSpacing(8)
        keep = _button("그대로 쓰기")
        keep.clicked.connect(lambda: self._set_setup_archive(""))
        change = _button("바꾸기...")
        change.clicked.connect(self._choose_setup_archive)
        row.addWidget(keep)
        row.addWidget(change)
        row.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(10)
        col.addWidget(self.setup_archive_label)
        col.addLayout(row)
        self._row(sec, "", col, stacked=True, warn=CLOUD_WARNING)
        # 3. 요약 AI
        lay = self._page(title="3. 요약 AI (F2)",
                         desc="큐에서 F2를 누르면 '어디까지 했지?'를 요약합니다. 이 PC에 설치된 CLI를 씁니다.")
        sec = self._section(lay, "쓰는 AI")
        self.setup_provider = {}
        self.setup_provider_touched = False
        grp = QButtonGroup(self)
        col = QVBoxLayout()
        col.setSpacing(10)
        for p, label in (("claude", "Claude (Claude Code CLI)"), ("codex", "GPT (Codex CLI)"), ("off", "끄기")):
            rb = QRadioButton(label)
            rb.clicked.connect(self._on_setup_provider)
            grp.addButton(rb)
            self.setup_provider[p] = rb
            col.addWidget(rb)
        self.setup_model = self._help("")
        self._row(sec, "", col, stacked=True, extras=(self.setup_model,))
        for p in ("claude", "codex"):
            self._status_row(sec, p)
        self._row(sec, "", None, "설치와 로그인은 직접 합니다(터미널에서 claude 또는 codex login). 모델을 바꾸려면 설정 > 요약 AI.")
        # 4. 노트 폴더와 수집 스크립트
        lay = self._page(title="4. 노트 폴더와 수집 스크립트")
        sec = self._section(lay, "노트 폴더", "선택")
        self.setup_notes = ListEdit("노트 폴더 선택 (md를 그대로 읽어 검색에 넣을 곳)")
        self._row(sec, "", self.setup_notes, "내 md 폴더(Obsidian 볼트 등)를 넣으면 같이 검색됩니다. 파일은 읽기만 합니다.",
                  stacked=True)
        self.setup_guides = [(site, self._script_guide(lay, site)) for site in SCRIPTS]
        for page in self._sections:
            page.addStretch(1)
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
        for prov, rows in self._status_rows.items():
            for box in rows:
                box.setVisible(prov == p)
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
            tell(self, SETUP_TITLE, "\n".join(errs.values()))
            return
        self._save_setup(cfg, True)

    def _skip(self) -> None:
        self._save_setup(S.skip_config(), False)

    def _save_setup(self, cfg: dict, finished: bool) -> None:
        old = self.core.config
        try:
            changed = self.core.update_config(cfg)
        except OSError as e:
            tell(self, SETUP_TITLE, f"config.json을 저장하지 못했습니다: {e}\n다음 실행 때 다시 묻습니다.")
            changed = set()
        self._done = True
        self.hooks.setup_finished(finished, changed, old)
        self.accept()
