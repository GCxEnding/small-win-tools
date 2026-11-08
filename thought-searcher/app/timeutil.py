"""시간 문자열 처리."""
from __future__ import annotations

import re
from datetime import datetime, timezone, tzinfo

_FRAC_RE = re.compile(r"\.(\d+)")


def parse_iso(value) -> datetime | None:
    """'2026-10-12T14:31:37.771055Z' 같은 문자열 -> 시간대 있는 datetime. 실패하면 None."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    # 3.10의 fromisoformat은 소수 초 자릿수가 3 또는 6이어야 한다
    s = _FRAC_RE.sub(lambda m: "." + (m.group(1) + "000000")[:6], s, count=1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo


def fmt_iso(dt: datetime, tz: tzinfo) -> str:
    return dt.astimezone(tz).isoformat(timespec="seconds")
