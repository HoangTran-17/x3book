"""Optional clean-ups ported from bigbag/epub-to-xtc-converter (MIT, see NOTICE).

All off by default so `tune` output stays identical to the plain pipeline.
CrossVi ignores most CSS, but these cases still cost space or break layout:
  - embedded fonts (CrossVi never uses them)
  - CSS float / position / flex / grid / transform (no layout engine for them)
  - WebP / GIF / BMP / TIFF images (CrossVi decodes only JPEG and PNG)
  - base64 data: URIs in src (large inline blobs)
"""
import io
import posixpath
import re
from dataclasses import dataclass, fields

from PIL import Image

from .core import CONTENT_RE, MAX_SIDE

FONT_RE = re.compile(r"\.(ttf|otf|woff2?)$", re.I)
CONVERT_RE = re.compile(r"\.(gif|webp|bmp|tiff?)$", re.I)


@dataclass
class Extras:
    strip_fonts: bool = False
    clean_css: bool = False
    convert_images: bool = False
    strip_data_uris: bool = False

    @classmethod
    def all(cls):
        return cls(**{f.name: True for f in fields(cls)})

    def any(self):
        return any(getattr(self, f.name) for f in fields(self))


# ---------------- CSS ----------------
# (?<![\w-]) keeps "text-transform" / "-webkit-..." intact; [^;}] stops at the end of the block.
_DECLS = [
    re.compile(r"(?<![\w-])float\s*:\s*[^;}]+;?", re.I),
    re.compile(r"(?<![\w-])position\s*:\s*(?:fixed|absolute|relative|sticky)[^;}]*;?", re.I),
    re.compile(r"(?<![\w-])display\s*:\s*(?:flex|grid|inline-flex|inline-grid)[^;}]*;?", re.I),
    re.compile(r"(?<![\w-])transform\s*:[^;}]*;?", re.I),
]


def _strip_at_blocks(css, at_rule):
    """Remove `@rule ... { ... }` blocks with balanced braces."""
    out, i = [], 0
    while i < len(css):
        idx = css.find(at_rule, i)
        if idx == -1:
            out.append(css[i:])
            break
        out.append(css[i:idx])
        brace = css.find("{", idx)
        if brace == -1:
            out.append(css[idx:])
            break
        depth, j = 1, brace + 1
        while j < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        i = j
    return "".join(out)


def clean_css(css):
    for pat in _DECLS:
        css = pat.sub("", css)
    for at in ("@font-face", "@keyframes"):
        css = _strip_at_blocks(css, at)
    return css


def clean_inline_styles(markup):
    def sub(m):
        return re.sub(r"\s+", " ", clean_css(m.group(0))).replace('style=" ', 'style="')
    return re.sub(r'style="[^"]*"', sub, markup, flags=re.I)


def strip_data_uris(markup):
    markup = re.sub(r'(src\s*=\s*")data:[^"]+(")', r"\1#\2", markup, flags=re.I)
    return re.sub(r"(src\s*=\s*')data:[^']+(')", r"\1#\2", markup, flags=re.I)


# ---------------- book-level steps ----------------
def _drop_manifest_item(book, full):
    href = re.escape(posixpath.relpath(full, book.base))
    book.opf = re.sub(r'\s*<item\b[^>]*\bhref="%s"[^>]*/>' % href, "", book.opf)


def strip_fonts(book):
    gone = [n for n in book.order if FONT_RE.search(n)]
    for n in gone:
        book.order.remove(n)
        del book.data[n]
        _drop_manifest_item(book, n)
    return len(gone)


def _ref_pattern(old_rel):
    return re.compile(r"(?<![\w./-])" + re.escape(old_rel))


def convert_images(book):
    """GIF/WebP/BMP/TIFF -> baseline grayscale JPEG (<= MAX_SIDE); rewrite every reference."""
    renames = {}
    for name in list(book.order):
        if not CONVERT_RE.search(name):
            continue
        try:
            im = Image.open(io.BytesIO(book.data[name]))
            im.load()
        except Exception:
            continue  # unreadable: leave it, `check` and the device will show it
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            im = Image.alpha_composite(Image.new("RGBA", im.size, "white"), im)
        im = im.convert("L")
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85, optimize=True, progressive=False)
        new = re.sub(r"\.[^.]+$", ".jpg", name)
        while new in book.data:
            new = new[:-4] + "_x3.jpg"
        book.order[book.order.index(name)] = new
        del book.data[name]
        book.data[new] = buf.getvalue()
        renames[name] = new
    if not renames:
        return 0
    for fname in list(book.order) + [book.opf_path]:
        is_opf = fname == book.opf_path
        if not (is_opf or CONTENT_RE.search(fname) or fname.lower().endswith((".css", ".ncx"))):
            continue
        text = book.opf if is_opf else book.data[fname].decode("utf8")
        for old, new in renames.items():
            old_rel, new_rel = posixpath.relpath(old, posixpath.dirname(fname) or "."), posixpath.relpath(new, posixpath.dirname(fname) or ".")
            text = _ref_pattern(old_rel).sub(lambda _m, r=new_rel: r, text)
        if is_opf:
            for new in renames.values():
                href = re.escape(posixpath.relpath(new, book.base))
                text = re.sub(r'(<item\b[^>]*\bhref="%s"[^>]*?\bmedia-type=")[^"]*(")' % href, r"\1image/jpeg\2", text)
                text = re.sub(r'(<item\b[^>]*?\bmedia-type=")[^"]*("[^>]*\bhref="%s")' % href, r"\1image/jpeg\2", text)
            book.opf = text
        else:
            book.data[fname] = text.encode("utf8")
    return len(renames)


def apply(book, extras):
    """Run the enabled steps; return log lines."""
    lines = []
    if extras.strip_fonts:
        lines.append("fonts removed: %d" % strip_fonts(book))
    if extras.clean_css:
        n = 0
        for name in book.order:
            low = name.lower()
            if low.endswith(".css"):
                s = book.data[name].decode("utf8")
                t = clean_css(s)
            elif CONTENT_RE.search(name):
                s = book.data[name].decode("utf8")
                t = clean_inline_styles(s)
            else:
                continue
            if t != s:
                book.data[name] = t.encode("utf8")
                n += 1
        lines.append("css cleaned  : %d file" % n)
    if extras.strip_data_uris:
        n = 0
        for name in book.order:
            if CONTENT_RE.search(name):
                s = book.data[name].decode("utf8")
                t = strip_data_uris(s)
                if t != s:
                    book.data[name] = t.encode("utf8")
                    n += 1
        lines.append("data uris    : %d file" % n)
    if extras.convert_images:
        lines.append("images -> jpg: %d" % convert_images(book))
    return lines
