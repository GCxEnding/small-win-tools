# thought-searcher (생각 검색기) 🧠

Claude(와 ChatGPT) 채팅 기록을 내 PC에 영구 보관하고, 흐릿한 기억(단어 몇 개)만으로 예전 대화를 찾는 트레이 도구예요.
"정리"하지 않고 "다 저장하고 검색"합니다. 수집, 변환, 검색 모두 로컬에서 하고 AI 토큰을 쓰지 않아요.

- claude.ai 데이터 내보내기 zip이 다운로드 폴더에 들어오면 자동으로 md로 바꾸고 색인합니다.
- Claude Code 세션(`%USERPROFILE%\.claude\projects`)을 30분마다 md로 바꾸고, 원본 jsonl도 따로 복사해 둡니다(30일 자동 삭제 대비).
  md에는 사람 입력과 Claude 답변 글만 담고, 도구 호출(Bash, Read 등)과 그 결과는 뺍니다.
- 가져오는 동안 트레이 아이콘에 ⏳가 붙고, 아이콘에 마우스를 올리면 진행 상황(`Claude Code 대화 가져오는 중 (3/14)`)이 보여요. `지금 가져오기`를 누르면 끝났을 때 `가져오기 완료: 새 대화 N개, 바뀐 대화 M개` 알림이 뜹니다.
- `Ctrl+Alt+H`로 검색 창을 띄웁니다.
- 마지막 가져오기 후 7일이 지나면 내보내기를 받으라고 알려 드려요.

## 설치

Python 3.10 이상(python.org 배포판 권장, `sqlite3`에 FTS5가 있어야 함)이 필요합니다.

```bash
cd small-win-tools/thought-searcher
pip install -r requirements.txt
```

## 첫 실행

```bash
pythonw thought_searcher.pyw
```

1. 묻는 것 없이 트레이에 🧠 아이콘이 생기고, 곧바로 Claude Code 세션을 모읍니다.
   대화 md는 기본 위치 `%LOCALAPPDATA%\thought-searcher\archive`에 쌓여요. 트레이 메뉴 `대화 보관 폴더 열기`로 바로 열 수 있습니다.
   다른 곳(동기화 폴더 등)에 두고 싶으면 `고급 > 대화 보관 폴더 바꾸기...`로 바꾸세요.
2. claude.ai 대화는 트레이 메뉴 `claude.ai 내보내기 받으러 가기`로 내보내기 페이지를 열어 zip을 받으면 됩니다(메일로 링크가 와요). 다운로드 폴더에 들어오면 자동으로 가져옵니다.
   내보내기는 `conversations-000.zip`, `projects-000.zip`, `memories-000.zip` 등 여러 개로 나뉘어 오는데, 필요한 것만 알아서 읽고 나머지는 무시합니다.
   처리한 zip은 지우거나 옮기지 않아요. 같은 zip을 다시 넣어도 중복되지 않습니다.
   `memories-000.zip`이 안 받아지면 claude.ai 메모리 화면에서 받은 `claude-memory-YYYY-MM-DD.zip`(md 묶음)을 다운로드 폴더에 두세요. 같은 메모리 문서로 들어가고, 둘 중 더 새것이 남습니다.
3. ChatGPT 내보내기 zip(`<긴 해시>-<날짜>-<해시>.zip`)도 다운로드 폴더에 두면 자동으로 가져옵니다. 파일 이름이 아니라 안의 `conversations.json` 구조로 알아봐요. 생각 과정, 도구 호출, 첨부 원본은 담지 않습니다.

### 시작 프로그램 등록

`Win+R` → `shell:startup` → 열린 폴더에 바로 가기를 만듭니다.

- 대상: `pythonw.exe "D:\...\small-win-tools\thought-searcher\thought_searcher.pyw"`
- 시작 위치: `D:\...\small-win-tools\thought-searcher`

## 검색 문법

