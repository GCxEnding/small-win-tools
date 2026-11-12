"""화면 색과 스타일. 설정 창, 시작 안내, 검색 창이 같이 쓴다.

색 값은 이 파일에만 둔다. 다른 파일은 Theme 속성(t.text, t.accent ...)이나 여기 함수만 쓴다.
모드와 강조색 이름, 화면 글자는 settings.py(THEME_MODES, THEME_ACCENTS)에 있다.

색 규칙
- 글자색은 세 단계: text(본문), sub(설명, 단위), placeholder. 예외로 저장을 막는 오류만 error(빨강).
- 강조색(accent)은 저장 버튼, 텍스트 링크, 초점 받은 입력칸 테두리에만 쓴다.
- 출처 배지만 서비스 고유색(BRAND)을 쓴다. 같은 회사는 같은 색, 칠하는 방식으로 종류를 나눈다.
"""
from __future__ import annotations

import ctypes
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QProxyStyle, QStyle
from PySide6.QtSvg import QSvgRenderer

from . import settings as S

# ---- 색 값 --------------------------------------------------------------------
BASE = {
    "light": {"bg": "#FFFFFF", "sidebar": "#F7F7F5", "line": "#EDEDEA", "text": "#1F1F1D", "sub": "#6B6B67",
              "placeholder": "#73736F", "input_bg": "#FFFFFF", "input_border": "#D9D9D5", "button": "#F2F2EF",
              "nav_sel": "#EAEAE6", "error": "#C5221F", "mark_bg": "#FFF1A8"},
    "dark": {"bg": "#1E1E1D", "sidebar": "#191918", "line": "#2C2C2A", "text": "#ECECE8", "sub": "#A1A19C",
             "placeholder": "#8C8C87", "input_bg": "#262625", "input_border": "#3A3A37", "button": "#2A2A28",
             "nav_sel": "#2C2C2A", "error": "#F28B82", "mark_bg": "#6B5B16"},
}
# 강조색: 모드별 (강조색, 강조색 위 글자색)
ACCENT = {
    "ink_blue": {"light": ("#2F5D8C", "#FFFFFF"), "dark": ("#8FB3DA", "#0F1B2A")},
    "deep_teal": {"light": ("#1E6F6B", "#FFFFFF"), "dark": ("#7CC6C0", "#0B201F")},
    "sage_green": {"light": ("#4A6B4F", "#FFFFFF"), "dark": ("#A3C4A6", "#142016")},
    "rust": {"light": ("#9A4A2E", "#FFFFFF"), "dark": ("#E0A487", "#2A140B")},
}
# 출처 배지: 서비스 고유색과 그 위 글자색
BRAND = {"claude": ("#D97757", "#FFFFFF"), "gpt": ("#74AA9C", "#10201C")}
# 출처 -> (회사, 칠하기). fill: 웹 채팅, outline: 코드 도구, tint: claude.ai 프로젝트/메모리, neutral: 내 문서
BADGE_STYLE = {
    "claude-ai": ("claude", "fill"), "claude-ai-project": ("claude", "tint"), "claude-ai-memory": ("claude", "tint"),
    "claude-code": ("claude", "outline"), "chatgpt": ("gpt", "fill"), "codex": ("gpt", "outline"),
    "note": (None, "neutral"), "journal": (None, "neutral"),
}
TINT_ALPHA = 0.24
# 강조색을 옅게 깐 바탕 (설정 찾기 칸, 탭 맞은 수 배지). 새 색 값이 아니라 강조색과 바탕색의 섞음이다.
ACCENT_SOFT_ALPHA = {"light": 0.07, "dark": 0.11}
ACCENT_BADGE_ALPHA = {"light": 0.14, "dark": 0.2}
MONO_FONTS = '"Consolas", "D2Coding", "Malgun Gothic", monospace'

# 단색 선 아이콘 (24x24, stroke만). 색은 그릴 때 정한다.
_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
ICONS = {
    "general": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "collect": '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14"/>',
    "ask": '<path d="M5 7h14M5 12h14M5 17h9"/>',
    "advanced": '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6'
                'M16.8 16.8l1.6 1.6M5.6 18.4l1.6-1.6M16.8 7.2l1.6-1.6"/>',
}
ICONS["settings"] = ICONS["advanced"]
ICONS["search"] = '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>'
ICONS["info"] = ('<g stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/></g>'
                 '<path d="M12 7.4v.4" stroke-width="2.6"/>')     # 작게 그려도 잘 보이게 굵게
