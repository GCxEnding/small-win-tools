# thought-searcher 확장 명세: 설정 창과 시작 안내

> 본 명세(`SPEC.md`), 큐 확장(`SPEC-queue.md`)에 붙는 확장이다. 여기 적지 않은 것은 두 문서를 따른다.
> 인터뷰: 2026-11-10. 이 세션은 인터뷰만 했고 코드는 쓰지 않았다. 구현은 새 세션에서 한다.

## 1. 개요
- 배경: 설정은 `%APPDATA%\thought-searcher\config.json`을 직접 고쳐야 한다. 트레이 메뉴로 바꿀 수 있는 것은 보관 폴더와 노트 폴더뿐이고, 그것도 `고급` 메뉴에 흩어져 있다.
- 목적
  1. 바꿀 수 있는 설정을 모두 설정 창 하나에서 바꾼다. config.json을 몰라도 쓸 수 있게 한다.
  2. 처음 쓰는 사람(옆자리 동료)을 위한 시작 안내를 둔다.
  3. F2 요약 AI를 Claude, GPT(Codex CLI), 끄기 중에서 고르고, 기본은 가장 싼 모델로 한다.
  4. 쓰는 서비스만 켜서, 안 쓰는 서비스의 알림과 메뉴가 보이지 않게 한다.
- 대상 사용자
  - CG 본인: 지금 설정이 그대로 유지돼야 한다(이전 동작이 바뀌지 않음).
  - 옆자리 동료: ChatGPT만 씀(Plus 이상), Claude 구독 없음. Obsidian은 쓰지만 업무 일지 형식은 다름. 회사 PC에 Python과 CLI가 설치돼 있는지는 모름.

## 2. 범위
### 포함
- 설정 창(탭 4개: 일반, 수집, 요약 AI, 고급), 저장/취소, 저장 즉시 적용
- 시작 안내(첫 실행 때만 자동으로 뜸, 건너뛰기 가능)
- 쓰는 서비스 선택(claude.ai, ChatGPT, Claude Code, Codex)과 그에 따른 수집, 알림, 메뉴 숨김
- 큐에 올릴 출처 선택(ChatGPT, Codex 대화도 큐에 올릴 수 있게)
- 요약 AI 선택(Claude / GPT / 끄기), 모델 목록, CLI 상태 확인(토큰 쓰지 않음)
- 단축키 기록 입력과 즉시 등록 시험
- 수집 스크립트 설치 단계 안내, 스크립트 복사 버튼, 수집 상태 표시
- 트레이 메뉴 정리, 검색 창 상태 줄의 톱니(⚙) 버튼

### 제외
- 앱이 CLI(Claude Code, Codex)나 Python, Tampermonkey를 직접 설치하거나 로그인 창을 띄우는 것. 상태만 보여 준다.
- 설정 가져오기/내보내기, PC 사이 설정 공유
- 동료의 Obsidian 일지 형식 지원(일지 연결은 지금 형식 그대로. 동료는 노트 폴더로만 넣음)
- 설치 프로그램(exe). 여전히 git clone + pip
- 스크립트 상수(`sync_minutes`, `max_per_run`)를 앱 설정 창에서 바꾸기(스크립트 맨 위 상수 그대로)
- 시험 요약(실제 AI 호출) 버튼

### 본 명세와 달라지는 점
- `SPEC.md` 3-1 "첫 실행에 아무것도 묻지 않는다"가 바뀐다: config.json이 없는 첫 실행에서만 시작 안내를 띄운다. 건너뛰면 지금과 같은 기본값으로 동작한다. config.json이 이미 있는 PC(CG의 두 PC)에서는 뜨지 않는다.
- `SPEC.md` 3-1 트레이 메뉴 구성이 바뀐다(5번).
- `SPEC-queue.md` 2번 제외 "ChatGPT, Codex를 큐에 올리는 것"이 설정으로 바뀐다(3-D). 기본값은 기존 사용자에게 지금과 같다.
- `SPEC-queue.md` 3-C-4 요약 실행이 Claude 고정에서 Claude 또는 Codex로 바뀐다.

## 3. 기능 요구사항

### A. 설정 창 공통
1. 여는 길: 트레이 메뉴 `설정...`(메뉴 위쪽, `검색` 바로 아래), 검색 창 상태 줄 오른쪽 끝의 작은 ⚙ 버튼(누르면 검색 창은 숨김). 이미 열려 있으면 앞으로 가져온다(창 하나만).
2. 창 이름 `생각 검색기 설정`. 크기는 내용에 맞추되 최소 560x480 정도, 크기 조절 가능. 화면 중앙(커서가 있는 모니터).
3. 아래쪽 버튼: `저장`, `취소`. 바꾼 것이 있으면 `저장`이 활성, 창 제목에 `*`.
   - `취소` 또는 창 닫기(X, Esc): 바꾼 것이 있으면 "저장하지 않고 닫을까요?" 확인.
   - `저장`: 모든 칸을 검사(3-G) → 통과하면 config.json에 원자적 저장 → 바로 적용(3-F) → 창 닫기. 실패한 칸이 있으면 그 탭으로 가서 칸 아래에 빨간 한 줄로 사유를 보여 주고 저장하지 않는다.
4. 외부 변경 감지: 창을 연 뒤 config.json이 바깥에서 바뀌었으면(수정 시각, 크기) 저장 전에 "config.json이 창을 연 뒤 바뀌었습니다. 덮어쓸까요? / 다시 읽기" 선택을 띄운다.
5. config.json이 깨져 기본값으로 동작 중이면(`config_broken`) 설정 창 맨 위에 경고 줄 "config.json을 읽지 못해 기본값으로 동작 중입니다. 저장하면 지금 화면 내용으로 새로 씁니다 (깨진 파일은 config.json.bak에 있음)". 저장하기 전에는 덮어쓰지 않는다(`CLAUDE.md` 5번 "사용자가 편집하는 파일은 덮어쓰지 않음" 유지).
6. 창에 없는 키(사용자가 손으로 넣은 키, 앞으로 생길 키)는 저장할 때 그대로 둔다. 창은 자기가 아는 키만 바꾼다.
7. 각 항목 옆이나 아래에 회색 한 줄 설명(무엇이 바뀌는지). 경로 칸에는 `찾아보기...` 버튼과 `열기` 버튼.

