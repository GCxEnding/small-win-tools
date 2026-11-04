"""검색 창 UI (목록형)."""
from __future__ import annotations

import ctypes

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import (QLabel, QLineEdit, QListWidget, QListWidgetItem, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from .search import Result

EMOJI_FONT = "Segoe UI Emoji"
TEXT_FONTS = ["Segoe UI", "Malgun Gothic"]
ROLE_RESULT = Qt.UserRole + 1


def popup_position(g: QRect, cur: QPoint, w: int, h: int, position: str = "cursor") -> QPoint:
    """화면 영역 g 안에서 창의 왼쪽 위 좌표를 정한다 (화면 없이 테스트 가능)."""
    if position == "center":
        return QPoint(g.left() + (g.width() - w) // 2, g.top() + (g.height() - h) // 2)
    x, y = cur.x() + 2, cur.y() + 2
    if x + w > g.right() + 1:          # 오른쪽이 모자라면 커서 왼쪽으로
        x = cur.x() - w - 2
    if y + h > g.bottom() + 1:         # 아래가 모자라면 커서 위로
        y = cur.y() - h - 2
    x = max(g.left(), min(x, g.right() + 1 - w))
    y = max(g.top(), min(y, g.bottom() + 1 - h))
    return QPoint(x, y)


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


class QueryEdit(QLineEdit):
    """한글 조합 중인 글자(preedit)까지 포함한 검색어를 알려 주는 입력란."""
    queryChanged = Signal(str)
    navigate = Signal(int)
    accepted = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.textChanged.connect(self.queryChanged.emit)

    def inputMethodEvent(self, e):
        super().inputMethodEvent(e)
        pre = e.preeditString()
        text, pos = self.text(), self.cursorPosition()
        self.queryChanged.emit(text[:pos] + pre + text[pos:])

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Down, Qt.Key_Up):
            self.navigate.emit(1 if k == Qt.Key_Down else -1)
        elif k in (Qt.Key_PageDown, Qt.Key_PageUp):
            self.navigate.emit(8 if k == Qt.Key_PageDown else -8)
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.accepted.emit()
        elif k == Qt.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(e)


class ResultDelegate(QStyledItemDelegate):
    ROW_H = 40

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.t = theme
        self.emoji_font = QFont(EMOJI_FONT)
        self.emoji_font.setPixelSize(22)
        self.name_font = QFont()
        self.name_font.setFamilies(TEXT_FONTS)
        self.name_font.setPixelSize(15)
        self.tag_font = QFont(self.name_font)
        self.tag_font.setPixelSize(12)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, p: QPainter, option, index):
        r: Result = index.data(ROLE_RESULT)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        if option.state & QStyle.State_Selected:
            p.setPen(Qt.NoPen)
            p.setBrush(self.t.sel)
            p.drawRoundedRect(rect.adjusted(4, 1, -4, -1), 6, 6)
        x = rect.left() + 12
        p.setFont(self.emoji_font)
        p.setPen(self.t.text)
        p.drawText(QRect(x, rect.top(), 34, rect.height()), Qt.AlignVCenter | Qt.AlignHCenter, r.emoji)
        x += 44
        name = r.name_ko or r.name_en or ""
        p.setFont(self.name_font)
        fm = QFontMetrics(self.name_font)
        name_w = min(fm.horizontalAdvance(name), int((rect.right() - x) * 0.5))
        p.drawText(QRect(x, rect.top(), name_w, rect.height()), Qt.AlignVCenter,
                   fm.elidedText(name, Qt.ElideRight, name_w))
        x += name_w + 12
        if r.tags:
            p.setFont(self.tag_font)
            p.setPen(self.t.sub)
            tw = rect.right() - 12 - x
            tfm = QFontMetrics(self.tag_font)
            p.drawText(QRect(x, rect.top(), tw, rect.height()), Qt.AlignVCenter,
                       tfm.elidedText(", ".join(r.tags), Qt.ElideRight, tw))
        p.restore()


