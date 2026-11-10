# 인수인계: 설정 창 디자인 개편과 테마 (2026-11-10 밤)

> 이 절이 최신입니다. 아래 "설정 창과 시작 안내" 절은 그 전 작업 기록이고 구조 설명은 여전히 유효합니다.
> **커밋은 하지 않았습니다**(CLAUDE.md 6번).

## A. 한 일

CG가 준 시안(라이트/다크 고급 탭 그림)대로 설정 창을 바꾸고 테마를 넣었습니다. UI 프레임워크(PySide6)는 그대로이고 화면 구성과 스타일만 바꿨습니다.

| 파일 | 내용 |
|---|---|
| `app/theme.py` (새) | **색 값은 여기에만** 있습니다. `BASE`(라이트/다크 기본색), `ACCENT`(강조색 4종 x 모드), `BRAND`/`BADGE_STYLE`(출처 배지), `make(mode, accent, dark=None)`/`from_config(cfg)` → `Theme`, `palette()`(앱 전체 QPalette), `dialog_qss()`(설정 창, 시작 안내), `search_qss()`(검색 창), 단색 선 아이콘(`icon()`, SVG 문자열), 강조색 동그라미(`swatch()`), 제목 표시줄 색(`style_titlebar`, DWM) |
| `app/settings.py` | `THEME_MODES`/`THEME_MODE_LABEL`, `THEME_ACCENTS`/`THEME_ACCENT_LABEL`, `read_theme`, 칸 종류 `theme_mode`/`theme_accent` 검사. 가중치 이름 `반감기(일)` → `반감기`(단위는 칸 안에 붙음) |
| `app/store.py` | 새 키 `theme_mode`(기본 `system`), `theme_accent`(기본 `ink_blue`) |
| `app/settings_window.py` | 위 탭 → 왼쪽 사이드바(208px, `nav_buttons`) + `QStackedWidget`(`stack`). 화면 도우미 `_page`(제목, 설명) → `_section`(제목 + 옆 설명 + 오른쪽 링크, 섹션 간격 36px) → `_row`(왼쪽 이름 14px + 설명 12.5px / 오른쪽 칸, `stacked=True`면 위아래). 새 위젯 `NumEdit`(화살표 없는 숫자 칸 + 단위), `LinesEdit`(가림 정규식 여러 줄 칸), `Section`. 모드, 강조색 고르기(`_chips`)는 저장 전에 창에 먼저 칠함(`_preview_theme`). 색을 직접 쓰던 `setStyleSheet(color:...)`는 모두 `tone="error"` 속성(`set_tone`)으로 바꿈. 시작 안내도 같은 테마와 섹션/줄 구조 |
| `app/window.py` | `Theme` 클래스를 `theme.py`로 옮김(`from .theme import Theme`는 남김). `SearchWindow(theme)`, `set_theme(t)`. ⚙ 글자 → 선 아이콘. 배지 색은 `theme.badge_colors`. 요약 줄의 💬 → `요약:` |
| `app/main.py` | `qapp.setStyle("Fusion")`, 시작 때 `T.apply_app`, `apply_theme()`(저장 때 `theme_*`가 바뀌면, Windows 앱 모드가 바뀌면 `colorSchemeChanged`) |
| `tests/test_theme.py` (새), `tests/test_settings_window.py` | 시안 색 값 대조, 이름 표 일치, 스타일시트에 테마 밖 색이 없는지, 배지, 검색 창 `set_theme`. 창 테스트는 `tabs` → `nav_buttons`/`stack`/`current_tab()`/`select_tab()`, 정규식 칸, 숫자 칸 단위, 테마 미리보기와 저장, 시작 안내 테마 |
| `README.md` | 설정 창 표(탭 → 메뉴, 모양 항목), 테마 설명, ⚙ → 톱니바퀴 아이콘 |

## B. 정한 것

