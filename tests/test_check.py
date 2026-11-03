from conftest import quiet
from x3book.check import check
from x3book.tune import tune


def test_check_flags_progressive_and_entity(epub):
    problems = check(epub, log=quiet)
    assert any("progressive" in p for p in problems)
    assert any("expat" in p for p in problems)


def test_check_flags_footer_hiding(epub, tmp_path):
    # Alpha and Beta share ch1.xhtml: the CrossVi footer only shows the first
    out = str(tmp_path / "o.epub")
    tune(epub, out, log=quiet)
    assert any("hides TOC entries" in p for p in check(out, log=quiet))


def test_check_passes_after_split(epub, tmp_path):
    out = str(tmp_path / "o.epub")
    tune(epub, out, {"split": [{"file": "ch1.xhtml", "before_id": "b"}]}, log=quiet)
    assert check(out, log=quiet) == []


def test_check_cli_exit_code(epub, tmp_path):
    from x3book.cli import main
    assert main(["check", epub]) == 1
    out = str(tmp_path / "o.epub")
    assert main(["tune", epub, out]) == 0
    assert "hides" in "".join(check(out, log=quiet))