### B. 탭과 항목
기본값 열의 "기존"은 지금 `DEFAULT_CONFIG` 값 그대로라는 뜻이다. 새 키는 3-H에 모았다.

**일반 탭**
| 항목 | 키 | 입력 방식 |
|---|---|---|
| 검색 창 단축키 | `hotkey` | 키 기록 칸(3-E) |
| 대화 보관 폴더 | `archive_dir` | 경로 칸. 비면 기본 위치 `%LOCALAPPDATA%\thought-searcher\archive`를 회색으로 보여 줌. 아래 경고 한 줄: "회사 PC 보관본을 개인 클라우드에 두지 마세요" |
| 노트 폴더 | `note_dirs` | 목록 + `추가...`(폴더 고르기) / `빼기`. "파일은 읽기만 합니다" 설명 |
| 업무 일지 폴더 | `journal_dir` | 경로 칸 + `끄기`(비우기). 설명: "YYYY/MM/YYYY-MM-DD.md 형식의 `## 업무` 구역을 읽습니다. 형식이 다르면 비워 두고 노트 폴더로만 넣으세요" |
| 열린 일 기간(일) | `queue_days` | 숫자(1~90) |
| 기본 노출 개수 | `queue_focus` | 숫자(0~20) |
| 큐에 올릴 출처 | `queue_sources` | 체크: claude.ai, ChatGPT, Claude Code, Codex, 노트 (3-D) |
| 큐에서 뺄 노트 폴더 | `queue_note_exclude` | 목록 + `추가...`(노트 폴더 안에서 폴더 고르기, 노트 폴더 기준 상대 경로로 저장) / `빼기`. 노트 폴더 밖을 고르면 거절 |

**수집 탭**
| 항목 | 키 | 입력 방식 |
|---|---|---|
| 쓰는 서비스 | `sources` | 체크 4개: claude.ai, ChatGPT, Claude Code, Codex (3-C) |
| 다운로드(감시) 폴더 | `watch_dir` | 경로 칸. 비면 시스템 다운로드 폴더를 회색으로 |
| 자동 수집 파일 폴더 | `capture_dir` | 경로 칸. 비면 `<감시 폴더>\claude-sync`를 회색으로 |
| Claude Code 세션 폴더 | `code_projects_dir` | 경로 칸 (Claude Code 켰을 때만 활성) |
| Codex 폴더 | `codex_dir` | 경로 칸 (Codex 켰을 때만 활성) |
| 수집 주기(분) | `code_collect_minutes` | 숫자(5~240) |
| claude.ai 내보내기 알림(일) | `reminder_days` | 숫자(1~60) + `끄기` 체크(`reminder_days: 0`). claude.ai 껐으면 숨김 |
| 자동 수집 멈춤 알림(시간) | `capture_stale_hours` | 숫자(1~72) |
| 수집 스크립트 설치 | (설정값 아님) | 3-I 안내 묶음. claude.ai, ChatGPT 중 켠 사이트만 |

**요약 AI 탭** (3-J)
| 항목 | 키 | 입력 방식 |
|---|---|---|
| 요약 AI | `ask_provider` | 라디오: Claude / GPT (Codex) / 끄기 |
| 모델 | `ask_model` (Claude), `ask_model_codex` (GPT) | 고를 수 있는 목록 + 직접 입력 가능한 콤보 상자. 가장 싼 모델에 "(가장 저렴)" 표시 |
| 추론 정도 (GPT만) | `ask_codex_effort` | 목록: low / medium. 기본 low |
| CLI 상태 | (설정값 아님) | 한 줄 + `다시 확인` 버튼 (3-J-4) |
| CLI 경로 | `ask_command`, `ask_command_codex` | 경로 칸. 비면 자동 찾기 결과를 회색으로 |

**고급 탭**
| 항목 | 키 | 입력 방식 |
|---|---|---|
| md 여는 명령 | `open_command` | 한 줄 텍스트(공백으로 나눔, 따옴표 허용). `{path}`, `{line}` 설명. `기본값` 버튼 |
| 검색 결과 최대 개수 | `max_results` | 숫자(10~500) |
| 순위 가중치 | `weights` 5개 | 숫자 칸 5개(제목, 본문, 같은 메시지 가산, 최근 가산, 반감기 일). `기본값` 버튼 |
| 추가 가림 정규식 | `extra_redact_patterns` | 목록(한 줄에 하나) + `추가` / `빼기`. 저장 전 정규식 문법 검사 |
| 요약 재료 메시지 수 | `ask_tail_messages` | 숫자(1~200) |
| 요약 재료 상한(자) | `ask_max_chars` | 숫자(1000~100000) |
| 요약 제한 시간(초) | `ask_timeout_seconds` | 숫자(10~600) |
| 내보내기 페이지 주소 | `export_page_url` | 한 줄 텍스트(`https://`로 시작) |
| 설정 파일 | (설정값 아님) | `config.json 열기`(기본 연결 프로그램), `데이터 폴더 열기`(APPDATA, LOCALAPPDATA 각각) 버튼 |

- 고급 탭 맨 위에 한 줄: "보통은 바꿀 필요가 없습니다."
- 색인 다시 만들기, md 전부 다시 만들기, zip 직접 고르기는 설정이 아니라 작업이므로 창에 넣지 않고 트레이 `고급`에 남긴다(5번).

### C. 쓰는 서비스 (`sources`)
1. 값: `{"claude_ai": bool, "chatgpt": bool, "claude_code": bool, "codex": bool}`.
2. 기존 config.json에 키가 없으면 모두 `true`로 본다(CG 본인의 지금 동작 그대로).
3. 시작 안내의 첫 단계에서 고르며, 미리 체크하는 기본 추정은 아래와 같다(추정일 뿐 사용자가 바꿈).
   - Claude Code: `%USERPROFILE%\.claude\projects`가 있으면 체크
   - Codex: `%USERPROFILE%\.codex`가 있으면 체크
   - claude.ai, ChatGPT: 체크 안 함(로컬에서 알 수 없음)
