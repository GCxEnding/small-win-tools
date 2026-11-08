# small-win-tools 작업 안내 (공통 문서)

이 저장소에서 작업하는 세션이 먼저 읽는 문서입니다. 도구별 내용은 각 폴더의 `SPEC.md`, `README.md`에 있고, 여기에는 **도구 사이에 겹치는 것**과 **공통 패턴**만 둡니다.
새 도구를 넣거나 단축키, 뮤텍스, 데이터 폴더를 정하면 4번 등록부를 함께 고칩니다.

## 1. 저장소 개요
- 공개 저장소 `GCxEnding/small-win-tools`. Windows 10/11용 작은 상주 도구 모음.
- 도구 하나 = 최상위 폴더 하나. 각 도구는 독립 실행되며 서로 import하지 않습니다.
- 사용 환경: 회사 PC와 개인 PC(둘 다 Windows). 같은 코드를 각 PC에 clone해서 쓰고, 개인 데이터는 PC마다 따로 둡니다.

## 2. 작업 흐름
1. 새 도구나 큰 기능은 인터뷰로 요구사항을 정리해 `<도구>/SPEC.md`를 먼저 씁니다. 인터뷰 세션에서는 코드를 쓰지 않습니다.
2. 구현은 **새 세션**에서 `SPEC.md`를 읽고 시작합니다. SPEC의 "검증 계획"을 모두 통과해야 완료입니다.
3. SPEC의 "사람 검토 체크포인트"에서는 멈추고 사용자 확인을 받습니다.
4. 완료 후 루트 `README.md` 도구 표에 한 줄 추가, 이 문서 4번 등록부 갱신.

## 3. 표준 폴더 구조
```
<도구-이름>/
├─ SPEC.md                ← 명세 (인터뷰 결과)
├─ README.md              ← 설치, 실행, 시작 프로그램 등록, 사용법
├─ requirements.txt       ← PySide6>=6.6, pytest>=8 (그 외는 꼭 필요할 때만)
├─ .gitignore             ← 도구 전용 제외 항목 (tests/local/ 등)
├─ <도구_이름>.pyw         ← 진입점. sys.path에 자기 폴더를 넣고 app.main.main()만 호출
├─ app/
│  ├─ __init__.py
│  ├─ main.py             ← 트레이, 단일 실행 뮤텍스, 메뉴, 알림, 앱 수명
│  ├─ store.py            ← 설정/상태 읽기와 원자적 저장
│  └─ ...                 ← 로직 모듈은 UI(PySide6)에 의존하지 않게 나눠 테스트 가능하게
├─ defaults/ 또는 data/   ← 동봉 기본값, 데이터 (선택)
└─ tests/
   ├─ conftest.py         ← sys.path에 도구 폴더 추가 (아래 그대로)
   ├─ fixtures/           ← 합성 데이터만
   ├─ local/              ← 실제 개인 데이터 샘플. 반드시 .gitignore
   └─ test_*.py
```
- `tests/conftest.py` 내용:
  ```python
  import sys
  from pathlib import Path

  sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
  ```
- 테스트는 도구 폴더에서 `pytest`로 실행합니다(루트에서 한꺼번에 돌리지 않음. 도구마다 `app` 패키지 이름이 같기 때문).

## 4. 공유 자원 등록부 (겹치면 안 되는 것)
새 값을 정하기 전에 이 표에서 충돌을 확인하고, 정한 뒤 바로 추가합니다.

### 전역 단축키
| 단축키 | 도구 | 용도 | 비고 |
|---|---|---|---|
| `Win+.` | emoji-searcher | 검색 창 | Windows 기본 이모지 패널을 레지스트리로 끄고 사용 |
| `Ctrl+Alt+E` | emoji-searcher | 보조 단축키 | `Win+.` 등록 실패 시 |
| `Ctrl+Alt+H` | thought-searcher | 검색 창 | |
| (없음) | gohome-vlog | | 단축키 쓰지 않음 |

- 모든 단축키는 각 도구 `config.json`에서 바꿀 수 있게 합니다. 여기 적는 것은 **기본값**입니다.
- 피할 조합: Windows 예약(`Win+V`, `Win+;`, `Win+Shift+S` 등), `Ctrl+Alt+Del`, IME 전환에 쓰이는 `Ctrl+Space`/`Shift+Space`.
- 사용자 PC 레지스트리 `DisabledHotkeys`에는 현재 `V`(Win+V 끔)가 들어 있다고 가정합니다. 이 값을 건드리는 스크립트는 기존 글자를 보존해야 합니다(emoji-searcher `registry/` 참고).

### 단일 실행 뮤텍스
형식: `Local\GCxEnding.small-win-tools.<폴더 이름>`
| 뮤텍스 | 도구 |
|---|---|
| `Local\GCxEnding.small-win-tools.emoji-searcher` | emoji-searcher |
| `Local\GCxEnding.small-win-tools.gohome-vlog` | gohome-vlog |
| `Local\GCxEnding.small-win-tools.thought-searcher` | thought-searcher |

