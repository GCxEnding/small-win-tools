# gohome-vlog 명세

> 표시 이름: gohome (트레이, 알림에 표시)
> 저장소: `GCxEnding/small-win-tools` (공개)
> 위치: `small-win-tools/gohome-vlog/`

## 1. 개요
- 목적: 하루 동안 어떤 프로그램, 어떤 프로젝트, 어떤 서버에서 일했는지 활성 창 기준으로 자동 기록하고, 퇴근 무렵 Obsidian 일지에 붙여 넣을 요약을 만들어 준다. 일지와 주간보고를 쓸 때 "오늘 뭐 했더라"를 떠올리는 시간을 줄여 빨리 보고하고 퇴근하는 것이 목표다.
- 사용자: CG 본인. 회사 PC(DLP 설치, 항상 켜 둠)와 집 PC(Windows)에서 각각 사용. 공개 레포이므로 다른 사람도 규칙 파일만 고쳐 쓸 수 있게 한다.
- 원칙: **입력 내용은 절대 수집하지 않는다.** 활성 창의 프로세스명, 창 제목, 시각만 기록한다. 데이터는 로컬에만 두고 원본은 매일 지운다.

## 2. 범위
### 포함
- 트레이 상주, 5초 간격 활성 창 기록
- 자리 비움, 화면 잠금, 절전 구간 제외
- 프로그램별 제목 해석 규칙 (`rules.json`, 정규식)
- 퇴근 알림(기본 17:50)과 일일 요약 생성, 퇴근 감지 시 최종 요약 재생성
- 요약 클립보드 복사 + 파일 저장 (Obsidian 일지 형식)
- 제외 목록, 제목 마스킹
- 일시 정지, 오늘 기록 삭제
- 원본 일 단위 자동 삭제, 요약 7일 보관

### 제외 (Out of scope)
- 키보드, 마우스 입력 내용이나 횟수 수집 (훅, Raw Input 등 모두 금지)
- 스크린샷, 창 내용 캡처
- 브라우저 URL 수집
- 네트워크 전송, 동기화, AI 요약 호출
- Obsidian 일지 파일 직접 수정
- 회사/집 PC 기록 병합
- 그래프, 대시보드 화면
- 업무 시간대 제한 (idle로만 거름)

## 3. 기능 요구사항
1. **수집**
   - `gohome_vlog.pyw` 실행 시 트레이 아이콘으로 상주한다.
   - 5초마다 활성 창의 `시각, 프로세스명, 창 제목`을 읽는다. 직전과 같은 창이고 제목도 같으면 지속 시간만 늘리고, 다르면 새 구간을 시작한다.
   - 자리 비움: `GetLastInputInfo` 기준 마지막 입력 후 5분이 지나면 idle 구간. idle 판정 시각은 "마지막 입력 시각"으로 소급한다(5분이 통째로 활동으로 잡히지 않게).
   - 화면 잠금/해제, 절전/복귀 이벤트를 받아 해당 구간을 idle로 처리한다.
2. **해석 (활동 키 만들기)**
   - 프로세스명과 창 제목을 `분류: 대상` 형태의 활동 키로 바꾼다.
   - 기본 규칙 (초기값, 실제 창 제목을 보고 보정한다):

     | 프로그램 | 프로세스 | 분류 | 추출 대상 |
     |---|---|---|---|
     | IntelliJ IDEA | `idea64.exe` | 코드 | 프로젝트, 파일 |
     | VS Code | `Code.exe` | 코드 | 폴더(프로젝트), 파일 |
     | Kiro | `Kiro.exe` | 코드 | 폴더(프로젝트), 파일 |
     | Tabby | `Tabby.exe` | 서버 | `user@host`의 host 또는 세션/프로필 이름 |
     | PuTTY | `putty.exe` | 서버 | `user@host`의 host 또는 세션 이름 |
     | WinSCP | `WinSCP.exe` | 파일전송 | 세션 이름 |
     | DBeaver | `dbeaver.exe` | DB | 연결 이름 |
     | Obsidian | `Obsidian.exe` | 노트 | 보관함 이름 |
     | Claude | `claude.exe` | AI | 앱 이름만 (`Claude`) |
     | Chrome | `chrome.exe` | 웹 | 앱 이름만 (`Chrome`) |
     | 그 외 | | 기타 | 프로세스명 |

   - 제목 구분자는 ` - `, en dash(U+2013), em dash(U+2014)를 모두 인식한다. IntelliJ는 en dash를 쓴다.
   - VS Code/Kiro 제목 앞의 수정 표시(`●`)는 제거하고 해석한다.
   - 코드 분류는 요약에서 **프로젝트 단위로 합치고, 그 프로젝트에서 오래 본 파일 상위 3개**를 괄호로 붙인다.
   - Tabby/PuTTY는 `user@host` 패턴이 있으면 host를, 없으면 제목에서 프로그램 이름을 뺀 나머지(세션명)를 쓴다.
   - 규칙은 `rules.json`에서 위에서부터 첫 번째로 맞는 것을 적용한다. 사용자가 순서대로 추가, 수정할 수 있다.
