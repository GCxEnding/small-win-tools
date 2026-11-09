# thought-searcher 명세

> 저장소: `GCxEnding/small-win-tools` (공개)
> 위치: `small-win-tools/thought-searcher/`
> 표시 이름: 생각 검색기 (트레이, 알림에 표시)

## 1. 개요
- 목적: Claude 채팅 기록을 PC에 영구 보관하고, 흐릿한 기억(단어 몇 개, 용어 일부)만으로 예전 대화를 빠르게 찾는다. "정리"하지 않고 "다 저장하고 검색"한다.
- 원칙: 대화 1개 = md 1개가 영구 원본이다. 검색 색인은 md에서 언제든 다시 만들 수 있는 소모품이다. 수집, 변환, 검색 모두 로컬에서 하며 AI 토큰을 쓰지 않는다.
- 사용자: CG 본인. 회사 PC와 개인 PC(둘 다 Windows). Everything, Ditto를 상시 쓰는 IT 숙련자.

## 2. 범위
### 포함
- 트레이 상주 앱 하나가 아래를 모두 담당
  - 전역 단축키(Ctrl+Alt+H)로 검색 창 호출
  - 다운로드 폴더 감시: claude.ai 내보내기 zip이 들어오면 자동 변환과 색인 갱신
  - Claude Code 세션 주기 수집: md 변환 + 원본 jsonl 로컬 복사
  - 주간 내보내기 알림 (Windows 알림)
- 가져오기 모듈 교체 구조 (claude.ai 내보내기, claude.ai 메모리 md 묶음, ChatGPT 내보내기, Claude Code 세션 4종 구현. 그 밖의 출처는 모듈 추가로 확장)
- claude.ai 내보내기의 대화, 프로젝트 문서, 메모리
- md 생성(덮어쓰기), 원본에서 사라진 대화 표시, 알려진 형식의 비밀 값 가림
- SQLite FTS5 색인과 검색어 문법(구문, 제외어, 필터)
- 색인 다시 만들기, 원본에서 전부 다시 변환

### 제외 (Out of scope)
- AI 요약, 임베딩, 의미 검색 등 토큰을 쓰는 기능
- ChatGPT의 생각 과정(thoughts, reasoning_recap), 도구 호출과 결과, 첨부 원본(file_*.dat)
- Claude 데스크톱 앱 Cowork(에이전트) 세션 (`AppData\Local\Claude-Data`)
- 서브에이전트 세션의 md 변환 (원본 jsonl 복사에는 포함)
- 첨부 파일 추출 텍스트, 아티팩트(tool_use로 만든 문서), thinking 블록
- 회사 PC와 개인 PC 사이의 보관본 공유나 병합
- md 직접 편집 보존 (항상 덮어씀)
- 한영 자판 오타 보정, 초성 검색
- claude.ai 자동 내보내기(로그인, 버튼 클릭 자동화). 내보내기는 사람이 수동으로 받는다.
- 설치 프로그램(exe 패키징). Git clone + pip 설치

## 3. 기능 요구사항
1. **상주와 수명**
   - `thought_searcher.pyw` 실행 시 트레이 아이콘으로 상주한다. 중복 실행은 이름 있는 뮤텍스로 막는다(두 번째 실행은 즉시 종료).
   - 첫 실행에 아무것도 묻지 않는다. `archive_dir`가 비어 있으면 기본 위치 `%LOCALAPPDATA%\thought-searcher\archive`를 쓴다(없으면 만든다). 사용자가 고른 폴더가 없어졌을 때만 수집을 멈추고 트레이 경고.
   - 트레이 메뉴: `검색 (Ctrl+Alt+H)`, `지금 가져오기`(Code 수집 + 다운로드 폴더 zip 확인), `claude.ai 내보내기 받으러 가기`, `대화 보관 폴더 열기`, `상태 보기`, `고급` > (`zip 파일 직접 고르기...`, `대화 보관 폴더 바꾸기...`, `검색 색인 다시 만들기`, `대화 md 전부 다시 만들기`), `종료`.
   - `상태 보기`: 마지막 zip 가져오기 시각, 마지막 Code 수집 시각, 대화 수(출처별), 색인 크기, 최근 경고 5개.
   - 시작 프로그램 등록은 README에 `shell:startup` 바로 가기 방법만 안내한다.

2. **가져오기 모듈 (교체 가능 구조)**
   - 모든 모듈은 같은 인터페이스를 따른다(7번). 앱 본체는 모듈 목록만 알고, 원본 형식은 모른다.
   - 모듈은 원본을 읽어 공통 모델(`Conversation`, `Message`)만 내놓는다. md 생성, 비밀 값 가림, 변경 판정, 색인은 본체가 한다.
   - zip 판별은 파일명이 아니라 내용으로 한다. 각 모듈의 `detect()`가 순서대로 확인해 처음 `True`인 모듈이 처리한다. (claude.ai와 ChatGPT 내보내기 모두 `conversations.json`을 가지므로 내부 구조로 구분해야 한다)

3. **claude.ai 내보내기 가져오기**
   - 대상: zip 안의 `conversations.json`, `projects.json`, `memories.json` (실제 파일명은 샘플로 확정, 10번).
   - 대화: 메시지의 텍스트 블록만 쓴다. `tool_use`(아티팩트 포함), `tool_result`, `thinking`, 첨부 추출 텍스트는 버린다. 첨부 파일은 파일명만 한 줄로 남긴다(`📎 첨부: report.pdf`).
   - 가지(branch): 메시지 부모 정보로 트리를 만들고, 가장 최근 메시지(마지막 생성 시각)에서 루트까지 거슬러 올라간 경로를 본문으로 쓴다. 본문에 없는 메시지는 `## 부록: 다른 가지` 아래에 시간순으로 둔다(검색됨). 부모 정보가 없으면 전체를 시간순 본문으로 쓴다.
   - 프로젝트: 프로젝트 1개 = md 1개. 프로젝트 지침(prompt template)과 문서 본문을 담는다.
   - 메모리: md 1개(`memories.md`)로 담는다.
   - 같은 zip을 다시 넣거나, 더 오래된 zip을 넣어도 결과가 바뀌지 않아야 한다(5번 변경 판정).

