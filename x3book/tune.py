"""Tune an EPUB for the Xteink X3 running CrossVi.

Always applied:
  - images: progressive JPEG, or longest side > MAX_SIDE -> grayscale, fit MAX_SIDE,
    baseline JPEG q85 / grayscale PNG (same file name, so no href changes)
  - SVG-wrapped images -> <img>, "svg" dropped from OPF properties
  - HTML-only entities -> numeric, text-free layout tables -> <div>, CSS "1.05e +3pt" -> plain
  - archive rewritten with "mimetype" first and stored (EPUB OCF)

Plan (all keys optional), paths are relative to the OPF directory:
  {"relabel": {"old TOC label": "new label"},
   "drop":    ["TOC label to remove; its children move up one level"],
   "split":   [{"file": "a.html", "before_id": "x"} | {"file": "a.html", "before_text": "prefix"}],
   "chapters_from": {"class": "block_", "heading_tag": "h2"}}

Why: the footer shows the FIRST TOC entry that points at the current spine file
(crossvi lib/Epub/Epub/BookMetadataCache.cpp:741-742), so every chapter needs its own
file and a meaningful label. Progressive JPEG decodes at 1/8 resolution
(JpegToFramebufferConverter.cpp:433-465).
"""
import copy
import html
import io
import json
import os
import posixpath
import re
import tempfile

from lxml import etree
from PIL import Image

from .core import (CONTENT_RE, MAX_SIDE, N, NCX_NS, XHTML_NS, Book, dump_xml,
                   html_entities_to_numeric, norm, parse_xml, text_of)

SVG_IMAGE_RE = re.compile(
    r"<(?:svg:)?svg\b[^>]*>[\s\S]*?<(?:svg:)?image\b[^>]*xlink:href=[\"']([^\"']+)[\"'][^>]*/?>\s*</(?:svg:)?svg>", re.I)


# ---------------- images / svg ----------------
def fix_images(book):
    n = 0
    for name in book.order:
        ext = name.lower().rsplit(".", 1)[-1]
        if ext not in ("jpg", "jpeg", "png"):
            continue
        im = Image.open(io.BytesIO(book.data[name]))
        prog = ext != "png" and bool(im.info.get("progressive") or im.info.get("progression"))
        if not prog and max(im.size) <= MAX_SIDE:
            continue
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, "white")
            im = Image.alpha_composite(bg, im)
        im = im.convert("L")
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        if ext == "png":
            im.save(buf, "PNG", optimize=True)
        else:
            im.save(buf, "JPEG", quality=85, optimize=True, progressive=False)
        book.data[name] = buf.getvalue()
        n += 1
    return n


def fix_svg(book):
    n = 0
    for name in book.order:
        if not CONTENT_RE.search(name):
            continue
        s = book.data[name].decode("utf8")
        t, k = SVG_IMAGE_RE.subn(lambda m: '<img style="max-width:100%;height:auto" src="' + m.group(1) + '" alt="" />', s)
        if k:
            book.data[name] = t.encode("utf8")
            n += k
    book.opf = re.sub(r'(properties="[^"]*?)\s*\bsvg\b', r"\1", book.opf)
    book.opf = re.sub(r'\s+properties=""', "", book.opf)
    return n


def fix_css_numbers(book):
    """KindleUnpack can emit "width: 1.05e +3pt"; CrossVi reads that as width 1 and
    draws the image as a 1 px line. Write such numbers out in plain decimal."""
    n = 0
    for name in book.order:
        if not name.lower().endswith(".css"):
            continue
        s = book.data[name].decode("utf8")
        t, k = re.subn(r"(?<![#\w.])(\d+(?:\.\d+)?)e\s*([+-])\s*(\d+)(?=[a-z%])",
                       lambda m: "%g" % float(m.group(1) + "e" + m.group(2) + m.group(3)), s)
        if k:
            book.data[name] = t.encode("utf8")
            n += k
    return n