4. 끈 서비스의 효과 (이미 보관된 md는 그대로 검색된다. 지우지 않는다)
   | 끈 서비스 | 멈추는 것 | 숨기는 것 |
   |---|---|---|
   | claude.ai | 주간 내보내기 알림, claude.ai zip 가져오기, `claude-ai_*.json` 수집 파일 가져오기, claude.ai 수집 멈춤 알림, 잘못 저장된 수집 파일 알림 | 트레이 `claude.ai 내보내기 받으러 가기`, 상태 보기의 claude.ai 줄 |
   | ChatGPT | ChatGPT zip 가져오기, `chatgpt_*.json` 가져오기, ChatGPT 수집 멈춤 알림 | 상태 보기의 ChatGPT 줄 |
   | Claude Code | Code 세션 수집과 원본 jsonl 복사 | 상태 보기의 Code 줄 |
   | Codex | Codex 대화 수집 | 상태 보기의 Codex 줄 |
   - claude.ai 메모리 md 묶음 zip(`claude-memory-*.zip`)은 claude.ai에 묶는다.
   - 끈 출처의 zip은 처리 이력에 남기지 않는다(나중에 켜면 다음 확인 때 가져오게).
   - 넷 다 끄면 저장 시 경고 "수집할 서비스가 없습니다. 노트 폴더만 검색합니다" (저장은 허용).
5. `지금 가져오기` 알림 문구도 켠 서비스 기준(예: ChatGPT만이면 "가져오는 중입니다 (새 zip 1개)").

### D. 큐에 올릴 출처 (`queue_sources`)
1. 값: 목록. 고를 수 있는 것: `claude-ai`, `chatgpt`, `claude-code`, `codex`, `note`.
2. 기본값
   - 기존 config.json에 키가 없으면 `["claude-ai", "claude-code", "note"]`(지금 동작 그대로).
   - 시작 안내를 거친 새 사용자는 켠 서비스 + `note`. (동료: `["chatgpt", "note"]`)
3. 프로젝트 문서, 메모리, `imported/`는 여전히 큐에 올리지 않는다(목록에 없음).
4. 일지 항목(`journal:`)은 `journal_dir`이 있으면 늘 올린다(이 설정과 무관).
5. ChatGPT, Codex 일의 흔적, 열기, 요약 재료는 claude.ai, Claude Code와 같다(마지막 메시지 시각, 마지막 메시지 줄, 마지막 `ask_tail_messages`개 메시지). `ask.py`의 `SOURCE_LABEL`과 채팅 출처 판정에 `chatgpt`, `codex`를 넣는다. 일지 `[session:: <id>]` 연결은 `chatgpt:<id>`, `codex:<id>` 문서 id도 받는다.

### E. 단축키 입력
1. 칸을 누르면 "키를 누르세요" 상태가 되고, 다음에 누른 조합을 `ctrl+alt+h` 형식으로 기록한다. Esc는 기록 취소, Backspace는 기본값(`ctrl+alt+h`)으로.
2. 수정 키(Ctrl, Alt, Shift, Win) 하나 이상 + 일반 키 하나여야 한다. 수정 키만, 일반 키만은 거절.
3. 기록하자마자 경고 한 줄을 보여 준다(저장은 막지 않음, 예약 키는 막음)
   - 막음: `CLAUDE.md` 4번 피할 조합(Win+V, Win+;, Win+Shift+S, Ctrl+Alt+Del, Ctrl+Space, Shift+Space 등)
   - 경고: 등록부의 다른 도구 키(Win+., Ctrl+Alt+E, Win+Shift+K, Ctrl+Alt+K) "emoji-searcher가 쓰는 키입니다"
4. 저장 시 등록 시험: 새 키를 `RegisterHotKey`로 먼저 등록해 본다. 성공하면 옛 키를 해제한다. 실패하면 옛 키를 그대로 두고 "Ctrl+Alt+J는 다른 프로그램이 쓰고 있어 등록하지 못했습니다" 칸 오류로 저장을 멈춘다. (지금 `HotkeyManager`는 키 하나만 들고 있으므로 "새 키 시험 등록 후 교체" 동작을 추가한다. `hotkey.py`는 emoji-searcher 복사본이므로 고치면 원본과 다른 복사본도 같이 고치거나, 바꾼 부분을 thought-searcher `main.py` 쪽에 둔다. 구현 세션이 고르고 `CLAUDE.md` 5번 복사 표의 상태를 갱신한다)
5. 트레이 메뉴 `검색 (Ctrl+Alt+H)` 글자도 새 키로 바꾼다.

### F. 저장 즉시 적용
모두 재시작 없이 적용한다. 바뀐 키만 처리한다.
| 바뀐 것 | 적용 |
|---|---|
| `hotkey` | 3-E-4 |
| `archive_dir` | 지금 `choose_archive`와 같은 흐름(`set_archive_dir` → 상태 갱신 → `start_jobs`). 새 폴더가 없으면 저장 전 "폴더를 만들까요?" 확인 |
| `note_dirs` | 지금 `add_note_dir`/`remove_note_dir`와 같은 효과 → `sync_notes` 작업 제출 |
| `journal_dir`, `queue_*` | 다음 큐 계산부터(검색 창이 열려 있으면 바로 다시 그림) |
| `sources` | 감시 폴더 다시 등록, 다음 확인부터 반영. 새로 켠 서비스가 있으면 `지금 가져오기`와 같은 작업 제출 |
| `watch_dir`, `capture_dir` | `_watch_folder()` 다시 실행 |
| `code_collect_minutes` | `collect_timer` 주기 다시 시작 |
| `code_projects_dir`, `codex_dir` | 다음 수집부터 |
| `reminder_days`, `capture_stale_hours`, `export_page_url` | 다음 확인부터 |
| `weights`, `max_results` | `Searcher` 가중치와 상한 교체 |
| `extra_redact_patterns` | `Redactor` 다시 만들기(다음에 쓰는 md부터. 이미 쓴 md는 다시 만들지 않음, 설명 한 줄로 안내) |
| `ask_*`, `open_command` | 다음 호출부터 |
- 작업 스레드가 도는 중에 설정이 바뀌어도 그 작업은 옛 값으로 끝낸다. `Core.config`를 통째로 바꾸지 말고 새 dict로 교체(작업 스레드가 읽는 도중 키가 사라지지 않게).
- 적용 로직은 Qt 없는 함수 `settings.diff(old, new) -> set[str]`(바뀐 키 목록)와 `settings.validate(new) -> dict[str, str]`(키 → 오류 문구)로 나눠 테스트한다. 화면 쪽은 결과에 따라 위 표의 동작만 부른다.

