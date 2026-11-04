# gohome-vlog 🏠

퇴근 전에 "오늘 뭐 했더라" 떠올리는 시간을 줄여 주는 작은 도구예요. 하루 동안 어떤 프로그램, 어떤 프로젝트, 어떤 서버에서 일했는지 **활성 창 기준으로** 자동 기록해 두었다가, 퇴근 무렵 Obsidian 일지에 붙여 넣을 요약을 만들어 줘요.

- 표시 이름은 **gohome** (트레이, 알림)
- 퇴근 시간(기본 17:50)이 되면 "오늘 브이로그 다 찍었습니다. 이제 집에 가셔도 됩니다." 하고 알려 줘요.
- 실행 중에는 인터넷을 전혀 안 써요. 회사 망에서도 그냥 돌아갑니다.

## 수집하는 것 / 하지 않는 것

**입력 내용은 절대 수집하지 않아요.** 기록하는 건 딱 세 가지예요.

| 수집하는 것 |
|---|
| 활성 창의 **프로세스 이름** (예: `idea64.exe`) |
| 활성 창의 **제목** (예: `workflow-core – ApprService.java`) |
| 그 창을 보고 있던 **시각** |

그리고 "마지막으로 입력한 시각"만 Windows에서 받아 자리 비움(idle) 판정에 써요. 무슨 키를 눌렀는지, 몇 번 눌렀는지는 알 수 없어요.

**수집하지 않는 것**

- 키보드, 마우스 입력의 내용이나 횟수
- 스크린샷, 창 안의 내용
- 브라우저 URL
- 네트워크 전송, 동기화, AI 요약 호출 (아무 데도 보내지 않아요)
- Obsidian 일지 파일 직접 수정 (요약은 클립보드와 요약 파일로만 줘요)

**쓰지 않는 Windows API**

입력을 가로채거나 읽는 방식은 전부 쓰지 않아요: 입력 훅, Raw Input, 키 상태 반복 조회 등. 쓰는 건 활성 창 정보(`GetForegroundWindow`, `GetWindowTextW`, `GetWindowThreadProcessId`, `OpenProcess`, `QueryFullProcessImageNameW`), 마지막 입력 시각(`GetLastInputInfo`), 잠금/절전 알림(`WTSRegisterSessionNotification`, `WM_POWERBROADCAST`)뿐이에요. `tests/test_forbidden_api.py` 가 소스에 금지 API 이름이 없는지 매번 검사해요.

데이터는 내 PC의 로컬 폴더에만 두고, 원본 기록은 하루가 지나면 지워요.

## 설치

Python 3.10 이상이 필요해요.

```bash
git clone https://github.com/GCxEnding/small-win-tools.git
```

```bash
cd small-win-tools/gohome-vlog
```

```bash
pip install -r requirements.txt
```

## 실행

```bash
pythonw gohome_vlog.pyw
```

창은 안 뜨고 작업 표시줄 트레이에 아이콘이 생겨요. 5초마다 활성 창을 확인해서 조용히 기록해요. 이미 실행 중이면 두 번째 실행은 바로 종료돼요.

## 컴퓨터 켤 때 자동 실행

1. Win+R → `shell:startup` 입력 → Enter (시작프로그램 폴더가 열려요)
2. 그 폴더에서 오른쪽 클릭 → 새로 만들기 → 바로 가기
3. 대상에 아래처럼 입력 (경로는 본인 것으로)

```text
pythonw.exe "D:\...\small-win-tools\gohome-vlog\gohome_vlog.pyw"
```

`pythonw.exe` 를 못 찾는다고 하면 `where pythonw` 로 나온 전체 경로를 넣어 주세요.

> 💡 그냥 `pythonw.exe` 라고 쓰면 Python 설치 관리자의 실행기(런처)가 프로세스 하나를 더 띄워 둘 수 있어요(약 15MB).
> 아래 명령으로 나온 실제 경로를 대상에 넣으면 프로세스가 하나만 떠요.
>
> ```bash
> python -c "import sys; print(sys.executable.replace('python.exe', 'pythonw.exe'))"
> ```

## 트레이 메뉴

- **오늘 요약 복사**: 지금까지의 요약을 만들어 파일로 저장하고 클립보드에 복사
- **요약 폴더 열기**: 요약 파일이 있는 폴더 열기
- **일시 정지** (30분 / 1시간 / 다시 시작할 때까지), **재개**: 정지 중에는 아이콘이 바뀌고, 그 구간은 자리 비움처럼 집계에서 빠져요.
- **오늘 기록 삭제**: 확인 후 오늘 원본 기록과 오늘 요약 파일을 바로 삭제
- **규칙 다시 읽기**: `rules.json` 고친 걸 바로 반영
- **종료**

### 퇴근 알림과 요약 시점

