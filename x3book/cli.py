"""Command line: `x3book <tune|check|pdf|merge|flashbook|convert>`."""
import argparse
import json
import sys

from . import __version__


def _add_extras(p):
    g = p.add_argument_group("optional clean-ups (ported from epub-to-xtc-converter, off by default)")
    g.add_argument("--epaper", action="store_true", help="enable all four options below")
    g.add_argument("--strip-fonts", action="store_true", help="remove embedded .ttf/.otf/.woff files (CrossVi never uses them)")
    g.add_argument("--clean-css", action="store_true", help="remove CSS float/position/flex/grid/transform and @font-face")
    g.add_argument("--convert-images", action="store_true", help="GIF/WebP/BMP/TIFF -> baseline grayscale JPEG, fix references")
    g.add_argument("--strip-data-uris", action="store_true", help='replace src="data:..." with "#"')


def _extras(a):
    from .epaper import Extras
    if a.epaper:
        return Extras.all()
    return Extras(a.strip_fonts, a.clean_css, a.convert_images, a.strip_data_uris)


def build_parser():
    ap = argparse.ArgumentParser(prog="x3book", description="Tune EPUBs for the Xteink X3 running CrossVi.")
    ap.add_argument("--version", action="version", version="x3book " + __version__)
    sub = ap.add_subparsers(dest="cmd", metavar="<command>")

    p = sub.add_parser("tune", help="optimize an EPUB (images, entities, tables, TOC) with an optional plan",
                       description="SRC may be .epub, .pdf (plan needs a \"pdf\" block) or .azw3 (needs the `mobi` package).")
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("plan", nargs="?", help="plan JSON: relabel / drop / split / chapters_from / pdf")
    _add_extras(p)

    p = sub.add_parser("check", help="report what CrossVi will choke on; exit 1 if there are problems")
    p.add_argument("epub", nargs="+")

    p = sub.add_parser("pdf", help="text PDF -> reflowable EPUB (no tuning pass; use `tune` for both)")
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("plan", help='plan JSON with a "pdf" block (or the block itself)')

    p = sub.add_parser("merge", help="join PDF and Markdown sources into one EPUB, driven by a plan")
    p.add_argument("plan")
    p.add_argument("-o", "--out", help="output path (default: \"out\" in the plan, relative to the plan file)")
    p.add_argument("--dump", metavar="DIR", help="also write one plain-text file per section")

    p = sub.add_parser("flashbook", help="Markdown book summary -> EPUB (build), length check (stats), EPUB -> text (source)")
    fs = p.add_subparsers(dest="fb_cmd", metavar="<build|stats|source>")
    q = fs.add_parser("build", help="book.md -> EPUB (out may be a folder)")
    q.add_argument("md")
    q.add_argument("out")
    q = fs.add_parser("stats", help="word counts and structure")
    q.add_argument("md")
    q = fs.add_parser("source", help="dump an EPUB as plain text per spine file")
    q.add_argument("epub")
    q.add_argument("out")

    p = sub.add_parser("convert", help="azw3/mobi/docx/fb2 -> EPUB via Calibre, then tune (no DRM support)")
    p.add_argument("src")
    p.add_argument("-o", "--out", help='output EPUB (default: "<name> [X3].epub" next to the input)')
    p.add_argument("--plan", help="plan JSON applied in the tune step")
    _add_extras(p)
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = build_parser()
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    if a.cmd == "tune":
        from .tune import tune
        tune(a.src, a.out, a.plan, _extras(a))
    elif a.cmd == "check":
        from .check import check
        bad = 0
        for path in a.epub:
            if len(a.epub) > 1:
                print("== " + path)
            problems = check(path)
            print("RESULT       : " + ("OK" if not problems else "%d problem(s): %s" % (len(problems), "; ".join(problems))))
            bad += bool(problems)
        return 1 if bad else 0
    elif a.cmd == "pdf":
        from . import pdf
        with open(a.plan, encoding="utf-8") as f:
            plan = json.load(f)
        print("pdf -> epub  : files %d, toc %d, images %d" % pdf.convert(a.src, plan.get("pdf", plan), a.out))
    elif a.cmd == "merge":
        from .merge import merge
        merge(a.plan, a.out, a.dump)
    elif a.cmd == "flashbook":
        from . import flashbook
        if a.fb_cmd == "build":
            flashbook.build(a.md, a.out)
        elif a.fb_cmd == "stats":
            flashbook.stats(a.md)
        elif a.fb_cmd == "source":
            flashbook.source(a.epub, a.out)
        else:
            ap.parse_args(["flashbook", "--help"])
    elif a.cmd == "convert":
        from .convert import convert
        convert(a.src, a.out, a.plan, _extras(a))
    return 0
