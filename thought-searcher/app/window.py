"""검색 창 UI."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from .queue import QueueItem, QueueResult, relative_time
from .search import Hit

TEXT_FONTS = ["Segoe UI", "Malgun Gothic", "Segoe UI Emoji"]
ROLE_HIT = Qt.UserRole + 1
ROLE_IDX = Qt.UserRole + 2
ROLE_KIND = Qt.UserRole + 3
ROLE_TEXT = Qt.UserRole + 4
# 목록 항목 종류: 검색 결과, 큐(크게/한 줄), 접기 줄, 빈 큐 안내
K_HIT, K_FOCUS, K_ROW, K_TOGGLE_REST, K_TOGGLE_CLOSED, K_EMPTY = "hit", "focus", "row", "rest", "closed", "empty"
CLOSE_LABEL = {"done": "완료", "drop": "버림"}
HINT_SEARCH = "Enter 열기 · Ctrl+Enter 메시지 복사 · Shift+Enter 대화 복사 · ←/→ 다른 맞은 메시지 · Esc 닫기"
HINT_QUEUE = "열린 일 · Enter 열기 · F4 완료 · Shift+F4 버림 · Shift+Enter 대화 복사 · 오른쪽 클릭 메뉴 · Esc 닫기"
BADGE = {"claude-ai": "AI", "claude-code": "Code", "claude-ai-project": "P", "claude-ai-memory": "M", "chatgpt": "GPT", "note": "노트", "codex": "Codex",
         "journal": "일지"}
BADGE_COLOR = {"claude-ai": "#d97757", "claude-code": "#3b82f6", "claude-ai-project": "#10a37f",
               "claude-ai-memory": "#a855f7", "chatgpt": "#6b7280", "note": "#ca8a04", "codex": "#0d9488",
               "journal": "#7c3aed"}
DEBOUNCE_MS = 150
WIN_W, WIN_H = 820, 560


def center_position(g: QRect, w: int, h: int) -> QPoint:
    return QPoint(g.left() + (g.width() - w) // 2, g.top() + (g.height() - h) // 3)


def _dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


class Theme:
    def __init__(self):
        d = _dark()
        self.bg = QColor("#202124" if d else "#ffffff")
        self.border = QColor("#3c4043" if d else "#c9ced6")
        self.text = QColor("#e8eaed" if d else "#1f2328")
        self.sub = QColor("#9aa0a6" if d else "#6a737d")
        self.sel = QColor("#2f4a6d" if d else "#dbe9fb")
        self.input_bg = QColor("#2a2b2e" if d else "#f4f6f8")
        self.mark_bg = QColor("#6b5b16" if d else "#fff1a8")
        self.warn = QColor("#f28b82" if d else "#c5221f")


class QueryEdit(QLineEdit):
    """한글 조합 중인 글자(preedit)까지 포함한 검색어를 알려 주는 입력란."""
    queryChanged = Signal(str)
    navigate = Signal(int)
    switchMatch = Signal(int)
    accepted = Signal(str)        # "open" | "copy_msg" | "copy_conv"
    itemKey = Signal(str)         # 큐: "done"(F4) | "drop"(Shift+F4) | "summary"(F2)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pre = ""
        self.textChanged.connect(lambda _t: self.queryChanged.emit(self.full_text()))

    def full_text(self) -> str:
        text, pos = self.text(), self.cursorPosition()
        return text[:pos] + self._pre + text[pos:]

    def inputMethodEvent(self, e):
        super().inputMethodEvent(e)
        self._pre = e.preeditString()
        self.queryChanged.emit(self.full_text())

    def focusOutEvent(self, e):
        self._pre = ""
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        at_end = self.cursorPosition() == len(self.text()) and not self.hasSelectedText() and not self._pre
        if k in (Qt.Key_Down, Qt.Key_Up):
            self.navigate.emit(1 if k == Qt.Key_Down else -1)
        elif k in (Qt.Key_PageDown, Qt.Key_PageUp):
            self.navigate.emit(8 if k == Qt.Key_PageDown else -8)
        elif k in (Qt.Key_Left, Qt.Key_Right) and at_end and not (mods & (Qt.ShiftModifier | Qt.ControlModifier)):
            self.switchMatch.emit(1 if k == Qt.Key_Right else -1)
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            if mods & Qt.ControlModifier:
                self.accepted.emit("copy_msg")
            elif mods & Qt.ShiftModifier:
                self.accepted.emit("copy_conv")
            else:
                self.accepted.emit("open")
        elif k == Qt.Key_F4 and not (mods & (Qt.AltModifier | Qt.ControlModifier)):
            self.itemKey.emit("drop" if mods & Qt.ShiftModifier else "done")
        elif k == Qt.Key_F2:
            self.itemKey.emit("summary")
        elif k == Qt.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(e)


def _draw_runs(p: QPainter, x: int, y_base: int, max_x: int, text: str, spans, fm: QFontMetrics,
               color: QColor, mark: QColor, bold_font: QFont | None = None) -> int:
    """강조 구간을 칠하며 한 줄 그리기. 넘치면 '…'. 그린 뒤 x를 돌려준다."""
    segs = []
    pos = 0
    for s, e in spans:
        if s > pos:
            segs.append((text[pos:s], False))
        segs.append((text[s:e], True))
        pos = e
    if pos < len(text):
        segs.append((text[pos:], False))
    ell = fm.horizontalAdvance("…")
    for seg, hl in segs:
        if not seg:
            continue
        w = fm.horizontalAdvance(seg)
        clipped = False
        if x + w > max_x:
            seg = fm.elidedText(seg, Qt.ElideRight, max(0, max_x - x))
            w = fm.horizontalAdvance(seg)
            clipped = True
        if hl and seg:
            p.fillRect(QRect(x, y_base - fm.ascent(), w, fm.height()), mark)
        p.setPen(color)
        p.drawText(x, y_base, seg)
        x += w
        if clipped or x + ell > max_x:
            break
    return x


class HitDelegate(QStyledItemDelegate):
    def __init__(self, theme: Theme, font: QFont, parent=None):
        super().__init__(parent)
        self.t = theme
        self.font = font
        self.bold = QFont(font)
        self.bold.setBold(True)
        self.small = QFont(font)
        self.small.setPointSizeF(font.pointSizeF() * 0.9)

        self.title_big = QFont(font)
        self.title_big.setPointSizeF(font.pointSizeF() * 1.15)
        self.title_big.setBold(True)
        self.now = 0.0      # 큐 상대 시각 기준 (창이 채운다)

    def sizeHint(self, option, index):
        fm = QFontMetrics(self.font)
        kind = index.data(ROLE_KIND) or K_HIT
        if kind == K_HIT:
            return QSize(option.rect.width(), fm.height() * 2 + 14)
        if kind == K_FOCUS:
            it: QueueItem = index.data(ROLE_HIT)
            extra = sum(1 for s in (it.subtitle, it.summary) if s)
            fms = QFontMetrics(self.small)
            return QSize(option.rect.width(),
                         QFontMetrics(self.title_big).height() + fms.height() * (1 + extra) + 6 + 3 * extra + 16)
        if kind in (K_TOGGLE_REST, K_TOGGLE_CLOSED):
            return QSize(option.rect.width(), fm.height() + 16)
        return QSize(option.rect.width(), fm.height() + 10)

    def _badge(self, p: QPainter, x: int, top: int, line_h: int, source: str) -> int:
        fms = QFontMetrics(self.small)
        badge = BADGE.get(source, "MD")
        bw = fms.horizontalAdvance(badge) + 10
        rect = QRect(x, top + (line_h - fms.height()) // 2 - 1, bw, fms.height() + 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(BADGE_COLOR.get(source, "#888888")))
        p.drawRoundedRect(rect, 4, 4)
        p.setFont(self.small)
        p.setPen(QColor("#ffffff"))
        p.drawText(rect, Qt.AlignCenter, badge)
        return bw

    def _paint_queue(self, p: QPainter, option, index, kind: str) -> None:
        r = option.rect
        p.save()
        if option.state & QStyle.State_Selected:
            p.fillRect(r, self.t.sel)
        x0, max_x = r.left() + 10, r.right() - 10
        fm, fms = QFontMetrics(self.font), QFontMetrics(self.small)
        if kind in (K_TOGGLE_REST, K_TOGGLE_CLOSED, K_EMPTY):
            if kind != K_EMPTY:
                p.setPen(QPen(self.t.border))
                p.drawLine(r.left() + 6, r.top() + 2, r.right() - 6, r.top() + 2)
            p.setFont(self.font)
            p.setPen(self.t.sub)
            p.drawText(QRect(x0, r.top() + 2, max_x - x0, r.height() - 2), Qt.AlignVCenter | Qt.AlignLeft,
                       index.data(ROLE_TEXT) or "")
            p.restore()
            return
        it: QueueItem = index.data(ROLE_HIT)
        closed = bool(it.closed_kind)
        if closed:
            right = f"{CLOSE_LABEL.get(it.closed_kind, '')} · {relative_time(it.closed_at, self.now)}"
        else:
            right = relative_time(it.trace_ts, self.now)
        rw = fms.horizontalAdvance(right)
        if kind == K_FOCUS:
            fmt = QFontMetrics(self.title_big)
            top = r.top() + 8
            bw = self._badge(p, x0, top, fmt.height(), it.source)
            y1 = top + fmt.ascent()
            p.setFont(self.title_big)
            _draw_runs(p, x0 + bw + 8, y1, max_x - rw - 12, it.title or "(제목 없음)", [], fmt, self.t.text,
                       self.t.mark_bg)
            p.setFont(self.small)
            p.setPen(self.t.sub)
            p.drawText(max_x - rw, y1, right)
            y = top + fmt.height() + 4 + fms.ascent()
            parts = [s for s in (it.project, datetime.fromtimestamp(it.trace_ts).strftime("%m-%d %H:%M")) if s]
            p.drawText(x0 + bw + 8, y, fms.elidedText("  ·  ".join(parts), Qt.ElideRight, max_x - x0 - bw - 8))
            for s in (it.subtitle, it.summary):
                if s:
                    y += fms.height() + 3
                    p.setFont(self.font if s is it.subtitle else self.small)
                    p.setPen(self.t.text if s is it.subtitle else self.t.sub)
                    p.drawText(x0 + bw + 8, y, QFontMetrics(p.font()).elidedText(s, Qt.ElideRight,
                                                                                max_x - x0 - bw - 8))
        else:
            top = r.top() + 5
            bw = self._badge(p, x0 + 12, top, fm.height(), it.source)
            y1 = top + fm.ascent()
            p.setFont(self.font)
            title = it.title or "(제목 없음)"
            if it.project:
                title += f"   {it.project}"
            _draw_runs(p, x0 + 12 + bw + 8, y1, max_x - rw - 12, title, [], fm,
                       self.t.sub if closed else self.t.text, self.t.mark_bg)
            p.setFont(self.small)
            p.setPen(self.t.sub)
            p.drawText(max_x - rw, y1, right)
        p.restore()

    def paint(self, p: QPainter, option, index):
        kind = index.data(ROLE_KIND) or K_HIT
        if kind != K_HIT:
            self._paint_queue(p, option, index, kind)
            return
        hit: Hit = index.data(ROLE_HIT)
        if hit is None:
            return
        idx = index.data(ROLE_IDX) or 0
        p.save()
        r = option.rect
        if option.state & QStyle.State_Selected:
            p.fillRect(r, self.t.sel)
        fm = QFontMetrics(self.font)
        fmb = QFontMetrics(self.bold)
        fms = QFontMetrics(self.small)
        x0 = r.left() + 10
        max_x = r.right() - 10
        y1 = r.top() + 5 + fm.ascent()
        # 1줄: 출처 | 제목 | 프로젝트 | 날짜 | (원본 없음)
        badge = BADGE.get(hit.source, "MD")
        bw = fms.horizontalAdvance(badge) + 10
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(BADGE_COLOR.get(hit.source, "#888888")))
        p.drawRoundedRect(QRect(x0, r.top() + 5 + (fm.height() - fms.height()) // 2 - 1, bw, fms.height() + 2), 4, 4)
        p.setFont(self.small)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRect(x0, r.top() + 5 + (fm.height() - fms.height()) // 2 - 1, bw, fms.height() + 2),
                   Qt.AlignCenter, badge)
        right_parts = []
        if hit.project and hit.source != "claude-ai-project":
            right_parts.append(hit.project)
        if hit.updated:
            right_parts.append(hit.updated.astimezone().strftime("%Y-%m-%d"))
        right = "  ·  ".join(right_parts)
        missing = "  (원본 없음)" if hit.status == "missing" else ""
        rw = fms.horizontalAdvance(right + missing)
        p.setFont(self.bold)
        _draw_runs(p, x0 + bw + 8, y1, max_x - rw - 12, hit.title, hit.title_highlights, fmb, self.t.text,
                   self.t.mark_bg)
        p.setFont(self.small)
        p.setPen(self.t.sub)
        p.drawText(max_x - rw, y1, right)
        if missing:
            p.setPen(self.t.warn)
            p.drawText(max_x - fms.horizontalAdvance(missing), y1, missing)
        # 2줄: 미리보기 [i/n]
        y2 = y1 + fm.height() + 3
        if hit.matches:
            m = hit.matches[min(idx, len(hit.matches) - 1)]
            total = hit.match_total or len(hit.matches)
            tag = f"  [{idx + 1}/{total}]" if hit.match_total else ""
            tw = fms.horizontalAdvance(tag)
            p.setFont(self.font)
            _draw_runs(p, x0, y2, max_x - tw - 4, m.preview, m.highlights, fm, self.t.sub, self.t.mark_bg)
            if tag:
                p.setFont(self.small)
                p.setPen(self.t.sub)
                p.drawText(max_x - tw, y2, tag)
        p.restore()


class SearchWindow(QWidget):
    searchRequested = Signal(str)
    action = Signal(str, object, int)    # (종류, Hit, 맞은 메시지 순번)

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.setWindowTitle("생각 검색기")
        self.t = Theme()
        font = QFont()
        font.setFamilies(TEXT_FONTS)
        font.setPointSize(10)
        self.setFont(font)
        self.resize(WIN_W, WIN_H)
        self.setStyleSheet(f"""
            QWidget#root {{ background:{self.t.bg.name()}; border:1px solid {self.t.border.name()}; }}
            QLineEdit {{ background:{self.t.input_bg.name()}; color:{self.t.text.name()};
                        border:1px solid {self.t.border.name()}; border-radius:6px; padding:8px 10px;
                        font-size:13pt; }}
            QListWidget {{ background:{self.t.bg.name()}; border:none; outline:none; }}
            QLabel {{ color:{self.t.sub.name()}; padding:2px 4px; }}
        """)
        root = QWidget(self)
        root.setObjectName("root")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(root)
        inner = QVBoxLayout(root)
        inner.setContentsMargins(10, 10, 10, 8)
        inner.setSpacing(6)
        self.edit = QueryEdit()
        self.edit.setPlaceholderText("기억나는 단어 몇 개  (\"구문\"  -제외  src:ai|code|codex|gpt|note|memory|project  proj:  after:2026-10)")
        self.list = QListWidget()
        self.delegate = HitDelegate(self.t, font, self.list)
        self.list.setItemDelegate(self.delegate)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.itemDoubleClicked.connect(lambda _i: self._emit("open"))
        self.list.itemClicked.connect(self._on_clicked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.status = QLabel("")
        inner.addWidget(self.edit)
        inner.addWidget(self.list, 1)
        inner.addWidget(self.status)
        self.hint = QLabel(HINT_SEARCH)
        f = QFont(font)
        f.setPointSizeF(8.5)
        self.hint.setFont(f)
        inner.addWidget(self.hint)
        self.mode = "search"
        self._queue: QueueResult | None = None
        self._show_rest = False
        self._show_closed = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._pending = ""
        self._timer.timeout.connect(lambda: self.searchRequested.emit(self._pending))
        self.edit.queryChanged.connect(self._on_changed)
        self.edit.navigate.connect(self._navigate)
        self.edit.switchMatch.connect(self._switch)
        self.edit.accepted.connect(self._emit)
        self.edit.itemKey.connect(self._item_key)
        self.edit.cancelled.connect(self.hide)

    # ---- 표시 ---------------------------------------------------------
    def popup(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.move(center_position(g, self.width(), self.height()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()
        self.edit.selectAll()
        self._show_rest = self._show_closed = False
        self.refresh()

    def refresh(self) -> None:
        self._pending = self.edit.full_text()
        self.searchRequested.emit(self._pending)

    def changeEvent(self, e):
        if e.type() == QEvent.ActivationChange and not self.isActiveWindow() and self.isVisible():
            QTimer.singleShot(0, self._hide_if_inactive)
        super().changeEvent(e)

    def _hide_if_inactive(self):
        if not self.isActiveWindow():
            self.hide()

    def _on_changed(self, text: str) -> None:
        self._pending = text
        self._timer.start()

    def set_results(self, hits: list[Hit], status: str) -> None:
        self.mode = "search"
        self.hint.setText(HINT_SEARCH)
        self.list.clear()
        for h in hits:
            it = QListWidgetItem()
            it.setData(ROLE_KIND, K_HIT)
            it.setData(ROLE_HIT, h)
            it.setData(ROLE_IDX, 0)
            self.list.addItem(it)
        if hits:
            self.list.setCurrentRow(0)
        self.status.setText(status)

    # ---- 큐 --------------------------------------------------------------
    def _add_row(self, kind: str, item: QueueItem | None = None, text: str = "") -> None:
        it = QListWidgetItem()
        it.setData(ROLE_KIND, kind)
        it.setData(ROLE_HIT, item)
        it.setData(ROLE_TEXT, text)
        it.setData(ROLE_IDX, 0)
        self.list.addItem(it)

    def set_queue(self, result: QueueResult, status: str, now: float, keep: str | None = None) -> None:
        """빈 검색어일 때의 열린 일 목록. keep: 다시 그린 뒤 고를 항목 id(없으면 같은 줄 번호)."""
        old_row = self.list.currentRow()
        self.mode = "queue"
        self._queue = result
        self.delegate.now = now
        self.hint.setText(HINT_QUEUE)
        self.list.clear()
        if not result.open_count:
            self._add_row(K_EMPTY, text=f"최근 {result.days}일 동안 흔적이 있는 일이 없습니다")
        for q in result.focus:
            self._add_row(K_FOCUS, q)
        if result.rest:
            arrow = "▾" if self._show_rest else "▸"
            self._add_row(K_TOGGLE_REST, text=f"{arrow} 나머지 {len(result.rest)}개")
            if self._show_rest:
                for q in result.rest:
                    self._add_row(K_ROW, q)
        if result.closed:
            arrow = "▾" if self._show_closed else "▸"
            self._add_row(K_TOGGLE_CLOSED, text=f"{arrow} 닫은 일 보기 ({len(result.closed)}, 최근 {result.days}일)")
            if self._show_closed:
                for q in result.closed:
                    self._add_row(K_ROW, q)
        row = 0
        if keep is not None:
            for i in range(self.list.count()):
                q = self.list.item(i).data(ROLE_HIT)
                if q is not None and q.id == keep:
                    row = i
                    break
            else:
                row = max(0, min(old_row, self.list.count() - 1))
        if self.list.count():
            self.list.setCurrentRow(row)
        self.status.setText(status)

    def _toggle(self, kind: str) -> bool:
        if self.mode != "queue" or self._queue is None or kind not in (K_TOGGLE_REST, K_TOGGLE_CLOSED):
            return False
        if kind == K_TOGGLE_REST:
            self._show_rest = not self._show_rest
        else:
            self._show_closed = not self._show_closed
        row = self.list.currentRow()
        self.set_queue(self._queue, self.status.text(), self.delegate.now)
        self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))
        return True

    def _on_clicked(self, it: QListWidgetItem) -> None:
        self._toggle(it.data(ROLE_KIND))
        self.edit.setFocus()

    def _current_queue_item(self) -> QueueItem | None:
        it = self.list.currentItem()
        if self.mode != "queue" or not it or it.data(ROLE_KIND) not in (K_FOCUS, K_ROW):
            return None
        return it.data(ROLE_HIT)

    def _item_key(self, kind: str) -> None:
        q = self._current_queue_item()
        if q is None:
            return
        if kind in ("done", "drop") and q.closed_kind:
            kind = "reopen"       # 닫은 일 보기에서는 F4가 다시 열기
        self.action.emit(kind, q, 0)

    def _context_menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if not it or self.mode != "queue" or it.data(ROLE_KIND) not in (K_FOCUS, K_ROW):
            return
        self.list.setCurrentItem(it)
        q: QueueItem = it.data(ROLE_HIT)
        menu = QMenu(self)
        acts = [("열기\tEnter", "open"), ("대화 복사\tShift+Enter", "copy_conv")]
        acts += [("다시 열기\tF4", "reopen")] if q.closed_kind else [("완료\tF4", "done"), ("버림\tShift+F4", "drop")]
        for label, kind in acts:
            menu.addAction(label).triggered.connect(lambda _=False, k=kind: self.action.emit(k, q, 0))
        menu.exec(self.list.viewport().mapToGlobal(pos))
        self.edit.setFocus()

    # ---- 키 --------------------------------------------------------------
    def _navigate(self, step: int) -> None:
        n = self.list.count()
        if not n:
            return
        row = max(0, min(n - 1, self.list.currentRow() + step))
        self.list.setCurrentRow(row)

    def _switch(self, step: int) -> None:
        it = self.list.currentItem()
        if not it or it.data(ROLE_KIND) != K_HIT:
            return
        hit: Hit = it.data(ROLE_HIT)
        if not hit.matches:
            return
        idx = (int(it.data(ROLE_IDX) or 0) + step) % len(hit.matches)
        it.setData(ROLE_IDX, idx)
        self.list.viewport().update()

    def _emit(self, kind: str) -> None:
        it = self.list.currentItem()
        if not it:
            return
        k = it.data(ROLE_KIND)
        if self._toggle(k):
            return
        if k == K_EMPTY or (k != K_HIT and kind == "copy_msg"):
            return
        self.action.emit(kind, it.data(ROLE_HIT), int(it.data(ROLE_IDX) or 0))
