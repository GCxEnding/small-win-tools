"""창 크기 같은 화면 상태를 LOCALAPPDATA의 ui_state.json에 저장한다 (UI 의존 없음).

모니터가 PC마다 달라서 config.json(APPDATA)에 넣지 않고, 설정 창에도 항목을 만들지 않는다.
앱이 관리하는 상태 파일이라 깨졌으면 .bak으로 보관하고 새로 시작한다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .store import atomic_json

FILE_NAME = "ui_state.json"
MIN_W, MIN_H = 560, 360
SPLIT_MIN, SPLIT_MAX = 0.2, 0.8


def load(path: Path | None) -> dict:
    """저장된 상태. 없거나 깨졌으면 빈 dict (깨진 파일은 .bak으로 옮긴다)."""
    if path is None or not Path(path).exists():
        return {}
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("최상위가 객체가 아님")
        return data
    except (OSError, ValueError):
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
        return {}


def save(path: Path | None, data: dict) -> bool:
    if path is None:
        return False
    try:
        atomic_json(Path(path), data)
    except OSError:
        return False
    return True


def search_state(data: dict) -> dict:
    """검색 창 항목만 걸러 낸다: w, h (정수, 최소 크기 이상), split (목록 칸 비율). 잘못된 값은 뺀다."""
    raw = data.get("search_window") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k, lo in (("w", MIN_W), ("h", MIN_H)):
        v = raw.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and v >= lo:
            out[k] = v
    v = raw.get("split")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and SPLIT_MIN <= v <= SPLIT_MAX:
        out["split"] = float(v)
    return out


def with_search_state(data: dict, state: dict) -> dict:
    """다른 키는 그대로 두고 검색 창 항목만 바꾼 새 dict."""
    new = dict(data) if isinstance(data, dict) else {}
    new["search_window"] = {k: state[k] for k in ("w", "h", "split") if k in state}
    return new


def fit_size(w: int, h: int, avail_w: int, avail_h: int) -> tuple[int, int]:
    """저장된 크기가 모니터 사용 가능 영역보다 크면 줄인다. 최소 크기(560x360)보다 작게는 만들지 않는다."""
    return max(MIN_W, min(w, avail_w)), max(MIN_H, min(h, avail_h))
