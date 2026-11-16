"""설정 창의 로직 (SPEC-settings.md). Qt 없음.

- FIELDS: 창이 다루는 키와 종류, 범위, 탭
- shown(): config 값 -> 창에 보여 줄 값 (잘못된 값이면 기본값과 표시)
- validate(): 저장 전 검사. {키: 오류 문구}
- diff(): 바뀐 키 목록. to_save(): 디스크 파일에 바뀐 키만 덮어 쓴 내용 (창에 없는 키 보존)
- 쓰는 서비스, 큐 출처 읽기 규칙, 시작 안내 기본값, 단축키 정규화와 예약 키 검사
"""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .store import DEFAULT_CONFIG, expand

TABS = ("general", "collect", "ask", "advanced")
TAB_LABEL = {"general": "일반", "collect": "수집", "ask": "요약 AI", "advanced": "고급"}

# ---- 쓰는 서비스와 큐 출처 ------------------------------------------------------
# 화면에 보이는 순서: 회사별로 묶어 claude.ai, Claude Code, ChatGPT, Codex
SERVICES = ("claude_ai", "claude_code", "chatgpt", "codex")
SERVICE_LABEL = {"claude_ai": "claude.ai", "claude_code": "Claude Code", "chatgpt": "ChatGPT", "codex": "Codex"}
SERVICE_SOURCE = {"claude_ai": "claude-ai", "claude_code": "claude-code", "chatgpt": "chatgpt", "codex": "codex"}
QUEUE_CHOICES = ("claude-ai", "claude-code", "chatgpt", "codex", "note")
QUEUE_LABEL = {"claude-ai": "claude.ai", "claude-code": "Claude Code", "chatgpt": "ChatGPT", "codex": "Codex",
               "note": "노트"}
LEGACY_QUEUE_SOURCES = ("claude-ai", "claude-code", "note")
# zip 가져오기 모듈 이름 -> 서비스 (claude.ai 메모리 md 묶음도 claude.ai)
IMPORTER_SERVICE = {"claude-ai": "claude_ai", "claude-ai-memory-md": "claude_ai", "chatgpt": "chatgpt",
                    "claude-code": "claude_code"}
CAPTURE_SITE_SERVICE = {"claude-ai": "claude_ai", "chatgpt": "chatgpt"}
PROVIDERS = ("claude", "codex", "off")
# 화면 모드와 강조색 이름 (색 값은 theme.py 한 곳)
THEME_MODES = ("light", "dark", "system")
THEME_MODE_LABEL = {"light": "라이트", "dark": "다크", "system": "시스템"}
SEARCH_SORTS = ("recent", "relevance")
SEARCH_SORT_LABEL = {"recent": "최신", "relevance": "정확도"}
THEME_ACCENTS = ("ink_blue", "deep_teal", "sage_green", "rust")
THEME_ACCENT_LABEL = {"ink_blue": "잉크 블루", "deep_teal": "딥 틸", "sage_green": "세이지 그린", "rust": "러스트"}


def read_theme(cfg: dict) -> tuple[str, str]:
    """(모드, 강조색). 모르는 값이면 기본값."""
    mode = str(cfg.get("theme_mode") or "").strip().lower()
    accent = str(cfg.get("theme_accent") or "").strip().lower()
    return (mode if mode in THEME_MODES else DEFAULT_CONFIG["theme_mode"],
            accent if accent in THEME_ACCENTS else DEFAULT_CONFIG["theme_accent"])


def read_search_sort(cfg: dict) -> str:
    """검색 창 기본 정렬. 잘못된 값이면 기본값(recent)."""
    v = str(cfg.get("search_sort") or "").strip().lower()
    return v if v in SEARCH_SORTS else DEFAULT_CONFIG["search_sort"]


def read_sources(cfg: dict) -> dict[str, bool]:
    """쓰는 서비스. 키가 없거나 형식이 다르면 모두 켬(기존 동작)."""
    raw = cfg.get("sources")
    if not isinstance(raw, dict):
        return {s: True for s in SERVICES}
    return {s: bool(raw.get(s, True)) for s in SERVICES}


