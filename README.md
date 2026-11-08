# small-win-tools

Windows에서 쓰는 작은 도구들을 모아 두는 곳이에요. 🧰

거창한 프로그램은 아니고, "이거 하나만 있으면 편하겠는데…" 싶을 때 만든 소품들입니다.
각 도구는 자기 폴더 안에서 따로 동작하니까, 필요한 것만 골라서 쓰시면 돼요.

## 도구 목록

| # | 도구 | 한 줄 소개 |
|---|---|---|
| 1 | [emoji-searcher](emoji-searcher/) | Win+. 으로 띄우는 한국어 이모지 검색기. `배포` → 🚀, 초성(`ㅂㅍ`)과 한영 오타(`qovh`)도 알아들어요. |
| 2 | [gohome-vlog](gohome-vlog/) | 활성 창 기준으로 하루 일한 프로그램·프로젝트·서버를 기록해 퇴근 전에 Obsidian 일지용 요약을 만들어 줘요. 입력 내용은 수집하지 않아요. |
| 3 | [thought-searcher](thought-searcher/) | Claude 채팅 기록(claude.ai 내보내기, Claude Code 세션)을 md로 영구 보관하고 Ctrl+Alt+H로 단어 몇 개만으로 찾아요. 전부 로컬, 토큰 0. |
| 4 | [hangul-restore](hangul-restore/) | 깨진 한글을 복사하고 Win+Shift+K. `寃곗옱` → `결재`. `°áÀç`, URL, `\u` 이스케이프, Base64까지 풀고 어디서 깨졌는지 원인 힌트도 알려 줘요. |

앞으로 더 늘어날 수도 있어요. 몇 개가 될지는 저도 모릅니다. 🙂

## 공통으로 필요한 것

- Windows 10 / 11
- 대부분 Python 3.10 이상 (도구별 README에 따로 적어 둘게요)

```bash
git clone https://github.com/GCxEnding/small-win-tools.git
```

받은 다음에는 쓰고 싶은 도구 폴더의 README를 열어 보세요.

## 폴더 규칙 (새 도구를 넣을 때)

- 도구 하나 = 최상위 폴더 하나 (`small-win-tools/<도구-이름>/`)
- 폴더 안에 `README.md`(설치·사용법)와 `SPEC.md`(명세)를 둡니다.
- 개인 데이터는 저장소가 아니라 `%APPDATA%\<도구-이름>\` 같은 PC별 위치에 둡니다. 공개 저장소라서요.
- 새 도구를 넣으면 위 표에 한 줄 추가!

## 만든 방식

이 저장소의 도구들은 AI와 함께 만들었어요.

- **사람 (GCxEnding)**: 기획, 명세(SPEC.md) 작성, 설계 결정, 실제 PC에서 테스트와 검수
- **Claude Opus 5.5 (Anthropic)**: 명세를 바탕으로 소스 코드, 테스트, 태그 데이터, 문서 작성

코드는 사람이 직접 돌려 보고 확인한 뒤에 올리지만, 한 줄씩 꼼꼼히 리뷰한 것은 아니에요.
문제를 발견하시면 이슈로 알려 주세요. 🙏