# 스타일시트 url()로 쓰는 작은 그림 (콤보 화살표, 체크 표시). 색을 넣어 임시 폴더에 파일로 쓴다.
_ASSETS = {
    "chevron": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12" fill="none" stroke="{a}" '
               'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5 6 7.5 9 4.5"/></svg>',
    "check": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect x="0.5" y="0.5" width="15" '
             'height="15" rx="3.5" fill="{a}"/><path d="M4.2 8.3 6.8 10.8 11.8 5.4" fill="none" stroke="{b}" '
             'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
}


@dataclass(frozen=True)
class Theme:
    mode: str              # 설정값 (light, dark, system)
    accent_key: str
    dark: bool             # 실제로 그리는 모드
    bg: QColor
    sidebar: QColor
    line: QColor
    text: QColor
    sub: QColor
    placeholder: QColor
    input_bg: QColor
    input_border: QColor
    button: QColor
    nav_sel: QColor
    error: QColor
    mark_bg: QColor        # 검색 결과의 맞은 글자 바탕
    accent: QColor
    on_accent: QColor

    # 검색 창이 쓰던 이름
    @property
    def border(self) -> QColor:
        return self.input_border

    @property
    def sel(self) -> QColor:
        return self.nav_sel

    @property
    def warn(self) -> QColor:
        return self.error

    def hex(self, name: str) -> str:
        return getattr(self, name).name()


def system_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


def make(mode: str = "system", accent: str = "ink_blue", dark: bool | None = None) -> Theme:
    """dark: 시스템 모드일 때 시스템이 다크인지 (None이면 지금 Windows 설정을 읽음)."""
    mode = mode if mode in S.THEME_MODES else "system"
    accent = accent if accent in S.THEME_ACCENTS else "ink_blue"
    if mode == "system":
        is_dark = system_dark() if dark is None else bool(dark)
    else:
        is_dark = mode == "dark"
    key = "dark" if is_dark else "light"
    acc, on_acc = ACCENT[accent][key]
    return Theme(mode=mode, accent_key=accent, dark=is_dark, accent=QColor(acc), on_accent=QColor(on_acc),
                 **{k: QColor(v) for k, v in BASE[key].items()})


def from_config(cfg: dict, dark: bool | None = None) -> Theme:
    mode, accent = S.read_theme(cfg)
    return make(mode, accent, dark)


def accent_color(accent: str, dark: bool) -> QColor:
    return QColor(ACCENT[accent]["dark" if dark else "light"][0])


# ---- 배지 ---------------------------------------------------------------------
def _blend(fg: QColor, bg: QColor, a: float) -> QColor:
    return QColor(round(fg.red() * a + bg.red() * (1 - a)), round(fg.green() * a + bg.green() * (1 - a)),
                  round(fg.blue() * a + bg.blue() * (1 - a)))


def accent_soft(t: Theme) -> QColor:
    """강조색을 옅게 깐 바탕 (설정 찾기 칸). 라이트 약 7%, 다크 약 11%."""
    return _blend(t.accent, t.bg, ACCENT_SOFT_ALPHA["dark" if t.dark else "light"])


def accent_badge(t: Theme) -> QColor:
    """사이드바 탭의 맞은 수 배지 바탕."""
    return _blend(t.accent, t.bg, ACCENT_BADGE_ALPHA["dark" if t.dark else "light"])


def derived(t: Theme) -> dict[str, QColor]:
    """테마 색을 섞어 만든 색 전부 (스타일시트에 들어갈 수 있는 값을 검사하는 테스트용)."""
    return {"accent_soft": accent_soft(t), "accent_badge": accent_badge(t)}


def badge_colors(t: Theme, source: str) -> tuple[QColor | None, QColor | None, QColor]:
    """(바탕 또는 None, 테두리 또는 None, 글자색)."""
    brand, style = BADGE_STYLE.get(source, (None, "neutral"))
    if brand is None:
        return t.button, t.input_border, t.sub
    color, on = (QColor(c) for c in BRAND[brand])
    if style == "fill":
        return color, None, on
    if style == "outline":
        return None, color, t.text
    return _blend(color, t.bg, TINT_ALPHA), None, t.text