def read_queue_sources(cfg: dict) -> tuple[str, ...]:
    """큐에 올릴 출처. 키가 없거나 형식이 다르면 예전 고정값."""
    raw = cfg.get("queue_sources")
    if not isinstance(raw, list):
        return LEGACY_QUEUE_SOURCES
    return tuple(s for s in QUEUE_CHOICES if s in raw)


def read_provider(cfg: dict) -> str:
    p = str(cfg.get("ask_provider") or "claude").strip().lower()
    return p if p in PROVIDERS else "claude"


# ---- 시작 안내 기본값 (3-C-3, 3-D-2, 3-J-1) ----------------------------------------------
def guess_sources(home: Path | None = None) -> dict[str, bool]:
    """설치 흔적으로 미리 체크할 서비스. claude.ai, ChatGPT는 로컬에서 알 수 없어 체크하지 않음."""
    home = Path(home) if home else Path.home()
    return {"claude_ai": False, "chatgpt": False,
            "claude_code": (home / ".claude" / "projects").is_dir(),
            "codex": (home / ".codex").is_dir()}


def setup_provider(sources: dict) -> str:
    if sources.get("claude_code") or sources.get("claude_ai"):
        return "claude"
    if sources.get("chatgpt") or sources.get("codex"):
        return "codex"
    return "off"


def setup_queue_sources(sources: dict) -> list[str]:
    return [SERVICE_SOURCE[s] for s in SERVICES if sources.get(s)] + ["note"]