### G. 저장 전 검사
| 항목 | 규칙 |
|---|---|
| 숫자 칸 | 정수(가중치는 실수), 표의 범위 안 |
| 경로 칸 | 빈 값 허용(기본값). 값이 있으면 존재하는 폴더여야 함. 보관 폴더만 "만들까요?" 허용 |
| 보관 폴더 | 노트 폴더와 같으면 거절. 노트 폴더 안이면 허용(기존 규칙: 보관 폴더 쪽은 노트로 안 봄) |
| 노트 폴더 | 중복 거절, 보관 폴더와 같으면 거절 |
| 큐 제외 폴더 | 노트 폴더 기준 상대 경로, `..` 거절 |
| 정규식 | `re.compile` 실패 시 몇 번째 줄인지와 오류 |
| `open_command` | `{path}`가 있어야 함 |
| `export_page_url` | `https://`로 시작 |
| 요약 AI | GPT나 Claude를 골랐는데 CLI 상태가 "없음"이면 경고(저장은 허용, F2 때 실패 사유로 다시 알림) |

### H. 새 설정 키 (`DEFAULT_CONFIG`에 추가)
| 키 | 기본값 | 뜻 |
|---|---|---|
| `sources` | `{"claude_ai": true, "chatgpt": true, "claude_code": true, "codex": true}` | 쓰는 서비스. 키가 없으면 이 값(기존 동작) |
| `queue_sources` | `["claude-ai", "claude-code", "note"]` | 큐에 올릴 출처 |
| `ask_provider` | `"claude"` | `"claude"` / `"codex"` / `"off"` |
| `ask_model_codex` | `"gpt-6-luna"` | GPT 요약 모델 |
| `ask_codex_effort` | `"low"` | GPT 추론 정도 |
| `ask_command_codex` | `[]` | 비면 자동 찾기(3-J-3) |
| `setup_done` | `false` | 시작 안내를 마쳤거나 건너뛰었는지. state가 아니라 config에 둔다(설정 창과 같은 생명주기) |
- 기존 키 `ask_model`(Claude 모델, 기본 `haiku`), `ask_command`(기본 `["claude"]`)는 그대로 쓴다. 이름을 바꾸지 않는다.
- `reminder_days: 0`은 알림 끔으로 새로 해석한다(지금 코드는 `or 7`이라 0이 7이 됨. 고친다).
- 기존 config.json이 있는 PC는 `setup_done`이 없어도 `true`로 본다(시작 안내가 뜨지 않게). 판정: "앱 시작 때 config.json이 없었음"일 때만 시작 안내.

### I. 수집 스크립트 안내 (수집 탭)
1. 켠 사이트(claude.ai, ChatGPT)마다 묶음 하나.
2. 단계 목록(README의 Tampermonkey 단계를 짧게): 확장 설치 → 설정 모드 고급 → 다운로드 모드 브라우저 API, `.json` 허용 → 크롬 "저장 위치 묻기" 끄기 → 메모리 절약 예외에 사이트 추가 → 스크립트 붙여 넣기.
   - Tampermonkey 확장 페이지, 크롬 설정 페이지는 `링크 열기`로 기본 브라우저에서 연다(앱이 직접 요청하지 않음. 기존 네트워크 규칙 안).
3. `스크립트 복사` 버튼: 누를 때만 `userscript/claude-sync.user.js` 또는 `chatgpt-sync.user.js` 내용을 클립보드에 넣고 "복사됨" 한 줄 표시.
4. 상태 한 줄: `_status.json`, `_status_chatgpt.json`을 읽어 "마지막 성공 11-10 14:20, 대화 87개" / "오류: 로그아웃됨 (11-10 13:00)" / "아직 수집 기록 없음". 기존 `capture_status_line`을 사이트별로 쓴다.
5. 회사 PC 주의 한 줄: "회사 크롬 정책으로 확장 설치가 막혀 있으면 zip 내보내기로 가져오세요."

### J. 요약 AI
1. 선택: Claude / GPT (Codex) / 끄기. 기본값
   - 기존 사용자: `claude`(지금 그대로)
   - 새 사용자(시작 안내): 켠 서비스에 Claude Code나 claude.ai가 있으면 Claude, 아니면 ChatGPT나 Codex가 있으면 GPT, 둘 다 없으면 끄기. (동료: GPT)
2. 끄기면 F2를 눌렀을 때 "요약 AI가 꺼져 있습니다 (설정 > 요약 AI)" 한 줄. 큐의 "F2 요약" 안내 글자도 숨긴다.
3. **CLI 찾기** (2026-11-10 이 PC에서 확인)
   - Claude: `ask_command`(기본 `claude`) → PATH. 이 PC: `%USERPROFILE%\.local\bin\claude`, Claude Code 2.1.319.
   - Codex: `ask_command_codex` → PATH의 `codex` → `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` 중 수정 시각이 가장 늦은 것. 이 PC는 PATH에 없고 Codex 데스크톱 앱이 넣은 `%LOCALAPPDATA%\OpenAI\Codex\bin\<해시>\codex.exe`(codex-cli 0.163.0-alpha.10.2)만 있었다. 해시 폴더는 여러 개일 수 있고 일부는 비어 있다(이 PC에 2개, codex.exe는 1개).
4. **CLI 상태 확인** (토큰 쓰지 않음). 요약 AI 탭을 열 때와 `다시 확인` 버튼에서 작업 스레드로 실행, 제한 시간 15초.
   | 단계 | Claude | Codex |
   |---|---|---|
   | 실행 파일 | 3번대로 찾음 | 3번대로 찾음 |
   | 버전 | `claude --version` | `codex --version` |
   | 로그인 | `claude auth status` (JSON, `loggedIn: true`, 종료 코드 0) | `codex login status` (`Logged in using ChatGPT`, 종료 코드 0) |
   - 결과 한 줄: `준비됨: Claude Code 2.1.319, claude.ai 로그인` / `로그인 필요: 터미널에서 claude 를 실행해 로그인하세요` / `찾지 못함: Claude Code CLI가 설치돼 있지 않거나 PATH에 없습니다. 아래 CLI 경로에 직접 지정할 수 있습니다`. Codex도 같은 꼴(`codex login`).
   - 설치나 로그인을 앱이 대신하지 않는다(인터뷰 결정: 상태만 표시).
   - 로그인 확인 출력 형식은 버전마다 바뀔 수 있으므로 종료 코드 0을 1차 기준으로, 문구는 보조로 쓴다.