| 정한 것 | 이유 |
|---|---|
| 글자색은 본문/보조/플레이스홀더 세 단계. **오류와 경고만 빨강**(`error`: 라이트 `#C5221F`, 다크 `#F28B82`), 경고 앞 ⚠는 뺌 | CG 결정 (2026-11-10) |
| 출처 배지만 서비스 고유색: Claude `#D97757`, GPT `#74AA9C`. 같은 회사는 같은 색, **칠하는 방식으로 종류 구분**: 웹 채팅(claude.ai, ChatGPT) 꽉 채움, 코드 도구(Claude Code, Codex) 테두리만, claude.ai 프로젝트/메모리 옅은 바탕(24%), 노트/일지 무채색 | CG가 GPT, 클로드 고유색을 주고 Code/Codex 구분 방법을 물음. 제안안을 넣음. **CG가 실제 검색 창에서 아직 안 봄**. 바꾸려면 `theme.BADGE_STYLE`, `BRAND`만 고치면 됨 |
| GPT 배지 글자는 흰색이 아닌 `#10201C` | `#74AA9C` 위 흰 글자는 대비가 2.5:1로 작은 글자에 약함 |
| 체크박스, 라디오의 체크 표시는 본문색(강조색 아님) | 강조색은 저장 버튼, 링크, 초점 테두리에만 쓴다는 규칙 |
| 선택된 모드/강조색 단추는 사이드바 선택처럼 옅은 회색 + 굵게 | 같은 규칙 |
| `Fusion` 스타일을 앱 전체에 씀 | Windows 기본 스타일은 입력칸 테두리, 콤보 상자 등 스타일시트 일부를 무시함 |
| 콤보 화살표, 체크 표시는 색을 넣은 SVG를 `%TEMP%\thought-searcher-ui\`에 써서 `url()`로 씀 | 스타일시트로 indicator를 꾸미면 Qt 기본 그림이 사라져 그림 파일이 필요. Fusion 기본 체크박스는 다크에서 거의 안 보였음 |
| 반감기 칸은 소수점 없이(정수) 보여 줌 | 시안 `180 일`. 손으로 넣은 소수값(예: 90.5)은 창에서 반올림돼 보이지만 그 칸을 건드리지 않으면 저장 때 쓰지 않음 |
| 넓은 칸(노트 폴더 목록, 큐 출처 체크 5개, 쓰는 서비스, 강조색 4개, 가림 정규식, 폴더 열기 단추 3개)은 stacked(이름 아래) | 오른쪽 칸 폭에 안 들어가거나, 왼쪽 설명이 좁아져 줄바꿈 높이 계산이 깨짐(강조색 설명이 잘렸음) |
| 다크 제목 표시줄: `DWMWA_USE_IMMERSIVE_DARK_MODE` + Windows 11은 제목 표시줄 색을 배경색으로 | 시안의 제목 줄 색과 맞춤. Windows 10은 다크/라이트만 |

### 다음 AI가 알아 둘 함정
- **숫자 칸(`NumEdit`) 안의 `QSpinBox`에 스타일시트로 `border`, `padding`, `::up-button`을 주면 안쪽 편집칸이 1px로 줄어 숫자가 안 보입니다.** 테두리는 바깥 `QFrame#numBox`가 그리고 스핀은 `setFrame(False)`로 처리했습니다. 또 일반 `QLineEdit` 규칙이 스핀과 편집 가능 콤보의 안쪽 편집칸에도 걸리므로 `QFrame#numBox QLineEdit, QComboBox QLineEdit`에서 초기화합니다.
- 색을 새로 쓸 때는 `theme.py`의 `BASE`에 키를 더하고 `Theme`에 같은 이름의 필드를 더합니다. `test_stylesheets_use_only_theme_values`가 스타일시트 안의 `#rrggbb`가 테마 값인지 검사합니다.
- 설정 키를 더하는 순서는 아래 6번 그대로입니다. 칸은 `_row(sec, 이름, 칸, 설명, key)`로 넣습니다.

## C. 확인한 것
- offscreen으로 설정 창 4개 메뉴와 시작 안내 3단계를 라이트/다크로 그려 시안과 비교했습니다(숫자 칸, 콤보 화살표, 체크박스, 강조색 줄을 이 과정에서 고침).
- pytest(`test_perf.py` 제외): **330 passed, 12 failed**. 실패 12개는 모두 `test_settings.py`의 "기본값이 검사를 통과" 계열이고, 이 PC에 지금 `%USERPROFILE%\.codex`가 없어서 납니다. 커밋된 HEAD(888d9ef)에서도 똑같이 12개가 실패하는 것을 확인했습니다(이번 변경과 무관). `.codex`가 있는 PC에서는 통과해야 합니다.

