"""`x3book merge`: join several sources (text PDFs, Markdown) into one EPUB for the X3.

Plan JSON (paths relative to the plan file):
  {"title": "...", "author": "...", "lang": "vi", "out": "out/book.epub",
   "cover": {"image": "cover.jpg"}                       # or a text cover:
          | {"heading": ["LINE 1", "LINE 2"], "subtitle": "...", "rows": [["I", "Part one"]], "footer": "..."},
   "parts": [
     {"type": "md", "file": "intro.md"},                 # each "## <heading>" -> one file + TOC entry
     {"type": "md", "file": "b.md", "part": "Part II", "part_note": "...", "labels": ["TOC label per ## section"]},
     {"type": "pdf", "file": "a.pdf", "part": "Part I", "part_note": "...", "cover_page": 0,
      "pages": [2, 209], "skip_pages": [14], "max_y": {"209": 130},
      "head_max_y": 140, "head_re": "^[IVXL]+$", "indent_x": 80, "center_x": 150,
      "fn_max_size": 0, "fn_min_y": 0, "replace": {"a": "b"},
      "skip_pages_matching": "[\\u0400-\\u04ff]",        # drop pages whose text matches (e.g. other script)
      "notes_page": 209, "notes_label": "Notes", "notes_title": "Notes",
      "sections": [{"page": 2, "label": "TOC label", "title": "Heading in text"}]}]}

TOC is flat (level 1) and each label should name its source ("A - Chapter 3"): the X3 footer shows
the TOC label of the current spine file on its own (crossvi EpubReaderActivity.cpp:4061-4067).
"""
import html
import io
import json
import os
import re
import unicodedata

from PIL import Image, ImageDraw

from . import pdf as pdfmod
from .core import MAX_SIDE
from .fonts import load_font
from .pdf import esc, span_html

try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None

EXTRA_CSS = """p.ct { }
p.li1 { margin: 0 0 0.4em 1em; text-align: left; }
p.li2 { margin: 0 0 0.4em 2em; text-align: left; }
p.li3 { margin: 0 0 0.4em 3em; text-align: left; }
p.part { text-align: center; margin: 1.5em 1em; font-style: italic; }
p.right { text-align: right; }
h4 { margin: 0.8em 0 0.4em 0; }
"""
NOTES_HREF = "@@NOTES@@"


def nfc(s):
    return unicodedata.normalize("NFC", s).replace(" ", " ").replace("·", "-")


def jpeg(im):
    im = im.convert("L")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85, optimize=True)  # baseline, never progressive
    return buf.getvalue()


def page_jpeg(page, dpi=150):
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    return jpeg(Image.open(io.BytesIO(pix.tobytes("png"))))


# ---------------------------------------------------------------- PDF text flow
def visual_lines(page, max_y):
    """pymupdf splits a printed line at superscripts; merge pieces whose boxes overlap vertically."""
    pieces = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            sp = [s for s in l["spans"] if s["text"].strip()]
            if sp and l["bbox"][1] < max_y:
                pieces.append({"bbox": list(l["bbox"]), "spans": l["spans"]})
    pieces.sort(key=lambda p: p["bbox"][1])
    lines = []
    for p in pieces:
        for L in lines:
            if min(L["y1"], p["bbox"][3]) - max(L["y0"], p["bbox"][1]) >= 3:
                L["pieces"].append(p); L["y0"] = min(L["y0"], p["bbox"][1]); L["y1"] = max(L["y1"], p["bbox"][3])
                break
        else:
            lines.append({"y0": p["bbox"][1], "y1": p["bbox"][3], "pieces": [p]})
    out = []
    for L in sorted(lines, key=lambda L: L["y0"]):
        L["pieces"].sort(key=lambda p: p["bbox"][0])
        spans, prev_x1 = [], None
        for p in L["pieces"]:
            if spans and prev_x1 is not None and p["bbox"][0] - prev_x1 > 1:
                spans.append({"text": " ", "font": "", "size": 0, "flags": 0})
            spans += p["spans"]; prev_x1 = p["bbox"][2]
        text = nfc("".join(s["text"] for s in spans)).strip()
        main = [s for s in spans if s["text"].strip()]
        out.append({"x0": L["pieces"][0]["bbox"][0], "x1": max(p["bbox"][2] for p in L["pieces"]),
                    "y0": L["y0"], "spans": spans, "text": text,
                    "size": max(s["size"] for s in main)})
    return out


