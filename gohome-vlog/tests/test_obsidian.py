from datetime import date

import pytest

from app import obsidian

DAY = date(2026, 11, 5)


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    return vault


def test_export_path_default(tmp_path):
    assert obsidian.export_path(tmp_path, "gohome", DAY) == tmp_path / "gohome" / "2026-11-05.md"


@pytest.mark.parametrize("folder", [str(__import__("pathlib").Path.cwd().resolve()), "../out", "a/../../out"])
def test_export_path_rejects_outside(tmp_path, folder):
    with pytest.raises(ValueError):
        obsidian.export_path(tmp_path, folder, DAY)


def test_not_a_vault(tmp_path):
    with pytest.raises(ValueError, match="Obsidian 볼트가 아닙니다"):
        obsidian.write_export(tmp_path, "gohome", DAY, "x")
    with pytest.raises(ValueError):
        obsidian.write_export(tmp_path / "missing", "gohome", DAY, "x")


def test_write_export_changes(tmp_path):
    vault = make_vault(tmp_path)
    assert obsidian.write_export(vault, "gohome", DAY, "본문") is True
    path = obsidian.export_path(vault, "gohome", DAY)
    assert path.read_text(encoding="utf-8") == obsidian.render("본문")
    assert obsidian.write_export(vault, "gohome", DAY, "본문") is False
    assert obsidian.write_export(vault, "gohome", DAY, "바뀐 본문") is True
    assert "바뀐 본문" in path.read_text(encoding="utf-8")


def test_render():
    out = obsidian.render("### 요약\n내용")
    assert out.startswith("%% gohome-vlog가 자동으로 만드는 파일입니다. 직접 고치면 덮어써집니다. %%\n\n")
    assert "### 요약\n내용" in out
    assert out.endswith("내용\n") and not out.endswith("\n\n")


def test_delete_export(tmp_path):
    vault = make_vault(tmp_path)
    obsidian.write_export(vault, "gohome", DAY, "x")
    path = obsidian.export_path(vault, "gohome", DAY)
    obsidian.delete_export(vault, "gohome", DAY)
    assert not path.exists()
    obsidian.delete_export(vault, "gohome", DAY)  # 없어도 예외 없음
