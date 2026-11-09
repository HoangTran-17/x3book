"""Rebuild a text PDF (InDesign export) as a reflowable EPUB 2 for the X3.

Used by `x3book pdf` and by `x3book tune` when the source is a .pdf (plan has a "pdf" block):
  {"pdf": {
     "title": "...", "author": "...", "lang": "vi",
     "cover_page": 0,                      # rendered to cover.jpg
     "skip_pages": [1, 5, 6],              # blank pages, printed TOC
     "drop_below_y": 560,                  # running footer / page number band
     "page_offset": 1,                     # printed page number = pdf index + offset
     "toc_pages": [5, 6, 7, 8],            # printed TOC: gives labels + which sections get a file
     "toc_entry_font": "Mulish-Bold 9.5", "toc_section_font": "Mulish-Regular 9.5",
     "para_starts": ["→"],            # a line starting with these opens a new paragraph
     "roles": {"<font> <size>": "drop|body|quote|center|footnote|figure|part|chapter|chapter_sub|section"}}}

Roles: part/chapter/section become h1/h2/h3 and (when listed in the printed TOC, or
always for part/chapter) start a new file with a TOC entry, so the X3 footer shows the
current section. "figure" text marks a diagram: its area is rendered as an image.
"""
import html
import io
import re
import uuid
import zipfile

from PIL import Image

from .core import MAX_SIDE

try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None
CSS = """body { margin: 0; }
p { margin: 0 0 0.6em 0; text-align: justify; }
h1, h2, h3 { text-align: center; margin: 1em 0 0.8em 0; }
p.quote { margin: 0.4em 1.5em 0.6em 1.5em; font-style: italic; }
p.center { text-align: center; }
p.fn { margin: 0.2em 0 0.6em 0; padding-left: 1em; font-size: 0.8em; }
p.fig { text-align: center; margin: 0.8em 0; }
.sup { vertical-align: super; }
"""


def clean(t):
    return t.replace("​", "").replace("­", "")


def esc(t):
    return html.escape(t, quote=False)


def span_html(s):
    t = esc(clean(s["text"]))
    if not t:
        return ""
    if s["flags"] & 1:  # superscript
        return '<span class="sup">%s</span>' % t
    f = s["font"]
    if "Bold" in f or "Semibold" in f:
        t = "<b>%s</b>" % t
    if "Italic" in f:
        t = "<i>%s</i>" % t
    return t


def key(s):
    return "%s %.1f" % (s["font"], round(s["size"], 1))


def lines_of(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            sp = [s for s in l["spans"] if s["text"].strip()]
            if sp:
                out.append({"bbox": l["bbox"], "spans": l["spans"], "first": sp[0],
                            "text": clean("".join(s["text"] for s in l["spans"])).strip()})
    return sorted(out, key=lambda l: (round(l["bbox"][1]), l["bbox"][0]))


def printed_toc(doc, cfg):
    """[(page_index, label, is_section)] from the printed TOC pages."""
    rows = []
    for pn in cfg.get("toc_pages", []):
        ls = lines_of(doc[pn])
        nums = [(l["bbox"][1], int(l["text"])) for l in ls if re.fullmatch(r"\d+", l["text"])]
        cur = None
        for l in ls:
            k = key(l["first"])
            if re.fullmatch(r"\d+", l["text"]) or k not in (cfg["toc_entry_font"], cfg["toc_section_font"]):
                continue
            y = l["bbox"][1]
            if cur and cur["kind"] == k and y - cur["y"] < 16:  # wrapped title
                cur["label"] += " " + l["text"]; cur["y"] = y
                continue
            num = min(nums, key=lambda n: abs(n[0] - y))
            cur = {"kind": k, "label": l["text"], "y": y, "page": num[1] - cfg.get("page_offset", 0)}
            rows.append(cur)
    return [(r["page"], re.sub(r"\s+", " ", r["label"]).strip(), r["kind"] == cfg["toc_section_font"]) for r in rows]


def render_clip(page, rect):
    pix = page.get_pixmap(clip=rect, dpi=220, colorspace=pymupdf.csGRAY)
    im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85, optimize=True)
    return buf.getvalue()