def line_html(spans, body_size, notes=False):
    out = []
    for s in spans:
        t = nfc(s["text"])
        m = re.fullmatch(r"\s*\[(\d+)\]\s*", t)
        if notes and m and s["size"] and s["size"] < body_size - 2:  # note marker "[n]"
            out.append(' <a href="%s#n%s">[%s]</a> ' % (NOTES_HREF, m.group(1), m.group(1)))
        elif s["size"] and s["size"] < body_size - 3 and t.strip():  # "1)" superscript
            out.append('<span class="sup">%s</span>' % esc(t.strip()))
        else:
            out.append(span_html(dict(s, text=t)) if s["font"] else " ")
    return "".join(out)


def tidy(h):
    for tag in ("b", "i"):
        h = re.sub(r"</%s>(\s*)<%s>" % (tag, tag), r"\1", h)
    h = re.sub(r"\s+", " ", h).strip()
    return re.sub(r"</a> ([,.;:])", r"</a>\1", h)


def pdf_sections(doc, cfg, pages):
    """[(label, title, [html])] following the plan's section start pages."""
    starts = {s["page"]: s for s in cfg["sections"]}
    head_re = re.compile(cfg.get("head_re", r"^[IVXL]+$"))
    head_max_y = cfg.get("head_max_y", 0)
    indent_x, center_x = cfg.get("indent_x", 1e9), cfg.get("center_x", 1e9)
    notes = cfg.get("notes_page") is not None
    sections, cur = [], None
    para, fns = None, []

    def close():
        nonlocal para, fns
        if para:
            body = tidy(" ".join(para["h"]))
            for a, b in cfg.get("replace", {}).items():
                body = body.replace(a, b)
            cls = para["cls"]
            if not cls and re.fullmatch(r"<b>.*</b>", body) and "</b>" not in body[3:-4]:
                cls = "ct"
            cur[2].append("<p%s>%s</p>" % (' class="%s"' % cls if cls else "", body))
        para = None
        for f in fns:
            cur[2].append('<p class="fn">%s</p>' % tidy(f))
        fns = []

    for pn in pages:
        page = doc[pn]
        if pn in starts:
            if cur:
                close()
            s = starts[pn]
            cur = (s["label"], s["title"], [])
            sections.append(cur)
        if cur is None:
            raise SystemExit("pdf part: no section starts at or before page %d" % pn)
        lines = visual_lines(page, cfg.get("max_y", {}).get(str(pn), cfg.get("drop_below_y", 1e9)))
        body_size = max((l["size"] for l in lines), key=lambda z: sum(1 for l in lines if l["size"] == z), default=12)
        prev_y = None
        for l in lines:
            # printed heading lines (numeral, all-caps title) are replaced by the plan's title
            if pn in starts and l["y0"] < head_max_y and (head_re.match(l["text"]) or l["text"] == l["text"].upper()):
                continue
            gap = prev_y is not None and l["y0"] - prev_y > 2.2 * l["size"]
            prev_y = l["y0"]
            h = line_html(l["spans"], body_size, notes)
            if l["size"] <= cfg.get("fn_max_size", 0) and l["y0"] >= cfg.get("fn_min_y", 0):
                if set(l["text"]) <= set("_ "):
                    continue
                if re.match(r"(\*|\d+\))", l["text"]) or not fns:
                    fns.append(h)
                else:
                    fns[-1] += " " + h
                continue
            if re.fullmatch(r"_+", l["text"]):
                continue
            x = l["x0"]
            if x >= center_x:
                close()
                para = {"cls": "center", "h": [h]}
                close()
            elif x >= indent_x or para is None or gap:
                close()
                para = {"cls": "", "h": [h]}
            else:
                para["h"].append(h)
        if para is None:
            close()  # flush footnotes of a page that ended on a closed paragraph
    close()
    return sections


def notes_blocks(doc, pn):
    text = nfc(doc[pn].get_text())
    parts = re.split(r"\[(\d+)\]", text)
    out = []
    for i in range(1, len(parts) - 1, 2):
        out.append('<p class="fn" id="n%s">[%s] %s</p>' % (parts[i], parts[i], esc(re.sub(r"\s+", " ", parts[i + 1]).strip())))
    return out


