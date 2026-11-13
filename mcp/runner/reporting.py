"""Bounded, offline, fixed-layout PDF rendering; Markdown is treated as data.

A4 pages use embedded TrueType fonts, with optional local CJK fallback. Missing
characters are rendered visibly as [U+XXXX] and listed in the return value.
No HTML, Markdown links, scripts, or remote images are evaluated. The caller
owns figure registration/verification, immutable staging, and source retention.
"""
from __future__ import annotations

from functools import lru_cache
import html
from io import BytesIO
from pathlib import Path
import re
import threading
import unicodedata

import reportlab
from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError
from reportlab.pdfgen.canvas import Canvas

MAX_TEXT_CHARS = 200_000
MAX_FIGURES = 20
MAX_PAGES = 500
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
# Reentrant: _load_fallbacks holds the lock while calling _register_once, which
# acquires it again. A plain Lock deadlocks the whole renderer on the first call.
_FONT_LOCK = threading.RLock()

# ReportLab raises `TTFError: postscript outlines are not supported` on .otf, so the
# candidate chains below deliberately list only TrueType-outline files (.ttf/.ttc).
# That rules out Source Han / Noto CJK .otf builds, which is why each chain carries
# several platform spellings rather than one "correct" font name.
_LATIN_SERIF = (
    # macOS
    ("/System/Library/Fonts/Supplemental/Times New Roman.ttf", None, False),
    ("/Library/Fonts/Times New Roman.ttf", None, False),
    # Linux (metric-compatible with Times)
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf", None, False),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", None, False),
    # Windows
    ("C:/Windows/Fonts/times.ttf", None, False),
)
_LATIN_SERIF_BOLD = (
    ("/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf", None, False),
    ("/Library/Fonts/Times New Roman Bold.ttf", None, False),
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf", None, False),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", None, False),
    ("C:/Windows/Fonts/timesbd.ttf", None, False),
)
_LATIN_SERIF_ITALIC = (
    ("/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf", None, False),
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf", None, False),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf", None, False),
    ("C:/Windows/Fonts/timesi.ttf", None, False),
)
_LATIN_SERIF_BOLD_ITALIC = (
    ("/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf", None, False),
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf", None, False),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf", None, False),
    ("C:/Windows/Fonts/timesbi.ttf", None, False),
)
_MONO = (
    ("/System/Library/Fonts/Menlo.ttc", 0, False),
    ("/System/Library/Fonts/Monaco.ttf", None, False),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", None, False),
    ("C:/Windows/Fonts/consola.ttf", None, False),
)

# CJK body faces: a serif (宋体 role) and a sans/heavy face (黑体 role). The pair is
# what makes "Chinese in Songti, Latin in Times" work, because Times has no CJK
# glyphs at all: every Chinese character resolves through this chain per glyph.
_CJK_SERIF = (
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 3, True),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 4, True),
    ("/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc", 0, True),
    ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 0, True),
    ("/usr/share/fonts/truetype/arphic/uming.ttc", 0, True),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0, True),
    ("C:/Windows/Fonts/simsun.ttc", 0, True),
)
_CJK_SANS = (
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1, True),
    ("/System/Library/Fonts/STHeiti Light.ttc", 1, True),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0, True),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 0, True),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0, True),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0, True),
    ("C:/Windows/Fonts/msyhbd.ttc", 0, True),
    ("C:/Windows/Fonts/msyh.ttc", 0, True),
)

# A profile is a named intent, not a font menu. The agent picks the intent from what
# the report actually contains; the resolver turns it into concrete registered faces.
FONT_PROFILES = {
    # Chinese body in a serif, Latin in Times: the scientific default.
    "scientific-cjk": {"latin": _LATIN_SERIF, "latin_bold": _LATIN_SERIF_BOLD,
                       "latin_italic": _LATIN_SERIF_ITALIC,
                       "latin_bold_italic": _LATIN_SERIF_BOLD_ITALIC,
                       "cjk": _CJK_SERIF, "cjk_bold": _CJK_SANS, "mono": _MONO},
    # Heavy sans headings and sans body: for slide-like or poster-like summaries.
    "cjk-sans": {"latin": _LATIN_SERIF, "latin_bold": _LATIN_SERIF_BOLD,
                 "latin_italic": _LATIN_SERIF_ITALIC,
                 "latin_bold_italic": _LATIN_SERIF_BOLD_ITALIC,
                 "cjk": _CJK_SANS, "cjk_bold": _CJK_SANS, "mono": _MONO},
    # Latin-only reports still get a CJK fallback so a stray character never vanishes.
    "latin-only": {"latin": _LATIN_SERIF, "latin_bold": _LATIN_SERIF_BOLD,
                   "latin_italic": _LATIN_SERIF_ITALIC,
                   "latin_bold_italic": _LATIN_SERIF_BOLD_ITALIC,
                   "cjk": _CJK_SERIF, "cjk_bold": _CJK_SANS, "mono": _MONO},
}
DEFAULT_PROFILE = "scientific-cjk"

_FALLBACK_CJK = _CJK_SERIF + _CJK_SANS


def _register_once(name: str, path: str, index: int | None) -> bool:
    """Register one face, tolerating a font that is absent or has CFF outlines."""
    if name in pdfmetrics.getRegisteredFontNames():
        return True
    if not Path(path).is_file():
        return False
    try:
        with _FONT_LOCK:
            face = TTFont(name, path, subfontIndex=index) if index is not None else TTFont(name, path)
            pdfmetrics.registerFont(face)
        glyphs = getattr(pdfmetrics.getFont(name).face, "charToGlyph", {})
        return bool(glyphs.get(ord("A")) or glyphs.get(ord("中")))
    except Exception:
        # Absent, CFF-outlined, or otherwise unusable: try the next candidate.
        return False


def _first_usable(name: str, chain) -> str | None:
    for path, index, _cjk in chain:
        if _register_once(name, path, index):
            return name
    return None


def _load_fallbacks() -> tuple[str, ...]:
    """Every CJK-capable face we could register, used per glyph when a role lacks one."""
    names: list[str] = []
    with _FONT_LOCK:
        for position, (path, index, _cjk) in enumerate(_FALLBACK_CJK):
            name = f"NotebookCJK{position}"
            if name in names:
                continue
            if _register_once(name, path, index):
                if _has(ord("中"), name):
                    names.append(name)
    return tuple(names)


def _has(codepoint: int, font: str) -> bool:
    try:
        glyphs = getattr(pdfmetrics.getFont(font).face, "charToGlyph", None)
    except Exception:
        return False
    return None if glyphs is None else bool(glyphs.get(codepoint))