### C-2. CG 확인 뒤 고친 것 (2026-11-11)
- CG가 실제 앱에서 보고 결과에 만족함.
- 서비스 순서를 회사별로: claude.ai, Claude Code, ChatGPT, Codex (`settings.SERVICES`, `SERVICE_LABEL`, `QUEUE_CHOICES`, `QUEUE_LABEL`, `store.DEFAULT_CONFIG["sources"]`). 쓰는 서비스, 큐 출처, 시작 안내가 모두 이 순서.
- 설정 창의 `QMessageBox`를 모두 `settings_window.ask()`/`tell()`(`Confirm` 대화 상자)로 바꿈. QMessageBox는 Windows 알림 소리를 내고 단추가 영어(Yes/No, Qt 번역 파일을 안 실어서)였음. 새 창은 테마를 따르고 아이콘이 없어 소리가 안 나며, 단추는 `저장/돌아가기`, `만들기/취소`, `닫기/계속 고치기`처럼 하는 일을 적음. 테스트는 `sw.ask`를 바꿔 끼움.
- 저장할 때 "CLI를 찾지 못했습니다" 경고를 없앰. Claude Code만 쓰거나 Codex만 쓰는 PC가 보통이고, CLI 상태 줄과 F2 실패 사유로 이미 보임.
- `settings.validate`: 경로 칸이 **기본값이면** 폴더가 없어도 통과(예: Codex를 안 쓰는 PC의 `%USERPROFILE%\.codex`). 이 때문에 이 PC에서 실패하던 `test_settings.py` 12개가 통과함. 직접 고른 경로는 그대로 검사.
- pytest(`test_perf.py` 제외): **345 passed** (C-3 뒤 351 passed).

### C-3. claude.ai 수집 제외 (2026-11-11, CG 요청: 개인 대화를 수집에서 빼기)

CG가 고른 안: **Tampermonkey 메뉴에서 빼기, claude.ai만, 기존 md도 지움.**

| 파일 | 내용 |
|---|---|
| `userscript/claude-sync.user.js` (0.2.0) | 메뉴 `이 대화 수집에서 빼기`, `이 프로젝트 수집에서 빼기`, `수집에서 뺀 목록 (되돌리기)`. GM 저장소 `exclude = {conversations: {uuid: {title, project}}, projects: {uuid: name}}`. 대화 목록을 훑을 때 뺀 대화, 뺀 프로젝트의 대화는 받지 않고 `seen`에만 적음. 뺀 프로젝트의 대화는 찾는 대로 `conversations`에 `project: <프로젝트 uuid>`로 더함. 프로젝트를 빼거나 되돌리면 `backfilled=false`로 전체 목록을 한 번 훑음. `_status.json`에 `exclude: {conversations: [{uuid,title,project}], projects: [{uuid,name}]}`를 같이 씀 (메뉴를 누르면 바로 씀) |
| `app/importers/claude_capture.py` | `Exclude`, `read_exclude(status)`(키가 없으면 None = 예전 스크립트), `capture_uuid(name)`. uuid는 `[0-9A-Za-z-]{8,64}`만 받음(파일 이름에 넣으므로) |
| `app/core.py` | `exclusions_pending()`(상태 파일 stat이 바뀌었는지, 2초 확인용), `capture_exclude`(상태 파일 → 없으면 `state["capture_exclude"]` 사본), `apply_exclusions()`: md(`claude-ai:<uuid>`, `claude-ai-project:<uuid>`)를 `Archive.find`로 찾아 지움, 수집 폴더/다운로드 폴더/원본 사본의 `claude-ai_<uuid>.json` 지움, `summaries.drop`, `queue_closed`에서 뺌, 색인 갱신. `import_captures`가 처음에 부르고, 뺀 대화의 새 수집 파일은 가져오지 않고 지움. zip(`claude-ai` 가져오기)은 `_drop_excluded`로 대화, 프로젝트 문서, 프로젝트 메모리 항목(`native_id = project:<uuid>`)을 뺌. `CaptureResult.removed` |
| `app/ask.py` | `SummaryStore.drop(ids)` |
| `app/main.py` | 2초 확인에 `exclusions_pending()` 더함 |
| `tests/test_exclude.py` (새) | 6개: 목록 읽기, 기존 흔적 지우기, 뺀 수집 파일 안 가져옴, 상태 파일이 없어도 목록 유지, zip에서 빼기(대화, 프로젝트 문서, 프로젝트 메모리), 되돌리면 다시 들어옴 |
| `README.md` | '개인 대화 빼기 (claude.ai)' 절 |