def fix_layout_tables(book):
    """Text-free tables only position images; CrossVi flattens tables and prints a
    "Tab Row N, Cell M:" label per cell (ChapterHtmlSlimParser.cpp:641), so unwrap them."""
    n = 0
    for name in book.order:
        if not CONTENT_RE.search(name):
            continue
        s = book.data[name].decode("utf8")

        def sub(m):
            nonlocal n
            if norm(html.unescape(re.sub(r"<[^>]+>", " ", m.group(0)))):
                return m.group(0)
            n += 1
            return "<div>" + "".join(re.findall(r"<img\b[^>]*>", m.group(0))) + "</div>"

        t = re.sub(r"<table\b.*?</table>", sub, s, flags=re.S)
        if t != s:
            book.data[name] = t.encode("utf8")
    return n


# ---------------- splitting ----------------
def split_tree(tree, marker):
    """Return (head, tail): head keeps content before the marked element, tail keeps it and after."""
    tail = copy.deepcopy(tree)
    for t, keep_after in ((tree, False), (tail, True)):
        node = t.xpath('//*[@x3split="%s"]' % marker)[0]
        first = True
        while etree.QName(node).localname != "body":
            parent = node.getparent()
            sibs = list(parent)
            i = sibs.index(node)
            if keep_after:
                for s in sibs[:i]:
                    parent.remove(s)
                parent.text = None
            else:
                for s in sibs[i + (0 if first else 1):]:
                    parent.remove(s)
                if not first:
                    node.tail = None
            first = False
            node = parent
    del tail.xpath('//*[@x3split="%s"]' % marker)[0].attrib["x3split"]
    return tree, tail


def ids_in(tree):
    return {el.get("id") for el in tree.iter() if isinstance(el.tag, str) and el.get("id")}


def split_file(book, full, points, moved):
    """points: list of elements (in document order) inside parsed tree; returns new file paths."""
    tree = points[0].getroottree()
    for k, el in enumerate(points):
        el.set("x3split", str(k))
    stem, ext = posixpath.splitext(full)
    parts, cur = [], tree
    for k in range(len(points)):
        head, cur = split_tree(cur, str(k))
        parts.append(head)
    parts.append(cur)
    names = [full] + ["%s_x3_%d%s" % (stem, k + 1, ext) for k in range(len(points))]
    head_ids = ids_in(parts[0])
    for name, part in zip(names[1:], parts[1:]):
        book.part_of[name] = full
        for i in ids_in(part) - head_ids:
            moved[(full, i)] = name
    # add manifest + spine entries right after the original
    man = book.manifest()
    oid, (_, attrs, tag) = next((i, v) for i, v in man.items() if v[0] == full)
    new_items, new_refs = "", ""
    for k, name in enumerate(names[1:], 1):
        nid = "%s_x3_%d" % (oid, k)
        href = posixpath.relpath(name, book.base)
        new_items += "\n    " + tag.replace('id="%s"' % oid, 'id="%s"' % nid).replace(
            'href="%s"' % attrs["href"], 'href="%s"' % href)
        new_refs += '\n    <itemref idref="%s"/>' % nid
        book.order.insert(book.order.index(full) + k, name)
    book.opf = book.opf.replace(tag, tag + new_items, 1)
    m = re.search(r'<itemref\b[^>]*idref="%s"[^>]*/>' % re.escape(oid), book.opf)
    book.opf = book.opf[:m.end()] + new_refs + book.opf[m.end():]
    for name, part in zip(names, parts):
        book.data[name] = dump_xml(part)
    return names[1:]


def find_points(tree, specs):
    pts = []
    for sp in specs:
        if "before_id" in sp:
            el = tree.xpath('//*[@id="%s"]' % sp["before_id"])[0]
            # split at the enclosing block so the heading paragraph moves whole
            while etree.QName(el.getparent()).localname not in ("body",) and etree.QName(el).localname not in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6"):
                el = el.getparent()
        else:
            el = next(e for e in tree.iter("{%s}p" % XHTML_NS, "{%s}div" % XHTML_NS)
                      if text_of(e).startswith(sp["before_text"]) and not len(e.xpath(".//h:p|.//h:div", namespaces=N)))
        pts.append(el)
    order = {e: i for i, e in enumerate(tree.iter())}
    return sorted(pts, key=lambda e: order[e])