3. **요약 형식**
   - Obsidian 일지와 맞춘다. 목록은 `-`, 구분은 `:`. '—' 기호는 쓰지 않는다.
   - 구성: 제목 줄(시작~끝 시각, 활동 합계), 활동별 누적 시간(많은 순), 시간대 흐름.
   - 5분 미만 활동은 "기타"로 묶는다.
   - 흐름은 10분 블록으로 나눠 각 블록의 주 활동(가장 오래 쓴 것, 2위가 1/3 이상이면 함께)을 표시하고, 같은 내용이 이어지는 블록은 합친다. idle만 있는 블록은 생략한다.
   - 예시:
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
4. **요약 시점**
   - 수동: 트레이 `오늘 요약 복사` → 지금까지의 요약을 생성, 파일 저장 + 클립보드 복사.
   - 퇴근 알림: `alarm_time`(기본 17:50)에 요약을 생성해 파일로 저장하고 알림을 띄운다. 알림 문구 예: "오늘 브이로그 다 찍었습니다. 이제 집에 가셔도 됩니다." 알림을 클릭하면 클립보드에 복사한다. (클립보드를 사용자 동의 없이 덮어쓰지 않기 위해, 알림 시점에는 복사하지 않는다)
   - 퇴근 감지: 알림 이후 30분 idle 또는 화면 잠금이 처음 발생하면 요약을 다시 생성해 파일을 최종본으로 덮어쓴다. 클립보드는 건드리지 않는다. 하루 한 번만.
   - 업무일 경계: `day_starts_at`(기본 04:00)을 지나면 전 업무일 요약을 마지막으로 다시 생성한 뒤 전날 원본을 삭제한다.
5. **트레이 메뉴**
   - `오늘 요약 복사`, `요약 폴더 열기`
   - `일시 정지` (30분 / 1시간 / 다시 시작할 때까지), `재개`
   - `오늘 기록 삭제` (확인 후 즉시)
   - `규칙 다시 읽기`, `종료`
   - 일시 정지 중에는 아이콘을 바꿔 표시한다. 일시 정지 구간은 idle과 같이 집계에서 빠진다.
6. **보존과 삭제**
   - 원본: 업무일 단위 jsonl. 업무일이 지나면 요약 생성 후 삭제.
   - 요약: `summary_keep_days`(기본 7일) 지난 파일 삭제.
   - 앱 시작 시에도 지난 업무일 원본이 남아 있으면 요약 후 삭제한다(재부팅, 강제 종료 대비).

