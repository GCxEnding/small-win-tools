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