class SearchWindow(QWidget):
    chosen = Signal(str)
    queryChanged = Signal(str)

    WIDTH, HEIGHT = 560, 440

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("emoji-searcher")
        self.resize(self.WIDTH, self.HEIGHT)
        t = self.theme = Theme()

        self.panel = QWidget(self)
        self.panel.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.panel)

        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self.edit = QueryEdit()
        self.edit.setPlaceholderText("이모지 검색 (한/영, 초성 ㅂㅍ, 자판 qnf)")
        f = QFont()
        f.setFamilies(TEXT_FONTS)
        f.setPixelSize(17)
        self.edit.setFont(f)
        self.edit.setMinimumHeight(40)
        lay.addWidget(self.edit)

        self.list = QListWidget()
        self.list.setItemDelegate(ResultDelegate(t, self.list))
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setUniformItemSizes(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        lay.addWidget(self.list, 1)

        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setFont(f)
        lay.addWidget(self.empty, 1)
        self.empty.hide()

        self.setStyleSheet(f"""
            #panel {{ background: {t.bg.name()}; border: 1px solid {t.border.name()}; border-radius: 10px; }}
            QLineEdit {{ background: {t.input_bg.name()}; color: {t.text.name()}; border: none;
                         border-radius: 6px; padding: 4px 10px; }}
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QLabel {{ color: {t.sub.name()}; }}
            QScrollBar:vertical {{ width: 8px; background: transparent; }}
            QScrollBar::handle:vertical {{ background: {t.border.name()}; border-radius: 4px; min-height: 24px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)

        self.edit.queryChanged.connect(self.queryChanged.emit)
        self.edit.navigate.connect(self._move)
        self.edit.accepted.connect(self._accept)
        self.edit.cancelled.connect(self.hide)
        self.list.itemClicked.connect(lambda it: self.chosen.emit(it.data(ROLE_RESULT).emoji))

    # ---- results ------------------------------------------------------
    def set_results(self, results: list[Result], query: str) -> None:
        self.list.clear()
        for r in results:
            it = QListWidgetItem()
            it.setData(ROLE_RESULT, r)
            it.setToolTip(f"{r.emoji} {r.name_ko} / {r.name_en}\n{', '.join(r.tags)}")
            self.list.addItem(it)
        if results:
            self.list.setCurrentRow(0)
            self.empty.hide()
            self.list.show()
        else:
            self.empty.setText("결과 없음" if query.strip() else
                               "검색어를 입력하세요.\n여기서 고른 이모지는 다음부터 이 자리에 최근 순으로 보여요.")
            self.list.hide()
            self.empty.show()

    def _move(self, step: int) -> None:
        n = self.list.count()
        if not n:
            return
        row = max(0, min(n - 1, self.list.currentRow() + step))
        self.list.setCurrentRow(row)
        self.list.scrollToItem(self.list.currentItem())

    def _accept(self) -> None:
        it = self.list.currentItem()
        if it is not None:
            self.chosen.emit(it.data(ROLE_RESULT).emoji)

    # ---- show / hide --------------------------------------------------
    def popup_pos(self, position: str = "cursor", cursor: QPoint | None = None) -> QPoint:
        """'cursor': 우클릭 메뉴처럼 커서 오른쪽 아래에 띄우고, 화면 밖으로 나가면 반대쪽으로 뒤집는다.
        'center': 커서가 있는 모니터 중앙."""
        cur = cursor if cursor is not None else QCursor.pos()
        screen = QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()
        return popup_position(screen.availableGeometry(), cur, self.width(), self.height(), position)
    def popup(self, position: str = "cursor") -> None:
        self.move(self.popup_pos(position))
        self.edit.clear()
        self.queryChanged.emit("")
        self.show()
        self.raise_()
        self.activateWindow()
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except OSError:
            pass
        self.edit.setFocus(Qt.ActiveWindowFocusReason)

    def event(self, e):
        if e.type() == QEvent.WindowDeactivate and self.isVisible():
            self.hide()
        return super().event(e)
