"""Flashbook: a ~30-minute summary of a non-fiction book, laid out for the Xteink X3.

  x3book flashbook build  <book.md> <out.epub|folder> [--target x3|std]   source .md -> EPUB
      x3 (default): EPUB 2 tuned for CrossVi on the Xteink X3, "[Flashbook X3].epub"
      std: EPUB 3 + nav + NCX for phone / PC / Kindle apps, "[Flashbook].epub"
  x3book flashbook stats  <book.md>                      length/structure check
  x3book flashbook source <book.epub> <out.txt>          full book -> plain text for the summary writer

Source format (.md):
  front matter "key: value" lines between "---" fences, then "## <section>" blocks.
  Front matter keys: title, subtitle, author, source_pages, read_minutes, source.
  The 4 intro sections and "Thông điệp chính" have fixed names; every other "##" is a key idea.
  Paragraphs are separated by a blank line, "- " starts a bullet, ***text*** is a highlight.
"""
import html
import io
import os
import re
import time
import unicodedata
import uuid
import zipfile

from .fonts import load_font

INTRO = ["Cuốn sách này nói về cái gì?", "Ai nên đọc cuốn sách này?", "Về tác giả", "Thời gian đọc"]
FINAL = "Thông điệp chính"
WPM = 250  # ~7,400 words = a 30 minute read


def nfc(s):
    return unicodedata.normalize("NFC", s)


# ---------------------------------------------------------------- source (book -> plain text for the writer)
def source(epub, out):
    """Dump an EPUB as plain text, one block per spine file, headed by its footer/TOC label."""
    import posixpath, zipfile as zf
    from urllib.parse import unquote
    z = zf.ZipFile(epub)
    opf_path = re.search(r'full-path="([^"]+)"', z.read("META-INF/container.xml").decode()).group(1)
    opf = z.read(opf_path).decode("utf8")
    base = posixpath.dirname(opf_path)
    man = {}
    for m in re.finditer(r"<item\b[^>]*>", opf):
        a = dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(0)))
        man[a.get("id")] = (posixpath.normpath(posixpath.join(base, unquote(a.get("href", "")))), a.get("media-type", ""))
    spine = [man[i][0] for i in re.findall(r'<itemref\b[^>]*idref="([^"]+)"', opf) if i in man]
    labels = {}
    ncx = next((p for p, t in man.values() if t == "application/x-dtbncx+xml"), None)
    if ncx:
        t = z.read(ncx).decode("utf8")
        for lab, src in re.findall(r"<navLabel>\s*<text>([^<]*)</text>\s*</navLabel>\s*<content src=\"([^\"]+)\"", t, re.S):
            f = posixpath.normpath(posixpath.join(posixpath.dirname(ncx), unquote(src.split("#")[0])))
            labels.setdefault(f, html.unescape(re.sub(r"\s+", " ", lab)).strip())
    parts, total, last = [], 0, "-"
    for f in spine:
        s = z.read(f).decode("utf8", "replace")
        body = s.split("<body", 1)[-1].split(">", 1)[-1]
        body = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", body)
        body = re.sub(r"(?i)</?(p|div|h[1-6]|li|br|blockquote|tr)\b[^>]*>", "\n", body)
        text = nfc(html.unescape(re.sub(r"<[^>]+>", "", body)))
        text = "\n".join(l.strip() for l in text.splitlines() if l.strip())
        if not text:
            continue
        n = len(re.findall(r"\w+", text))
        total += n
        last = labels.get(f, last)  # an unlabeled file continues the previous chapter, as on the device
        parts.append("=== [%s] (%d words)\n%s\n" % (last, n, text))
    open(out, "w", encoding="utf-8", newline="\n").write("\n".join(parts))
    print("source: %d parts, %d words -> %s" % (len(parts), total, out))


