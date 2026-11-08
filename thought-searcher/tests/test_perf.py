"""대화 2만 개(대화당 평균 30메시지) 규모에서 검색 1회 300ms 이하. 느린 테스트지만 기본 실행에 포함."""
import random
import time
from datetime import datetime, timedelta, timezone

import pytest

from conftest import KST

from app.archive import render
from app.index import Index, connect
from app.model import Conversation, Message
from app.search import Searcher

N_CONV = 20_000
AVG_MSG = 30
LIMIT_MS = 300

KO = ("배포 로그 설정 서버 데이터 검색 오류 수정 확인 테스트 사용자 요청 응답 파일 폴더 스크립트 대시보드 성능 "
      "메모리 색인 질의 결과 화면 단축키 알림 수집 변환 보관 동기화 회사 개인 프로젝트 문서 정리 일지 회고 "
      "톰캣 엔진엑스 쿠버네티스 도커 컨테이너 네트워크 인증서 보안 권한 계정 비밀번호 백업 복구 장애 원인 "
      "분석 측정 비교 개선 리팩터링 함수 클래스 모듈 패키지 의존성 버전 업데이트 설치 실행 종료 시작").split()
EN = ("nginx tomcat docker kubernetes python sqlite fts5 query index search log deploy build test commit "
      "branch merge pull request api token json yaml config server client http https cache redis kafka "
      "grafana prometheus elastic logpick logcut bigram trigram unicode windows linux powershell bash").split()
RARE = ["희귀단어{}".format(i) for i in range(50)] + ["zebrafish{}".format(i) for i in range(50)]


def _text(rng: random.Random) -> str:
    n = rng.randint(8, 30)
    words = []
    for _ in range(n):
        r = rng.random()
        if r < 0.6:
            words.append(rng.choice(KO) + rng.choice(["", "를", "가", "에서", "은", ""]))
        elif r < 0.98:
            words.append(rng.choice(EN))
        else:
            words.append(rng.choice(RARE))
    return " ".join(words)


@pytest.fixture(scope="module")
def big_index(tmp_path_factory):
    rng = random.Random(20261107)
    root = tmp_path_factory.mktemp("perf_archive")
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    sources = ["claude-ai", "claude-code"]
    for i in range(N_CONV):
        src = sources[i % 2]
        t0 = base + timedelta(minutes=i * 50)
        nmsg = rng.randint(10, 50)
        msgs = [Message(f"m{j}", "user" if j % 2 == 0 else "assistant", t0 + timedelta(minutes=j), _text(rng))
                for j in range(nmsg)]
        cid = f"{src}:{i:08d}-perf"
        c = Conversation(cid, src, " ".join(rng.choice(KO + EN) for _ in range(3)), f"proj{i % 37}", t0,
                         msgs[-1].created, "", msgs)
        d = root / src / f"{t0:%Y}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{t0:%Y-%m-%d}_c_{i:08d}.md").write_text(render(c, KST), encoding="utf-8", newline="\n")
    idx = Index(tmp_path_factory.mktemp("perf_db") / "index.db")
    t = time.perf_counter()
    idx.sync(root)
    print(f"\n색인 {N_CONV}개: {time.perf_counter() - t:.1f}s")
    conn = connect(idx.db_path)
    yield Searcher(conn)
    conn.close()


QUERIES = [
    "배포", "로그 배포", "nginx", "nginx설정", "log", "logpick", "\"로그 배포\"", "서버 오류 수정",
    "docker 컨테이너 네트워크", "희귀단어7", "zebrafish3", "src:code 배포", "proj:proj1 로그", "after:2025-06 검색",
    "배포 -롤백", "색인 -nginx", "톰", "a", "grafana prometheus elastic", "데이터를",
]


def test_index_size(big_index):
    n = big_index.conn.execute("SELECT count(*), sum(msg_count) FROM docs").fetchone()
    assert n[0] == N_CONV and n[1] > N_CONV * 25


@pytest.mark.parametrize("q", QUERIES)
def test_query_under_limit(big_index, q):
    big_index.search(q)   # 디스크 캐시 데우기
    # 매번 새 Searcher(질의 캐시 없음)로 잰다
    best = min(_timed(Searcher(big_index.conn), q) for _ in range(3))
    assert best <= LIMIT_MS, f"{q!r}: {best:.0f}ms"


def _timed(s, q):
    t = time.perf_counter()
    hits = s.search(q)
    ms = (time.perf_counter() - t) * 1000
    assert hits or q in ("a",)
    return ms
