## 검색 개선 3단계: by:me, 한영 자동 보정, 0건 안내 + 정렬 순서와 `모두 지우기` 위치 (2026-11-13)
기준 문서는 `docs/search-plan.md` 5, 6, 7절입니다. push는 하지 않았고 `tests/test_perf.py`는 CG 지시로 돌리지 않았습니다.

### 먼저 고친 것 (CG 결정)
- 정렬 단추 순서를 어디서나 `최신 | 정확도`(기본값이 앞)로. 창 안 단추(`window.SORTS`)를 뒤집었고 설정 세그먼트는 이미 그 순서였습니다.
- `모두 지우기`를 칩 첫째 줄 끝(`일지` 뒤)으로 옮기고 둘째 줄은 `기간, 프로젝트, 내 질문, 정렬`. 칩 여백(`#qchip` 7px, `#qseg` 6px), 줄 간격 4px, 줄 이름 칸 28px, `모두 지우기` 8.5pt, 프로젝트 칩 이름 8자(`PROJECT_LABEL_MAX`)로 줄여 폭을 맞췄습니다.
- 칩 줄 최소 폭(실제 Windows 글꼴, 창을 띄운 상태, 출처 칩 8개 + 기간 + 프로젝트 이름 15자 + `모두 지우기` 켬): 예전(30c4b43) 칩 끔 528px / 전부 켬 626px -> 지금 칩 끔 519px / 전부 켬(내 질문 포함) 521px. 창 최소 폭(560px) 안에 들어갑니다.

### 바뀐 파일
| 파일 | 내용 |
|---|---|
| `app/query.py` | `Query.by_me`, `by:me`/`by:나`, `filter_labels`에 `by:me`. `token_kind`, `strip_tokens`(검색칸에서 해당 종류의 조건 조각 지우기: source/period/project/mine/exclude) |
| `app/search.py` | 후보 계산을 `_term_rows`로 뺌(검색과 개수 세기가 같이 씀). `by:me`: 단어마다 사용자 메시지에 있는 대화만(`_in_user_messages`), 노트 제외(노트 구역이 `role=user`로 저장되기 때문), 맞은 메시지/채팅 시각/미리보기는 사용자 메시지만. `Searcher.count`/`count_query`(Hit를 만들지 않음). `_msg_times`가 (시각, 사용자 메시지 id)를 돌려줌 |
| `app/hangul.py` (새) | emoji-searcher `hangul.py`의 두벌식 표와 `is_keyboard_latin`, `latin_to_hangul` 복사(출처를 주석에 적음) + `hangul_to_latin`, `latin_word_to_hangul`, `fix_layout`, `found_message` |
| `app/zero.py` (새) | `present`, `without`, `zero_hint`, `ZeroHint`(`text`: `출처를 제외하면 12건입니다`, `eul_reul`), `search_all`(검색 -> 0건이면 한영 보정 -> 그래도 0건이면 안내) |
| `app/window.py` | `내 질문` 칩(`ChipBar.mine`, `mine_button`), 칩 `clear_kinds`, 0건 안내 줄(`K_HINT`, 선택 가능, 클릭/Enter -> `remove_condition`), `set_results(..., hint=)`, 정렬 순서, 칩 줄 배치, 미리보기 제목 비움(항목 없을 때 `(제목 없음)` 안 보임) |
| `app/main.py` | `on_query`가 `search_all` 사용, 보정으로 찾으면 상태에 `nginx로 찾았습니다  ·  N건 · Xms` |
| `app/theme.py` | 칩/정렬/모두 지우기 여백 |
| `tests/test_by_me_zero.py` (새) | 17개. `test_search_sort.py`는 옛 최소 폭 시험 한 개를 뺌 |
| `README.md`, `docs/search-plan.md` | 검색 문법 표 `by:me`, 칩, 한영 보정, 0건 안내, 정렬 순서 |

### 정한 것 (계획에 없던 부분)
- 맞은 메시지/후보: `by:me`는 단어마다 "사용자 메시지에 그 단어가 있다"를 따로 보고 교집합. 제목에만 있는 단어는 인정하지 않습니다. 단어 없이 `by:me`만 있는 질의는 큐 거르기 길(예전과 같음)이라 `by:me`가 큐에는 영향이 없습니다(큐가 비어 검색으로 넘어가면 노트를 뺀 최근 대화 목록).
- 한영 보정 대상: `-제외어`, 따옴표 구문, `:`가 든 조각은 건드리지 않습니다. 영문 -> 한글은 소문자 영문 2자 이상이고 결과가 완성된 음절뿐일 때만(`nginx`, `docker`는 낱자가 남아 제외). 한글 -> 영문은 낱자 자모가 하나라도 있는 낱말만(완성된 한글 낱말은 그대로).
- 상태 글자는 `nginx로 찾았습니다  ·  3건 · 12ms`. 조사는 `로`/`으로`(한글 받침 없음/ㄹ이면 `로`).
- 0건 안내의 "가장 많이 나오는 조건"이 같으면 순서(출처, 기간, 프로젝트, 내 질문, 제외어) 앞쪽. 조건이 하나뿐이고 그것을 빼도 0건이면 안내 없음. 칩과 손으로 친 조각이 같이 있으면 둘 다 한 조건으로 보고 둘 다 끕니다.
- 안내 줄 클릭 직후 0.5초 안의 더블클릭은 새 목록의 항목을 열지 않게 무시합니다.