@lru_cache(maxsize=8)
def resolve_fonts(profile: str = DEFAULT_PROFILE) -> dict:
    """Turn a profile name into concrete faces, plus a record of what actually loaded.

    Cached per profile because the result is immutable: the old module-level mutable
    FONTS dict meant two reports rendered with different fonts could corrupt each
    other inside one process.
    """
    if profile == "auto":
        profile = DEFAULT_PROFILE
    if profile not in FONT_PROFILES:
        raise ValueError(f"Unknown font profile {profile!r}; choose one of "
                         f"{sorted(FONT_PROFILES)} or 'auto'")
    spec = FONT_PROFILES[profile]
    resolved: dict[str, str] = {}
    used: dict[str, str] = {}
    notes: list[str] = []

    def take(role: str, name: str, chain) -> None:
        found = _first_usable(name, chain)
        if found:
            resolved[role] = found
            used[role] = Path(chain[0][0]).name if found else ""
        else:
            notes.append(f"{role}: profile face unavailable, fell back")

    take("r", "NotebookSerif", spec["latin"])
    take("b", "NotebookSerifBold", spec["latin_bold"])
    take("i", "NotebookSerifItalic", spec["latin_italic"])
    take("bi", "NotebookSerifBoldItalic", spec["latin_bold_italic"])
    take("m", "NotebookMonoR", spec["mono"])
    for role, suffix in (("mb", "Bold"), ("mi", "Italic")):
        base = resolved.get("m")
        resolved[role] = base if base else ""
    take("songti", "NotebookCJKBody", spec["cjk"])
    take("heiti", "NotebookCJKHeavy", spec["cjk_bold"])

    # Latin slots fall back to bundled Vera, which ships inside reportlab itself.
    directory = Path(reportlab.__file__).parent / "fonts"
    vera = (("NotebookVera", "Vera.ttf"), ("NotebookVeraBold", "VeraBd.ttf"),
            ("NotebookVeraIt", "VeraIt.ttf"), ("NotebookVeraBI", "VeraBI.ttf"))
    for name, filename in vera:
        _register_once(name, str(directory / filename), None)
    registered = set(pdfmetrics.getRegisteredFontNames())
    for role, substitute in (("r", "NotebookVera"), ("b", "NotebookVeraBold"),
                             ("i", "NotebookVeraIt"), ("bi", "NotebookVeraBI")):
        if not resolved.get(role) or resolved[role] not in registered:
            resolved[role] = substitute if substitute in registered else "Helvetica"
            notes.append(f"{role}: fell back to {resolved[role]}")
    if not resolved.get("m") or resolved["m"] not in registered:
        resolved.update({"m": "Courier", "mb": "Courier-Bold", "mi": "Courier-Oblique"})
        notes.append("mono: fell back to Courier")

    fallbacks = _load_fallbacks()
    # A CJK role with no CJK glyphs would silently print tofu; borrow a fallback face.
    for role in ("songti", "heiti"):
        face = resolved.get(role)
        if not face or not _has(ord("中"), face):
            borrowed = next((candidate for candidate in fallbacks if _has(ord("中"), candidate)), None)
            if borrowed:
                resolved[role] = borrowed
                notes.append(f"{role}: borrowed {borrowed}")
            else:
                resolved[role] = resolved["r"]
                notes.append(f"{role}: no CJK face on this machine; Chinese will show as [U+XXXX]")

    return {"profile": profile, "fonts": resolved, "fallbacks": fallbacks,
            "cjk_available": any(_has(ord("中"), resolved.get(role) or "") for role in ("songti", "heiti")),
            "notes": notes,
            "used": {role: resolved.get(role, "") for role in ("r", "b", "i", "bi", "m", "mb", "mi", "songti", "heiti")}}


def font_report(profile: str = DEFAULT_PROFILE) -> dict:
    """Compact description for the report record and the preflight probe."""
    info = resolve_fonts(profile)
    return {"profile": info["profile"], "fonts": dict(info["used"]),
            "cjk_available": info["cjk_available"], "notes": list(info["notes"]),
            "profiles": sorted(FONT_PROFILES)}


_SUBSTITUTABLE = set("₀₁₂₃₄₅₆₇₈₉₊₋⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")

# One exponent is either drawn with real script glyphs or written in caret notation.
# Resolving it per character produced "κ^-¹": the missing minus became "^-" while the
# Latin-1 "¹" stayed a true superscript, so a single exponent looked like two conventions.
_SCRIPT_RUN = re.compile("[" + "".join(re.escape(c) for c in sorted(_SUBSTITUTABLE)) + "]+")

# A record reaches the renderer as Markdown, where an HTML entity is a character.
# Printing "&lt;160" instead of "<160" is a renderer defect, not an authoring one.
_HTML_ENTITY = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]{1,31}|#\d{1,6}|#[xX][0-9a-fA-F]{1,5});")
_CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")


def _unescape(text: str) -> str:
    """Decode the HTML entities a Markdown source legitimately contains."""
    if "&" not in text:
        return text
    return _HTML_ENTITY.sub(lambda match: html.unescape(match.group(0)), text)


def _smart_quotes(text: str) -> str:
    """Straight quotes around Chinese become Chinese quotes.

    Only a pair whose body contains CJK is rewritten, so inch marks, JSON fragments
    and every quote inside a code span keep their literal form.
    """
    if '"' not in text:
        return text

    def pair(match: "re.Match[str]") -> str:
        return "“" + match.group(1) + "”" if _CJK.search(match.group(1)) else match.group(0)

    return re.sub(r'"([^"\n]{1,80})"', pair, text)


@lru_cache(maxsize=4)
def _faces_for(profile: str, kind: str = "prose") -> tuple[str, ...]:
    """Faces that actually draw this kind of text, mirroring _Layout._styled.

    Prose falls back through the Latin faces and the CJK fallbacks; a code block uses
    the mono face for everything except CJK, which `_styled` routes to the CJK face
    regardless of style. Probing code against the mono face alone reported every
    Chinese character inside a fenced block as missing (55 false warnings on one real
    record) while it rendered correctly.
    """
    info = resolve_fonts(profile)
    if kind == "code":
        roles = ("m", "mb", "mi", "songti", "heiti")
    else:
        roles = ("r", "b", "i", "bi", "songti", "heiti")
    faces = [info["fonts"].get(role) or "" for role in roles]
    faces += list(info["fallbacks"])
    return tuple(dict.fromkeys(face for face in faces if face))


def _split_code(text: str) -> tuple[str, str]:
    """Prose with fenced blocks removed, plus the fenced blocks themselves."""
    fences = re.findall(r"^```[^\n]*\n(.*?)^```\s*$", text or "", re.S | re.M)
    prose = re.sub(r"^```[^\n]*\n.*?^```\s*$", "", text or "", flags=re.S | re.M)
    return prose, "\n".join(fences)


def check_glyphs(text: str, profile: str = DEFAULT_PROFILE) -> list[dict]:
    """Characters no face in this profile can draw, with a short context snippet.

    Called from `validate` so a missing glyph is reported before finalizing rather
    than discovered in a delivered PDF. Sub/superscripts are transliterated to caret
    notation, so they are not reported here.
    """
    prose, code = _split_code(text)
    prose_faces, code_faces = _faces_for(profile, "prose"), _faces_for(profile, "code")
    missing: dict[int, int] = {}
    for character in prose:
        if character in "\n\t" or character in _SUBSTITUTABLE:
            continue
        if unicodedata.category(character).startswith("C"):
            continue
        if any(_supports(face, character) for face in prose_faces):
            continue
        missing[ord(character)] = missing.get(ord(character), 0) + 1
    for character in code:
        if character in "\n\t" or unicodedata.category(character).startswith("C"):
            continue
        if any(_supports(face, character) for face in code_faces):
            continue
        missing[ord(character)] = missing.get(ord(character), 0) + 1
    findings = []
    for point, count in sorted(missing.items()):
        character = chr(point)
        haystack = prose if character in prose else code
        position = haystack.find(character)
        start = max(0, position - 20)
        context = haystack[start:position + 21].replace("\n", " ")
        findings.append({"codepoint": f"U+{point:04X}", "character": character,
                         "count": count, "context": context})
    return findings