# ---------------------------------------------------------------- parse / stats
def parse(path):
    raw = nfc(open(path, encoding="utf-8-sig").read()).replace("\r\n", "\n")  # tolerate files saved by Notepad/PowerShell
    fm, body = re.match(r"---\n(.*?)\n---\n(.*)", raw, re.S).groups()
    meta = dict(re.findall(r"^(\w+):[ \t]*(.*)$", fm, re.M))
    sections = []
    for m in re.finditer(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", body, re.S | re.M):
        paras = [p.strip() for p in re.split(r"\n\s*\n", m.group(2)) if p.strip()]
        sections.append((m.group(1).strip(), paras))
    return meta, sections


def words(s):
    return len(re.findall(r"\w+", s.replace("***", "")))


def stats(path):
    meta, sections = parse(path)
    total = sum(words(" ".join(p)) for _, p in sections)
    ideas = [(t, p) for t, p in sections if t not in INTRO and t != FINAL]
    print("title        :", meta.get("title"), "|", meta.get("author"))
    print("total words  : %d  (~%d min at %d wpm)" % (total, round(total / WPM), WPM))
    print("intro        :", ", ".join("%s %dw" % (t, words(" ".join(p))) for t, p in sections if t in INTRO))
    print("key ideas    : %d" % len(ideas))
    for k, (t, p) in enumerate(ideas, 1):
        hl = sum(len(re.findall(r"\*\*\*(.+?)\*\*\*", x)) for x in p)
        print("  %2d. %-58s %4dw %2dp hl%d" % (k, t[:58], words(" ".join(p)), len(p), hl))
    fin = [p for t, p in sections if t == FINAL]
    print("final        :", "%dw" % words(" ".join(fin[0])) if fin else "MISSING")


# ---------------------------------------------------------------- build
# CrossVi lets the reader's paragraph-alignment setting override text-align on <p>
# (BlockStyle.h fromCssStyle), but headings keep theirs - so centred lines are h4.
CSS = """body { margin: 0; }
p { margin: 0 0 0.6em 0; text-indent: 1em; text-align: justify; }
h1 { text-align: center; margin: 0.6em 0 0.2em 0; }
h4.sub { text-align: center; font-style: italic; margin: 0 0 0.3em 0; }
h4.meta { text-align: center; margin: 0 0 1.2em 0; }
h2 { text-align: left; margin: 0.4em 0 0.8em 0; }
h3 { text-align: left; margin: 1.2em 0 0.4em 0; }
p.li { text-indent: 0; margin-left: 1.2em; }
p.final { margin: 0.4em 1em 0.6em 1em; }
p.sign { text-align: right; font-style: italic; }
"""

# Standard edition: no font-family / colour, sizes in em/% so the reading app's
# font, size and dark mode settings win.
CSS_STD = """body { margin: 0 4%; line-height: 1.5; }
p { margin: 0 0 0.7em 0; text-indent: 1.2em; text-align: justify; }
h1 { font-size: 1.6em; text-align: center; margin: 1.5em 0 0.3em 0; line-height: 1.25; }
p.sub { text-align: center; font-style: italic; text-indent: 0; margin: 0 0 0.4em 0; }
p.meta { text-align: center; text-indent: 0; margin: 0 0 2em 0; }
h2 { font-size: 1.3em; text-align: left; margin: 1em 0 0.8em 0; line-height: 1.3; page-break-before: always; }
h3 { font-size: 1.1em; margin: 1.4em 0 0.5em 0; }
ul { margin: 0 0 0.7em 1.2em; padding: 0; }
li { margin: 0 0 0.3em 0; }
p.final { margin: 0.5em 1.5em 0.7em 1.5em; text-indent: 0; }
p.sign { text-align: right; font-style: italic; text-indent: 0; }
div.cover { margin: 0; text-align: center; }
div.cover img { max-width: 100%; max-height: 100vh; }
"""


def inline(md, std=False):
    t = html.escape(md, quote=False)
    return re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>" if std else r"<b><i>\1</i></b>", t)


def paras_html(paras, cls="", std=False):
    out = []
    for p in paras:
        if p.startswith("- ") and std:
            if not out or out[-1] != "</ul>":  # consecutive bullets share one <ul>
                out += ["<ul>", "</ul>"]
            out.insert(-1, "<li>%s</li>" % inline(p[2:], std))
        elif p.startswith("- "):
            out.append('<p class="li">• %s</p>' % inline(p[2:]))
        else:
            out.append("<p%s>%s</p>" % (' class="%s"' % cls if cls else "", inline(p, std)))
    return out


def cover_jpeg(meta, W=528):
    from PIL import Image, ImageDraw
    z = lambda v: v * W // 528  # layout is drawn for 528 px wide; integer scaling keeps the X3 cover byte-identical
    H = z(792)
    im = Image.new("L", (W, H), 255)
    dr = ImageDraw.Draw(im)
    f = lambda size, bold=False: load_font(z(size), bold)

    def wrap(text, font, width):
        out, line = [], ""
        for w in text.split():
            t = (line + " " + w).strip()
            if dr.textlength(t, font=font) > width and line:
                out.append(line); line = w
            else:
                line = t
        return out + ([line] if line else [])

    dr.rectangle([0, 0, W, z(150)], fill=0)
    dr.text((W / 2, z(75)), "FLASHBOOK", font=f(44, True), fill=255, anchor="mm")
    y = z(230)
    for ln in wrap(meta["title"].upper(), f(48, True), W - z(60)):
        dr.text((W / 2, y), ln, font=f(48, True), fill=0, anchor="mm"); y += z(60)
    y += z(20)
    for ln in wrap(meta.get("subtitle", ""), f(24), W - z(80)):
        dr.text((W / 2, y), ln, font=f(24), fill=60, anchor="mm"); y += z(32)
    dr.line([W / 2 - z(60), y + z(20), W / 2 + z(60), y + z(20)], fill=0, width=z(3))
    dr.text((W / 2, y + z(60)), meta.get("author", ""), font=f(28, True), fill=0, anchor="mm")
    bottom = "Đọc trong %s phút" % meta.get("read_minutes", "?")
    if meta.get("source_pages"):
        bottom += " · sách gốc %s trang" % meta["source_pages"]
    dr.text((W / 2, H - z(70)), bottom, font=f(22), fill=0, anchor="mm")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85, optimize=True)
    return buf.getvalue()