def skip_config() -> dict:
    """건너뛰기: 지금과 같은 기본값 + setup_done."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["setup_done"] = True
    return cfg


def setup_config(sources: dict, archive_dir: str = "", note_dirs=(), provider: str | None = None) -> dict:
    """시작 안내를 마쳤을 때 저장할 설정."""
    cfg = skip_config()
    cfg["sources"] = {s: bool(sources.get(s)) for s in SERVICES}
    cfg["queue_sources"] = setup_queue_sources(sources)
    cfg["ask_provider"] = provider if provider in PROVIDERS else setup_provider(sources)
    cfg["archive_dir"] = str(archive_dir or "")
    cfg["note_dirs"] = [str(p) for p in note_dirs]
    return cfg


# ---- 단축키 (3-E) -----------------------------------------------------------
MOD_ORDER = ("ctrl", "alt", "shift", "win")
_MOD_ALIAS = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift", "win": "win"}
# 가상 키 코드 -> 이름. hotkey.py의 parse_hotkey가 받는 이름과 같다 (test_settings에서 대조)
VK_NAME = {0xBE: ".", 0xBC: ",", 0xBA: ";", 0xBF: "/", 0xC0: "`", 0xBD: "-", 0xBB: "=", 0xDB: "[", 0xDD: "]",
           0xDC: "\\", 0xDE: "'", 0x20: "space"}
VK_NAME.update({c: chr(c).lower() for c in range(0x41, 0x5B)})
VK_NAME.update({c: chr(c) for c in range(0x30, 0x3A)})
VK_NAME.update({0x6F + n: f"f{n}" for n in range(1, 25)})
KEY_NAMES = frozenset(VK_NAME.values())
DEFAULT_HOTKEY = str(DEFAULT_CONFIG["hotkey"])
# 막는 키: Windows 예약, IME 전환 (CLAUDE.md 4번)
RESERVED = {"win+v": "Windows 클립보드 기록", "win+;": "Windows 이모지 패널", "win+shift+s": "Windows 화면 캡처",
            "ctrl+alt+del": "Windows 보안 화면", "ctrl+space": "IME 전환", "shift+space": "IME 전환",
            "win+l": "Windows 잠금", "alt+tab": "창 전환", "alt+f4": "창 닫기"}
# 경고만: 이 저장소의 다른 도구 기본 키 (CLAUDE.md 4번 등록부)
OTHER_TOOLS = {"win+.": "emoji-searcher", "ctrl+alt+e": "emoji-searcher", "win+shift+k": "hangul-restore",
               "ctrl+alt+k": "hangul-restore"}


def normalize_hotkey(text: str) -> str:
    """'Alt+Ctrl+H' -> 'ctrl+alt+h'. 수정 키 하나 이상 + 일반 키 하나가 아니면 ValueError."""
    parts = [p for p in str(text or "").strip().lower().replace(" ", "").split("+")]
    if not parts or any(not p for p in parts):
        raise ValueError("단축키 형식이 잘못됐습니다")
    mods, keys = set(), []
    for p in parts:
        if p in _MOD_ALIAS:
            mods.add(_MOD_ALIAS[p])
        elif p in KEY_NAMES:
            keys.append(p)
        else:
            raise ValueError(f"쓸 수 없는 키입니다: {p}")
    if not mods:
        raise ValueError("Ctrl, Alt, Shift, Win 중 하나 이상과 같이 눌러야 합니다")
    if len(keys) != 1:
        raise ValueError("수정 키와 일반 키 하나를 같이 눌러야 합니다" if not keys else "일반 키는 하나만 쓸 수 있습니다")
    return "+".join([m for m in MOD_ORDER if m in mods] + keys)


def display_hotkey(text: str) -> str:
    """'ctrl+alt+h' -> 'Ctrl+Alt+H' (메뉴, 안내 문구용)."""
    try:
        norm = normalize_hotkey(text)
    except ValueError:
        return str(text)
    out = []
    for p in norm.split("+"):
        out.append(p.capitalize() if len(p) > 1 else p.upper())
    return "+".join(out)


def check_hotkey(text: str) -> tuple[str, str, str]:
    """(정규화한 키, 오류, 경고). 오류가 있으면 저장할 수 없다."""
    try:
        norm = normalize_hotkey(text)
    except ValueError as e:
        return "", str(e), ""
    if norm in RESERVED:
        return norm, f"{display_hotkey(norm)}는 {RESERVED[norm]}에 쓰여 고를 수 없습니다", ""
    if norm in _OTHER_NORM:
        return norm, "", f"{_OTHER_NORM[norm]}가 쓰는 키입니다"
    return norm, "", ""


def _normalized_keys(table: dict) -> dict:
    out = {}
    for k, v in table.items():
        try:
            out[normalize_hotkey(k)] = v
        except ValueError:
            out[k] = v                     # ctrl+alt+del처럼 기록할 수 없는 키는 그대로
    return out


RESERVED = _normalized_keys(RESERVED)
_OTHER_NORM = _normalized_keys(OTHER_TOOLS)


def same_hotkey(a: str, b: str) -> bool:
    try:
        return normalize_hotkey(a) == normalize_hotkey(b)
    except ValueError:
        return str(a).strip().lower() == str(b).strip().lower()


# ---- 칸 정의 ----------------------------------------------------------------
@dataclass(frozen=True)
class Field:
    key: str
    tab: str
    kind: str     # hotkey path paths relpaths int sources queue_sources choice text cli command weights regexes url
    #               theme_mode theme_accent search_sort
    lo: float | None = None
    hi: float | None = None


FIELDS: tuple[Field, ...] = (
    Field("hotkey", "general", "hotkey"),
    Field("theme_mode", "general", "theme_mode"),
    Field("theme_accent", "general", "theme_accent"),
    Field("search_sort", "general", "search_sort"),
    Field("archive_dir", "general", "path"),
    Field("note_dirs", "general", "paths"),
    Field("journal_dir", "general", "path"),
    Field("queue_days", "general", "int", 1, 90),
    Field("queue_focus", "general", "int", 0, 20),
    Field("queue_sources", "general", "queue_sources"),
    Field("queue_note_exclude", "general", "relpaths"),
    Field("sources", "collect", "sources"),
    Field("watch_dir", "collect", "path"),
    Field("capture_dir", "collect", "path"),
    Field("code_projects_dir", "collect", "path"),
    Field("codex_dir", "collect", "path"),
    Field("code_collect_minutes", "collect", "int", 5, 240),
    Field("reminder_days", "collect", "int", 0, 60),          # 0 = 끔
    Field("capture_stale_hours", "collect", "int", 1, 72),
    Field("ask_provider", "ask", "choice"),
    Field("ask_model", "ask", "text"),
    Field("ask_model_codex", "ask", "text"),
    Field("ask_codex_effort", "ask", "text"),
    Field("ask_command", "ask", "cli"),
    Field("ask_command_codex", "ask", "cli"),
    Field("open_command", "advanced", "command"),
    Field("max_results", "advanced", "int", 10, 500),
    Field("weights", "advanced", "weights"),
    Field("extra_redact_patterns", "advanced", "regexes"),
    Field("ask_tail_messages", "advanced", "int", 1, 200),
    Field("ask_max_chars", "advanced", "int", 1000, 100000),
    Field("ask_timeout_seconds", "advanced", "int", 10, 600),
    Field("export_page_url", "advanced", "url"),
)
FIELD = {f.key: f for f in FIELDS}
NOT_IN_WINDOW = frozenset({"setup_done"})     # 창에 칸이 없는 DEFAULT_CONFIG 키
# 가중치 5개: (키, 이름, 최소, 최대)
WEIGHTS = (("title", "제목", 0.0, 100.0), ("body", "본문", 0.0, 100.0), ("same_message_bonus", "같은 메시지 가산", 0.0, 10.0),
           ("recency", "최근 가산", 0.0, 10.0), ("recency_half_life_days", "반감기", 1.0, 3650.0))
# 서비스를 끄면 검사하지 않는(비활성) 칸
FIELD_SERVICE = {"code_projects_dir": "claude_code", "codex_dir": "codex", "reminder_days": "claude_ai"}
ARCHIVE_KEY = "archive_dir"


def tab_of(err_key: str) -> str:
    return FIELD[err_key.split(".", 1)[0]].tab


def _num(value, integer: bool) -> float | None:
    if isinstance(value, bool):
        return None
    if integer:
        if isinstance(value, int):
            return float(value)
        if isinstance(value, float) and value.is_integer():
            return value
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _range_error(value, lo, hi, integer: bool = True) -> str:
    n = _num(value, integer)
    if n is None:
        return "정수가 아닙니다" if integer else "숫자가 아닙니다"
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        fmt = (lambda x: f"{int(x)}") if integer else (lambda x: f"{x:g}")
        return f"{fmt(lo)}~{fmt(hi)} 사이로 넣으세요"
    return ""


def _str_list(value) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        return None
    return value


def as_command(value) -> list[str]:
    """'claude' 또는 ['claude', ...] -> 목록."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(x) for x in value]
    return []