def _base_fonts(profile: str = DEFAULT_PROFILE) -> tuple[str, str]:
    """Kept for callers that only need the body pair."""
    info = resolve_fonts(profile)
    return info["fonts"]["r"], info["fonts"]["b"]


def _cjk_fonts() -> tuple[str, ...]:
    """Every registered CJK fallback face."""
    return _load_fallbacks()


# Compatibility alias: the resolved default profile. Read-only in practice; new code
# must go through resolve_fonts() so per-report fonts stay independent.
FONTS = resolve_fonts(DEFAULT_PROFILE)["fonts"]


_KEYWORDS = {
    "python": {"def", "class", "return", "if", "elif", "else", "for", "while", "in", "not", "and",
               "or", "import", "from", "as", "with", "try", "except", "finally", "raise", "yield",
               "lambda", "None", "True", "False", "async", "await", "pass", "break", "continue",
               "global", "nonlocal", "assert", "del", "is"},
    "bash": {"if", "then", "else", "elif", "fi", "for", "in", "do", "done", "while", "case", "esac",
             "function", "export", "local", "return", "echo", "cd", "source", "set", "unset"},
    "json": {"true", "false", "null"},
    "yaml": {"true", "false", "null", "yes", "no"},
    "text": set(),
}
_COMMENT = {"python": "#", "bash": "#", "yaml": "#", "json": None, "text": None, "shell": "#"}
_TOKEN = re.compile(r"""(?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(?P<number>\b\d+(?:\.\d+)?\b)|(?P<word>[A-Za-z_][A-Za-z0-9_]*)""")
COLORS = {"plain": (0.12, 0.12, 0.12), "comment": (0.45, 0.47, 0.5), "string": (0.64, 0.11, 0.11),
          "keyword": (0.0, 0.0, 0.72), "number": (0.04, 0.45, 0.3)}


def _tokenize(line: str, language: str):
    """Very small highlighter: comments, strings, numbers and keywords. Unknown text stays plain."""
    lang = (language or "text").strip().lower()
    lang = {"py": "python", "sh": "bash", "shell": "bash", "yml": "yaml", "js": "json"}.get(lang, lang)
    marker = _COMMENT.get(lang)
    cut = len(line)
    if marker:
        quote = None
        for position, character in enumerate(line):
            if quote:
                if character == quote: quote = None
            elif character in "\"'":
                quote = character
            elif line.startswith(marker, position):
                cut = position
                break
    body, tail = line[:cut], line[cut:]
    keywords = _KEYWORDS.get(lang, set())
    tokens, last = [], 0
    for match in _TOKEN.finditer(body):
        if match.start() > last:
            tokens.append((body[last:match.start()], "plain"))
        kind = "string" if match.group("string") else "number" if match.group("number") else (
            "keyword" if match.group("word") in keywords else "plain")
        tokens.append((match.group(0), kind))
        last = match.end()
    if last < len(body):
        tokens.append((body[last:], "plain"))
    if tail:
        tokens.append((tail, "comment"))
    return tokens or [("", "plain")]


def _is_cjk(character: str) -> bool:
    code = ord(character)
    return (0x2E80 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or 0xFF00 <= code <= 0xFFEF
            or 0x3000 <= code <= 0x303F)


def _supports(font: str, character: str) -> bool:
    """True when this font can draw the character. Standard PDF fonts have no glyph table."""
    try:
        face = pdfmetrics.getFont(font).face
    except Exception:
        return False
    glyphs = getattr(face, "charToGlyph", None)
    if glyphs is None:                      # built-in Type1 (Courier, Helvetica): Latin-1 only
        return ord(character) < 256
    return bool(glyphs.get(ord(character)))