## 4. 입력과 데이터
위치: `%LOCALAPPDATA%\gohome-vlog\` (로밍 프로필 서버 동기화를 피하려고 Roaming이 아닌 Local 사용)

- `raw\2026-11-04.jsonl`: 원본. 추가 쓰기만 함
  ```json
  {"start": "2026-11-04T09:02:10", "end": "2026-11-04T09:15:40", "proc": "idea64.exe", "title": "workflow-core – ApprService.java"}
  {"start": "2026-11-04T09:15:40", "end": "2026-11-04T09:21:00", "idle": "away"}
  {"start": "2026-11-04T12:00:00", "end": "2026-11-04T12:58:00", "idle": "lock"}
  ```
  - `idle` 값: `away`(입력 없음), `lock`(잠금), `sleep`(절전), `pause`(일시 정지)
  - 구간이 진행 중일 때는 30초마다 마지막 줄을 갱신하는 대신, 상태 파일(`raw\current.json`)에 진행 중 구간을 저장하고 구간이 끝나면 jsonl에 확정 추가한다.
- `summary\2026-11-04.md`: 요약
- `rules.json`: 해석 규칙 (없으면 `defaults/rules.json` 복사)
  ```json
  [
    {
      "process": "putty.exe",
      "category": "서버",
      "patterns": ["@(?P<target>[\\w.-]+)", "^(?P<target>.+?) - PuTTY$"]
    }
  ]
  ```
  - `patterns`는 순서대로 시도, 처음 맞는 `target` 그룹 사용. 하나도 안 맞으면 `target`은 프로그램 이름.
  - 코드 분류는 `project`, `file` 그룹을 쓴다.
  - `app_only: true`면 제목을 보지 않는다 (Claude, Chrome).
- `config.json`:
  ```json
  {
    "poll_seconds": 5,
    "idle_minutes": 5,
    "day_starts_at": "04:00",
    "alarm_time": "17:50",
    "leave_idle_minutes": 30,
    "min_minutes_for_item": 5,
    "timeline_block_minutes": 10,
    "code_top_files": 3,
    "summary_keep_days": 7,
    "exclude_processes": ["KeePassXC.exe", "1Password.exe"],
    "exclude_title_patterns": ["(?i)inprivate", "(?i)private browsing"],
    "mask_title_patterns": []
  }
  ```
- 제외: 걸리면 제목 없이 `{"proc": "...", "excluded": true}`로만 기록, 요약에서는 "제외됨"으로 시간만 집계.
- 마스킹: `mask_title_patterns`에 맞는 부분을 원본 저장 전에 `***`로 바꾼다 (예: 고객사명).

## 5. 엣지 케이스와 처리 규칙
| 상황 | 처리 |
|---|---|
| 자정 넘어 작업 | `day_starts_at` 기준으로 업무일 구분. 03:59까지는 전날 |
| 알림 시각에 이미 idle/잠금 상태 | 알림은 띄우고, 퇴근 감지는 즉시 충족된 것으로 보고 최종본 생성 |
| 알림 이후 야근 후 잠금 | 그 시점에 최종본 재생성 (하루 한 번). 이후 활동은 업무일 경계 재생성에서 반영 |
| idle 시작 시점 | 마지막 입력 시각으로 소급 |
| 절전 복귀 후 시계 점프 | 절전 시작 시각에 이전 구간을 닫고 `sleep` 구간 추가 |
| 관리자 권한 창 등 제목/프로세스 읽기 실패 | `(알 수 없음)`으로 기록, 멈추지 않음 |
| 활성 창 없음 (바탕화면, 작업 전환) | 직전 구간을 닫고 기록 안 함 |
| 같은 창에서 제목만 바뀜 (파일 전환) | 새 구간 |
| 5초 안에 오간 창 | 기록 누락 허용 |
| 강제 종료, 정전 | 확정된 jsonl은 유지, `current.json`의 진행 구간은 다음 실행 시 확정 처리. 깨진 줄은 무시 |
| `rules.json`, `config.json` 깨짐 | 기본값으로 동작, 트레이 경고. 파일은 덮어쓰지 않음 |
| 요약 대상 기록이 없음 | "기록된 활동이 없습니다." 한 줄 요약 |
| 코드 프로젝트의 파일이 3개 미만 | 있는 만큼만 표시 |
| 제목에서 프로젝트를 못 찾은 IDE 창 | `코드: (프로젝트 없음)`으로 묶음 |
| 중복 실행 | 이름 있는 뮤텍스로 두 번째 실행 즉시 종료 |
| 클립보드가 다른 프로그램에 잠김 | 짧게 재시도 후 실패 알림, 파일은 정상 저장 |

## 6. 제약
- 실행 환경: Windows 10/11. 회사 PC는 DLP 설치, 항상 켜져 있음.
- 사용 API: `GetForegroundWindow`, `GetWindowTextW`, `GetWindowThreadProcessId`, `OpenProcess`(`PROCESS_QUERY_LIMITED_INFORMATION`), `QueryFullProcessImageNameW`, `GetLastInputInfo`, `WTSRegisterSessionNotification`, 절전 알림(`WM_POWERBROADCAST`)
- **사용 금지 API**: `SetWindowsHookEx`, `RegisterRawInputDevices`, `GetRawInputData`, `GetAsyncKeyState`/`GetKeyState` 반복 조회, 입력을 가로채거나 읽는 모든 방식
- 기술 스택: Python 3.10 이상, PySide6(트레이, 알림), `ctypes`(Win32). 외부 의존성은 PySide6, pytest만.
- 성능: 폴링 1회가 체감 부하 없이(수 ms 이내) 끝날 것. 상주 CPU 사용률 거의 0.
- 보안: 네트워크 접근 없음. 공개 레포이므로 예시와 테스트 데이터에 실제 회사, 고객사, 서버 이름을 쓰지 않는다.

## 7. 관련 파일과 인터페이스
```
small-win-tools/
├─ README.md                     ← 도구 목록에 gohome-vlog 한 줄 추가
└─ gohome-vlog/
   ├─ SPEC.md
   ├─ README.md                  ← 수집 항목 설명, 설치, 시작 프로그램 등록, 규칙 추가 방법
   ├─ .gitignore                 ← tests/local/ 제외
   ├─ requirements.txt
   ├─ gohome_vlog.pyw            ← 진입점
   ├─ app/
   │  ├─ main.py                 ← 트레이, 뮤텍스, 메뉴, 알림, 스케줄
   │  ├─ win32.py                ← ctypes 래퍼 (사용 API만)
   │  ├─ collector.py            ← 폴링, idle, 잠금/절전, 일시 정지
   │  ├─ store.py                ← jsonl, current.json, 보존/삭제
   │  ├─ rules.py                ← 해석, 제외, 마스킹
   │  └─ summary.py              ← 집계, 타임라인, markdown (UI 의존 없음)
   ├─ defaults/
   │  ├─ rules.json
   │  └─ config.json
   └─ tests/
      ├─ test_rules.py
      ├─ test_summary.py
      ├─ test_store.py
      ├─ test_forbidden_api.py
      ├─ fixtures/
      │  ├─ sample_day.jsonl         ← 가상의 하루 (커밋)
      │  ├─ sample_day.expected.md   ← 위 기록의 정답 요약 (커밋)
      │  └─ sample_titles.json       ← 프로그램별 가상 창 제목과 기대 활동 키
      └─ local/                      ← 실제 기록 검증용, Git 제외
