import json
from datetime import date, datetime, time, timedelta

import pytest

from app.collector import Collector
from app.rules import Privacy
from app.store import Store, business_day, load_default_config

START = time(4, 0)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path)
    s.ensure()
    return s


def test_business_day_boundary():
    assert business_day(datetime(2026, 11, 5, 3, 59), START) == date(2026, 11, 4)
    assert business_day(datetime(2026, 11, 5, 4, 0), START) == date(2026, 11, 5)


def test_append_splits_at_boundary(store):
    store.append_record({"start": "2026-11-05T03:50:00", "end": "2026-11-05T04:10:00", "idle": "sleep"}, START)
    a = store.read_records(date(2026, 11, 4))
    b = store.read_records(date(2026, 11, 5))
    assert a == [{"start": "2026-11-05T03:50:00", "end": "2026-11-05T04:00:00", "idle": "sleep"}]
    assert b == [{"start": "2026-11-05T04:00:00", "end": "2026-11-05T04:10:00", "idle": "sleep"}]


def test_broken_lines_ignored(store):
    day = date(2026, 11, 4)
    store.raw_path(day).write_text(
        '{"start": "2026-11-04T09:00:00", "end": "2026-11-04T09:10:00", "proc": "a.exe", "title": "t"}\n'
        '{"start": "2026-11-04T09:10:00", "end": "2026-11-0\n'
        "garbage\n\n[1, 2]\n"
        '{"start": "2026-11-04T09:20:00", "end": "2026-11-04T09:30:00", "idle": "away"}\n',
        encoding="utf-8")
    recs = store.read_records(day)
    assert [r["start"][-8:] for r in recs] == ["09:00:00", "09:20:00"]


def test_recover_current(store):
    store.save_current({"start": "2026-11-04T09:00:00", "end": "2026-11-04T09:07:30",
                        "proc": "a.exe", "title": "t"})
    assert store.recover_current(START)
    assert not store.current_path.exists()
    assert store.read_records(date(2026, 11, 4))[0]["end"] == "2026-11-04T09:07:30"
    assert not store.recover_current(START)


def test_recover_broken_current(store):
    store.current_path.write_text("{broken", encoding="utf-8")
    assert not store.recover_current(START)
    assert not store.current_path.exists()


def test_finalize_past_days(store):
    for d in ("2026-11-02", "2026-11-03", "2026-11-04"):
        store.append_record({"start": f"{d}T09:00:00", "end": f"{d}T10:00:00", "proc": "a.exe", "title": ""}, START)
    seen = []
    done = store.finalize_past_days(date(2026, 11, 4), lambda day, recs: seen.append((day, len(recs))) or f"S {day}")
    assert done == [date(2026, 11, 2), date(2026, 11, 3)]
    assert seen == [(date(2026, 11, 2), 1), (date(2026, 11, 3), 1)]
    assert store.raw_days() == [date(2026, 11, 4)]
    assert store.summary_path(date(2026, 11, 3)).read_text(encoding="utf-8") == "S 2026-11-03"


def test_purge_summaries_keep_7_days(store):
    today = date(2026, 11, 10)
    for i in range(10):
        store.write_summary(today - timedelta(days=i), "x")
    removed = store.purge_summaries(today, 7)
    assert removed == [today - timedelta(days=i) for i in (9, 8, 7)]
    assert len(list(store.summary_dir.glob("*.md"))) == 7


def test_delete_day(store):
    day = date(2026, 11, 4)
    store.append_record({"start": "2026-11-04T09:00:00", "end": "2026-11-04T10:00:00", "idle": "away"}, START)
    store.save_current({"start": "2026-11-04T10:00:00", "end": "2026-11-04T10:01:00", "idle": "away"})
    store.write_summary(day, "x")
    store.delete_day(day)
    assert not store.raw_path(day).exists()
    assert not store.current_path.exists()
    assert not store.summary_path(day).exists()


def test_broken_config_falls_back_without_overwrite(store):
    store.config_path.write_text("{not json", encoding="utf-8")
    store.rules_path.write_text("[{]", encoding="utf-8")
    cfg, rules = store.load_config(), store.load_rules()
    assert cfg.warning and rules.warning
    assert cfg.data["poll_seconds"] == load_default_config()["poll_seconds"]
    assert rules.data  # 기본 규칙
    assert store.config_path.read_text(encoding="utf-8") == "{not json"
    assert store.rules_path.read_text(encoding="utf-8") == "[{]"