def field_error(key: str, value) -> str:
    """값 하나의 형식과 범위 검사 (파일 시스템은 보지 않음). 맞으면 빈 문자열."""
    f = FIELD[key]
    k = f.kind
    if k == "int":
        return _range_error(value, f.lo, f.hi)
    if k == "hotkey":
        return check_hotkey(str(value or ""))[1] if isinstance(value, str) else "글자가 아닙니다"
    if k == "path":
        return "" if isinstance(value, str) else "경로 글자가 아닙니다"
    if k in ("paths", "relpaths", "regexes"):
        items = _str_list(value)
        if items is None:
            return "목록 형식이 아닙니다"
        if k == "relpaths":
            for p in items:
                s = p.strip()
                if not s:
                    continue
                if os.path.isabs(s) or re.match(r"^[A-Za-z]:", s) or s.startswith(("\\", "/")):
                    return f"노트 폴더 기준 상대 경로여야 합니다: {p}"
                if ".." in re.split(r"[\\/]+", s):
                    return f"'..'은 쓸 수 없습니다: {p}"
        if k == "regexes":
            for i, p in enumerate(items, 1):
                try:
                    re.compile(p)
                except re.error as e:
                    return f"{i}번째 줄: {e}"
        return ""
    if k == "sources":
        if value is None:
            return ""
        if not isinstance(value, dict) or not all(isinstance(value.get(s, True), bool) for s in SERVICES):
            return "형식이 잘못됐습니다"
        return ""
    if k == "queue_sources":
        items = _str_list(value)
        if items is None:
            return "목록 형식이 아닙니다"
        bad = [x for x in items if x not in QUEUE_CHOICES]
        return f"알 수 없는 출처: {', '.join(bad)}" if bad else ""
    if k == "choice":
        return "" if value in PROVIDERS else "claude, codex, off 중 하나여야 합니다"
    if k == "theme_mode":
        return "" if value in THEME_MODES else f"{', '.join(THEME_MODES)} 중 하나여야 합니다"
    if k == "search_sort":
        return "" if value in SEARCH_SORTS else f"{', '.join(SEARCH_SORTS)} 중 하나여야 합니다"
    if k == "theme_accent":
        return "" if value in THEME_ACCENTS else f"{', '.join(THEME_ACCENTS)} 중 하나여야 합니다"
    if k == "text":
        if not isinstance(value, str) or not value.strip():
            return "비어 있습니다"
        if key == "ask_codex_effort" and not re.fullmatch(r"[A-Za-z_-]+", value.strip()):
            return "low, medium 같은 이름이어야 합니다"
        return ""
    if k == "cli":
        if isinstance(value, str):
            return ""
        return "" if _str_list(value) is not None else "명령 형식이 아닙니다"
    if k == "command":
        items = _str_list(value)
        if not items:
            return "명령이 비어 있습니다"
        if not any("{path}" in a for a in items):
            return "{path}가 들어 있어야 합니다"
        return ""
    if k == "weights":
        if not isinstance(value, dict):
            return "형식이 잘못됐습니다"
        for wk, _name, lo, hi in WEIGHTS:
            if wk in value and _range_error(value[wk], lo, hi, integer=False):
                return f"{wk}: {_range_error(value[wk], lo, hi, integer=False)}"
        return ""
    if k == "url":
        if not isinstance(value, str) or not value.strip().lower().startswith("https://"):
            return "https:// 로 시작해야 합니다"
        return ""
    return ""