4. **Claude Code 세션 수집**
   - 대상: `%USERPROFILE%\.claude\projects\<프로젝트 폴더>\<sessionId>.jsonl` (메인 세션만 md 변환).
   - 시점: 앱 시작 시, 30분마다(설정값), 트레이 `지금 수집`.
   - md에 담는 것
     - `type: user`의 사람 입력 텍스트, `type: assistant`의 텍스트 블록 전부
     - 도구 호출(`tool_use`)은 담지 않는다(2026-11-08 사용자 결정: Bash, Read 같은 줄은 잡음). 규칙이 바뀌면 다음 수집에서 모든 Code md를 자동으로 다시 만든다(`collector.RENDER_VERSION`).
     - 슬래시 명령은 `/<명령> <인자>` 한 줄로
     - 대화 압축 요약(compact summary) 메시지는 `> [이전 대화 요약]` 인용으로
   - md에서 빼는 것: 도구 결과(`tool_result`), thinking, `isSidechain: true`, `isMeta: true`, 시스템 첨부, 큐/요청 기록 등 대화가 아닌 줄.
   - 제목: `custom-title` 항목 > `summary` 항목 > 첫 사람 입력 앞 60자. 프로젝트: 메시지의 `cwd` 마지막 폴더명(없으면 프로젝트 폴더명).
   - 진행 중인 세션도 수집한다. 마지막 줄이 쓰는 중이라 깨져 있으면 그 줄만 건너뛴다.
   - **원본 복사**: `projects` 폴더 전체(서브에이전트 폴더 포함)를 `%LOCALAPPDATA%\thought-searcher\raw\claude-code\`로 같은 구조로 복사한다. 크기나 수정 시각이 바뀐 파일만 다시 복사. 원본이 지워져도 복사본은 지우지 않는다.

5. **보관본(md) 생성과 변경 판정**
   - 대화 ID: `<출처>:<원본 ID>` (예: `claude-ai:6f1c...`, `claude-code:85a483d2-...`, `claude-ai-project:<uuid>`, `claude-ai-memory:main`).
   - 파일 위치: `<보관 폴더>/<출처>/<YYYY>/<YYYY-MM-DD>_<제목 슬러그>_<ID 앞 8자>.md`. 날짜는 대화 생성일(로컬 시간). 슬러그는 Windows 금지 문자 제거, 공백은 `-`, 최대 60자.
   - 프로젝트는 `<보관 폴더>/claude-ai/projects/<이름>_<ID 앞 8자>.md`, 메모리는 `<보관 폴더>/claude-ai/memories.md`.
   - 제목이 바뀌면 파일 이름도 바꾼다(같은 ID 앞 8자 파일을 찾아 이름 변경 후 덮어쓰기).
   - 변경 판정: 새로 만든 md 내용과 기존 md 내용이 같으면 쓰지 않는다(동기화 폴더 불필요한 갱신 방지). 다르면 덮어쓴다. 단, claude.ai 대화는 가져오는 쪽 `updated_at`이 기존 md의 `updated`보다 오래되었으면 건너뛴다(오래된 zip 재투입 대비).
   - 저장은 임시 파일에 쓴 뒤 교체(원자적 저장). UTF-8, BOM 없음, LF.
   - 비밀 값 가림(6번)을 적용한 뒤 저장한다.
   - **사라진 대화**: md는 지우지 않고 frontmatter에 `source_status: missing`, `missing_since: <날짜>`를 기록한다. 검색 결과에 `(원본 없음)`으로 작게 표시.
     - claude.ai: 가져온 zip이 지금까지 가져온 zip 중 가장 최신(내보내기 시각 기준)일 때만, 그 zip에 없는 기존 `claude-ai:*` 대화를 missing 처리한다. 다시 나타나면 `present`로 되돌린다.
     - claude-code: 원본 jsonl이 `projects`에 없으면 missing 처리(30일 자동 정리 포함).

6. **비밀 값 가림**
   - md에 쓰기 전에 알려진 형식만 `***가림:<종류>***`로 바꾼다. 원본 zip과 원본 jsonl 복사본은 건드리지 않는다.
   - 기본 패턴: Anthropic(`sk-ant-...`), OpenAI(`sk-...` 일정 길이 이상), GitHub(`ghp_`, `gho_`, `github_pat_`), AWS 액세스 키(`AKIA[0-9A-Z]{16}`), Slack(`xox[abprs]-...`), Google API 키(`AIza...`), PEM 개인 키 블록(`-----BEGIN ... PRIVATE KEY-----` ~ `END`), JWT(`eyJ...\.eyJ...\.`).
   - `config.json`의 `extra_redact_patterns`(정규식 목록)로 추가할 수 있다.

7. **다운로드 폴더 감시**
   - 감시 폴더: Windows 알려진 폴더 Downloads(`SHGetKnownFolderPath`), `config.json`으로 변경 가능.
   - 새 `.zip` 감지 시 크기가 5초 이상 변하지 않고 열 수 있을 때 처리(다운로드 중 파일, `.crdownload`, `.part`는 무시).
   - 앱 시작 시에도 감시 폴더의 zip 중 처리 이력에 없는 것을 확인해 처리한다.
   - 처리한 zip은 **그대로 둔다.** 처리 이력(`state.json`)에 SHA-256, 파일명, 경로, 내보내기 시각, 처리 시각, 결과 수(새로/바뀜/그대로/missing)를 남기고, 같은 해시는 다시 처리하지 않는다.
   - 어느 모듈도 `detect()`하지 못한 zip은 이력에 `ignored`로 남기고 무시한다(알림 없음).
   - 처리 완료 시 알림: `claude.ai 가져오기 완료: 새 대화 12, 바뀜 3`.

8. **주간 내보내기 알림**
   - 마지막 claude.ai zip 가져오기 후 7일이 지나면 Windows 알림을 띄운다: `claude.ai 내보내기를 받을 때가 됐어요 (마지막: 11월 1일)`.
   - 받을 때까지 하루 1번 다시 띄운다(앱 시작 시, 그리고 매시 확인). 가져오기 이력이 한 번도 없으면 첫 실행 다음 날부터 띄운다.
   - 알림 클릭 시 claude.ai 내보내기 설정 페이지를 기본 브라우저로 연다(URL은 `config.json`의 `export_page_url`).

9. **색인**
   - 위치: `%LOCALAPPDATA%\thought-searcher\index.db`. 색인은 **md만** 읽어 만든다(원본 zip, jsonl은 읽지 않음).
   - md를 쓸 때마다 해당 대화의 색인을 갱신한다. 앱 시작 시 보관 폴더의 md 목록과 수정 시각을 색인과 비교해 새것, 바뀐 것, 없어진 것을 맞춘다.
   - `색인 다시 만들기`: db를 지우고 보관 폴더 전체에서 다시 만든다. 진행률을 트레이 툴팁에 표시하고, 그동안 검색 창은 "색인 중" 안내.
   - 색인 스키마 버전이 다르거나 db가 깨졌으면 자동으로 다시 만든다.

10. **검색**
    - **분할(토큰화)**: NFKC 정규화 + 소문자화 후
      - 한글(및 한자, 가나) 연속 구간: 2글자씩 겹쳐 자른다(bigram). 이때 한글 사이의 공백은 무시하고 이어 붙인다. 예: `로그 배포` → `로그`, `그배`, `배포`. 따라서 `로그배포`와 `로그 배포`(구문)가 같은 것을 찾는다.
      - 영문, 숫자: 단어 단위(`[a-z0-9_]+` 기준), 접두어 검색 지원.
      - 섞인 글자: `nginx설정` → `nginx` + `설정`.
      - 이 분할 결과를 공백으로 이어 FTS5(`unicode61`, 분리 문자 기본) 열에 넣는다. 질의도 같은 함수로 분할한다.
    - **검색어 문법**
      - 공백으로 나눈 각 단어: 대화 안 어디에든 있으면 됨(대화 단위 AND). 한 메시지에 같이 있을 필요 없음.
      - 영어 단어는 접두어 일치(`log` → `logpick`, `logcut`), 대소문자 무시.
      - 한글 단어는 bigram 구문으로 일치(`배포를` 안의 `배포`도 맞음).
      - `"..."`: 구문. 안의 글자가 붙어서(한글은 공백 무시) 나와야 함.
      - `-단어`: 제외. 그 단어가 있는 대화는 뺌.
      - 필터: `src:ai`(claude.ai 대화), `src:code`(Claude Code), `src:project`, `src:memory`, `proj:<부분 문자열>`, `after:YYYY-MM[-DD]`, `before:YYYY-MM[-DD]`. 알 수 없는 `xxx:yyy`는 일반 검색어로 취급.
      - 1글자 단어(한글 1자, 영문 1자): 제목에서만 부분 일치로 찾는다(다른 단어와 AND).
      - 입력이 비거나 필터만 있으면: 최근 대화순 목록.
    - **순위**: 대화 단위 BM25(FTS5 기본) 점수를 기준으로
      - 제목에 맞으면 가산(제목 열 가중치, 기본 10배)
      - 모든 단어가 한 메시지 안에 같이 나오면 가산(근접 보너스)
      - 최근 대화 가산(반감기 180일, 기본 가중치는 관련도를 뒤집지 않을 정도)
      - 가중치는 `config.json`에서 조정 가능. 결과 최대 50개(설정값).
    - **맞은 메시지 위치**: 상위 결과마다 단어가 가장 많이 맞은 메시지를 대표로 고르고, 그 메시지의 md 줄 번호와 미리보기를 만든다.
    - 성능: 입력 후 150ms 쉬었다가(디바운스) 검색. 대화 2만 개 규모에서 검색 1회 300ms 이하.

11. **검색 창**
    - Ctrl+Alt+H로 화면 중앙(커서가 있는 모니터)에 뜨고 입력란에 포커스. 다시 누르면 숨김(토글). Esc, 포커스 잃으면 숨김.
    - 결과 한 항목(2줄)
      - 1줄: `출처 표시(AI/Code/P/M) | 제목 | 프로젝트 | 날짜(updated) | (원본 없음)`
      - 2줄: 대표 메시지 미리보기 한 줄, 맞은 부분 강조, `[3/7]`처럼 맞은 메시지 순번/개수
    - 키 조작: ↑/↓ 결과 이동, ←/→ 같은 대화의 다른 맞은 메시지로 미리보기 전환(입력란 커서가 맨 끝일 때만, 아니면 입력란 커서 이동), Esc 닫기
      - `Enter`: md 열기. `config.json`의 `open_command`(기본 `["code", "-g", "{path}:{line}"]`)로 대표 메시지 줄에서 연다. 실행 실패 시 Windows 기본 연결 프로그램으로 연다.
      - `Ctrl+Enter`: 미리보기 중인 메시지 본문(md 원문)을 클립보드에 복사, 창 숨김, "복사됨" 알림
      - `Shift+Enter`: 대화 전체 md를 클립보드에 복사
    - 결과 없음: "결과 없음" 한 줄과 적용된 필터 표시. 색인 중이면 "색인 중 (1234/20000)".
    - 한글 조합 중에도 결과가 갱신되어야 한다(조합 중 글자 포함해 검색).

## 4. 입력과 데이터
### 원본
- claude.ai 내보내기 zip: 설정 > 개인정보 > 데이터 내보내기로 받는 zip. 전체 스냅숏(받을 때마다 모든 대화 포함). 주 1회 수동.
  - 예상 구조(실제 샘플로 확정): `conversations.json` = `[{uuid, name, created_at, updated_at, chat_messages: [{uuid, sender: "human"|"assistant", text, content: [{type, text, ...}], created_at, attachments, files, parent_message_uuid?}]}]`, `projects.json`, `memories.json`, `users.json`(읽지 않음)
- Claude Code: `%USERPROFILE%\.claude\projects\*\*.jsonl`. 한 줄 = JSON 하나. 주요 필드: `type`(user, assistant, summary, custom-title 등), `sessionId`, `uuid`, `parentUuid`, `timestamp`, `cwd`, `isSidechain`, `isMeta`, `message.content`(문자열 또는 블록 목록: text, tool_use, tool_result, thinking). 현재 이 PC 기준 8개 프로젝트, 약 55MB.

### 보관본 md 형식
```markdown
---
id: claude-code:85a483d2-72af-409f-8235-10ac005117dc
source: claude-code
title: thought-searcher 인터뷰
project: small-win-tools
created: 2026-11-07T22:38:44+09:00
updated: 2026-11-07T23:10:02+09:00
url: 
messages: 24
source_status: present
missing_since: 
format_version: 1
---

