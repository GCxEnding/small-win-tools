"""기대 md 초안 생성기. 만든 뒤 사람이 직접 읽어 확인하고 커밋한다 (테스트가 이 파일과 완전 일치를 본다).

  python tests/fixtures/make_expected.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))

from conftest import FIXTURES, KST, TODAY, make_export_zips  # noqa: E402

from app.archive import Archive, render  # noqa: E402
from app.importers.claude_code import parse_session  # noqa: E402
from app.importers.claude_export import ClaudeExportImporter  # noqa: E402
from app.redact import Redactor  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp())
    exp = FIXTURES / "claude_export_small.expected"
    shutil.rmtree(exp, ignore_errors=True)
    exp.mkdir()
    a = Archive(exp, KST, Redactor(), today=lambda: TODAY)
    imp = ClaudeExportImporter()
    for z in make_export_zips(tmp / "zips"):
        if imp.detect(z):
            for c in imp.iter_conversations(z):
                a.write(c)
    c = parse_session(FIXTURES / "code_session.jsonl")
    (FIXTURES / "code_session.expected.md").write_text(render(c, KST, redact=Redactor()), encoding="utf-8",
                                                       newline="\n")
    shutil.rmtree(tmp, ignore_errors=True)
    print("expected written")


if __name__ == "__main__":
    main()