class _Layout:
    def __init__(self, canvas: Canvas, profile: str = DEFAULT_PROFILE):
        self.canvas = canvas
        self.fonts = resolve_fonts(profile)
        self.faces = self.fonts["fonts"]
        self.fallbacks = self.fonts["fallbacks"]
        self.regular, self.bold = self.faces["r"], self.faces["b"]
        self.width, self.height = A4
        self.margin = 48.0
        self.usable = self.width - 2 * self.margin
        self.y = self.height - self.margin
        self.page = 1
        self.drawn = False
        self.unsupported: set[int] = set()
        self.transliterated: set[int] = set()   # rendered as caret notation, not missing
        self.glyph_cache: dict[tuple[str, bool], tuple[str, str]] = {}
        self.width_cache: dict[tuple[str, str, float], float] = {}

    def _footer(self) -> None:
        """Page number in the CJK body face: Times has no CJK glyphs and would emit .notdef."""
        self.canvas.setFont(self.faces.get("songti", self.regular), 8)
        self.canvas.setFillGray(0.45)
        self.canvas.drawRightString(self.width - self.margin, 25, f"第 {self.page} 页")
        self.canvas.setFillGray(0)

    def need(self, height: float) -> None:
        if height > self.height - 2 * self.margin:
            raise ValueError("A report block exceeds the printable page height")
        if self.y - height >= self.margin:
            return
        if self.page >= MAX_PAGES:
            raise ValueError(f"Report exceeds {MAX_PAGES} pages")
        self._footer()
        self.canvas.showPage()
        self.page += 1
        self.y = self.height - self.margin
        self.drawn = False

    def new_page(self) -> None:
        if self.page >= MAX_PAGES:
            raise ValueError(f"Report exceeds {MAX_PAGES} pages")
        self._footer()
        self.canvas.showPage()
        self.page += 1
        self.y = self.height - self.margin
        self.drawn = False

    def glyph(self, character: str, bold: bool) -> tuple[str, str]:
        key = (character, bold)
        if key not in self.glyph_cache:
            base = self.bold if bold else self.regular
            # Invisible format/control characters are explicit, not hidden.
            if unicodedata.category(character).startswith("C"):
                font = None
            elif _supports(base, character):
                font = base
            else:
                font = next((candidate for candidate in _cjk_fonts()
                             if _supports(candidate, character)), None)
            if font is None:
                replacement = self._substitute(character)
                if replacement != character:
                    self.transliterated.add(ord(character))
                    shown = replacement
                else:
                    self.unsupported.add(ord(character))
                    shown = f"[U+{ord(character):04X}]"
                self.glyph_cache[key] = (base, shown)
            else:
                self.glyph_cache[key] = (font, character)
        return self.glyph_cache[key]

    def lines(self, text: str, size: float, bold: bool):
        """Greedy character wrapping with word breaks; no quadratic long lines."""
        line: list[tuple[str, str, float]] = []
        width = 0.0
        for character in text.expandtabs(4):
            font, display = self.glyph(character, bold)
            key = (font, display, size)
            if key not in self.width_cache:
                self.width_cache[key] = pdfmetrics.stringWidth(display, font, size)
            atom_width = self.width_cache[key]
            if line and width + atom_width > self.usable:
                split = next((i + 1 for i in range(len(line) - 1, -1, -1)
                              if line[i][1].isspace()), len(line))
                yield line[:split]
                line = line[split:]
                width = sum(atom[2] for atom in line)
                # A prefix moved after a word break may itself fill the line.
                if line and width + atom_width > self.usable:
                    yield line
                    line, width = [], 0.0
            line.append((font, display, atom_width))
            width += atom_width
        if line:
            yield line

    def text(self, text: str, *, size: float = 10, bold: bool = False,
             after: float = 5) -> None:
        leading = size * 1.4
        for line in self.lines(text, size, bold):
            self.need(leading)
            self.y -= leading
            x = self.margin
            # Draw contiguous same-font runs for searchable/extractable text.
            run_font, run_text, run_width = None, [], 0.0
            for font, display, atom_width in line + [(None, "", 0)]:
                if font != run_font and run_text:
                    self.canvas.setFont(run_font, size)
                    self.canvas.drawString(x, self.y, "".join(run_text))
                    x += run_width
                    run_text, run_width = [], 0.0
                run_font = font
                run_text.append(display)
                run_width += atom_width
        self.y -= after
        self.drawn = True

    def _substitute(self, text: str) -> str:
        """Rewrite scripts as caret notation when the fonts cannot draw them."""
        import re as _re
        sub = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
               "₆": "6", "₇": "7", "₈": "8", "₉": "9", "₊": "+", "₋": "-"}
        sup = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5",
               "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁺": "+", "⁻": "-"}

        def caret(match: "_re.Match[str]") -> str:
            return "^" + "".join(sup[c] for c in match.group(0))

        def under(match: "_re.Match[str]") -> str:
            return "_" + "".join(sub[c] for c in match.group(0))

        text = _re.sub("[" + "".join(sup) + "]+", caret, text)
        return _re.sub("[" + "".join(sub) + "]+", under, text)

    def _drawable(self, character: str, style: str) -> bool:
        """True when some face available for this style can draw the character."""
        if unicodedata.category(character).startswith("C"):
            return True
        key_style = "m" if style == "m" else ("b" if "b" in style else "r")
        if _is_cjk(character):
            face = self.faces["heiti"] if key_style in ("b", "bi") else self.faces["songti"]
        else:
            face = self.faces.get(key_style, self.faces["r"])
        return _supports(face, character) or any(_supports(f, character) for f in self.fallbacks)

    def _script_safe(self, text: str, style: str) -> str:
        """Rewrite a sub/superscript run as a whole when any of its glyphs is missing.

        Resolving an exponent per character produced "κ^-¹": the missing minus became
        "^-" while the Latin-1 "¹" stayed a real superscript, so one exponent read as
        two different conventions. A run is now either fully drawn or fully caret.
        """
        if not _SCRIPT_RUN.search(text):
            return text

        def whole(match: "re.Match[str]") -> str:
            run = match.group(0)
            if all(self._drawable(ch, style) for ch in run):
                return run
            self.transliterated.update(ord(ch) for ch in run)
            return self._substitute(run)

        return _SCRIPT_RUN.sub(whole, text)

    def _styled(self, character: str, style: str) -> tuple[str, str]:
        key = (character, style)
        cached = self.glyph_cache.get(key)
        if cached is not None:
            return cached
        key_style = "b" if "b" in style else "r"
        if style == "m":
            key_style = "m"
        if unicodedata.category(character).startswith("C"):
            font = None
        elif _is_cjk(character):
            font = self.faces["heiti"] if key_style in ("b", "bi") else self.faces["songti"]
            if not _supports(font, character):
                font = next((c for c in self.fallbacks if _supports(c, character)), None)
        else:
            font = self.faces.get(key_style, self.faces["r"])
            if not _supports(font, character):
                font = next((c for c in self.fallbacks if _supports(c, character)), None)
        if font is None:
            fallback = self.faces.get(key_style, self.faces["r"])
            replacement = self._substitute(character)
            if replacement != character:
                self.transliterated.add(ord(character))
                shown = replacement
            else:
                self.unsupported.add(ord(character))
                shown = f"[U+{ord(character):04X}]"
            self.glyph_cache[key] = (fallback, shown)
        else:
            self.glyph_cache[key] = (font, character)
        return self.glyph_cache[key]

    def _atoms_raw(self, text: str, size: float, indent: float):
        """Same greedy wrap, but the text is literal: no inline Markdown parsing."""
        atoms = []
        for character in self._script_safe(text, "m").expandtabs(4):
            font, display = self._styled(character, "m")
            key = (font, display, size)
            if key not in self.width_cache:
                self.width_cache[key] = pdfmetrics.stringWidth(display, font, size)
            atoms.append((font, display, self.width_cache[key], "m"))
        usable = self.usable - indent
        line, width, lines = [], 0.0, []
        for atom in atoms:
            if line and width + atom[2] > usable:
                lines.append(line)
                line, width = [], 0.0
            line.append(atom)
            width += atom[2]
        if line:
            lines.append(line)
        return lines

    def measure(self, text: str, size: float, style: str = "r") -> float:
        total = 0.0
        for character in self._script_safe(_plain(text), style):
            font, display = self._styled(character, style)
            key = (font, display, size)
            if key not in self.width_cache:
                self.width_cache[key] = pdfmetrics.stringWidth(display, font, size)
            total += self.width_cache[key]
        return total

    def _atoms(self, text: str, size: float, indent: float, force_bold: bool = False):
        """Split styled text into atoms and greedily wrap them into lines."""
        atoms = []
        for chunk, style in _parse_inline(text):
            if style == "math":
                try:
                    _png, width_pt, _height_pt, _depth_pt = math_image(chunk, size, force_bold)
                except Exception:
                    # Unrenderable TeX is shown literally rather than dropped silently.
                    for character in ("$" + chunk + "$"):
                        font, display = self._styled(character, "r")
                        key = (font, display, size)
                        self.width_cache.setdefault(key, pdfmetrics.stringWidth(display, font, size))
                        atoms.append((font, display, self.width_cache[key], "r"))
                    continue
                atoms.append((None, chunk, width_pt, "math"))
                continue
            if force_bold and style == "r":
                style = "b"
            scale = 0.72 if style == "sup" else 1.0
            for character in self._script_safe(chunk, style).expandtabs(4):
                font, display = self._styled(character, style)
                key = (font, display, size)
                if key not in self.width_cache:
                    self.width_cache[key] = pdfmetrics.stringWidth(display, font, size)
                atoms.append((font, display, self.width_cache[key] * scale, style))
        usable = self.usable - indent
        line, width, lines = [], 0.0, []
        for atom in atoms:
            if line and width + atom[2] > usable:
                split = next((i + 1 for i in range(len(line) - 1, -1, -1) if line[i][1].isspace()), len(line))
                lines.append(line[:split])
                line = line[split:]
                width = sum(item[2] for item in line)
                if line and width + atom[2] > usable:
                    lines.append(line)
                    line, width = [], 0.0
            line.append(atom)
            width += atom[2]
        if line:
            lines.append(line)
        return lines

    def rich(self, text: str, *, size: float = 10, indent: float = 0, after: float = 6,
             bold: bool = False) -> None:
        """Draw styled runs: bold, italic, bold-italic, inline code, strike, underline."""
        leading = size * 1.45
        if text.strip():
            self.drawn = True
        for line in self._atoms(text, size, indent, force_bold=bold):
            self.need(leading)
            self.y -= leading
            x = self.margin + indent
            run_font, run_text, run_width, run_style = None, [], 0.0, None

            def flush() -> None:
                nonlocal x, run_font, run_text, run_width, run_style
                # A run is only drawable when it carries both text and a resolved font;
                # the sentinel atom and a just-drawn formula both leave it empty.
                if not run_text or run_font is None:
                    run_text, run_width = [], 0.0
                    return
                raise_by = size * 0.34 if (run_style or "") == "sup" else 0.0
                self.canvas.setFont(run_font, size * 0.72 if (run_style or "") == "sup" else size)
                self.canvas.drawString(x, self.y + raise_by, "".join(run_text))
                if run_style and "u" in run_style:
                    self.canvas.setLineWidth(0.6)
                    self.canvas.line(x, self.y - 1.6, x + run_width, self.y - 1.6)
                if run_style and "s" in run_style:
                    self.canvas.setLineWidth(0.6)
                    self.canvas.line(x, self.y + size * 0.32, x + run_width, self.y + size * 0.32)
                x += run_width
                run_text, run_width = [], 0.0

            for font, display, atom_width, style in line + [(None, "", 0, None)]:
                if font is None and style is None:
                    continue                      # sentinel: only flushes the last run
                if style == "math":
                    # Flush the surrounding prose first, then stamp the rendered formula
                    # on the same baseline so an inline expression reads as text.
                    flush()
                    run_font, run_style = font, style
                    try:
                        png, width_pt, height_pt, depth_pt = math_image(display, size, bold)
                    except Exception:
                        self.canvas.setFont(self.regular, size)
                        self.canvas.drawString(x, self.y, "$" + display + "$")
                        x += atom_width
                        continue
                    baseline = self.y - depth_pt + size * 0.22
                    self.canvas.drawImage(ImageReader(BytesIO(png)), x, baseline,
                                          width=width_pt, height=height_pt, mask="auto")
                    x += width_pt
                    continue
                if (font, style) != (run_font, run_style):
                    flush()
                run_font, run_style = font, style
                run_text.append(display)
                run_width += atom_width
            flush()
        self.y -= after

    def code_block(self, lines: list[str], *, size: float = 8.5, after: float = 8,
                   language: str = "text") -> None:
        leading = size * 1.35
        padding = 5
        body: list[list[tuple[str, str, float, str, str]]] = []
        usable = self.usable - padding * 2
        for raw in lines:
            atoms: list[tuple[str, str, float, str, str]] = []
            tokens = _tokenize(raw, language)
            if not tokens:
                body.append([])
                continue
            for chunk, kind in tokens:
                for line_atoms in self._atoms_raw(chunk, size, 0):
                    for font, display, width, _style in line_atoms:
                        atoms.append((font, display, width, "m", kind))
            current, used = [], 0.0
            for atom in atoms:
                if current and used + atom[2] > usable:
                    body.append(current)
                    current, used = [], 0.0
                current.append(atom)
                used += atom[2]
            body.append(current)
        per_page = max(1, int((self.height - 2 * self.margin - 2 * padding - leading) // leading))
        self.drawn = True
        while body:
            chunk, body = body[:per_page], body[per_page:]
            height = len(chunk) * leading + padding * 2
            if self.y - height < self.margin:
                self.new_page()
            top = self.y
            self.canvas.setFillGray(0.95)
            self.canvas.rect(self.margin, top - height, self.usable, height, stroke=0, fill=1)
            self.canvas.setFillGray(0)
            self.y = top - padding
            for line in chunk:
                self.y -= leading
                x = self.margin + padding
                run_font, run_text, run_width, run_kind = None, [], 0.0, None
                for font, display, atom_width, _style, kind in line + [(None, "", 0, None, None)]:
                    if run_text and (font, kind) != (run_font, run_kind):
                        self.canvas.setFont(run_font, size * (0.94 if run_kind == "comment" else 1.0))
                        self.canvas.setFillColorRGB(*COLORS.get(run_kind, COLORS["plain"]))
                        self.canvas.drawString(x, self.y, "".join(run_text))
                        x += run_width
                        run_text, run_width = [], 0.0
                    run_font, run_kind = font, kind
                    run_text.append(display)
                    run_width += atom_width
                self.canvas.setFillColorRGB(*COLORS["plain"])
            self.y = top - height
        self.y -= after

    def table(self, header: list[str], rows: list[list[str]], *, size: float = 8.5) -> None:
        """Fixed-layout grid: wrapped cells, per-run fonts, header repeated after a page break.

        Wide tables shrink their type and truncate over-long cells; the full text stays in
        record.md and in the bibliography line, so the grid stays readable.
        """
        columns = max([len(header)] + [len(r) for r in rows])
        if columns == 0:
            return
        if columns > 9:
            size = max(6.6, size * 0.72)
        elif columns > 6:
            size = max(7.2, size * 0.84)
        limit = 90 if columns <= 6 else (60 if columns <= 9 else 42)

        def clip(value: str) -> str:
            plain = _plain(value)
            if len(plain) <= limit:
                return value
            keep = value[:limit]
            while keep and keep.count("`") % 2:
                keep = keep[:-1]
            if " " in keep:
                keep = keep[:keep.rfind(" ")]
            return keep.rstrip(" ,.;:") + "…"

        header = [clip(cell) for cell in header]
        rows = [[clip(cell) for cell in row] for row in rows]
        header = header + [""] * (columns - len(header))
        rows = [r + [""] * (columns - len(r)) for r in rows]
        minimum = size * 6
        padding = 4.0
        leading = size * 1.32

        def tokens_of(cell: str, bold: bool = False):
            """The cell split at spaces, so a machine-readable token can stay whole."""
            tokens, current = [], []
            for atom in (a for line in self._atoms(cell, size, 0, force_bold=bold) for a in line):
                current.append(atom)
                if atom[1].isspace():
                    tokens.append(current)
                    current = []
            if current:
                tokens.append(current)
            return tokens

        def token_width(token) -> float:
            return sum(atom[2] for atom in token)

        natural = []
        for index in range(columns):
            head = self.measure(header[index], size, "b")
            body = max([self.measure(row[index], size) for row in rows] or [0.0])
            natural.append(max(head, body) + size * 2.6)
        # An identifier, hash or path has no space to break at. Splitting it across two
        # lines silently destroys the one thing the table exists to carry: a copyable
        # exact value. Each column therefore gets a floor wide enough for its longest
        # unbreakable token, and the remaining space is shared by the rest.
        floors = []
        for index in range(columns):
            widest = 0.0
            for cell, bold in [(header[index], True)] + [(row[index], False) for row in rows]:
                for token in tokens_of(cell, bold):
                    if any(atom[1].isspace() for atom in token):
                        continue
                    widest = max(widest, token_width(token))
            floors.append(min(max(widest + padding * 2, minimum), self.usable * 0.55))
        widths = [0.0] * columns
        if sum(floors) <= self.usable:
            spare = [max(0.0, natural[i] - floors[i]) for i in range(columns)]
            room = self.usable - sum(floors)
            want = sum(spare) or 1.0
            widths = [floors[i] + room * spare[i] / want for i in range(columns)]
        else:
            order = sorted(range(columns), key=lambda index: natural[index])
            remaining = self.usable
            pending = list(order)
            while pending:
                index = pending[0]
                share = remaining / len(pending)
                if natural[index] <= share:
                    widths[index] = natural[index]
                    remaining -= natural[index]
                    pending.pop(0)
                else:
                    for other in pending:
                        widths[other] = remaining / len(pending)
                    break

        def wrap(cell: str, width: float, bold: bool = False):
            limit = max(width - padding * 2, size * 2)
            lines, current, used = [], [], 0.0
            for token in tokens_of(cell, bold):
                need = token_width(token)
                if current and used + need > limit:
                    lines.append(current)
                    current, used = [], 0.0
                if not current and need > limit:
                    # Only a token wider than the whole column is broken inside.
                    for atom in token:
                        if current and used + atom[2] > limit:
                            lines.append(current)
                            current, used = [], 0.0
                        current.append(atom)
                        used += atom[2]
                    continue
                current.extend(token)
                used += need
            if current:
                lines.append(current)
            return lines or [[]]

        def height_of(cells, rows_style):
            tallest = 1
            for cell, width in zip(cells, widths):
                tallest = max(tallest, len(wrap(cell, width, rows_style == "b")))
            return tallest * leading + padding * 2

        def draw(cells, y_top, bold_all):
            x = self.margin
            for cell, width in zip(cells, widths):
                y = y_top - padding - leading
                for line in wrap(cell, width, bold_all):
                    cx = x + padding
                    run_font, run_text, run_width = None, [], 0.0
                    for font, display, atom_width, style in line:
                        wanted = font
                        if run_text and wanted != run_font:
                            self.canvas.setFont(run_font, size)
                            self.canvas.drawString(cx, y, "".join(run_text))
                            cx += run_width
                            run_text, run_width = [], 0.0
                        run_font = wanted
                        run_text.append(display)
                        run_width += atom_width
                    if run_text:
                        self.canvas.setFont(run_font, size)
                        self.canvas.drawString(cx, y, "".join(run_text))
                    y -= leading
                x += width
            self.drawn = True

        header_height = height_of(header, "b")
        body_height = sum(height_of(row, "r") for row in rows)
        self.drawn = True
        if header_height + body_height <= self.height - 2 * self.margin and self.y - header_height - body_height < self.margin:
            self.new_page()          # the table fits a page: keep it whole
        else:
            self.need(header_height + leading * 3)

        def draw_header():
            top = self.y
            self.canvas.setFillGray(0.9)
            self.canvas.rect(self.margin, top - header_height, sum(widths), header_height, stroke=0, fill=1)
            self.canvas.setFillGray(0)
            draw(header, top, True)
            self.canvas.setLineWidth(0.5)
            self.canvas.line(self.margin, top - header_height, self.margin + sum(widths), top - header_height)
            self.y = top - header_height

        draw_header()
        for row in rows:
            height = height_of(row, "r")
            if self.y - height < self.margin:
                self.new_page()
                draw_header()
                height = height_of(row, "r")
            draw(row, self.y, False)
            self.y -= height
            self.canvas.setLineWidth(0.3)
            self.canvas.line(self.margin, self.y, self.margin + sum(widths), self.y)
        self.y -= 10

    def rule(self) -> None:
        self.need(18)
        self.y -= 8
        self.canvas.setLineWidth(0.8)
        self.canvas.setStrokeGray(0.55)
        self.canvas.line(self.margin, self.y, self.margin + self.usable, self.y)
        self.canvas.setStrokeGray(0)
        self.y -= 10
        self.drawn = True

    def page_break(self) -> None:
        """Start a new page for the artifacts divider; skip it if the page is still empty."""
        if self.drawn:
            self.new_page()

    def finish(self) -> int:
        self._footer()
        self.canvas.save()
        return self.page


# Inline math is recognised before other emphasis so `$a_1$` never eats the underscores.
_INLINE = re.compile(
    r"(?P<math>\$(?!\$)[^$\n]{1,400}\$)"
    r"|(?P<footnote>\[\^[^\]]+\])"
    r"|(?P<code>`[^`]+`)"
    r"|(?P<bolditalic>\*\*\*[^*]+\*\*\*)"
    r"|(?P<bold>\*\*[^*]+\*\*)"
    r"|(?P<underline>__[^_]+__)"
    r"|(?P<strike>~~[^~]+~~)"
    r"|(?P<italic>(?<!\*)\*(?!\s)[^*]+?\*(?!\*))"
)
_STYLE_FLAGS = {"code": "m", "bolditalic": "bi", "bold": "b", "underline": "ru", "strike": "rs",
                "italic": "i", "footnote": "sup", "math": "math"}


def _parse_inline(text: str) -> list[tuple[str, str]]:
    """Split one line into (text, style) runs. Style codes: r,b,i,bi,m plus u/s markers."""
    runs: list[tuple[str, str]] = []
    position = 0
    for match in _INLINE.finditer(text):
        if match.start() > position:
            runs.append((_strip_links(text[position:match.start()]), "r"))
        kind = match.lastgroup or "r"
        body = match.group(0)
        if kind == "math":
            body = body[1:-1]
        elif kind == "footnote":
            body = body[2:-1]
        elif kind == "code":
            body = body[1:-1]
        elif kind == "bolditalic":
            body = body[3:-3]
        elif kind in ("bold", "italic"):
            body = body[2:-2] if kind == "bold" else body[1:-1]
        elif kind == "underline":
            body = body[2:-2]
        elif kind == "strike":
            body = body[2:-2]
        runs.append((body, _STYLE_FLAGS.get(kind, "r")))
        position = match.end()
    if position < len(text):
        runs.append((_strip_links(text[position:]), "r"))
    out: list[tuple[str, str]] = []
    for chunk, style in runs:
        if not chunk:
            continue
        if style not in ("m", "math"):      # a code span and a formula stay literal
            chunk = _smart_quotes(_unescape(chunk))
        out.append((chunk, style))
    return out


def _strip_links(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)


def _plain(text: str) -> str:
    return "".join(chunk for chunk, _style in _parse_inline(text))


# A figure is sized to its own page, not to whatever vertical space happens to be
# left. Shrinking a 2400 px plot to a third of the page makes its axes unreadable,
# so the layout moves to a fresh page instead and keeps the figure large.
FIGURE_HEIGHT_FRACTION = 0.62      # of the printable height, leaving room for caption
FIGURE_MIN_HEIGHT = 0.30           # below this the caption crowd out the plot itself


# In-text figure shortcut: `如 \fig{fig_heatmap_iptm} 所示` prints 图 3 and puts the plot
# right after that sentence. Keyed by artifact id or by the file's stem, so a renumbered
# or renamed figure never leaves a stale number in the prose.
_FIGURE_REF = re.compile(r"\\fig\{([^{}]+)\}")


def _place_figure(layout, canvas, path: Path, caption: str, artifact_id: str, number: int) -> None:
    """Draw one figure at the largest size that still fits, caption directly beneath."""
    with _figure_image(path) as image:
        printable = layout.height - 2 * layout.margin
        caption_room = 74.0
        target = printable * FIGURE_HEIGHT_FRACTION
        scale = min(layout.usable / image.width, target / image.height)
        height = image.height * scale
        # Only start a new page when the remaining space cannot hold a readable
        # figure plus its caption; never silently shrink below that floor.
        if layout.y - layout.margin < height + caption_room and height < printable * 0.9:
            room = layout.y - layout.margin - caption_room
            if room < printable * FIGURE_MIN_HEIGHT:
                layout.new_page()
        room = layout.y - layout.margin - caption_room
        scale = min(layout.usable / image.width, target / image.height,
                    max(room, printable * FIGURE_MIN_HEIGHT) / image.height)
        width, height = image.width * scale, image.height * scale
        layout.need(height + caption_room)
        layout.y -= height
        canvas.drawImage(ImageReader(image), layout.margin + (layout.usable - width) / 2,
                         layout.y, width=width, height=height, mask="auto")
    layout.y -= 10
    layout.rich(f"图 {number}. " + " ".join(caption.splitlines()), size=9, after=2)
    layout.rich(f"工件：`{artifact_id}`", size=8, after=14)


MATHTEXT_DPI = 400
MATH_CACHE: dict[tuple[str, float, bool], tuple[bytes, float, float, float]] = {}
_MATH_LOCK = threading.Lock()


def math_image(expression: str, size: float, bold: bool = False) -> tuple[bytes, float, float, float]:
    """Rasterise a TeX expression locally; returns (png, width_pt, height_pt, depth_pt).

    matplotlib's mathtext is a self-contained TeX-subset engine, so no TeX
    installation is required and nothing leaves the machine. Cache is keyed by the
    expression and font size because a report commonly repeats the same symbol.
    """
    key = (expression, round(float(size), 2), bool(bold))
    with _MATH_LOCK:
        cached = MATH_CACHE.get(key)
        if cached is not None:
            return cached
        from matplotlib import mathtext
        from matplotlib.font_manager import FontProperties
        buffer = BytesIO()
        prop = FontProperties(size=float(size))
        depth = mathtext.math_to_image(expression, buffer, prop=prop,
                                      dpi=MATHTEXT_DPI, format="png")
        buffer.seek(0)
        with Image.open(buffer) as image:
            width_pt = image.width / MATHTEXT_DPI * 72.0
            height_pt = image.height / MATHTEXT_DPI * 72.0
        depth_pt = float(depth) / MATHTEXT_DPI * 72.0
        value = (buffer.getvalue(), width_pt, height_pt, depth_pt)
        if len(MATH_CACHE) > 512:
            MATH_CACHE.clear()
        MATH_CACHE[key] = value
        return value


def _figure_image(path: Path) -> Image.Image:
    if not path.is_file():
        raise ValueError(f"Figure is not a local regular file: {path}")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError(f"Figure exceeds {MAX_IMAGE_BYTES} bytes: {path}")
    # Bounded local read also protects against a file growing after stat().
    with path.open("rb") as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Figure exceeds {MAX_IMAGE_BYTES} bytes: {path}")
    with Image.open(BytesIO(data)) as original:
        if original.format not in {"PNG", "JPEG"}:
            raise ValueError(f"Only PNG/JPEG figures are supported: {path}")
        if original.width * original.height > MAX_IMAGE_PIXELS:
            raise ValueError(f"Figure exceeds {MAX_IMAGE_PIXELS} pixels: {path}")
        if getattr(original, "n_frames", 1) != 1:
            raise ValueError(f"Animated figures are unsupported: {path}")
        original.verify()
    with Image.open(BytesIO(data)) as original:
        original.load()
        image = ImageOps.exif_transpose(original)
        image.thumbnail((2400, 2400))
        return image.convert("RGBA" if "A" in image.getbands() or
                             "transparency" in image.info else "RGB")


def render_report(markdown_text: str, output_path: Path, *, title: str,
                  figures: list[dict] = [], font_profile: str | None = None) -> dict:
    """Render a report, raising on invalid inputs or rendering/write failures.

    Limits: 200k source characters, 20 figures, 1024 title characters, 4000
    characters per caption, 256 per artifact ID, and 500 pages. Images are
    limited to 25 MiB/40 million pixels and embedded at at most 2400x2400 px.
    Headings (# through ######) and fenced blocks are recognized; all other
    Markdown is literal text. No link/image destination is opened from text.
    The default figures list is never mutated. Output parents must exist.
    PDF bytes are fully rendered in memory before opening the output file.
    """
    if not isinstance(markdown_text, str):
        raise TypeError("markdown_text must be a string")
    if len(markdown_text) > MAX_TEXT_CHARS:
        raise ValueError(f"Report text exceeds {MAX_TEXT_CHARS} characters")
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    if not title.strip() or len(title) > 1024:
        raise ValueError("title must contain 1-1024 characters")
    if not isinstance(figures, list):
        raise TypeError("figures must be a list")
    if font_profile is not None and not isinstance(font_profile, str):
        raise TypeError("font_profile must be a string or None")
    if len(figures) > MAX_FIGURES:
        raise ValueError(f"Report exceeds {MAX_FIGURES} figures")
    output_path = Path(output_path)
    prepared = []
    for figure in figures:
        if not isinstance(figure, dict):
            raise TypeError("Each figure must be a dictionary")
        path = figure.get("path")
        caption, artifact_id = figure.get("caption"), figure.get("artifact_id")
        if not isinstance(path, (str, Path)) or not str(path):
            raise ValueError("Figure path must be a nonempty local path")
        if not isinstance(caption, str) or len(caption) > 4000:
            raise ValueError("Figure caption must be a string of at most 4000 characters")
        if not isinstance(artifact_id, str) or not artifact_id.strip() or len(artifact_id) > 256:
            raise ValueError("Figure artifact_id must contain 1-256 characters")
        figure_path = Path(path)
        if output_path.resolve() == figure_path.resolve():
            raise ValueError("Output path must not overwrite a figure")
        prepared.append((figure_path, caption, artifact_id))

    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4, pageCompression=1, invariant=1)
    canvas.setTitle(title)
    canvas.setAuthor("Levin Research Notebook")
    layout = _Layout(canvas, font_profile or DEFAULT_PROFILE)
    layout.rich(" ".join(title.splitlines()), size=19, after=8, bold=True)

    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    blank = False
    first_heading = True

    # Figures are numbered by where they first appear in the document, not by the order
    # they were registered. Registration order is an artifact of the workflow; a reader
    # flipping pages needs 图 1, 图 2, 图 3 down the page. A number is therefore reserved
    # the first time the renderer meets that figure — either a placement marker or an
    # in-text reference — and reused afterwards.
    numbers: dict[str, int] = {}
    placed_keys: set[str] = set()

    def lookup(key: str):
        wanted = key.strip()
        for item in prepared:
            if wanted in (item[2], item[0].stem, item[0].name):
                return item
        return None

    def number_for(item) -> int:
        if item[2] not in numbers:
            numbers[item[2]] = len(numbers) + 1
        return numbers[item[2]]

    def place(item) -> None:
        if item[2] in placed_keys:
            return
        number = number_for(item)
        _place_figure(layout, canvas, item[0], item[1], item[2], number)
        placed_keys.add(item[2])

    def resolve_refs(text: str) -> tuple[str, list]:
        """Turn \\fig{key} into 图 N and report figures that must follow this block.

        The first in-text reference is the reference point: the plot belongs right after
        the sentence that cites it, so the reader never turns a page to find it.
        """
        deferred: list = []

        def replacement(match) -> str:
            item = lookup(match.group(1))
            if item is None:
                return f"[未登记图 {match.group(1).strip()}]"
            number = number_for(item)
            if item[2] not in placed_keys:
                deferred.append(item)
            return f"图 {number}"

        return _FIGURE_REF.sub(replacement, text), deferred

    def flush(deferred: list) -> None:
        for item in deferred:
            place(item)

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        fence = re.match(r"^\s*(`{3,}|~{3,})\s*(\S*)$", line)
        if fence:
            marker = fence.group(1)
            block = []
            index += 1
            while index < len(lines) and not re.match(r"^\s*" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$", lines[index]):
                block.append(lines[index])
                index += 1
            index += 1
            layout.code_block(block[:400], language=fence.group(2) or "text")
            blank = False
            continue
        if not stripped:
            if not blank:
                layout.y -= 4
            blank = True
            index += 1
            continue
        blank = False
        if stripped == "\\figures":
            # Whatever the body never cited. It still lands here so no registered plot
            # silently disappears; `validate` names the figures in this position. The
            # block says what it is, because a page of plots with no framing reads like
            # an appendix someone forgot to cite.
            pending = [item for item in prepared if item[2] not in placed_keys]
            if pending:
                layout.need(60)
                layout.rich("图表", size=13, after=4)
                if placed_keys:
                    layout.rich("下列图表未在正文中逐图引用，集中在此呈现。", size=9, after=8)
                for item in pending:
                    place(item)
            index += 1
            continue
        single = re.fullmatch(r"\\figure\{([^{}]+)\}", stripped)
        if single:
            # An explicit placement lands next to the claim that needs it.
            item = lookup(single.group(1))
            if item is None:
                layout.rich(f"[未找到图 {single.group(1).strip()}：请在 figures 中登记该工件]", size=9, after=6)
                index += 1
                continue
            place(item)
            index += 1
            continue
        display_math = re.fullmatch(r"\$\$(.+?)\$\$", stripped) or re.fullmatch(r"\\\[(.+?)\\\]", stripped)
        if display_math:
            expression = " ".join(display_math.group(1).split())
            try:
                png, width_pt, height_pt, depth_pt = math_image(expression, 11.5)
            except Exception:
                layout.rich("$" + expression + "$", size=10, after=8)
                index += 1
                continue
            if width_pt > layout.usable:
                scale = layout.usable / width_pt
                width_pt, height_pt, depth_pt = width_pt * scale, height_pt * scale, depth_pt * scale
            layout.need(height_pt + 26)
            layout.y -= height_pt + 8
            canvas.drawImage(ImageReader(BytesIO(png)),
                             layout.margin + (layout.usable - width_pt) / 2,
                             layout.y + depth_pt - 2, width=width_pt, height=height_pt, mask="auto")
            layout.y -= 10
            layout.drawn = True
            index += 1
            continue
        if stripped in ("\\pagebreak", "\\newpage"):
            layout.page_break()          # explicit divider: artifacts open a new page
            index += 1
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            layout.rule()
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2)
            if level == 1 and first_heading and _plain(text).casefold() == " ".join(title.split()).casefold():
                first_heading = False
                index += 1
                continue
            first_heading = False
            size = max(10.5, 17 - level * 1.6)
            layout.need(size * 2 + (44 if level <= 2 else 30))
            layout.y -= 4 if level >= 3 else 8
            layout.rich(text, size=size, after=6, bold=True)
            index += 1
            continue
        if stripped.startswith("|") and index + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[index + 1]):
            header = [cell.strip() for cell in stripped.strip("|").split("|")]
            index += 2
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            layout.table(header, rows[:400])
            continue
        note = re.match(r"^\[\^([^\]]+)\]:\s*(.+)$", stripped)
        if note:
            layout.rich(f"[{note.group(1)}] {note.group(2)}", size=9, indent=12, after=3)
            index += 1
            continue
        if stripped.startswith(">"):
            quote = [stripped.lstrip("> ").strip()]
            index += 1
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip("> ").strip())
                index += 1
            text = " ".join(part for part in quote if part)
            text, deferred = resolve_refs(text)
            layout.need(14)
            top = layout.y
            layout.rich(text, size=9.4, indent=14, after=4)
            canvas.setLineWidth(1.6)
            canvas.setStrokeGray(0.72)
            canvas.line(layout.margin + 4, top - 2, layout.margin + 4, layout.y + 2)
            canvas.setStrokeGray(0)
            flush(deferred)
            continue
        bullet = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.+)$", line)
        if bullet:
            depth = len(bullet.group(1)) // 2
            marker = "•" if bullet.group(2) in "-*+" else bullet.group(2)
            body, deferred = resolve_refs(bullet.group(3))
            layout.rich(f"{marker} {body}", size=10, indent=12 + depth * 12, after=2)
            flush(deferred)
            index += 1
            continue
        paragraph = [stripped]
        index += 1
        while index < len(lines):
            nxt = lines[index]
            if (not nxt.strip() or nxt.strip() in ("\\pagebreak", "\\newpage") or nxt.lstrip().startswith(("#", "|", ">", "```", "~~~"))
                    or re.match(r"^(\s*)([-*+]|\d+[.)])\s+", nxt)
                    or re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", nxt.strip())):
                break
            paragraph.append(nxt.strip())
            index += 1
        body, deferred = resolve_refs(" ".join(paragraph))
        layout.rich(body, size=10, after=6)
        flush(deferred)

    remaining = [item for item in prepared if item[2] not in placed_keys]
    if remaining:
        layout.need(60)
        layout.rich("图表" if not placed_keys else "其余图表（正文未引用）", size=13, after=6)
        if placed_keys:
            layout.rich("下列图表在正文中没有引用位置，因此集中排在文末。", size=9, after=8)
        for item in remaining:
            place(item)
    pages = layout.finish()
    output_path.write_bytes(buffer.getvalue())
    return {"pdf_path": str(output_path), "pages": pages,
            "renderer": f"reportlab-{reportlab.Version}",
            "unsupported_codepoints": [f"U+{point:04X}" for point in sorted(layout.unsupported)],
            "transliterated_codepoints": [f"U+{point:04X}" for point in sorted(layout.transliterated)],
            "fonts": {"profile": layout.fonts["profile"],
                      "resolved": dict(layout.fonts["used"]),
                      "cjk_available": layout.fonts["cjk_available"],
                      "notes": list(layout.fonts["notes"])}}