# thought-searcher 인터뷰

<!-- bs:msg 1 user 2026-11-07T22:38:44+09:00 -->
## 🧑 사용자 (2026-11-07 22:38)

AI 채팅 기록을 내 PC에 영구 보관하고...

<!-- bs:msg 2 assistant 2026-11-07T22:39:10+09:00 -->
## 🤖 Claude (2026-11-07 22:39)

레포 구조를 먼저 확인하겠습니다.

## 부록: 다른 가지

<!-- bs:msg 9 user 2026-11-05T10:00:00+09:00 branch -->
## 🧑 사용자 (2026-11-05 10:00) [다른 가지]
...
```
- 색인은 `<!-- bs:msg ... -->` 표식으로 메시지를 나눈다(제목 `##`에 의존하지 않음. 메시지 본문에 `##`가 있어도 안전).
- 메시지 본문에 `<!-- bs:msg` 문자열이 있으면 `<!-- bs\:msg`로 바꿔 쓴다.
- `url`: claude.ai 대화는 `https://claude.ai/chat/<uuid>`, 그 외 빈 값.
- `format_version`: md 형식이 바뀌면 올린다. 올라가면 `원본에서 전부 다시 변환`을 안내한다.

### 개인 데이터 (PC별, 저장소 밖)
- `%APPDATA%\thought-searcher\config.json`
  ```json
  {
    "archive_dir": "D:\\OneDrive\\thought-archive-home",
    "hotkey": "ctrl+alt+h",
    "watch_dir": "",
    "code_projects_dir": "%USERPROFILE%\\.claude\\projects",
    "code_collect_minutes": 30,
    "reminder_days": 7,
    "export_page_url": "https://claude.ai/settings/data-privacy-controls",
    "open_command": ["code", "-g", "{path}:{line}"],
    "max_results": 50,
    "weights": {"title": 10.0, "body": 1.0, "same_message_bonus": 0.3, "recency": 0.2, "recency_half_life_days": 180},
    "extra_redact_patterns": []
  }
  ```
  (`watch_dir` 빈 값 = 시스템 Downloads)