def rewrite_refs(book, moved):
    """Point href="file#id" at the part that now holds the id."""
    if not moved:
        return
    for name in list(book.order):
        if not (CONTENT_RE.search(name) or name.endswith(".ncx")):
            continue
        s = book.data[name].decode("utf8")

        def sub(m):
            attr, path, frag = m.group(1), m.group(2), m.group(3)
            # "#id" inside a split part still means "id in the original file"
            target = book.full(path, name) if path else book.part_of.get(name, name)
            new = moved.get((target, frag), target)
            if new == (book.full(path, name) if path else name):
                return m.group(0)
            if new == name:
                return '%s="#%s"' % (attr, frag)
            return '%s="%s#%s"' % (attr, book.rel(new, name), frag)

        t = re.sub(r'\b(href|src)="([^"#]*)#([^"]+)"', sub, s)
        if t != s:
            book.data[name] = t.encode("utf8")


# ---------------- TOC ----------------
def ncx_ops(book, plan):
    p = book.ncx_path()
    tree = parse_xml(book.data[p])
    relabel = plan.get("relabel", {})
    hit = set()
    for t in tree.iterfind(".//n:navPoint/n:navLabel/n:text", N):
        key = norm(t.text)
        if key in relabel:
            t.text = relabel[key]
            hit.add(key)
    for label in plan.get("drop", []):
        for np_ in tree.iterfind(".//n:navPoint", N):
            if norm(np_.findtext("n:navLabel/n:text", namespaces=N)) == label:
                parent, i = np_.getparent(), list(np_.getparent()).index(np_)
                for k, child in enumerate(np_.findall("n:navPoint", N)):
                    parent.insert(i + 1 + k, child)
                parent.remove(np_)
                hit.add(label)
                break
    renumber(tree)
    book.data[p] = dump_xml(tree)
    missing = (set(relabel) | set(plan.get("drop", []))) - hit
    if missing:
        raise SystemExit("TOC label not found: %s" % sorted(missing))
    nav = book.nav_path()
    if nav and relabel:
        nt = parse_xml(book.data[nav])
        for a in nt.iterfind(".//h:nav//h:a", N):
            key = text_of(a)
            if key in relabel:
                for c in list(a):
                    a.remove(c)
                a.text = relabel[key]
        book.data[nav] = dump_xml(nt)
    if nav and plan.get("drop"):
        raise SystemExit("drop on nav.xhtml is not implemented")


def renumber(tree):
    for k, np_ in enumerate(tree.iterfind(".//n:navPoint", N), 1):
        np_.set("playOrder", str(k))
    depth = max((len(np_.xpath("ancestor::n:navPoint", namespaces=N)) + 1 for np_ in tree.iterfind(".//n:navPoint", N)), default=1)
    for m in tree.iterfind(".//n:head/n:meta[@name='dtb:depth']", N):
        m.set("content", str(depth))


def sentence(s):
    s = norm(s)
    return s[:1].upper() + s[1:].lower() if s.isupper() else s


def chapters_from(book, cfg, moved):
    """Build a flat TOC from styled heading paragraphs; split so each chapter has its own file."""
    cls, tag = cfg["class"], cfg.get("heading_tag", "h2")
    entries = []
    for full in book.spine():
        if not CONTENT_RE.search(full):
            continue
        tree = parse_xml(book.data[full])
        heads = [p for p in tree.iter("{%s}p" % XHTML_NS) if p.get("class") == cls and text_of(p)]
        starts, labels, i = [], [], 0
        while i < len(heads):
            h = heads[i]
            nxt = heads[i + 1] if i + 1 < len(heads) else None
            if text_of(h).isdigit() and nxt is not None and nxt is h.getnext():
                starts.append(h); labels.append("%s. %s" % (text_of(h), sentence(text_of(nxt)))); i += 2
            else:
                starts.append(h); labels.append(sentence(text_of(h))); i += 1
        for h in heads:
            h.tag = "{%s}%s" % (XHTML_NS, tag)
        if not starts:
            book.data[full] = dump_xml(tree)
            continue
        # heading opens the file -> no split there; otherwise the lead-in stays in `full`
        # without its own entry and inherits the previous chapter's label
        lead = not starts[0].xpath("preceding::text()[normalize-space()][ancestor::h:body] | preceding::h:img", namespaces=N)
        pts = starts[1:] if lead else starts
        names = split_file(book, full, pts, moved) if pts else []
        if not pts:
            book.data[full] = dump_xml(tree)
        entries += list(zip(labels, ([full] if lead else []) + names))
    ncx = book.ncx_path()
    tree = parse_xml(book.data[ncx])
    nav_map = tree.find(".//n:navMap", N)
    for c in list(nav_map):
        nav_map.remove(c)
    for k, (label, full) in enumerate(entries, 1):
        np_ = etree.SubElement(nav_map, "{%s}navPoint" % NCX_NS, id="x3np_%d" % k)
        etree.SubElement(etree.SubElement(np_, "{%s}navLabel" % NCX_NS), "{%s}text" % NCX_NS).text = label
        etree.SubElement(np_, "{%s}content" % NCX_NS, src=book.rel(full, ncx))
    renumber(tree)
    book.data[ncx] = dump_xml(tree)
    return len(entries)


