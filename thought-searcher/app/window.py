"""검색 창 UI.

구성 (docs/redesign-plan.md): 위 큰 검색칸 + 결과 수, 가운데 목록, 아래 막대(설정, 키 안내).
창이 WIDE_MIN_W 이상이면 목록 | 나누기 막대 | 미리보기 칸, 좁으면 목록만 (고른 줄만 두 번째 줄을 가짐).
"""
from __future__ import annotations

import html
import re
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStyle, QStyledItemDelegate, QToolButton,
                               QVBoxLayout, QWidget)

from . import mdparse
from . import theme as T
from . import ui_state
from .query import parse as parse_query
from .queue import QueueItem, QueueResult, relative_time
from .search import Hit, find_spans
from .theme import Theme

TEXT_FONTS = ["Segoe UI", "Malgun Gothic", "Segoe UI Emoji"]
ROLE_HIT = Qt.UserRole + 1
ROLE_IDX = Qt.UserRole + 2
ROLE_KIND = Qt.UserRole + 3
ROLE_TEXT = Qt.UserRole + 4
# 목록 항목 종류: 검색 결과, 큐(첫 줄들/나머지 줄), 접기 줄, 빈 큐 안내
K_HIT, K_FOCUS, K_ROW, K_TOGGLE_REST, K_TOGGLE_CLOSED, K_EMPTY = "hit", "focus", "row", "rest", "closed", "empty"
CLOSE_LABEL = {"done": "완료", "drop": "버림"}
# 아래 막대의 키 안내: (동작, 키들, 굵게, 좁으면 숨김)
HINTS_SEARCH = [("열기", ("Enter",), True, False), ("메시지 복사", ("Ctrl", "Enter"), False, False),
                ("대화 복사", ("Shift", "Enter"), False, True)]
HINTS_QUEUE = [("열기", ("Enter",), True, False), ("요약", ("F2",), False, False), ("완료", ("F4",), False, False),
               ("버림", ("Shift", "F4"), False, False), ("대화 복사", ("Shift", "Enter"), False, True)]
BADGE = {"claude-ai": "AI", "claude-code": "Code", "claude-ai-project": "P", "claude-ai-memory": "M", "chatgpt": "GPT", "note": "노트", "codex": "Codex",
         "journal": "일지"}
SOURCE_NAME = {"claude-ai": "claude.ai", "claude-code": "Claude Code", "claude-ai-project": "claude.ai 프로젝트",
               "claude-ai-memory": "claude.ai 메모리", "chatgpt": "ChatGPT", "note": "노트", "codex": "Codex",
               "journal": "업무 일지"}
PLACEHOLDER = "기억나는 단어 몇 개"
# 검색 옵션 칩: (글자, src: 값). 회사별로 모아 둔 순서
SOURCE_CHIPS = [("AI", "ai"), ("프로젝트", "project"), ("메모리", "memory"), ("Code", "code"), ("GPT", "gpt"),
                ("Codex", "codex"), ("노트", "note"), ("일지", "journal")]
_SRC_VALUE = {"claude-ai": "ai", "claude-ai-project": "project", "claude-ai-memory": "memory", "claude-code": "code",
              "chatgpt": "gpt", "codex": "codex", "note": "note", "journal": "journal"}
# 기간 칩: (글자, 며칠 전부터 / "year" / None=전체)
PERIOD_CHIPS = [("전체", None), ("1주", 7), ("1달", 30), ("3달", 90), ("올해", "year")]
PROJECT_LABEL_MAX = 12   # 최소 폭(560)에서도 둘째 줄이 넘치지 않게. 전체 이름은 툴팁
QUERY_TIP = ("기억나는 단어 몇 개  (\"구문\"  -제외  src:ai|code|codex|gpt|note|memory|project  proj:  after:2026-10)")
DEBOUNCE_MS = 150
PREVIEW_DEBOUNCE_MS = 60
WIN_W, WIN_H = 820, 560
WIDE_MIN_W = 760      # 이 폭 이상이면 목록 | 미리보기 (기준값)
DEFAULT_SPLIT = 0.4   # 넓을 때 목록 칸 비율
EDGE = 6              # 크기를 끌 수 있는 테두리 두께
CORNER_MARK = 14      # 오른쪽 아래 모서리 표시
SAVE_DELAY_MS = 500
CTX_CHARS = 500       # 미리보기: 앞뒤 메시지에서 보여 줄 글자 수
HIT_CHARS = 3000      # 미리보기: 맞은 메시지에서 보여 줄 글자 수
ROLE_NAME = {"user": "나", "assistant": "AI"}


def center_position(g: QRect, w: int, h: int) -> QPoint:
    return QPoint(g.left() + (g.width() - w) // 2, g.top() + (g.height() - h) // 3)


class EdgeGrip(QWidget):
    """창 테두리 한 변(또는 모서리). 누르고 끌면 시스템이 크기를 바꿔 준다 (QWindow.startSystemResize).
    mark=True면 오른쪽 아래 모서리 표시(점 세 줄)를 그린다."""

    def __init__(self, owner: "SearchWindow", edges, mark: bool = False):
        super().__init__(owner)
        self.owner, self.edges, self.mark = owner, edges, mark
        horiz = bool(edges & (Qt.LeftEdge | Qt.RightEdge))
        vert = bool(edges & (Qt.TopEdge | Qt.BottomEdge))
        diag_back = (edges & Qt.LeftEdge and edges & Qt.BottomEdge) or (edges & Qt.RightEdge and edges & Qt.TopEdge)
        if horiz and vert:
            self.setCursor(Qt.SizeBDiagCursor if diag_back else Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.SizeHorCursor if horiz else Qt.SizeVerCursor)
        self.color = QColor("#808080")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.owner.begin_user_resize(self.edges)
            e.accept()

    def paintEvent(self, _e):
        if not self.mark:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self.color, 1.2, Qt.SolidLine, Qt.RoundCap))
        w, h = self.width(), self.height()
        for k in (4, 8, 12):
            p.drawLine(w - 2, h - 2 - k, w - 2 - k, h - 2)


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
        self.copy_other = None    # Ctrl+C 때 다른 곳(요약 칸)의 고른 글을 먼저 복사하는 함수. True면 처리됨
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
        elif k == Qt.Key_C and mods == Qt.ControlModifier and self.copy_other and self.copy_other(self.hasSelectedText()):
            pass                           # 요약 칸에서 고른 글을 복사했다
        else:
            super().keyPressEvent(e)


def term_spans(text: str, terms: list[str]) -> list[tuple[int, int]]:
    """글 안에서 낱말(대소문자 무시)이 나오는 구간. 겹치면 합친다."""
    low = text.lower()
    spans: list[tuple[int, int]] = []
    for t in terms:
        t = t.lower()
        i = low.find(t) if t else -1
        while i >= 0:
            spans.append((i, i + len(t)))
            i = low.find(t, i + len(t))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