- `%APPDATA%\thought-searcher\state.json`: zip 처리 이력, 마지막 가져오기 시각, 마지막 알림 시각, Code 파일별 크기/수정 시각
- `%LOCALAPPDATA%\thought-searcher\index.db`: 색인 (소모품)
- `%LOCALAPPDATA%\thought-searcher\raw\claude-code\...`: Code 원본 jsonl 복사본
- `%LOCALAPPDATA%\thought-searcher\logs\thought-searcher.log`: 회전 로그(1MB x 3)

### 색인 스키마 (안)
- `docs(conv_id PK, path, title, source, project, created, updated, status, md_mtime, md_size)`
- `messages(id PK, conv_id, ordinal, role, line_no, is_branch, text)`
- `conv_fts` (FTS5, `title_tok`, `body_tok`): 대화 단위 매칭과 BM25
- `msg_fts` (FTS5, `tok`, content는 `messages.id` 연결): 대표 메시지 찾기, 근접 보너스
- `meta(key, value)`: 스키마 버전 등

## 5. 엣지 케이스와 처리 규칙
| 상황 | 처리 |
|---|---|
| 같은 zip을 다시 넣음 | 해시가 이력에 있으면 건너뜀. 해시가 달라도 내용이 같으면 md를 쓰지 않음 |
| 더 오래된 zip을 나중에 넣음 | 대화별 `updated_at`이 기존보다 오래되면 건너뜀. missing 처리도 하지 않음(5번) |
| zip이 다운로드 중 | 크기 안정 + 열기 가능할 때까지 대기 |
| zip이 깨졌거나 JSON 파싱 실패 | 이력에 `failed`와 사유 기록, 알림 1회. 보관본은 건드리지 않음 |
| zip 안 일부 대화만 형식 오류 | 그 대화만 건너뛰고 경고 로그, 나머지는 처리. 완료 알림에 `건너뜀 N` 표시 |
| 다른 서비스 zip이나 무관한 zip | `detect()` 실패, `ignored`로 기록하고 무시 |
| 메시지가 0개인 대화 | md를 만들지 않음 |
| 제목이 없는 대화 | 첫 사람 입력 앞 60자, 그것도 없으면 `(제목 없음)` |
| 제목에 Windows 금지 문자, 예약어(CON 등), 이모지 | 금지 문자 제거, 예약어면 앞에 `_`. 이모지는 유지 |
| 제목이 바뀜 | ID 앞 8자로 기존 파일을 찾아 이름 변경 |
| ID 앞 8자가 같은 다른 대화(충돌) | frontmatter의 전체 `id`로 확인, 다르면 앞 12자로 늘림 |
| 보관 폴더에 같은 `id`의 md가 2개(동기화 충돌 사본 등) | 색인은 `updated`가 최신인 것 하나만 쓰고 경고. 파일은 지우지 않음 |
| 보관 폴더에 형식이 맞지 않는 md(사람이 넣은 파일 등) | 색인하지 않고 무시 |
| 보관 폴더가 없음(동기화 드라이브 분리, 경로 바뀜) | 수집 중단, 트레이 경고. 폴더를 새로 만들지 않음(엉뚱한 곳에 쌓임 방지) |
| 진행 중인 Code 세션의 마지막 줄이 깨짐 | 그 줄만 건너뜀. 다음 수집에서 다시 읽음 |
| Code 세션 jsonl이 30일 정리로 사라짐 | md 유지 + missing 표시. 원본 복사본 유지 |
| Code jsonl 안 알 수 없는 `type` | 무시(앞으로 형식이 바뀌어도 죽지 않게) |
| 같은 세션을 이어서 진행(resume) | 같은 sessionId 파일이 자라므로 md를 다시 만들어 덮어씀 |
| 메시지에 `<!-- bs:msg` 문자열 | 이스케이프해서 저장 (4번) |
| `config.json`, `state.json` JSON 깨짐 | `.bak`으로 보관하고 기본값으로 시작, 트레이 경고. config는 덮어쓰지 않고 기본값으로만 동작 |
| `index.db` 깨짐, 스키마 버전 다름 | 자동 삭제 후 다시 만들기 |
| 색인 다시 만들기 중 검색 | "색인 중" 안내, 완료된 범위까지 결과 표시 |
| 단축키 등록 실패 | 트레이 알림으로 알리고 트레이 메뉴 `검색`으로 사용 |
| `open_command` 실행 실패(VS Code 없음, PATH 없음) | Windows 기본 연결 프로그램으로 열기 |
| 검색어가 1글자 | 제목 부분 일치만 |
| 검색어가 특수 문자뿐 | 빈 입력처럼 최근 대화 목록 |
| FTS5 문법 문자(`*`, `"`, `NEAR`, `AND` 등)를 그대로 입력 | 질의 파서가 항상 이스케이프한 FTS 질의를 만든다(문법 오류로 죽지 않음) |
| 알림이 집중 모드로 숨겨짐 | 가져오기는 정상 진행. `상태 보기`에서 확인 가능 |
| 앱이 꺼져 있는 동안 zip이 들어옴 | 다음 시작 시 처리 |
| 보관 폴더 쓰기 중 강제 종료 | 원자적 저장으로 깨짐 방지. 다음 시작 시 색인 대조로 맞춤 |