# ---------------------------------------------------------------- Markdown
def md_inline(t):
    t = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>|~])", lambda m: "\x00%d\x00" % ord(m.group(1)), t)
    t = esc(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    return re.sub("\x00(\\d+)\x00", lambda m: esc(chr(int(m.group(1)))), t)


def md_blocks(lines):
    """Small Markdown subset: #-headings, > quotes, * / - / 1. lists (nested by indent), hard breaks."""
    out, para = [], None

    def close():
        nonlocal para
        if para:
            body = "".join(para["h"]).strip()
            body = re.sub(r"(<br/>\s*)+$", "", body)
            out.append("<p%s>%s</p>" % (' class="%s"' % para["cls"] if para["cls"] else "", body))
        para = None

    for raw in lines:
        line = nfc(raw.rstrip("\n"))
        hard = line.endswith("  ")
        s = line.strip()
        if not s or re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            close(); continue
        m = re.match(r"(#{1,4})\s+(.*)", s)
        if m:
            close()
            lv = min(len(m.group(1)) + 1, 4)
            out.append("<h%d>%s</h%d>" % (lv, md_inline(m.group(2).strip()), lv))
            continue
        if s.startswith(">"):
            t = s.lstrip(">").strip()
            if para is None or para["cls"] != "quote":
                close(); para = {"cls": "quote", "h": []}
            para["h"].append(md_inline(t) + ("<br/>" if hard else " "))
            continue
        m = re.match(r"(\s*)([*-]|\d+\\?\.)\s+(.*)", line)
        if m:
            close()
            indent = len(m.group(1).expandtabs(4))
            lv = min(indent // 2 + 1, 3)
            mark = "•" if m.group(2) in "*-" else m.group(2).replace("\\", "")
            para = {"cls": "li%d" % lv, "h": ["%s %s" % (mark, md_inline(m.group(3).strip())) + ("<br/>" if hard else " ")]}
            continue
        if para is None:
            para = {"cls": "", "h": []}
        para["h"].append(md_inline(s) + ("<br/>" if hard else " "))
    close()
    return out


def md_sections(text):
    """Split at '## '; returns (preamble_lines, [(heading, lines)])."""
    pre, secs = [], []
    for line in text.splitlines():
        m = re.match(r"##\s+(.*)", line)
        if m and not line.startswith("###"):
            secs.append((nfc(m.group(1)).strip(), []))
        elif secs:
            secs[-1][1].append(line)
        else:
            pre.append(line)
    return pre, secs


# ---------------------------------------------------------------- cover
def text_cover(cfg):
    W, H = 528, 792
    heading = cfg["heading"]
    band = 170 if len(heading) <= 2 else 50 + 60 * len(heading)
    im = Image.new("L", (W, H), 255)
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, W, band], fill=0)
    for i, line in enumerate(heading):
        dr.text((W / 2, 65 + 60 * i), line, font=load_font(52, True), fill=255, anchor="mm")
    if cfg.get("subtitle"):
        dr.text((W / 2, band + 45), cfg["subtitle"], font=load_font(28, True), fill=0, anchor="mm")
    y = band + 130
    for mark, text in cfg.get("rows", []):
        dr.text((60, y), mark, font=load_font(26, True), fill=0, anchor="lm")
        dr.text((120, y), text, font=load_font(22), fill=0, anchor="lm")
        y += 70
    if cfg.get("rows"):
        dr.line([W / 2 - 80, y + 10, W / 2 + 80, y + 10], fill=0, width=3)
    if cfg.get("footer"):
        dr.text((W / 2, H - 70), cfg["footer"], font=load_font(20), fill=80, anchor="mm")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85, optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- build
