"""House plotting style: Arial for Latin and a Heiti (黑体) face for CJK, inside figures only.

matplotlib does NOT fall back per glyph in practice: text set in Arial renders CJK as boxes.
So pick the font per string with `label_axes()` / `legend_with_style()`, which use Arial for pure
Latin text and Heiti as soon as a CJK character appears.

Figure captions and body prose are typeset by the report renderer in Songti + Times New Roman,
so plots and captions keep different families on purpose.

Usage:
    from plot_style import apply_plot_style, label_axes, legend_with_style
    apply_plot_style()
    fig, ax = plt.subplots()
    label_axes(ax, title="Euler 与解析解对比", xlabel="步长 dt (s)", ylabel="误差 (mol/L)")
    legend_with_style(ax)
"""
from __future__ import annotations

import re

LATIN_FAMILY = "Arial"
CJK_FILES = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)
_CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef\u3000-\u303f]")


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def cjk_font(size: float | None = None):
    """FontProperties for the first available Heiti face."""
    from matplotlib import font_manager as fm
    for path in CJK_FILES:
        try:
            return fm.FontProperties(fname=path, size=size)
        except Exception:
            continue
    for family in ("Heiti TC", "Songti SC", "Noto Sans CJK SC", "SimHei"):
        try:
            return fm.FontProperties(family=family, size=size)
        except Exception:
            continue
    return fm.FontProperties(size=size)


def font_for(text: str, size: float | None = None):
    from matplotlib import font_manager as fm
    return cjk_font(size) if has_cjk(text) else fm.FontProperties(family=LATIN_FAMILY, size=size)


def apply_plot_style() -> dict:
    import matplotlib
    from matplotlib import font_manager as fm
    names = {font.name for font in fm.fontManager.ttflist}
    latin = LATIN_FAMILY if LATIN_FAMILY in names else "DejaVu Sans"
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": [latin],
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    })
    return {"latin": latin, "cjk_file": next((p for p in CJK_FILES if __import__("os").path.exists(p)), None)}


def label_axes(ax, *, title: str | None = None, xlabel: str | None = None, ylabel: str | None = None,
               size: float = 10) -> None:
    """Set axis text with the correct family per string."""
    if title is not None:
        ax.set_title(title, fontproperties=font_for(title, size + 1))
    if xlabel is not None:
        ax.set_xlabel(xlabel, fontproperties=font_for(xlabel, size))
    if ylabel is not None:
        ax.set_ylabel(ylabel, fontproperties=font_for(ylabel, size))


def legend_with_style(ax, **kwargs):
    _handles, texts = ax.get_legend_handles_labels()
    prop = cjk_font(kwargs.pop("fontsize", 8)) if any(has_cjk(str(t)) for t in texts) else None
    kwargs.setdefault("frameon", False)
    return ax.legend(prop=prop, **kwargs) if prop else ax.legend(**kwargs)


if __name__ == "__main__":
    print(apply_plot_style())