정한 것과 이유
- **내보내기 zip에는 대화마다 프로젝트 정보가 없음**(`tests/local/export`의 실제 zip에서 확인: 대화 키는 `account, computer_folders, created_at, name, summary, updated_at, uuid`뿐). 그래서 프로젝트를 빼도 앱은 대화 uuid로 거르고, 프로젝트에 속한 대화 uuid는 스크립트가 목록을 훑으며 모아 줌. 프로젝트 문서와 프로젝트 메모리는 프로젝트 uuid로 거름.
- 목록의 원본은 스크립트(GM 저장소). 앱의 `state["capture_exclude"]`는 상태 파일이 잠깐 없을 때 쓰는 사본. 되돌리면 앱은 아무것도 지우지 않고, 스크립트가 다시 받은 파일로 md가 다시 생김.
- 다운로드 폴더의 zip 파일 자체는 지우지 않음(내 대화만 든 파일이 아님). README에 적음.

확인 못 한 것 (**CG가 실제 claude.ai에서 확인 필요**)
- 대화 목록 API(`chat_conversations?limit=...`) 항목에 `project_uuid`가 오는지. 안 오더라도 본문을 받을 때 `project_uuid`로 다시 거르므로 새로 받는 대화는 빠지지만, **이미 받아 둔(바뀌지 않은) 프로젝트 대화는 목록에 project가 와야 찾아짐.** 안 오면 프로젝트 대화 목록 API를 따로 불러야 함.
- 대화 메타 API(`chat_conversations/<uuid>`, tree 없이)가 `name`, `project_uuid`를 주는지(메뉴에서 씀).
- 이 PC에는 수집 파일이 없어(`%LOCALAPPDATA%\thought-searcher\raw\claude-ai-capture` 비어 있음) 실제 응답으로 시험하지 못함. 스크립트는 `node --check`만 통과.

## D. 남은 일
0. **수집 제외 실제 확인** (C-3 '확인 못 한 것'): 스크립트 0.2.0을 Tampermonkey에 다시 붙여 넣고, 대화 하나와 프로젝트 하나를 빼 본 뒤 보관 폴더에서 md가 지워지는지, 개발자 도구 콘솔에 오류가 없는지.
1. **CG가 실제 트레이 앱을 재시작해 확인**: 설정 창 4개 메뉴, 라이트/다크/시스템 전환, 강조색 4종, 제목 표시줄 색, 검색 창 배지(위 B의 배지 구분안이 괜찮은지), 시작 안내(`THOUGHT_SEARCHER_APPDATA`, `THOUGHT_SEARCHER_LOCALAPPDATA`를 빈 폴더로 두고 실행).
2. 실제 Windows 화면(고해상도 배율 포함)에서 글자 크기와 줄 간격이 시안과 맞는지. 스타일시트 글자 크기는 pt(14px = 10.5pt, 12.5px ≈ 9.4pt)입니다.
3. (해결됨, C-2) 이 PC에서 `test_settings.py` 12개가 실패하던 문제.
4. 아래 5번(설정 창 E2E, 동료 PC 시험)은 그대로 남아 있습니다.

---

# 인수인계: 설정 창과 시작 안내 (SPEC-settings.md 구현)

> 작성: 2026-11-10. 다음 세션은 이 문서와 `SPEC-settings.md`를 먼저 읽습니다.
> 명세 11번의 1~4단계 코드를 모두 넣었고 자동 테스트는 통과했습니다. **커밋은 하지 않았습니다**(CLAUDE.md 6번: 사용자가 요청할 때만).

## 1. 현재 상태 한눈에

| 항목 | 상태 |
|---|---|
| 1단계 설정 로직 (`settings.py`, store/core/queue) | 완료, 테스트 통과 |
| 2단계 설정 창 (4개 탭, 저장/취소, 즉시 적용, 트레이 메뉴, ⚙, 단축키 기록과 등록 시험) | 완료, offscreen 테스트 통과 |
| 3단계 요약 AI (`cli_check.py`, Codex 실행, 모델 표기, 큐에 ChatGPT/Codex) | 완료, 실제 Codex 1회 호출 확인 |
| 4단계 시작 안내, 수집 스크립트 안내, README | 완료 |
| pytest (`test_perf.py` 제외) | 328 passed, 4 skipped |
| `test_perf.py` | 20 passed, 1 failed (`docker 컨테이너 네트워크` 370ms). **원래 HEAD(c1c4ecf)에서도 같은 실패(328ms)**. 이번 변경과 무관 |
| 명세 12번 End-to-end 2~11 (실제 트레이 앱) | **아직 안 함**. 사용자가 앱을 재시작해 확인 (4번 표) |
| 명세 13번 동료 PC 시험 | 사람 검토 체크포인트. 아직 안 함 |