## 6. 제약
- 실행 환경: Windows 10/11, 회사 PC와 개인 PC 각각 독립 설치. pip 사용 가능.
- 기술 스택:
  - Python 3.10 이상, 표준 `sqlite3`(FTS5 포함 빌드여야 함. 시작 시 확인하고 없으면 오류 안내)
  - PySide6: 트레이, 검색 창, 알림(`QSystemTrayIcon.showMessage`), 폴더 감시(`QFileSystemWatcher` + 주기 확인)
  - `ctypes`: 전역 단축키(`RegisterHotKey`), 뮤텍스, Downloads 경로
  - 외부 의존성은 PySide6, pytest만
  - emoji-searcher의 `hotkey.py`는 복사해서 쓴다(도구 간 import 금지. 각 도구 폴더는 독립)
- 보안·네트워크:
  - 실행 중 네트워크 접근 없음. 예외는 알림 클릭 시 브라우저로 URL 열기뿐(앱이 직접 요청하지 않음).
  - PC별 완전 분리: 회사 PC의 보관본, 원본, 색인은 회사 PC에만. 보관 폴더를 어떤 동기화 폴더에 둘지는 사람이 PC마다 정한다(README에 "회사 PC 보관본을 개인 클라우드에 두지 말 것" 안내).
  - 공개 저장소: 실제 대화 샘플, 실제 검색 정답은 저장소에 커밋하지 않는다(11번).
- 성능: 검색 1회 300ms 이하(대화 2만 개), 단축키 후 창 표시 체감 지연 없음. Code 수집과 zip 가져오기는 백그라운드 스레드에서 해 검색 창을 막지 않는다.
- 규모 가정: 대화 2만 개, md 합계 1GB까지.