### 개인 데이터 위치
| 도구 | 위치 | 내용 |
|---|---|---|
| emoji-searcher | `%APPDATA%\emoji-searcher\` | config.json, user_tags.json, usage.json |
| gohome-vlog | `%LOCALAPPDATA%\gohome-vlog\` | 원본 jsonl, 요약, 설정 (PC 밖으로 나가면 안 되는 기록이라 Local) |
| thought-searcher | `%APPDATA%\thought-searcher\`, `%LOCALAPPDATA%\thought-searcher\` | 설정/상태는 APPDATA, 색인/원본 복사/로그는 LOCALAPPDATA |

- 기준: 작은 설정과 상태는 `%APPDATA%\<폴더 이름>\`, 크거나 다시 만들 수 있는 것(캐시, 색인, 로그)과 PC 밖으로 나가면 안 되는 기록은 `%LOCALAPPDATA%\<폴더 이름>\`.
- 저장소 안에는 개인 데이터를 절대 두지 않습니다. 실제 샘플은 `tests/local/`이나 도구 `.gitignore`에 넣은 폴더에만.

### 트레이 표시
| 도구 | 표시 이름(`APP_NAME`) | 아이콘 |
|---|---|---|
| emoji-searcher | `emoji-searcher` | 🔍 |
| gohome-vlog | `gohome` | 🏠 (일시 정지 시 변형) |
| thought-searcher | `생각 검색기` | 🧠 (보관 폴더 없으면 ⚠ 겹침) |

### 저장소 밖에 손대는 것
| 도구 | 대상 | 되돌리는 방법 |
|---|---|---|
| emoji-searcher | `HKCU\...\Explorer\Advanced\DisabledHotkeys`에 `¾` 추가 | `registry/restore-win-period.cmd` |

## 5. 공통 구현 패턴
기존 도구에서 이미 쓰고 있는 방식입니다. 특별한 이유가 없으면 따릅니다.

- **기술 스택**: Python 3.10 이상, PySide6(트레이, 창, 알림), `ctypes`로 Win32 직접 호출. 외부 의존성은 PySide6, pytest만.
- **진입점**: `<도구_이름>.pyw` (pythonw로 콘솔 없이 실행). 얇게 유지.
- **트레이 상주**: 시작 시 창 없이 `QSystemTrayIcon`. 아이콘은 이모지를 `QPainter`로 그려 여러 크기(16~64)로 만듭니다(이미지 파일 동봉 안 함). `emoji-searcher/app/main.py`의 `make_icon` 참고.
- **단일 실행**: `CreateMutexW` + `ERROR_ALREADY_EXISTS(183)`이면 즉시 종료.
- **알림**: `QSystemTrayIcon.showMessage`. 클릭 동작이 필요하면 `messageClicked`. 클립보드는 사용자 동작(클릭, 키 입력) 없이 덮어쓰지 않습니다.
- **전역 단축키**: `RegisterHotKey` + `QAbstractNativeEventFilter`. 실패하면 보조 키, 그것도 실패하면 트레이 알림 후 트레이 메뉴로만 사용.
- **원자적 저장**: 같은 폴더에 임시 파일로 쓰고 `fsync` 후 `os.replace`. UTF-8, BOM 없음, LF. (`emoji-searcher/app/store.py`의 `atomic_write_json`, `gohome-vlog/app/store.py`의 `atomic_write_text`)
- **설정 파일 처리**
  - 없으면 기본값으로 만들어 둡니다.
  - JSON이 깨졌으면 기본값으로 동작하고 트레이 경고. **사용자가 편집하는 파일은 덮어쓰지 않습니다.**
  - 앱이 관리하는 상태 파일이 깨졌으면 `.bak`으로 이름을 바꿔 보관하고 새로 시작.
- **네트워크**: 실행 중 네트워크 접근 없음이 기본. 브라우저로 URL 열기만 예외.
- **금지 API 검사 테스트**: 도구가 쓰면 안 되는 API나 모듈이 있으면 소스 전체를 정규식으로 검사하는 테스트를 둡니다. 금지어는 문자열 조각을 합쳐 만들어 테스트 파일 자신이 걸리지 않게 합니다(`gohome-vlog/tests/test_forbidden_api.py`).
- **UI와 로직 분리**: 검색, 요약, 변환 같은 로직은 PySide6 없이 함수로 호출할 수 있게 만들어 pytest로 검증합니다. 정답 샘플(골든 마스터)은 `tests/fixtures/` 또는 `tests/*.json`.

### 도구 사이에 복사해 쓰는 코드
도구끼리 import하지 않으므로 공통 코드는 복사합니다. 원본을 고치면 복사본도 같이 고칩니다.
| 원본 | 복사본 | 상태 |
|---|---|---|
| `emoji-searcher/app/hotkey.py` | `thought-searcher/app/hotkey.py` | 동일 |

## 6. 문서와 커밋 규칙
- 사용자와의 대화, 문서는 한국어 존댓말.
- 문서와 메시지에 em dash(U+2014) 기호를 쓰지 않습니다. `-`나 `:`를 씁니다.
- 커밋 메시지는 한글. 형식: `<도구 이름>: <무엇을 했는지>` (예: `gohome-vlog: 흐름 블록 10분으로 변경, 상주 부하 줄이기`). 저장소 전체 변경은 도구 이름 없이.
- 수정 결과를 보여 줄 때는 바뀐 부분만.
- 커밋, 푸시는 사용자가 요청할 때만.
- 공개 저장소이므로 커밋 전에 개인 데이터(실제 대화, 로그, 서버 이름, 회사 정보)가 섞이지 않았는지 `git status`로 확인합니다.
