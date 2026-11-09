"""SQLite FTS5 색인. 보관 폴더의 md와 노트 폴더의 md를 읽어 만든다 (언제든 버리고 다시 만들 수 있는 소모품)."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .archive import md_files
from .mdparse import ParsedDoc, parse_file
from .notes import SOURCE as NOTE_SOURCE, iter_note_files, parse_note
from .timeutil import parse_iso
from .tokenize import normalize, token_string

SCHEMA_VERSION = 1
log = logging.getLogger("thought-searcher")

ProgressFn = Callable[[int, int], None]


def fts5_available() -> bool:
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
        c.close()
        return True
    except sqlite3.Error:
        return False


def _contentless_ok() -> bool:
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(a, content='', contentless_delete=1)")
        c.execute("INSERT INTO t(rowid, a) VALUES (1, 'x')")
        c.execute("DELETE FROM t WHERE rowid = 1")
        c.close()
        return True
    except sqlite3.Error:
        return False


def _schema(contentless: bool) -> list[str]:
    opt = ", content='', contentless_delete=1" if contentless else ""
    tok = "tokenize='unicode61 remove_diacritics 0'"
    return [
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)",
        """CREATE TABLE IF NOT EXISTS files(
            path TEXT PRIMARY KEY, mtime REAL, size INTEGER, conv_id TEXT, updated TEXT)""",
        "CREATE INDEX IF NOT EXISTS files_conv ON files(conv_id)",
        """CREATE TABLE IF NOT EXISTS docs(
            id INTEGER PRIMARY KEY, conv_id TEXT UNIQUE, path TEXT, title TEXT, title_norm TEXT,
            source TEXT, project TEXT, project_norm TEXT, created TEXT, updated TEXT, updated_ts REAL,
            status TEXT, md_mtime REAL, md_size INTEGER, msg_first INTEGER, msg_last INTEGER,
            msg_count INTEGER)""",
        "CREATE INDEX IF NOT EXISTS docs_updated ON docs(updated_ts)",
        """CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY, doc_id INTEGER, ordinal INTEGER, role TEXT, line_no INTEGER,
            body_line INTEGER, is_branch INTEGER, text TEXT)""",
        "CREATE INDEX IF NOT EXISTS messages_doc ON messages(doc_id)",
        f"CREATE VIRTUAL TABLE IF NOT EXISTS conv_fts USING fts5(title_tok, body_tok{opt}, {tok})",
        f"CREATE VIRTUAL TABLE IF NOT EXISTS msg_fts USING fts5(tok{opt}, {tok})",
    ]


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        conn.close()
        raise
    return conn


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    ignored: int = 0
    duplicates: list[str] | None = None


class Index:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.lock = threading.Lock()          # 쓰기 직렬화
        self.progress: tuple[int, int] | None = None   # 다시 만드는 중이면 (완료, 전체)
        self.warnings: list[str] = []
        self.note_roots: list[Path] = []      # 노트 폴더 (core가 설정에서 채운다)
        self.note_exclude: list[Path] = []    # 노트로 보지 않을 폴더 (보관 폴더)
        self.tz = None
        self._note_of: dict[str, Path] = {}   # 이번 대조에서 찾은 노트 파일 -> 노트 폴더

    def _note_files(self) -> dict[str, Path]:
        found = {str(p): root for p, root in iter_note_files(self.note_roots, self.note_exclude)}
        self._note_of = found
        return found

    def _note_root(self, path: str) -> Path | None:
        if path in self._note_of:
            return self._note_of[path]
        for r in self.note_roots:
            try:
                Path(path).resolve().relative_to(Path(r).resolve())
                return Path(r)
            except (ValueError, OSError):
                continue
        return None

    def _parse(self, path: str) -> ParsedDoc | None:
        root = self._note_root(path)
        if root is not None:
            return parse_note(Path(path), root, self.tz)
        return parse_file(Path(path))

    # ---- 열기 ---------------------------------------------------------
    def open(self) -> sqlite3.Connection:
        """스키마 확인. 버전이 다르거나 깨졌으면 지우고 새로 만든다."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = None
        try:
            conn = connect(self.db_path)
            ver = None
            try:
                row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                ver = row[0] if row else None
            except sqlite3.DatabaseError:
                ver = None
            if ver is not None and ver != str(SCHEMA_VERSION):
                raise sqlite3.DatabaseError(f"스키마 버전 다름 {ver}")
            if ver is None:
                tables = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
                if tables:
                    raise sqlite3.DatabaseError("meta 없음")
                self._create(conn)
            conn.execute("SELECT count(*) FROM docs").fetchone()
            ok = conn.execute("PRAGMA quick_check").fetchone()[0]
            if ok != "ok":
                raise sqlite3.DatabaseError(ok)
            return conn
        except sqlite3.DatabaseError as e:
            log.warning("색인 다시 만들기 (%s)", e)
            if conn is not None:
                conn.close()
            self._delete_files()
            conn = connect(self.db_path)
            self._create(conn)
            return conn

    def _delete_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.db_path) + suffix)
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    def _create(self, conn: sqlite3.Connection) -> None:
        contentless = _contentless_ok()
        with conn:
            for sql in _schema(contentless):
                conn.execute(sql)
            conn.execute("INSERT OR REPLACE INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            conn.execute("INSERT OR REPLACE INTO meta VALUES('contentless', ?)", ("1" if contentless else "0",))

    # ---- 문서 단위 ----------------------------------------------------
    @staticmethod
    def _delete_doc(conn: sqlite3.Connection, conv_id: str) -> None:
        row = conn.execute("SELECT id, msg_first, msg_last FROM docs WHERE conv_id=?", (conv_id,)).fetchone()
        if not row:
            return
        doc_id, a, b = row
        conn.execute("DELETE FROM conv_fts WHERE rowid=?", (doc_id,))
        if a is not None:
            conn.execute("DELETE FROM msg_fts WHERE rowid BETWEEN ? AND ?", (a, b))
        conn.execute("DELETE FROM messages WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM docs WHERE id=?", (doc_id,))

    @staticmethod
    def _insert_doc(conn: sqlite3.Connection, path: Path, doc: ParsedDoc, mtime: float, size: int) -> None:
        m = doc.meta
        upd = parse_iso(m.get("updated"))
        cur = conn.execute(
            """INSERT INTO docs(conv_id, path, title, title_norm, source, project, project_norm, created,
               updated, updated_ts, status, md_mtime, md_size, msg_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc.conv_id, str(path), m.get("title", ""), normalize(m.get("title", "")), m.get("source", ""),
             m.get("project", ""), normalize(m.get("project", "")), m.get("created", ""), m.get("updated", ""),
             upd.timestamp() if upd else 0.0, m.get("source_status", "present") or "present", mtime, size,
             len(doc.messages)))
        doc_id = cur.lastrowid
        first = last = None
        body_parts = []
        for pm in doc.messages:
            c = conn.execute(
                "INSERT INTO messages(doc_id, ordinal, role, line_no, body_line, is_branch, text) VALUES(?,?,?,?,?,?,?)",
                (doc_id, pm.ordinal, pm.role, pm.line_no, pm.body_line, int(pm.is_branch), pm.text))
            mid = c.lastrowid
            first = mid if first is None else first
            last = mid
            label = pm.heading[5:] if pm.heading.startswith("## 📄 ") else ""
            if m.get("source") == NOTE_SOURCE and pm.heading:
                label = pm.heading.lstrip("#").strip()     # 노트는 구역 제목도 검색
            tok = token_string(f"{label}\n{pm.text}" if label else pm.text)
            conn.execute("INSERT INTO msg_fts(rowid, tok) VALUES(?, ?)", (mid, tok))
            body_parts.append(tok)
        conn.execute("UPDATE docs SET msg_first=?, msg_last=? WHERE id=?", (first, last, doc_id))
        conn.execute("INSERT INTO conv_fts(rowid, title_tok, body_tok) VALUES(?,?,?)",
                     (doc_id, token_string(m.get("title", "")), " ".join(body_parts)))

    # ---- 대조 ---------------------------------------------------------
    def sync(self, archive_root: Path, progress: ProgressFn | None = None,
             conn: sqlite3.Connection | None = None, only: list[Path] | None = None) -> SyncResult:
        """보관 폴더(또는 only 경로들)의 md와 색인을 맞춘다."""
        with self.lock:
            own = conn is None
            conn = conn or self.open()
            try:
                return self._sync(conn, Path(archive_root), progress, only)
            finally:
                if own:
                    conn.close()

    def sync_notes(self, progress: ProgressFn | None = None) -> SyncResult:
        """노트 폴더만 다시 확인한다 (보관 폴더는 건드리지 않음). 빠진 폴더의 노트는 색인에서 지운다."""
        with self.lock:
            conn = self.open()
            try:
                return self._sync(conn, None, progress, None, notes_only=True)
            finally:
                conn.close()

    @staticmethod
    def _stat_all(paths) -> dict[str, tuple[float, int]]:
        out = {}
        for p in paths:
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[str(p)] = (st.st_mtime, st.st_size)
        return out

    def _sync(self, conn, root: Path | None, progress, only, notes_only: bool = False) -> SyncResult:
        res = SyncResult(duplicates=[])
        known = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT path, mtime, size FROM files")}
        if notes_only:
            current = self._stat_all(self._note_files())
            note_paths = {r[0] for r in conn.execute("SELECT path FROM files WHERE conv_id LIKE 'note:%'")}
            gone = [p for p in note_paths if p not in current]
        elif only is None:
            current = {}
            if root is not None and root.is_dir():
                current = self._stat_all(p for p in md_files(root) if not p.name.startswith("."))
            current.update(self._stat_all(self._note_files()))
            gone = [p for p in known if p not in current]
        else:
            current = {}
            gone = []
            for p in only:
                try:
                    st = Path(p).stat()
                    current[str(p)] = (st.st_mtime, st.st_size)
                except OSError:
                    if str(p) in known:
                        gone.append(str(p))
        changed = [p for p, v in current.items() if known.get(p) != v]
        total = len(changed) + len(gone)
        done = 0
        conn.execute("BEGIN")
        try:
            for p in gone:
                row = conn.execute("SELECT conv_id FROM files WHERE path=?", (p,)).fetchone()
                conn.execute("DELETE FROM files WHERE path=?", (p,))
                if row and row[0]:
                    self._resolve(conn, row[0], res)
                done += 1
            for p in changed:
                doc = self._parse(p)     # 파일은 한 번만 읽는다
                cid = doc.conv_id if doc is not None else None
                old = conn.execute("SELECT conv_id FROM files WHERE path=?", (p,)).fetchone()
                mt, sz = current[p]
                conn.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)",
                             (p, mt, sz, cid, doc.meta.get("updated", "") if doc else ""))
                if old and old[0] and old[0] != cid:
                    self._resolve(conn, old[0], res)
                if cid:
                    self._resolve(conn, cid, res, (p, doc))
                else:
                    res.ignored += 1
                done += 1
                if done % 200 == 0:
                    conn.execute("COMMIT")
                    conn.execute("BEGIN")
                    if progress:
                        progress(done, total)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        res.duplicates = sorted(set(res.duplicates))
        if progress:
            progress(total, total)
        return res

    def _resolve(self, conn, cid: str, res: SyncResult, parsed: tuple[str, ParsedDoc] | None = None) -> None:
        """같은 id의 md 중 updated가 최신인 것 하나만 색인한다."""
        rows = conn.execute("SELECT path, mtime, size, updated FROM files WHERE conv_id=?", (cid,)).fetchall()
        had = conn.execute("SELECT path, md_mtime, md_size FROM docs WHERE conv_id=?", (cid,)).fetchone()
        winner = doc = None
        if len(rows) > 1:
            res.duplicates.append(cid)
            log.warning("같은 id의 md가 %d개: %s", len(rows), cid)
        rows.sort(key=lambda r: (parse_iso(r[3]).timestamp() if parse_iso(r[3]) else 0, r[1]), reverse=True)
        for r in rows:
            if parsed and parsed[0] == r[0]:
                doc = parsed[1]
            else:
                doc = self._parse(r[0])
            if doc is not None and doc.conv_id == cid:
                winner = r
                break
        if winner is None:
            if had:
                self._delete_doc(conn, cid)
                res.removed += 1
        elif not had or (had[0], had[1], had[2]) != (winner[0], winner[1], winner[2]):
            self._delete_doc(conn, cid)
            self._insert_doc(conn, Path(winner[0]), doc, winner[1], winner[2])
            if had:
                res.updated += 1
            else:
                res.added += 1

    def rebuild(self, archive_root: Path, progress: ProgressFn | None = None) -> SyncResult:
        """모든 표를 비우고 보관 폴더 전체에서 다시 만든다."""
        with self.lock:
            conn = self.open()
            try:
                with conn:
                    for t in ("files", "docs", "messages", "conv_fts", "msg_fts"):
                        conn.execute(f"DROP TABLE IF EXISTS {t}")
                self._create(conn)
                return self._sync(conn, Path(archive_root), progress, None)
            finally:
                conn.close()

    def delete_db(self) -> None:
        with self.lock:
            self._delete_files()

    def stats(self) -> dict:
        conn = self.open()
        try:
            by_src = dict(conn.execute("SELECT source, count(*) FROM docs GROUP BY source").fetchall())
        finally:
            conn.close()
        size = 0
        for suffix in ("", "-wal"):
            try:
                size += os.path.getsize(str(self.db_path) + suffix)
            except OSError:
                pass
        return {"by_source": by_src, "size": size}