def test_missing_settings_copied(store):
    assert not store.rules_path.exists()
    assert store.load_rules().warning is None
    assert store.load_config().warning is None
    assert store.rules_path.exists() and store.config_path.exists()


# ---- collector (가짜 시계, 가짜 Win32) ------------------------------------
class FakeApi:
    def __init__(self):
        self.window = ("idea64.exe", "proj – A.java")
        self.idle = 0.0

    def foreground(self):
        return self.window

    def idle_seconds(self):
        return self.idle


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def make_collector(store, config=None):
    cfg = {**load_default_config(), **(config or {})}
    clock = Clock(datetime(2026, 11, 4, 9, 0, 0))
    api = FakeApi()
    c = Collector(store, cfg, Privacy.from_config(cfg), START, api, clock)
    return c, api, clock


def records(store):
    return store.read_records(date(2026, 11, 4))


def run(c, clock, seconds, step=5):
    for _ in range(int(seconds // step)):
        clock.advance(seconds=step)
        c.tick()


def test_collector_window_change_and_extend(store):
    c, api, clock = make_collector(store)
    c.tick()
    run(c, clock, 60)
    api.window = ("idea64.exe", "proj – B.java")
    run(c, clock, 30)
    c.stop()
    recs = records(store)
    assert [(r["start"][-8:], r["end"][-8:], r["title"]) for r in recs] == [
        ("09:00:00", "09:01:05", "proj – A.java"),
        ("09:01:05", "09:01:30", "proj – B.java"),
    ]


def test_collector_idle_backdated_to_last_input(store):
    c, api, clock = make_collector(store)
    c.tick()
    run(c, clock, 600)  # 10분 활동
    # 이후 입력이 없다가 5분이 지난 시점에 idle 판정
    for _ in range(61):
        clock.advance(seconds=5)
        api.idle += 5
        c.tick()
    assert c.idle_reason() == "away"
    # 돌아옴
    clock.advance(seconds=5)
    api.idle = 0
    c.tick()
    run(c, clock, 60)
    c.stop()
    recs = records(store)
    assert recs[0]["end"] == "2026-11-04T09:10:00"  # 마지막 입력 시각으로 소급
    assert recs[1] == {"start": "2026-11-04T09:10:00", "end": "2026-11-04T09:15:10", "idle": "away"}
    assert recs[2]["start"] == "2026-11-04T09:15:10"


def test_collector_lock_pause_and_exclude(store):
    c, api, clock = make_collector(store)
    c.tick()
    run(c, clock, 60)
    c.on_lock()
    run(c, clock, 120)
    c.on_unlock()
    run(c, clock, 30)
    c.pause(30)
    run(c, clock, 30 * 60)  # 30분 후 자동 재개
    assert not c.paused
    api.window = ("KeePassXC.exe", "secret.kdbx - KeePassXC")
    run(c, clock, 30)
    c.stop()
    recs = records(store)
    kinds = [r.get("idle") or ("excluded" if r.get("excluded") else r["proc"]) for r in recs]
    assert kinds == ["idea64.exe", "lock", "idea64.exe", "pause", "idea64.exe", "excluded"]
    assert "title" not in recs[-1]
    pause = recs[3]
    assert (datetime.fromisoformat(pause["end"]) - datetime.fromisoformat(pause["start"])) == timedelta(minutes=30)


def test_collector_sleep_clock_jump(store):
    c, api, clock = make_collector(store)
    c.tick()
    run(c, clock, 60)
    clock.advance(hours=1)  # 절전 알림 없이 시계가 뜀
    c.tick()
    c.stop()
    recs = records(store)
    assert recs[0]["end"] == "2026-11-04T09:01:00"
    assert recs[1] == {"start": "2026-11-04T09:01:00", "end": "2026-11-04T10:01:00", "idle": "sleep"}


def test_collector_no_foreground_and_mask(store):
    c, api, clock = make_collector(store, {"mask_title_patterns": ["acme"]})
    api.window = ("chrome.exe", "acme 포털")
    c.tick()
    run(c, clock, 30)
    api.window = None
    run(c, clock, 30)
    c.stop()
    recs = records(store)
    assert len(recs) == 1
    assert recs[0]["title"] == "*** 포털"
    assert recs[0]["end"] == "2026-11-04T09:00:35"


def test_collector_saves_current(store):
    c, api, clock = make_collector(store)
    c.tick()
    run(c, clock, 40)
    data = json.loads(store.current_path.read_text(encoding="utf-8"))
    assert data["start"] == "2026-11-04T09:00:00"
    assert data["proc"] == "idea64.exe"
