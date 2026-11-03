import subprocess

import pytest

from conftest import build_epub, quiet
from x3book import convert as cv
from x3book.check import check


def test_missing_calibre_gives_install_hint(tmp_path, monkeypatch):
    src = tmp_path / "b.azw3"
    src.write_bytes(b"x")
    monkeypatch.setattr(cv, "find_ebook_convert", lambda: None)
    with pytest.raises(SystemExit) as e:
        cv.convert(str(src), log=quiet)
    assert "Calibre" in str(e.value) and "calibre-ebook.com" in str(e.value)


def test_rejects_other_extensions(tmp_path):
    with pytest.raises(SystemExit):
        cv.convert(str(tmp_path / "x.txt"), log=quiet)


def test_convert_runs_ebook_convert_then_tune(tmp_path, monkeypatch):
    src = tmp_path / "book.mobi"
    src.write_bytes(b"x")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        build_epub(cmd[2])  # pretend Calibre wrote the EPUB
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cv, "find_ebook_convert", lambda: "ebook-convert")
    monkeypatch.setattr(cv.subprocess, "run", fake_run)
    out = cv.convert(str(src), log=quiet)
    assert calls and calls[0][:2] == ["ebook-convert", str(src)]
    assert out == str(tmp_path / "book [X3].epub")
    assert not any("progressive" in p for p in check(out, log=quiet))


def test_drm_failure_message(tmp_path, monkeypatch):
    src = tmp_path / "book.azw3"
    src.write_bytes(b"x")
    monkeypatch.setattr(cv, "find_ebook_convert", lambda: "ebook-convert")
    monkeypatch.setattr(cv.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "DRMError: book is encrypted"))
    with pytest.raises(SystemExit) as e:
        cv.convert(str(src), log=quiet)
    assert "DRM" in str(e.value)