## 2. 바뀐 파일

| 파일 | 내용 |
|---|---|
| `app/settings.py` (새) | Qt 없음. `FIELDS`(키, 탭, 종류, 범위), `shown`(잘못된 값이면 기본값과 표시), `validate`, `archive_missing`, `warnings`, `diff`, `to_save`(바뀐 키만 디스크 파일에 덮어씀), `read_sources`/`read_queue_sources`/`read_provider`, 시작 안내 기본값(`guess_sources`, `setup_provider`, `setup_config`, `skip_config`), 단축키(`normalize_hotkey`, `check_hotkey`, `VK_NAME`, 예약/다른 도구 키), `split_command`/`join_command` |
| `app/cli_check.py` (새) | Qt 없음. `resolve`(Claude: 설정 → PATH, Codex: 설정 → PATH → `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` 중 가장 늦은 것), `check`(버전 + 로그인, 15초, 토큰 0), `codex_models`(`models_cache.json`의 `visibility == "list"`), `CHEAPEST` |
| `app/settings_window.py` (새) | `SettingsWindow`(QDialog, 일반 모드 4개 탭 / 시작하기 모드 4단계), `Hooks`(main.py로 넘기는 동작), `HotkeyEdit`, `PathEdit`, `ListEdit`, 수집 스크립트 안내 묶음 |
| `app/store.py` | 새 키 7개, `load_config(create=)`, `config_missing`, `read_raw_config`, `config_signature` |
| `app/core.py` | `Core(create_config=)`, `sources`/`service_on`/`site_on`, `update_config`(저장 + 본체 적용, `self.config`를 새 dict로 교체), `reload_config`, 끈 서비스 zip은 `ZipOutcome("off")`로 이력 없이 건너뜀, 수집 파일/알림/상태 줄 거르기, `capture_site_status`, `collect_code` 서비스별, `reminder_days: 0` = 끔, `_int_cfg(lo=)`(queue_focus 0 허용), `summarize` 제공자별, `ask_model_label` |
| `app/ask.py` | `SOURCE_LABEL`/`CHAT_SOURCES`에 chatgpt, codex. `build_command(..., provider, effort, out_file)`, `run_codex`(`-o` 파일에서 답 읽고 지움), `clean_env`(Codex는 `CODEX_HOME` 말고 `CODEX_*` 전부 뺌), `summarize(provider=)`, `OFF_MESSAGE`, `model_label` |
| `app/queue.py` | `compute(..., sources=)`, `load_docs(..., sources=)`, `ALL_SOURCES`, `QueueItem.summary_model` |
| `app/main.py` | 트레이 메뉴(명세 4번 모양), `설정...`, `open_settings`(창 하나), `swap_hotkey`(새 키 먼저 등록 후 옛 키 해제, ID 번갈아 씀), 기록 중 전역 키 잠시 해제, `apply_settings`(명세 3-F 표), 첫 실행 판정과 수집 보류, 알림 클릭(`archive`, `hotkey` → 설정 창), F2 끄기 |
| `app/window.py` | 상태 줄 ⚙ (`settingsRequested`), `set_ask_enabled`(끄면 F2 안내 숨김), 요약 줄/상세 칸에 모델 표기 |
| `tests/test_settings.py`, `test_sources.py`, `test_cli_check.py`, `test_settings_window.py` (새) | 명세 12번 목록 + 창 offscreen 테스트 |
| `tests/test_ask.py`, `test_queue.py` | 명세 12번 추가 항목 |
| `README.md` | 첫 실행(시작 안내), 설정 창, 요약 AI 고르기, ChatGPT만 쓰는 경우, 트레이 메뉴 표, 데이터 위치 |
| `../CLAUDE.md` | 5번 복사 표: `hotkey.py`는 그대로 동일, 키 교체는 `main.py`의 `swap_hotkey`에 둠 |

## 3. 구현하며 정한 것 (명세에 없거나 명세와 조금 다른 것)

