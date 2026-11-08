"""화면 없는 본체: 설정/상태, zip 가져오기, Code 수집, 색인. 트레이 앱과 CLI가 함께 쓴다."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import collector
from .archive import Archive, ArchiveMissing, FORMAT_VERSION, md_files, read_front_file
from .importers import ImportFailed, detect
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
    result: str                  # "ok" | "skipped" | "ignored" | "failed" | "no_archive"
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Core:
    def __init__(self, store: Store | None = None, tz=None):
        self.store = store or Store()
        setup_logging(self.store)
        self.tz = tz or local_tz()
        self.lock = threading.RLock()
        self.warnings: list[str] = []
        cfg = self.store.load_config()
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

    @property
    def watch_dir(self) -> Path:
        p = expand(str(self.config.get("watch_dir") or ""))
        return Path(p) if p else downloads_dir()

    @property
    def projects_dir(self) -> Path:
        return Path(expand(str(self.config.get("code_projects_dir") or "%USERPROFILE%\\.claude\\projects")))

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
        rec = {"name": path.name, "path": str(path), "size": st.st_size, "mtime": st.st_mtime,
               "processed_at": _now_iso(), "export_time": "", "result": "", "counts": {}, "importer": ""}
        out = self._import(path, rec)
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

    def _import(self, path: Path, rec: dict) -> ZipOutcome:
        imp = detect(path)
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

            for conv in imp.iter_conversations(path, on_skip):
                seen.add(conv.conv_id)
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

    # ---- Code ---------------------------------------------------------------
    def collect_code(self, force: bool = False, progress=None) -> collector.CollectResult | None:
        if not self.archive_ok():
            return None
        archive = self.archive()
        with self.lock:
            res = collector.collect(self.projects_dir, self.store.raw_dir, archive, self.state, force,
                                    progress)
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
        now = now or datetime.now(timezone.utc).astimezone()
        days = float(self.config.get("reminder_days") or 7)
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
                 "claude-ai-memory": "메모리"}
        lines = [
            f"보관 폴더: {self.archive_dir or '(설정 안 됨)'}{'' if self.archive_ok() else '  ⚠ 없음'}",
            f"마지막 zip 가져오기: {fmt(self.state.get('last_zip_import'))}",
            f"마지막 Code 수집: {fmt(self.state.get('last_code_collect'))}",
            "대화 수: " + (", ".join(f"{names.get(k, k)} {v}" for k, v in sorted(st['by_source'].items())) or "0"),
            f"색인 크기: {st['size'] / 1_048_576:.1f} MB",
            "최근 경고:",
        ]
        lines += [f"  {w}" for w in self.warnings[-5:]] or ["  없음"]
        return "\n".join(lines)