class ElideLabel(QLabel):
    """넘치면 '…'로 줄여 보이는 한 줄 라벨. text()는 전체 글자를 돌려준다 (결과 수, 상태, 설정 줄 설명).
    줄여진 때만 툴팁에 전체 글자를 보인다. set_marks로 낱말을 칠할 수 있다 (설정 찾기)."""

    MAX_W = 300
    elidedChanged = Signal(bool)          # '…'로 줄어 보이는지가 바뀌었다 (설정 줄의 ⓘ를 켜고 끈다)

    def __init__(self, text: str = ""):
        super().__init__("")
        self._full = ""
        self.elided = False
        self._terms: list[str] = []
        self._mark = ""
        self.setTextFormat(Qt.PlainText)
        self.setText(text)

    def text(self) -> str:
        return self._full

    def setText(self, t: str) -> None:
        self._full = str(t)
        self._elide()
        self.updateGeometry()

    def set_marks(self, terms: list[str], mark_hex: str = "") -> None:
        self._terms = [t for t in terms if t]
        self._mark = mark_hex
        self._elide()

    def _elide(self) -> None:
        w = max(10, self.width() - 8)
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, w) if self.width() > 8 else self._full
        # 줄여 보인 때만 전체 글자 (줄바꿈되는 표로 감싸 긴 설명도 한눈에)
        self.setToolTip(tip_wrap(self._full, 340) if shown != self._full else "")
        if (shown != self._full) != self.elided:
            self.elided = shown != self._full
            self.elidedChanged.emit(self.elided)
        spans = term_spans(shown, self._terms) if self._terms and self._mark else []
        if spans:
            self.setTextFormat(Qt.RichText)
            super().setText(_marked_html(shown, spans, self._mark))
        else:
            self.setTextFormat(Qt.PlainText)
            super().setText(shown)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def sizeHint(self) -> QSize:
        h = super().sizeHint().height()
        return QSize(min(self.MAX_W, self.fontMetrics().horizontalAdvance(self._full) + 12), h)

    def minimumSizeHint(self) -> QSize:
        return QSize(40, super().minimumSizeHint().height())


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


def paint_badge(p: QPainter, t: Theme, small: QFont, x: int, top: int, line_h: int, source: str) -> int:
    """출처 배지를 (x, 줄 top) 에 그리고 너비를 돌려준다."""
    fms = QFontMetrics(small)
    badge = BADGE.get(source, "MD")
    bw = fms.horizontalAdvance(badge) + 10
    rect = QRect(x, top + (line_h - fms.height()) // 2 - 1, bw, fms.height() + 2)
    fill, edge, color = T.badge_colors(t, source)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(edge, 1) if edge is not None else Qt.NoPen)
    p.setBrush(fill if fill is not None else Qt.NoBrush)
    p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setFont(small)
    p.setPen(color)
    p.drawText(rect, Qt.AlignCenter, badge)
    return bw


class HitDelegate(QStyledItemDelegate):
    """결과 줄 한 줄: 배지, 제목, 프로젝트, 날짜. 고른 줄은 바탕색 + 왼쪽 강조색 막대.
    compact=False(좁음)이면 고른 줄만 두 번째 줄(맞은 메시지 미리보기, 큐는 일지 항목)을 가진다."""

    def __init__(self, theme: Theme, font: QFont, parent=None):
        super().__init__(parent)
        self.t = theme
        self.font = font
        self.bold = QFont(font)
        self.bold.setBold(True)
        self.small = QFont(font)
        self.small.setPointSizeF(font.pointSizeF() * 0.9)
        self.now = 0.0      # 큐 상대 시각 기준 (창이 채운다)
        self.ask_state: dict[str, str] = {}   # 요약 중이거나 실패한 항목: id -> 표시할 한 줄
        self.compact = False                  # True: 모든 줄이 한 줄 (넓을 때)
        self.current_row = -1                 # 고른 줄 번호 (창이 채운다)

    def summary_line(self, it: QueueItem) -> str:
        if it.id in self.ask_state:
            return self.ask_state[it.id]
        if it.summary:
            return (f"요약: {it.summary}" + ("  (새 흔적 있음)" if it.summary_stale else "")
                    + (f"  · {it.summary_model}" if it.summary_model else ""))
        return ""

    def second_line(self, index) -> bool:
        """이 줄이 두 번째 줄을 가지나 (좁을 때 고른 줄만)."""
        if self.compact or index.row() != self.current_row:
            return False
        kind = index.data(ROLE_KIND) or K_HIT
        if kind == K_HIT:
            hit: Hit = index.data(ROLE_HIT)
            return bool(hit and hit.matches)
        if kind in (K_FOCUS, K_ROW):
            it: QueueItem = index.data(ROLE_HIT)
            return bool(it and it.subtitle)
        return False

    def sizeHint(self, option, index):
        fm = QFontMetrics(self.font)
        h = fm.height() + 14
        if self.second_line(index):
            h += fm.height() + 3
        return QSize(option.rect.width(), h)

    def _bar(self, p: QPainter, r: QRect, selected: bool) -> None:
        if selected:
            p.fillRect(r, self.t.sel)
            p.fillRect(QRect(r.left(), r.top(), 3, r.height()), self.t.accent)

    def _paint_plain(self, p: QPainter, option, index, kind: str) -> None:
        r = option.rect
        p.save()
        self._bar(p, r, bool(option.state & QStyle.State_Selected))
        x0, max_x = r.left() + 14, r.right() - 12
        if kind != K_EMPTY:
            p.setPen(QPen(self.t.line))
            p.drawLine(r.left() + 6, r.top() + 1, r.right() - 6, r.top() + 1)
        p.setFont(self.font)
        p.setPen(self.t.sub)
        p.drawText(QRect(x0, r.top() + 2, max_x - x0, r.height() - 2), Qt.AlignVCenter | Qt.AlignLeft,
                   index.data(ROLE_TEXT) or "")
        p.restore()

    def _paint_queue(self, p: QPainter, option, index) -> None:
        r = option.rect
        it: QueueItem = index.data(ROLE_HIT)
        p.save()
        self._bar(p, r, bool(option.state & QStyle.State_Selected))
        x0, max_x = r.left() + 14, r.right() - 12
        fm, fms = QFontMetrics(self.font), QFontMetrics(self.small)
        closed = bool(it.closed_kind)
        if closed:
            when = f"{CLOSE_LABEL.get(it.closed_kind, '')} · {relative_time(it.closed_at, self.now)}"
        else:
            when = relative_time(it.trace_ts, self.now)
        right = "  ·  ".join(s for s in (it.project, when) if s)
        rw = fms.horizontalAdvance(right)
        top = r.top() + 7
        y1 = top + fm.ascent()
        bw = paint_badge(p, self.t, self.small, x0, top, fm.height(), it.source)
        p.setFont(self.bold)
        _draw_runs(p, x0 + bw + 8, y1, max_x - rw - 12, it.title or "(제목 없음)", [], QFontMetrics(self.bold),
                   self.t.sub if closed else self.t.text, self.t.mark_bg)
        p.setFont(self.small)
        p.setPen(self.t.sub)
        p.drawText(max_x - rw, y1, right)
        if self.second_line(index):
            p.setFont(self.font)
            _draw_runs(p, x0 + bw + 8, y1 + fm.height() + 3, max_x, it.subtitle, [], fm, self.t.sub, self.t.mark_bg)
        p.restore()

    def paint(self, p: QPainter, option, index):
        kind = index.data(ROLE_KIND) or K_HIT
        if kind in (K_TOGGLE_REST, K_TOGGLE_CLOSED, K_EMPTY):
            self._paint_plain(p, option, index, kind)
            return
        if kind in (K_FOCUS, K_ROW):
            self._paint_queue(p, option, index)
            return
        hit: Hit = index.data(ROLE_HIT)
        if hit is None:
            return
        idx = index.data(ROLE_IDX) or 0
        p.save()
        r = option.rect
        self._bar(p, r, bool(option.state & QStyle.State_Selected))
        fm = QFontMetrics(self.font)
        fmb = QFontMetrics(self.bold)
        fms = QFontMetrics(self.small)
        x0 = r.left() + 14
        max_x = r.right() - 12
        top = r.top() + 7
        y1 = top + fm.ascent()
        # 한 줄: 출처 | 제목 | 프로젝트 | 날짜(MM-DD) | (원본 없음)
        bw = paint_badge(p, self.t, self.small, x0, top, fm.height(), hit.source)
        right_parts = []
        if hit.project and hit.source != "claude-ai-project":
            right_parts.append(hit.project)
        if hit.updated:
            right_parts.append(hit.updated.astimezone().strftime("%m-%d"))
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
        # 좁을 때 고른 줄만 두 번째 줄: 맞은 메시지 미리보기 + ← i/n →
        if self.second_line(index):
            y2 = y1 + fm.height() + 3
            m = hit.matches[min(idx, len(hit.matches) - 1)]
            total = hit.match_total or len(hit.matches)
            tag = f"← {idx + 1}/{total} →" if total > 1 else ""
            tw = fms.horizontalAdvance(tag) + 8 if tag else 0
            p.setFont(self.font)
            _draw_runs(p, x0 + bw + 8, y2, max_x - tw - 4, m.preview, m.highlights, fm, self.t.sub, self.t.mark_bg)
            if tag:
                p.setFont(self.small)
                p.setPen(self.t.sub)
                p.drawText(max_x - tw + 8, y2, tag)
        p.restore()


