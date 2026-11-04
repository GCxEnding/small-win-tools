# emoji-searcher 🔍

노트 제목 맨 앞에 붙일 이모지를 **한국어로** 빠르게 찾아서 바로 입력해 주는 작은 도구예요.

Windows 기본 이모지 패널(Win+.)은 한국어 검색이 아쉽잖아요. 그래서 이모지마다 한/영 연상 태그를 미리 넉넉히 만들어 두고, 그걸로 검색하게 했어요.

- `배포` → 🚀 &nbsp; `버그` → 🐛 &nbsp; `완료` → ✅ &nbsp; `보류` → ⏸️
- 초성으로도 찾아요: `ㅂㅍ` → 🚀
- 한/영 전환을 깜빡해도 괜찮아요: `qnf`(=불) → 🔥, `qovh`(=배포) → 🚀
- 영어도 돼요: `deploy`, `bug`
- 자주/최근에 쓴 이모지는 위로 올라오고, 검색창이 비어 있을 땐 최근 쓴 순서로 보여 줘요.
- 실행 중에는 인터넷을 전혀 안 써요. 회사 망에서도 그냥 돌아갑니다.

## 설치

Python 3.10 이상이 필요해요.

```bash
git clone https://github.com/GCxEnding/small-win-tools.git
```

```bash
cd small-win-tools/emoji-searcher
```

```bash
pip install -r requirements.txt
```

## 실행

```bash
pythonw emoji_searcher.pyw
```

창은 안 뜨고 작업 표시줄 트레이에 🔍 아이콘이 생겨요. 이제 아무 데서나 **Win+.** 을 누르면 마우스 커서 자리에 우클릭 메뉴처럼 검색창이 나와요.

