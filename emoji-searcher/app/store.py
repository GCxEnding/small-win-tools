"""%APPDATA%\\emoji-searcher 개인 데이터 읽기/쓰기 (원자적 저장)."""
from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG = {
    "hotkey": "win+.",
    "fallback_hotkey": "ctrl+alt+e",
    "max_results": 30,
    "position": "cursor",
}

USER_TAGS_EXAMPLE = {
    "_설명": "이모지를 키로, 태그 목록을 값으로 적으세요. 저장 후 트레이 메뉴 '개인 태그 다시 읽기'. 이 줄은 지워도 됩니다.",
    "🔥": ["긴급", "핫픽스"],
    "🧪": ["실험실"],
}


def default_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "emoji-searcher"


def atomic_write_json(path: Path, data) -> None:
    """임시 파일에 쓴 뒤 교체한다. 저장 도중 꺼져도 원래 파일은 깨지지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
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
    data: dict
    warning: str | None = None


@dataclass
class Store:
    root: Path = field(default_factory=default_data_dir)

    @property
    def user_tags_path(self) -> Path:
        return self.root / "user_tags.json"

    @property
    def usage_path(self) -> Path:
        return self.root / "usage.json"

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- config -------------------------------------------------------
    def load_config(self) -> LoadResult:
        self.ensure()
        if not self.config_path.exists():
            atomic_write_json(self.config_path, DEFAULT_CONFIG)
            return LoadResult(dict(DEFAULT_CONFIG))
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("최상위가 객체가 아님")
        except (ValueError, OSError) as e:
            return LoadResult(dict(DEFAULT_CONFIG), f"config.json을 읽지 못해 기본값으로 동작합니다: {e}")
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(raw)
        try:
            cfg["max_results"] = max(1, int(cfg["max_results"]))
        except (TypeError, ValueError):
            cfg["max_results"] = DEFAULT_CONFIG["max_results"]
        return LoadResult(cfg)

    # ---- user tags ----------------------------------------------------
    def load_user_tags(self) -> LoadResult:
        """깨진 파일은 절대 덮어쓰지 않고, 개인 태그 없이 동작한다."""
        self.ensure()
        if not self.user_tags_path.exists():
            atomic_write_json(self.user_tags_path, USER_TAGS_EXAMPLE)
        try:
            raw = json.loads(self.user_tags_path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("최상위가 객체({})가 아님")
        except (ValueError, OSError) as e:
            return LoadResult({}, f"user_tags.json을 읽지 못했습니다. 개인 태그 없이 동작합니다.\n{e}")
        tags: dict[str, list[str]] = {}
        for k, v in raw.items():
            if isinstance(v, str):
                v = [v] if not k.startswith("_") else []
            if not isinstance(v, list):
                continue
            words = [str(t).strip() for t in v if str(t).strip()]
            key = unicodedata.normalize("NFC", str(k).strip())
            if key and words:
                tags.setdefault(key, []).extend(words)
        return LoadResult(tags)

    # ---- usage --------------------------------------------------------
    def load_usage(self) -> LoadResult:
        self.ensure()
        if not self.usage_path.exists():
            return LoadResult({})
        try:
            raw = json.loads(self.usage_path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("최상위가 객체가 아님")
            usage = {}
            for k, v in raw.items():
                usage[k] = {"count": int(v.get("count", 0)), "last_used": str(v.get("last_used", ""))}
            return LoadResult(usage)
        except (ValueError, OSError, AttributeError, TypeError) as e:
            bak = self.usage_path.with_name("usage.json.bak")
            try:
                os.replace(self.usage_path, bak)
            except OSError:
                pass
            return LoadResult({}, f"usage.json이 깨져 usage.json.bak으로 보관하고 새로 시작합니다.\n{e}")

    def record_use(self, usage: dict, emoji: str, now: datetime | None = None) -> None:
        now = now or datetime.now()
        rec = usage.setdefault(emoji, {"count": 0, "last_used": ""})
        rec["count"] = int(rec.get("count", 0)) + 1
        rec["last_used"] = now.replace(microsecond=0).isoformat()
        atomic_write_json(self.usage_path, usage)
