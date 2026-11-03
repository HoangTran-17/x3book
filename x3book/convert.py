"""`x3book convert`: azw3 / mobi / docx / fb2 -> EPUB with Calibre's `ebook-convert`, then `tune`."""
import os
import shutil
import subprocess
import sys
import tempfile

from .tune import tune

SUPPORTED = (".azw3", ".azw", ".mobi", ".docx", ".fb2")

INSTALL_HINT = (
    "Calibre `ebook-convert` not found.\n"
    "  Install Calibre (https://calibre-ebook.com/download), then make sure `ebook-convert` is on PATH.\n"
    "  Windows: winget install --id calibre.calibre   (default path: C:\\Program Files\\Calibre2)\n"
    "  Or set X3BOOK_EBOOK_CONVERT to the full path of ebook-convert."
)
DRM_HINT = (
    "Calibre could not read this file. If it is DRM-protected (e.g. bought on Amazon), x3book does not\n"
    "support it and will not remove DRM. Use a DRM-free copy."
)


def find_ebook_convert():
    env = os.environ.get("X3BOOK_EBOOK_CONVERT")
    if env and os.path.isfile(env):
        return env
    exe = shutil.which("ebook-convert")
    if exe:
        return exe
    candidates = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            candidates.append(os.path.join(base, "Calibre2", "ebook-convert.exe"))
            candidates.append(os.path.join(base, "Programs", "Calibre2", "ebook-convert.exe"))
    candidates.append("/Applications/calibre.app/Contents/MacOS/ebook-convert")
    return next((c for c in candidates if os.path.isfile(c)), None)


def convert(src, out=None, plan=None, extras=None, log=print):
    if not src.lower().endswith(SUPPORTED):
        raise SystemExit("unsupported input %r; expected one of %s (for .pdf use `x3book pdf`; .epub use `x3book tune`)"
                         % (os.path.basename(src), ", ".join(SUPPORTED)))
    if not os.path.isfile(src):
        raise SystemExit("file not found: " + src)
    exe = find_ebook_convert()
    if not exe:
        raise SystemExit(INSTALL_HINT)
    if out is None:
        out = os.path.splitext(src)[0] + " [X3].epub"
    tmp = os.path.join(tempfile.mkdtemp(prefix="x3book-"), "converted.epub")
    log("calibre      : %s" % exe)
    res = subprocess.run([exe, src, tmp], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0 or not os.path.isfile(tmp):
        msg = (res.stderr or "") + (res.stdout or "")
        sys.stderr.write(msg[-2000:])
        raise SystemExit(DRM_HINT if "drm" in msg.lower() else "ebook-convert failed (exit %s)" % res.returncode)
    tune(tmp, out, plan, extras, log)
    return out
