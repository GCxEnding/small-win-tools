"""data/syllable_freq.json 생성기 (개발용, 한 번 돌리면 됨).

- ksx1001: KS X 1001 완성형 한글 2,350자 (Python euc-kr 코덱으로 뽑는다)
- common : 그중 일상·업무 문서에서 특히 자주 쓰는 음절 (손으로 고른 목록)
그 외 현대 한글 음절(11,172자 중 나머지)은 '희귀'로 본다.

    python tools/build_syllable_freq.py
"""
from __future__ import annotations

import json
from pathlib import Path

COMMON = (
    "가각간갈감갑값강같개객갱거건걸검겁것게겠겨격견결겸경계고곡곤골곳공과관광괜교구국군굴굳권귀규균그극근글금급긍기긴길김깊까깨꺼께"
    "꼭꽃꾸끄끝끼나낙난날남납낫낮내냅냈너널넘넣네녀년념노녹논놀농높놓뇌누눈뉴느는늘능니님다단달담답당대댓더덕던덜데델도독돈돌동되된될됨됩"
    "두둔둘뒤드득든들듯등디딩따딱때떠떤또뜻띄라락란람랍랑래랜램랫략량러런럼렇레렉렌려력련렬렴령례로록론롤롭뢰료룡루류륙률르른를름릅릇릉리"
    "린림립링마막만많말맑망맞매맥맨맵머먹먼멀메멘며면멸명몇모목몬몰몸못묘무묵문물뭐므미민밀밍및바박밖반받발밝밤밥방배백밴뱃버번벌범법벗베"
    "벤벨벽변별병보복본볼봄봉봐부북분불붙브블비빈빌빙빛빠빨뻐뼈뿐사삭산살삶삼삽상새색샘생샤서석섞선설섬섭성세섹센셀셈셋셔션소속손솔송쇄수"
    "숙순술숨쉬쉽슈스슨슬습승시식신실심십싱싸쌍써쓰씀씨씩아악안앉않알암압앗았앙앞애액앱야약얀양어억언얻얼엄업없었엇에엑엔엘여역연열염엽였"
    "영옆예옛오옥온올옮옵와완왔왕왜외요욕용우운울움웃워원월웨웹위윈유육윤율융으은을음응의이익인일읽임입있잊자작잔잘잠잡장재쟁저적전절젊점"
    "접정젖제젝젠져조족존졸종좋좌죄주죽준줄중즈즉즐즘증지직진질짐집징짜짧째쪽찍차착찬찰참창찾채책처척천철첨첩첫청체쳐초촉촌총촬최추축춘출"
    "충취츠측층치칙친칠침칭카칸칼캐커컨컬컴케켓켜코콘콜쿠퀴크큰클큼키킨킬타탁탄탈탐탑탕태택탭터턴털테텍텐텔템토톤톨통퇴투툴튜트특튼틀티틱"
    "팀팅파판팔패팩팬퍼퍼페펜펴편평폐포폭폰폴폼표푸풀품풍퓨프픈플피픽필핑하학한할함합항해핵핸했행향허헌험헤헬혀현혈협형혜호혹혼홀홈홍화확"
    "환활황회획횟효후훈훨휘휴흐흑흔흘흡흥희흰히힌힘"
)


def main() -> None:
    ksx = []
    for cp in range(0xAC00, 0xD7A4):
        ch = chr(cp)
        # euc-kr 코덱은 8바이트 조합 표현(KS X 1001 부속서)까지 받아 주므로 2바이트인 것만 센다
        b = ch.encode("cp949")
        if len(b) == 2 and 0xB0 <= b[0] <= 0xC8 and 0xA1 <= b[1] <= 0xFE:
            ksx.append(ch)
    assert len(ksx) == 2350, len(ksx)
    ksx_set = set(ksx)
    common = sorted(set(COMMON))
    missing = [c for c in common if c not in ksx_set]
    if missing:
        raise SystemExit(f"KS X 1001에 없는 음절이 COMMON에 있음: {''.join(missing)}")
    data = {
        "_설명": "한글 음절 빈도 등급표. common=자주 쓰는 음절, ksx1001=KS X 1001 완성형 2,350자. 나머지 현대 한글 음절은 희귀로 본다. tools/build_syllable_freq.py로 생성.",
        "common": "".join(common),
        "ksx1001": "".join(ksx),
    }
    out = Path(__file__).resolve().parent.parent / "data" / "syllable_freq.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{out}: common {len(common)}자, ksx1001 {len(ksx)}자")


if __name__ == "__main__":
    main()
