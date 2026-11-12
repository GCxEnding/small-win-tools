"""화면 없는 본체: 설정/상태, zip 가져오기, Code 수집, 색인. 트레이 앱과 CLI가 함께 쓴다."""
from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import ask, cli_check, codex, collector, queue, settings
from .journal import JournalReader
from .archive import Archive, ArchiveMissing, FORMAT_VERSION, md_files, read_front_file
from .importers import ImportFailed, detect
from .importers import claude_capture
from .index import Index
from .redact import Redactor
from .store import Store, expand
from .timeutil import local_tz, parse_iso
from .watcher import downloads_dir, sha256_file

log = logging.getLogger("thought-searcher")


def setup_logging(store: Store) -> None:
    if any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        return
    try:
        store.log_dir.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(store.log_dir / "thought-searcher.log", maxBytes=1_000_000, backupCount=3,
                                encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    except OSError:
        pass


@dataclass
class ZipOutcome:
    result: str                  # "ok" | "skipped" | "ignored" | "failed" | "no_archive" | "off"(끈 서비스)
    importer: str = ""
    counts: dict = field(default_factory=dict)
    reason: str = ""
    written: list[Path] = field(default_factory=list)

    def message(self) -> str:
        c = self.counts
        if self.result == "failed":
            return f"claude.ai 가져오기 실패: {self.reason}"
        s = f"claude.ai 가져오기 완료: 새 대화 {c.get('new', 0)}, 바뀜 {c.get('changed', 0)}"
        if c.get("skipped"):
            s += f", 건너뜀 {c['skipped']}"
        return s


@dataclass
class CaptureResult:
    new: int = 0
    changed: int = 0
    not_ready: int = 0
    removed: int = 0              # 수집 제외로 지운 md
    failed: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Core:
    def __init__(self, store: Store | None = None, tz=None, create_config: bool = True):
        """create_config=False: config.json이 없어도 만들지 않는다(트레이 앱. 시작 안내 뒤에 저장)."""
        self.store = store or Store()
        setup_logging(self.store)
        self.tz = tz or local_tz()
        self.lock = threading.RLock()
        self.warnings: list[str] = []
        cfg = self.store.load_config(create=create_config)
        self.config = cfg.data
        self._warn(cfg.warning)
        st = self.store.load_state()
        self.state = st.data
        self._warn(st.warning)
        if not self.state.get("first_run"):
            self.state["first_run"] = _now_iso()
            self.save_state()
        self.redactor = Redactor(self.config.get("extra_redact_patterns") or [])
        for e in self.redactor.errors:
            self._warn(e)
        self.index = Index(self.store.index_path)
        self.index.tz = self.tz
        self._apply_note_dirs()
        self._journal = JournalReader()
        self._journal_warned = False
        self.summaries = ask.SummaryStore(self.store.local / "summaries.json")

    # ---- 공통 -----------------------------------------------------------
    def _warn(self, msg: str | None) -> None:
        if msg:
            log.warning(msg)
            self.warnings.append(f"{datetime.now():%m-%d %H:%M} {msg}")
            del self.warnings[:-20]

    def save_state(self) -> None:
        with self.lock:
            try:
                self.store.save_state(self.state)
            except OSError as e:
                self._warn(f"state.json 저장 실패: {e}")

    @property
    def default_archive(self) -> Path:
        return self.store.local / "archive"

    @property
    def archive_dir(self) -> Path | None:
        p = expand(str(self.config.get("archive_dir") or ""))
        if p:
            return Path(p)
        # 비어 있으면 기본 위치. 기본 위치는 없으면 만든다 (사용자가 고른 폴더는 만들지 않음)
        d = self.default_archive
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return d

    def archive_ok(self) -> bool:
        d = self.archive_dir
        return bool(d and d.is_dir())

    def archive(self) -> Archive:
        d = self.archive_dir
        if not d or not d.is_dir():
            raise ArchiveMissing(f"보관 폴더가 없습니다: {d or '(설정 안 됨)'}")
        return Archive(d, self.tz, self.redactor)

    def set_archive_dir(self, path: Path) -> None:
        self.config["archive_dir"] = str(path)
        self.store.save_config(self.config)
        self._apply_note_dirs()

    # ---- 설정 창 (SPEC-settings.md) ---------------------------------------------
    @property
    def sources(self) -> dict[str, bool]:
        return settings.read_sources(self.config)

    def service_on(self, service: str) -> bool:
        return self.sources.get(service, True)

    def update_config(self, new: dict) -> set[str]:
        """설정 창 저장: 바뀐 키만 디스크 파일에 덮어 쓰고(손으로 넣은 키 보존) 본체 쪽 적용까지. 바뀐 키를 돌려준다.
        self.config는 통째로 새 dict로 바꾼다(작업 스레드가 읽던 옛 dict는 그대로 남아 옛 값으로 끝남)."""
        old = self.config
        changed = settings.diff(old, new)
        raw = None if (self.store.config_broken or self.store.config_missing) else self.store.read_raw_config()
        self.store.save_config(settings.to_save(raw, new, changed))
        self.config = new
        if "extra_redact_patterns" in changed:
            self.redactor = Redactor(new.get("extra_redact_patterns") or [])
            for e in self.redactor.errors:
                self._warn(e)
        if changed & {"note_dirs", "archive_dir"}:
            self._apply_note_dirs()
        if "journal_dir" in changed:
            self._journal_warned = False
        return changed

    def reload_config(self) -> set[str]:
        """config.json을 다시 읽어 바꾼다(설정 창 '다시 읽기'). 저장하지 않는다. 바뀐 키를 돌려준다."""
        res = self.store.load_config(create=False)
        self._warn(res.warning)
        new = res.data
        changed = settings.diff(self.config, new)
        self.config = new
        if "extra_redact_patterns" in changed:
            self.redactor = Redactor(new.get("extra_redact_patterns") or [])
        if changed & {"note_dirs", "archive_dir"}:
            self._apply_note_dirs()
        return changed

    # ---- 노트 폴더 ----------------------------------------------------------
    @property
    def note_dirs(self) -> list[Path]:
        raw = self.config.get("note_dirs") or []
        return [Path(expand(str(p))) for p in raw if isinstance(p, str) and p.strip()]

    def _apply_note_dirs(self) -> None:
        self.index.note_roots = self.note_dirs
        d = self.archive_dir if self.config.get("archive_dir") or self.default_archive.is_dir() else None
        self.index.note_exclude = [d] if d else []

    def add_note_dir(self, path: Path) -> bool:
        """노트 폴더 추가. 이미 있으면 False."""
        key = str(Path(path))
        cur = [str(p) for p in self.config.get("note_dirs") or []]
        if any(Path(expand(p)) == Path(key) for p in cur):
            return False
        self.config["note_dirs"] = cur + [key]
        self.store.save_config(self.config)
        self._apply_note_dirs()
        return True

    def remove_note_dir(self, path: Path) -> None:
        cur = [str(p) for p in self.config.get("note_dirs") or []]
        self.config["note_dirs"] = [p for p in cur if Path(expand(p)) != Path(path)]
        self.store.save_config(self.config)
        self._apply_note_dirs()

    def sync_notes(self, progress=None):
        res = self.index.sync_notes(progress)
        missing = [str(p) for p in self.note_dirs if not p.is_dir()]
        if missing:
            self._warn("노트 폴더가 없습니다: " + ", ".join(missing))
        return res

    @property
    def watch_dir(self) -> Path:
        p = expand(str(self.config.get("watch_dir") or ""))
        return Path(p) if p else downloads_dir()

    @property
    def projects_dir(self) -> Path:
        return Path(expand(str(self.config.get("code_projects_dir") or "%USERPROFILE%\\.claude\\projects")))

    @property
    def codex_dir(self) -> Path:
        return Path(expand(str(self.config.get("codex_dir") or "%USERPROFILE%\\.codex")))

    def reindex_paths(self, paths: list[Path]) -> None:
        if paths and self.archive_dir:
            self.index.sync(self.archive_dir, only=paths)

    # ---- zip --------------------------------------------------------------
    def known_zip(self, path: Path) -> bool:
        """같은 경로, 크기, 수정 시각으로 이미 처리한 zip이면 해시 계산도 건너뛴다."""
        try:
            st = path.stat()
        except OSError:
            return False
        key = [str(path), st.st_size, st.st_mtime]
        for rec in self.state.get("zips", {}).values():
            if key in rec.get("seen", []) or [rec.get("path"), rec.get("size"), rec.get("mtime")] == key:
                return True
        return False

    def import_zip(self, path: Path, force: bool = False) -> ZipOutcome:
        path = Path(path)
        if not self.archive_ok():
            return ZipOutcome("no_archive", reason="보관 폴더 없음")
        try:
            digest = sha256_file(path)
            st = path.stat()
        except OSError as e:
            return ZipOutcome("failed", reason=str(e))
        with self.lock:
            prev = self.state["zips"].get(digest)
        if prev and not force:
            # 같은 내용의 다른 이름 zip도 기억해 두어 다음부터는 해시도 계산하지 않는다
            with self.lock:
                seen = prev.setdefault("seen", [])
                key = [str(path), st.st_size, st.st_mtime]
                if key not in seen:
                    seen.append(key)
                    del seen[:-20]
                    log.info("이미 가져온 zip과 내용이 같음: %s", path)
            self.save_state()
            return ZipOutcome("skipped")
        imp = detect(path)
        svc = settings.IMPORTER_SERVICE.get(imp.name) if imp is not None else None
        if svc and not self.service_on(svc):
            # 끈 서비스의 zip: 가져오지 않고 이력에도 남기지 않는다(나중에 켜면 다음 확인 때 가져옴)
            log.info("끈 서비스(%s)의 zip이라 건너뜀: %s", svc, path)
            return ZipOutcome("off", importer=imp.name)
        rec = {"name": path.name, "path": str(path), "size": st.st_size, "mtime": st.st_mtime,
               "processed_at": _now_iso(), "export_time": "", "result": "", "counts": {}, "importer": ""}
        out = self._import(path, rec, imp)
        rec["result"] = out.result
        rec["importer"] = out.importer
        rec["counts"] = out.counts
        if out.reason:
            rec["reason"] = out.reason
        with self.lock:
            self.state["zips"][digest] = rec
            if out.result == "ok" and out.importer == "claude-ai":
                self.state["last_zip_import"] = rec["processed_at"]
        self.save_state()
        if out.result == "failed":
            self._warn(f"{path.name}: {out.reason}")
        return out

    def _import(self, path: Path, rec: dict, imp=None) -> ZipOutcome:
        if imp is None:
            import zipfile
            if not zipfile.is_zipfile(path):
                return ZipOutcome("failed", reason="zip 파일이 아니거나 깨짐")
            return ZipOutcome("ignored")
        out = ZipOutcome("ok", importer=imp.name)
        counts = {"new": 0, "changed": 0, "same": 0, "older": 0, "missing": 0, "skipped": 0}
        try:
            archive = self.archive()
            snap = imp.snapshot_time(path) if imp.is_full_snapshot() else None
            sources = imp.snapshot_sources(path) if imp.is_full_snapshot() else set()
            rec["export_time"] = snap.isoformat() if snap else ""
            seen: set[str] = set()

            def on_skip(msg):
                counts["skipped"] += 1
                log.warning(msg)

            ex = self.capture_exclude if imp.name == "claude-ai" else None
            for conv in imp.iter_conversations(path, on_skip):
                seen.add(conv.conv_id)
                if ex:
                    conv = self._drop_excluded(conv, ex)
                    if conv is None:
                        counts["excluded"] = counts.get("excluded", 0) + 1
                        continue
                r = archive.write(conv, status="present", skip_if_older=True)
                counts[r.status] += 1
                if r.status in ("new", "changed"):
                    out.written.append(r.path)
                    if r.old_path:
                        out.written.append(r.old_path)
            # 사라진 대화: 지금까지 가져온 스냅숏 중 가장 최신일 때만
            for src in sources:
                with self.lock:
                    latest = parse_iso(self.state["snapshots"].get(src))
                if snap is None or (latest and snap < latest):
                    continue
                with self.lock:
                    self.state["snapshots"][src] = snap.isoformat()
                for p, meta in archive.iter_docs({src}):
                    if meta["id"] in seen:
                        continue
                    if archive.set_status(p, "missing"):
                        counts["missing"] += 1
                        out.written.append(p)
        except ImportFailed as e:
            return ZipOutcome("failed", importer=imp.name, reason=str(e))
        except ArchiveMissing as e:
            return ZipOutcome("no_archive", importer=imp.name, reason=str(e))
        out.counts = counts
        self.reindex_paths(out.written)
        return out

    # ---- claude.ai 자동 수집 (SPEC-queue.md 3-D, 3-E) ------------------------------
    @property
    def capture_dir(self) -> Path:
        p = expand(str(self.config.get("capture_dir") or ""))
        return Path(p) if p else self.watch_dir / "claude-sync"

    @property
    def capture_raw_dir(self) -> Path:
        return self.store.local / "raw" / "claude-ai-capture"

    def site_on(self, site: str) -> bool:
        return self.service_on(settings.CAPTURE_SITE_SERVICE.get(site, "claude_ai"))

    def _capture_files(self, folder: Path) -> list[Path]:
        """켠 서비스의 수집 파일만 (끈 서비스 파일은 이력에도 남기지 않아 나중에 켜면 가져온다)."""
        return [p for p in claude_capture.capture_files(folder) if self.site_on(claude_capture.site_of(p.name))]

    def pending_captures(self) -> list[Path]:
        """처리 기록과 크기나 수정 시각이 다른 수집 파일."""
        try:
            files = self._capture_files(self.capture_dir)
        except OSError:
            return []
        out = []
        with self.lock:
            seen = self.state.setdefault("capture_files", {})
            for p in files:
                try:
                    st = p.stat()
                except OSError:
                    continue
                rec = seen.get(p.name)
                if not rec or rec.get("size") != st.st_size or rec.get("mtime") != st.st_mtime:
                    out.append(p)
        return out

    def import_captures(self, force: bool = False) -> CaptureResult:
        """바뀐 수집 파일만 읽어 보관본에 넣는다. 덜 써진 파일은 다음 확인 때 다시 본다. 파일은 지우지 않는다."""
        res = CaptureResult()
        if not self.archive_ok():
            res.failed.append("보관 폴더 없음")
            return res
        if self.site_on("claude-ai") and (force or self.exclusions_pending()):
            res.removed = len(self.apply_exclusions())
        if force:
            try:
                files = self._capture_files(self.capture_dir)
            except OSError:
                files = []
        else:
            files = self.pending_captures()
        if not files:
            return res
        archive = self.archive()
        raw = self.capture_raw_dir
        ex = self.capture_exclude
        for p in files:
            if claude_capture.capture_uuid(p.name) in ex.conversations:
                try:
                    p.unlink()                 # 뺀 대화: 가져오지 않고 다운로드 폴더에서도 지운다
                except OSError as e:
                    log.warning("뺀 대화 수집 파일을 지우지 못함 %s: %s", p.name, e)
                continue
            try:
                st = p.stat()
                conv = claude_capture.read_capture(p)
            except claude_capture.NotReady as e:
                res.not_ready += 1
                log.info("수집 파일 다음에 다시: %s (%s)", p.name, e)
                continue
            except (ImportFailed, OSError) as e:
                res.failed.append(str(e))
                log.warning("수집 파일 실패: %s", e)
                with self.lock:   # 같은 내용으로 계속 실패하지 않게 기록 (파일이 바뀌면 다시 읽음)
                    self.state["capture_files"][p.name] = {"mtime": st.st_mtime, "size": st.st_size,
                                                           "updated": "", "error": str(e)[:200]}
                continue
            try:
                raw.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, raw / p.name)
            except OSError as e:
                log.warning("수집 원본 복사 실패: %s", e)
            updated = ""
            if conv is not None:
                try:
                    r = archive.write(conv, status="present", skip_if_older=True)
                except ArchiveMissing as e:
                    res.failed.append(str(e))
                    break
                updated = conv.updated.isoformat()
                if r.status == "new":
                    res.new += 1
                elif r.status == "changed":
                    res.changed += 1
                if r.status in ("new", "changed"):
                    res.written.append(r.path)
                    if r.old_path:
                        res.written.append(r.old_path)
            with self.lock:
                self.state["capture_files"][p.name] = {"mtime": st.st_mtime, "size": st.st_size, "updated": updated}
                self.state["last_capture_import"] = _now_iso()
        self.save_state()
        self.reindex_paths(res.written)
        return res

    def misplaced_captures(self) -> int:
        """Tampermonkey 다운로드 설정이 기본값이면 하위 폴더 대신 다운로드 폴더 바로 아래에 쌓인다."""
        try:
            return len(self._capture_files(self.watch_dir))
        except OSError:
            return 0

    def capture_notice(self, now: datetime | None = None) -> str | None:
        """띄울 수집 알림 하나 (멈춤: 사이트마다 하루 한 번, 저장 위치 잘못: 한 번). 띄우면 기록한다."""
        now = now or datetime.now(timezone.utc)
        with self.lock:
            sent = self.state.setdefault("capture_notices", {})
        if self.misplaced_captures() and not sent.get("misplaced"):
            with self.lock:
                sent["misplaced"] = now.isoformat()
            self.save_state()
            return ("자동 수집 파일이 다운로드 폴더 바로 아래에 저장되고 있습니다.\n"
                    "Tampermonkey 다운로드 설정(브라우저 API 모드)을 확인하세요.")
        hours = max(1, self._int_cfg("capture_stale_hours", 3))
        for site, label in claude_capture.SITE_LABEL.items():
            if not self.site_on(site):
                continue
            status = claude_capture.read_status(self.capture_dir, site)
            ok = claude_capture.last_ok(status)
            if status is None or ok is None:
                continue     # 이 사이트를 한 번도 수집하지 않은 PC에서는 알리지 않음
            age = (now - ok).total_seconds() / 3600
            if age < hours:
                continue
            key = "stale" if site == "claude-ai" else f"stale:{site}"
            last = parse_iso(sent.get(key))
            if last and (now - last).total_seconds() < 24 * 3600:
                continue
            with self.lock:
                sent[key] = now.isoformat()
            self.save_state()
            err = str(status.get("error") or "")
            tail = f"마지막 오류: {err[:120]}" if err else f"{label} 탭이 열려 있는지 확인하세요."
            return f"{label} 자동 수집이 {int(age)}시간째 멈춰 있습니다.\n{tail}"
        return None

    def capture_site_status(self, site: str) -> str:
        """설정 창 수집 탭의 사이트별 한 줄 (3-I-4)."""
        status = claude_capture.read_status(self.capture_dir, site)
        if status is None:
            return "아직 수집 기록 없음"
        fmt = (lambda dt: dt.astimezone(self.tz).strftime("%m-%d %H:%M"))
        err = str(status.get("error") or "").strip()
        if err:
            run = parse_iso(status.get("last_run")) or claude_capture.last_ok(status)
            return f"오류: {err[:120]}" + (f" ({fmt(run)})" if run else "")
        ok = claude_capture.last_ok(status)
        if ok is None:
            return "아직 수집 기록 없음"
        n = sum(1 for x in (self.state.get("capture_files") or {}) if claude_capture.site_of(x) == site)
        return f"마지막 성공 {fmt(ok)}, 대화 {n}개"

    def capture_status_line(self) -> str:
        lines = []
        names = list(self.state.get("capture_files") or {})
        for site, label in claude_capture.SITE_LABEL.items():
            if not self.site_on(site):
                continue
            status = claude_capture.read_status(self.capture_dir, site)
            if status is None:
                continue
            ok = claude_capture.last_ok(status)
            when = ok.astimezone(self.tz).strftime("%m-%d %H:%M") if ok else "없음"
            n = sum(1 for x in names if claude_capture.site_of(x) == site)
            err = f", 오류: {status['error']}" if status.get("error") else ""
            lines.append(f"{label} 자동 수집: 마지막 성공 {when}, 대화 {n}개{err}")
        return "\n".join(lines) or "자동 수집: 없음"

    # ---- 수집 제외 (claude.ai, Tampermonkey 메뉴에서 뺀 대화와 프로젝트) -------------------------
    def _status_sig(self) -> list | None:
        try:
            st = (self.capture_dir / claude_capture.STATUS_NAME).stat()
        except OSError:
            return None
        return [st.st_mtime, st.st_size]

    def exclusions_pending(self) -> bool:
        """상태 파일이 바뀌어 제외 목록을 다시 볼 때가 됐는지 (2초 확인용, 파일 stat만)."""
        if not self.site_on("claude-ai"):
            return False
        sig = self._status_sig()
        with self.lock:
            return sig is not None and sig != self.state.get("capture_exclude_sig")

    @property
    def capture_exclude(self) -> claude_capture.Exclude:
        """지금 제외 목록. 상태 파일이 없거나 예전 형식이면 마지막으로 읽은 목록을 쓴다(state.json에 보관)."""
        ex = claude_capture.read_exclude(claude_capture.read_status(self.capture_dir, "claude-ai"))
        if ex is not None:
            return ex
        with self.lock:
            return claude_capture.Exclude.from_json(self.state.get("capture_exclude"))

    def apply_exclusions(self) -> list[Path]:
        """제외 목록에 든 대화의 기존 흔적을 지운다: 보관 md(대화, 프로젝트 문서), 다운로드 폴더의 수집 파일과
        앱의 원본 사본, 요약, 큐 닫기 기록. 지운 md 경로(색인 갱신용)를 돌려준다."""
        sig = self._status_sig()
        ex = self.capture_exclude
        with self.lock:
            self.state["capture_exclude"] = ex.to_json()
            self.state["capture_exclude_sig"] = sig
        removed: list[Path] = []
        if ex and self.archive_ok():
            archive = self.archive()
            ids = [f"claude-ai:{u}" for u in ex.conversations] + [f"claude-ai-project:{u}" for u in ex.projects]
            for cid in ids:
                p = archive.find(cid)
                if p is None:
                    continue
                try:
                    p.unlink()
                    removed.append(p)
                except OSError as e:
                    log.warning("뺀 대화 md를 지우지 못함 %s: %s", p, e)
            for u in ex.conversations:
                for folder in (self.capture_dir, self.watch_dir, self.capture_raw_dir):
                    try:
                        (folder / f"claude-ai_{u}.json").unlink(missing_ok=True)
                    except OSError as e:
                        log.warning("뺀 대화 수집 파일을 지우지 못함 %s: %s", u, e)
            with self.lock:
                closed = self.state.setdefault("queue_closed", {})
                for cid in ids:
                    closed.pop(cid, None)
                for u in ex.conversations:
                    self.state.setdefault("capture_files", {}).pop(f"claude-ai_{u}.json", None)
                self.summaries.drop(ids)
        self.save_state()
        if removed:
            log.info("수집 제외로 md %d개를 지움", len(removed))
            self.reindex_paths(removed)
        return removed

    @staticmethod
    def _drop_excluded(conv, ex: claude_capture.Exclude):
        """zip에서 읽은 claude.ai 항목 하나를 제외 목록으로 거른다. 빼면 None, 메모리는 뺀 프로젝트 메모리만 지운다."""
        source, _, native = conv.conv_id.partition(":")
        if source == "claude-ai" and native in ex.conversations:
            return None
        if source == "claude-ai-project" and native in ex.projects:
            return None
        if source == "claude-ai-memory" and ex.projects:
            # 프로젝트 메모리 항목은 native_id가 'project:<uuid>' (claude_export.convert_memory)
            conv.messages = [m for m in conv.messages
                             if not (m.native_id.startswith("project:") and m.native_id[8:] in ex.projects)]
        return conv

    # ---- Code ---------------------------------------------------------------
    def collect_code(self, force: bool = False, progress=None) -> collector.CollectResult | None:
        if not self.archive_ok():
            return None
        src = self.sources
        if not (src["claude_code"] or src["codex"]):
            return collector.CollectResult()
        archive = self.archive()
        with self.lock:
            if src["claude_code"]:
                res = collector.collect(self.projects_dir, self.store.raw_dir, archive, self.state, force,
                                        progress, {ask.project_dir_name(self.ask_dir)})
            else:
                res = collector.CollectResult()
            # Codex는 Claude Code 다음에: 옮겨 온 대화가 Claude Code md와 겹치는지 보려면 그쪽이 먼저 있어야 한다
            if src["codex"]:
                cx = codex.collect(self.codex_dir, archive, self.state, force)
                res.new += cx.new
                res.changed += cx.changed
                res.written += cx.written
            self.state["last_code_collect"] = _now_iso()
        self.save_state()
        self.reindex_paths(res.written)
        return res

    # ---- 색인 -----------------------------------------------------------
    def sync_index(self, progress=None):
        if not self.archive_ok():
            return None
        res = self.index.sync(self.archive_dir, progress)
        if res.duplicates:
            self._warn(f"같은 id의 md가 여러 개: {len(res.duplicates)}건 (최신 것만 색인)")
        return res

    def rebuild_index(self, progress=None):
        if not self.archive_ok():
            return None
        return self.index.rebuild(self.archive_dir, progress)

    def rebuild_all(self) -> dict:
        """대화 md 전부 다시 만들기: 이력의 zip(남아 있는 것)을 내보내기 시각 순으로 + Code 원본 복사본 전체."""
        out = {"zips": 0, "zip_missing": 0, "code": None}
        recs = sorted((r for r in self.state.get("zips", {}).values() if r.get("result") == "ok"),
                      key=lambda r: r.get("export_time") or "")
        with self.lock:
            self.state["snapshots"] = {}
        for r in recs:
            p = Path(r.get("path", ""))
            if p.is_file():
                self.import_zip(p, force=True)
                out["zips"] += 1
            else:
                out["zip_missing"] += 1
        out["code"] = self.collect_code(force=True)
        out["captures"] = self.import_captures(force=True).new
        self.sync_index()
        return out

    def old_format_count(self) -> int:
        if not self.archive_ok():
            return 0
        n = 0
        for p in md_files(self.archive_dir):
            meta = read_front_file(p)
            if meta and meta.get("id") and meta.get("format_version") and meta["format_version"] != str(FORMAT_VERSION):
                n += 1
        return n

    # ---- 알림 판단 ----------------------------------------------------------
    def reminder_due(self, now: datetime | None = None) -> str | None:
        """띄울 알림 문구, 아니면 None. 하루 1번."""
        if not self.service_on("claude_ai"):
            return None
        now = now or datetime.now(timezone.utc).astimezone()
        raw = self.config.get("reminder_days", 7)
        try:
            days = float(7 if raw is None or isinstance(raw, bool) else raw)
        except (TypeError, ValueError):
            days = 7.0
        if days <= 0:
            return None                    # reminder_days: 0 = 알림 끔
        last = parse_iso(self.state.get("last_zip_import"))
        base = last or parse_iso(self.state.get("first_run"))
        if base is None:
            return None
        if last is None:
            # 이력이 한 번도 없으면 첫 실행 다음 날부터
            if now.astimezone(self.tz).date() <= base.astimezone(self.tz).date():
                return None
        elif (now - last).total_seconds() < days * 86400:
            return None
        shown = parse_iso(self.state.get("last_reminder"))
        if shown and shown.astimezone(self.tz).date() == now.astimezone(self.tz).date():
            return None
        if last:
            d = last.astimezone(self.tz)
            return f"claude.ai 내보내기를 받을 때가 됐어요 (마지막: {d.month}월 {d.day}일)"
        return "claude.ai 내보내기를 받을 때가 됐어요 (아직 가져온 적 없음)"

    def mark_reminded(self, now: datetime | None = None) -> None:
        with self.lock:
            self.state["last_reminder"] = (now or datetime.now(timezone.utc).astimezone()).isoformat(timespec="seconds")
        self.save_state()

    # ---- 상태 ----------------------------------------------------------
    # ---- 열린 일 큐 ---------------------------------------------------------
    def _int_cfg(self, key: str, default: int, lo: int = 1) -> int:
        v = self.config.get(key)
        if v is None or isinstance(v, bool) or v == "":
            return default
        try:
            n = int(v)
        except (TypeError, ValueError):
            return default
        return n if n >= lo else default

    def queue_filters(self) -> queue.Filters:
        jd = str(self.config.get("journal_dir") or "").strip()
        return queue.Filters.build(self.note_dirs, self.config.get("queue_note_exclude") or [],
                                   self.archive_dir, expand(jd) if jd else "")

    @property
    def journal_dir(self) -> Path | None:
        jd = str(self.config.get("journal_dir") or "").strip()
        return Path(expand(jd)) if jd else None

    def read_journal(self, now: float, days: int) -> list:
        root = self.journal_dir
        if root is None:
            return []
        if not root.is_dir():
            if not self._journal_warned:
                self._journal_warned = True
                self._warn(f"업무 일지 폴더가 없습니다: {root}")
            return []
        return self._journal.read_recent(root, datetime.fromtimestamp(now).date(), days)

    def compute_queue(self, conn, now: float | None = None, days: int | None = None) -> queue.QueueResult:
        now = datetime.now().timestamp() if now is None else now
        days = max(days or 0, self._int_cfg("queue_days", 14))     # 기간 칩이 더 길면 그만큼 본다
        entries = self.read_journal(now, days)
        extra = [i for e in entries for i in e.sessions]
        srcs = settings.read_queue_sources(self.config)
        docs = queue.load_docs(conn, now - days * queue.DAY, extra, srcs)
        with self.lock:
            closed = dict(self.state.get("queue_closed") or {})
        res = queue.compute(docs, closed, now, days, self._int_cfg("queue_focus", 5, lo=0), self.queue_filters(),
                            entries, srcs)
        for it in (*res.focus, *res.rest, *res.closed):
            self.attach_summary(it)
        return res

    # ---- 요약 (F2) -------------------------------------------------------
    @property
    def ask_dir(self) -> Path:
        """요약용 claude -p를 실행하는 폴더. 세션 기록이 남더라도 이 프로젝트는 수집에서 뺀다."""
        return self.store.local / "ask"

    def attach_summary(self, it: queue.QueueItem) -> None:
        rec = self.summaries.get(it.id)
        if not rec:
            return
        it.summary_text = str(rec["text"])
        it.summary = ask.headline(it.summary_text)
        it.summary_stale = self.summaries.is_stale(it.id, it.trace_ts)
        it.summary_model = ask.model_label(str(rec.get("model") or ""))

    @property
    def ask_provider(self) -> str:
        return settings.read_provider(self.config)

    def ask_model_label(self, cfg: dict | None = None) -> str:
        """'claude:haiku', 'codex:gpt-6-luna', 끄기면 빈 문자열."""
        cfg = cfg or self.config
        p = settings.read_provider(cfg)
        if p == "codex":
            return f"codex:{str(cfg.get('ask_model_codex') or 'gpt-6-luna').strip()}"
        if p == "claude":
            return f"claude:{str(cfg.get('ask_model') or 'haiku').strip()}"
        return ""

    def summarize(self, it: queue.QueueItem) -> str:
        """설정한 요약 AI(claude -p 또는 codex exec)로 요약하고 저장한다. 실패하면 ask.AskError. 작업 스레드에서 부른다."""
        cfg = self.config            # 도중에 설정이 바뀌어도 이 호출은 옛 값으로 끝낸다
        provider = settings.read_provider(cfg)
        limits = ask.Limits(self._int_cfg("ask_tail_messages", 20), self._int_cfg("ask_max_chars", 12000))
        timeout = self._int_cfg("ask_timeout_seconds", 120)
        if provider == "codex":
            model = str(cfg.get("ask_model_codex") or "gpt-6-luna").strip()
            cmd = cli_check.resolve("codex", cfg.get("ask_command_codex"))
            text = ask.summarize(it, ask_command=cmd, model=model, limits=limits, cwd=self.ask_dir, timeout=timeout,
                                 provider="codex", effort=str(cfg.get("ask_codex_effort") or "low").strip())
        else:
            cmd = settings.as_command(cfg.get("ask_command")) or ["claude"]
            model = str(cfg.get("ask_model") or "haiku").strip()
            text = ask.summarize(it, ask_command=cmd, model=model, limits=limits, cwd=self.ask_dir, timeout=timeout,
                                 provider=provider)
        with self.lock:
            self.summaries.put(it.id, it.trace_ts, text, f"{provider}:{model}")
        return text

    def close_item(self, item_id: str, kind: str) -> None:
        with self.lock:
            closed = self.state.setdefault("queue_closed", {})
            queue.close(closed, item_id, kind)
            queue.prune(closed, datetime.now().timestamp(), self._int_cfg("queue_days", 14) * 2)
        self.save_state()

    def reopen_item(self, item_id: str) -> None:
        with self.lock:
            queue.reopen(self.state.setdefault("queue_closed", {}), item_id)
        self.save_state()

    def status_text(self) -> str:
        def fmt(v):
            dt = parse_iso(v)
            return dt.astimezone(self.tz).strftime("%Y-%m-%d %H:%M") if dt else "없음"
        try:
            st = self.index.stats()
        except Exception as e:  # noqa: BLE001
            st = {"by_source": {}, "size": 0}
            self._warn(f"색인 상태 읽기 실패: {e}")
        names = {"claude-ai": "claude.ai 대화", "claude-code": "Claude Code", "claude-ai-project": "프로젝트",
                 "claude-ai-memory": "메모리", "chatgpt": "ChatGPT", "note": "노트", "codex": "Codex"}
        src = self.sources
        lines = [f"보관 폴더: {self.archive_dir or '(설정 안 됨)'}{'' if self.archive_ok() else '  ⚠ 없음'}"]
        if src["claude_ai"]:
            lines.append(f"마지막 claude.ai zip 가져오기: {fmt(self.state.get('last_zip_import'))}")
        if src["claude_code"] or src["codex"]:
            label = "Claude Code, Codex" if src["claude_code"] and src["codex"] else \
                ("Claude Code" if src["claude_code"] else "Codex")
            lines.append(f"마지막 {label} 수집: {fmt(self.state.get('last_code_collect'))}")
        if src["claude_ai"] or src["chatgpt"]:
            lines.append(self.capture_status_line())
        if not any(src.values()):
            lines.append("쓰는 서비스: 없음 (노트 폴더만 검색)")
        lines += [
            "대화 수: " + (", ".join(f"{names.get(k, k)} {v}" for k, v in sorted(st['by_source'].items())) or "0"),
            "노트 폴더: " + (", ".join(str(p) for p in self.note_dirs) or "없음"),
            f"색인 크기: {st['size'] / 1_048_576:.1f} MB",
            "최근 경고:",
        ]
        lines += [f"  {w}" for w in self.warnings[-5:]] or ["  없음"]
        return "\n".join(lines)