def merge(plan_path, out=None, dump=None, log=print):
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    pdir = os.path.dirname(os.path.abspath(plan_path))
    path = lambda p: os.path.join(pdir, p)

    cover_cfg = plan.get("cover", {})
    if "image" in cover_cfg:
        with open(path(cover_cfg["image"]), "rb") as f:
            cover = jpeg(Image.open(io.BytesIO(f.read())))
    else:
        cover = text_cover({"heading": [plan["title"]], **cover_cfg})
    files, toc, images = [], [], {"images/cover.jpg": cover}

    def add(label, body):
        files.append({"name": "text/%03d.xhtml" % len(files), "body": body})
        toc.append((1, label, files[-1]["name"]))
        return files[-1]["name"]

    def part_page(cfg, img=None):
        body = ["<h1>%s</h1>" % esc(cfg["part"])]
        if cfg.get("part_note"):
            body.append('<p class="part">%s</p>' % esc(cfg["part_note"]))
        if img:
            body.append('<p class="fig"><img src="../%s" alt=""/></p>' % img)
        add(cfg["part"], body)

    for k, part in enumerate(plan["parts"]):
        kind = part["type"]
        if kind == "md":
            with open(path(part["file"]), encoding="utf-8-sig") as f:
                pre, secs = md_sections(f.read())
            labels = part.get("labels")
            if labels is not None and len(labels) != len(secs):
                raise SystemExit("%s: %d '##' sections but %d labels: %s" % (part["file"], len(secs), len(labels), [h for h, _ in secs]))
            if "part" in part:
                add(part["part"], ["<h1>%s</h1>" % esc(part["part"])] + md_blocks(pre)
                    + (['<p class="part">%s</p>' % esc(part["part_note"])] if part.get("part_note") else []))
            for i, (head, lines) in enumerate(secs):
                add(labels[i] if labels else head, ["<h2>%s</h2>" % md_inline(head)] + md_blocks(lines))
        elif kind == "pdf":
            if pymupdf is None:
                raise SystemExit("PDF parts need pymupdf: pip install pymupdf")
            doc = pymupdf.open(path(part["file"]))
            img = None
            if "cover_page" in part:
                img = "images/part%d_cover.jpg" % k
                images[img] = page_jpeg(doc[part["cover_page"]])
            if "part" in part:
                part_page(part, img)
            lo, hi = part["pages"]
            if part.get("skip_pages_matching"):
                rx = re.compile(part["skip_pages_matching"])
                pages = [p for p in range(lo, hi + 1)
                         if not rx.search(doc[p].get_text()) and re.search(r"[a-zA-Z]", doc[p].get_text())]
            else:
                pages = [p for p in range(lo, hi + 1) if p not in part.get("skip_pages", [])]
            first = len(files)
            secs = pdf_sections(doc, part, pages)
            for label, title, body in secs:
                add(label, ["<h2>%s</h2>" % esc(title)] + body)
            if part.get("notes_page") is not None:
                notes = add(part["notes_label"], ["<h2>%s</h2>" % esc(part.get("notes_title", part["notes_label"]))]
                            + notes_blocks(doc, part["notes_page"]))
                for f in files[first:]:
                    f["body"] = [b.replace(NOTES_HREF, "../" + notes) for b in f["body"]]
            log("pdf part %d: %d sections, %d pages" % (k, len(secs), len(pages)))
        else:
            raise SystemExit("unknown part type: %r" % kind)

    # internal link check (`check` only covers TOC targets)
    ids = {f["name"]: set(re.findall(r'id="([^"]+)"', "".join(f["body"]))) for f in files}
    bad = []
    for f in files:
        for href in re.findall(r'href="([^"]+)"', "".join(f["body"])):
            tgt, _, frag = href.partition("#")
            tgt = os.path.normpath(os.path.join("text", tgt)).replace("\\", "/") if tgt.startswith("..") else tgt
            if tgt not in ids or (frag and frag not in ids[tgt]):
                bad.append((f["name"], href))
    log("internal links bad: %s" % (bad or 0))

    if dump:
        os.makedirs(dump, exist_ok=True)
        for k, f in enumerate(files):
            text = re.sub(r"<br/>", "\n", "\n".join(f["body"]))
            text = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</p>|</h\d>", "\n", text)))
            with open(os.path.join(dump, "%03d.txt" % k), "w", encoding="utf-8") as fh:
                fh.write(toc[k][1] + "\n\n" + text)

    out = out or path(plan["out"])
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    pdfmod.write_epub(out, {"title": plan["title"], "author": plan.get("author", ""), "lang": plan.get("lang", "vi")},
                      files, toc, images, css=pdfmod.CSS + EXTRA_CSS)
    log("written: %s | files %d, toc %d, images %d, %d KB" % (out, len(files), len(toc), len(images), os.path.getsize(out) // 1024))
    return out