## 7. 관련 파일과 인터페이스
```
small-win-tools/
├─ README.md                       ← 도구 목록에 thought-searcher 한 줄 추가
└─ thought-searcher/
   ├─ SPEC.md
   ├─ README.md                    ← 설치, 첫 실행, 시작 프로그램 등록, 검색 문법, 보관 폴더 주의
   ├─ requirements.txt             ← PySide6, pytest
   ├─ .gitignore                   ← tests/local/ 등
   ├─ thought_searcher.pyw           ← 진입점 (얇게)
   ├─ app/
   │  ├─ main.py                   ← 트레이, 뮤텍스, 메뉴, 스케줄, 알림
   │  ├─ hotkey.py                 ← emoji-searcher에서 복사
   │  ├─ window.py                 ← 검색 창 UI
   │  ├─ model.py                  ← Conversation, Message 데이터클래스
   │  ├─ importers/
   │  │  ├─ base.py                ← Importer 인터페이스, 등록 목록
   │  │  ├─ claude_export.py       ← claude.ai zip
   │  │  └─ claude_code.py         ← Code jsonl
   │  ├─ archive.py                ← md 렌더링, 파일명, 변경 판정, missing 처리, 원자적 저장
   │  ├─ mdparse.py                ← md → frontmatter + 메시지 목록 (색인용)
   │  ├─ redact.py                 ← 비밀 값 가림
   │  ├─ tokenize.py               ← bigram + 영문 단어 분할 (질의, 문서 공용)
   │  ├─ query.py                  ← 검색어 파서 (구문, 제외어, 필터, 1글자)
   │  ├─ index.py                  ← SQLite 스키마, 갱신, 대조, 다시 만들기
   │  ├─ search.py                 ← 검색과 순위 (UI 의존 없음)
   │  ├─ watcher.py                ← Downloads 감시, zip 처리 이력
   │  ├─ collector.py              ← Code 세션 수집 + 원본 복사
   │  ├─ store.py                  ← config.json, state.json 읽기/원자적 저장
   │  └─ cli.py                    ← 화면 없이 실행: import <zip>, collect, reindex, rebuild, search <q>
   └─ tests/
      ├─ fixtures/                 ← 합성 데이터만 (실제 대화 금지)
      │  ├─ claude_export_small.zip 또는 펼친 폴더
      │  ├─ claude_export_small.expected/  ← 정답 md
      │  ├─ code_session.jsonl
      │  └─ code_session.expected.md
      ├─ golden_queries.example.json   ← 합성 데이터용 검색 정답
      ├─ local/                    ← .gitignore. 실제 샘플과 실제 정답 (커밋 금지)
      ├─ test_tokenize.py
      ├─ test_query.py
      ├─ test_importer_claude_export.py
      ├─ test_importer_claude_code.py
      ├─ test_archive.py
      ├─ test_redact.py
      ├─ test_index_search.py
      ├─ test_perf.py
      ├─ test_real_sample.py       ← tests/local/ 없으면 skip
      └─ test_forbidden_network.py
```

### 가져오기 인터페이스
```python
@dataclass
class Message:
    native_id: str
    role: Literal["user", "assistant"]
    created: datetime            # 시간대 포함
    text: str                    # md 본문 그대로
    on_main_branch: bool = True

@dataclass
class Conversation:
    conv_id: str                 # "<source>:<native id>"
    source: str                  # "claude-ai" | "claude-code" | "claude-ai-project" | "claude-ai-memory"
    title: str
    project: str
    created: datetime
    updated: datetime
    url: str
    messages: list[Message]

class Importer(Protocol):
    name: str                                     # "claude-ai", "claude-code"
    def detect(self, path: Path) -> bool: ...     # zip 또는 폴더 내용으로 판별
    def iter_conversations(self, path: Path) -> Iterator[Conversation]: ...
    def snapshot_time(self, path: Path) -> datetime | None: ...   # 전체 스냅숏이면 내보내기 시각 (missing 판정용)
    def is_full_snapshot(self) -> bool: ...       # claude.ai True, Code는 폴더 기준 별도 처리
```
- 새 출처(ChatGPT 등)는 `importers/`에 파일 하나와 등록 한 줄로 추가한다. 본체 수정 없이 동작해야 한다.

### 검색 인터페이스
```python
def search(query: str, limit: int = 50) -> list[Hit]
@dataclass
class Hit:
    conv_id: str; path: Path; title: str; source: str; project: str
    updated: datetime; status: str; score: float
    matches: list[MatchedMessage]   # 순위순. [0]이 대표
@dataclass
class MatchedMessage:
    ordinal: int; line_no: int; preview: str; highlights: list[tuple[int, int]]
```

## 8. 결정 사항과 근거
| 결정 | 이유 | 버린 대안 |
|---|---|---|
| md 1개 = 대화 1개, 영구 원본 | 사람이 읽을 수 있고 동기화, Everything 검색 가능. 도구가 사라져도 남음 | DB가 원본 |
| 색인은 md에서만 생성 | 색인을 언제든 버리고 다시 만들 수 있음 | 원본 zip/jsonl에서 직접 색인 |
| bigram 사전 분할 + FTS5 unicode61 | trigram은 3글자 미만(`배포`, `DB`)을 색인으로 못 찾음. 2글자 검색이 핵심 | trigram + LIKE 보조(느림), trigram + bigram 이중 색인(복잡) |
| 한글 사이 공백 무시 | 띄어쓰기를 기억하지 못함 | 공백 그대로 |
| 대화 단위 AND | 사람은 한 대화의 단어를 따로따로 기억함 | 메시지 단위 AND, OR 대체 |
| 대화 FTS + 메시지 FTS 두 개 | 매칭/순위는 대화 단위, 위치/미리보기는 메시지 단위가 필요 | 메시지 FTS만 쓰고 파이썬에서 교집합(느림) |
| BM25 + 제목 + 근접 + 최신 가산 | 드문 단어, 제목, 함께 나온 단어, 최근 일이 기억과 잘 맞음 | 최신순, 관련도만 |
| 영어 접두어, 구문, 제외어, 필터 | 단어 끝을 기억 못 할 때, 범위 좁히기 | 한영 오타 보정, 초성(선택 안 함) |
| 1글자는 제목만 | bigram 색인에 1글자 토큰이 없고, 본문 1글자는 잡음 | 본문 LIKE 전체 훑기 |
| 트레이 앱 하나 | 등록 하나로 끝, emoji-searcher와 같은 구조 | 수집은 작업 스케줄러 |
| PC별 완전 분리 | 회사 정보가 개인 클라우드로 가지 않음, 동기화 충돌 없음 | 공유 폴더 + PC별 하위 폴더, 완전 통합 |
| md 항상 덮어씀 | 재생성 안전, 구현 단순 | 메모 구역 보존 |
| 내용이 같으면 쓰지 않음 | 동기화 폴더 불필요한 업로드 방지 | 매번 덮어쓰기 |
| 사라진 대화 보존 + 표시 | 영구 보관이 목적 | 함께 삭제, 표시 없음 |
| claude.ai 마지막 가지 본문 + 부록 | 읽기 자연스럽고 버린 가지도 검색됨 | 마지막 가지만, 전부 시간순 |
| Code: 대화만 (도구 호출 줄 제외) | 도구 호출 줄은 읽을 때 잡음 (2026-11-08 변경) | 대화 + 도구 호출 1줄(처음 안), 출력까지 전부 |
| Code 원본 jsonl 로컬 복사 | 30일 삭제 대비, 변환 규칙이 바뀌어도 다시 만들 수 있음 | md만 |
| 처리한 zip은 다운로드 폴더에 그대로 | 사용자 선택. 이력(해시)으로 중복 방지 | 로컬 폴더로 이동, 삭제 |
| 알려진 형식만 비밀 값 가림 | 동기화 폴더 노출 위험 감소, 오탐 적음 | 가리지 않음, 넓은 휴리스틱 |
| Enter 열기(VS Code 해당 줄), Ctrl+Enter 메시지 복사, Shift+Enter 대화 복사 | 위치까지 바로 이동, 복사 범위 두 가지 | 복사가 기본 |
| 알림: 마지막 가져오기 7일 후, 하루 1번 | 이미 받은 주에는 안 뜸 | 고정 요일 |
| 단축키 Ctrl+Alt+H | History. 충돌 적음 | Win+Shift+F, Ctrl+Shift+Space |

