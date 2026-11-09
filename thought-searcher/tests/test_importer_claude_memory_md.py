import zipfile

from conftest import make_export_zips

from app.importers import detect
from app.importers.claude_export import ClaudeExportImporter
from app.importers.claude_memory_md import ClaudeMemoryMdImporter, split_front
from app.search import search

ROOT = "claude-memory-2026-11-09"


def _md(name, desc, body):
    return f'---\nname: "{name}"\ndescription: "{desc}"\n---\n\n{body}\n'


FILES = {
    "profile.md": _md("profile", "사용자 소개", "홈랩을 운영한다."),
    "areas/homelab.md": _md("homelab", "라즈베리파이 홈랩", "- 그라파나로 온도를 본다"),
    "topics/reading.md": _md("reading", "독서 메모", "- 소설 한 권 읽는 중"),
    "projects/사내 로그 수집/index.md": _md("index", "프로젝트 개요", "fluentbit 를 쓴다"),
    "projects/사내 로그 수집/areas/alerts.md": _md("alerts", "알림 규칙", "슬랙 대신 메일"),
}


def _zip(path, files=FILES, root=ROOT, when=(2026, 11, 9, 0, 22, 18)):
    with zipfile.ZipFile(path, "w") as z:
        for rel, text in files.items():
            info = zipfile.ZipInfo(f"{root}/{rel}" if root else rel, date_time=when)
            z.writestr(info, text.encode("utf-8"))
    return path


def test_split_front_strips_quotes():
    meta, body = split_front(FILES["areas/homelab.md"])
    assert meta == {"name": "homelab", "description": "라즈베리파이 홈랩"}
    assert body.strip() == "- 그라파나로 온도를 본다"


def test_detect(tmp_path):
    z = _zip(tmp_path / "claude-memory-2026-11-09.zip")
    assert ClaudeMemoryMdImporter().detect(z)
    assert not ClaudeExportImporter().detect(z)
    assert detect(z).name == "claude-ai-memory-md"
    assert ClaudeMemoryMdImporter().detect(_zip(tmp_path / "flat.zip", root=""))   # 감싼 폴더 없이도


def test_not_detected_for_other_md_zips(tmp_path):
    imp = ClaudeMemoryMdImporter()
    skill = {"SKILL.md": _md("obsidian-log", "일지 스킬", "본문"), "references/rules.md": _md("r", "d", "x")}
    assert not imp.detect(_zip(tmp_path / "skill.zip", skill, root="obsidian-log"))
    notes = {"2026/11/2026-11-09.md": "# 일지\n", "README.md": "# 노트\n"}
    assert not imp.detect(_zip(tmp_path / "notes.zip", notes, root="vault"))
    mixed = dict(FILES, **{"areas/pic.png": "x"})
    assert not imp.detect(_zip(tmp_path / "mixed.zip", mixed))
    no_front = {k: "그냥 본문\n" for k in FILES}
    assert not imp.detect(_zip(tmp_path / "nofront.zip", no_front))
    for cz in make_export_zips(tmp_path / "claude"):
        assert not imp.detect(cz)


def test_convert_same_shape_as_official_memory(tmp_path):
    convs = list(ClaudeMemoryMdImporter().iter_conversations(_zip(tmp_path / "m.zip")))
    assert len(convs) == 1
    c = convs[0]
    assert c.conv_id == "claude-ai-memory:main" and c.source == "claude-ai-memory"
    labels = [m.label for m in c.messages]
    assert "메모리 파일: /areas/homelab.md" in labels
    assert "메모리 파일: /projects/사내 로그 수집/areas/alerts.md" in labels
    home = next(m for m in c.messages if m.label.endswith("/areas/homelab.md"))
    assert home.text == "> 라즈베리파이 홈랩\n\n- 그라파나로 온도를 본다"
    assert c.updated.isoformat() == "2026-11-09T00:22:18+00:00"


def test_core_import_newer_memory_wins(core_env, tmp_path):
    # 공식 JSON(2026-10-25) 먼저, 더 새 md 묶음(2026-11-09)이 덮어씀
    for z in make_export_zips(tmp_path / "claude"):
        if z.stem.startswith("memories"):
            assert core_env.import_zip(z).result == "ok"
    last = core_env.state.get("last_zip_import")
    out =core_env.import_zip(_zip(tmp_path / "claude-memory-2026-11-09.zip"))
    assert out.result == "ok" and out.importer == "claude-ai-memory-md" and out.counts["changed"] == 1
    text = (core_env.archive_dir / "claude-ai" / "memories.md").read_text("utf-8")
    assert "소설 한 권" in text
    hits = search("그라파나 src:memory", db_path=core_env.index.db_path)
    assert [h.conv_id for h in hits] == ["claude-ai-memory:main"]
    # 더 오래된 md 묶음은 덮어쓰지 않음
    old = _zip(tmp_path / "claude-memory-2026-10-01.zip", {"areas/x.md": _md("x", "옛것", "옛 내용")},
               root="claude-memory-2026-10-01", when=(2026, 10, 1, 0, 0, 0))
    assert core_env.import_zip(old).counts["older"] == 1
    assert core_env.state.get("last_zip_import") == last   # 메모리만 받은 것은 대화 내보내기 알림 기준을 바꾸지 않음