# ---- 아이콘 ---------------------------------------------------------------------
def icon(name: str, color: QColor, size: int = 16) -> QIcon:
    data = QByteArray(_SVG.format(c=color.name(), body=ICONS[name]).encode("utf-8"))
    out = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        QSvgRenderer(data).render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        out.addPixmap(pm)
    return out


def swatch(color: QColor, size: int = 14) -> QIcon:
    """강조색 고르기 칸의 동그라미."""
    out = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        out.addPixmap(pm)
    return out


# ---- 팔레트, 스타일시트 -----------------------------------------------------------
def palette(t: Theme) -> QPalette:
    pal = QPalette()
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        dis = group == QPalette.Disabled
        pal.setColor(group, QPalette.Window, t.bg)
        pal.setColor(group, QPalette.WindowText, t.placeholder if dis else t.text)
        pal.setColor(group, QPalette.Base, t.input_bg)
        pal.setColor(group, QPalette.AlternateBase, t.sidebar)
        pal.setColor(group, QPalette.Text, t.placeholder if dis else t.text)
        pal.setColor(group, QPalette.PlaceholderText, t.placeholder)
        pal.setColor(group, QPalette.Button, t.button)
        pal.setColor(group, QPalette.ButtonText, t.placeholder if dis else t.text)
        pal.setColor(group, QPalette.Highlight, t.nav_sel)
        pal.setColor(group, QPalette.HighlightedText, t.text)
        pal.setColor(group, QPalette.ToolTipBase, t.input_bg)
        pal.setColor(group, QPalette.ToolTipText, t.text)
        pal.setColor(group, QPalette.Link, t.accent)
        pal.setColor(group, QPalette.Light, t.input_bg)
        pal.setColor(group, QPalette.Midlight, t.line)
        pal.setColor(group, QPalette.Mid, t.input_border)
        pal.setColor(group, QPalette.Dark, t.input_border)
        pal.setColor(group, QPalette.Shadow, t.input_border)
        pal.setColor(group, QPalette.BrightText, t.error)
    return pal


def apply_app(app, t: Theme) -> None:
    """앱 전체(트레이 메뉴, 메시지 상자 포함)의 기본 팔레트."""
    app.setPalette(palette(t))


