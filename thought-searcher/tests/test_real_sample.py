"""실제 샘플 검증. tests/local/ 이 없으면 skip (공개 저장소에 커밋하지 않는 폴더).

tests/local/
  export/*.zip                 실제 claude.ai 내보내기 zip
  expected/<보관 폴더 기준 경로>.md   골라 둔 실제 대화의 기대 md (사람이 확인)
  code/<sessionId>.jsonl, code/<sessionId>.expected.md   실제 Code 세션과 기대 md
  golden_queries.json          실제 기억으로 쓴 검색 정답
"""
import json
from pathlib import Path

import pytest

from conftest import KST

LOCAL = Path(__file__).resolve().parent / "local"
pytestmark = pytest.mark.skipif(not LOCAL.is_dir(), reason="tests/local/ 없음")


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    from app.archive import Archive
    from app.core import Core
    from app.importers.claude_code import parse_session
    from app.index import connect
    from app.search import Searcher
    from app.store import Store

    tmp = tmp_path_factory.mktemp("real")
    roam, local, arch = tmp / "roam", tmp / "local", tmp / "archive"
    for d in (roam, local, arch):
        d.mkdir()
    (roam / "config.json").write_text(json.dumps({"archive_dir": str(arch), "code_projects_dir": str(tmp / "none")}),
                                      encoding="utf-8")
    core = Core(Store(roam, local), tz=KST)
    outcomes = {z.name: core.import_zip(z) for z in sorted((LOCAL / "export").glob("*.zip"))}
    a = Archive(arch, KST, core.redactor)
    for f in sorted((LOCAL / "code").glob("*.jsonl")):
        conv = parse_session(f)
        if conv:
            a.write(conv)
    core.sync_index()
    conn = connect(core.store.index_path)
    yield {"core": core, "archive": arch, "outcomes": outcomes, "searcher": Searcher(conn)}
    conn.close()


def test_import_succeeds(real):
    out = real["outcomes"]
    assert out, "tests/local/export 에 zip이 없음"
    assert not [n for n, o in out.items() if o.result == "failed"]
    assert any(o.result == "ok" and o.counts.get("new") for o in out.values())


def test_expected_md(real):
    exp = LOCAL / "expected"
    files = sorted(exp.rglob("*.md"))
    assert files
    for f in files:
        got = real["archive"] / f.relative_to(exp)
        assert got.exists(), f.relative_to(exp)
        assert got.read_text("utf-8") == f.read_text("utf-8"), f.name


def test_code_expected_md():
    from app.archive import render
    from app.importers.claude_code import parse_session
    from app.redact import Redactor
    files = sorted((LOCAL / "code").glob("*.jsonl"))
    assert files
    for f in files:
        exp = f.with_name(f.stem + ".expected.md")
        assert render(parse_session(f), KST, redact=Redactor()) == exp.read_text("utf-8"), f.name


def test_golden_queries(real):
    path = LOCAL / "golden_queries.json"
    if not path.exists():
        pytest.skip("golden_queries.json 없음 (사람이 작성)")
    golden = json.loads(path.read_text("utf-8"))
    fails = []
    for g in golden:
        got = [h.conv_id for h in real["searcher"].search(g["query"])][: g.get("top", 5)]
        for e in g["expect"]:
            if not any(x.startswith(e) for x in got):
                fails.append((g["query"], e, got[:3]))
    assert not fails, fails

