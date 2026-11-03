import io
import re
import zipfile

import pytest
from PIL import Image

from conftest import build_epub, page, quiet, read
from x3book.check import check
from x3book.tune import tune


def ncx_labels(data):
    return re.findall(r"<text>([^<]*)</text>", data["OEBPS/toc.ncx"].decode())[1:]


def test_images_and_zip_layout(epub, tmp_path):
    out = str(tmp_path / "out.epub")
    tune(epub, out, log=quiet)
    data, _ = read(out)
    im = Image.open(io.BytesIO(data["OEBPS/images/big.jpg"]))
    assert max(im.size) == 792
    assert im.mode == "L"
    assert not im.info.get("progressive") and not im.info.get("progression")
    with zipfile.ZipFile(out) as z:
        first = z.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED


def test_entities_become_numeric(epub, tmp_path):
    out = str(tmp_path / "out.epub")
    tune(epub, out, log=quiet)
    data, _ = read(out)
    assert b"&emsp;" not in data["OEBPS/ch1.xhtml"]
    assert b"&#8195;" in data["OEBPS/ch1.xhtml"]


def test_only_text_free_tables_are_unwrapped(tmp_path):
    body = ('<h1 id="a">A</h1><table><tr><td><img src="images/big.jpg"/></td></tr></table>'
            '<table><tr><td>real data</td></tr></table>')
    src = build_epub(tmp_path / "t.epub", chapters={"c.xhtml": page("T", body)})
    out = str(tmp_path / "out.epub")
    tune(src, out, log=quiet)
    data, _ = read(out)
    assert data["OEBPS/c.xhtml"].count(b"<table") == 1
    assert b"real data" in data["OEBPS/c.xhtml"]


def test_relabel_and_drop(epub, tmp_path):
    out = str(tmp_path / "out.epub")
    tune(epub, out, {"relabel": {"ALPHA": "Alpha"}, "drop": ["Delta"]}, log=quiet)
    data, _ = read(out)
    assert ncx_labels(data) == ["Alpha", "Beta"]


def test_split_gives_each_chapter_its_own_file(epub, tmp_path):
    out = str(tmp_path / "out.epub")
    plan = {"split": [{"file": "ch1.xhtml", "before_id": "b"}, {"file": "ch1.xhtml", "before_text": "GAMMA"}],
            "relabel": {"Beta": "Beta (tuned)"}}
    tune(epub, out, plan, log=quiet)
    data, names = read(out)
    assert len([n for n in names if n.startswith("OEBPS/ch1")]) == 3
    toc = data["OEBPS/toc.ncx"].decode()
    srcs = re.findall(r'<content src="([^"]+)"', toc)
    assert len({s.split("#")[0] for s in srcs}) == 3  # one file per TOC entry
    assert "Beta (tuned)" in toc
    assert check(out, log=quiet) == []


def test_missing_label_is_an_error(epub, tmp_path):
    with pytest.raises(SystemExit):
        tune(epub, str(tmp_path / "o.epub"), {"relabel": {"Nope": "x"}}, log=quiet)


def test_chapters_from_heading_paragraphs(tmp_path):
    body = ('<p class="ch">1</p><p class="ch">FIRST ONE</p><p>text</p>'
            '<p class="ch">SECOND</p><p>more</p>')
    src = build_epub(tmp_path / "c.epub", chapters={"only.xhtml": page("T", body)})
    out = str(tmp_path / "o.epub")
    tune(src, out, {"chapters_from": {"class": "ch"}}, log=quiet)
    data, _ = read(out)
    assert ncx_labels(data) == ["1. First one", "Second"]
    assert check(out, log=quiet) == []