# ---------------- driver ----------------
def load_plan(path_or_dict):
    if path_or_dict is None:
        plan = {}
    elif isinstance(path_or_dict, dict):
        plan = copy.deepcopy(path_or_dict)
    else:
        with open(path_or_dict, encoding="utf8") as f:
            plan = json.load(f)
    # book text is often NFD; compare everything in NFC
    plan["relabel"] = {norm(k): v for k, v in plan.get("relabel", {}).items()}
    plan["drop"] = [norm(d) for d in plan.get("drop", [])]
    for sp in plan.get("split", []):
        if "before_text" in sp:
            sp["before_text"] = norm(sp["before_text"])
    return plan


def tune(src, out, plan=None, extras=None, log=print):
    """Tune `src` (.epub, or .pdf with a "pdf" plan block, or .azw3 with the `mobi` package) into `out`."""
    from . import epaper
    plan = load_plan(plan)
    extras = extras or epaper.Extras()
    if src.lower().endswith(".pdf"):
        from . import pdf
        tmp = posixpath.join(tempfile.mkdtemp(), "from_pdf.epub")
        log("pdf -> epub  : files %d, toc %d, images %d" % pdf.convert(src, plan["pdf"], tmp))
        src = tmp
    if src.lower().endswith(".azw3"):
        try:
            import mobi  # KindleUnpack wrapper; KF8 (azw3) without DRM unpacks to a plain EPUB
        except ImportError:
            raise SystemExit("azw3 needs the `mobi` package (pip install mobi), or use Calibre: x3book convert")
        _, src = mobi.extract(src)
        if not src.lower().endswith(".epub"):
            raise SystemExit("azw3 did not unpack to an EPUB: " + src)
    book = Book(src)
    moved = {}
    by_file = {}
    for sp in plan.get("split", []):
        by_file.setdefault(book.full(sp["file"]), []).append(sp)
    for full, specs in by_file.items():
        tree = parse_xml(book.data[full])
        new = split_file(book, full, find_points(tree, specs), moved)
        log("split        : %s -> +%d file" % (full, len(new)))
    if "chapters_from" in plan:
        log("chapters     : %s" % chapters_from(book, plan["chapters_from"], moved))
    rewrite_refs(book, moved)
    if plan.get("relabel") or plan.get("drop"):
        ncx_ops(book, plan)
        log("toc          : relabel %d, drop %d" % (len(plan.get("relabel", {})), len(plan.get("drop", []))))
    ent = 0
    for name in book.order:
        if CONTENT_RE.search(name):
            fixed = html_entities_to_numeric(book.data[name])
            if fixed != book.data[name]:
                book.data[name] = fixed
                ent += 1
    # CrossVi's expat parser stops a chapter at the first undefined entity
    log("entity fix   : %d file" % ent)
    log("css numbers  : %s" % fix_css_numbers(book))
    log("svg unwrap   : %s" % fix_svg(book))
    log("layout tables: %s" % fix_layout_tables(book))
    for line in epaper.apply(book, extras):
        log(line)
    log("images fixed : %s" % fix_images(book))
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    book.save(out)
    log("written      : %s" % out)