## 9. 가정 (사용자가 위임한 판단)
- 1글자 검색어는 제목 부분 일치로만 찾는다.
- 한영 오타 보정, 초성 검색은 넣지 않는다.
- "띄어쓰기 무시"는 한글 사이 공백을 무시하는 것으로 해석했다. 영문 단어 사이 공백은 단어 구분으로 둔다(`log pick`은 두 단어).
- 영문 단어 분할은 `[a-z0-9_]+` 기준이며 camelCase는 나누지 않는다(`logPick` → `logpick`, `log` 접두어로 찾힘).
- 순위 가중치 기본값(제목 10배, 근접 0.3, 최신 0.2, 반감기 180일)은 정답 샘플 통과를 기준으로 구현 중 조정한다.
- 검색 창은 화면 중앙(커서가 있는 모니터)에 뜬다.
- 결과 최대 50개, 디바운스 150ms.
- Code 수집 주기 30분.
- 보관 폴더 하위 구조는 `<출처>/<연도>/`로 나눈다(한 폴더 파일 수 과다 방지).
- 시간은 모두 로컬 시간대(+09:00)로 md에 적는다.
- 알림은 PySide6 트레이 알림을 쓴다(별도 토스트 라이브러리 없음). 클릭 동작은 `messageClicked` 신호로 처리.
- claude.ai 프로젝트 문서와 메모리도 같은 검색 대상이며, 필터 `src:project`, `src:memory`로 구분한다.
- claude.ai 메모리는 공식 내보내기의 `memories-000.zip`(JSON) 대신 메모리 화면에서 받은 md 묶음(`claude-memory-YYYY-MM-DD.zip`)으로도 들어온다. 둘 다 같은 문서(`claude-ai-memory:main`, `claude-ai/memories.md`)가 되고 더 새것이 남는다. md 묶음만 가져온 것은 주간 내보내기 알림 기준(`last_zip_import`)을 바꾸지 않는다.
- 노트 폴더(`config.json`의 `note_dirs`)의 일반 md는 변환 없이 제자리에서 읽어 색인한다. id `note:<절대 경로 소문자>`, source `note`, 배지 `노트`, 필터 `src:note`. 파일 하나가 문서 하나이고 `#` 제목마다 구역(메시지)으로 나눈다. 보관 폴더에는 쓰지 않고, 보관 폴더가 노트 폴더 안에 있어도 보관 폴더 쪽은 노트로 보지 않는다. 폴더를 빼면 색인에서만 지운다.
- ChatGPT 대화는 `chatgpt:<conversation_id>`, 보관 위치 `chatgpt/YYYY/`, 필터 `src:gpt`. 화면에 보이는 가지는 `current_node`에서 `parent`를 따라 올라간 경로이고, 나머지 노드는 부록(다른 가지)으로 둔다.

## 10. 미결 사항
- **claude.ai 내보내기 실제 구조**: 파일명(`projects.json`, `memories.json`), 메시지 부모 필드(가지 정보) 유무, 첨부 표기 방식, 내보내기 시각을 어디서 얻는지(zip 안 정보 또는 파일 수정 시각). 사용자가 줄 실제 zip으로 확정하고, 이 명세 3번과 4번을 고친다.
- 가지 정보가 내보내기에 없다면 "마지막 가지 본문 + 부록" 규칙은 적용할 수 없다(전체 시간순으로 대체).
- claude.ai 내보내기 설정 페이지의 정확한 URL.
- 회사 PC에서: 시작 프로그램 실행 허용 여부, Downloads 폴더 리디렉션 여부, `code` 명령 PATH 여부, Ctrl+Alt+H를 다른 사내 프로그램이 쓰는지.
- Windows 알림 클릭(`messageClicked`)이 알림 센터로 넘어간 뒤에도 동작하는지.
- Claude Code jsonl 형식은 버전마다 바뀔 수 있다. 이 PC의 현재 형식 기준으로 구현하고, 모르는 `type`은 무시한다.