| 정한 것 | 이유 |
|---|---|
| 저장 시 **화면에서 바뀐 칸만** 새 값으로 바꾸고, 디스크에는 바뀐 키만 덮어씀(`settings.to_save`) | 손대지 않은 값(예: 문자열 `"claude"`로 된 `ask_command`)과 손으로 넣은 키를 그대로 두기 위해. 아무것도 안 바꾸면 파일 내용이 그대로(명세 E2E 3) |
| 경로 존재 검사는 **바뀐 값만**, 끈 서비스의 칸(`code_projects_dir`, `codex_dir`)은 검사 안 함 | 손대지 않은 칸 때문에 저장이 막히지 않게 |
| config 값이 잘못돼 기본값을 보여 준 칸은 저장할 때 그 기본값으로 씀. 이때 `저장`이 처음부터 켜짐(제목 `*`는 안 붙음) | 명세 5번 엣지 케이스 "기본값을 보여 줌"을 저장까지 이어지게 |
| 트레이 앱은 `Core(create_config=False)`. CLI(`python -m app.cli`)는 예전처럼 config.json을 만듦 | 시작 안내 중 종료하면 다음 실행에 다시 뜨게(명세 5번). 단, CLI를 먼저 돌린 PC는 시작 안내가 뜨지 않음 |
| 크롬 설정 단계는 `링크 열기` 대신 **`주소 복사`**(`chrome://settings/downloads`, `chrome://settings/performance`) | `chrome://` 주소는 다른 프로그램에서 열 수 없음. Tampermonkey는 `https://www.tampermonkey.net/`을 `링크 열기`로 |
| `openUrl`은 여전히 `main.py`에만 있음(`Hooks.open_url`로 넘김) | `test_forbidden_network.py`의 "URL 여는 곳은 main.py 하나" 규칙 유지 |
| 잘못 저장된 수집 파일 알림은 **켠 사이트 파일만** 셈 | 명세 표는 claude.ai에 묶었지만, ChatGPT 스크립트도 같은 실수를 하므로 |
| 예약 키에 `Win+L`, `Alt+Tab`, `Alt+F4`를 더함 | 등록 자체가 안 되거나 쓰면 곤란한 조합 |
| Codex 실행 때 `CODEX_HOME`을 뺀 `CODEX_*` 환경 변수를 모두 뺌 | 명세 10번 미결 "정리할 환경 변수 목록". 세션, 샌드박스 변수를 이어받지 않게. 인증 위치는 남김 |
| 상태 보기의 `마지막 zip 가져오기` → `마지막 claude.ai zip 가져오기`, `마지막 Code 수집` → 켠 서비스 이름 | 끈 서비스 줄을 숨기면서 무엇의 시각인지 분명하게 |
| F2 끄기 안내는 트레이 알림 없이 그 항목 줄에만 한 줄 | 명세 3-J-2 "한 줄" |
| `_int_cfg`: 하한 아래 값은 기본값 | 예전 `or default` 동작(0 → 기본값) 유지. `queue_focus`만 0 허용 |
| 숫자 칸, 목록 상자는 클릭해 초점이 있을 때만 휠로 값이 바뀜(`_WheelGuard`). 초점이 없으면 휠은 화면 스크롤 | 2026-11-10 사용자 피드백: 스크롤하려다 가중치 값이 바뀜 |

### 사용자 피드백 (2026-11-10)
- 설정 창은 디자인을 따로 주지 않았으므로 다듬을 곳이 있음(사용자가 나중에 정함). 기능은 괜찮다고 함.
- "최근 일 목록이 5개인데 10개로" → 이미 있는 `queue_focus`(설정 > 일반 > 열린 일 큐 > 크게 보여 줄 개수, 0~20). 찾기 어려웠으므로 칸 제목과 설명을 더 분명하게 고침.

## 4. 확인한 것