def default_of(key: str):
    return copy.deepcopy(DEFAULT_CONFIG[key])


def shown(key: str, cfg: dict) -> tuple[object, bool]:
    """창에 보여 줄 값과 '잘못된 값이라 기본값을 보여 줌' 여부."""
    if key not in cfg:
        return default_of(key), False
    v = cfg[key]
    if key == "weights":
        base = default_of("weights")
        if not isinstance(v, dict):
            return base, True
        bad = False
        for wk, _n, lo, hi in WEIGHTS:
            if wk in v:
                if _range_error(v[wk], lo, hi, integer=False):
                    bad = True
                else:
                    base[wk] = float(v[wk])
        return base, bad
    if key == "sources":
        return read_sources(cfg), bool(field_error(key, v))
    if field_error(key, v):
        return default_of(key), True
    return copy.deepcopy(v), False


# ---- 저장 전 검사 (3-G) ------------------------------------------------------
def _norm_path(p: str) -> str:
    return os.path.normcase(os.path.abspath(expand(str(p)).strip()))


def _changed(key: str, new: dict, old: dict | None) -> bool:
    return old is None or new.get(key) != old.get(key)


def validate(new: dict, old: dict | None = None) -> dict[str, str]:
    """{키: 오류 문구}. 경로 존재 검사는 바뀐 값만 (손대지 않은 값 때문에 저장이 막히지 않게).
    보관 폴더는 없어도 여기서는 통과시킨다(창이 '만들까요?'를 묻는다, archive_missing 참고)."""
    errs: dict[str, str] = {}
    src = read_sources(new)
    for f in FIELDS:
        if f.key not in new:
            continue
        v = new[f.key]
        svc = FIELD_SERVICE.get(f.key)
        if svc and not src[svc]:
            continue
        e = field_error(f.key, v)
        if e:
            errs[f.key] = e
            continue
        # 기본값(예: %USERPROFILE%\.codex)은 없어도 통과: 그 도구를 안 쓰는 PC일 수 있다
        if f.kind == "path" and f.key != ARCHIVE_KEY and isinstance(v, str) and v.strip() \
                and v.strip() != str(DEFAULT_CONFIG.get(f.key, "")) \
                and _changed(f.key, new, old) and not Path(expand(v.strip())).is_dir():
            errs[f.key] = f"폴더가 없습니다: {v.strip()}"
        elif f.kind == "paths":
            seen: set[str] = set()
            old_items = {_norm_path(p) for p in (old or {}).get(f.key) or [] if isinstance(p, str)}
            for p in v:
                if not p.strip():
                    continue
                n = _norm_path(p)
                if n in seen:
                    errs[f.key] = f"같은 폴더가 두 번 들어 있습니다: {p}"
                    break
                seen.add(n)
                if n not in old_items and not Path(expand(p.strip())).is_dir():
                    errs[f.key] = f"폴더가 없습니다: {p}"
                    break
        elif f.kind == "cli" and _changed(f.key, new, old):
            cmd = as_command(v)
            first = expand(cmd[0]).strip() if cmd else ""
            if first and ("\\" in first or "/" in first) and not Path(first).is_file():
                errs[f.key] = f"파일이 없습니다: {first}"
    # 보관 폴더와 노트 폴더 (보관 폴더가 노트 폴더 안에 있는 것은 허용)
    arch = str(new.get(ARCHIVE_KEY) or "").strip()
    notes = [p for p in (new.get("note_dirs") or []) if isinstance(p, str) and p.strip()] \
        if isinstance(new.get("note_dirs"), list) else []
    if arch and any(_norm_path(p) == _norm_path(arch) for p in notes):
        errs.setdefault(ARCHIVE_KEY, "노트 폴더와 같은 폴더는 보관 폴더로 쓸 수 없습니다")
        errs.setdefault("note_dirs", "보관 폴더와 같은 폴더는 노트 폴더로 넣을 수 없습니다")
    return errs


