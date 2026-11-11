"""테마 값 (theme.py). 색 값은 사용자 시안(2026-11-10) 그대로인지 확인한다."""
import os

import pytest

from app import settings as S


@pytest.fixture
def T(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    qtw = pytest.importorskip("PySide6.QtWidgets")
    qtw.QApplication.instance() or qtw.QApplication([])
    from app import theme
    return theme


def test_names_match_settings(T):
    assert set(T.ACCENT) == set(S.THEME_ACCENTS) == set(S.THEME_ACCENT_LABEL)
    assert set(S.THEME_MODES) == set(S.THEME_MODE_LABEL) == {"light", "dark", "system"}
    assert set(T.BASE["light"]) == set(T.BASE["dark"])


def test_spec_colors(T):
    light, dark = T.make("light"), T.make("dark")
    assert (light.bg.name(), light.sidebar.name(), light.line.name(), light.text.name(), light.sub.name(),
            light.input_border.name(), light.button.name(), light.nav_sel.name(), light.placeholder.name()) == \
        ("#ffffff", "#f7f7f5", "#ededea", "#1f1f1d", "#6b6b67", "#d9d9d5", "#f2f2ef", "#eaeae6", "#73736f")
    assert (dark.bg.name(), dark.sidebar.name(), dark.line.name(), dark.text.name(), dark.sub.name(),
            dark.input_bg.name(), dark.input_border.name(), dark.button.name(), dark.nav_sel.name(),
            dark.placeholder.name()) == \
        ("#1e1e1d", "#191918", "#2c2c2a", "#ecece8", "#a1a19c", "#262625", "#3a3a37", "#2a2a28", "#2c2c2a", "#8c8c87")
    assert dark.bg.name() != "#000000"
    expect = {"ink_blue": ("#2f5d8c", "#ffffff", "#8fb3da", "#0f1b2a"),
              "deep_teal": ("#1e6f6b", "#ffffff", "#7cc6c0", "#0b201f"),
              "sage_green": ("#4a6b4f", "#ffffff", "#a3c4a6", "#142016"),
              "rust": ("#9a4a2e", "#ffffff", "#e0a487", "#2a140b")}
    for acc, (la, lo, da, do) in expect.items():
        lt, dk = T.make("light", acc), T.make("dark", acc)
        assert (lt.accent.name(), lt.on_accent.name(), dk.accent.name(), dk.on_accent.name()) == (la, lo, da, do)


def test_system_mode_and_bad_config(T):
    assert T.make("system", dark=True).dark and not T.make("system", dark=False).dark
    t = T.from_config({"theme_mode": "neon", "theme_accent": 3}, dark=False)
    assert (t.mode, t.accent_key, t.dark) == ("system", "ink_blue", False)
    assert S.field_error("theme_mode", "neon") and not S.field_error("theme_mode", "dark")
    assert S.field_error("theme_accent", "red") and not S.field_error("theme_accent", "rust")


def test_badges_cover_sources_and_group_by_company(T):
    from app.window import BADGE
    assert set(BADGE) == set(T.BADGE_STYLE)
    for dark in (False, True):
        t = T.make("dark" if dark else "light")
        fill, edge, _ = T.badge_colors(t, "claude-ai")
        assert fill.name() == "#d97757" and edge is None
        fill, edge, _ = T.badge_colors(t, "claude-code")
        assert fill is None and edge.name() == "#d97757"
        fill, edge, _ = T.badge_colors(t, "chatgpt")
        assert fill.name() == "#74aa9c"
        fill, edge, _ = T.badge_colors(t, "codex")
        assert fill is None and edge.name() == "#74aa9c"
        assert T.badge_colors(t, "unknown")[0] == t.button


def test_stylesheets_use_only_theme_values(T):
    import re
    for mode in ("light", "dark"):
        for acc in S.THEME_ACCENTS:
            t = T.make(mode, acc)
            allowed = {getattr(t, k).name() for k in (*T.BASE["light"], "accent", "on_accent")}
            allowed |= {c.name() for c in T.derived(t).values()}      # 섞어 만든 색(옅은 강조색)은 허용
            for qss in (T.dialog_qss(t), T.search_qss(t)):
                used = {c.lower() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", qss)}
                assert used <= allowed, used - allowed


def test_search_window_set_theme(T):
    from app.window import SearchWindow
    w = SearchWindow(T.make("light"))
    w.set_theme(T.make("dark", "deep_teal"))
    assert w.t.dark and "#7cc6c0" in w.styleSheet().lower() and w.delegate.t is w.t
    w.close()


def test_accent_soft_is_a_blend_of_accent_and_bg(T):
    light, dark = T.make("light", "ink_blue"), T.make("dark", "ink_blue")
    for t, a in ((light, 0.07), (dark, 0.11)):
        soft = T.accent_soft(t)
        for ch in ("red", "green", "blue"):
            lo, hi = sorted((getattr(t.bg, ch)(), getattr(t.accent, ch)()))
            assert lo <= getattr(soft, ch)() <= hi
            assert abs(getattr(soft, ch)() - (getattr(t.accent, ch)() * a + getattr(t.bg, ch)() * (1 - a))) <= 1
        assert T.accent_badge(t) != soft and T.accent_badge(t).name() != t.accent.name()
    assert T.icon("search", light.sub, 16).availableSizes() and T.icon("info", light.sub, 14).availableSizes()