# ---- 미리보기 (넓을 때 오른쪽 칸) -----------------------------------------------
class MdCache:
    """md 경로 + 수정시각으로 읽은 결과를 기억한다 (고른 줄을 오가도 다시 읽지 않음)."""

    def __init__(self, size: int = 8):
        self.size = size
        self._d: OrderedDict = OrderedDict()

    def get(self, path) -> mdparse.ParsedDoc | None:
        p = Path(path)
        try:
            key = (str(p), p.stat().st_mtime_ns)
        except OSError:
            return None
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        doc = mdparse.parse_file(p)
        self._d[key] = doc
        while len(self._d) > self.size:
            self._d.popitem(last=False)
        return doc


def match_regs(hit: Hit) -> list[re.Pattern]:
    """맞은 낱말 정규식: 목록 미리보기에서 강조된 글자들(대소문자 무시)."""
    words = {m.preview[s:e] for m in hit.matches for s, e in m.highlights if m.preview[s:e].strip()}
    return [re.compile(re.escape(w), re.IGNORECASE) for w in sorted(words, key=len, reverse=True)]


def pick_context(doc: mdparse.ParsedDoc, ordinal: int):
    """(앞 메시지 또는 None, 맞은 메시지, 뒤 메시지 또는 None). 맞은 메시지가 없으면 None."""
    for i, m in enumerate(doc.messages):
        if m.ordinal == ordinal:
            return (doc.messages[i - 1] if i > 0 else None, m,
                    doc.messages[i + 1] if i + 1 < len(doc.messages) else None)
    return None


