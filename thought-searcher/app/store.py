"""config.json, state.json 읽기와 원자적 저장. 개인 데이터는 저장소 밖 PC별 위치에 둔다."""
from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "thought-searcher"
OLD_APP_NAME = "brain-searcher"

DEFAULT_CONFIG = {
    "archive_dir": "",
    "hotkey": "ctrl+alt+h",
    "watch_dir": "",
    "code_projects_dir": "%USERPROFILE%\\.claude\\projects",
    "code_collect_minutes": 30,
    "reminder_days": 7,
    "export_page_url": "https://claude.ai/settings/data-privacy-controls",
    "open_command": ["code", "-g", "{path}:{line}"],
    "max_results": 50,
    "weights": {"title": 10.0, "body": 1.0, "same_message_bonus": 0.3, "recency": 0.2,
                "recency_half_life_days": 180},
    "extra_redact_patterns": [],
    "note_dirs": [],
    "codex_dir": "%USERPROFILE%\\.codex",
    "queue_days": 14,           # 열린 일로 보는 기간 (SPEC-queue.md)
    "queue_focus": 5,           # 크게 보여 줄 개수
    "queue_note_exclude": [],   # 큐에서 뺄 노트 폴더 (노트 폴더 기준 상대 경로)
    "journal_dir": "",          # 업무 일지 보관함 루트. 비면 일지 기능 끔
    "ask_model": "haiku",       # F2 요약 모델
    "ask_command": ["claude"],  # claude CLI가 PATH에 없으면 전체 경로로
    "ask_tail_messages": 20,    # 요약 재료: 마지막 메시지 수
    "ask_max_chars": 12000,     # 요약 재료 상한 (넘치면 오래된 쪽부터 자름)
    "ask_timeout_seconds": 120,
    "capture_dir": "",         # claude.ai 자동 수집 파일 폴더. 비면 <watch_dir>\claude-sync
    "capture_stale_hours": 3,  # 수집이 이만큼 멈추면 트레이 알림
    # 설정 창 확장 (SPEC-settings.md 3-H). 기본값은 예전 동작 그대로
    "sources": {"claude_ai": True, "chatgpt": True, "claude_code": True, "codex": True},   # 쓰는 서비스
    "queue_sources": ["claude-ai", "claude-code", "note"],   # 큐에 올릴 출처
    "ask_provider": "claude",       # F2 요약 AI: "claude" | "codex" | "off"
    "ask_model_codex": "gpt-6-luna",
    "ask_codex_effort": "low",
    "ask_command_codex": [],        # 비면 PATH의 codex, 그다음 Codex 데스크톱 앱 번들
    "setup_done": False,            # 시작 안내를 마쳤거나 건너뜀 (판정은 '시작 때 config.json이 없었음')
}

DEFAULT_STATE = {
    "first_run": "",
    "zips": {},               # sha256 -> 처리 기록
    "snapshots": {},          # 출처 -> 가져온 스냅숏 중 가장 최신 내보내기 시각
    "last_zip_import": "",
    "last_code_collect": "",
    "last_reminder": "",
    "code_files": {},         # 원본 복사 기록: 상대 경로 -> [크기, 수정 시각 ns]
    "code_sessions": {},      # md 변환 기록: 상대 경로 -> [크기, 수정 시각 ns, 원본 있음]
    "queue_closed": {},       # 큐에서 직접 닫은 일: id -> {"kind": "done"|"drop", "at": 시각}
    "capture_files": {},      # claude.ai 수집 파일: 파일 이름 -> {"mtime", "size", "updated"}
    "capture_notices": {},    # 수집 관련 알림을 마지막으로 띄운 시각: 종류 -> ISO
}


@dataclass
class Loaded:
    data: dict
    warning: str | None = None


def _env_dir(var: str, fallback_var: str) -> Path:
    v = os.environ.get(var)
    if v:
        return Path(v)
    base = Path(os.environ.get(fallback_var) or str(Path.home()))
    new = base / APP_NAME
    old = base / OLD_APP_NAME
    if not new.exists() and old.is_dir():
        # 예전 이름(brain-searcher) 시절 데이터를 한 번만 옮긴다. 실패하면 새로 시작
        try:
            os.rename(old, new)
        except OSError:
            pass
    return new


def roaming_dir() -> Path:
    return _env_dir("THOUGHT_SEARCHER_APPDATA", "APPDATA")


def local_dir() -> Path:
    return _env_dir("THOUGHT_SEARCHER_LOCALAPPDATA", "LOCALAPPDATA")


def expand(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p or ""))


def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _merge(defaults: dict, data: dict) -> dict:
    out = copy.deepcopy(defaults)
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


class Store:
    def __init__(self, roaming: Path | None = None, local: Path | None = None):
        self.root = Path(roaming) if roaming else roaming_dir()
        self.local = Path(local) if local else local_dir()
        self.config_path = self.root / "config.json"
        self.state_path = self.root / "state.json"
        self.config_broken = False
        self.config_missing = False     # load_config 때 config.json이 없었음 (첫 실행: 시작 안내)

    @property
    def index_path(self) -> Path:
        return self.local / "index.db"

    @property
    def raw_dir(self) -> Path:
        return self.local / "raw" / "claude-code"

    @property
    def log_dir(self) -> Path:
        return self.local / "logs"

    def _load(self, path: Path, defaults: dict, what: str) -> Loaded:
        if not path.exists():
            return Loaded(copy.deepcopy(defaults))
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("최상위가 객체가 아님")
            return Loaded(_merge(defaults, data))
        except (OSError, ValueError) as e:
            bak = path.with_name(path.name + ".bak")
            try:
                shutil.copy2(path, bak)
            except OSError:
                pass
            return Loaded(copy.deepcopy(defaults), f"{what} 읽기 실패({e}). {bak.name}로 보관하고 기본값으로 시작합니다.")

    def load_config(self, create: bool = True) -> Loaded:
        """create=False: 없어도 만들지 않는다(트레이 앱 첫 실행. 시작 안내를 마치거나 건너뛸 때 저장)."""
        self.config_missing = not self.config_path.exists()
        res = self._load(self.config_path, DEFAULT_CONFIG, "config.json")
        self.config_broken = res.warning is not None
        if create and not self.config_path.exists():
            try:
                atomic_json(self.config_path, res.data)
            except OSError:
                pass
        return res

    def read_raw_config(self) -> dict | None:
        """디스크의 config.json 그대로(기본값을 합치지 않음). 없거나 깨졌으면 None."""
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def config_signature(self) -> tuple[int, int] | None:
        """외부 변경 감지용 (수정 시각 ns, 크기). 파일이 없으면 None."""
        try:
            st = self.config_path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def save_config(self, data: dict) -> None:
        atomic_json(self.config_path, data)
        self.config_broken = False
        self.config_missing = False

    def load_state(self) -> Loaded:
        return self._load(self.state_path, DEFAULT_STATE, "state.json")

    def save_state(self, data: dict) -> None:
        atomic_json(self.state_path, data)
