"""Font lookup for generated cover pages (Vietnamese needs a real TTF with diacritics)."""
import os

from PIL import ImageFont

_REGULAR = ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf", "arial.ttf", "DejaVuSans.ttf"]
_BOLD = ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]


def load_font(size, bold=False):
    override = os.environ.get("X3BOOK_FONT_BOLD" if bold else "X3BOOK_FONT")
    for path in ([override] if override else []) + (_BOLD if bold else _REGULAR):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)  # no diacritics guaranteed, but never crashes