> Win+. 이 Windows 기본 이모지 패널에 잡혀 있으면, 대신 **Ctrl+Alt+E** 로 등록되고 트레이 알림으로 알려 드려요.
> Win+. 을 쓰고 싶으면 아래 [Win+. 기본 동작 끄기](#win-기본-동작-끄기)를 해 주세요.

### 사용법

| 키 | 동작 |
|---|---|
| Win+. | 검색창 열기 / 닫기 |
| 글자 입력 | 바로바로 검색 (한글 조합 중에도 갱신돼요) |
| ↑ / ↓, PgUp / PgDn | 결과 이동 |
| Enter | 선택 → 원래 쓰던 창에 바로 붙여넣기 |
| Esc, 창 밖 클릭 | 닫기 |

- 공백으로 여러 단어를 넣으면 전부 맞는 것만 보여 줘요. 예: `빨간 하트`
- 선택한 이모지는 클립보드에도 들어가요(원래 클립보드 내용은 덮어써요).
- 관리자 권한으로 실행된 창에는 Windows가 자동 입력을 막아요. 그럴 땐 "클립보드에 복사됨" 알림이 뜨니까 Ctrl+V 한 번만 눌러 주세요.
- 트레이 아이콘을 클릭해서 열었을 때도 붙여넣을 창을 알 수 없어서 클립보드 복사만 해요.

### 트레이 메뉴

- **열기**: 검색창 열기
- **데이터 폴더 열기**: `%APPDATA%\emoji-searcher\` 열기
- **개인 태그 다시 읽기**: `user_tags.json` 고친 걸 바로 반영
- **종료**

## Win+. 기본 동작 끄기

Windows 기본 이모지 패널 대신 이 도구가 Win+. 을 받게 하려면:

1. `registry\disable-win-period.cmd` 더블클릭
   - 지금 값과 바뀐 값을 보여 줘요. 이미 Win+V 등을 꺼 두셨어도 그 설정은 그대로 두고 Win+. 만 추가해요.
   - 바꾸기 전에 `registry\backup\` 에 백업(.reg)을 남겨요.
2. Explorer를 재시작할지 물어보면 `Y` (또는 나중에 로그아웃 후 로그인)
3. emoji-searcher를 다시 실행하고 Win+. 눌러 보기

되돌리고 싶으면 `registry\restore-win-period.cmd` 를 실행하면 Win+. 만 원래대로 돌아와요.

> ⚠️ 이 방법(`DisabledHotkeys`)으로 이모지 패널이 실제로 꺼지는지는 아직 확인 전이에요. 이모지 패널은 Explorer가 아니라 입력기 쪽에서 처리할 수도 있거든요.
> 안 꺼지면 그냥 Ctrl+Alt+E 로 쓰시거나, `config.json` 에서 다른 키로 바꿔 주세요.

## 컴퓨터 켤 때 자동 실행

1. Win+R → `shell:startup` 입력 → Enter (시작프로그램 폴더가 열려요)
2. 그 폴더에서 오른쪽 클릭 → 새로 만들기 → 바로 가기
3. 대상에 아래처럼 입력 (경로는 본인 것으로)

```text
pythonw.exe "D:\...\small-win-tools\emoji-searcher\emoji_searcher.pyw"
```

`pythonw.exe` 를 못 찾는다고 하면 `where pythonw` 로 나온 전체 경로를 넣어 주세요.

## 내 데이터 (PC마다 따로)

`%APPDATA%\emoji-searcher\` 에 저장돼요. 저장소에는 안 올라가요.

| 파일 | 내용 |
|---|---|
| `user_tags.json` | 내가 붙이는 태그. 직접 편집해요. |
| `usage.json` | 이모지별 사용 횟수, 마지막 사용 시각 |
| `config.json` | 단축키, 결과 개수 |
| `error.log` | 문제가 생겼을 때만 생겨요 |

### 개인 태그 추가하기

`user_tags.json` 을 메모장으로 열어서 이렇게 적으면 돼요:

```json
{
  "🔥": ["긴급", "핫픽스"],
  "🧪": ["실험실"],
  "🦆": ["러버덕", "오리디버깅"]
}
```

저장한 다음 트레이 메뉴 **개인 태그 다시 읽기**. 개인 태그는 검색할 때 가중치를 더 받아서 위쪽에 나와요.
처음 실행 때 예시가 들어간 파일을 만들어 드려요. JSON이 깨져 있으면 알림만 띄우고 개인 태그 없이 동작해요(파일은 절대 덮어쓰지 않아요).

### 설정 바꾸기 (`config.json`)

```json
{
  "hotkey": "win+.",
  "fallback_hotkey": "ctrl+alt+e",
  "max_results": 30,
  "position": "cursor"
}
```

키 이름 예: `ctrl`, `alt`, `shift`, `win` + 글자/숫자, `f1`~`f24`, `.` `,` `;` `/` `space` 등. `position` 은 `cursor`(커서 자리, 기본) 또는 `center`(모니터 중앙). 바꾼 뒤에는 앱을 다시 실행해 주세요.

## 개발자용

### 테스트

```bash
python -m pytest
```

`tests/golden_queries.json` 에 "이 검색어면 이 이모지가 상위 5개 안에 나와야 한다"는 정답 샘플이 있어요. 자주 쓰는 이모지/뜻에 맞게 고쳐 주세요.

### 태그 데이터 다시 만들기

검색 데이터(`data/emoji_tags.json`)는 미리 만들어서 같이 커밋해 둬요. 태그를 고치고 싶으면:

1. `tools/ai_tags/*.txt` 수정 (한 줄에 하나: `🚀|배포,출시,릴리즈|deploy,launch,release`, 앞에 둔 태그일수록 검색 순위가 조금 더 높아요)
2. 다시 빌드

```bash
python tools/build_data.py
```

- 원천: Unicode `emoji-test.txt` + CLDR 이름/키워드(ko, en) + `tools/ai_tags` 의 연상 태그
- 처음 한 번은 원천 파일을 내려받아 `tools/.cache/` 에 둬요(개발할 때만 인터넷 사용).
- 기본은 Emoji 15.0까지, 피부색 변형 제외. 회사 PC에서 깨져 보이는 게 있으면 `--max-version 14.0` 처럼 낮춰 주세요.
- 성별 변형(👩‍🔬 등)은 기본형(🧑‍🔬)의 태그를 물려받고, 국기는 나라 이름이 자동으로 들어가요.

### 구조

```
emoji-searcher/
├─ emoji_searcher.pyw     진입점
├─ app/
│  ├─ main.py             트레이, 단일 실행, 앱 수명
│  ├─ hotkey.py           전역 단축키 (RegisterHotKey)
│  ├─ window.py           검색창 UI (PySide6)
│  ├─ paste.py            포커스 복귀, Ctrl+V 전송 (SendInput)
│  ├─ search.py           검색/정렬 (UI 없음, 테스트 대상)
│  ├─ hangul.py           초성, 두벌식 영문 → 한글
│  └─ store.py            %APPDATA% 데이터, 원자적 저장
├─ data/emoji_tags.json   검색 데이터
├─ tools/                 데이터 빌드 스크립트와 태그 원본
├─ registry/              Win+. 끄기/되돌리기
└─ tests/
```

자세한 결정 이유와 엣지 케이스는 [SPEC.md](SPEC.md)에 있어요.
