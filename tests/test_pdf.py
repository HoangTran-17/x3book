import re
import zipfile

from x3book.pdf import write_epub


def test_cover_id_unique_with_part_covers(tmp_path):
    # merge adds per-part covers (images/part1_cover.jpg); only images/cover.jpg is the book cover
    out = str(tmp_path / "o.epub")
    images = {"images/cover.jpg": b"\xff\xd8", "images/part1_cover.jpg": b"\xff\xd8", "images/part2_cover.jpg": b"\xff\xd8"}
    write_epub(out, {"title": "T"}, [{"name": "text/c1.xhtml", "body": ["<p>x</p>"]}], [(1, "C1", "text/c1.xhtml")], images)
    opf = zipfile.ZipFile(out).read("OEBPS/content.opf").decode("utf-8")
    ids = re.findall(r'<item id="([^"]+)"', opf)
    assert len(ids) == len(set(ids))
    assert re.search(r'<item id="cover-img" href="images/cover.jpg"', opf)
