"""활성 창 폴링, 자리 비움, 잠금/절전, 일시 정지. 시계와 Win32 호출은 주입 가능."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Callable, Protocol

from .rules import Privacy

SAVE_CURRENT_EVERY = timedelta(seconds=30)
# 이 이상 폴링이 끊기면 절전 알림을 놓친 것으로 보고 sleep 구간으로 처리
GAP_FACTOR = 6
MIN_GAP = timedelta(seconds=60)

# idle 사유 우선순위 (앞이 우선)
MODE_ORDER = ("sleep", "lock", "pause")


class Api(Protocol):
    def foreground(self) -> tuple[str, str] | None: ...
    def idle_seconds(self) -> float: ...


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Collector:
    def __init__(self, store, config: dict, privacy: Privacy, starts_at: time, api: Api,
                 clock: Callable[[], datetime] = datetime.now):
        self.store = store
        self.privacy = privacy
        self.starts_at = starts_at
        self.api = api
        self.clock = clock
        self.apply_config(config)
        self.cur: dict | None = None  # {"start": dt, "end": dt, "fields": {...}}
        self.modes: set[str] = set()
        self.pause_until: datetime | None = None
        self.last_tick: datetime | None = None
        self._last_save: datetime | None = None

    def apply_config(self, config: dict) -> None:
        self.poll = timedelta(seconds=float(config.get("poll_seconds", 5)))
        self.idle_limit = timedelta(minutes=float(config.get("idle_minutes", 5)))

    # ---- 구간 관리 ------------------------------------------------------
    def _record(self, seg: dict, end: datetime | None = None) -> dict:
        return {"start": _iso(seg["start"]), "end": _iso(end or seg["end"]), **seg["fields"]}

    def _close(self, at: datetime) -> None:
        seg, self.cur = self.cur, None
        if seg is not None:
            end = max(seg["start"], at)
            if end > seg["start"]:
                self.store.append_record(self._record(seg, end), self.starts_at)
        self.store.save_current(None)
        self._last_save = None

    def _start(self, fields: dict, at: datetime, now: datetime) -> None:
        self.cur = {"start": at, "end": max(at, now), "fields": fields}

    def _save(self, now: datetime, force: bool = False) -> None:
        if self.cur is None:
            return
        if force or self._last_save is None or now - self._last_save >= SAVE_CURRENT_EVERY:
            self.store.save_current(self._record(self.cur))
            self._last_save = now

    def _cur_idle(self) -> str | None:
        return self.cur["fields"].get("idle") if self.cur else None

    def mode_reason(self) -> str | None:
        return next((m for m in MODE_ORDER if m in self.modes), None)

    def _window_fields(self, proc: str, title: str) -> dict:
        if self.privacy.is_excluded(proc, title):
            return {"proc": proc, "excluded": True}
        return {"proc": proc, "title": self.privacy.mask(title)}

    # ---- 폴링 ----------------------------------------------------------
    def tick(self) -> None:
        now = self.clock()
        if self.last_tick is not None:
            gap = now - self.last_tick
            if gap > max(self.poll * GAP_FACTOR, MIN_GAP) and "sleep" not in self.modes:
                # 절전 알림 없이 시계가 뛰었다: 마지막 폴링 시각에 닫고 sleep 구간 추가
                at = self.last_tick
                self._close(at)
                self.store.append_record({"start": _iso(at), "end": _iso(now), "idle": "sleep"},
                                         self.starts_at)
        self.last_tick = now

        if "pause" in self.modes and self.pause_until is not None and now >= self.pause_until:
            self._set_mode("pause", False, now)

        reason = self.mode_reason()
        if reason:
            if self._cur_idle() == reason:
                self.cur["end"] = now
            else:
                self._close(now)
                self._start({"idle": reason}, now, now)
            self._save(now)
            return

        try:
            idle = timedelta(seconds=max(0.0, float(self.api.idle_seconds())))
        except Exception:  # noqa: BLE001  읽기 실패해도 멈추지 않는다
            idle = timedelta(0)
        last_input = now - idle

        if idle >= self.idle_limit:
            if self._cur_idle() == "away":
                self.cur["end"] = now
            else:
                # 마지막 입력 시각으로 소급
                at = max(last_input, self.cur["start"]) if self.cur else last_input
                self._close(at)
                self._start({"idle": "away"}, at, now)
            self._save(now)
            return

        start_at = now
        if self._cur_idle() == "away":
            start_at = max(last_input, self.cur["start"])
            self._close(start_at)
        elif self._cur_idle():
            self._close(now)

        try:
            fg = self.api.foreground()
        except Exception:  # noqa: BLE001
            fg = ("(알 수 없음)", "")
        if fg is None:
            self._close(now)
            return
        fields = self._window_fields(str(fg[0] or "(알 수 없음)"), str(fg[1] or ""))
        if self.cur is not None and self.cur["fields"] == fields:
            self.cur["end"] = now
        else:
            self._close(now)
            self._start(fields, start_at, now)
        self._save(now)

    # ---- 이벤트 --------------------------------------------------------
    def _set_mode(self, name: str, on: bool, now: datetime | None = None) -> None:
        now = now or self.clock()
        old = self.mode_reason()
        if on:
            self.modes.add(name)
        else:
            self.modes.discard(name)
            if name == "pause":
                self.pause_until = None
        new = self.mode_reason()
        if old == new:
            return
        self._close(now)
        if new:
            self._start({"idle": new}, now, now)
            self._save(now, force=True)

    def on_lock(self) -> None:
        self._set_mode("lock", True)

    def on_unlock(self) -> None:
        self._set_mode("lock", False)

    def on_suspend(self) -> None:
        self._set_mode("sleep", True)

    def on_resume(self) -> None:
        now = self.clock()
        self._set_mode("sleep", False, now)
        self.last_tick = now  # 절전 구간이 시계 점프로 한 번 더 잡히지 않게

    def pause(self, minutes: float | None) -> None:
        now = self.clock()
        self.pause_until = now + timedelta(minutes=minutes) if minutes else None
        self._set_mode("pause", True, now)

    def resume(self) -> None:
        self._set_mode("pause", False)

    @property
    def paused(self) -> bool:
        return "pause" in self.modes

    # ---- 조회 / 정리 ----------------------------------------------------
    def idle_reason(self) -> str | None:
        """지금 진행 중인 idle 구간의 사유 (away/lock/sleep/pause) 또는 None."""
        return self._cur_idle()

    def idle_duration(self, now: datetime | None = None) -> timedelta:
        if not self._cur_idle():
            return timedelta(0)
        return (now or self.clock()) - self.cur["start"]

    def snapshot(self, now: datetime | None = None) -> list[dict]:
        """진행 중 구간을 now까지로 본 기록 (요약용, 저장하지 않음)."""
        if self.cur is None:
            return []
        return [self._record(self.cur, max(self.cur["start"], now or self.cur["end"]))]

    def checkpoint(self, now: datetime | None = None) -> None:
        """진행 중 구간을 now까지 확정하고 같은 구간을 now부터 이어 간다 (업무일 경계용)."""
        now = now or self.clock()
        if self.cur is None:
            return
        fields = self.cur["fields"]
        self.cur["end"] = max(self.cur["start"], now)
        self._close(now)
        self._start(fields, now, now)

    def discard_current(self) -> None:
        """오늘 기록 삭제용: 진행 구간을 저장하지 않고 버린다."""
        self.cur = None
        self.store.save_current(None)
        self._last_save = None

    def stop(self) -> None:
        self._close(self.clock())