| 입력 | 뜻 |
|---|---|
| `로그 배포` | 두 단어가 **대화 안 어디에든** 있으면 찾음 (한 메시지에 같이 있을 필요 없음) |
| `로그배포` | 한글은 띄어쓰기를 무시해요. `로그 배포`(구문)와 같은 것을 찾습니다 |
| `log` | 영어는 앞부분만 맞아도 찾음 (`logpick`, `logcut`) |
| `"nginx 설정"` | 구문: 붙어서 나와야 함 |
| `-롤백` | 제외: 이 단어가 있는 대화는 뺌 |
| `src:ai` `src:code` `src:project` `src:memory` `src:gpt` `src:note` | 출처 필터 (`src:노트`도 됨) |
| `proj:small` | 프로젝트 이름 일부 |
| `after:2026-10` `before:2026-11-05` | 날짜 범위 |
| `배` (1글자) | 제목에서만 찾음 |
| (빈 입력) | 최근 대화 목록 |

순위는 BM25 관련도에 제목 일치, 한 메시지 안 동시 등장, 최근 대화 가산을 더해 정합니다. 가중치는 `config.json`의 `weights`에서 바꿀 수 있어요.

### 검색 창 키

| 키 | 동작 |
|---|---|
| `↑` `↓` | 결과 이동 |
| `←` `→` | 같은 대화의 다른 맞은 메시지로 미리보기 전환 (입력란 커서가 맨 끝일 때) |
| `Enter` | md를 맞은 메시지 줄에서 열기 (기본 VS Code, 실패하면 기본 연결 프로그램) |
| `Ctrl+Enter` | 미리보기 중인 메시지 본문 복사 |
| `Shift+Enter` | 대화 전체 md 복사 |
| `Esc` | 닫기 |

## 트레이 메뉴

평소에는 아무것도 누르지 않아도 됩니다. 가져오기는 자동이에요.

| 메뉴 | 하는 일 |
|---|---|
| 검색 (Ctrl+Alt+H) | 검색 창 열기 |
| 지금 가져오기 | 30분을 기다리지 않고 Claude Code 대화와 노트 폴더를 바로 모으고, 다운로드 폴더의 새 zip도 확인 |
| claude.ai 내보내기 받으러 가기 | claude.ai 데이터 내보내기 페이지를 브라우저로 열기 |
| 대화 보관 폴더 열기 | 대화 md가 쌓인 폴더 열기 |
| 상태 보기 | 마지막 가져오기 시각, 대화 수, 경고 |
| 고급 > zip 파일 직접 고르기... | 다운로드 폴더 밖에 있는 zip 가져오기 |
| 고급 > 대화 보관 폴더 바꾸기... | md를 쌓을 폴더 바꾸기 |
| 고급 > 노트 폴더 추가... | 내 md 폴더(Obsidian 볼트 등)를 검색에 넣기 |
| 고급 > 노트 폴더 빼기 | 등록한 노트 폴더를 검색에서 빼기 (파일은 그대로) |
| 고급 > 검색 색인 다시 만들기 | 검색이 이상할 때. md에서 색인만 새로 만듦 |
| 고급 > 대화 md 전부 다시 만들기 | 도구를 업데이트한 뒤 안내가 뜰 때. 받아 둔 zip과 Code 세션 복사본에서 md를 새로 만듦 |

화면 없이 쓰고 싶으면 CLI도 있어요.

```bash
python -m app.cli search 로그 배포
```

(`import <zip>`, `collect`, `reindex`, `rebuild-index`, `rebuild`, `status`도 있습니다.)

## 보관 폴더 주의 ⚠

- **회사 PC 보관본을 개인 클라우드(OneDrive 개인, Google Drive 등)에 두지 마세요.** PC마다 보관 폴더를 따로 정하고, 서로 공유하거나 합치지 않습니다.
- md는 도구가 항상 다시 만들어 덮어씁니다. 직접 고친 내용은 보존되지 않아요.
- 원본에서 사라진 대화도 md는 지우지 않고 `source_status: missing`으로 표시만 합니다.
- md에 쓰기 전에 알려진 형식의 비밀 값(API 키, 토큰, 개인 키 등)을 `***가림:<종류>***`로 바꿉니다. 원본 zip과 jsonl 복사본은 그대로예요. 회사 전용 형식은 `extra_redact_patterns`에 정규식으로 추가하세요.
- 보관 폴더가 없어지면(드라이브 분리 등) 수집을 멈춥니다. 엉뚱한 곳에 쌓이지 않도록 폴더를 새로 만들지 않아요.

