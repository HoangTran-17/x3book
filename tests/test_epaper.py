import io

from PIL import Image

from conftest import build_epub, img_bytes, quiet, read
from x3book.epaper import Extras, clean_css, strip_data_uris
from x3book.tune import tune


def test_clean_css_removes_layout_but_keeps_text_transform():
    css = ("p { float: left; text-transform: uppercase; color: #000 }\n"
           ".a { display: flex; position: absolute; top: 0 }\n"
           ".b { transform: rotate(3deg); -webkit-transform: none; margin: 0 }\n"
           "@font-face { font-family: X; src: url(x.ttf); }\n"
           "@keyframes k { from { opacity: 0 } to { opacity: 1 } }\n"
           "h1 { margin: 1em }")
    out = clean_css(css)
    assert "float" not in out and "flex" not in out and "absolute" not in out
    assert "text-transform: uppercase" in out and "-webkit-transform" in out
    assert "@font-face" not in out and "@keyframes" not in out
    assert "h1 { margin: 1em }" in out and "margin: 0" in out


def test_strip_data_uris():
    assert strip_data_uris('<img src="data:image/png;base64,AAAA"/>') == '<img src="#"/>'


def test_strip_fonts_and_manifest(tmp_path):
    src = build_epub(tmp_path / "f.epub", extra_files={"OEBPS/fonts/a.ttf": b"x" * 10},
                     extra_manifest='<item id="f1" href="fonts/a.ttf" media-type="font/ttf"/>')
    out = str(tmp_path / "o.epub")
    tune(src, out, extras=Extras(strip_fonts=True), log=quiet)
    data, names = read(out)
    assert "OEBPS/fonts/a.ttf" not in names
    assert b"a.ttf" not in data["OEBPS/content.opf"]


def test_convert_webp_and_gif_to_baseline_jpeg(tmp_path):
    chapters = {"c.xhtml": '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
                           '<body><h1 id="a">A</h1><p><img src="images/w.webp"/><img src="images/g.gif"/></p></body></html>'}
    src = build_epub(tmp_path / "w.epub", chapters=chapters,
                     extra_files={"OEBPS/images/w.webp": img_bytes((900, 600), "WEBP"),
                                  "OEBPS/images/g.gif": img_bytes((100, 80), "GIF")},
                     extra_manifest='<item id="w" href="images/w.webp" media-type="image/webp"/>'
                                    '<item id="g" href="images/g.gif" media-type="image/gif"/>')
    out = str(tmp_path / "o.epub")
    tune(src, out, extras=Extras(convert_images=True), log=quiet)
    data, names = read(out)
    assert "OEBPS/images/w.jpg" in names and "OEBPS/images/g.jpg" in names
    assert "OEBPS/images/w.webp" not in names and "OEBPS/images/g.gif" not in names
    assert b"w.jpg" in data["OEBPS/c.xhtml"] and b"g.gif" not in data["OEBPS/c.xhtml"]
    assert b"image/webp" not in data["OEBPS/content.opf"] and b"image/gif" not in data["OEBPS/content.opf"]
    im = Image.open(io.BytesIO(data["OEBPS/images/w.jpg"]))
    assert im.format == "JPEG" and max(im.size) <= 792 and not im.info.get("progressive")


def test_extras_off_by_default(tmp_path):
    src = build_epub(tmp_path / "d.epub", css=b"p { float: left; }")
    out = str(tmp_path / "o.epub")
    tune(src, out, log=quiet)
    data, _ = read(out)
    assert b"float" in data["OEBPS/style.css"]