- 알림 시각(`alarm_time`, 기본 17:50)에 요약 파일을 만들고 알림을 띄워요. 작업 중인 클립보드를 덮어쓰지 않으려고 이때는 복사하지 않고, **알림을 클릭하면** 복사해요.
- 알림 이후 30분 자리 비움 또는 화면 잠금이 처음 생기면 요약을 한 번 더 만들어 파일을 최종본으로 덮어써요(하루 한 번, 클립보드는 그대로).
- 업무일 경계(`day_starts_at`, 기본 04:00)를 넘으면 전날 요약을 마지막으로 다시 만든 뒤 전날 원본을 지워요.

## 요약 형식

Obsidian 일지에 맞춰 목록은 `-`, 구분은 `:` 로 만들어요.

```markdown
### 오늘의 브이로그 (09:02 ~ 18:11, 활동 7시간 12분)
- 코드: workflow-core (ApprService.java, ApprDao.java, appr-sql.xml) : 3시간 05분
- 서버: dev-was01 : 1시간 20분
- DB: dev-oracle : 40분
- 파일전송: dev-was01 : 12분
- AI: Claude : 35분
- 웹: Chrome : 28분
- 노트: work-vault : 15분
- 기타 : 17분

#### 흐름
- 09:00 ~ 10:30 : 코드 workflow-core, 서버 dev-was01
- 10:30 ~ 11:40 : 코드 workflow-core
- 13:00 ~ 14:00 : DB dev-oracle
- 14:00 ~ 17:40 : 코드 workflow-core
```

- 활동은 누적 시간이 많은 순서예요. 5분 미만 활동은 "기타"로 묶어요.
- 코드는 프로젝트 단위로 합치고, 오래 본 파일 상위 3개를 괄호로 붙여요.
- 흐름은 10분 블록 단위로 주 활동을 보여 주고, 같은 내용이 이어지면 합쳐요. 자리 비움만 있는 블록은 빼요.

## 내 데이터 (PC마다 따로)