5. **모델 목록**
   - Claude: 고정 목록 `haiku`(가장 저렴), `sonnet`, `opus` + 직접 입력. `claude --help`의 `--model` 설명이 "별칭 또는 전체 이름"이라고 하므로 직접 입력은 그대로 넘긴다. 2026-11-10 `--model haiku`가 실제로 `claude-haiku-5-5`로 돌았다(약 12초).
   - GPT: `%USERPROFILE%\.codex\models_cache.json`의 `models` 중 `visibility == "list"`인 것의 `slug`, `display_name`, `description`을 보여 준다(앱이 네트워크로 받지 않음. 파일이 없거나 깨졌으면 기본값 `gpt-6-luna` 하나 + 직접 입력). 2026-11-10 이 PC 목록: `gpt-6-luna`("Fast and affordable model for easier tasks."), `gpt-5.6-terra`, `gpt-5.6-luna`.
   - "가장 저렴" 표시: Claude는 `haiku`. GPT는 `gpt-6-luna`를 고정으로 표시한다. 캐시에는 가격 정보가 없다(필드 확인함). 외부 자료로는 ChatGPT Plus 5시간 한도가 Luna 계열이 가장 넉넉하다(아래 9번 출처, 공식 페이지 아님).
6. **Codex 실행 명령** (2026-11-10 이 PC에서 실제 실행으로 확인)
   ```
   codex exec -m <ask_model_codex> -c model_reasoning_effort="<ask_codex_effort>"
              --ephemeral --skip-git-repo-check -s read-only --ignore-user-config
              --color never -o <임시 파일> -
   ```
   - 재료는 표준 입력(`-`), 답은 `-o`(`--output-last-message`) 파일에서 읽는다. 표준 출력에는 머리말, 사용 토큰, MCP 오류 같은 잡음이 섞여 나온다(실제로 Notion MCP 인증 오류 줄이 섞였다).
   - `--ephemeral`: 세션 파일을 남기지 않는다. 실행 전후 `state_5.sqlite`의 threads 수가 51 → 51로 그대로였다(요약 호출이 Codex 수집에 새 대화로 잡히지 않음). 그래도 `SPEC-queue.md` 3-C-4처럼 전용 작업 폴더(`%LOCALAPPDATA%\thought-searcher\ask\`)에서 실행한다.
   - `-s read-only`: 모델이 명령을 실행하더라도 파일을 바꾸지 못하게. `--ignore-user-config`: 사용자의 `config.toml`(기본 모델 `gpt-5.6-luna`, 추론 `high`, 플러그인)을 무시. 인증은 그대로 쓴다.
   - 실측: `gpt-6-luna` + `low`로 한 줄 요약 13.5초, 토큰 약 13,000개(대부분 에이전트 기본 프롬프트). 재료 12,000자면 더 쓴다.
   - 환경 변수는 Claude처럼 정리한다(Codex 관련 `CODEX_*` 중 세션을 잇는 변수가 있으면 뺀다. 구현 세션이 확인).
7. Claude 실행은 지금 그대로(`claude -p --model <ask_model> --no-session-persistence --disable-slash-commands --strict-mcp-config --tools ""`).
8. `summaries.json`의 `model`에는 `claude:haiku`, `codex:gpt-6-luna`처럼 제공자를 붙여 저장한다(예전 값 `haiku`는 Claude로 읽는다). 요약 줄 끝에 작은 회색으로 모델 표시.
9. 실패 사유 문구는 제공자 이름을 넣는다("codex 명령을 찾지 못했습니다 (설정 > 요약 AI에서 확인)").
10. 참고 출처(외부, 공식 아님): Codex 요금과 Plus 한도 정리 [usagebox](https://usagebox.com/articles/openai-codex-pricing-usage-limits-2026), [seawork](https://seawork.ai/en/blogs/codex-pricing/). 구현 세션은 OpenAI 공식 Codex 요금 페이지로 다시 확인한다.

### K. 시작 안내 (첫 실행)
1. 조건: 앱 시작 때 config.json이 없음(그리고 예전 이름 brain-searcher 데이터 이동도 없었음). 트레이 아이콘을 먼저 띄우고, 1초 뒤 설정 창을 "시작하기" 모드로 연다.
2. 시작하기 모드는 같은 설정 창에서 탭 대신 단계 화면을 보여 주고 아래 버튼이 `이전` / `다음` / `건너뛰기`(마지막 단계는 `마치기`).
3. 단계
   1. **쓰는 서비스**: 3-C 체크 4개(3-C-3 추정으로 미리 체크). "끈 서비스는 수집도 알림도 하지 않습니다."
   2. **보관 폴더**: 기본 위치를 보여 주고 `그대로 쓰기` / `바꾸기...`. 회사 PC 개인 클라우드 경고.
   3. **요약 AI**: 3-J-1 기본값으로 고른 상태. CLI 상태 확인을 자동으로 돌려 한 줄 표시. 모델은 가장 싼 것으로 정해져 있고 바꾸려면 설정에서.
   4. **노트 폴더와 수집 스크립트**: 노트 폴더 `추가...`(선택). 켠 사이트가 claude.ai나 ChatGPT면 3-I 묶음을 그대로 보여 줌. 아니면 이 단계에서 수집 부분은 숨김.
4. `마치기`: 고른 값으로 config.json 저장(`setup_done: true`) → 3-F 적용 → 수집 시작 → 트레이 알림 "준비됐습니다. Ctrl+Alt+H로 검색 창을 엽니다."
5. `건너뛰기`(아무 단계에서나): 지금과 같은 기본값으로 config.json 저장(`setup_done: true`, `sources` 모두 true) → 지금처럼 동작. 알림 "설정은 트레이 메뉴 '설정...'에서 바꿀 수 있습니다."
6. 시작 안내 창을 X로 닫으면 건너뛰기와 같다. 다음 실행에 다시 뜨지 않는다.
7. 시작 안내가 떠 있는 동안에는 수집을 시작하지 않는다(엉뚱한 보관 폴더에 쌓이지 않게). 단축키와 트레이는 동작.

## 4. 트레이 메뉴 (바뀐 뒤)
```
검색 (Ctrl+Alt+H)
설정...
──────
지금 가져오기
claude.ai 내보내기 받으러 가기     ← claude.ai 켰을 때만
──────
대화 보관 폴더 열기
상태 보기
고급 >
  zip 파일 직접 고르기...
  ──────
  검색 색인 다시 만들기
  대화 md 전부 다시 만들기
──────
종료
```
- 빠지는 것: `고급 > 대화 보관 폴더 바꾸기...`, `고급 > 노트 폴더 추가...`, `고급 > 노트 폴더 빼기`(설정 창 일반 탭으로).
- 보관 폴더가 없을 때 알림 문구의 "트레이 메뉴 '고급 > 대화 보관 폴더 바꾸기'"는 "트레이 메뉴 '설정...'"으로 바꾼다. 알림을 누르면 설정 창 일반 탭을 연다(`messageClicked`, 종류 `archive`).
- 단축키 등록 실패 알림도 "설정 > 일반에서 바꿀 수 있습니다"를 붙이고, 누르면 설정 창을 연다.

## 5. 엣지 케이스
| 상황 | 처리 |
|---|---|
| 설정 창이 열린 채 트레이에서 노트 폴더 같은 것을 바꿀 길 | 없음(트레이에서 뺐음). 외부 편집만 3-A-4로 잡는다 |
| 저장 중 작업 스레드가 수집 중 | 그 작업은 옛 값으로 끝남. 다음 작업부터 새 값 |
| 보관 폴더를 바꿨는데 기존 md가 옛 폴더에 있음 | 옮기지 않는다(지금 동작 그대로). 설명 한 줄: "기존 md는 옮기지 않습니다. 필요하면 직접 옮긴 뒤 '검색 색인 다시 만들기'" |
| 새 단축키 등록 실패 | 옛 키 유지, 저장 멈춤(3-E-4) |
| 옛 키 해제 뒤 새 키 등록 사이 실패 | 새 키를 먼저 등록하므로 생기지 않음. 같은 키를 다시 저장하면 등록 시험 생략 |
| `models_cache.json`이 없음(Codex 한 번도 안 씀) | 모델 목록에 `gpt-6-luna` 하나 + 직접 입력 |
| 직접 입력한 모델 이름이 틀림 | 저장은 허용. F2 실패 시 CLI 오류 마지막 줄을 사유로 표시(지금 `_last_line` 방식) |
| Codex가 업데이트돼 `bin\<새 해시>\`로 바뀜 | 자동 찾기가 매번 가장 늦은 codex.exe를 고름. `ask_command_codex`를 지정했으면 그 경로가 없을 때 "찾지 못함" |
| CLI 상태 확인이 15초 넘게 걸림 | "확인 시간 초과" 한 줄. 설정 저장은 막지 않음 |
| ChatGPT만 켰는데 claude.ai zip이 다운로드 폴더에 들어옴 | 가져오지 않고 이력에도 남기지 않음. 나중에 켜면 가져옴 |
| 큐 출처에서 뺀 출처의 직접 닫기 기록 | `queue_closed`는 그대로 둠(다시 켜면 그대로 적용) |
| config.json에 사용자가 손으로 넣은 주석 같은 잘못된 값(예: `queue_days: "abc"`) | 창은 기본값을 보여 주고 칸 아래 "config.json 값이 잘못돼 기본값을 보여 줍니다" |
| 시작 안내 중 앱 종료 | `setup_done` 저장 전이므로 config.json 없음 → 다음 실행에 다시 시작 안내 |
| 동료 PC에 Codex 데스크톱 앱 없이 npm으로 설치한 `codex` | PATH에서 찾음 |
| 동료 PC에 PySide6 없음 | 기존 `_deps.py` 흐름(첫 실행 설치 제안) 뒤에 시작 안내 |

## 6. 제약
- 기존 규칙 그대로: PySide6, pytest만. 앱 코드에 네트워크 모듈 없음(`test_forbidden_network.py` 유지). CLI 실행은 F2와 CLI 상태 확인(버전, 로그인 상태)에서만.
- CLI 상태 확인은 AI 호출을 하지 않는다(토큰 0).
- 설정 창은 Qt 위젯(`QDialog` + `QTabWidget`)으로, 검색 창과 같은 글꼴. 모든 문구 한국어 존댓말, em dash 없음.
- 저장소에 개인 경로를 기본값으로 넣지 않는다.
- config.json 형식(평평한 키 + `weights`)을 바꾸지 않는다. 새 키만 더한다.

## 7. 관련 파일
| 파일 | 내용 |
|---|---|
| `app/settings.py` (새) | Qt 없음. 설정 칸 정의(키, 종류, 범위, 기본값, 탭), `validate`, `diff`, 기존 config에서 `sources`/`queue_sources`/`setup_done` 읽기 규칙, 시작 안내 기본값 계산(설치 흔적 추정), 단축키 예약/등록부 검사 |
| `app/cli_check.py` (새) | Qt 없음. Claude/Codex 실행 파일 찾기, 버전, 로그인 상태, `models_cache.json` 읽기 |
| `app/settings_window.py` (새) | 설정 창과 시작 안내 화면 |
| `app/ask.py` | 제공자별 명령 구성(`build_command`), Codex 실행(`-o` 파일 읽기), `SOURCE_LABEL`에 chatgpt/codex, 채팅 출처 판정 |
| `app/queue.py` | `queue_sources`로 출처 거르기 |
| `app/core.py` | `sources`에 따른 수집/가져오기/알림 거르기, `reminder_days: 0`, 설정 교체(`apply_config`) |
| `app/main.py` | 트레이 메뉴 변경, `설정...`, 저장 후 적용(단축키 교체, 타이머, 감시 폴더, Searcher), 첫 실행 판정 |
| `app/window.py` | 상태 줄 ⚙ 버튼, 요약 AI 꺼짐일 때 F2 안내 |
| `app/store.py` | 새 기본값, "시작 때 config.json이 없었음" 표시(`load_config` 결과에) |
| `app/hotkey.py` 또는 `main.py` | 새 키 시험 등록 후 교체 (3-E-4) |
| `README.md` | 첫 실행(시작 안내), 설정 창, 요약 AI 고르기(Claude/GPT, CLI 설치와 로그인은 사용자가), ChatGPT만 쓰는 경우 |

## 8. 결정 사항과 근거
| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 첫 실행 때만 짧은 시작 안내, 건너뛰기 가능 | 동료가 config.json을 몰라도 시작. 건너뛰면 지금과 같음 | 묻지 않음(지금), 단계 없이 설정 창만 |
| config.json이 있으면 시작 안내 안 띄움 | CG의 두 PC 동작이 바뀌지 않게 | `setup_done` 없으면 무조건 |
| 쓰는 서비스 체크로 수집, 알림, 메뉴를 함께 끔 | ChatGPT만 쓰는 사람에게 claude.ai 내보내기 알림이 매일 뜨는 문제 | 알림만 끄기, 이력으로 자동 판단 |
| 큐 출처도 설정 | ChatGPT만 쓰면 큐가 비어 쓸모없음 | 지금처럼 고정 |
| 탭 4개(일반/수집/요약 AI/고급) | 자주 쓰는 것과 손댈 일 없는 것 분리 | 한 페이지 + 접기, 왼쪽 목록 |
| 설정은 창으로, 작업(색인, 다시 만들기, zip 고르기)은 트레이 고급에 | 설정과 작업은 성격이 다름 | 전부 창으로, 트레이 그대로 |
| 저장/취소 버튼, 저장 즉시 적용 | 검사 후 한 번에, 재시작 없이 | 바꾸면 즉시 저장, 재시작 필요 |
| 단축키 키 기록 + 저장 전 등록 시험 | 실패해도 옛 키가 살아 있음 | 목록 고르기, 글자 입력 |
| 요약 AI 기본은 가장 싼 모델(haiku, gpt-6-luna) + 목록 선택 | 토큰 절약, 필요하면 바꿀 수 있음 | 고정, 직접 입력만 |
| GPT 모델 목록은 `models_cache.json`에서 | 네트워크 없이 그 PC의 Codex가 아는 모델만 | 고정 목록(금방 낡음) |
| Codex는 `--ephemeral` + `-o` 파일 | 수집에 새 대화로 잡히지 않음(실측), 표준 출력 잡음 회피 | `--json` 이벤트 파싱 |
| CLI 확인은 설치와 로그인만, 토큰 안 씀 | 확인 버튼이 사용량을 쓰지 않게 | 시험 요약 |
| CLI 없을 때 상태만 표시 | 사내 PC 설치 정책을 앱이 건드리지 않음 | 설치 콘솔 띄우기, 명령 복사 버튼 |
| 스크립트 안내는 단계 + 복사 버튼 + 상태 | README를 몰라도 설치, 동작 여부 바로 확인 | README 링크만 |
| 창에 없는 키는 보존 | 손으로 넣은 설정과 앞으로 생길 키를 지키기 | 창 내용으로 통째로 덮어쓰기 |

## 9. 가정 (구현 중 바꿀 수 있음)
- 설정 창 최소 크기 560x480, 숫자 칸 범위는 3-B 표의 값.
- 시작 안내는 설정 창과 같은 창의 다른 모드로 만든다(창을 하나 더 만들지 않음).
- 큐 출처 기본값을 정할 때 Codex를 켠 새 사용자는 `codex`도 큐에 넣는다.
- GPT 추론 정도는 low/medium만 보여 준다(high 이상은 요약에 과함). 직접 입력은 config.json으로.
- 상태 확인 결과는 창이 열려 있는 동안만 기억한다(저장하지 않음).
- 설정 창이 열려 있어도 검색 창 단축키는 동작한다(설정 창 단축키 칸에 초점이 있을 때만 전역 키를 잠시 해제해 기록이 되게 한다. 구현 세션이 필요하면).

## 10. 미결 사항
- 동료 PC: Python 설치 여부, PATH에 `codex`가 있는지(데스크톱 앱 번들만 있을 수 있음), 회사 크롬에서 Tampermonkey 설치 허용 여부. 4번 체크포인트에서 확인.
- Codex 공식 요금 페이지 기준 "가장 저렴한 모델" 재확인(외부 자료 기준 gpt-6-luna). 모델 목록이 바뀌면 "가장 저렴" 표시 대상만 고친다.
- `codex exec`가 사용자 플러그인의 MCP를 `--ignore-user-config`에도 띄우는 것으로 보인다(Notion MCP 인증 오류 줄). 요약 결과에는 영향이 없었지만, 끌 수 있는 옵션이 있으면 구현 세션이 넣는다.
- Codex 실행 시 정리할 환경 변수 목록.

## 11. 구현 단계
단계마다 따로 커밋하고, 앞 단계만으로도 쓸 수 있게 한다.
1. **설정 로직**: `settings.py`(칸 정의, 검사, diff, 기본값 규칙), `store.py` 새 키, `core.py` 설정 교체와 `sources`/`reminder_days: 0`, `queue.py` `queue_sources`. 화면 없음.
2. **설정 창**: `settings_window.py` 4개 탭, 저장/취소, 즉시 적용, 트레이 메뉴 변경, ⚙ 버튼, 단축키 기록과 등록 시험.
3. **요약 AI**: `cli_check.py`, `ask.py` Codex 실행, 요약 AI 탭, `summaries.json` 모델 표기, 큐에 ChatGPT/Codex 요약 재료.
4. **시작 안내와 스크립트 안내**: 시작하기 모드, 수집 탭 스크립트 묶음, README.

## 12. 검증 계획
- 자동 테스트 (pytest, 합성 데이터만. 실제 CLI는 부르지 않음)
  - `test_settings.py`
    - 칸 정의가 `DEFAULT_CONFIG`의 모든 키를 덮음(설정 창에 빠진 키가 없음). 예외 목록은 테스트 안에 명시(`setup_done` 등)
    - `validate`: 숫자 범위 경계(안/밖), 존재하지 않는 경로, 보관 폴더 = 노트 폴더 거절, 노트 폴더 중복, 큐 제외 `..` 거절, 잘못된 정규식(줄 번호 포함), `open_command`에 `{path}` 없음, `https://` 아닌 주소
    - `diff`: 바뀐 키만 나옴, `weights` 안쪽 값 하나만 바뀌어도 `weights`
    - 저장 시 창에 없는 키 보존(알 수 없는 키를 넣은 config로 왕복)
    - 기존 config(새 키 없음) → `sources` 모두 true, `queue_sources` 지금 값, 시작 안내 안 뜸
    - config.json 없음 → 시작 안내 뜸. 건너뛰기 결과 config가 지금 기본값과 같음(+`setup_done`)
    - 시작 안내 기본값: `.claude/projects`만 있는 가짜 홈 → Claude Code 체크, 요약 Claude. `.codex`만 → Codex 체크, 요약 GPT. 아무것도 없음 + ChatGPT 체크 → 요약 GPT, 큐 `["chatgpt", "note"]`. 아무것도 없음 → 요약 끄기
    - 단축키: 예약 키 거절, 등록부 다른 도구 키 경고, 수정 키만/일반 키만 거절, `ctrl+alt+h` 형식 정규화
  - `test_sources.py`
    - claude.ai 끔 → `reminder_due()` None, claude.ai zip과 `claude-ai_*.json` 가져오지 않고 이력에도 안 남김, 수집 멈춤 알림 없음
    - ChatGPT 끔 → ChatGPT zip, `chatgpt_*.json` 무시
    - Claude Code 끔 → `collect_code`가 아무것도 안 함, Codex만 켜면 Codex만 수집
    - 껐다 켜면 다음 확인에서 가져옴
    - `reminder_days: 0` → 알림 없음
  - `test_queue.py` (추가): `queue_sources`에 `chatgpt`, `codex`를 넣으면 올라오고, 빼면 빠짐. 기본값은 지금 결과와 같음. `[session:: chatgpt:<id>]` 연결
  - `test_cli_check.py`
    - 가짜 실행 파일(작은 .cmd 또는 python 스크립트)로 버전/로그인 성공, 로그인 안 됨(종료 코드 1), 없음, 시간 초과
    - Codex 자동 찾기: 가짜 `%LOCALAPPDATA%\OpenAI\Codex\bin\<해시1>\codex.exe`, `<해시2>\`(빈 폴더) → 있는 것, 둘 다 있으면 수정 시각 늦은 것. 지정 경로가 우선
    - `models_cache.json` 합성 파일: `visibility: "hide"` 제외, 없거나 깨지면 기본 하나
  - `test_ask.py` (추가)
    - `build_command`: Claude는 지금과 같음, Codex는 3-J-6 인자 순서(`-m`, `-c model_reasoning_effort=...`, `--ephemeral`, `-s read-only`, `-o <파일>`, `-`)
    - 가짜 `codex`가 표준 출력에 잡음, `-o` 파일에 답을 쓰면 답만 읽음
    - `ask_provider: off` → 호출 없이 "꺼져 있음" 사유
    - `summaries.json` 예전 `model: "haiku"`를 Claude로 읽음, 새로 쓸 때 `codex:gpt-6-luna`
    - ChatGPT, Codex 일의 재료가 마지막 메시지들로 만들어짐
  - 기존 테스트 전체 통과, `test_forbidden_network.py` 통과
- **End-to-end** (마지막에 실행해 통과해야 완료)
  1. `pytest` 전체 통과
  2. CG PC(기존 config.json) 앱 재시작 → 시작 안내 안 뜸, 트레이 메뉴가 4번 모양, 동작은 이전과 같음(큐, 검색, 수집)
  3. `설정...` → 4개 탭, 지금 값이 그대로 보임 → 아무것도 안 바꾸고 저장 → config.json 내용 그대로(키 순서 외 차이 없음)
  4. 단축키를 Ctrl+Alt+J로 바꿔 저장 → 재시작 없이 Ctrl+Alt+J 동작, Ctrl+Alt+H 해제. 다른 프로그램이 쓰는 키로 바꾸면 오류, 옛 키 유지
  5. 노트 폴더 추가/빼기, 큐 기간 7일로 → 저장 즉시 검색과 큐에 반영
  6. 요약 AI를 GPT로 → 상태 줄 "준비됨" → F2 → 30초 안에 요약, 줄 끝 `codex:gpt-6-luna` → Codex 대화 수집에 새 대화가 생기지 않음(`src:codex` 최근 목록 그대로)
  7. 요약 AI 끄기 → F2 → "꺼져 있습니다" 한 줄
  8. 빈 데이터 폴더(`THOUGHT_SEARCHER_APPDATA`, `THOUGHT_SEARCHER_LOCALAPPDATA`를 임시 폴더로)로 실행 → 시작 안내 → ChatGPT만 체크, 요약 GPT로 마침 → claude.ai 메뉴 없음, 다음 날로 시계를 돌린 `reminder_due` 확인에서 알림 없음, 큐 출처 `chatgpt`, `note`
  9. 8번을 다시 하되 첫 단계에서 건너뛰기 → config가 지금 기본값 + `setup_done`
  10. 수집 탭 `스크립트 복사` → 클립보드에 스크립트 내용, 상태 줄에 마지막 성공 시각
  11. config.json을 메모장으로 깨뜨림 → 재시작 → 설정 창 경고 줄 → 저장 전까지 파일 그대로 → 저장하면 새로 씀

## 13. 사람 검토 체크포인트
1. **동료 PC 시험** (4단계 후): 동료가 README와 시작 안내만 보고 clone, 설치, 첫 실행, ChatGPT 수집 스크립트 설치, GPT 요약 F2까지 해 본다. 막힌 곳(문구, 순서, Python/CLI/Tampermonkey 설치 문제)을 모아 사용자가 고칠 범위를 정한다. 이때 10번 미결(동료 PC의 Python, codex 위치, 크롬 확장 정책)도 확정한다.
