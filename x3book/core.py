"""Shared EPUB plumbing: zip container, OPF/NCX helpers, XML parsing."""
import html
import html.entities
import io
import posixpath
import re
import unicodedata
import zipfile
from urllib.parse import unquote

from lxml import etree

MAX_SIDE = 792  # X3 panel is 528x792; 792 keeps full detail in landscape reading too
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
XHTML_NS = "http://www.w3.org/1999/xhtml"
N = {"n": NCX_NS, "h": XHTML_NS}
CONTENT_RE = re.compile(r"\.(x?html?)$", re.I)


def norm(s):
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", s or "").strip())


def text_of(el):
    return norm("".join(el.itertext()))


class Book:
    """In-memory EPUB: every zip entry as bytes plus the OPF as text."""

    def __init__(self, path):
        with zipfile.ZipFile(path) as z:
            self.order = [i.filename for i in z.infolist()]
            self.data = {n: z.read(n) for n in self.order}
        cont = self.data["META-INF/container.xml"].decode("utf8")
        self.opf_path = re.search(r'full-path="([^"]+)"', cont).group(1)
        self.base = posixpath.dirname(self.opf_path)
        self.opf = self.data[self.opf_path].decode("utf8")
        self.part_of = {}  # split part -> original file

    # ---- paths ----
    def full(self, rel, frm=None):
        d = posixpath.dirname(frm) if frm else self.base
        return posixpath.normpath(posixpath.join(d, unquote(html.unescape(rel))))

    def rel(self, full, frm):
        return posixpath.relpath(full, posixpath.dirname(frm))

    def manifest(self):
        out = {}
        for m in re.finditer(r"<item\b[^>]*>", self.opf):
            a = dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(0)))
            if "href" in a:
                out[a.get("id")] = (self.full(a["href"]), a, m.group(0))
        return out

    def spine(self):
        man = self.manifest()
        return [man[i][0] for i in re.findall(r'<itemref\b[^>]*idref="([^"]+)"', self.opf) if i in man]

    def ncx_path(self):
        for full, a, _ in self.manifest().values():
            if a.get("media-type") == "application/x-dtbncx+xml":
                return full
        return None

    def nav_path(self):
        for full, a, _ in self.manifest().values():
            if "nav" in a.get("properties", "").split():
                return full
        return None

    def save(self, out):
        """Write the EPUB with `mimetype` first and stored (EPUB OCF)."""
        self.data[self.opf_path] = self.opf.encode("utf8")
        with zipfile.ZipFile(out, "w") as z:
            z.writestr(zipfile.ZipInfo("mimetype"), self.data["mimetype"], compress_type=zipfile.ZIP_STORED)
            for n in self.order:
                if n != "mimetype":
                    z.writestr(n, self.data[n], compress_type=zipfile.ZIP_DEFLATED)


def html_entities_to_numeric(b):
    # XHTML files often use HTML-only entities (&nbsp; &emsp;) that an XML parser rejects
    def sub(m):
        name = m.group(1)
        if name in ("amp", "lt", "gt", "quot", "apos") or name not in html.entities.name2codepoint:
            return m.group(0)
        return "&#%d;" % html.entities.name2codepoint[name]
    return re.sub(r"&([A-Za-z][A-Za-z0-9]*);", sub, b.decode("utf8")).encode("utf8")


def parse_xml(b):
    b = html_entities_to_numeric(b)
    return etree.parse(io.BytesIO(b), etree.XMLParser(huge_tree=True, resolve_entities=False, remove_blank_text=False))


def dump_xml(tree):
    buf = io.BytesIO()
    tree.write(buf, xml_declaration=True, encoding="utf-8")
    return buf.getvalue()
