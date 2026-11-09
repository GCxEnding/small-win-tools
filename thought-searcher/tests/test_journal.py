"""업무 일지 읽기 (SPEC-queue.md 3-B, 12번 test_journal.py). 합성 일지만 쓴다."""
import os
from datetime import date, datetime

from app.journal import (JournalReader, entry_time, journal_path, normalize_title, parse_journal,
                         session_doc_id)

DAY = date(2026, 11, 6)
UUID1 = "11111111-2222-3333-4444-555555555555"
UUID2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

# frontmatter, 금요일 전용 구역, 다른 구역 목록이 있는 실제 모양의 합성 일지
SAMPLE = f"""---
date: 2026-11-06
tags: [일지]
---
# 2026-11-06 (금)

## 업무
첫 줄에 적은 그냥 글은 항목이 아님
- [/] #개발 로그 규격 통일
	- 느린 쿼리만 남기도록 정리
	- [ ] #할일 개발서버 배포 후 확인 [created:: 2026-11-06]
- [x] #운영지원 #고객/가나다 게시판 개선 검토 [session:: {UUID1}]
	- 결론 정리
	- [x] #할일 회신 [created:: 2026-11-05] [completion:: 2026-11-06]
- [ ] 문서 검토   필요함
- [-] 버린 실험
	- 하위 첫 줄 [session:: claude-ai:{UUID2}] [session:: {UUID1}]
- 체크 없는 항목
-
- [ ]
- [ ] #할일
## 이슈 / 협의 필요
- [ ] 이슈 구역 항목은 읽지 않음

## 메모 (보고 제외)
- [ ] 메모 구역도 읽지 않음

## 업무 로그 (보고 제외)
![[gohome/2026-11-06]]

<!-- ▼▼▼ 금요일 전용 (월~목에는 여기부터 끝까지 삭제) ▼▼▼ -->
## 차주 진행업무
- [ ] #개발 업무명 - 할 일
"""


def test_reads_only_work_section_and_items():
    es = parse_journal(SAMPLE, DAY, "j.md")
    assert [e.title for e in es] == ["로그 규격 통일", "게시판 개선 검토", "문서 검토 필요함", "버린 실험",
                                     "체크 없는 항목"]


def test_states():
    es = {e.title: e for e in parse_journal(SAMPLE, DAY)}
    assert es["로그 규격 통일"].state == "/"
    assert es["게시판 개선 검토"].state == "x"
    assert es["문서 검토 필요함"].state == " "
    assert es["버린 실험"].state == "-"
    assert es["체크 없는 항목"].state == "/"        # 체크 없음 = 진행


def test_odd_check_marks_are_progress_and_upper_x_done():
    text = "## 업무\n- [>] 미룸\n- [X] 대문자 완료\n"
    assert [e.state for e in parse_journal(text, DAY)] == ["/", "x"]


def test_children_and_open_children():
    es = {e.title: e for e in parse_journal(SAMPLE, DAY)}
    a = es["로그 규격 통일"]
    assert a.open_children is True and len(a.children) == 2
    assert es["게시판 개선 검토"].open_children is False     # 하위 할 일이 [x]
    assert es["게시판 개선 검토"].closed_kind == "done"
    assert es["버린 실험"].closed_kind == "drop"
    assert es["문서 검토 필요함"].closed_kind == ""


def test_done_with_open_child_stays_open():
    text = "## 업무\n- [x] 끝난 듯한 일\n\t- [/] 아직 진행 중인 하위\n"
    (e,) = parse_journal(text, DAY)
    assert e.state == "x" and e.open_children and e.closed_kind == ""


def test_line_numbers():
    lines = SAMPLE.splitlines()
    for e in parse_journal(SAMPLE, DAY):
        assert lines[e.line - 1].startswith("-") and e.text in lines[e.line - 1]


def test_session_links_item_line_child_and_multiple():
    es = {e.title: e for e in parse_journal(SAMPLE, DAY)}
    assert es["게시판 개선 검토"].sessions == [f"claude-code:{UUID1}"]
    assert es["버린 실험"].sessions == [f"claude-ai:{UUID2}", f"claude-code:{UUID1}"]
    assert es["로그 규격 통일"].sessions == []


def test_session_doc_id():
    assert session_doc_id(UUID1) == f"claude-code:{UUID1}"
    assert session_doc_id(f"claude-ai:{UUID2}") == f"claude-ai:{UUID2}"


def test_normalize_title():
    assert normalize_title("#개발 #고객/가나다  결재   예정함 [created:: 2026-11-05] [session:: x]") == "결재 예정함"
    assert normalize_title("C# 공부와 issue#12") == "C# 공부와 issue#12"   # 단어 중간의 #은 태그가 아님
    assert normalize_title("#할일") == ""


def test_no_work_section():
    assert parse_journal("# 2026-11-06\n## 메모\n- [ ] x\n", DAY) == []


def test_work_log_heading_is_not_work_section():
    assert parse_journal("## 업무 로그 (보고 제외)\n- [ ] 로그\n", DAY) == []


def test_crlf_and_bom():
    text = "﻿## 업무\r\n- [x] 윈도 줄바꿈\r\n"
    (e,) = parse_journal(text.lstrip("﻿"), DAY)
    assert e.title == "윈도 줄바꿈" and e.state == "x"


def test_entry_time():
    end = datetime(2026, 11, 6, 23, 59).timestamp()
    assert entry_time(DAY, None) == end
    assert entry_time(DAY, datetime(2026, 11, 6, 16, 40).timestamp()) == datetime(2026, 11, 6, 16, 40).timestamp()
    assert entry_time(DAY, datetime(2026, 11, 8, 9, 0).timestamp()) == end        # 나중에 고쳐도 그날 끝
    assert entry_time(DAY, datetime(2026, 11, 1).timestamp()) == datetime(2026, 11, 6).timestamp()


def test_reader_reads_recent_days_and_caches(tmp_path):
    root = tmp_path / "vault"
    for d, body in [(date(2026, 11, 6), SAMPLE), (date(2026, 11, 9), "## 업무\n- [ ] 오늘 일\n"),
                    (date(2026, 10, 26), "## 업무\n- [ ] 오래된 일\n"),
                    (date(2026, 10, 25), "## 업무\n- [ ] 너무 오래된 일\n")]:
        p = journal_path(root, d)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    assert journal_path(root, date(2026, 11, 9)) == root / "2026" / "11" / "2026-11-09.md"
    r = JournalReader()
    es = r.read_recent(root, date(2026, 11, 9), 14)
    titles = [e.title for e in es]
    assert "오늘 일" in titles and "로그 규격 통일" in titles and "오래된 일" in titles   # 10-26 = 14일 전까지 (days+1개 파일)
    assert "너무 오래된 일" not in titles
    assert [e.title for e in r.read_recent(root, date(2026, 11, 9), 3)] == ["오늘 일", *titles[1:6]]
    # 캐시: 같은 파일이면 같은 객체, 고치면 다시 읽음
    first = r.read_recent(root, date(2026, 11, 9), 0)
    assert r.read_recent(root, date(2026, 11, 9), 0)[0] is first[0]
    p = journal_path(root, date(2026, 11, 9))
    p.write_text("## 업무\n- [x] 오늘 일\n- [ ] 새 일\n", encoding="utf-8")
    os.utime(p, (first[0].at + 5, first[0].at + 5))
    again = r.read_recent(root, date(2026, 11, 9), 0)
    assert [(e.title, e.state) for e in again] == [("오늘 일", "x"), ("새 일", " ")]