def archive_missing(new: dict) -> str:
    """보관 폴더를 직접 골랐는데 없으면 그 경로 (창이 '폴더를 만들까요?'를 묻는다)."""
    arch = str(new.get(ARCHIVE_KEY) or "").strip()
    if arch and not Path(expand(arch)).is_dir():
        return expand(arch)
    return ""


def warnings(new: dict) -> dict[str, str]:
    """저장은 막지 않는 경고."""
    out: dict[str, str] = {}
    if not any(read_sources(new).values()):
        out["sources"] = "수집할 서비스가 없습니다. 노트 폴더만 검색합니다"
    hk = new.get("hotkey")
    if isinstance(hk, str):
        w = check_hotkey(hk)[2]
        if w:
            out["hotkey"] = w
    return out


# ---- 바뀐 키와 저장 ------------------------------------------------------------
def diff(old: dict, new: dict) -> set[str]:
    """값이 다른 키 (weights 안쪽 값 하나만 달라도 weights)."""
    return {k for k in set(old) | set(new) if old.get(k, _MISSING) != new.get(k, _MISSING)}


_MISSING = object()


def to_save(raw: dict | None, new: dict, changed: set[str]) -> dict:
    """디스크에 쓸 내용. raw(디스크 파일)가 있으면 바뀐 키만 덮어 쓰고 나머지(손으로 넣은 키)는 그대로 둔다.
    raw가 없으면(첫 실행, 깨진 파일) new 전체."""
    if raw is None:
        return copy.deepcopy(new)
    out = copy.deepcopy(raw)
    for k in sorted(changed):
        if k in new:
            out[k] = copy.deepcopy(new[k])
        else:
            out.pop(k, None)
    return out


# ---- 명령 줄 (open_command) ----------------------------------------------------
def split_command(text: str) -> list[str]:
    """공백으로 나누고 큰따옴표로 묶은 부분은 한 칸으로 (Windows 경로의 \\는 그대로)."""
    out, cur, quoted, has = [], [], False, False
    for ch in str(text or ""):
        if ch == '"':
            quoted = not quoted
            has = True
        elif ch.isspace() and not quoted:
            if cur or has:
                out.append("".join(cur))
            cur, has = [], False
        else:
            cur.append(ch)
    if cur or has:
        out.append("".join(cur))
    return out


def join_command(args) -> str:
    return " ".join(f'"{a}"' if (not a or any(c.isspace() for c in a)) else a for a in as_command(args))