def figure_rect(page, figure_lines):
    r = pymupdf.Rect(figure_lines[0]["bbox"])
    for l in figure_lines[1:]:
        r |= pymupdf.Rect(l["bbox"])
    pa = page.rect.width * page.rect.height
    for d in page.get_drawings():
        dr = d["rect"]
        if dr.width * dr.height < 0.5 * pa and dr.intersects(r + (-60, -60, 60, 60)):
            r |= dr
    return (r + (-8, -8, 8, 8)) & page.rect


def convert(pdf_path, cfg, out_path):
    if pymupdf is None:
        raise SystemExit("PDF support needs pymupdf: pip install pymupdf")
    doc = pymupdf.open(pdf_path)
    roles = cfg["roles"]
    toc_rows = printed_toc(doc, cfg)
    toc_by_page = {}
    for pg, label, is_sec in toc_rows:
        toc_by_page.setdefault((pg, is_sec), []).append(label)
    skip = set(cfg.get("skip_pages", [])) | set(cfg.get("toc_pages", [])) | {cfg.get("cover_page", 0)}
    starts = tuple(cfg.get("para_starts", []))

    files = []      # [{"name", "body": [html]}]
    toc = []        # [(level, label, file)]
    images = {}     # name -> bytes
    state = {"para": None, "fn": [], "in_part": False, "chapter_level": 1}

    def new_file():
        files.append({"name": "text/%03d.xhtml" % len(files), "body": []})

    def emit(h):
        if not files:
            new_file()
        files[-1]["body"].append(h)

    def close_para():
        p = state["para"]
        if p:
            emit('<p%s>%s</p>' % (' class="%s"' % p["cls"] if p["cls"] else "", re.sub(r"\s+", " ", p["html"]).strip()))
            state["para"] = None
        for f in state["fn"]:
            emit('<p class="fn">%s</p>' % f)
        state["fn"] = []

    def heading(role, text_html, label_text, pn):
        close_para()
        if role == "part":
            level, tag = 1, "h1"
            state["in_part"] = True
            state["chapter_level"] = 2
        elif role == "chapter":
            level, tag = state["chapter_level"], "h2"
        else:
            level, tag = state["chapter_level"] + 1, "h3"
        listed = toc_by_page.get((pn, role == "section"))
        if role != "section" or listed:
            new_file()
            label = listed.pop(0) if listed else label_text
            toc.append((level, label, files[-1]["name"]))
        text_html = re.sub(r"\s+", " ", re.sub(r"\s+</b>", "</b> ", text_html)).replace("</b> <b>", " ").strip()
        emit("<%s>%s</%s>" % (tag, text_html, tag))

    for pn in range(doc.page_count):
        if pn in skip:
            continue
        page = doc[pn]
        ls = [l for l in lines_of(page) if l["bbox"][1] < cfg.get("drop_below_y", 1e9)]
        figs = [l for l in ls if roles.get(key(l["first"])) == "figure"]
        fig_y = None
        if figs:
            rect = figure_rect(page, figs)
            name = "images/fig_%03d.jpg" % pn
            images[name] = render_clip(page, rect)
            fig_y = rect.y0
            # text drawn inside the diagram is part of the image now
            ls = [l for l in ls if not rect.contains(pymupdf.Point((l["bbox"][0] + l["bbox"][2]) / 2, (l["bbox"][1] + l["bbox"][3]) / 2))]
        pending_head = None
        prev = None
        for l in ls + [None]:
            if fig_y is not None and (l is None or l["bbox"][1] > fig_y):
                if pending_head:
                    heading(*pending_head); pending_head = None
                close_para()
                emit('<p class="fig"><img src="../%s" alt=""/></p>' % name)
                fig_y = None
            if l is None:
                break
            role = roles.get(key(l["first"]), "body")
            if role == "drop":
                continue
            h = "".join(span_html(s) for s in l["spans"]).strip()
            if role in ("part", "chapter", "section"):
                if pending_head and pending_head[0] == role and l["bbox"][1] - prev["bbox"][3] < 20:
                    pending_head = (role, pending_head[1] + " " + h, pending_head[2] + " " + l["text"], pn)
                else:
                    if pending_head:
                        heading(*pending_head)
                    pending_head = (role, h, l["text"], pn)
                prev = l
                continue
            if role == "chapter_sub" and pending_head:
                pending_head = (pending_head[0], pending_head[1] + "<br/>" + h, pending_head[2] + " " + l["text"], pn)
                prev = l
                continue
            if pending_head:
                heading(*pending_head); pending_head = None
            if role == "footnote":
                if re.match(r"\(\d+\)", l["text"]) or not state["fn"]:
                    state["fn"].append(h)
                else:
                    state["fn"][-1] += " " + h
                continue
            cls = {"quote": "quote", "center": "center"}.get(role, "")
            p = state["para"]
            size = l["first"]["size"]
            same_page_gap = prev is not None and l["bbox"][1] - prev["bbox"][1] <= 1.9 * size
            cont_page = prev is None and p is not None and not re.search(r"[.!?…:”\"»)\]]$", p["text"])
            if p and p["cls"] == cls and (same_page_gap or cont_page) and not l["text"].startswith(starts) and role != "center":
                p["html"] += " " + h
                p["text"] = l["text"]
            else:
                close_para()
                state["para"] = {"cls": cls, "html": h, "text": l["text"]}
            prev = l
        if pending_head:
            heading(*pending_head)
        if state["para"] is None:
            close_para()  # flush footnotes of a page that ended on a closed paragraph
    close_para()

    # cover
    cover = doc[cfg.get("cover_page", 0)].get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
    im = Image.open(io.BytesIO(cover.tobytes("png"))).convert("L")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=85, optimize=True)
    images["images/cover.jpg"] = buf.getvalue()

    write_epub(out_path, cfg, files, toc, images)
    return len(files), len(toc), len(images)


