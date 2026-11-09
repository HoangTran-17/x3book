"""Regression against EPUBs built by the old local scripts (x3_epub.py and the anthology script).

Local only. The repo is public and CI has no books, so no book names or content live here.
Set X3BOOK_LOCAL_BOOKS to the books folder; the other variables are paths relative to it
(or absolute). A test skips when its variables are not set.
  azw3:  X3BOOK_AZW3_SRC (source .azw3), X3BOOK_AZW3_OLD (old [X3] EPUB of it)
  merge: X3BOOK_MERGE_PLAN (x3book merge plan .json), X3BOOK_MERGE_OLD (old [X3] EPUB of it)
"""
import io
import os
import re

import pytest
from PIL import Image

from conftest import quiet
from x3book.check import check
from x3book.core import MAX_SIDE, N, XHTML_NS, Book, norm, parse_xml

BOOKS = os.environ.get("X3BOOK_LOCAL_BOOKS")
pytestmark = pytest.mark.skipif(not BOOKS, reason="X3BOOK_LOCAL_BOOKS not set (needs local books)")


def need(path):
    if not os.path.exists(path):
        pytest.skip("missing local file: %s" % path)
    return path


def local(var):
    rel = os.environ.get(var)
    if not rel:
        pytest.skip("%s not set" % var)
    return need(os.path.join(BOOKS, rel))


def metrics(path):
    b = Book(path)
    spine = b.spine()
    ncx = b.ncx_path()
    toc = []
    for np_ in parse_xml(b.data[ncx]).iterfind(".//n:navPoint", N):
        target = b.full(np_.find("n:content", N).get("src").partition("#")[0], ncx)
        toc.append((norm(np_.findtext("n:navLabel/n:text", namespaces=N)), spine.index(target)))
    words = []
    for f in spine:
        body = parse_xml(b.data[f]).find(".//{%s}body" % XHTML_NS)
        words.append(len(norm("".join(body.itertext())).split()))
    images = []
    for n in b.order:
        if n.lower().endswith((".jpg", ".jpeg", ".png")):
            im = Image.open(io.BytesIO(b.data[n]))
            images.append((im.format, im.size, im.mode, bool(im.info.get("progressive") or im.info.get("progression"))))
    meta = {k: re.findall(r"<dc:%s\b[^>]*>(.*?)</dc:%s>" % (k, k), b.opf, re.S) for k in ("title", "creator", "language")}
    return {"spine": len(spine), "toc": toc, "words": words, "images": sorted(images), "meta": meta,
            "problems": check(path, log=quiet)}


def assert_same(new_path, old_path):
    new, old = metrics(new_path), metrics(old_path)
    assert new["problems"] == []
    assert old["problems"] == []  # reference sanity: a broken old build is not a baseline
    assert new["spine"] == old["spine"]
    assert new["toc"] == old["toc"]  # labels and the spine file each label points at
    # Exact match on purpose: as of 2026-11-09 both pipelines give the same text per spine
    # file (measured), so any drift is a behaviour change to look at, not noise.
    diff = [(i, a, b) for i, (a, b) in enumerate(zip(new["words"], old["words"])) if a != b]
    assert not diff, "word count per spine file (index, new, old): %s" % diff[:10]
    # Image names may differ (merge names part covers by index, the old script by source),
    # so compare format / size / mode / progressive as a multiset.
    assert new["images"] == old["images"]
    assert not any(prog for *_, prog in new["images"])
    assert all(max(size) <= MAX_SIDE for _, size, _, _ in new["images"])
    assert new["meta"] == old["meta"]
    return new


def test_azw3_matches_old_x3_epub(tmp_path):
    pytest.importorskip("mobi")
    from x3book.tune import tune
    src = local("X3BOOK_AZW3_SRC")
    old = local("X3BOOK_AZW3_OLD")
    out = str(tmp_path / "azw3.epub")
    # same plan as the old local plan for this book (no book text in it)
    tune(src, out, {"chapters_from": {"class": "block_", "heading_tag": "h2"}}, log=quiet)
    # dc:identifier and the font obfuscation key are random per KindleUnpack run; the metrics skip both
    m = assert_same(out, old)
    assert len(m["toc"]) > 1


def test_merge_matches_old_epub(tmp_path):
    from x3book.merge import merge
    plan = local("X3BOOK_MERGE_PLAN")
    old = local("X3BOOK_MERGE_OLD")
    out = str(tmp_path / "merge.epub")
    merge(plan, out, log=quiet)
    m = assert_same(out, old)
    assert len(m["toc"]) > 1
