"""Resolve the platform chart font and audit text before PNG export."""
from pathlib import Path
import sys

PLATFORM_FONT = "STHeiti" if sys.platform == "darwin" else "Microsoft YaHei" if sys.platform == "win32" else "Noto Sans CJK SC"


def register_platform_font():
    """Register the macOS font asset that an isolated Matplotlib cache may miss."""
    from matplotlib import font_manager

    candidates = list(Path("/System/Library/AssetsV2/com_apple_MobileAsset_Font7").glob("*/AssetData/STHEITI.ttf"))
    for path in candidates:
        try:
            font_manager.fontManager.addfont(str(path))
        except (OSError, ValueError):
            continue
    try:
        return font_manager.findfont(PLATFORM_FONT, fallback_to_default=False)
    except ValueError:
        return None


def audit_figure_fonts(fig, *, normalize=False):
    """Return real font files, substitutions, and glyph gaps for visible text.

    Chat preserves installed source fonts. When the first requested family is
    unavailable, it explicitly substitutes the platform font. Normalization
    applies the same fixed font to every text artist.
    """
    from matplotlib import font_manager
    from matplotlib.font_manager import FontProperties
    from matplotlib.ft2font import FT2Font
    from matplotlib.text import Text

    platform_path = register_platform_font()
    records, substitutions, missing_glyphs = [], [], []
    charmaps = {}
    for text in fig.findobj(match=Text):
        value = text.get_text()
        if not value or not text.get_visible() or text.get_alpha() == 0:
            continue
        requested = list(text.get_fontfamily())
        primary = requested[0] if requested else 'sans-serif'
        original = FontProperties(family=[primary], weight=text.get_fontweight(), style=text.get_fontstyle())
        try:
            font_manager.findfont(original, fallback_to_default=False)
            primary_available = True
        except ValueError:
            primary_available = False
        if normalize or not primary_available:
            if not platform_path:
                raise RuntimeError(f"Platform chart font {PLATFORM_FONT} is unavailable; cannot export with a verified font")
            text.set_fontfamily(PLATFORM_FONT)
        properties = text.get_fontproperties()
        try:
            path = font_manager.findfont(properties, fallback_to_default=False)
        except ValueError as exc:
            raise RuntimeError(f"Cannot resolve font for text {value[:50]!r}: {requested}") from exc
        actual = font_manager.FontProperties(fname=path).get_name()
        item = {'text': value[:120], 'requested_family': primary, 'actual_family': actual,
                'font_file': Path(path).name}
        records.append(item)
        if not normalize and not primary_available:
            substitutions.append({'text': value[:120], 'requested_family': primary,
                                  'selected_family': actual, 'reason': 'original font unavailable'})
        if path not in charmaps:
            charmaps[path] = FT2Font(path).get_charmap()
        # Matplotlib may render mathtext separately; its TeX-like syntax is not
        # a direct glyph request to the surrounding text font.
        if '$' not in value:
            missing = sorted({char for char in value if not char.isspace() and ord(char) not in charmaps[path]})
            if missing:
                missing_glyphs.append({'text': value[:120], 'font': actual,
                                       'characters': ''.join(missing)[:40]})
    return {'platform_font': PLATFORM_FONT, 'fonts': records,
            'substitutions': substitutions, 'missing_glyphs': missing_glyphs}