## 데이터 위치 (PC별, 저장소 밖)

| 위치 | 내용 |
|---|---|
| `%APPDATA%\thought-searcher\config.json` | 설정 (보관 폴더, 노트 폴더, 단축키, 감시 폴더, 가중치 등) |
| `%APPDATA%\thought-searcher\state.json` | zip 처리 이력, 마지막 가져오기/수집/알림 시각 |
| `%LOCALAPPDATA%\thought-searcher\index.db` | 검색 색인 (지워도 md에서 다시 만듦) |
| `%LOCALAPPDATA%\thought-searcher\raw\claude-code\` | Code 원본 jsonl 복사본 |
| `%LOCALAPPDATA%\thought-searcher\logs\` | 로그 (1MB x 3) |

## 테스트

```bash
pytest
```

- 성능 테스트(`test_perf.py`)는 합성 대화 2만 개를 만들어 색인하므로 몇 분 걸립니다.
- 실제 샘플 테스트(`test_real_sample.py`)는 `tests/local/`이 있을 때만 돕니다. 이 폴더에는 실제 대화가 들어 있으니 **커밋하지 마세요**(`.gitignore`에 들어 있음).
- 합성 fixture는 `tests/fixtures/make_fixtures.py`, 기대 md 초안은 `make_expected.py`로 다시 만들 수 있어요.

## 새 출처 추가

`app/importers/`에 파일 하나를 만들어 `detect`, `iter_conversations`, `snapshot_time`, `is_full_snapshot`, `snapshot_sources`를 구현하고 `base.py`의 `registry()`에 한 줄 추가합니다. 새 출처 이름(`source`)으로 보관 폴더를 쓰려면 `archive.py`의 `SOURCE_DIRS`, `ARCHIVE_SUBDIRS`에, 검색 필터와 배지는 `query.py`의 `SOURCE_ALIASES`, `window.py`의 `BADGE`에 한 줄씩 넣으세요(`chatgpt.py` 참고).

## 내 노트 md 넣기 (노트 폴더)

Obsidian 일지, 메모처럼 직접 쓴 md는 `고급 > 노트 폴더 추가...`로 폴더를 고르면 형식 변환 없이 그대로 검색됩니다.

- 파일은 **읽기만** 합니다. 복사하거나 고치지 않고, 보관 폴더에도 쓰지 않아요.
- 하위 폴더까지 모두 읽고, 점으로 시작하는 폴더(`.obsidian`, `.git` 등)는 건너뜁니다.
- 검색 결과에 `노트` 배지로 나오고, `src:note`로 노트만 찾을 수 있어요. `proj:`에는 `폴더 이름/하위 폴더`가 들어갑니다(예: `proj:MyVault/2026`).
- 제목은 파일 이름(frontmatter `title`이 있으면 그것)입니다.
- 날짜는 frontmatter `date`, 파일 이름의 `YYYY-MM-DD`/`YYYYMMDD`, 파일 수정 시각 순으로 정합니다. 일지는 고친 날이 아니라 일지 날짜로 정렬돼요.
- `#` 제목마다 구역으로 나눠 색인하고, 구역 제목도 검색됩니다. Enter를 누르면 원본 파일이 맞은 줄에서 열립니다.
- 바뀐 노트는 30분마다(`지금 가져오기`를 누르면 바로) 반영됩니다.

## 다른 곳의 대화 md 넣기

Codex 기록처럼 이미 md로 가지고 있는 대화는 보관 폴더의 `imported\`에 정해진 형식으로 넣으면 같이 검색됩니다. 형식과 방법은 [MD_IMPORT.md](MD_IMPORT.md)를 보세요.
