import json
import re

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
    assert check(str(built[0]), log=quiet) == []
    txt = tmp_path / "src.txt"
    assert main(["flashbook", "source", str(built[0]), str(txt)]) == 0
    assert "Điều thứ nhất" in txt.read_text(encoding="utf-8")


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