```
- `summary.build_summary(records, config, now) -> str`: 기록만 넣으면 화면 없이 테스트 가능.
- `rules.resolve(proc, title, rules) -> ActivityKey`: 해석 단독 테스트 가능.
- `collector`의 시계와 Win32 호출은 주입 가능하게 해 테스트에서 가짜로 교체.

## 8. 결정 사항과 근거
| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 활성 창 제목만 수집 | 회사 DLP 환경에서 입력 가로채기는 위험 | 키 입력 카운트, 훅 |
| idle은 `GetLastInputInfo` | 마지막 입력 시각만 반환, 내용 무관 | 입력 훅 |
| 시간대 제한 없음 | idle로 충분히 걸러지고 야근/원격 작업도 남음 | 업무 시간대만 기록 |
| `%LOCALAPPDATA%`, 원본 매일 삭제 | 민감한 제목이 남거나 동기화되지 않게 | `%APPDATA%`, 장기 보관 |
| 클립보드 + 파일 | 붙일 위치를 사용자가 고르고 보관함 경로 설정 불필요 | 일지 직접 추가, 스킬 입력 전용 |
| 17:50 알림 + 퇴근 감지 재생성 | PC가 항상 켜져 있어 알림을 놓칠 일이 적고, 야근분도 반영 | 수동만, 알림만 |
| 알림 시 클립보드 자동 복사 안 함 | 작업 중 클립보드를 덮어쓰지 않게 | 알림과 동시에 복사 |
| 코드: 프로젝트 + 파일 상위 3개 | 일지에 쓰기 좋은 밀도 | 프로젝트만, 파일 전부 |
| Claude, Chrome은 앱 이름만 | 제목이 길고 일지에 의미가 적음 | 제목 그대로, 업무 사이트만 |
| 규칙 파일(정규식, 위에서부터) | 프로그램마다 제목 형식이 다르고 다른 사용자도 확장 | 하드코딩 |
| 가상 기록 커밋, 실제 기록 로컬 | 공개 레포에 업무 정보가 올라가지 않게 | 실제 기록 마스킹 후 커밋 |
| small-win-tools 폴더 | 소형 Windows 유틸 일원화 | 독립 레포 |

## 9. 가정 (사용자가 위임한 판단)
- 기본 해석 규칙의 프로세스명과 제목 형식은 일반적인 기본값 기준이다. 실제 창 제목과 다를 수 있어 첫 사용 후 보정한다.
- Obsidian은 보관함 이름까지만 쓴다 (노트 제목은 일지 날짜 노트가 대부분이라 의미가 적음).
- WinSCP, DBeaver는 세션/연결 이름까지만 쓴다.
- 폴링 5초, idle 5분, 업무일 시작 04:00, 요약 보관 7일, 퇴근 감지 30분.
- 알림은 PySide6 트레이 알림(`QSystemTrayIcon.showMessage`)을 쓴다. 집중 지원(방해 금지) 모드에서는 알림이 숨겨질 수 있으나 요약 파일은 정상 생성된다.
- 회사 PC에서 이 도구를 쓰는 것이 사내 정책상 문제없는지는 사용자가 확인한다.

## 10. 미결 사항
- 실제 창 제목 샘플: 특히 Tabby(세션명/`user@host` 혼재), DBeaver, WinSCP. 첫 사용 후 `tests/local/`에 모아 규칙을 보정한다.
- 요약 형식의 세부(흐름 블록 길이, "기타" 기준)는 실제 하루 요약을 본 뒤 조정할 수 있다.

## 11. 검증 계획
- **정답 샘플**
  - 가상(커밋): `sample_day.jsonl` + `sample_day.expected.md`. Claude가 작성. 포함 상황: IntelliJ 두 프로젝트, Kiro, Tabby(`user@host`와 세션명 각각), PuTTY, WinSCP, DBeaver, Obsidian, Claude, Chrome, 미등록 프로그램, 점심 잠금, 5분 이상 idle, 제외 프로그램, 일시 정지, 알림 이후 야근, 자정 넘김 작업
  - 가상 창 제목(커밋): `sample_titles.json`, 프로그램별 2~3개와 기대 활동 키
  - 실제(로컬): 구현 후 집 PC, 회사 PC에서 각각 하루 사용한 요약. CG가 "일지에 그대로 붙여도 되는가"로 판단
- **자동 테스트 (pytest)**
  - `test_rules.py`: `sample_titles.json` 전체 일치, 구분자 3종, 수정 표시 제거, 첫 일치 규칙 우선, 제외/마스킹, 규칙 미일치 시 프로세스명
  - `test_summary.py`: 정답 요약과 일치, 5분 미만 "기타", 10분 블록 병합, idle/일시 정지 제외 합계, 코드 파일 상위 3개, 빈 기록, '—' 미포함
  - `test_store.py`: 깨진 줄 무시, `current.json` 복구, 업무일 경계(03:59/04:00), 지난 원본 요약 후 삭제, 요약 7일 보관
  - `test_forbidden_api.py`: 소스 전체에서 금지 API 이름이 나오지 않음
- **End-to-end 검증 (마지막에 실행해 통과해야 완료)**
  1. `pip install -r requirements.txt` 후 `pytest` 전체 통과
  2. 실행 → 트레이 아이콘, 30분 평소처럼 작업 → `오늘 요약 복사` → Obsidian에 붙여 형식 확인
  3. 5분 이상 자리 비움 → 활동 시간에서 빠짐, idle 시작이 마지막 입력 시각
  4. Win+L 잠금/해제 → `lock` 구간
  5. 일시 정지 중 작업 → 기록 안 됨, 아이콘 변경
  6. `alarm_time`을 2분 뒤로 설정 → 알림 표시, 요약 파일 생성, 클립보드 변화 없음, 알림 클릭 시 복사
  7. 알림 후 잠금 → 요약 파일이 최종본으로 갱신
  8. `day_starts_at`을 현재 시각 직후로 설정 → 전날 요약 생성, 원본 삭제
  9. `오늘 기록 삭제` → 원본 삭제 확인
  10. 회사 PC에서 하루 사용 → DLP 경고/차단 없음, 실제 요약을 CG가 확인

## 12. 사람 검토 체크포인트
1. `sample_day.expected.md`(정답 요약) 검토: 자동 테스트 작성 전
2. 트레이 첫 실행, 알림 문구와 아이콘 확인
3. 집 PC 하루 사용 후 실제 요약 확인, 창 제목 샘플 수집과 `rules.json` 보정
4. 회사 PC 적용, DLP 반응 확인
5. 회사 PC 하루 요약 확인 후 완료 판정
