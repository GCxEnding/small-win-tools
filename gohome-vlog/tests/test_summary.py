import json
from datetime import datetime
from pathlib import Path

from app.store import load_default_config
from app.summary import EMPTY_TEXT, build_summary, fmt_duration

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONFIG = load_default_config()
DAY_END = datetime(2026, 11, 5, 4, 0)


def load_sample():
    with (FIXTURES / "sample_day.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def rec(start, end, proc=None, title="", **extra):
    r = {"start": f"2026-11-04T{start}:00", "end": f"2026-11-04T{end}:00", **extra}
    if proc:
        r.update(proc=proc, title=title)
    return r


def test_matches_expected_sample():
    expected = (FIXTURES / "sample_day.expected.md").read_text(encoding="utf-8")
    assert build_summary(load_sample(), CONFIG, DAY_END) == expected


def test_no_em_dash():
    out = build_summary(load_sample(), CONFIG, DAY_END)
    assert "—" not in out


def test_empty():
    assert build_summary([], CONFIG, DAY_END) == EMPTY_TEXT
    only_idle = [rec("09:00", "10:00", idle="away"), rec("10:00", "11:00", idle="lock")]
    assert build_summary(only_idle, CONFIG, DAY_END) == EMPTY_TEXT


def test_fmt_duration():
    assert fmt_duration(40 * 60) == "40분"
    assert fmt_duration(3 * 3600 + 5 * 60) == "3시간 05분"
    assert fmt_duration(29) == "0분"
    assert fmt_duration(30) == "1분"


def test_small_items_go_to_other():
    recs = [
        rec("09:00", "09:30", "chrome.exe", "x"),
        rec("09:30", "09:34", "claude.exe", "y"),
        rec("09:34", "09:37", "notepad.exe", "z"),
    ]
    out = build_summary(recs, CONFIG, DAY_END)
    assert "- 웹: Chrome : 30분" in out
    assert "- 기타 : 7분" in out
    assert "AI: Claude" not in out.split("####")[0]


def test_idle_and_pause_not_counted():
    recs = [
        rec("09:00", "10:00", "chrome.exe", "x"),
        rec("10:00", "11:00", idle="pause"),
        rec("11:00", "11:30", idle="away"),
        rec("11:30", "12:00", idle="sleep"),
        rec("12:00", "12:30", "chrome.exe", "x"),
    ]
    out = build_summary(recs, CONFIG, DAY_END)
    assert out.splitlines()[0] == "### 오늘의 브이로그 (09:00 ~ 12:30, 활동 1시간 30분)"
    assert "- 09:00 ~ 10:00 : 웹 Chrome" in out
    assert "- 12:00 ~ 12:30 : 웹 Chrome" in out  # idle 블록 생략으로 이어지지 않음


def test_default_block_is_10_minutes():
    recs = [rec("09:00", "09:08", "chrome.exe", "x"), rec("09:08", "09:20", "putty.exe", "srv - PuTTY")]
    flow = build_summary(recs, CONFIG, DAY_END).split("#### 흐름\n")[1].splitlines()
    # 09:00 블록: 웹 8분, 서버 2분(1/3 미만) -> 웹만
    assert flow == ["- 09:00 ~ 09:10 : 웹 Chrome", "- 09:10 ~ 09:20 : 서버 srv"]


def test_excluded_counted_as_time_only():
    recs = [rec("09:00", "09:10", proc=None, excluded=True) | {"proc": "KeePassXC.exe"}]
    out = build_summary(recs, CONFIG, DAY_END)
    assert "- 제외됨 : 10분" in out
    assert "KeePassXC" not in out


def test_code_top_files():
    recs = [
        rec("09:00", "09:40", "idea64.exe", "proj – A.java"),
        rec("09:40", "10:10", "idea64.exe", "proj – B.java"),
        rec("10:10", "10:30", "idea64.exe", "proj – C.java"),
        rec("10:30", "10:40", "idea64.exe", "proj – D.java"),
    ]
    out = build_summary(recs, CONFIG, DAY_END)
    assert "- 코드: proj (A.java, B.java, C.java) : 1시간 40분" in out
    two = build_summary(recs[:2], CONFIG, DAY_END)
    assert "- 코드: proj (A.java, B.java) : 1시간 10분" in two


def test_flow_blocks_merge_and_secondary():
    recs = [
        rec("09:00", "09:30", "idea64.exe", "proj – A.java"),
        # 09:30 블록: 코드 10분, 서버 5분 (1/3 이상) -> 함께 표시
        rec("09:30", "09:40", "idea64.exe", "proj – A.java"),
        rec("09:40", "09:45", "putty.exe", "srv - PuTTY"),
        # 09:45 블록: 코드 13분, 서버 2분 (1/3 미만) -> 코드만
        rec("09:45", "09:58", "idea64.exe", "proj – A.java"),
        rec("09:58", "10:00", "putty.exe", "srv - PuTTY"),
    ]
    out = build_summary(recs, {**CONFIG, "timeline_block_minutes": 15}, DAY_END)
    flow = out.split("#### 흐름\n")[1].splitlines()
    assert flow == [
        "- 09:00 ~ 09:30 : 코드 proj",
        "- 09:30 ~ 09:45 : 코드 proj, 서버 srv",
        "- 09:45 ~ 10:00 : 코드 proj",
    ]


def test_now_clips_in_progress():
    recs = [rec("09:00", "10:00", "chrome.exe", "x")]
    out = build_summary(recs, CONFIG, datetime(2026, 11, 4, 9, 30))
    assert "활동 30분" in out.splitlines()[0]