class BusyNote:
    """오래 걸리는 일 동안 커서 근처 모니터 가운데에 작은 '여는 중…' 상자와 모래시계 커서를 보인다.
    만들 때 바로 그려 두고(이벤트 루프가 막혀도 보이게), done()에서 닫는다."""

    def __init__(self, t: Theme, text: str):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication, QLabel
        self.label = QLabel(text)
        self.label.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.label.setAttribute(Qt.WA_ShowWithoutActivating)
        self.label.setStyleSheet(f"QLabel {{ background:{t.bg.name()}; color:{t.text.name()}; "
                                 f"border:1px solid {t.input_border.name()}; border-radius:8px; "
                                 f"padding:14px 26px; font-size:11pt; }}")
        self.label.adjustSize()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.label.move(g.center() - QPoint(self.label.width() // 2, self.label.height() // 2))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.label.show()
        self.label.repaint()
        QApplication.processEvents()
        self._open = True

    def done(self) -> None:
        from PySide6.QtWidgets import QApplication
        if self._open:
            self._open = False
            QApplication.restoreOverrideCursor()
            self.label.hide()
            self.label.deleteLater()


def show_without_flash(widget) -> None:
    """처음 그리기 전 빈 창(Windows가 칠한 회색 바탕)이 잠깐 보이지 않게, 투명하게 띄워 다 그린 뒤 보인다."""
    from PySide6.QtCore import QTimer
    widget.setWindowOpacity(0.0)
    widget.show()
    widget.repaint()                      # 첫 그리기를 지금 끝낸다

    def reveal():
        try:
            widget.setWindowOpacity(1.0)
        except RuntimeError:              # 그새 창이 지워짐
            pass
    QTimer.singleShot(0, reveal)


TIP_DELAY_MS = 300        # 툴팁이 뜨기까지 (Qt 기본 700ms)


class FastTipStyle(QProxyStyle):
    """툴팁을 마우스를 올리자마자(0.2초) 띄운다. 나머지는 기본 스타일 그대로."""

    def styleHint(self, hint, option=None, widget=None, ret=None):
        if hint == QStyle.SH_ToolTip_WakeUpDelay:
            return TIP_DELAY_MS
        if hint == QStyle.SH_ToolTip_FallAsleepDelay:
            return 0
        return super().styleHint(hint, option, widget, ret)


def install_fast_tips(app) -> None:
    """앱 스타일을 FastTipStyle로 감싼다. 팔레트를 되돌리므로 apply_app보다 먼저 부른다."""
    base = app.style().name() if hasattr(app.style(), "name") else ""
    app.setStyle(FastTipStyle(base) if base else FastTipStyle())


def _scrollbar_qss(c: dict) -> str:
    return f"""
        QScrollBar:vertical {{ background:transparent; width:10px; margin:2px 2px 2px 0; }}
        QScrollBar::handle:vertical {{ background:{c['input_border']}; border-radius:3px; min-height:32px; }}
        QScrollBar:horizontal {{ background:transparent; height:10px; margin:0 2px 2px 2px; }}
        QScrollBar::handle:horizontal {{ background:{c['input_border']}; border-radius:3px; min-width:32px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background:none; }}
        QToolTip {{ background:{c['input_bg']}; color:{c['text']}; border:1px solid {c['input_border']}; padding:4px; }}
    """


def _asset(name: str, a: str, b: str = "") -> str:
    """색을 넣은 SVG 파일 경로 (스타일시트 url()용, / 구분자)."""
    folder = Path(tempfile.gettempdir()) / "thought-searcher-ui"
    p = folder / f"{name}-{a.lstrip('#')}{b.lstrip('#')}.svg"
    if not p.exists():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            p.write_text(_ASSETS[name].format(a=a, b=b), encoding="utf-8")
        except OSError:
            return ""
    return p.as_posix()


def _c(t: Theme) -> dict:
    c = {k: getattr(t, k).name() for k in (*BASE["light"], "accent", "on_accent")}
    c.update({k: v.name() for k, v in derived(t).items()})
    return c


def _keycap_qss(c: dict) -> str:
    """키캡: 작은 글자, 둥근 테두리, 아래쪽이 조금 두꺼운 선."""
    return f"""
        QLabel#keycap {{ background:{c['input_bg']}; color:{c['sub']}; border:1px solid {c['input_border']};
                         border-bottom:2px solid {c['input_border']}; border-radius:4px; padding:0 5px;
                         font-size:8.5pt; }}
        QLabel#keycapStrong {{ background:{c['input_bg']}; color:{c['text']}; border:1px solid {c['input_border']};
                               border-bottom:2px solid {c['input_border']}; border-radius:4px; padding:0 5px;
                               font-size:8.5pt; font-weight:700; }}
    """


def dialog_qss(t: Theme) -> str:
    """설정 창, 시작 안내."""
    c = _c(t)
    return f"""
        QDialog {{ background:{c['bg']}; }}
        QLabel {{ color:{c['text']}; }}
        QLabel#desc, QLabel#unit, QLabel#caption {{ color:{c['sub']}; font-size:9.4pt; }}
        QLabel#sideCaption {{ color:{c['sub']}; font-size:9pt; padding:0 12px 6px 12px; }}
        QLabel#name {{ font-size:10.5pt; }}
        QLabel#rowName {{ font-size:10.5pt; font-weight:700; }}
        QFrame#searchHead {{ background:{c['bg']}; border:none; border-bottom:1px solid {c['line']}; }}
        QLineEdit#hotkey[caps="true"] {{ color:transparent; selection-color:transparent;
                                         selection-background-color:transparent; }}
        QLabel#pageTitle {{ font-size:16.5pt; font-weight:700; }}
        QLabel#pageDesc {{ color:{c['sub']}; font-size:9.75pt; }}
        QLabel#sectionTitle {{ font-size:11.25pt; font-weight:700; }}
        QLabel[tone="error"] {{ color:{c['error']}; }}
        QLabel#banner {{ color:{c['error']}; font-weight:700; padding:10px 24px; background:{c['bg']};
                         border-bottom:1px solid {c['line']}; }}
        QFrame#hline {{ background:{c['line']}; border:none; }}
        QFrame#sidebar {{ background:{c['sidebar']}; border:none; border-right:1px solid {c['line']}; }}
        QFrame#footer {{ background:{c['bg']}; border:none; border-top:1px solid {c['line']}; }}
        QWidget#content {{ background:{c['bg']}; }}
        QScrollArea {{ background:{c['bg']}; border:none; }}

        QPushButton {{ background:{c['button']}; color:{c['text']}; border:1px solid {c['input_border']};
                       border-radius:6px; padding:6px 14px; font-size:10pt; }}
        QPushButton:hover {{ background:{c['nav_sel']}; }}
        QPushButton:disabled {{ color:{c['placeholder']}; }}
        QPushButton#primary {{ background:{c['accent']}; color:{c['on_accent']}; border:1px solid {c['accent']};
                               font-weight:700; padding:7px 18px; }}
        QPushButton#primary:disabled {{ background:{c['button']}; color:{c['placeholder']};
                                        border-color:{c['input_border']}; }}
        QPushButton#secondary {{ padding:7px 18px; }}
        QPushButton#link {{ background:transparent; border:none; color:{c['accent']}; padding:2px 4px; }}
        QPushButton#link:hover {{ text-decoration:underline; }}
        QPushButton#nav {{ background:transparent; border:none; border-left:3px solid transparent; border-radius:6px;
                           border-top-left-radius:2px; border-bottom-left-radius:2px; text-align:left;
                           padding:9px 12px 9px 9px; font-size:10.5pt; color:{c['text']}; }}
        QPushButton#nav:hover {{ background:{c['button']}; }}
        QPushButton#nav:checked {{ background:{c['nav_sel']}; font-weight:700; border-left-color:{c['accent']}; }}
        QPushButton#nav[dim="true"] {{ color:{c['placeholder']}; }}
        QLabel#navBadge {{ background:{c['accent_badge']}; color:{c['accent']}; border-radius:8px; padding:0 6px;
                           font-size:8.5pt; font-weight:700; }}
        QPushButton#chip {{ background:transparent; border:1px solid {c['input_border']}; border-radius:6px;
                            padding:6px 12px; }}
        QPushButton#chip:hover {{ background:{c['button']}; }}
        QPushButton#chip:checked {{ background:{c['nav_sel']}; font-weight:700; }}
        /* 붙은 버튼(세그먼트): 위치는 segpos 속성 (first, mid, last) */
        QPushButton#seg {{ background:transparent; border:1px solid {c['input_border']}; border-radius:0;
                           padding:6px 14px; }}
        QPushButton#seg:hover {{ background:{c['button']}; }}
        QPushButton#seg:checked {{ background:{c['nav_sel']}; font-weight:700; }}
        QPushButton#seg[segpos="first"] {{ border-top-left-radius:6px; border-bottom-left-radius:6px; }}
        QPushButton#seg[segpos="mid"] {{ border-left-width:0; }}
        QPushButton#seg[segpos="last"] {{ border-left-width:0; border-top-right-radius:6px;
                                       border-bottom-right-radius:6px; }}
        QToolButton#info {{ background:transparent; border:none; border-radius:8px; padding:1px; }}
        QToolButton#info:hover {{ background:{c['button']}; }}

        /* 설정 찾기 칸: 강조색 테두리 1.5px + 옅은 강조색 바탕 */
        QFrame#searchBox {{ background:{c['accent_soft']}; border:1.5px solid {c['accent']}; border-radius:9px; }}
        QFrame#searchBox QLineEdit {{ background:transparent; border:none; padding:6px 4px; font-size:11pt; }}
        QLabel#searchCount {{ color:{c['accent']}; font-weight:700; font-size:9.4pt; }}
        QLabel#changedDot {{ background:{c['accent']}; border-radius:4px; }}
        QLabel#changedText {{ color:{c['text']}; font-size:9.75pt; }}

        /* 카드: 섹션의 줄이 들어가는 상자 */
        QFrame#card {{ background:{c['sidebar']}; border:1px solid {c['line']}; border-radius:9px; }}

        QLineEdit, QPlainTextEdit, QComboBox, QListWidget {{
            background:{c['input_bg']}; color:{c['text']}; border:1px solid {c['input_border']};
            border-radius:6px; padding:6px 10px; font-size:10.5pt;
            selection-background-color:{c['nav_sel']}; selection-color:{c['text']}; }}
        QPlainTextEdit, QListWidget {{ padding:6px 6px; }}
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus {{ border-color:{c['accent']}; }}
        QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{ color:{c['placeholder']}; }}
        QLineEdit#mono {{ font-family:{MONO_FONTS}; }}
        QComboBox::drop-down {{ border:none; background:transparent; width:26px; }}
        QComboBox::down-arrow {{ image:url("{_asset('chevron', c['sub'])}"); width:12px; height:12px; }}
        QComboBox QAbstractItemView {{ background:{c['input_bg']}; color:{c['text']}; outline:0;
            border:1px solid {c['input_border']}; selection-background-color:{c['nav_sel']};
            selection-color:{c['text']}; }}
        QListWidget::item {{ padding:3px 4px; border-radius:4px; }}
        QListWidget::item:selected {{ background:{c['nav_sel']}; color:{c['text']}; }}

        QFrame#numBox {{ background:{c['input_bg']}; border:1px solid {c['input_border']}; border-radius:6px; }}
        QFrame#numBox[focus="true"] {{ border-color:{c['accent']}; }}
        /* 숫자 칸: border, padding, ::up-button 규칙을 주면 Qt가 안쪽 편집칸을 1px로 줄인다. 틀은 setFrame(False) */
        QFrame#numBox QAbstractSpinBox {{ background:transparent; color:{c['text']}; font-size:10.5pt;
            selection-background-color:{c['nav_sel']}; selection-color:{c['text']}; }}
        QFrame#numBox QLineEdit, QComboBox QLineEdit {{ background:transparent; border:none; padding:0;
            border-radius:0; }}

        QCheckBox, QRadioButton {{ color:{c['text']}; spacing:6px; font-size:10.5pt; background:transparent; }}
        QCheckBox:disabled, QRadioButton:disabled {{ color:{c['placeholder']}; }}
        QCheckBox::indicator, QRadioButton::indicator {{ width:14px; height:14px; background:{c['input_bg']};
            border:1px solid {c['sub']}; }}
        QCheckBox::indicator {{ border-radius:4px; }}
        QCheckBox::indicator:checked {{ border:none; width:16px; height:16px;
            image:url("{_asset('check', c['text'], c['bg'])}"); }}
        QRadioButton::indicator {{ border-radius:8px; }}
        QRadioButton::indicator:checked {{ border:4px solid {c['text']}; width:8px; height:8px; }}
        QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color:{c['input_border']}; }}
    """ + _keycap_qss(c) + _scrollbar_qss(c)


def search_qss(t: Theme) -> str:
    c = _c(t)
    return f"""
        QWidget#root {{ background:{c['bg']}; border:1px solid {c['input_border']}; }}
        QFrame#head {{ background:{c['bg']}; border:none; border-bottom:1px solid {c['line']}; }}
        QLineEdit#query {{ background:transparent; color:{c['text']}; border:none; padding:6px 4px;
                           font-size:15pt; selection-background-color:{c['nav_sel']}; selection-color:{c['text']}; }}
        QLabel#count {{ color:{c['sub']}; font-size:9.4pt; padding:0 4px; }}
        /* 검색 옵션 칩: 꺼짐은 line 테두리 + 본문색, 켜짐은 옅은 강조색 바탕 + 강조색 테두리, 굵게 */
        QFrame#chips {{ background:transparent; border:none; }}
        QFrame#chips QLabel#chipCaption {{ color:{c['sub']}; font-size:8.5pt; padding:0; }}
        QPushButton#qchip {{ background:transparent; color:{c['text']}; border:1px solid {c['line']};
                             border-radius:11px; padding:2px 10px; font-size:9pt; min-height:18px; }}
        QPushButton#qchip:hover {{ background:{c['button']}; }}
        QPushButton#qchip:checked {{ background:{c['accent_soft']}; border-color:{c['accent']}; font-weight:700; }}
        QPushButton#chipClear {{ background:transparent; border:none; color:{c['accent']}; font-size:9pt;
                                 padding:2px 4px; }}
        QPushButton#chipClear:hover {{ text-decoration:underline; }}
        QFrame#chipSep {{ background:{c['line']}; border:none; }}
        QListWidget {{ background:{c['bg']}; border:none; outline:none; }}
        QLabel {{ color:{c['sub']}; padding:2px 4px; }}
        QLabel#detail {{ color:{c['text']}; background:{c['sidebar']}; border:1px solid {c['line']};
                         border-radius:6px; padding:6px 10px; }}
        /* 나누기 막대: 잡기 쉽게 7px, 가운데에 얇은 선 */
        QSplitter::handle:horizontal {{ background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c['bg']},
            stop:0.4 {c['bg']}, stop:0.4 {c['line']}, stop:0.6 {c['line']}, stop:0.6 {c['bg']}, stop:1 {c['bg']}); }}
        QSplitter::handle:horizontal:hover {{ background:qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c['bg']},
            stop:0.4 {c['bg']}, stop:0.4 {c['input_border']}, stop:0.6 {c['input_border']}, stop:0.6 {c['bg']},
            stop:1 {c['bg']}); }}

        QFrame#preview {{ background:{c['bg']}; border:none; }}
        QScrollArea#previewScroll {{ background:{c['bg']}; border:none; }}
        QWidget#previewBody {{ background:{c['bg']}; }}
        QLabel#pvTitle {{ color:{c['text']}; font-size:12pt; font-weight:700; padding:0; }}
        QLabel#pvMeta, QLabel#pvIndex {{ color:{c['sub']}; font-size:9.4pt; padding:0; }}
        QLabel#pvEmpty {{ color:{c['sub']}; padding:12px 14px; }}
        QFrame#pvHit {{ background:{c['sidebar']}; border:none; border-left:3px solid {c['accent']}; }}
        QFrame#pvCtx {{ background:transparent; border:none; border-left:3px solid transparent; }}
        QFrame#pvHit QLabel, QFrame#pvCtx QLabel {{ padding:0; color:{c['text']}; }}
        QFrame#pvCtx QLabel {{ color:{c['sub']}; }}
        QLabel#pvRole {{ color:{c['sub']}; font-size:8.5pt; padding:0; }}
        /* 큐 미리보기의 최근 대화: 역할은 작은 회색 굵게, 본문은 한 줄 */
        QFrame#pvRecent {{ background:transparent; border:none; border-left:3px solid {c['line']}; }}
        QFrame#pvRecent QLabel {{ padding:0; }}
        QLabel#pvWho {{ color:{c['sub']}; font-size:9pt; font-weight:700; }}
        QLabel#pvLine {{ color:{c['text']}; }}

        QFrame#bottomBar {{ background:{c['sidebar']}; border:none; border-top:1px solid {c['line']}; }}
        QFrame#bottomBar QLabel {{ padding:0; font-size:8.5pt; }}
        QLabel#appName {{ color:{c['sub']}; font-size:9pt; }}
        QLabel#keyAction {{ color:{c['sub']}; }}
        QLabel#keyActionStrong {{ color:{c['text']}; font-weight:700; }}
        QToolButton#gear {{ background:transparent; border:none; border-radius:4px; padding:2px; }}
        QToolButton#gear:hover {{ background:{c['button']}; }}
    """ + _keycap_qss(c).replace("QLabel#keycap", "QFrame#bottomBar QLabel#keycap") + _scrollbar_qss(c)

# ---- Windows 제목 표시줄 -------------------------------------------------------------
_DWMWA_DARK = (20, 19)        # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 20H1 이전은 19)
_DWMWA_CAPTION_COLOR, _DWMWA_TEXT_COLOR = 35, 36     # Windows 11


def _colorref(c: QColor) -> int:
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def style_titlebar(widget, t: Theme) -> None:
    """제목 표시줄을 테마에 맞춘다. Windows 아닌 곳, 오래된 Windows에서는 아무것도 하지 않음."""
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return
    try:
        dwm = ctypes.windll.dwmapi
        hwnd = ctypes.c_void_p(int(widget.winId()))
        on = ctypes.c_int(1 if t.dark else 0)
        for attr in _DWMWA_DARK:
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
        for attr, color in ((_DWMWA_CAPTION_COLOR, t.bg), (_DWMWA_TEXT_COLOR, t.text)):
            v = ctypes.c_uint(_colorref(color))
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
    except (OSError, AttributeError):
        pass

_DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND = 33, 2      # Windows 11


def round_corners(widget) -> bool:
    """창 모서리를 둥글게 (Windows 11). 안 되는 환경(Windows 10, 다른 OS, offscreen)은 사각형 그대로 두고 False."""
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return False
    try:
        hwnd = ctypes.c_void_p(int(widget.winId()))
        v = ctypes.c_int(_DWMWCP_ROUND)
        return ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(v), ctypes.sizeof(v)) == 0
    except (OSError, AttributeError):
        return False
