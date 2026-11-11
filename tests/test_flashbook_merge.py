import io
import json
import re

from PIL import Image

from conftest import quiet, read
from x3book import flashbook
from x3book.check import check
from x3book.cli import main

BOOK_MD = """---
title: Sample Book
subtitle: A test
author: Jane Doe
source_pages: 200
---

## Về cuốn sách
Một đoạn giới thiệu.

## Về tác giả
Tác giả giả định.

## Ý 1: Điều thứ nhất
Đoạn một có ***điểm nhấn***.

- ý gạch đầu dòng

## Thông điệp chính
Kết luận ngắn.
"""


def test_flashbook_build_stats_source(tmp_path, capsys):
    md = tmp_path / "book.md"
    md.write_text(BOOK_MD, encoding="utf-8")
    assert main(["flashbook", "stats", str(md)]) == 0
    assert capsys.readouterr().out.strip()
    out = tmp_path / "out"
    out.mkdir()
    assert main(["flashbook", "build", str(md), str(out)]) == 0
    built = list(out.glob("*.epub"))
    assert len(built) == 1
    # EPUB 2 forbids the HTML5 doctype (EPUBCheck HTM-004); omitting it is valid.
    data, _ = read(str(built[0]))
    assert 'version="2.0"' in data["OEBPS/content.opf"].decode()
    assert not any(b"<!DOCTYPE" in v for k, v in data.items() if k.endswith(".xhtml"))
    assert check(str(built[0]), log=quiet) == []
    txt = tmp_path / "src.txt"
    assert main(["flashbook", "source", str(built[0]), str(txt)]) == 0
    assert "Điều thứ nhất" in txt.read_text(encoding="utf-8")


def test_flashbook_build_std(tmp_path):
    md = tmp_path / "book.md"
    md.write_text(BOOK_MD.replace("source_pages: 200", "source_pages: 200\nsource: Flashbook X3")
                  .replace("- ý gạch đầu dòng", "- ý một\n\n- ý hai"), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    assert main(["flashbook", "build", str(md), str(out), "--target", "std"]) == 0
    built = list(out.glob("*.epub"))
    assert [p.name for p in built] == ["Sample Book - Jane Doe [Flashbook].epub"]
    assert check(str(built[0]), log=quiet) == []
    data, _ = read(str(built[0]))
    opf = data["OEBPS/content.opf"].decode()
    for want in ('version="3.0"', 'properties="nav"', 'properties="cover-image"'):
        assert want in opf
    assert re.search(r'<meta property="dcterms:modified">\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ</meta>', opf)
    assert data["OEBPS/nav.xhtml"].decode().count("<li><a href=") == data["OEBPS/toc.ncx"].decode().count("<navPoint")
    pages = "".join(v.decode() for k, v in data.items() if k.endswith(".xhtml"))
    assert all(b"<!DOCTYPE html>" in v for k, v in data.items() if k.endswith(".xhtml"))
    assert "<ul>\n<li>ý một</li>\n<li>ý hai</li>\n</ul>" in pages
    assert "<strong><em>điểm nhấn</em></strong>" in pages
    assert '<p class="sub">A test</p>' in pages and "<h4" not in pages
    assert "— Flashbook</p>" in pages
    assert Image.open(io.BytesIO(data["OEBPS/cover.jpg"])).size == (1600, 2400)


def test_merge_markdown_parts(tmp_path):
    (tmp_path / "a.md").write_text("## One\nText one.\n\n## Two\nText two.\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("## Solo\nOnly.\n", encoding="utf-8")
    plan = {"title": "Joined", "author": "Anon", "lang": "en", "out": "out/joined.epub",
            "cover": {"heading": ["JOINED"], "subtitle": "demo"},
            "parts": [{"type": "md", "file": "a.md", "labels": ["A - One", "A - Two"]},
                      {"type": "md", "file": "b.md", "labels": ["B - Solo"]}]}
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    assert main(["merge", str(p)]) == 0
    out = tmp_path / "out" / "joined.epub"
    data, _ = read(str(out))
    labels = re.findall(r"<text>([^<]*)</text>", data["OEBPS/toc.ncx"].decode())
    for want in ("A - One", "A - Two", "B - Solo"):
        assert want in labels
    assert check(str(out), log=quiet) == []
