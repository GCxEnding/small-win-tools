"""%LOCALAPPDATA%\\gohome-vlog 데이터: 원본 jsonl, current.json, 요약, 설정. 보존/삭제."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable

from .rules import DEFAULTS_DIR, Rule, compile_patterns, load_default_rules, parse_rules

APP_DIR_NAME = "gohome-vlog"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_DIR_NAME


def load_default_config() -> dict:
    with (DEFAULTS_DIR / "config.json").open(encoding="utf-8") as f:
        return json.load(f)


def parse_hhmm(text: str, fallback: str) -> time:
    for v in (text, fallback):
        try:
            h, m = str(v).split(":")
            return time(int(h), int(m))
        except (ValueError, TypeError):
            continue
    return time(0, 0)


def day_start_time(config: dict) -> time:
    return parse_hhmm(config.get("day_starts_at", "04:00"), "04:00")


def business_day(dt: datetime, starts_at: time) -> date:
    """day_starts_at 이전 시각은 전날 업무일."""
    shifted = dt - timedelta(hours=starts_at.hour, minutes=starts_at.minute)
    return shifted.date()


def day_bounds(day: date, starts_at: time) -> tuple[datetime, datetime]:
    start = datetime.combine(day, starts_at)
    return start, start + timedelta(days=1)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class LoadResult:
    data: object
    warning: str | None = None


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


@dataclass
class Store:
    root: Path = field(default_factory=default_data_dir)

    # ---- 경로 ----------------------------------------------------------
    @property
    def raw_dir(self) -> Path:
        return self.root / "raw"

    @property
    def summary_dir(self) -> Path:
        return self.root / "summary"

    @property
    def current_path(self) -> Path:
        return self.raw_dir / "current.json"

    @property
    def state_path(self) -> Path:
        return self.raw_dir / "state.json"

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def rules_path(self) -> Path:
        return self.root / "rules.json"

    def raw_path(self, day: date) -> Path:
        return self.raw_dir / f"{day.isoformat()}.jsonl"

    def summary_path(self, day: date) -> Path:
        return self.summary_dir / f"{day.isoformat()}.md"

    def ensure(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.summary_dir.mkdir(parents=True, exist_ok=True)

    # ---- 설정 ----------------------------------------------------------
    def _copy_default(self, name: str, dest: Path) -> None:
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(DEFAULTS_DIR / name, dest)

    def load_config(self) -> LoadResult:
        """깨졌으면 기본값으로 동작하고 경고. 사용자 파일은 덮어쓰지 않는다."""
        defaults = load_default_config()
        self._copy_default("config.json", self.config_path)
        try:
            with self.config_path.open(encoding="utf-8-sig") as f:
                user = json.load(f)
            if not isinstance(user, dict):
                raise ValueError("최상위가 객체가 아닙니다.")
            merged = {**defaults, **user}
            for k in ("exclude_title_patterns", "mask_title_patterns"):
                compile_patterns(merged.get(k))
            return LoadResult(merged)
        except (OSError, ValueError) as e:
            return LoadResult(defaults, f"config.json을 읽지 못해 기본값으로 동작합니다: {e}")

    def load_rules(self) -> LoadResult:
        self._copy_default("rules.json", self.rules_path)
        try:
            with self.rules_path.open(encoding="utf-8-sig") as f:
                return LoadResult(parse_rules(json.load(f)))
        except (OSError, ValueError) as e:
            return LoadResult(load_default_rules(), f"rules.json을 읽지 못해 기본 규칙으로 동작합니다: {e}")

    # ---- 원본 ----------------------------------------------------------
    def append_record(self, rec: dict, starts_at: time) -> None:
        """확정 구간 추가. 업무일 경계를 넘는 구간은 나눠서 각 날짜 파일에 쓴다."""
        try:
            s = datetime.fromisoformat(rec["start"])
            e = datetime.fromisoformat(rec["end"])
        except (KeyError, TypeError, ValueError):
            return
        if e <= s:
            return
        while s < e:
            day = business_day(s, starts_at)
            _, day_end = day_bounds(day, starts_at)
            part_end = min(e, day_end)
            part = {**rec, "start": _iso(s), "end": _iso(part_end)}
            path = self.raw_path(day)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(part, ensure_ascii=False) + "\n")
            s = part_end

    def read_records(self, day: date) -> list[dict]:
        """깨진 줄(강제 종료로 잘린 줄 등)은 무시."""
        path = self.raw_path(day)
        if not path.exists():
            return []
        out = []
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and "start" in rec and "end" in rec:
                    out.append(rec)
        return out

    def raw_days(self) -> list[date]:
        if not self.raw_dir.exists():
            return []
        days = []
        for p in self.raw_dir.glob("*.jsonl"):
            try:
                days.append(date.fromisoformat(p.stem))
            except ValueError:
                continue
        return sorted(days)

    def delete_raw(self, day: date) -> None:
        self.raw_path(day).unlink(missing_ok=True)

    # ---- 진행 중 구간 ----------------------------------------------------
    def save_current(self, rec: dict | None) -> None:
        if rec is None:
            self.current_path.unlink(missing_ok=True)
            return
        atomic_write_text(self.current_path, json.dumps(rec, ensure_ascii=False))

    def recover_current(self, starts_at: time) -> bool:
        """지난 실행의 진행 구간을 마지막 저장 시각까지로 확정한다."""
        path = self.current_path
        if not path.exists():
            return False
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = None
        path.unlink(missing_ok=True)
        if isinstance(rec, dict):
            self.append_record(rec, starts_at)
            return True
        return False

    # ---- 상태(알림/퇴근 감지 여부) ------------------------------------------
    def load_state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict) -> None:
        atomic_write_text(self.state_path, json.dumps(state, ensure_ascii=False))

    # ---- 요약 ----------------------------------------------------------
    def write_summary(self, day: date, text: str) -> Path:
        path = self.summary_path(day)
        atomic_write_text(path, text)
        return path

    def finalize_past_days(self, today: date, summarize: Callable[[date, list[dict]], str]) -> list[date]:
        """오늘 이전 업무일 원본을 요약한 뒤 삭제한다. 처리한 날짜 목록."""
        done = []
        for day in self.raw_days():
            if day >= today:
                continue
            self.write_summary(day, summarize(day, self.read_records(day)))
            self.delete_raw(day)
            done.append(day)
        return done

    def purge_summaries(self, today: date, keep_days: int) -> list[date]:
        """keep_days일(오늘 포함) 지난 요약 삭제."""
        removed = []
        if not self.summary_dir.exists():
            return removed
        for p in self.summary_dir.glob("*.md"):
            try:
                d = date.fromisoformat(p.stem)
            except ValueError:
                continue
            if (today - d).days >= keep_days:
                p.unlink(missing_ok=True)
                removed.append(d)
        return sorted(removed)

    def delete_day(self, day: date) -> None:
        """오늘 기록 삭제: 원본, 진행 구간, 그날 요약."""
        self.delete_raw(day)
        self.current_path.unlink(missing_ok=True)
        self.summary_path(day).unlink(missing_ok=True)