### 함정
- 칩 줄 폭 수치는 글꼴이 있는 실제 Windows 렌더링 기준입니다. offscreen 시험은 글꼴이 없어 글자가 넓게 잡혀(약 600px) 시험 기준을 `MIN_W + 60`으로 두었습니다.
- 칩 레이아웃은 창을 띄우기 전과 후의 `minimumSizeHint`가 다릅니다(스타일 적용 전엔 더 큼). 폭을 잴 때는 창을 띄우고 `layout().activate()` 뒤에 재야 합니다.
- `Searcher.search()`가 `by:me`에서 후보를 줄이는 쿼리는 단어마다 `messages` + `msg_fts` 조인입니다. 흔한 단어에서는 비용이 있으니 마지막 속도 확인 때 같이 보세요.

### 확인한 것
- `python -m pytest -q --deselect tests/test_perf.py` 통과.
- 화면 캡처 2장(`$KIROCREW_SCRATCH\png8\`): `search-narrow-chips-light.png`(창 최소 폭 560px, 칩 전부 켬, 모두 지우기 보임), `search-zero-dark.png`(0건 안내 줄). 안내 화면에서 미리보기 칸 제목이 `(제목 없음)`으로 나오는 결함을 고쳐 한 번 다시 찍었습니다.

### 남은 일
- 모든 단계 뒤 `tests/test_perf.py`를 돌려 `89a7794`와 비교(기간 질의, `by:me`, 최신순 포함).
- README 설정 창 표와 `docs/copy-table.md` 문구 정리는 CG 확인 후.

---

## 검색 개선 2단계: 정렬, 채팅 시각 표시, 날짜 묶음 줄 (2026-11-13)
기준 문서는 `docs/search-plan.md` 3, 4, 8절입니다. push는 하지 않았고 `tests/test_perf.py`는 CG 지시로 돌리지 않았습니다(모든 단계 뒤 따로 확인).

### 바뀐 파일
| 파일 | 내용 |
|---|---|
| `app/search.py` | `Searcher.search(text, limit, sort="relevance"\|"recent")`. 최신순은 후보를 채팅 시각 늦은 순(같으면 점수 높은 쪽)으로 정렬한 뒤 limit로 자름(`_rank`는 건드리지 않음, 최신순에서는 부르지 않음). `_matched_times`가 {대화: 맞은 메시지 중 가장 늦은 시각}을 SQL 한 번으로 구해 기간 거르기(`_in_period`)와 정렬이 같이 씀. `MatchedMessage.time` 추가. 최신순이면 `matches`가 늦은 메시지부터 |
| `app/window.py` | 칩 줄 오른쪽 끝 `정확도 \| 최신` 단추(`ChipBar.sort`, `sort_buttons`, NoFocus), `Ctrl+R`(`QueryEdit.toggleSort`), `popup()`에서 기본값으로 복귀, `SearchWindow.sort`/`set_default_sort`, `set_results(..., grouped=)`와 날짜 묶음 줄(`K_GROUP`, 고를 수 없는 항목 + `_navigate`가 건너뜀), 결과 줄 날짜(`row_when`), 미리보기 머리/메시지 이름표(`msg_stamp`, `role_label`), 아래 막대 키 안내 `정렬 Ctrl R`(좁으면 숨김) |
| `app/theme.py` | `#qseg`(정렬 단추) 스타일 |
| `app/settings.py`, `app/store.py` | `search_sort`(기본 `recent`), `SEARCH_SORTS`/`SEARCH_SORT_LABEL`, `read_search_sort`, 칸 종류 `search_sort` |
| `app/settings_window.py` | `설정 > 일반 > 검색 창 > 기본 정렬` 세그먼트(최신 / 정확도) |
| `app/main.py` | 검색에 `sort=window.sort`, 묶음 줄은 `최신순 and q.has_text`일 때만, 시작과 설정 저장 때 `set_default_sort` |
| `tests/test_search_sort.py`(새), `test_search_window.py`, `test_settings_search.py` | 새 테스트 13개. 키 안내 4개, 세그먼트 5개로 기대값 수정 |
| `README.md` | 검색 문법(기간이 메시지 기준, 정렬), 검색 창 화면, 검색 창 키 `Ctrl+R`, 설정 창 일반 행 |

### 정한 것 (계획에 없던 부분)
- `search()` 기본 인자는 `sort="relevance"`라 CLI와 예전 테스트는 그대로입니다. 창이 `window.sort`를 넘깁니다.
- 묶음 줄은 `최신순 + 단어(또는 한 글자) 검색`일 때만 만듭니다. 칩만 켠 목록, 큐, 정확도순에는 없습니다. 기준 날짜는 `SearchWindow.today`(시험에서 바꿈), 묶음 이름은 `window.date_group`.
- `모두 지우기`는 칩만 끄고 정렬은 그대로 둡니다(`ChipBar.reset(keep_sort=True)`). 창을 열 때(`popup`)만 기본값으로 돌아갑니다. 설정을 바꿔도 열려 있는 검색의 정렬은 그대로이고 다음에 열 때부터 적용됩니다.
- 설정의 세그먼트 순서는 `최신 | 정확도`, 창 안 단추는 계획대로 `정확도 | 최신`.
- `· 마지막 MM-DD`는 `Hit.updated`(대화 마지막 시각)와 `Hit.chat_time`의 로컬 날짜가 다를 때만 붙고 흐리게(sub 색 알파 150) 그립니다.
- 키 안내 `정렬 Ctrl R`을 아래 막대에 넣었고 좁은 창에서는 `대화 복사`처럼 숨깁니다.

### 함정
- 칩 줄의 최소 폭: 정렬 단추를 달아도 칩을 안 켰을 때는 첫째 줄(590px)이 기준 그대로입니다. 그러나 칩을 켜서 `모두 지우기`가 보이면 둘째 줄이 약 650px 이상이 되어, 창 최소 폭이 그만큼 커집니다(예전 약 590). 좁게 줄여 둔 창에서 칩을 켜면 창이 조금 넓어집니다. 문제가 되면 `모두 지우기`를 첫째 줄로 옮기거나 칩 여백을 줄일 것.
- 날짜 묶음 줄은 항목 플래그를 비워(`Qt.NoItemFlags`) 고를 수 없게 했습니다. 키 이동은 `_step_row`로 건너뛰고, 위 방향으로 첫 결과에 닿으면 `_on_row_changed`가 바로 위 묶음 줄이 보이게 스크롤합니다.
- 최신순에서는 영어 앞부분 일치(`log` -> `logpick`)로 약하게 맞은 대화가 위로 올 수 있습니다(계획에서 일단 두기로 함).
- 화면 확인용 Qt는 `offscreen` 플랫폼에서 글꼴이 없어 글자가 네모로 나옵니다. 화면 캡처는 기본(windows) 플랫폼으로 해야 읽힙니다.

### 확인한 것
- `python -m pytest -q --deselect tests/test_perf.py` 통과.
- 화면 캡처 2장(`$KIROCREW_SCRATCH\png7\search-wide-recent-light.png` 980px 라이트, 묶음 4개와 `· 마지막` 한 줄 / `settings-general-dark.png`). 눈에 띄는 결함 없음.

### 남은 일
- 3단계: `by:me` + `내 질문` 칩(정렬 단추 앞), 한영 자동 보정, 0건 안내.
- 모든 단계 뒤 `tests/test_perf.py` 확인(최신순은 `_rank`를 안 부르므로 따로 느려지지 않지만, 기간 질의 `_matched_times`는 흔한 단어에서 비용이 있음).

---

## 검색 개선 1단계: 메시지 시각 색인, 메시지 기준 기간 검색, 채팅 시각 (2026-11-12 밤)
기준 문서는 `docs/search-plan.md`입니다. 이번에는 검색 엔진만 바꿨고 창, 정렬, 칩, 설정은 건드리지 않았습니다. push는 하지 않았습니다.

### 바뀐 파일
| 파일 | 내용 |
|---|---|
| `app/index.py` | `SCHEMA_VERSION` 2. `messages.created_ts REAL`(UTC 초)와 `messages_created` 색인 추가. 메시지 시각을 못 읽거나 없으면 문서 `updated_ts` |
| `app/search.py` | `Hit.chat_time` 추가. 단어가 있는 검색의 `after:`/`before:`를 맞은 메시지 시각 기준으로 거름(`_in_period`). 메시지 시각 일괄 조회(`_msg_times`). `_make_hit`이 기간 안의 메시지만 `matches`/`match_total`에 담고 `chat_time` 계산 |
| `tests/test_message_time.py` (새) | 11개 |
| `tests/test_index_search.py` | 스키마 버전 단언을 `SCHEMA_VERSION`으로 |
| `docs/search-plan.md` | 이번 커밋에서 처음 추가. 1단계 보충 설명 한 절 덧붙임 |

### 정한 것 (계획에 없던 부분)
- **맞은 메시지** = 검색어 중 하나라도 들어 있는 메시지(`msg_fts`의 OR). 미리보기가 맞은 메시지를 고르는 방식(`_rowids`를 단어별로 합침)과 같습니다. 대화 전체는 지금처럼 모든 단어가 AND로 맞아야 후보가 됩니다. 그래서 `레디스 캐시`처럼 단어가 서로 다른 메시지에 나뉘어도, 그중 하나가 기간 안이면 남습니다.
- **제목에만 맞은 대화**(맞은 메시지가 하나도 없음): 예전 대화 단위 조건(`updated_ts >= after`, `created < before`)으로 판단하고 `chat_time`은 `updated_ts`입니다. 미리보기는 기간 안의 첫 메시지(없으면 첫 메시지). 본문에도 맞은 메시지가 있는데 모두 기간 밖이면 이 예외로 살리지 않습니다.
- 한 글자 검색어만 있는 질의(`title_terms`뿐)와 단어 없는 질의는 예전 그대로입니다. `chat_time`은 `updated_ts`로 채웁니다(마지막 메시지 시각과 같음).
- `before:`는 로컬 시간대 0시 미만(그날은 제외). `after:`는 0시 이상. 단어가 있을 때만 메시지 시각 `created_ts`로 비교합니다.
- `chat_time`은 로컬 시간대 aware `datetime`. 기간이 있으면 기간 안의 맞은 메시지 중 가장 늦은 시각.
- `_rank`는 그대로입니다. 기간 거르기는 `_rank` 앞에서 하므로 상위 N개를 자른 뒤 기간 밖이 섞이지 않습니다.
- 노트는 구역마다 시각이 없어서 `parse_note`가 문서 시각을 `created`에 넣고 있으므로 결과적으로 문서 `updated_ts`와 같습니다.

### 함정
- `messages.id`가 대화 안에서 이어지는 번호라는 기존 전제(`msg_first`..`msg_last`)를 그대로 씁니다. 제목에만 맞은 대화의 미리보기 선택도 이 범위를 돕니다.
- 메시지 시각 일괄 조회는 결과로 나갈 대화(최대 `limit`개)의 메시지 (id, created_ts)를 400개 대화씩 한 번에 읽습니다. 메시지가 아주 많은 대화가 섞이면 이 양이 늘어납니다.
- 기간 거르기 SQL은 `messages WHERE id IN (msg_fts MATCH ...) AND created_ts 범위`입니다. 흔한 단어 + 넓은 기간이면 `_rowids`와 비슷한 비용이 듭니다.
- 앱이 시작할 때 `main.py`가 `index.open()`으로 옛 버전 색인을 비우고, 이어서 `start_jobs`의 `sync_index`가 md에서 다시 채웁니다(대화가 많으면 처음에 부분 결과만 보임. 기존 재색인과 같음).
- `tests/test_queue.py`의 `_fill`은 `created_ts` 없이 `messages`에 넣습니다(NULL 허용). 기간 검색은 NULL 메시지를 기간 밖으로 봅니다.
- 작업 폴더 파일의 줄 끝이 CRLF인 것과 LF인 것이 섞여 있습니다(`core.autocrlf=true`). 저장소에는 LF로 들어갑니다.

### 확인한 것
- `python -m pytest -q --deselect tests/test_perf.py` 401개 통과(새 테스트 11개 포함).
- 스키마 1 -> 2 자동 재생성: 옛 스키마 파일을 직접 만들어 `open()`이 비우고 `sync()`가 md로 채우는 것을 `test_schema_v1_index_is_rebuilt_from_md`로 확인.
- **속도 테스트(`tests/test_perf.py`)는 CG 지시로 이번 단계에서 건너뜀.** 모든 단계 끝난 뒤 따로 확인할 것. 참고로 변경 전에 한 번 돌렸을 때 `docker 컨테이너 네트워크` 한 질의가 327ms로 한도(300ms)를 넘겨 실패했고(나머지 통과), 변경 후 전체 실행은 21개 모두 통과했습니다. 중간에 따로 잰 `after:2025-06 검색`은 312ms(3회 중 최소)였으니, 기간 질의가 한도 근처인지 마지막에 확인해야 합니다.

### 남은 일
- 2단계: 정렬(`정확도`/`최신`, `Ctrl+R`, 설정 `search_sort`), 화면의 채팅 시각 표시, 날짜 구분 줄. `Hit.chat_time`을 쓰면 됩니다.
- 3단계: `by:me`, 한영 자동 보정, 0건 안내.
- 모든 단계가 끝난 뒤 `tests/test_perf.py`를 돌려 기간 질의 속도를 확인.
- README와 `docs/copy-table.md` 갱신은 3단계 뒤.

---

# 인수인계: 검색창, 설정창 새 디자인 (2026-11-12)

> 이 절은 검색 개선 1단계 이전의 기록입니다(맨 위 절이 최신). 아래 절들은 그 전 작업 기록이고 구조 설명은 여전히 유효합니다.
> 기준 문서는 `docs/redesign-plan.md`(CG와 정함). 문구 정리는 `docs/copy-table.md`에 표로만 있고 **코드에는 아직 반영하지 않았습니다**(CG 확인 대기). push는 하지 않았습니다.

## 같은 날 오전 추가 (CG 피드백, 커밋 83a9779 ~ 318ce2b)
- 일지 칩(`src:journal`, `src:일지`): 단어와 같이 쓰면 일지 폴더 안의 노트 문서를 찾음(`search.journal_prefix`, `Searcher.journal_dir`, main.py가 검색마다 넣음).
- 단어 없이 칩만 켜면 검색 대신 열린 일 큐를 거름(`main.filter_queue`, `Core.compute_queue(days=)`로 기간 칩만큼 거슬러 봄). 거른 큐가 비면 검색으로 넘어감.
- 수집 스크립트 6단계는 굵은 제목 + 여러 줄 설명(`_row(plain=True)`).
- 문구표(`docs/copy-table.md`) 반영: 줄에는 줄인 설명, ⓘ에는 툴팁 글. 46자 임시 규칙 없앰. 툴팁 글이 없는 줄은 설명이 '…'로 잘릴 때만 ⓘ가 켜짐(`ElideLabel.elidedChanged`). ⓘ는 강조색 16px. 순위 가중치는 `WEIGHT_HELP`에 설명.
- 툴팁 0.3초(`theme.FastTipStyle`, `install_fast_tips`를 `main()`에서 팔레트보다 먼저).
- 작은 흰 창 깜빡임: 부모 없는 위젯을 레이아웃에 넣기 전에 `setVisible(True)` 하면 독립 창으로 잠깐 뜸. 아래 막대 키 안내와 ⓘ에서 고침. **위젯은 레이아웃에 넣은 뒤 보이게 할 것.** `test_no_stray_windows_when_opening`이 지킴.
- 처음 띄울 때 빈 회색 창: 검색창은 목록을 채운 뒤 띄우고, 두 창 모두 `theme.show_without_flash`(투명하게 띄워 첫 그리기 뒤 보임).
- 설정 창은 만드는 데 약 3초: `theme.BusyNote`("설정 창 여는 중…" + 모래시계 커서).
- 요약 칸: 끌어서 고르기, Ctrl+C(검색칸 초점 그대로, `QueryEdit.copy_other`), 오른쪽 클릭 복사. 같은 글이면 `setText`를 다시 하지 않아 고른 부분이 남음.
- 남은 것: 문구표 메모 1("크게 보여 줄 개수" 이름), 요약 지시문을 대화체로 바꿀지(CG가 haiku의 형식 밖 대화체 답을 좋아함, `ask.PROMPT`), Windows 실화면 확인(프로젝트 메뉴, 560px 둘째 줄).

## 큐 미리보기에 최근 대화 (2026-11-12 아침, CG 요청)
- 넓은 창의 큐 미리보기 칸 위쪽에 요약 없이도 내용이 보이게 `최근 대화`를 넣었습니다(그 아래에 저장된 요약 또는 F2 안내).
  - 채팅(claude.ai, Code, GPT, Codex): 마지막 5턴(`RECENT_TURNS`, 사용자 질문 하나 + 그 뒤 답들 = 한 턴), 한 줄 30자(`RECENT_CHARS`), `나` / `AI`. 가지 메시지, 빈 메시지는 뺌. md 꾸밈 기호(`` ` ``, `*`, `#`, `>`, 링크)는 빼고 공백은 하나로. 줄인 줄은 툴팁에 전체.
  - 일지 항목: `최근 일지` 마지막 5개(`MM-DD` + 본문과 하위 줄). 노트: `노트 끝부분` 마지막 5줄.
- 함수: `window.one_line`, `window.recent_turns`, `PreviewPane.add_recent`, `SearchWindow._fill_recent`. 스타일 `#pvRecent`, `#pvWho`, `#pvLine`(왼쪽 line 색 3px 막대).
- 좁은 창(미리보기 칸 없음)에는 넣지 않았습니다.
- 본문 끝이 원래 `...`이면 `…`와 겹쳐 `-...…`처럼 보일 수 있음(작은 흠).

## 검색 옵션 칩 구현 (2026-11-12 아침)
- `app/window.py`: `ChipBar`(머리 프레임 안, 검색칸 아래 두 줄), `SOURCE_CHIPS`, `PERIOD_CHIPS`, `project_token`, `period_after`. `SearchWindow(..., projects=)`, `query_text()`(검색칸 + 칩 토큰), `_on_chips`(바로 다시 검색, 초점은 검색칸). `popup()` 때 `chips.reset()`. placeholder는 `기억나는 단어 몇 개`.
- `app/theme.py` `search_qss`: `#chips`, `#qchip`(꺼짐 line 테두리, 켜짐 `accent_soft` + 강조색 테두리 + 굵게), `#chipClear`, `#chipSep`, `#chipCaption`. 새 색 값 없음.
- `app/main.py`: `project_names(conn)`(색인 docs의 프로젝트, 최근 순, 노트 제외, 40개). 메뉴를 열 때마다 읽음.
- 단어 없이 칩만 켜면 검색이 필터만으로 돌아 최근 순 목록이 나옵니다(`Searcher.search`의 `q.terms` 없는 분기). 큐로 돌아가지 않음.
- 함정
  - `proj:`는 공백에서 끊기므로 프로젝트 이름의 가장 긴 공백 없는 조각을 씁니다(`project_token`). 부분 일치라 그 조각을 가진 다른 프로젝트도 걸릴 수 있습니다. 검색 문법을 고치지 않으려고 이렇게 둠.
  - 손으로 친 `src:`, `proj:`는 칩을 켜진 것으로만 보이고 토큰을 더 붙이지 않습니다. 이 상태에서 칩을 눌러도 검색칸의 글자를 지우지는 않으므로 켜진 모양이 남습니다. 손으로 친 `after:`는 기간 칩에 반영하지 않습니다.
  - 프로젝트 메뉴(`QMenu.exec`)가 떠 있는 동안 창이 비활성이 되어 숨겨지지 않게 `chips.menu_open`을 `_hide_if_inactive`가 봅니다. 메뉴가 닫히면 창을 다시 활성화.
  - 칩은 `QSizePolicy.Fixed`(좁은 창에서 글자가 잘리지 않게), 프로젝트 칩 이름은 12자에서 줄임(전체는 툴팁).
- 시험: `tests/test_search_window.py`의 칩 4개(토큰, popup 비우기, NoFocus, 손으로 친 토큰, 프로젝트 목록). 전체 377 통과.
- 남은 확인: Windows 실화면에서 프로젝트 메뉴를 열고 닫아도 창이 안 닫히는지, 한글 글꼴로 둘째 줄이 560px에서 넘치지 않는지.

## 추가 수정 (같은 날, CG 확인 뒤)
- 설정창 아래 막대에서 취소/저장 옆 키캡(Esc, Ctrl S)을 뺐습니다. Esc, Ctrl+S 단축키는 그대로 동작하고, 설정 찾기 칸 안의 `Ctrl F` 안내는 그대로입니다.
- 설정 찾기로 섹션이 숨겨지면 보이는 첫 섹션의 위 간격을 없앱니다(`Section.set_first`, `_refresh_filter`). 전에는 숨은 섹션 뒤 첫 보이는 섹션이 36px 간격을 그대로 가져 제목 아래가 크게 비었습니다.
- "열자마자 바뀐 설정 1개"는 버그가 아니었습니다. 확인용 그림 스크립트가 `queue_days`를 일부러 7로 바꾼 뒤 찍은 것입니다. 경로 확장 전 값(`~/notes`, `%USERPROFILE%`)을 넣은 config로도 열자마자 바뀐 키가 없음을 `tests/test_settings_search.py::test_fresh_window_has_no_changed_count`가 확인합니다.

## 바뀐 파일
| 파일 | 내용 |
|---|---|
| `app/theme.py` | 옅은 강조색(`accent_soft`, `accent_badge`, `derived`), 키캡/찾기 칸/카드/세그먼트/강조색 막대/아래 막대/나누기 막대 스타일, 아이콘 `search`/`info`, `round_corners`(DWM 모서리) |
| `app/ui_state.py` (새) | `ui_state.json`(LOCALAPPDATA) 읽기/쓰기, 값 검사, 화면 맞춤(`fit_size`). `Store.ui_state_path` 추가 |
| `app/window.py` | 검색창 전면 개편: 큰 검색칸, 한 줄 `HitDelegate`, `QSplitter`+`PreviewPane`(좁음/넓음 `WIDE_MIN_W=760`), 아래 막대, 크기 조절 `EdgeGrip`, `ElideLabel`(줄임 라벨, 낱말 칠하기) |
| `app/settings_window.py` | 카드 섹션, 두 줄 `_row`(+`tip`, `empty_desc`, `plain`), `InfoButton`(ⓘ), `SearchBox` 설정 찾기, `NavButton` 배지, 아래 막대(바뀐 설정 수, 키캡), Ctrl+S/Ctrl+F, 모드 세그먼트, 단축키 칸 키캡 |
| `app/main.py` | `SearchWindow(theme, state_path=...)` |
| `tests/test_ui_state.py`, `test_search_window.py`, `test_settings_search.py` (새), `test_theme.py` | 새 동작 시험. `test_theme.py`의 "스타일시트에 테마 밖 색 없음"은 섞어 만든 옅은 강조색을 허용하도록 고침 |
| `README.md`, `docs/redesign-plan.md`, `docs/copy-table.md` | 화면 설명, 계획, 문구표 |

## 정한 것
- 검색창 넓음/좁음 기준은 760px(`window.WIDE_MIN_W`). 기본 창 크기 820x560은 넓음에 속합니다. 최소 560x360.
- 목록 칸 비율은 `ui_state.json`의 `search_window.split`(0.2~0.8). 크기와 같이, 사용자가 끌어서 바꿨을 때만 저장합니다(화면에 맞춰 줄인 크기를 덮어쓰지 않으려고).
- 미리보기는 `mdparse`로 md를 읽어 `MatchedMessage.ordinal` 앞뒤를 고릅니다(`MdCache`, 경로+수정시각 키, 8개). 맞은 낱말은 목록 미리보기의 강조 글자들을 모아 본문에서 다시 찾습니다(검색 코드를 건드리지 않으려고). md 형식이 아닌 원본(노트 등)이면 목록의 미리보기 한 줄을 보입니다. `missing`이면 "원본 없음".
- 큐 줄은 모두 한 줄 모양입니다. 일지 항목(`subtitle`)은 좁을 때 고른 줄의 둘째 줄에, 넓을 때 미리보기 머리에 보입니다. 저장된 요약(`detail` 라벨)은 넓을 때 미리보기 칸, 좁을 때 목록 아래로 옮겨 다닙니다.
- 설정 찾기: 줄의 이름+설명+툴팁(+빈 칸 글)에서 모든 낱말(AND)을 찾습니다. 설정값 때문에 숨은 줄(서비스 끔 등)은 `_nat`로 따로 기억해 찾기와 상관없이 숨깁니다. 저장 오류가 나면 찾기 칸을 비워 오류 줄이 보이게 합니다.
- 문구 확정 전 임시 규칙: 설명이 46자(`AUTO_TIP_LEN`)를 넘으면 한 줄로 줄여 보이고 전체는 ⓘ 툴팁에 둡니다. 문구표가 확정되면 각 `_row`에 `tip=`/`empty_desc=`를 넣고 이 규칙은 빼면 됩니다.
- 경로 칸(`PathEdit`)이 든 줄은 자동으로 stacked(이름 아래 가로로 펼침)입니다.
- Esc 동작은 그대로(바뀐 것 있으면 확인). 시작 안내(setup)는 같은 카드/아래 막대를 쓰고 찾기 칸은 없습니다.

## 함정
- `QPushButton`에 동적 속성 이름을 `pos`로 쓰면 `QWidget.pos`와 겹칩니다. 세그먼트 위치는 `segpos`.
- 창을 `show()`하기 전에는 `resize()`해도 `resizeEvent`가 안 옵니다. 좁음/넓음은 `_apply_mode()`가 `set_results`, `set_queue`에서도 다시 정합니다. 테스트에서 폭을 바꿀 때는 먼저 `show()`.
- 레이아웃에서 뺀 위젯은 `deleteLater()`만으로는 이벤트 루프가 돌 때까지 화면에 남아 겹쳐 보입니다. `hide()`(+`setParent(None)`)를 같이 합니다(미리보기 본문, 아래 막대 키 안내).
- Qt 툴팁은 순수 글자면 줄바꿈하지 않아 `tip_html`이 폭 340의 표로 감쌉니다.
- 정해진 계획과 impeccable 지침이 부딪힌 곳: 지침은 "카드 모서리 12~16px, 1px 넘는 색 있는 border-left 금지"인데 계획은 카드 모서리 9px, 선택 줄/탭의 왼쪽 강조 막대 3px입니다. 계획(CG 합의)을 따랐습니다.
- 둥근 모서리(DWM 33)와 `startSystemResize` 끌기는 offscreen에서 시험할 수 없어 Windows 11 실화면 확인이 필요합니다(함수는 실패해도 사각형/무동작으로 안전).
- 검색칸 placeholder는 큰 글자에서 잘려서 `src:|proj:|after:` 요약형으로 줄이고, 전체 문법은 검색칸 툴팁으로 옮겼습니다(검색 문법 자체는 그대로).
- 아래 막대 키 안내에서 `←/→`, `Esc 닫기` 문구는 계획대로 뺐습니다. `←→`는 좁은 줄과 미리보기 머리에 보입니다.
- `tests/test_perf.py::test_query_under_limit[docker 컨테이너 네트워크]`가 이 PC에서 300ms 기준을 313ms로 넘겨 실패합니다(작업 전부터 그랬고 UI와 무관). 나머지는 모두 통과.

## 확인한 것
- `python -m pytest -q --ignore=tests/test_perf.py`: 374개 통과. `tests/test_perf.py`는 위 1건만 실패(이전과 같음).
- `QWidget.grab()`으로 검색창(좁음 620/넓음 980 x 검색/큐 x 라이트/다크)과 설정창(일반, 찾기 중 x 라이트/다크)을 찍어 봤습니다. 찍은 스크립트는 세션 scratch에 있었고 저장소에는 없습니다(합성 데이터 사용).
- 찍어서 고친 것: 미리보기에 이전 결과가 겹쳐 보임, 아래 막대 키 안내 겹침(큐 전환), 경로 칸 줄이 좁아 설명이 잘림.

## 남은 일
1. CG가 `docs/copy-table.md`를 확인하면 `settings_window.py`에 문구 반영(`tip=`, `empty_desc=`), 임시 규칙 제거, 깨지는 테스트 기대값 갱신. "크게 보여 줄 개수" 이름 변경 여부도 그때 정합니다. (2026-11-12: 문구 반영됨, 이름은 "기본 노출 개수"로 바꿈)
2. Windows 11 실제 화면에서 둥근 모서리, 테두리 끌기, 나누기 막대 끌기 확인.
3. `SPEC.md`/`SPEC-settings.md`에 새 화면 설명을 옮길지 결정(지금은 계획 문서와 README에만 반영).
4. ~~검색 옵션 칩~~ **2026-11-12 구현함** (아래 "검색 옵션 칩 구현" 절). Windows 실화면 확인만 남음. 아래는 정한 내용 그대로 둡니다.
   - 1줄 `출처`(여러 개 고름, 회사별 순서): AI(`src:ai`), 프로젝트(`src:project`), 메모리(`src:memory`), Code(`src:code`), GPT(`src:gpt`), Codex(`src:codex`), 노트(`src:note`).
   - 2줄 `기간`(하나만 고름): 전체 / 1주 / 1달 / 3달 / 올해 -> `after:YYYY-MM-DD`(오늘-7일, -30일, -90일, 1월 1일). 구분선 뒤 `프로젝트 ▾` 칩: 색인의 프로젝트 이름 메뉴(+ "모든 프로젝트"), 고르면 칩에 이름 표시(`proj:`). 하나라도 켜지면 줄 끝에 `모두 지우기`.
   - 칩 모양: 둥근 알약, 작은 글자. 꺼짐은 line 테두리 + 본문색, 켜짐은 옅은 강조색 바탕(`accent_soft`) + 강조색 테두리와 굵은 글자. 줄 앞에 회색 작은 제목. 새 색 값 없음.
   - 칩은 검색칸에 글자를 넣지 않습니다. 검색할 때만 칩 토큰을 검색어 뒤에 붙여 넘깁니다(검색, 문법 코드는 그대로). 손으로 `src:code` 등을 치면 해당 칩을 켜진 것으로만 표시합니다.
   - 칩은 NoFocus(입력 초점은 검색칸에 남음), 누르면 바로 다시 검색, 창이 닫히지 않아야 합니다. 창을 열 때마다(`popup()`) 모두 끕니다.
   - 단어가 비고 칩도 없으면 지금처럼 큐. 단어가 비고 칩만 켜졌을 때는 검색이 필터만으로 되면 결과를 보이고, 안 되면 큐를 유지하고 함정에 적습니다.
   - placeholder는 `기억나는 단어 몇 개`만 남기고 전체 문법은 툴팁에 둡니다.
   - 시험: 칩 토큰이 붙는지, popup 때 비워지는지, 손으로 친 토큰이 칩을 켜는지.

---
# 인수인계: 설정 창 디자인 개편과 테마 (2026-11-10 밤)

> (2026-11-10 시점) 아래 "설정 창과 시작 안내" 절은 그 전 작업 기록이고 구조 설명은 여전히 유효합니다.
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