## 11. 검증 계획
- 정답 샘플:
  - **합성 샘플(저장소 커밋)**: 구현 세션이 실제 구조를 흉내 낸 작은 claude.ai 내보내기(대화 5개: 가지 있는 대화, 제목 없는 대화, 비밀 값 포함 대화, 프로젝트 1개, 메모리)와 Code 세션 jsonl 1개(도구 호출, tool_result, thinking, 사이드체인, 깨진 마지막 줄 포함)를 만들고, 기대 md를 `*.expected`로 둔다.
  - **실제 샘플(커밋 금지, `tests/local/`)**: 사용자가 준 실제 zip에서 고른 대화 3~5개의 기대 md를 구현 세션이 만들고 사용자가 확인한다.
  - **검색 정답(실제)**: 사용자가 실제 기억으로 15개 정도 작성 → `tests/local/golden_queries.json`. 형식: `[{"query": "로그 배포", "expect": ["claude-code:85a483d2..."], "top": 5}]`. 기대 대화가 상위 `top` 안이면 통과.
  - **검색 정답(합성)**: `tests/golden_queries.example.json`에 합성 데이터 기준 10개 이상.
- 자동 테스트 (pytest)
  - `test_tokenize.py`: `로그 배포` → `로그 그배 배포`, `배포를` 안에 `배포`, `nginx설정` → `nginx` + `설정`, NFKC, 대소문자, 1글자 처리
  - `test_query.py`: 구문, 제외어, 필터 각각과 조합, 알 수 없는 필터, FTS 특수 문자 이스케이프, 빈 입력, 필터만 있는 입력
  - `test_importer_claude_export.py`: 합성 zip → 기대 md와 완전 일치, 가지 처리, 0개 메시지 대화 제외, 일부 대화 형식 오류 시 나머지 처리, 다른 형식 zip `detect()` False
  - `test_importer_claude_code.py`: 기대 md와 완전 일치, 도구 호출 줄 없음, tool_result/thinking/사이드체인 제외, 깨진 마지막 줄 무시, 모르는 type 무시
  - `test_archive.py`: 같은 zip 2번 → 두 번째는 쓰기 0건, 오래된 zip → 변화 없음, 제목 변경 → 파일 이름 변경, ID 충돌, missing 처리와 복귀, 최신이 아닌 zip은 missing 처리 안 함, 원자적 저장
  - `test_redact.py`: 패턴별 가림, 일반 문장 오탐 없음, `extra_redact_patterns`
  - `test_index_search.py`: md만으로 색인 생성, 색인 삭제 후 재생성 결과 동일, 대화 단위 AND(두 단어가 다른 메시지), 제외어, 영어 접두어, 한글 공백 무시, 제목 가산(같은 조건이면 제목 일치가 위), 근접 보너스, 최신 가산이 관련도를 뒤집지 않음, 대표 메시지 줄 번호가 md의 실제 줄과 일치, 합성 검색 정답 전부 통과
  - `test_perf.py`: 합성 대화 2만 개(대화당 평균 30메시지) 생성 → 색인 → 대표 검색어 20개 각각 300ms 이하 (느린 테스트 표시, 기본 실행에 포함)
  - `test_real_sample.py`: `tests/local/`이 있으면 실제 zip 가져오기 성공, 실제 기대 md 일치, 실제 검색 정답 15개 통과. 없으면 skip
  - `test_forbidden_network.py`: `app/` 코드에 `socket`, `urllib.request`, `http.client`, `requests` 등 네트워크 모듈 사용이 없음
- **End-to-end 검증:** (마지막에 실행해 통과해야 완료로 본다)
  1. `pip install -r requirements.txt` 후 `pytest` 전체 통과 (`tests/local/` 포함)
  2. `thought_searcher.pyw` 첫 실행 → 묻는 창 없이 트레이 아이콘 표시, 기본 보관 폴더 생성
  3. 시작 직후 Code 세션 수집 → 보관 폴더 `claude-code/` 아래에 md 생성, `%LOCALAPPDATA%\thought-searcher\raw\claude-code\`에 jsonl 복사 확인
  4. 실제 claude.ai zip을 다운로드 폴더에 복사 → 자동 가져오기 → 완료 알림 → `claude-ai/` 아래 md 생성
  5. 같은 zip을 다른 이름으로 다시 복사 → 보관 폴더 파일 수정 시각 변화 없음
  6. Ctrl+Alt+H → 실제 검색 정답 중 5개를 직접 입력해 기대 대화가 상위 5위 안
  7. Enter → VS Code가 대표 메시지 줄에서 열림. Ctrl+Enter → 메시지 복사, Shift+Enter → 대화 전체 복사 확인
  8. `색인 다시 만들기` 후 6번 결과가 같음
  9. `index.db`를 지우고 앱 재시작 → 자동 재생성 후 검색 정상
  10. `state.json`의 마지막 가져오기 시각을 8일 전으로 고치고 재시작 → 알림 표시 → 클릭 시 브라우저로 내보내기 페이지 열림
  11. 회사 PC에서 clone 후 2, 3, 6, 7 반복 (회사 PC는 별도 보관 폴더)

## 12. 사람 검토 체크포인트
1. **구현 시작 전**: 실제 claude.ai zip 제공 → 구현 세션이 구조를 조사해 10번 미결(파일명, 가지 정보, 내보내기 시각)을 정리하고 명세 3, 4번 수정안을 보여 줌 → 사용자 승인
2. **md 형식 확정**: 실제 대화 3~5개와 Code 세션 2개를 변환한 md를 사용자가 VS Code로 열어 읽기 편한지, 빠진 내용이 없는지, 비밀 값이 가려졌는지 확인 → 확정되면 `format_version: 1` 고정
3. **검색 정답 작성**: 사용자가 실제 기억으로 `tests/local/golden_queries.json` 15개 작성 (2번 이후, 실제 데이터가 보관 폴더에 들어간 뒤)
4. **순위 조정 확인**: 정답 통과율과 실패한 검색어 목록을 보고 가중치 조정안 승인
5. **검색 창 첫 화면**: 글꼴, 창 크기, 2줄 결과 표시, 강조 표시, ←/→ 전환 동작 확인
6. **E2E 직접 확인**: 11번 E2E 2~10번을 개인 PC에서, 11번을 회사 PC에서
