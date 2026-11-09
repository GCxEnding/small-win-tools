import os

from conftest import KST

from app.notes import iter_note_files, note_id, parse_note
from app.search import search

JOURNAL = """---
date: 2026-11-06
tags: [일지]
---
# 2026-11-06 (금)

## 업무
- [/] #개발 배포 로그 규격 통일
	- 느린 쿼리만 파일에 남김

## 이슈 / 협의 필요

## 메모 (보고 제외)
```bash
# 이건 제목이 아님
tail -f app.log
```
"""


def _vault(tmp_path):
    v = tmp_path / "MyVault"
    (v / "2026" / "11").mkdir(parents=True)
    (v / ".obsidian").mkdir()
    (v / "장기메모").mkdir()
    (v / "2026" / "11" / "2026-11-06.md").write_text(JOURNAL, encoding="utf-8")
    (v / "장기메모" / "조직 동기화 API.md").write_text("API 적재 순서 정리\n\n## 순서\n부서 먼저", encoding="utf-8")
    (v / "20260929_회의.md").write_text("본문만 있는 메모", encoding="utf-8")
    (v / ".obsidian" / "workspace.md").write_text("무시", encoding="utf-8")
    (v / "그림.png").write_bytes(b"x")
    return v


def test_iter_skips_dot_dirs_and_non_md(tmp_path):
    v = _vault(tmp_path)
    names = sorted(p.name for p, _ in iter_note_files([v]))
    assert names == ["2026-11-06.md", "20260929_회의.md", "조직 동기화 API.md"]
    assert iter_note_files([v, v / "장기메모"]).__len__() == 3          # 겹쳐 등록해도 한 번
    assert len(iter_note_files([v], exclude=[v / "장기메모"])) == 2


def test_journal_sections_and_date(tmp_path):
    v = _vault(tmp_path)
    p = v / "2026" / "11" / "2026-11-06.md"
    doc = parse_note(p, v, KST)
    assert doc.meta["source"] == "note" and doc.conv_id == note_id(p)
    assert doc.title == "2026-11-06"
    assert doc.meta["created"] == doc.meta["updated"] == "2026-11-06T00:00:00+09:00"
    assert doc.meta["project"] == "MyVault/2026/11"
    heads = [m.heading for m in doc.messages]
    assert heads == ["## 업무", "## 메모 (보고 제외)"]           # 빈 구역은 빼고, 코드 블록 안 #은 제목 아님
    assert doc.messages[0].line_no == 7 and doc.messages[0].text.startswith("- [/] #개발")
    assert "tail -f" in doc.messages[1].text


def test_title_and_date_fallbacks(tmp_path):
    v = _vault(tmp_path)
    d = parse_note(v / "20260929_회의.md", v, KST)
    assert d.title == "20260929_회의" and d.meta["created"].startswith("2026-09-29")
    assert d.messages[0].line_no == 1 and d.meta["project"] == "MyVault"
    n = parse_note(v / "장기메모" / "조직 동기화 API.md", v, KST)
    assert [m.heading for m in n.messages] == ["", "## 순서"]   # 첫 제목 전 글도 구역


def test_core_note_dirs_search_and_remove(core_env, tmp_path):
    v = _vault(tmp_path)
    assert core_env.add_note_dir(v) and not core_env.add_note_dir(v)
    core_env.sync_index()
    db = core_env.index.db_path
    hits = search("배포 src:note", db_path=db)
    assert [h.title for h in hits] == ["2026-11-06"] and hits[0].matches[0].line_no == 8   # 맞은 줄로 열림
    assert [h.title for h in search("부서 먼저", db_path=db)] == ["조직 동기화 API"]
    assert search("보고 제외 src:노트", db_path=db)                # 구역 제목도 검색
    assert search("배포 after:2026-11 before:2026-11-07", db_path=db)
    # 파일이 바뀌면 sync_notes로 반영, 원본은 그대로
    j = v / "2026" / "11" / "2026-11-06.md"
    before = j.read_bytes()
    (v / "새 메모.md").write_text("카프카 토픽 정리", encoding="utf-8")
    core_env.sync_notes()
    assert search("카프카", db_path=db) and j.read_bytes() == before
    assert not list(core_env.archive_dir.rglob("*.md"))           # 보관 폴더에는 아무것도 쓰지 않음
    # 폴더를 빼면 검색에서 사라짐
    core_env.remove_note_dir(v)
    core_env.sync_notes()
    assert search("카프카", db_path=db) == [] and search("", db_path=db) == []


def test_archive_inside_note_dir_is_not_double_indexed(core_env, tmp_path):
    arch = core_env.archive_dir
    core_env.add_note_dir(arch.parent)                             # 보관 폴더를 품은 폴더를 노트로 등록
    (arch / "claude-ai").mkdir(exist_ok=True)
    (arch / "claude-ai" / "x.md").write_text("보관본", encoding="utf-8")
    files = [p for p, _ in iter_note_files(core_env.index.note_roots, core_env.index.note_exclude)]
    assert not any(str(arch) in os.fspath(p) for p in files)