- 자동 테스트: 1번 표.
- 이 PC 실제 확인 (2026-11-10)
  - `claude --version` → `2.1.319 (Claude Code)`, `claude auth status` → JSON `loggedIn: true`, 종료 코드 0. 상태 줄 `준비됨: Claude Code 2.1.319, claude.ai 로그인`.
  - Codex: PATH에 없음, 번들 `%LOCALAPPDATA%\OpenAI\Codex\bin\<해시>\codex.exe`(codex-cli 0.163.0-alpha.10.2), `codex login status` → `Logged in using ChatGPT`.
  - 앱 코드 경로(`ask.summarize(provider="codex")`)로 실제 요약 1회: **6.3초**, 세 덩어리 형식 정상, `state_5.sqlite` threads **51 → 51**(요약이 Codex 수집에 새 대화로 안 잡힘).
  - 단축키: 안 쓰는 키(Ctrl+Alt+Shift+F19/F20)로 `swap_hotkey` 시험. 새 키 등록 후 옛 키가 풀림, 다른 곳이 잡은 키는 실패하고 옛 키 유지, 같은 키는 시험 생략.
  - 설정 창 탭 4개와 시작 안내 단계 화면을 offscreen으로 그려 배치 확인(가중치 칸이 넘쳐 2열로 고침, 가로 스크롤 끔).
- "가장 저렴" 확인: OpenAI 공식 [Codex 요금 문서](https://learn.chatgpt.com/docs/pricing) 기준 GPT-6 Luna가 토큰당 크레딧이 가장 낮고(입력 2.5, 출력 12.5 크레딧/100만 토큰), Plus 5시간 메시지 추정치도 가장 큼(350~3,000). `gpt-6-luna` 고정 표시 그대로 둠.

## 5. 남은 일 (다음 세션)

1. **명세 12번 End-to-end 2~11** (사용자가 트레이 앱을 재시작해 확인). 특히:
   - 2: CG PC 재시작 → 시작 안내 안 뜸, 트레이 메뉴 4번 모양
   - 4: 단축키 Ctrl+Alt+J로 바꿔 저장 → 재시작 없이 동작, Ctrl+Alt+H 해제
   - 6: 요약 AI GPT → F2 → 30초 안 요약, 줄 끝 `codex:gpt-6-luna`
   - 8~9: `THOUGHT_SEARCHER_APPDATA`, `THOUGHT_SEARCHER_LOCALAPPDATA`를 빈 임시 폴더로 두고 실행해 시작 안내 마치기/건너뛰기 (`pythonw thought_searcher.pyw`, 실행 중인 앱은 뮤텍스 때문에 먼저 종료)
   - 11: config.json을 깨뜨린 뒤 재시작 → 설정 창 경고 줄 → 저장 전까지 파일 그대로
2. 실패가 나오면 고치고, 단계별 커밋은 사용자 확인 후(커밋 메시지 초안을 먼저 보여 줌).
3. **명세 13번 동료 PC 시험** (사람 검토 체크포인트): README와 시작 안내만으로 설치, ChatGPT 수집 스크립트, GPT 요약까지. 이때 명세 10번 미결(동료 PC의 Python, codex 위치, 크롬 확장 정책)을 확정.
4. 미결로 남은 것
   - `codex exec`가 `--ignore-user-config`에도 플러그인 MCP를 띄우는 문제: `codex exec --help`(0.163.0-alpha.10.2)에 MCP를 끄는 전용 옵션이 없어 넣지 않음. 공식 문서도 MCP 서버가 사용량을 늘린다고 함. `-c mcp_servers={}` 같은 설정 덮어쓰기가 먹는지 시험해 볼 만함.
   - `test_perf.py`의 `docker 컨테이너 네트워크` 질의 300ms 초과는 이번 작업 전부터 있던 실패. 따로 볼 일.
5. 루트 `README.md` 도구 표는 바꿀 내용 없음(새 도구가 아님).

## 6. 다음 세션이 알아 둘 구조

- 설정 키를 새로 더할 때: `store.DEFAULT_CONFIG` + `settings.FIELDS`(안 넣으면 `test_fields_cover_all_default_keys`가 실패) + `settings_window`에 칸(`_bind(key, setter, getter)`와 `_item(..., key)`) + 필요하면 `main.App.apply_settings`에 적용.
- 저장 흐름: `SettingsWindow.save()` → `settings.validate` → 보관 폴더 만들기 확인 → 경고 → 외부 변경(`config_signature`) → `Hooks.try_hotkey` → `Core.update_config` → `Hooks.applied`(= `App.apply_settings`).
- 첫 실행 판정은 `store.config_missing`(앱 시작 때 config.json 없음). `setup_done` 키는 기록용이고 판정에 쓰지 않음.
- 실행 중 앱과 단축키, 뮤텍스가 겹치므로 시험용 앱을 띄우려면 실행 중인 앱을 먼저 종료.