def page(title, body, lang):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="%s">\n'
            '<head><title>%s</title><link rel="stylesheet" type="text/css" href="../style.css"/></head>\n'
            '<body>\n%s\n</body>\n</html>\n') % (lang, esc(title), "\n".join(body))


def write_epub(out, cfg, files, toc, images, css=CSS):
    lang, title, uid = cfg.get("lang", "vi"), cfg["title"], "urn:uuid:" + str(uuid.uuid4())
    files.insert(0, {"name": "text/cover.xhtml", "body": ['<div><img src="../images/cover.jpg" alt=""/></div>']})
    man = ['<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
           '<item id="css" href="style.css" media-type="text/css"/>']
    for k, f in enumerate(files):
        man.append('<item id="t%d" href="%s" media-type="application/xhtml+xml"/>' % (k, f["name"]))
    for k, n in enumerate(sorted(images)):
        iid = "cover-img" if n == "images/cover.jpg" else "i%d" % k
        man.append('<item id="%s" href="%s" media-type="image/jpeg"/>' % (iid, n))
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">\n'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">\n'
           '<dc:title>%s</dc:title><dc:creator opf:role="aut">%s</dc:creator><dc:language>%s</dc:language>\n'
           '<dc:identifier id="uid">%s</dc:identifier><meta name="cover" content="cover-img"/>\n</metadata>\n'
           '<manifest>\n%s\n</manifest>\n<spine toc="ncx">\n%s\n</spine>\n'
           '<guide><reference type="cover" title="Cover" href="text/cover.xhtml"/></guide>\n</package>\n') % (
        esc(title), esc(cfg.get("author", "")), lang, uid, "\n".join(man),
        "\n".join('<itemref idref="t%d"/>' % k for k in range(len(files))))
    # nested navMap from (level, label, file)
    nav, stack, n = [], [], 0
    for level, label, f in toc:
        while stack and stack[-1] >= level:
            nav.append("</navPoint>"); stack.pop()
        n += 1
        nav.append('<navPoint id="np%d" playOrder="%d"><navLabel><text>%s</text></navLabel><content src="%s"/>' % (n, n, esc(label), f))
        stack.append(level)
    nav += ["</navPoint>"] * len(stack)
    depth = max((l for l, _, _ in toc), default=1)
    ncx = ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
           '<head><meta name="dtb:uid" content="%s"/><meta name="dtb:depth" content="%d"/></head>\n'
           '<docTitle><text>%s</text></docTitle>\n<navMap>\n%s\n</navMap>\n</ncx>\n') % (uid, depth, esc(title), "\n".join(nav))
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>\n',
                   compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", css, compress_type=zipfile.ZIP_DEFLATED)
        for f in files:
            z.writestr("OEBPS/" + f["name"], page(title, f["body"], lang), compress_type=zipfile.ZIP_DEFLATED)
        for name, data in images.items():
            z.writestr("OEBPS/" + name, data, compress_type=zipfile.ZIP_STORED)