def crop(text: str, spans: list[tuple[int, int]], limit: int) -> tuple[str, list[tuple[int, int]]]:
    """긴 글은 첫 맞은 곳 앞 조금부터 limit 글자만. 잘린 쪽에 '…'를 붙이고 강조 구간을 맞춰 옮긴다."""
    if len(text) <= limit:
        return text, spans
    start = max(0, (spans[0][0] - min(200, limit // 4)) if spans else 0)
    end = min(len(text), start + limit)
    out = ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")
    shift = start - (1 if start else 0)
    new = [(max(0, s - shift), min(len(out), e - shift)) for s, e in spans if e > start and s < end]
    return out, new


def _marked_html(text: str, spans: list[tuple[int, int]], mark: str) -> str:
    out, pos = [], 0
    for s, e in spans:
        out.append(html.escape(text[pos:s]))
        out.append(f'<span style="background-color:{mark}">{html.escape(text[s:e])}</span>')
        pos = e
    out.append(html.escape(text[pos:]))
    return "".join(out)


def to_html(text: str, spans: list[tuple[int, int]], mark: str) -> str:
    return _marked_html(text, spans, mark).replace("\n", "<br>")


class BadgeWidget(QWidget):
    """미리보기 머리의 출처 배지 (목록 줄과 같은 모양)."""

    def __init__(self, theme: Theme, font: QFont):
        super().__init__()
        self.t = theme
        self.small = QFont(font)
        self.small.setPointSizeF(font.pointSizeF() * 0.9)
        self.source = ""

    def set_source(self, source: str) -> None:
        self.source = source
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        fms = QFontMetrics(self.small)
        return QSize(fms.horizontalAdvance(BADGE.get(self.source, "MD")) + 10, fms.height() + 4)

    def paintEvent(self, _e):
        if self.source:
            p = QPainter(self)
            paint_badge(p, self.t, self.small, 0, 0, self.height(), self.source)


def _wrap_label(text: str = "", name: str = "", rich: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(True)
    lb.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


class PreviewPane(QFrame):
    """오른쪽 미리보기 칸: 배지+제목, 출처·프로젝트·날짜, 맞은 메시지 i / n, 본문 (또는 큐의 저장된 요약)."""

    def __init__(self, theme: Theme, font: QFont):
        super().__init__()
        self.setObjectName("preview")
        self.t = theme
        self.setMinimumWidth(240)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 14, 10)
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.badge = BadgeWidget(theme, font)
        self.title = QLabel("")
        self.title.setObjectName("pvTitle")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.PlainText)
        head.addWidget(self.badge, 0, Qt.AlignTop)
        head.addWidget(self.title, 1)
        v.addLayout(head)
        self.meta = QLabel("")
        self.meta.setObjectName("pvMeta")
        self.meta.setWordWrap(True)
        self.meta.setTextFormat(Qt.PlainText)
        v.addWidget(self.meta)
        self.index = QLabel("")
        self.index.setObjectName("pvIndex")
        v.addWidget(self.index)
        v.addSpacing(6)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("previewScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.body.setObjectName("previewBody")
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 4, 0)
        self.body_lay.setSpacing(8)
        self.body_lay.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.body)
        v.addWidget(self.scroll, 1)
        self._keep: list[QWidget] = []        # 본문을 비울 때 지우지 않을 위젯 (큐의 요약 라벨)

    def set_theme(self, t: Theme) -> None:
        self.t = t
        self.badge.t = t
        self.badge.update()

    def keep(self, w: QWidget) -> None:
        self._keep = [w]

    def clear_body(self) -> None:
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            w = item.widget()
            if w is None:
                continue
            if w in self._keep:
                w.hide()
                w.setParent(self)          # 지우지 않고 잠시 맡아 둔다 (창이 다시 가져감)
            else:
                w.hide()                   # 지워지기 전까지 남아 겹쳐 보이지 않게
                w.deleteLater()

    def set_header(self, source: str, title: str, meta: str, index: str = "", sub: str = "") -> None:
        self.badge.set_source(source)
        self.title.setText(title or "(제목 없음)")
        self.title.setToolTip(title)
        self.meta.setText(meta + (f"\n{sub}" if sub else ""))
        self.index.setText(index)
        self.index.setVisible(bool(index))

    def add_note(self, text: str) -> None:
        if text:
            self.body_lay.addWidget(_wrap_label(text, "pvEmpty"))

    def add_recent(self, lines: list[tuple[str, str, str]], title: str = "최근 대화") -> None:
        """큐: 최근 몇 턴을 '나 : …', 'AI : …' 한 줄씩. 줄을 가리키면 전체 글자."""
        if not lines:
            return
        frame = QFrame()
        frame.setObjectName("pvRecent")
        g = QGridLayout(frame)
        g.setContentsMargins(12, 8, 10, 10)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(4)
        g.addWidget(_wrap_label(title, "pvRole"), 0, 0, 1, 2)
        for r, (role, short, full) in enumerate(lines, 1):
            who = QLabel(role)
            who.setObjectName("pvWho")
            line = QLabel(short)
            line.setObjectName("pvLine")
            line.setTextFormat(Qt.PlainText)
            if full != short:
                line.setToolTip(tip_wrap(full))
            g.addWidget(who, r, 0, Qt.AlignTop)
            g.addWidget(line, r, 1)
        g.setColumnStretch(1, 1)
        self.body_lay.addWidget(frame)

    def add_block(self, hit_block: bool, role: str, text: str, spans: list[tuple[int, int]]) -> None:
        frame = QFrame()
        frame.setObjectName("pvHit" if hit_block else "pvCtx")
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 8, 10, 10)
        v.setSpacing(3)
        v.addWidget(_wrap_label(role, "pvRole"))
        v.addWidget(_wrap_label(to_html(text, spans, self.t.mark_bg.name()), "", rich=True))
        self.body_lay.addWidget(frame)


RECENT_TURNS = 5       # 큐 미리보기: 최근 대화 몇 턴 (사용자 질문 하나 + 그 뒤 답들 = 한 턴)
RECENT_CHARS = 30      # 한 줄에 보일 글자 수 (전체는 툴팁)
_MD_NOISE = re.compile(r"```\w*|[`*#>]+|!?\[([^\]]*)\]\([^)]*\)")


def tip_wrap(text: str, width: int = 420) -> str:
    """Qt 툴팁은 순수 글자면 줄바꿈하지 않아 폭을 정한 표로 감싼다."""
    return f"<table width='{width}'><tr><td>{html.escape(text)}</td></tr></table>"


def one_line(text: str, n: int = RECENT_CHARS) -> tuple[str, str]:
    """md 본문 -> (n자로 줄인 한 줄, 툴팁용 전체 한 줄). 꾸밈 기호는 빼고 공백은 하나로."""
    flat = " ".join(_MD_NOISE.sub(lambda m: m.group(1) or " ", text or "").split())
    return (flat if len(flat) <= n else flat[:n].rstrip() + "…"), flat


def recent_turns(doc, turns: int = RECENT_TURNS, n: int = RECENT_CHARS) -> list[tuple[str, str, str]]:
    """대화 md의 마지막 몇 턴: [(역할 이름, 줄인 한 줄, 전체 한 줄)]. 가지(branch) 메시지와 빈 메시지는 뺀다."""
    if doc is None:
        return []
    msgs = [m for m in doc.messages if not m.is_branch and one_line(m.text, n)[1]]
    starts = [i for i, m in enumerate(msgs) if m.role == "user"]
    first = starts[-turns] if len(starts) >= turns else 0
    out = []
    for m in msgs[first:]:
        short, full = one_line(m.text, n)
        out.append((ROLE_NAME.get(m.role, m.role), short, full))
    return out


def project_token(name: str) -> str:
    """프로젝트 이름 -> proj: 값. 검색 문법은 공백에서 끊기므로 이름에서 가장 긴 공백 없는 조각을 쓴다
    (proj:는 부분 일치라 그 조각을 가진 프로젝트가 같이 걸릴 수 있다)."""
    parts = [p.strip('"') for p in str(name or "").split()]
    parts = [p for p in parts if p]
    return max(parts, key=len) if parts else ""


def period_after(kind, today: date) -> date | None:
    if kind is None:
        return None
    if kind == "year":
        return date(today.year, 1, 1)
    return today - timedelta(days=int(kind))


