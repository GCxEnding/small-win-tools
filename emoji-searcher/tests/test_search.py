import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.search import Searcher, load_entries
from app.store import Store

HERE = Path(__file__).resolve().parent
GOLDEN = json.loads((HERE / "golden_queries.json").read_text(encoding="utf-8"))
SKIN_TONES = {chr(c) for c in range(0x1F3FB, 0x1F400)}
NOW = datetime(2026, 11, 4, 12, 0, 0)


@pytest.fixture(scope="module")
def entries():
    return load_entries()


@pytest.fixture
def searcher(entries):
    return Searcher(entries, now=NOW)


def emojis(results):
    return [r.emoji for r in results]


# ---- 데이터 검사 -----------------------------------------------------------
def test_data_tags_not_empty(entries):
    bad = [e["emoji"] for e in entries if not e["tags_ko"] or not e["tags_en"]]
    assert not bad


def test_data_no_duplicates(entries):
    seen = [e["emoji"] for e in entries]
    assert len(seen) == len(set(seen))


def test_data_no_skin_tones(entries):
    assert not [e["emoji"] for e in entries if SKIN_TONES & set(e["emoji"])]


# ---- 정답 샘플 -------------------------------------------------------------
@pytest.mark.parametrize("case", GOLDEN, ids=[c["query"] for c in GOLDEN])
def test_golden(searcher, case):
    top5 = emojis(searcher.search(case["query"], 5))
    assert set(case["expect"]) & set(top5), f"{case['query']!r} -> {top5}"


# ---- 정렬 규칙 -------------------------------------------------------------
def test_exact_above_contains(searcher):
    res = searcher.search("배포", 50)
    exact = [r for r in res if any(m == "배포" for m in r.matched)]
    partial = [r for r in res if r not in exact]
    assert exact
    if partial:
        assert min(r.score for r in exact) > max(r.score for r in partial)


def test_usage_does_not_override_exact(entries):
    # 부분 포함으로만 걸리는 이모지를 아주 많이, 방금 쓴 것으로 만든다
    s = Searcher(entries, now=NOW)
    partial_only = [r.emoji for r in s.search("배포", 50) if "배포" not in r.matched]
    exact = [r.emoji for r in s.search("배포", 50) if "배포" in r.matched]
    assert exact
    usage = {e: {"count": 10_000, "last_used": NOW.isoformat()} for e in partial_only}
    s.set_usage(usage)
    res = s.search("배포", 50)
    first_partial = next((i for i, r in enumerate(res) if r.emoji in partial_only), len(res))
    last_exact = max(i for i, r in enumerate(res) if r.emoji in exact)
    assert last_exact < first_partial


def test_usage_boosts_among_equals(entries):
    s = Searcher(entries, now=NOW)
    base = emojis(s.search("하트", 10))
    target = base[5]
    s.set_usage({target: {"count": 20, "last_used": NOW.isoformat()}})
    assert emojis(s.search("하트", 10)).index(target) < 5


def test_recent_when_empty(entries):
    usage = {
        "🚀": {"count": 3, "last_used": (NOW - timedelta(days=3)).isoformat()},
        "🔥": {"count": 1, "last_used": NOW.isoformat()},
    }
    s = Searcher(entries, usage=usage, now=NOW)
    assert emojis(s.search("", 10)) == ["🔥", "🚀"]
    assert emojis(s.search("   ", 10)) == ["🔥", "🚀"]
    assert Searcher(entries).search("", 10) == []


def test_and_search(searcher):
    res = searcher.search("빨간 하트", 10)
    assert res and res[0].emoji == "❤️"
    assert all(len(r.matched) >= 1 for r in res)


def test_case_and_space_insensitive(searcher):
    assert emojis(searcher.search("  DEPLOY ", 5)) == emojis(searcher.search("deploy", 5))


def test_mixed_choseong_is_plain_contains(searcher):
    # '배ㅍ' 은 초성 검색이 아니라 일반 부분 일치 -> 결과 없음이 정상
    assert searcher.search("배ㅍ", 5) == []


def test_composing_prefix_updates(searcher):
    # 한글 조합 중간 상태에서도 결과가 나와야 한다
    assert searcher.search("ㅂ", 5)
    assert searcher.search("배", 5)


