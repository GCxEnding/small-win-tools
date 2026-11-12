"""검색 창 새 모양 (좁음/넓음 전환, 미리보기 칸, 아래 막대, 나누기 저장). 화면 없이 offscreen."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from conftest import KST, TODAY

from app import mdparse
from app.archive import Archive
from app.index import Index, connect
from app.model import Conversation, Message
from app.redact import Redactor
from app.search import Searcher


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    qtw = pytest.importorskip("PySide6.QtWidgets")
    app = qtw.QApplication.instance() or qtw.QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def hits(tmp_path):
    """합성 대화 하나를 md로 쓰고 색인해 '배포' 검색 결과를 만든다."""
    root = tmp_path / "archive"
    root.mkdir()
    t0 = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
    texts = ["안녕하세요 첫 질문입니다", "서버 배포 순서를 알려 주세요", "먼저 빌드하고 배포 스크립트를 실행합니다",
             "롤백은 어떻게 하나요", "이전 태그로 되돌립니다", "배포 로그는 어디 있나요"]
    msgs = [Message(f"m{i}", "user" if i % 2 == 0 else "assistant", t0 + timedelta(minutes=i), t)
            for i, t in enumerate(texts)]
    conv = Conversation("claude-ai:aaaaaaaa-0000-0000-0000-000000000001", "claude-ai", "배포 질문", "프로젝트A", t0,
                        msgs[-1].created, "", msgs)
    a = Archive(root, KST, Redactor(), today=lambda: TODAY)
    path = a.write(conv).path
    idx = Index(tmp_path / "index.db")
    idx.sync(root)
    conn = connect(idx.db_path)
    out = Searcher(conn).search("배포")
    yield out, path
    conn.close()


def test_pick_context_and_html_helpers(hits):
    from app.window import crop, pick_context, to_html
    found, path = hits
    doc = mdparse.parse_file(path)
    h = found[0]
    ordinal = h.matches[0].ordinal
    prev, cur, nxt = pick_context(doc, ordinal)
    assert cur.ordinal == ordinal and (prev is None or prev.ordinal < ordinal) and (nxt is None or nxt.ordinal > ordinal)
    assert pick_context(doc, 999) is None
    assert to_html("a<b>\nc", [(0, 1)], "#fff") == 'a'.join(['<span style="background-color:#fff">', '</span>']) + "&lt;b&gt;<br>c"
    text, spans = crop("가" * 100 + "나다" + "라" * 100, [(100, 102)], 50)
    assert len(text) <= 52 and text[spans[0][0]:spans[0][1]] == "나다"


def test_narrow_vs_wide_layout(qt, hits):
    from app.window import WIDE_MIN_W, SearchWindow
    found, _ = hits
    w = SearchWindow()
    w.resize(620, 500)
    w.show()
    qt.processEvents()
    w.set_results(found, "1건")
    assert w.wide is False and w.pane.isHidden() and w.delegate.compact is False
    # 좁을 때는 고른 줄만 두 줄
    r0 = w.list.item(0)
    assert w.delegate.second_line(w.list.model().index(0, 0))
    one = w.delegate.sizeHint(_Opt(300), w.list.model().index(0, 0))
    w.delegate.current_row = -1
    assert w.delegate.sizeHint(_Opt(300), w.list.model().index(0, 0)).height() < one.height()
    w.delegate.current_row = 0
    w.resize(980, 500)
    qt.processEvents()
    assert w.wide is True and not w.pane.isHidden() and w.delegate.compact is True
    assert not w.delegate.second_line(w.list.model().index(0, 0))
    assert 980 >= WIDE_MIN_W
    # 키 안내: 좁으면 '대화 복사'를 숨김
    shown = [w._hint_widgets[i][0].isHidden() for i in range(len(w._hint_widgets))]
    assert shown == [False, False, False]
    w.resize(620, 500)
    qt.processEvents()
    assert [wd.isHidden() for wd, _n in w._hint_widgets] == [False, False, True]
    assert r0 is not None
    w.close()


class _Opt:
    class _R:
        def __init__(self, w):
            self._w = w

        def width(self):
            return self._w

    def __init__(self, w):
        self.rect = self._R(w)


def test_wide_preview_shows_matched_message_with_neighbours(qt, hits):
    from PySide6.QtWidgets import QFrame, QLabel
    from app.window import SearchWindow
    found, _ = hits
    w = SearchWindow()
    w.resize(980, 500)
    w.show()
    qt.processEvents()
    w.set_results(found, "1건")
    qt.processEvents()
    assert w.pane.title.text() == "배포 질문"
    assert "claude.ai" in w.pane.meta.text() and "프로젝트A" in w.pane.meta.text()
    total = found[0].match_total
    assert w.pane.index.text().startswith(f"맞은 메시지 1 / {total}")
    hit_blocks = w.pane.body.findChildren(QFrame, "pvHit")
    ctx_blocks = w.pane.body.findChildren(QFrame, "pvCtx")
    assert len(hit_blocks) == 1 and 1 <= len(ctx_blocks) <= 2
    html_text = " ".join(lb.text() for lb in hit_blocks[0].findChildren(QLabel))
    assert "background-color" in html_text and "배포" in html_text
    # ←/→ 로 다른 맞은 메시지로: 미리보기도 따라간다
    if total > 1:
        w._switch(1)
        assert w.pane.index.text().startswith(f"맞은 메시지 2 / {total}")
    w.close()


def test_missing_original_and_non_md_fallback(qt, hits):
    from PySide6.QtWidgets import QLabel
    from app.window import SearchWindow
    found, path = hits
    w = SearchWindow()
    w.resize(980, 500)
    w.show()
    h = found[0]
    h.status = "missing"
    w.set_results([h], "x")
    texts = [lb.text() for lb in w.pane.body.findChildren(QLabel)]
    assert "원본 없음" in texts
    h.status = "ok"
    h.path = path.with_name("없는파일.md")          # 읽을 수 없음: 목록의 미리보기 한 줄로 대신
    w.set_results([h], "x")
    assert any(h.matches[0].preview[:2] in lb.text() for lb in w.pane.body.findChildren(QLabel))
    w.close()


def test_status_label_elides_but_keeps_text(qt):
    from app.window import SearchWindow
    w = SearchWindow()
    long = "⏳ 검색 색인 확인 중   ·   " + "가" * 80
    w.status.setText(long)
    assert w.status.text() == long and w.status.sizeHint().width() <= w.status.MAX_W
    w.close()


def test_split_ratio_saved_with_window_size(qt, tmp_path):
    from app.window import SearchWindow
    p = tmp_path / "ui_state.json"
    p.write_text(json.dumps({"search_window": {"w": 900, "h": 600, "split": 0.3}}), encoding="utf-8")
    w = SearchWindow(state_path=p)
    assert w._split == 0.3 and w.wide is True
    w._split = 0.5
    w.user_resized()
    w.save_state()
    assert json.loads(p.read_text(encoding="utf-8"))["search_window"] == {"w": 900, "h": 600, "split": 0.5}
    w.close()


def test_rounded_corner_call_is_safe_offscreen(qt):
    from app import theme as T
    from app.window import SearchWindow
    w = SearchWindow()
    assert T.round_corners(w) is False          # offscreen / Windows 아님: 그냥 False
    w.close()


def test_queue_wide_shows_saved_summary_in_preview(qt):
    from app.queue import QueueItem, QueueResult
    from app.window import SearchWindow
    w = SearchWindow()
    w.resize(980, 500)
    w.show()
    qt.processEvents()
    q = QueueItem("claude-code:a", "claude-code", "큐 제목", "proj", "C:/x.md", 1, 1_000_000.0, summary="요", summary_text="저장된 요약")
    w.set_queue(QueueResult(focus=[q], days=14), "s", 1_000_100.0)
    qt.processEvents()
    assert w.detail.text().startswith("저장된 요약") and not w.detail.isHidden()
    assert w.pane.isAncestorOf(w.detail) and w.pane.title.text() == "큐 제목"
    w.resize(620, 500)
    qt.processEvents()
    assert w.left.isAncestorOf(w.detail) and not w.detail.isHidden()
    w.close()


# ---- 검색 옵션 칩 ------------------------------------------------------------------
def test_chip_tokens_and_helpers():
    from datetime import date
    from app.window import period_after, project_token
    d = date(2026, 11, 12)
    assert period_after(None, d) is None and period_after(7, d) == date(2026, 11, 5)
    assert period_after(30, d) == date(2026, 10, 13) and period_after("year", d) == date(2026, 1, 1)
    assert project_token("생각 검색기") == "검색기" and project_token("small-win-tools") == "small-win-tools"
    assert project_token("") == ""


def test_chips_append_tokens_and_reset_on_popup(qt):
    from datetime import date
    from app.window import SearchWindow
    w = SearchWindow(projects=lambda: ["프로젝트A", "small-win-tools"])
    got = []
    w.searchRequested.connect(got.append)
    c = w.chips
    c.src_buttons["code"].click()
    c.src_buttons["gpt"].click()
    c.period_buttons[7].click()
    c.project = "small-win-tools"
    today = date(2026, 11, 12)
    assert c.tokens(today) == ["src:code", "src:gpt", "after:2026-11-05", "proj:small-win-tools"]
    assert c.compose("배포 ", today) == "배포 src:code src:gpt after:2026-11-05 proj:small-win-tools"
    assert w.edit.text() == ""                                         # 검색칸에는 글자를 넣지 않음
    assert got and got[-1].startswith("src:code src:gpt after:")       # 누르면 바로 다시 검색 (단어 없이 필터만)
    assert not c.clear_button.isHidden()
    for b in [*c.src_buttons.values(), *c.period_buttons.values(), c.proj_button, c.clear_button]:
        assert b.focusPolicy() == Qt_NoFocus()
    w.popup()
    assert not c.active() and c.tokens(today) == [] and c.clear_button.isHidden()
    assert c.period_buttons[None].isChecked()
    w.hide()
    w.deleteLater()


def test_typed_tokens_light_chips_without_duplicates(qt):
    from datetime import date
    from app.window import SearchWindow
    w = SearchWindow()
    c = w.chips
    w.edit.setText("배포 src:code proj:demo")
    assert c.src_buttons["code"].isChecked() and not c.src_buttons["gpt"].isChecked()
    assert c.proj_button.isChecked() and "demo" in c.proj_button.text()
    assert c.tokens(date(2026, 11, 12)) == []                         # 표시만, 토큰은 더 붙이지 않음
    assert not c.active() and c.clear_button.isHidden()
    w.edit.setText("배포")
    assert not c.src_buttons["code"].isChecked() and not c.proj_button.isChecked()
    w.chips.clear()
    w.deleteLater()


def test_project_names_from_index(tmp_path):
    from app.main import project_names
    idx = Index(tmp_path / "index.db")
    idx.open().close()
    conn = connect(tmp_path / "index.db")
    with conn:
        for cid, src, proj, ts in [("a", "claude-code", "old", 1), ("b", "claude-ai", "new", 9), ("c", "note", "vault/x", 99),
                                   ("d", "codex", "", 50), ("e", "claude-code", "old", 5)]:
            conn.execute("INSERT INTO docs(conv_id, path, title, source, project, updated_ts) VALUES(?,?,?,?,?,?)",
                         (cid, f"C:/{cid}.md", cid, src, proj, ts))
    assert project_names(conn) == ["new", "old"]
    conn.close()


def Qt_NoFocus():
    from PySide6.QtCore import Qt
    return Qt.NoFocus


# ---- 큐 미리보기: 최근 대화 ---------------------------------------------------------
def _md(n_turns, branch=True):
    out = ["---", "id: claude-code:s1", "source: claude-code", "title: t", "format_version: 1", "---", "", "# t", ""]
    k = 0
    for t in range(1, n_turns + 1):
        for role, body in (("user", f"질문 {t} " + "가" * 40), ("assistant", f"**답** {t} `code`")):
            k += 1
            out += [f"<!-- bs:msg {k} {role} 2026-11-09T10:{k:02d}:00+09:00 -->", f"## {role}", "", body, ""]
    if branch:
        out += [f"<!-- bs:msg {k + 1} user 2026-11-08T10:00:00+09:00 branch -->", "## 가지", "", "가지 글", ""]
    return "\n".join(out)


def test_recent_turns_last_five_one_line():
    from app.window import RECENT_CHARS, one_line, recent_turns
    doc = mdparse.parse_text(_md(7))
    got = recent_turns(doc)
    assert len(got) == 10 and got[0][0] == "나" and got[0][1].startswith("질문 3") and got[1][0] == "AI"
    assert len(got[0][1]) == RECENT_CHARS + 1 and got[0][1].endswith("…") and got[0][2].endswith("가")
    assert got[1][1] == "답 3 code"                                  # md 꾸밈 기호는 뺌
    assert all("가지 글" not in full for _r, _s, full in got)
    assert len(recent_turns(mdparse.parse_text(_md(2)))) == 4          # 턴이 적으면 있는 만큼
    assert recent_turns(None) == [] and one_line("a\n\n  b") == ("a b", "a b")


def test_queue_preview_shows_recent_turns(qt, tmp_path):
    from app.queue import QueueItem, QueueResult
    from app.window import SearchWindow
    p = tmp_path / "c.md"
    p.write_text(_md(6), encoding="utf-8")
    w = SearchWindow()
    w.resize(980, 560)
    w.show()
    it = QueueItem("claude-code:s1", "claude-code", "t", "", str(p), 1, 1.8e9)
    w.set_queue(QueueResult(focus=[it]), "s", 1.8e9)
    w._refresh_preview()
    frames = w.pane.body.findChildren(type(w.pane), "pvRecent") or \
        [f for f in w.pane.body.findChildren(QFrameType()) if f.objectName() == "pvRecent"]
    assert frames
    texts = [lb.text() for lb in frames[0].findChildren(QLabelType())]
    assert texts[0] == "최근 대화" and texts.count("나") == 5 and texts.count("AI") == 5
    w.hide()
    w.deleteLater()


def QFrameType():
    from PySide6.QtWidgets import QFrame
    return QFrame


def QLabelType():
    from PySide6.QtWidgets import QLabel
    return QLabel


# ---- 일지 칩, 칩만 켰을 때 큐 거르기 -----------------------------------------------------
def test_journal_source_alias_and_filter_sql(tmp_path):
    from app.query import parse
    from app.search import journal_prefix
    q = parse("src:journal 배포")
    assert q.sources == ["journal"] and "src:journal" in q.filter_labels()
    assert parse("src:일지").sources == ["journal"]
    root = tmp_path / "vault"
    assert journal_prefix(root).endswith("vault\\") and journal_prefix("") == ""
    idx = Index(tmp_path / "index.db")
    idx.open().close()
    conn = connect(tmp_path / "index.db")
    with conn:
        for cid, src, path in [("j", "note", str(root / "2026" / "11" / "2026-11-11.md")),
                               ("n", "note", str(tmp_path / "other" / "a.md")), ("c", "claude-code", str(tmp_path / "c.md"))]:
            conn.execute("INSERT INTO docs(conv_id, path, title, source, updated_ts) VALUES(?,?,?,?,?)",
                         (cid, path, cid, src, 1))
    s = Searcher(conn)
    assert [h.conv_id for h in s.search("src:journal")] == []            # 일지 폴더 설정 없음
    s.journal_dir = str(root)
    assert [h.conv_id for h in s.search("src:journal")] == ["j"]
    assert sorted(h.conv_id for h in s.search("src:journal src:code")) == ["c", "j"]
    conn.close()


def test_filter_queue_keeps_journal_and_period():
    from datetime import date, datetime as dt
    from app.main import filter_queue
    from app.query import parse
    from app.queue import QueueItem, QueueResult
    now = dt(2026, 11, 12, 9, 0).timestamp()
    items = [QueueItem("journal:a", "journal", "a", "", "j.md", 1, now - 3600),
             QueueItem("claude-ai:b", "claude-ai", "b", "데모", "b.md", 1, now - 10 * 86400),
             QueueItem("claude-code:c", "claude-code", "c", "small-win-tools", "c.md", 1, now - 3600)]
    res = QueueResult(items[:2], items[2:], [], 14)
    one_week = parse(f"after:{date(2026, 11, 5).isoformat()}")
    got = filter_queue(res, one_week, 5)
    assert [i.id for i in got.focus] == ["journal:a", "claude-code:c"]       # 일지도 남는다
    assert [i.id for i in filter_queue(res, parse("src:journal"), 5).focus] == ["journal:a"]
    assert [i.id for i in filter_queue(res, parse("proj:small"), 1).rest] == []
    assert [i.id for i in filter_queue(res, parse("src:ai src:code"), 1).rest] == ["claude-code:c"]


def test_elided_label_tooltip_wraps_full_text(qt):
    from app.window import ElideLabel
    lb = ElideLabel("가" * 200)
    lb.resize(80, 20)
    lb._elide()
    assert "<table" in lb.toolTip() and "가" * 200 in lb.toolTip()
    lb.resize(4000, 20)
    lb._elide()
    assert lb.toolTip() == ""


def test_fast_tooltip_style(qt):
    from PySide6.QtWidgets import QStyle
    from app import theme as T
    st = T.FastTipStyle()
    assert st.styleHint(QStyle.SH_ToolTip_WakeUpDelay) == T.TIP_DELAY_MS == 300