`%LOCALAPPDATA%\gohome-vlog\` 에 저장돼요. 로밍 프로필 서버로 동기화되지 않도록 Roaming이 아닌 Local을 써요. 저장소에는 안 올라가요.

| 파일 | 내용 |
|---|---|
| `raw\2026-11-04.jsonl` | 원본 기록 (업무일별, 추가 쓰기만 함) |
| `raw\current.json` | 진행 중인 구간. 강제 종료돼도 다음 실행 때 확정해요. |
| `summary\2026-11-04.md` | 일일 요약 |
| `rules.json` | 창 제목 해석 규칙. 직접 편집해요. 없으면 기본값을 복사해 줘요. |
| `config.json` | 설정. 없으면 기본값을 복사해 줘요. |

### 보존 규칙

- **원본**: 업무일이 지나면 요약을 만든 뒤 삭제해요. 앱을 시작할 때 지난 업무일 원본이 남아 있어도(재부팅, 강제 종료) 요약 후 삭제해요.
- **요약**: `summary_keep_days`(기본 7일)가 지나면 삭제해요.
- 제외 대상(아래 `exclude_*`)은 제목 없이 "제외됨"으로 시간만 집계해요.

## 설정 바꾸기 (`config.json`)

바꾼 뒤에는 앱을 다시 실행해 주세요. JSON이 깨져 있으면 기본값으로 동작하고 트레이로 알려요(파일은 절대 덮어쓰지 않아요).

| 항목 | 기본값 | 설명 |
|---|---|---|
| `poll_seconds` | `5` | 활성 창을 확인하는 간격(초) |
| `idle_minutes` | `5` | 마지막 입력 후 이 시간이 지나면 자리 비움. 시작 시각은 마지막 입력 시각으로 소급해요. |
| `day_starts_at` | `"04:00"` | 업무일이 바뀌는 시각. 03:59까지는 전날로 쳐요. |
| `alarm_time` | `"17:50"` | 퇴근 알림 시각 |
| `leave_idle_minutes` | `30` | 알림 이후 이 시간 자리 비우면 퇴근으로 보고 최종본 생성 |
| `min_minutes_for_item` | `5` | 이보다 짧은 활동은 "기타"로 묶음 |
| `timeline_block_minutes` | `10` | 흐름 블록 길이(분) |
| `code_top_files` | `3` | 코드 활동에 붙이는 파일 개수 |
| `summary_keep_days` | `7` | 요약 파일 보관 일수 |
| `exclude_processes` | `["KeePassXC.exe", "1Password.exe"]` | 이 프로세스는 제목 없이 "제외됨"으로만 기록 |
| `exclude_title_patterns` | `["(?i)inprivate", "(?i)private browsing"]` | 제목이 이 정규식에 맞으면 제외 |
| `mask_title_patterns` | `[]` | 제목에서 이 정규식에 맞는 부분을 저장 전에 `***` 로 바꿈 (예: 고객사 이름) |

## 규칙 추가 방법 (`rules.json`)

프로그램 창 제목을 `분류: 대상` 으로 바꾸는 규칙이에요. 목록에서 **위에서부터 첫 번째로 맞는 규칙**만 적용하니까, 구체적인 규칙을 위에 두세요.

| 키 | 설명 |
|---|---|
| `process` | 프로세스 이름 (예: `putty.exe`) |
| `category` | 요약에 찍힐 분류 (예: `서버`) |
| `patterns` | 제목에 적용할 정규식 목록. 순서대로 시도해 처음 맞는 것의 `target` 그룹을 대상으로 써요. 하나도 안 맞으면 프로그램 이름이 대상이 돼요. |
| `app_only` | `true` 면 제목을 보지 않고 앱 이름만 써요 (Claude, Chrome 등) |

- 코드 분류는 `target` 대신 `project`, `file` 이름 그룹을 써요. 요약에서는 프로젝트로 합치고 파일 상위 N개를 붙여요.
- 제목 구분자는 ` - `, en dash(–), em dash(—) 를 모두 알아봐요. VS Code, Kiro 제목 앞의 수정 표시(`●`)는 알아서 지우고 해석해요.
- 어떤 규칙에도 안 맞는 프로그램은 `기타: 프로세스이름` 으로 기록돼요.

예시: 터미널 프로그램 `mytermapp.exe` 의 제목이 `admin@dev-was01 - MyTerm` 이면 호스트 이름이 대상이 되게 하기.

```json
{
  "process": "mytermapp.exe",
  "category": "서버",
  "patterns": ["@(?P<target>[\w.-]+)", "^(?P<target>.+?) - MyTerm$"]
}
```

JSON 안에서 백슬래시는 `\` 처럼 두 번 써야 해요. 저장한 다음 트레이 메뉴 **규칙 다시 읽기**.

## 개발자용

### 테스트

```bash
pytest
```

- `tests/fixtures/` 에 가상의 하루 기록과 정답 요약, 프로그램별 가상 창 제목이 있어요.
- `tests/local/` 에는 실제 기록으로 검증한 파일을 모아 둘 수 있어요(Git 제외).

### 구조

```
gohome-vlog/
├─ gohome_vlog.pyw        진입점
├─ app/
│  ├─ main.py             트레이, 단일 실행, 메뉴, 알림, 스케줄
│  ├─ win32.py            ctypes 래퍼 (쓰는 API만)
│  ├─ collector.py        폴링, 자리 비움, 잠금/절전, 일시 정지
│  ├─ store.py            jsonl, current.json, 보존/삭제
│  ├─ rules.py            제목 해석, 제외, 마스킹
│  └─ summary.py          집계, 흐름, markdown (UI 없음)
├─ defaults/              기본 rules.json, config.json
└─ tests/
```

## 성능

느린 PC에서도 티 나지 않게 만들었어요. 직접 재 본 값(Windows 11, Python 3.15, PySide6 6.12):

- **CPU**: 1분에 약 16ms (코어 하나 기준 0.03% 정도)
- **폴링 1회**: 약 4µs. 같은 창이면 프로세스 이름을 다시 조회하지 않아요(`OpenProcess` 반복 없음, 보안 프로그램 감시 부담도 줄어요).
- **메모리**: 약 60MB. 대부분 트레이와 알림에 쓰는 Qt 라이브러리 몫이에요.
- **디스크**: 창이 바뀔 때 한 줄 추가, 진행 중 구간은 30초마다 작은 파일 하나 덮어쓰기(fsync 없음).
- 타이머는 정밀도를 낮춰(`VeryCoarseTimer`) Windows가 다른 타이머와 묶어서 깨울 수 있게 했어요.
- 잠금, 절전 중에는 창 정보를 읽지 않아요.

## 알려진 한계

- Windows **집중 지원(방해 금지)** 모드에서는 퇴근 알림이 숨겨질 수 있어요. 요약 파일은 정상적으로 만들어지니까 트레이 메뉴 **요약 폴더 열기** 나 **오늘 요약 복사** 로 가져오세요.
- 기본 규칙의 프로세스 이름과 제목 형식은 일반적인 기본값 기준이라 **실제 창 제목과 다를 수 있어요.** 처음 며칠 써 보고 `rules.json` 을 보정해 주세요.
- 5초보다 짧게 오간 창은 기록에서 빠질 수 있어요.
- 관리자 권한 창처럼 제목이나 프로세스를 읽을 수 없으면 `(알 수 없음)` 으로 기록돼요.
- 회사 PC에서 쓰기 전에 사내 보안 정책상 문제가 없는지 직접 확인해 주세요.

자세한 결정 이유와 엣지 케이스는 [SPEC.md](SPEC.md)에 있어요.
