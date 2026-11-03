"""`x3book check`: report what CrossVi will choke on, and the footer label each spine file gets."""
import io
import xml.parsers.expat
import zipfile

from PIL import Image

from .core import CONTENT_RE, MAX_SIDE, N, Book, html_entities_to_numeric, norm, parse_xml


def check(path, log=print):
    """Print the report (same lines as the old `x3_epub.py --check`). Return a list of problems."""
    book = Book(path)
    problems = []
    with zipfile.ZipFile(path) as z:
        first = z.infolist()[0]
        zt = z.testzip()
    log("zip test     : %s" % (zt or "OK"))
    if zt:
        problems.append("zip test failed: %s" % zt)
    log("mimetype     : %s %s" % (first.filename, "STORED" if first.compress_type == 0 else "COMPRESSED (BAD)"))
    if first.filename != "mimetype" or first.compress_type != 0:
        problems.append("mimetype must be the first entry and stored")
    bad = []
    for n in book.order:
        if CONTENT_RE.search(n) or n.endswith((".ncx", ".opf")):
            # raw expat, same parser family as the device; no entity pre-pass here
            p = xml.parsers.expat.ParserCreate()
            try:
                p.Parse(book.data[n], True)
            except xml.parsers.expat.ExpatError as e:
                bad.append("%s: %s" % (n, e))
    log("expat parse  : %s" % ("OK" if not bad else bad))
    problems += ["expat parse: " + b for b in bad]
    toc = []
    ncx = book.ncx_path()
    if ncx:
        t = parse_xml(book.data[ncx])
        for np_ in t.iterfind(".//n:navPoint", N):
            src = np_.find("n:content", N).get("src")
            f, _, frag = src.partition("#")
            toc.append((len(np_.xpath("ancestor::n:navPoint", namespaces=N)) + 1,
                        norm(np_.findtext("n:navLabel/n:text", namespaces=N)), book.full(f, ncx), frag))
    missing = [e for e in toc if e[2] not in book.data]
    log("toc entries  : %d | broken targets: %s" % (len(toc), missing or 0))
    if missing:
        problems.append("%d broken TOC targets" % len(missing))
    imgs = [n for n in book.order if n.lower().endswith((".jpg", ".jpeg", ".png"))]
    prog = big = 0
    for n in imgs:
        im = Image.open(io.BytesIO(book.data[n]))
        prog += bool(im.info.get("progressive") or im.info.get("progression"))
        big += max(im.size) > MAX_SIDE
    log("images       : %d, progressive %d, > %dpx %d" % (len(imgs), prog, MAX_SIDE, big))
    if prog:
        problems.append("%d progressive JPEG" % prog)
    tables = sum(book.data[n].count(b"<table") for n in book.order if CONTENT_RE.search(n))
    log("tables       : %d" % tables)
    ents = sum(html_entities_to_numeric(book.data[n]) != book.data[n] for n in book.order if CONTENT_RE.search(n))
    log("html entities: %d file" % ents)
    log("footer label per spine file (simulates BookMetadataCache.cpp:741-810):")
    last = "-"
    for si, f in enumerate(book.spine()):
        ents = [e for e in toc if e[2] == f]
        hidden = [e for e in ents[1:] if e[0] <= ents[0][0]]
        if ents:
            last = ents[0][1]
        mark = "  !! hides: " + "; ".join(e[1][:30] for e in hidden) if hidden else ""
        if hidden:
            problems.append("spine file %s hides TOC entries" % f)
        log("  %3d %-60s%s" % (si, (last if ents else "(inherit) " + last)[:60], mark))
    return problems