def test_english_and_converted_merged(searcher):
    # 'rk' -> 영단어 일부 + '가' 변환 결과가 함께, 중복 없이
    res = emojis(searcher.search("rk", 30))
    assert len(res) == len(set(res))
    assert res


def test_no_result(searcher):
    assert searcher.search("zzqqxxyy없는말", 5) == []


def test_speed(searcher):
    t = time.perf_counter()
    for q in ["ㅂ", "배", "배포", "d", "de", "dep", "qnf", "ㅂㅍ"]:
        searcher.search(q, 30)
    assert (time.perf_counter() - t) / 8 < 0.1


# ---- 개인 태그 -------------------------------------------------------------
def test_user_tags_applied(entries):
    s = Searcher(entries, user_tags={"🧪": ["실험실전용태그"]}, now=NOW)
    assert emojis(s.search("실험실전용태그", 3))[0] == "🧪"


def test_user_tags_unknown_emoji(entries):
    s = Searcher(entries, user_tags={"🫨🫨": ["흔들흔들개인"]}, now=NOW)
    assert emojis(s.search("흔들흔들개인", 3)) == ["🫨🫨"]


def test_user_tags_weighted(entries):
    s = Searcher(entries, user_tags={"💩": ["배포"]}, now=NOW)
    assert emojis(s.search("배포", 3))[0] == "💩"


def test_broken_user_tags(tmp_path, entries):
    store = Store(tmp_path)
    store.ensure()
    store.user_tags_path.write_text("{ 이건 json 아님", encoding="utf-8")
    res = store.load_user_tags()
    assert res.data == {} and res.warning
    assert store.user_tags_path.read_text(encoding="utf-8") == "{ 이건 json 아님"  # 덮어쓰지 않음
    Searcher(entries, user_tags=res.data).search("배포", 5)


def test_user_tags_created_with_example(tmp_path):
    store = Store(tmp_path)
    res = store.load_user_tags()
    assert store.user_tags_path.exists()
    assert res.data.get("🔥") == ["긴급", "핫픽스"]
    assert "_설명" not in res.data


# ---- 사용 기록 -------------------------------------------------------------
def test_broken_usage_backed_up(tmp_path):
    store = Store(tmp_path)
    store.ensure()
    store.usage_path.write_text("not json", encoding="utf-8")
    res = store.load_usage()
    assert res.data == {} and res.warning
    assert (tmp_path / "usage.json.bak").read_text(encoding="utf-8") == "not json"
    assert not store.usage_path.exists()


def test_record_use_atomic(tmp_path):
    store = Store(tmp_path)
    usage = {}
    store.record_use(usage, "🚀", NOW)
    store.record_use(usage, "🚀", NOW)
    saved = json.loads(store.usage_path.read_text(encoding="utf-8"))
    assert saved["🚀"]["count"] == 2
    assert not list(tmp_path.glob("*.tmp"))


# ---- 창 위치 ---------------------------------------------------------------
@pytest.mark.parametrize("cur, expect", [
    ((100, 100), (102, 102)),          # 여유 있으면 커서 오른쪽 아래
    ((1900, 100), (1900 - 560 - 2, 102)),   # 오른쪽 끝: 커서 왼쪽으로
    ((100, 1000), (102, 1000 - 440 - 2)),   # 아래쪽 끝: 커서 위로
    ((1900, 1000), (1338, 558)),       # 오른쪽 아래 구석: 둘 다 뒤집기
])
def test_popup_position_cursor(cur, expect):
    from PySide6.QtCore import QPoint, QRect
    from app.window import popup_position
    p = popup_position(QRect(0, 0, 1920, 1040), QPoint(*cur), 560, 440)
    assert (p.x(), p.y()) == expect


def test_popup_position_second_monitor_and_center():
    from PySide6.QtCore import QPoint, QRect
    from app.window import popup_position
    g = QRect(1920, 0, 1920, 1040)
    p = popup_position(g, QPoint(1925, 5), 560, 440)
    assert p.x() >= 1920 and p.y() >= 0
    c = popup_position(g, QPoint(1925, 5), 560, 440, "center")
    assert (c.x(), c.y()) == (1920 + 680, 300)
