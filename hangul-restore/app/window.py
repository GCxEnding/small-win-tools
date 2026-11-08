"""복원 팝업 UI: 입력란 / 후보 목록 / 상세."""
from __future__ import annotations

import ctypes

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QKeySequence, QPainter, QTextCursor
from PySide6.QtWidgets import (QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from restore import Analysis, Candidate

from . import winshell

TEXT_FONTS = ["Malgun Gothic", "Segoe UI"]
MONO_FONTS = ["D2Coding", "Consolas", "Malgun Gothic"]
ROLE_CAND = Qt.UserRole + 1
_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
_MOUSE_BUTTONS = (0x01, 0x02, 0x04)    # VK_LBUTTON, VK_RBUTTON, VK_MBUTTON
MSG_NO_CLIPBOARD = "클립보드에 텍스트가 없습니다. 아래 입력란에 붙여 넣어도 됩니다."


def _font(families, px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(families)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


class Theme:
    def __init__(self):
        d = _dark()
        self.bg = QColor("#202124" if d else "#ffffff")
        self.border = QColor("#3c4043" if d else "#d0d4da")
        self.text = QColor("#e8eaed" if d else "#1f2328")
        self.sub = QColor("#9aa0a6" if d else "#6a737d")
        self.sel = QColor("#2f4a6d" if d else "#dbe9fb")
        self.input_bg = QColor("#2a2b2e" if d else "#f4f6f8")
        self.warn = QColor("#f0a35e" if d else "#b35900")
        self.bad = QColor("#f28b82" if d else "#c5221f")
        self.ok = QColor("#81c995" if d else "#1e7e34")


def one_line(s: str) -> str:
    return s.replace("\r\n", "⏎").replace("\n", "⏎").replace("\r", "⏎").replace("\t", " ")


class InputEdit(QPlainTextEdit):
    """여러 줄 입력란. Esc 닫기, Ctrl+Enter 선택, Ctrl+↑/↓ 후보 이동."""
    navigate = Signal(int)
    accepted = Signal()
    cancelled = Signal()

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        if k == Qt.Key_Escape:
            self.cancelled.emit()
        elif k in (Qt.Key_Return, Qt.Key_Enter) and mods & Qt.ControlModifier:
            self.accepted.emit()
        elif k in (Qt.Key_Up, Qt.Key_Down) and mods & Qt.ControlModifier:
            self.navigate.emit(1 if k == Qt.Key_Down else -1)
        else:
            super().keyPressEvent(e)


class CandidateDelegate(QStyledItemDelegate):
    ROW_H = 66

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.t = theme
        self.main_font = _font(MONO_FONTS, 15)
        self.sub_font = _font(TEXT_FONTS, 12)
        self.label_font = _font(TEXT_FONTS, 11, bold=True)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    def _label_color(self, label: str) -> QColor:
        if label == "복원 불가에 가까움":
            return self.t.bad
        if label == "원문":
            return self.t.sub
        return self.t.warn

    def paint(self, p: QPainter, option, index):
        c: Candidate = index.data(ROLE_CAND)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        if option.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen)
            p.setBrush(self.t.sel)
            p.drawRoundedRect(rect.adjusted(4, 1, -4, -1), 6, 6)
        x, right = rect.left() + 14, rect.right() - 14
        top = rect.top() + 6

        # 1줄: 결과 + 라벨
        label_w = 0
        lfm = QFontMetrics(self.label_font)
        labels = [lb for lb in c.labels if not lb.endswith("글자 손실")]
        if c.lost_chars:
            labels.insert(1 if labels else 0, f"{c.lost_chars}글자 손실")
        label_text = " · ".join(labels)
        if label_text:
            label_w = lfm.horizontalAdvance(label_text) + 8
        p.setFont(self.main_font)
        p.setPen(self.t.text)
        fm = QFontMetrics(self.main_font)
        w = right - x - label_w
        p.drawText(QRect(x, top, w, 22), Qt.AlignVCenter, fm.elidedText(one_line(c.result), Qt.ElideRight, w))
        if label_text:
            p.setFont(self.label_font)
            color = self._label_color(labels[-1]) if labels else self.t.sub
            p.setPen(color)
            p.drawText(QRect(right - label_w + 8, top, label_w - 8, 22), Qt.AlignVCenter | Qt.AlignRight, label_text)

        # 2줄: 경로, 3줄: 힌트
        p.setFont(self.sub_font)
        sfm = QFontMetrics(self.sub_font)
        p.setPen(self.t.sub)
        path = c.path_text if not c.is_original else "원문 (변환 없음)"
        p.drawText(QRect(x, top + 22, right - x, 18), Qt.AlignVCenter, sfm.elidedText(path, Qt.ElideRight, right - x))
        if c.hint:
            p.drawText(QRect(x, top + 39, right - x, 18), Qt.AlignVCenter,
                       sfm.elidedText("💡 " + c.hint, Qt.ElideRight, right - x))
        p.restore()


class RestoreWindow(QWidget):
    chosen = Signal(str)
    textEdited = Signal(str)

    WIDTH, HEIGHT = 760, 620

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("hangul-restore")
        self.resize(self.WIDTH, self.HEIGHT)
        t = self.theme = Theme()
        self.source_text = ""        # 클립보드 원문 (줄바꿈 그대로)
        self.analysis: Analysis | None = None

        self.panel = QWidget(self)
        self.panel.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.panel)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        self.title = QLabel("깨진 한글 복원")
        self.title.setFont(_font(TEXT_FONTS, 13, bold=True))
        self.title.setObjectName("title")
        lay.addWidget(self.title)

        self.edit = InputEdit()
        self.edit.setFont(_font(MONO_FONTS, 14))
        self.edit.setPlaceholderText("깨진 문자열을 여기에 붙여 넣으세요")
        self.edit.setFixedHeight(84)
        self.edit.setTabChangesFocus(True)
        lay.addWidget(self.edit)

        self.status = QLabel()
        self.status.setFont(_font(TEXT_FONTS, 12))
        self.status.setWordWrap(True)
        self.status.setObjectName("status")
        lay.addWidget(self.status)

        self.list = QListWidget()
        self.list.setItemDelegate(CandidateDelegate(t, self.list))
        self.list.setUniformItemSizes(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        lay.addWidget(self.list, 3)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(_font(MONO_FONTS, 13))
        self.detail.setObjectName("detail")
        lay.addWidget(self.detail, 2)

        self.help = QLabel("↑↓ 이동 · Enter 복사하고 닫기 · Esc·창 밖 클릭 닫기 · 글자는 입력란으로 · Ctrl+V(Win+V) 바꿔서 해독 (입력란에서는 Ctrl+Enter, Ctrl+↑↓)")
        self.help.setFont(_font(TEXT_FONTS, 11))
        self.help.setObjectName("help")
        lay.addWidget(self.help)

        self.setStyleSheet(f"""
            #panel {{ background: {t.bg.name()}; border: 1px solid {t.border.name()}; border-radius: 10px; }}
            QPlainTextEdit {{ background: {t.input_bg.name()}; color: {t.text.name()}; border: none;
                              border-radius: 6px; padding: 4px 6px; }}
            QListWidget {{ background: transparent; border: none; outline: none; }}
            #title {{ color: {t.text.name()}; }}
            #status, #help {{ color: {t.sub.name()}; }}
            QScrollBar:vertical {{ width: 8px; background: transparent; }}
            QScrollBar::handle:vertical {{ background: {t.border.name()}; border-radius: 4px; min-height: 24px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._emit_edited)
        self.edit.textChanged.connect(self._debounce.start)
        self.edit.navigate.connect(self._move)
        self.edit.accepted.connect(self._accept)
        self.edit.cancelled.connect(self.hide)
        self.list.currentRowChanged.connect(self._show_detail)
        self.list.installEventFilter(self)
        self._was_down = False
        self._was_esc = False
        self._outside_timer = QTimer(self)
        self._outside_timer.setInterval(40)
        self._outside_timer.timeout.connect(self._check_outside_click)
        # Enter는 목록이 처리하지 않고 창으로 올라오므로 keyPressEvent에서 받는다 (activated와 겹치면 두 번 실행됨)
        self.list.itemDoubleClicked.connect(lambda _it: self._accept())

    # ---- 입력 -----------------------------------------------------------
    def current_text(self) -> str:
        """사용자가 고치지 않았으면 클립보드 원문(줄바꿈 보존), 고쳤으면 입력란 내용."""
        return self.source_text if self.source_text is not None else self.edit.toPlainText()

    def _emit_edited(self) -> None:
        self.source_text = None     # 이제 입력란 내용이 기준
        self.textEdited.emit(self.edit.toPlainText())

    def paste_replace(self) -> None:
        md = QGuiApplication.clipboard().mimeData()
        text = md.text() if md is not None and md.hasText() else ""
        if not text:
            return
        self.set_input(text)
        self.textEdited.emit(text)

    def set_input(self, text: str) -> None:
        self.source_text = text
        self.edit.blockSignals(True)
        self.edit.setPlainText(text)
        self.edit.blockSignals(False)

    # ---- 결과 -----------------------------------------------------------
    def set_analysis(self, a: Analysis, extra_status: str | None = None) -> None:
        self.analysis = a
        self.list.clear()
        for c in a.candidates:
            it = QListWidgetItem()
            it.setData(ROLE_CAND, c)
            it.setToolTip(c.result[:2000])
            self.list.addItem(it)
        msgs = [m for m in (extra_status, a.status, a.notice) if m]
        top = a.candidates[0] if a.candidates else None
        if top is not None and not top.is_original and not msgs:
            msgs.append(f"후보 {len(a.candidates)}개 · 1위: {top.path_text}")
        self.status.setText(" · ".join(msgs))
        if a.candidates:
            self.list.setCurrentRow(0)
        else:
            self.detail.clear()

    def _show_detail(self, row: int) -> None:
        if not self.analysis or row < 0 or row >= len(self.analysis.candidates):
            self.detail.clear()
            return
        c = self.analysis.candidates[row]
        lines = [c.result, "", "────────"]
        lines.append("경로: " + ("원문 (변환 없음)" if c.is_original else c.path_text))
        if c.labels:
            lines.append("라벨: " + ", ".join(c.labels))
        if c.lost_chars:
            lines.append(f"손실: {c.lost_chars}글자 (□ 자리)")
        if c.hint:
            lines.append("원인 힌트: " + c.hint)
        if c.details:
            lines.append("구간별:")
            lines += [f"  - {d}" for d in c.details]
        lines.append(f"점수: {c.score:.2f}")
        self.detail.setPlainText("\n".join(lines))

    def _move(self, step: int) -> None:
        n = self.list.count()
        if n:
            self.list.setCurrentRow(max(0, min(n - 1, self.list.currentRow() + step)))

    def _accept(self) -> None:
        it = self.list.currentItem()
        if it is not None:
            self.chosen.emit(it.data(ROLE_CAND).result)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._accept()
        else:
            super().keyPressEvent(e)

    # ---- 표시 -----------------------------------------------------------
    def popup(self) -> None:
        cur = QCursor.pos()
        screen = QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.move(QPoint(g.left() + (g.width() - self.width()) // 2, g.top() + (g.height() - self.height()) // 2))
        self.show()
        self.raise_()
        self.activateWindow()
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except OSError:
            pass
        self.list.setFocus(Qt.ActiveWindowFocusReason)

    # ---- 닫기: 창 밖을 마우스로 눌렀을 때만 -------------------------------
    # 포커스를 잃을 때(WindowDeactivate) 닫으면 한/영 전환·IME 창처럼 키 하나에도 닫혀 버린다.
    # 그래서 창이 떠 있는 동안만 마우스 버튼 상태를 짧게 확인한다 (입력 훅은 쓰지 않음).
    def _mouse_down(self) -> bool:
        try:
            return any(_user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MOUSE_BUTTONS)
        except (AttributeError, OSError):
            return False

    def _check_outside_click(self) -> None:
        down = self._mouse_down()
        if (down and not self._was_down and not self.frameGeometry().contains(QCursor.pos())
                and not winshell.is_shell_overlay_click()):     # Win+V 클립보드 기록, 시작 메뉴 등은 예외
            self.hide()
        self._was_down = down
        # 창이 활성이면 Esc는 keyPressEvent가 받는다. 비활성(Win+V를 쓴 뒤 등)일 때만 여기서 닫는다.
        esc = winshell.key_down(winshell.VK_ESCAPE)
        if esc and not self._was_esc and self.isVisible() and not self.isActiveWindow()                 and winshell.esc_closes_popup():
            self.hide()
        self._was_esc = esc

    def showEvent(self, e):
        self._was_down = self._mouse_down()     # 창을 띄운 클릭(트레이 등)은 무시
        self._was_esc = winshell.key_down(winshell.VK_ESCAPE)
        self._outside_timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._outside_timer.stop()
        super().hideEvent(e)

    # ---- 목록에 포커스가 있을 때 친 글자는 입력란으로 ---------------------
    def eventFilter(self, obj, e):
        if obj is self.list and e.type() == QEvent.KeyPress:
            mods = e.modifiers() & ~Qt.KeypadModifier
            text = e.text()
            # Ctrl+V (Win+V 클립보드 기록에서 고르면 Windows가 Ctrl+V를 보낸다): 그 내용으로 바꿔 다시 해독
            if e.matches(QKeySequence.Paste):
                self.paste_replace()
                return True
            if e.key() == Qt.Key_Backspace or (text and text.isprintable() and not mods & (Qt.ControlModifier | Qt.AltModifier)):
                self.edit.setFocus(Qt.OtherFocusReason)
                self.edit.moveCursor(QTextCursor.End)
                if e.key() == Qt.Key_Backspace:
                    self.edit.textCursor().deletePreviousChar()
                else:
                    self.edit.insertPlainText(text)
                return True
        return super().eventFilter(obj, e)
