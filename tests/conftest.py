"""Synthetic EPUB builder: no book content, everything is generated in tmp."""
import io
import zipfile

import pytest
from PIL import Image

CONTAINER = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
             '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
             '</rootfiles></container>')


def jpeg_bytes(size, progressive=False):
    buf = io.BytesIO()
    Image.effect_noise(size, 60).convert("RGB").save(buf, "JPEG", quality=90, progressive=progressive)
    return buf.getvalue()


def img_bytes(size, fmt):
    buf = io.BytesIO()
    Image.effect_noise(size, 60).convert("RGB").save(buf, fmt)
    return buf.getvalue()


def page(title, body):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><title>%s</title>'
            '<link rel="stylesheet" href="style.css" type="text/css"/></head><body>%s</body></html>' % (title, body))


def build_epub(path, extra_files=None, extra_manifest="", chapters=None, css=b"p { margin: 0; }\n"):
    """Default book: one chapter file with two headings + a progressive 1600px JPEG, `&emsp;`, a layout table."""
    chapters = chapters or {
        "ch1.xhtml": page("Book", (
            '<h1 id="a">Alpha</h1><p>Alpha text&emsp;with an HTML entity.</p>'
            '<p><img src="images/big.jpg" alt=""/></p>'
            '<h1 id="b">Beta</h1><p>Beta text.</p>'
            '<p id="gamma">GAMMA starts here</p><p>Gamma text.</p>'
            '<table><tr><td>cell one</td><td>cell two</td></tr></table>')),
        "ch2.xhtml": page("Two", '<h1 id="d">Delta</h1><p>Delta text.</p>'),
    }
    files = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": CONTAINER.encode(),
        "OEBPS/style.css": css,
        "OEBPS/images/big.jpg": jpeg_bytes((1600, 1200), progressive=True),
    }
    for name, body in chapters.items():
        files["OEBPS/" + name] = body.encode("utf8")
    files.update(extra_files or {})
    man = "".join('<item id="c%d" href="%s" media-type="application/xhtml+xml"/>' % (i, n) for i, n in enumerate(chapters))
    spine = "".join('<itemref idref="c%d"/>' % i for i in range(len(chapters)))
    opf = ('<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test</dc:title><dc:language>en</dc:language>'
           '<dc:identifier id="id">urn:test</dc:identifier></metadata><manifest>'
           '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
           '<item id="css" href="style.css" media-type="text/css"/>'
           '<item id="big" href="images/big.jpg" media-type="image/jpeg"/>' + man + extra_manifest +
           '</manifest><spine toc="ncx">' + spine + '</spine></package>')
    ncx = ('<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           '<head><meta name="dtb:depth" content="1"/></head><docTitle><text>Test</text></docTitle><navMap>'
           '<navPoint id="n1" playOrder="1"><navLabel><text>ALPHA</text></navLabel><content src="ch1.xhtml#a"/></navPoint>'
           '<navPoint id="n2" playOrder="2"><navLabel><text>Beta</text></navLabel><content src="ch1.xhtml#b"/></navPoint>'
           '<navPoint id="n3" playOrder="3"><navLabel><text>Delta</text></navLabel><content src="ch2.xhtml#d"/></navPoint>'
           '</navMap></ncx>')
    files["OEBPS/content.opf"] = opf.encode()
    files["OEBPS/toc.ncx"] = ncx.encode()
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", files["mimetype"], compress_type=zipfile.ZIP_STORED)
        for n, d in files.items():
            if n != "mimetype":
                z.writestr(n, d, compress_type=zipfile.ZIP_DEFLATED)
    return str(path)


@pytest.fixture
def epub(tmp_path):
    return build_epub(tmp_path / "in.epub")


def read(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}, z.namelist()


def quiet(*a, **k):
    pass