class ChipBar(QFrame):
    """검색칸 아래 옵션 칩 두 줄 (출처 / 기간, 프로젝트). 검색칸에는 글자를 넣지 않고,
    검색할 때 compose()가 칩 토큰을 검색어 뒤에 붙인다. 칩은 초점을 가져가지 않는다."""
    changed = Signal()

    def __init__(self, projects: Callable[[], list[str]] | None = None):
        super().__init__()
        self.setObjectName("chips")
        self.projects = projects or (lambda: [])
        self.menu_open = False                    # 프로젝트 메뉴가 떠 있는 동안 창을 숨기지 않게
        self._clicked: set[str] = set()           # 누른 출처 칩 (src 값)
        self._typed: set[str] = set()             # 검색칸에 손으로 친 src: (표시만)
        self._typed_proj: list[str] = []
        self.period = None
        self.project = ""
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 0, 18, 10)
        v.setSpacing(6)
        row1 = self._row(v, "출처")
        self.src_buttons: dict[str, QPushButton] = {}
        for label, value in SOURCE_CHIPS:
            b = self._chip(label)
            b.clicked.connect(lambda _c=False, val=value: self._toggle_source(val))
            row1.addWidget(b)
            self.src_buttons[value] = b
        row1.addStretch(1)
        row2 = self._row(v, "기간")
        self.period_group = QButtonGroup(self)
        self.period_group.setExclusive(True)
        self.period_buttons: dict[object, QPushButton] = {}
        for label, kind in PERIOD_CHIPS:
            b = self._chip(label)
            self.period_group.addButton(b)
            b.clicked.connect(lambda _c=False, k=kind: self._set_period(k))
            row2.addWidget(b)
            self.period_buttons[kind] = b
        sep = QFrame()
        sep.setObjectName("chipSep")
        sep.setFixedSize(1, 16)
        row2.addSpacing(4)
        row2.addWidget(sep)
        row2.addSpacing(4)
        self.proj_button = self._chip("프로젝트 ▾", checkable=False)
        self.proj_button.clicked.connect(self._pick_project)
        row2.addWidget(self.proj_button)
        row2.addStretch(1)
        self.clear_button = QPushButton("모두 지우기")
        self.clear_button.setObjectName("chipClear")
        self.clear_button.setFocusPolicy(Qt.NoFocus)
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear)
        row2.addWidget(self.clear_button)
        self._render()

    def _row(self, v: QVBoxLayout, caption: str) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(6)
        cap = QLabel(caption)
        cap.setObjectName("chipCaption")
        cap.setFixedWidth(30)
        h.addWidget(cap)
        v.addLayout(h)
        return h

    def _chip(self, text: str, checkable: bool = True) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("qchip")
        b.setCheckable(True)                     # 켜짐 모양은 :checked로. 프로젝트 칩은 _render가 정한다
        b.setFocusPolicy(Qt.NoFocus)
        b.setCursor(Qt.PointingHandCursor)
        b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)    # 좁은 창에서 글자가 잘리게 줄어들지 않게
        if not checkable:
            b.setProperty("menu", True)
        return b

    # ---- 상태 -----------------------------------------------------------------
    def _toggle_source(self, value: str) -> None:
        if value in self._clicked:
            self._clicked.discard(value)
        else:
            self._clicked.add(value)
        self._render()
        self.changed.emit()

    def _set_period(self, kind) -> None:
        self.period = kind
        self._render()
        self.changed.emit()

    def _pick_project(self) -> None:
        menu = QMenu(self)
        menu.addAction("모든 프로젝트").setData("")
        try:
            names = list(self.projects())
        except Exception:  # noqa: BLE001  색인을 못 읽어도 창은 그대로
            names = []
        if names:
            menu.addSeparator()
        for n in names:
            act = menu.addAction(n)
            act.setData(n)
            act.setCheckable(True)
            act.setChecked(n == self.project)
        if not names:
            act = menu.addAction("(프로젝트가 있는 대화 없음)")
            act.setEnabled(False)
        self.menu_open = True
        try:
            got = menu.exec(self.proj_button.mapToGlobal(self.proj_button.rect().bottomLeft()))
        finally:
            self.menu_open = False
            self.window().activateWindow()       # 메뉴가 닫히면 검색 창을 다시 앞으로
        self._render()                           # 누른 순간 :checked가 바뀐 것을 되돌린다
        if got is None or got.data() is None:
            return
        self.project = str(got.data())
        self._render()
        self.changed.emit()

    def clear(self) -> None:
        had = self.active()
        self.reset()
        if had:
            self.changed.emit()

    def reset(self) -> None:
        """창을 열 때마다 모두 끈다."""
        self._clicked.clear()
        self.period = None
        self.project = ""
        self._render()

    def active(self) -> bool:
        return bool(self._clicked or self.period is not None or self.project)

    def sync_from_text(self, text: str) -> None:
        """손으로 친 src:, proj:는 해당 칩을 켜진 것으로만 보인다(토큰을 더 붙이지 않는다)."""
        q = parse_query(text or "")
        self._typed = {_SRC_VALUE[s] for s in q.sources if s in _SRC_VALUE}
        self._typed_proj = list(q.projects)
        self._render()

    def _render(self) -> None:
        for value, b in self.src_buttons.items():
            b.setChecked(value in self._clicked or value in self._typed)
        self.period_buttons[self.period].setChecked(True)
        if self.project:
            name = self.project if len(self.project) <= PROJECT_LABEL_MAX else self.project[:PROJECT_LABEL_MAX - 1] + "…"
            self.proj_button.setText(f"{name} ▾")
            self.proj_button.setToolTip(self.project)
        elif self._typed_proj:
            self.proj_button.setText(f"{self._typed_proj[0]} ▾")
            self.proj_button.setToolTip("")
        else:
            self.proj_button.setText("프로젝트 ▾")
            self.proj_button.setToolTip("")
        self.proj_button.setChecked(bool(self.project or self._typed_proj))
        self.clear_button.setVisible(self.active())

    # ---- 토큰 -----------------------------------------------------------------
    def tokens(self, today: date | None = None) -> list[str]:
        out = [f"src:{v}" for _l, v in SOURCE_CHIPS if v in self._clicked]
        after = period_after(self.period, today or date.today())
        if after:
            out.append(f"after:{after.isoformat()}")
        tok = project_token(self.project)
        if tok:
            out.append(f"proj:{tok}")
        return out

    def compose(self, text: str, today: date | None = None) -> str:
        toks = self.tokens(today)
        if not toks:
            return text
        return f"{text.rstrip()} {' '.join(toks)}".strip()


