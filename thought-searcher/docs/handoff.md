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
