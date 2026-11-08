"""%APPDATA%\\hangul-restore 의 config.json, hints.json 읽기.

없으면 기본값을 복사해 두고, 깨져 있으면 기본값으로 동작하되 파일은 덮어쓰지 않는다.
사용 기록은 저장하지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from restore.hints import Rule, default_rules, parse_rules

TOOL_DIR = Path(__file__).resolve().parent.parent
DEFAULTS = TOOL_DIR / "defaults"


def default_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "hangul-restore"


def _default_config() -> dict:
    try:
        return json.loads((DEFAULTS / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"hotkey": "win+shift+k", "fallback_hotkey": "ctrl+alt+k",
                "max_depth": 3, "max_candidates": 5, "max_input_chars": 20000}


@dataclass
class Loaded:
    config: dict
    rules: list[Rule]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Store:
    root: Path = field(default_factory=default_data_dir)

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def hints_path(self) -> Path:
        return self.root / "hints.json"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("config.json", "hints.json"):
            target = self.root / name
            if not target.exists():
                try:
                    shutil.copyfile(DEFAULTS / name, target)
                except OSError:
                    pass

    def load(self) -> Loaded:
        warnings: list[str] = []
        try:
            self.ensure()
        except OSError as e:
            warnings.append(f"데이터 폴더를 만들지 못했습니다: {e}")

        cfg = _default_config()
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("최상위가 객체가 아님")
            cfg.update(raw)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            warnings.append(f"config.json을 읽지 못해 기본값으로 동작합니다.\n{e}")

        rules = default_rules()
        try:
            rules = parse_rules(json.loads(self.hints_path.read_text(encoding="utf-8-sig")))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as e:
            warnings.append(f"hints.json을 읽지 못해 기본 힌트로 동작합니다.\n{e}")
        return Loaded(cfg, rules, warnings)