class SearchWindow(QWidget):
    searchRequested = Signal(str)
    action = Signal(str, object, int)    # (종류, Hit, 맞은 메시지 순번)
    settingsRequested = Signal()         # 아래 막대 ⚙

    def __init__(self, theme: Theme | None = None, state_path=None, projects: Callable[[], list[str]] | None = None):
        """projects: 프로젝트 칩 메뉴에 보일 이름 목록을 돌려주는 함수 (main.py가 색인에서 읽는다)."""
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.state_path = state_path          # ui_state.json (없으면 크기를 저장하지 않음)
        self._state = ui_state.search_state(ui_state.load(state_path))
        self._saved = dict(self._state)
        self._user_dirty = False              # 사용자가 크기를 바꿨나 (화면에 맞춰 줄인 크기는 저장하지 않는다)
        self._split = float(self._state.get("split", DEFAULT_SPLIT))
        self._applying_split = False
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.setWindowTitle("생각 검색기")
        self.t = theme or T.make()
        font = QFont()
        font.setFamilies(TEXT_FONTS)
        font.setPointSize(10)
        self.setFont(font)
        self.setMinimumSize(ui_state.MIN_W, ui_state.MIN_H)
        self.resize(self._state.get("w", WIN_W), self._state.get("h", WIN_H))
        self.ask_enabled = True
        self.wide: bool | None = None         # 폭에 따른 배치 (처음에는 정하지 않음)
        self.md_cache = MdCache()
        root = QWidget(self)
        root.setObjectName("root")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(root)
        inner = QVBoxLayout(root)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        # 머리: 돋보기, 큰 검색칸, 결과 수
        head = QFrame()
        head.setObjectName("head")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(0)
        hh = QHBoxLayout()
        hh.setContentsMargins(18, 12, 18, 8)
        hh.setSpacing(10)
        hv.addLayout(hh)
        self.chips = ChipBar(projects)
        self.chips.changed.connect(self._on_chips)
        hv.addWidget(self.chips)
        self.search_icon = QLabel()
        self.search_icon.setFixedSize(22, 22)
        self.edit = QueryEdit()
        self.edit.setObjectName("query")
        self.edit.setPlaceholderText(PLACEHOLDER)
        self.edit.setToolTip(QUERY_TIP)
        self.status = ElideLabel("")
        self.status.setObjectName("count")
        hh.addWidget(self.search_icon)
        hh.addWidget(self.edit, 1)
        hh.addWidget(self.status)
        inner.addWidget(head)
        # 가운데: 목록 | 미리보기
        self.list = QListWidget()
        self.delegate = HitDelegate(self.t, font, self.list)
        self.list.setItemDelegate(self.delegate)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.itemDoubleClicked.connect(lambda _i: self._emit("open"))
        self.list.itemClicked.connect(self._on_clicked)
        self.list.currentRowChanged.connect(self._on_row_changed)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.detail = QLabel("")          # 큐: 고른 일의 저장된 요약
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.PlainText)
        self.detail.setObjectName("detail")
        # 끌어서 고른 뒤 Ctrl+C 또는 오른쪽 클릭으로 복사. 초점은 검색칸에 남긴다(키 조작이 그대로 되게)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail.setFocusPolicy(Qt.NoFocus)
        self.detail.setCursor(Qt.IBeamCursor)
        self.detail.setContextMenuPolicy(Qt.CustomContextMenu)
        self.detail.customContextMenuRequested.connect(self._detail_menu)
        self._menu_open = False
        self.edit.copy_other = lambda edit_has_sel: bool(self.detail.selectedText()) and self.copy_summary()
        self.detail.hide()
        self.left = QWidget()
        self.left_lay = QVBoxLayout(self.left)
        self.left_lay.setContentsMargins(EDGE, 4, EDGE, 6)
        self.left_lay.setSpacing(6)
        self.left_lay.addWidget(self.list, 1)
        self.left_lay.addWidget(self.detail)
        self.left.setMinimumWidth(260)
        self.pane = PreviewPane(self.t, font)
        self.pane.keep(self.detail)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(7)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.pane)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 6)
        self.splitter.splitterMoved.connect(self._on_split_moved)
        inner.addWidget(self.splitter, 1)
        # 아래 막대: 설정, 앱 이름, 키 안내
        bar = QFrame()
        bar.setObjectName("bottomBar")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(10, 6, 20, 6)
        bh.setSpacing(8)
        self.gear = QToolButton()
        self.gear.setObjectName("gear")
        self.gear.setIconSize(QSize(16, 16))
        self.gear.setToolTip("설정")
        self.gear.setFocusPolicy(Qt.NoFocus)
        self.gear.setCursor(Qt.PointingHandCursor)
        self.gear.clicked.connect(self.settingsRequested.emit)
        bh.addWidget(self.gear)
        bh.addWidget(self._plain_label("생각 검색기", "appName"))
        bh.addStretch(1)
        self.hint_box = QHBoxLayout()
        self.hint_box.setSpacing(14)
        bh.addLayout(self.hint_box)
        inner.addWidget(bar)
        self._hint_widgets: list[tuple[QWidget, bool]] = []
        self._grips = [EdgeGrip(self, edges, mark) for edges, mark in (
            (Qt.LeftEdge, False), (Qt.RightEdge, False), (Qt.TopEdge, False), (Qt.BottomEdge, False),
            (Qt.LeftEdge | Qt.TopEdge, False), (Qt.RightEdge | Qt.TopEdge, False),
            (Qt.LeftEdge | Qt.BottomEdge, False), (Qt.RightEdge | Qt.BottomEdge, True))]
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_state)
        self._pv_timer = QTimer(self)
        self._pv_timer.setSingleShot(True)
        self._pv_timer.setInterval(PREVIEW_DEBOUNCE_MS)
        self._pv_timer.timeout.connect(self._refresh_preview)
        self.mode = "search"
        self._queue: QueueResult | None = None
        self._show_rest = False
        self._show_closed = False
        self.set_theme(self.t)
        self._apply_mode()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._pending = ""
        self._timer.timeout.connect(lambda: self.searchRequested.emit(self.query_text()))
        self.edit.queryChanged.connect(self._on_changed)
        self.edit.navigate.connect(self._navigate)
        self.edit.switchMatch.connect(self._switch)
        self.edit.accepted.connect(self._emit)
        self.edit.itemKey.connect(self._item_key)
        self.edit.cancelled.connect(self.hide)

    @staticmethod
    def _plain_label(text: str, name: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName(name)
        return lb

    # ---- 표시 ---------------------------------------------------------------
    def set_theme(self, t: Theme) -> None:
        """테마 바꾸기 (설정 저장, 시스템 모드 전환 때 main.py가 부른다)."""
        self.t = t
        self.delegate.t = t
        self.setPalette(T.palette(t))
        self.setStyleSheet(T.search_qss(t))
        self.gear.setIcon(T.icon("settings", t.sub, 16))
        self.search_icon.setPixmap(T.icon("search", t.sub, 20).pixmap(20, 20))
        for g in getattr(self, "_grips", []):
            g.color = t.placeholder
        self.pane.set_theme(t)
        self.list.viewport().update()
        self._refresh_preview()

    def popup(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        w, h = ui_state.fit_size(self.width(), self.height(), g.width(), g.height())
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)                 # 이 모니터보다 크면 줄인다 (저장된 크기는 그대로 둔다)
        self.move(center_position(g, self.width(), self.height()))
        # 목록을 먼저 채운 뒤 띄운다 (띄우고 채우면 큐 계산 동안 빈 창이 보인다)
        self._show_rest = self._show_closed = False
        self.chips.reset()
        self.chips.sync_from_text(self.edit.full_text())
        self.refresh()
        T.show_without_flash(self)
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()
        self.edit.selectAll()

    def query_text(self) -> str:
        """검색에 넘기는 글자: 검색칸 + 켜진 칩 토큰."""
        return self.chips.compose(self._pending)

    def refresh(self) -> None:
        self._pending = self.edit.full_text()
        self.searchRequested.emit(self.query_text())

    def _on_chips(self) -> None:
        """칩을 눌렀다: 바로 다시 검색. 초점은 검색칸에 그대로."""
        self._timer.stop()
        self._show_rest = self._show_closed = False
        self.refresh()
        self.edit.setFocus()

    # ---- 크기 조절, 저장 ------------------------------------------------------
    def _place_grips(self) -> None:
        w, h, b = self.width(), self.height(), EDGE
        left, right, top, bottom, tl, tr, bl, br = self._grips
        left.setGeometry(0, b, b, h - 2 * b)
        right.setGeometry(w - b, b, b, h - 2 * b)
        top.setGeometry(b, 0, w - 2 * b, b)
        bottom.setGeometry(b, h - b, w - 2 * b, b)
        tl.setGeometry(0, 0, b, b)
        tr.setGeometry(w - b, 0, b, b)
        bl.setGeometry(0, h - b, b, b)
        br.setGeometry(w - CORNER_MARK, h - CORNER_MARK, CORNER_MARK, CORNER_MARK)
        for g in self._grips:
            g.raise_()

    def begin_user_resize(self, edges) -> None:
        """테두리를 눌렀다: 시스템 크기 조절을 시작한다 (끝날 때까지 돌아오지 않음). 끝나면 저장 예약."""
        handle = self.windowHandle()
        if handle is None:
            return
        if handle.startSystemResize(edges):
            self.user_resized()

    def user_resized(self) -> None:
        """사용자가 크기(또는 나누기 위치)를 바꿨다: 잠시 뒤 저장."""
        self._user_dirty = True
        self._save_timer.start()

    def current_state(self) -> dict:
        return {**self._state, "w": self.width(), "h": self.height(), "split": round(self._split, 3)}

    def save_state(self) -> None:
        """바뀐 것이 있을 때만 ui_state.json에 쓴다. 다른 키는 그대로 둔다."""
        self._save_timer.stop()
        if self.state_path is None or not self._user_dirty:
            return
        cur = self.current_state()
        if cur == self._saved:
            return
        data = ui_state.load(self.state_path)
        if ui_state.save(self.state_path, ui_state.with_search_state(data, cur)):
            self._saved = cur
            self._state = cur
            self._user_dirty = False

    def _on_split_moved(self, _pos: int, _index: int) -> None:
        if self._applying_split:
            return
        sizes = self.splitter.sizes()
        total = sum(sizes)
        if total > 0:
            self._split = min(ui_state.SPLIT_MAX, max(ui_state.SPLIT_MIN, sizes[0] / total))
            self.user_resized()

    def _apply_split(self) -> None:
        total = max(self.splitter.width(), self.width() - 2)
        if total <= 0:
            return
        left = int(total * self._split)
        self._applying_split = True
        self.splitter.setSizes([left, total - left])
        self._applying_split = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_grips()
        self._apply_mode()
        if self.wide:
            self._apply_split()

    def showEvent(self, e):
        super().showEvent(e)
        T.round_corners(self)

    def hideEvent(self, e):
        self.save_state()
        super().hideEvent(e)

    # ---- 좁음 / 넓음 -----------------------------------------------------------
    def _apply_mode(self) -> None:
        """창 폭이 WIDE_MIN_W 이상이면 넓은 배치. 바뀌었을 때만 다시 배치한다."""
        wide = self.width() >= WIDE_MIN_W
        if wide == self.wide:
            return
        self.wide = wide
        self.delegate.compact = wide
        self.pane.setVisible(wide)
        self._set_hints()
        self._place_detail()
        self.list.doItemsLayout()
        self.list.viewport().update()
        if wide:
            self._apply_split()
            self._refresh_preview()

    def _set_hints(self) -> None:
        """아래 막대의 키 안내를 지금 모드에 맞게 다시 만든다. 대화 복사는 좁으면 숨긴다."""
        while self.hint_box.count():
            item = self.hint_box.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)      # 바로 떼어 새 안내와 겹치지 않게
                item.widget().deleteLater()
        self._hint_widgets = []
        specs = HINTS_QUEUE if self.mode == "queue" else HINTS_SEARCH
        for action, keys, strong, narrow_hide in specs:
            if action == "요약" and not self.ask_enabled:
                continue
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(5)
            h.addWidget(self._plain_label(action, "keyActionStrong" if strong else "keyAction"))
            for k in keys:
                cap = self._plain_label(k, "keycapStrong" if strong else "keycap")
                h.addWidget(cap)
            self.hint_box.addWidget(w)            # 먼저 넣고 (부모 없는 위젯을 보이게 하면 작은 창으로 뜬다)
            w.setVisible(not (narrow_hide and not self.wide))
            self._hint_widgets.append((w, narrow_hide))

    def _place_detail(self) -> None:
        """큐의 저장된 요약 칸(detail): 넓으면 미리보기 칸 안, 좁으면 목록 아래."""
        if self.mode == "queue" and self.wide:
            self.pane.body_lay.addWidget(self.detail)
        else:
            self.left_lay.addWidget(self.detail)
        self._update_detail()           # 옮기면 숨겨지므로 보일 것인지 다시 정한다

    def changeEvent(self, e):
        if e.type() == QEvent.ActivationChange and not self.isActiveWindow() and self.isVisible():
            QTimer.singleShot(0, self._hide_if_inactive)
        super().changeEvent(e)

    # ---- 요약 복사 ----------------------------------------------------------------
    def summary_text(self) -> str:
        """복사할 요약 글: 고른 부분이 있으면 그것, 없으면 요약 전체 (모델 표시 줄은 뺀다)."""
        if self.detail.isHidden():
            return ""
        sel = self.detail.selectedText()
        if sel:
            return sel
        q = self._current_queue_item()
        return q.summary_text if q is not None and q.summary_text else ""

    def copy_summary(self) -> bool:
        text = self.summary_text()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status.setText("요약을 복사했습니다")
        return bool(text)

    def _detail_menu(self, pos) -> None:
        q = self._current_queue_item()
        menu = QMenu(self)
        sel = self.detail.selectedText()
        if sel:
            menu.addAction("고른 글 복사\tCtrl+C").triggered.connect(lambda: self.copy_summary())
        if q is not None and q.summary_text:
            menu.addAction("요약 전체 복사").triggered.connect(
                lambda: (QGuiApplication.clipboard().setText(q.summary_text), self.status.setText("요약을 복사했습니다")))
        if menu.isEmpty():
            return
        self._menu_open = True
        try:
            menu.exec(self.detail.mapToGlobal(pos))
        finally:
            self._menu_open = False
            self.activateWindow()
            self.edit.setFocus()

    def _hide_if_inactive(self):
        if self.chips.menu_open or self._menu_open:
            return                         # 프로젝트 칩 메뉴가 떠 있는 동안은 숨기지 않는다
        if not self.isActiveWindow():
            self.hide()

    def _on_changed(self, text: str) -> None:
        self._pending = text
        self.chips.sync_from_text(text)
        self._timer.start()

    def set_results(self, hits: list[Hit], status: str) -> None:
        self._apply_mode()
        was_queue = self.mode == "queue"
        self.mode = "search"
        self.detail.hide()
        if was_queue:
            self._set_hints()
        self._place_detail()
        self.list.clear()
        for h in hits:
            it = QListWidgetItem()
            it.setData(ROLE_KIND, K_HIT)
            it.setData(ROLE_HIT, h)
            it.setData(ROLE_IDX, 0)
            self.list.addItem(it)
        if hits:
            self.list.setCurrentRow(0)
        self.delegate.current_row = self.list.currentRow()
        self.status.setText(status)
        self._refresh_preview()

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
        self._apply_mode()
        old_row = self.list.currentRow()
        was_search = self.mode != "queue"
        self.mode = "queue"
        self._queue = result
        self.delegate.now = now
        if was_search:
            self._set_hints()
        self._place_detail()
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
        self.delegate.current_row = self.list.currentRow()
        self.status.setText(status)
        self._update_detail()
        self._refresh_preview()

    def _update_detail(self) -> None:
        """고른 일의 요약 칸. 저장본만 보여 준다(AI 호출 없음)."""
        if self.mode != "queue":
            self.detail.hide()
            return
        q = self._current_queue_item()
        if q is None:
            self.detail.hide()
            return
        if q.id in self.delegate.ask_state:
            text = self.delegate.ask_state[q.id]
        elif q.summary_text:
            text = q.summary_text
            if q.summary_stale:
                text += "\n(요약 이후 새 흔적 있음, F2로 새로)" if self.ask_enabled else "\n(요약 이후 새 흔적 있음)"
            if q.summary_model:
                text += f"\n({q.summary_model})"
        elif self.ask_enabled:
            text = "F2: 어디까지 했지? (요약)"
        else:
            self.detail.hide()            # 요약 AI 끔: F2 안내를 보이지 않는다
            return
        if self.detail.text() != text:        # 같은 글이면 그대로 둔다 (다시 넣으면 끌어서 고른 부분이 풀린다)
            self.detail.setText(text)
        self.detail.show()

    def set_ask_enabled(self, enabled: bool) -> None:
        """요약 AI를 끄면 큐의 F2 안내 글자를 숨긴다."""
        self.ask_enabled = bool(enabled)
        if self.mode == "queue":
            self._set_hints()
            self._update_detail()

    def set_ask_state(self, item_id: str, text: str | None) -> None:
        """요약 중, 실패 표시. None이면 지움."""
        if text is None:
            self.delegate.ask_state.pop(item_id, None)
        else:
            self.delegate.ask_state[item_id] = text
        self.list.doItemsLayout()
        self.list.viewport().update()
        self._update_detail()

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
        acts = [("열기\tEnter", "open")] + ([("요약\tF2", "summary")] if self.ask_enabled else []) + \
               [("대화 복사\tShift+Enter", "copy_conv")]
        acts += [("다시 열기\tF4", "reopen")] if q.closed_kind else [("완료\tF4", "done"), ("버림\tShift+F4", "drop")]
        for label, kind in acts:
            menu.addAction(label).triggered.connect(lambda _=False, k=kind: self.action.emit(k, q, 0))
        menu.exec(self.list.viewport().mapToGlobal(pos))
        self.edit.setFocus()

    # ---- 미리보기 ----------------------------------------------------------
    def _on_row_changed(self, row: int) -> None:
        self.delegate.current_row = row
        if not self.delegate.compact:
            self.list.doItemsLayout()         # 좁을 때: 고른 줄만 두 줄
        self.list.viewport().update()
        self._update_detail()
        if self.wide:
            self._pv_timer.start()

    def _refresh_preview(self) -> None:
        """넓을 때만 오른쪽 칸을 다시 채운다."""
        self._pv_timer.stop()
        if not self.wide:
            return
        pane = self.pane
        pane.clear_body()
        it = self.list.currentItem()
        kind = it.data(ROLE_KIND) if it else None
        if kind == K_HIT:
            self._fill_hit(it.data(ROLE_HIT), int(it.data(ROLE_IDX) or 0))
        elif kind in (K_FOCUS, K_ROW):
            q: QueueItem = it.data(ROLE_HIT)
            when = datetime.fromtimestamp(q.trace_ts).strftime("%Y-%m-%d %H:%M")
            meta = "  ·  ".join(s for s in (SOURCE_NAME.get(q.source, q.source), q.project, when) if s)
            pane.set_header(q.source, q.title, meta, sub=q.subtitle)
            self._fill_recent(q)
            self._update_detail()
            if not self.detail.isHidden():
                pane.body_lay.addWidget(self.detail)
                self.detail.show()
        else:
            pane.set_header("", "", "")
            if kind is None:
                pane.add_note("결과가 없습니다" if self.mode == "search" else "")

    def _fill_recent(self, q: QueueItem) -> None:
        """큐 미리보기 위쪽: 채팅은 최근 몇 턴, 일지 항목은 최근 기록, 노트는 끝부분 몇 줄. 요약 없이도 내용을 본다."""
        pane = self.pane
        if q.source == "journal":
            ents = sorted(q.journal or [], key=lambda e: (e.day, e.line))[-RECENT_TURNS:]
            lines = []
            for e in ents:
                short, full = one_line(" ".join([e.text, *[c.strip() for c in e.children]]), RECENT_CHARS)
                lines.append((f"{e.day:%m-%d}", short, full))
            pane.add_recent(lines, "최근 일지")
            return
        doc = self.md_cache.get(q.path)
        lines = recent_turns(doc)
        if lines:
            pane.add_recent(lines)
            return
        if q.source == "note":
            try:
                text = Path(q.path).read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                return
            rows = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("---")][-RECENT_TURNS:]
            pane.add_recent([("", *one_line(ln)) for ln in rows], "노트 끝부분")

    def _fill_hit(self, hit: Hit, idx: int) -> None:
        pane = self.pane
        total = hit.match_total or len(hit.matches)
        idx = min(idx, len(hit.matches) - 1) if hit.matches else 0
        when = hit.updated.astimezone().strftime("%Y-%m-%d %H:%M") if hit.updated else ""
        meta = "  ·  ".join(s for s in (SOURCE_NAME.get(hit.source, hit.source), hit.project, when) if s)
        index = f"맞은 메시지 {idx + 1} / {total}" + ("    ← →" if total > 1 else "") if hit.matches else ""
        pane.set_header(hit.source, hit.title, meta, index)
        if hit.status == "missing":
            pane.add_note("원본 없음")
            return
        m = hit.matches[idx] if hit.matches else None
        doc = self.md_cache.get(hit.path)
        ctx = pick_context(doc, m.ordinal) if (doc is not None and m is not None) else None
        if ctx is None:
            if m is not None:                 # md 형식이 아닌 원본(노트 등): 목록의 미리보기 한 줄만
                pane.add_block(True, "", m.preview, m.highlights)
            else:
                pane.add_note("맞은 메시지가 없습니다")
            return
        prev, cur, nxt = ctx
        regs = match_regs(hit)
        if prev:
            text, _ = crop(prev.text, [], CTX_CHARS)
            pane.add_block(False, ROLE_NAME.get(prev.role, prev.role), text, [])
        spans = find_spans(cur.text, regs) if regs else []
        text, spans = crop(cur.text, spans, HIT_CHARS)
        pane.add_block(True, ROLE_NAME.get(cur.role, cur.role), text, spans)
        if nxt:
            text, _ = crop(nxt.text, [], CTX_CHARS)
            pane.add_block(False, ROLE_NAME.get(nxt.role, nxt.role), text, [])

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
        self._refresh_preview()

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