def ascii_name(s):
    s = unicodedata.normalize("NFD", s.replace("Đ", "D").replace("đ", "d"))
    s = re.sub(r"[^\w .,&()-]", "", "".join(c for c in s if not unicodedata.combining(c)))
    return re.sub(r"\s+", " ", s).strip()


def build(src, out, target="x3"):
    std = target == "std"
    meta, sections = parse(src)
    if not out.lower().endswith(".epub"):  # a folder: name the file after the book
        out = "%s/%s - %s [%s].epub" % (out.rstrip("/\\"), ascii_name(meta["title"]), ascii_name(meta.get("author", "")),
                                         "Flashbook" if std else "Flashbook X3")
    total = sum(words(" ".join(p)) for _, p in sections)
    meta.setdefault("read_minutes", "")
    if not meta["read_minutes"]:
        meta["read_minutes"] = str(max(5, round(total / WPM / 5) * 5))
    lang = "vi"
    title = "%s (Flashbook)" % meta["title"]
    files, toc = [], []

    center = "p" if std else "h4"
    intro = ["<h1>%s</h1>" % html.escape(meta["title"])]
    if meta.get("subtitle"):
        intro.append('<%s class="sub">%s</%s>' % (center, html.escape(meta["subtitle"]), center))
    line = [meta.get("author", ""), "Flashbook %s phút" % meta["read_minutes"]]
    if meta.get("source_pages"):
        line.append("sách gốc %s trang" % meta["source_pages"])
    intro.append('<%s class="meta">%s</%s>' % (center, html.escape(" - ".join(x for x in line if x)), center))
    k = 0
    for name, paras in sections:
        if name in INTRO:
            intro += ["<h3>%s</h3>" % html.escape(name)] + paras_html(paras, std=std)
    files.append(("intro", intro)); toc.append(("Giới thiệu", "intro"))
    for name, paras in sections:
        if name in INTRO:
            continue
        if name == FINAL:
            body = ["<h2>%s</h2>" % html.escape(name)] + paras_html(paras, "final", std)
            if meta.get("source"):
                sign = meta["source"]
                if std and sign == "Flashbook X3":  # the device name is noise outside the X3
                    sign = "Flashbook"
                body.append('<p class="sign">— %s</p>' % html.escape(sign))
            files.append(("final", body)); toc.append((FINAL, "final"))
            continue
        k += 1
        fid = "idea%02d" % k
        label = "%d. %s" % (k, name)
        files.append((fid, ["<h2>%s</h2>" % html.escape(label)] + paras_html(paras, std=std)))
        toc.append((label, fid))

    # a separate id for the std edition, so apps holding both never merge them into one book
    uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, ("flashbook-std:" if std else "flashbook:") + meta["title"] + meta.get("author", "")))
    html_tag = '<html xmlns="http://www.w3.org/1999/xhtml" lang="vi" xml:lang="vi">' if std else '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="vi">'
    page = lambda body: ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n' + html_tag + '\n'
                         '<head><title>%s</title><link rel="stylesheet" type="text/css" href="style.css"/></head>\n<body>\n%s\n</body>\n</html>\n'
                         % (html.escape(title), "\n".join(body)))
    man = ['<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
           '<item id="css" href="style.css" media-type="text/css"/>',
           '<item id="cover-img" href="cover.jpg" media-type="image/jpeg"%s/>' % (' properties="cover-image"' if std else ""),
           '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>']
    if std:
        man.insert(1, '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    man += ['<item id="%s" href="%s.xhtml" media-type="application/xhtml+xml"/>' % (f, f) for f, _ in files]
    spine = ['<itemref idref="cover"/>'] + ['<itemref idref="%s"/>' % f for f, _ in files]
    if std:
        # the .md mtime: rebuilding without touching the source keeps the OPF identical (a code/CSS change does not bump it)
        modified = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(src)))
        opf = ('<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="vi">\n'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
               '<dc:title>%s</dc:title><dc:creator id="aut">%s</dc:creator>'
               '<meta refines="#aut" property="role" scheme="marc:relators">aut</meta><dc:language>%s</dc:language>\n'
               '<dc:identifier id="uid">%s</dc:identifier><meta property="dcterms:modified">%s</meta>'
               '<meta name="cover" content="cover-img"/>\n</metadata>\n'
               '<manifest>\n%s\n</manifest>\n<spine toc="ncx">\n%s\n</spine>\n'
               '<guide><reference type="cover" title="Cover" href="cover.xhtml"/>'
               '<reference type="text" title="Giới thiệu" href="intro.xhtml"/></guide>\n</package>\n') % (
            html.escape(title), html.escape(meta.get("author", "")), lang, uid, modified, "\n".join(man), "\n".join(spine))
        navx = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="vi" xml:lang="vi">\n'
                '<head><title>%s</title></head>\n<body>\n<nav epub:type="toc" id="toc"><h1>Mục lục</h1>\n<ol>\n%s\n</ol>\n</nav>\n'
                '<nav epub:type="landmarks" hidden=""><ol><li><a epub:type="cover" href="cover.xhtml">Bìa</a></li>'
                '<li><a epub:type="bodymatter" href="intro.xhtml">Giới thiệu</a></li></ol></nav>\n</body>\n</html>\n') % (
            html.escape(title), "\n".join('<li><a href="%s.xhtml">%s</a></li>' % (f, html.escape(lbl)) for lbl, f in toc))
    else:
        opf = ('<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">\n'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">\n'
               '<dc:title>%s</dc:title><dc:creator opf:role="aut">%s</dc:creator><dc:language>%s</dc:language>\n'
               '<dc:identifier id="uid">%s</dc:identifier><meta name="cover" content="cover-img"/>\n</metadata>\n'
               '<manifest>\n%s\n</manifest>\n<spine toc="ncx">\n%s\n</spine>\n'
               '<guide><reference type="cover" title="Cover" href="cover.xhtml"/></guide>\n</package>\n') % (
            html.escape(title), html.escape(meta.get("author", "")), lang, uid, "\n".join(man), "\n".join(spine))
    nav = "\n".join('<navPoint id="np%d" playOrder="%d"><navLabel><text>%s</text></navLabel><content src="%s.xhtml"/></navPoint>'
                    % (i, i, html.escape(lbl), f) for i, (lbl, f) in enumerate(toc, 1))
    ncx = ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
           '<head><meta name="dtb:uid" content="%s"/><meta name="dtb:depth" content="1"/></head>\n'
           '<docTitle><text>%s</text></docTitle>\n<navMap>\n%s\n</navMap>\n</ncx>\n') % (uid, html.escape(title), nav)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        D = zipfile.ZIP_DEFLATED
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>\n', compress_type=D)
        z.writestr("OEBPS/content.opf", opf, compress_type=D)
        z.writestr("OEBPS/toc.ncx", ncx, compress_type=D)
        if std:
            z.writestr("OEBPS/nav.xhtml", navx, compress_type=D)
        z.writestr("OEBPS/style.css", CSS_STD if std else CSS, compress_type=D)
        z.writestr("OEBPS/cover.jpg", cover_jpeg(meta, 1600 if std else 528), compress_type=zipfile.ZIP_STORED)
        cover = ('<div class="cover"><img src="cover.jpg" alt="%s"/></div>' % html.escape(title) if std
                 else '<div><img src="cover.jpg" alt=""/></div>')
        z.writestr("OEBPS/cover.xhtml", page([cover]), compress_type=D)
        for f, body in files:
            z.writestr("OEBPS/%s.xhtml" % f, page(body), compress_type=D)
    print("build: %d key ideas, %d words, %s min -> %s" % (k, total, meta["read_minutes"], out))
