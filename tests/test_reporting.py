"""Focused offline tests for the fixed-layout reporting module.

Run with: PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p test_reporting.py
Optional pypdf assertions check page contents without making it a runtime dependency.
"""
from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

try:
    import reportlab
    from PIL import Image
except ImportError:
    reportlab = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

if reportlab is not None:
    module_path = Path(__file__).resolve().parents[1] / "mcp" / "runner" / "reporting.py"
    spec = importlib.util.spec_from_file_location("notebook_reporting", module_path)
    reporting = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reporting)

# Artifact root is overridable so the suite runs on any machine; the default is a
# process-local temp directory, never a hard-coded home path.
SCRATCH = Path(os.environ.get("NOTEBOOK_TEST_SCRATCH")
               or Path(tempfile.gettempdir()) / "levin-research-notebook-tests" / "report-worker")


@unittest.skipIf(reportlab is None, "ReportLab/Pillow dependencies are unavailable")
class ReportingTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        # Keep rendered fixtures for parent review; never clean retained outputs.
        self.root = Path(tempfile.mkdtemp(prefix="report-test-", dir=SCRATCH))
        self.output = self.root / "report.pdf"

    def render(self, text="Report content", **kwargs):
        return reporting.render_report(text, self.output, title="Test report", **kwargs)

    def reader(self):
        if PdfReader is None:
            self.skipTest("Optional pypdf is unavailable")
        return PdfReader(self.output)

    def test_small_failed_report_and_no_figures(self):
        result = self.render("# Failed run\n\nStatus: FAILED\nNo verified figures are available.")
        self.assertEqual(result["pdf_path"], str(self.output))
        self.assertEqual(result["pages"], 1)
        self.assertEqual(result["renderer"], f"reportlab-{reportlab.Version}")
        self.assertTrue(self.output.read_bytes().startswith(b"%PDF-"))
        text = self.reader().pages[0].extract_text()
        for expected in ("Test report", "Failed run", "FAILED", "第 1 页"):
            self.assertIn(expected, text)

    def test_empty_report_is_valid(self):
        self.assertEqual(self.render("")["pages"], 1)
        self.assertEqual(len(self.reader().pages), 1)

    def test_long_lines_wrap_inside_printable_area(self):
        captured = []
        original = reporting.Canvas.drawString

        def record(canvas, x, y, text, *args, **kwargs):
            width = reporting.pdfmetrics.stringWidth(text, canvas._fontname, canvas._fontsize)
            captured.append((x, y, width))
            return original(canvas, x, y, text, *args, **kwargs)

        with patch.object(reporting.Canvas, "drawString", record):
            result = self.render("A" * 9000 + "\n" + "mixed words " * 1500)
        self.assertGreater(result["pages"], 1)
        self.assertGreater(len(captured), 100)
        for x, y, width in captured:
            self.assertGreaterEqual(x, 48)
            self.assertGreaterEqual(y, 48)
            self.assertLessEqual(x + width, reporting.A4[0] - 48 + 0.01)
        reader = self.reader()
        self.assertEqual(len(reader.pages), result["pages"])
        for number, page in enumerate(reader.pages, 1):
            self.assertIn(f"第 {number} 页", page.extract_text())

    def test_markdown_html_and_code_are_inert(self):
        text = ('![remote](https://example.invalid/image.png)\n'
                '<img src="https://example.invalid/image.png">\n'
                '```python\n__import__("os").system("touch forbidden")\n```')
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network access")), \
                patch("os.system", side_effect=AssertionError("Code execution")):
            self.render(text)
        extracted = self.reader().pages[0].extract_text()
        self.assertIn("https://example.invalid/image.png", extracted)
        self.assertIn("__import__", extracted)
        self.assertIn("<img", extracted)

    def test_font_profiles_resolve_and_report_themselves(self):
        for profile in ("scientific-cjk", "cjk-sans", "latin-only"):
            with self.subTest(profile=profile):
                info = reporting.font_report(profile)
                self.assertEqual(info["profile"], profile)
                for role in ("r", "b", "i", "bi", "m", "songti", "heiti"):
                    self.assertTrue(info["fonts"][role], f"{role} unresolved in {profile}")
                self.assertIn("cjk_available", info)
                self.assertIn("notes", info)

    def test_unknown_font_profile_is_rejected(self):
        # A typo must fail loudly rather than silently render with the default.
        with self.assertRaises(ValueError):
            reporting.resolve_fonts("no-such-profile")

    def test_auto_profile_is_accepted(self):
        self.assertEqual(reporting.resolve_fonts("auto")["profile"], reporting.DEFAULT_PROFILE)

    def test_resolved_fonts_are_per_call_not_global(self):
        # Two reports with different profiles in one process must not share state.
        first = reporting.resolve_fonts("scientific-cjk")["fonts"]
        second = reporting.resolve_fonts("cjk-sans")["fonts"]
        self.assertIsNot(first, second)
        self.assertEqual(reporting.resolve_fonts("scientific-cjk")["fonts"]["songti"],
                         first["songti"])

    def test_render_report_reports_the_fonts_it_used(self):
        result = self.render("字体回报 \u4e2d\u6587")
        fonts = result["fonts"]
        self.assertEqual(fonts["profile"], reporting.DEFAULT_PROFILE)
        self.assertIn("songti", fonts["resolved"])
        self.assertIn("cjk_available", fonts)
        self.assertIsInstance(fonts["notes"], list)

    def test_explicit_profile_reaches_the_renderer(self):
        result = self.render("正文 with \u4e2d\u6587", font_profile="cjk-sans")
        self.assertEqual(result["fonts"]["profile"], "cjk-sans")

    def test_unicode_fallback_reports_unavailable_glyphs(self):
        # Simulate a host with no CJK face at all: the CJK roles must degrade to a
        # Latin face and the affected characters must be reported, not drawn as tofu.
        baseline = reporting.resolve_fonts("scientific-cjk")
        starved = copy.deepcopy(baseline)
        starved["fonts"].update({"songti": "NotebookVera", "heiti": "NotebookVeraBold"})
        starved["fallbacks"] = ()
        starved["cjk_available"] = False
        with patch.object(reporting, "resolve_fonts", return_value=starved):
            result = self.render("Café α β 中文 \U0001f9ec")
        self.assertIn("U+4E2D", result["unsupported_codepoints"])
        self.assertIn("U+1F9EC", result["unsupported_codepoints"])
        text = self.reader().pages[0].extract_text()
        self.assertIn("Café", text)
        self.assertIn("[U+4E2D]", text)
        self.assertIn("[U+1F9EC]", text)

    def test_controls_are_visible_and_not_silent(self):
        result = self.render("before\x00after\u202eend")
        self.assertIn("U+0000", result["unsupported_codepoints"])
        self.assertIn("U+202E", result["unsupported_codepoints"])

    def test_html_entities_render_as_characters(self):
        # A record is Markdown, where "&lt;160" is "<160". Printing the entity made a
        # delivered PDF look corrupt, so the renderer must decode it.
        self.render("残基 &lt;160 且 &lt;H&gt; = +1.30，条件 a &gt; b，5 &amp; 6。")
        text = self.reader().pages[0].extract_text()
        for entity in ("&lt;", "&gt;", "&amp;"):
            self.assertNotIn(entity, text)
        flat = text.replace("\n", "")
        for wanted in ("<160", "<H> = +1.30", "a > b", "5 & 6"):
            self.assertIn(wanted, flat)

    def test_straight_quotes_become_chinese_quotes_but_never_inside_code(self):
        self.render('# 引号\n\n他说"可能稳定构象/通道"，又说"压在催化腔上"。\n\n'
                    '| 参数 | 值 |\n| --- | --- |\n| `{"batch_size": 10}` | 固定 |\n\n'
                    '```\n{"frames": 300, "note": "keep me"}\n```')
        flat = "\n".join(p.extract_text() or "" for p in self.reader().pages).replace("\n", "")
        self.assertIn("“可能稳定构象/通道”", flat)
        self.assertIn("“压在催化腔上”", flat)
        # Machine-readable content keeps its literal quotes: rewriting them would
        # silently change a parameter block a reader is meant to copy.
        self.assertIn('"batch_size": 10', flat)
        self.assertIn('"frames": 300', flat)
        self.assertNotIn("“batch_size”", flat)

    def test_figure_citation_places_the_plot_at_the_sentence_that_cites_it(self):
        # The reference point, not the registration order, decides both the number and the
        # position: a plot cited first must be 图 1 and must sit under that sentence.
        from PIL import Image
        paths = []
        for name, colour in (("registered-first.png", (200, 80, 80)),
                             ("registered-second.png", (80, 120, 200))):
            target = self.root / name
            Image.new("RGB", (600, 300), colour).save(target)
            paths.append(target)
        figures = [dict(path=str(paths[0]), caption="注册在先的图", artifact_id="fig-first"),
                   dict(path=str(paths[1]), caption="注册在后的图", artifact_id="fig-second")]
        self.render("# 引用\n\n先引用后注册的那张：如 \\fig{fig-second} 所示。\n\n"
                    "再引用另一张：见 \\fig{fig-first}。\n\n"
                    "重复引用一次：\\fig{fig-second} 不再插入。", figures=figures)
        flat = "".join(p.extract_text() or "" for p in self.reader().pages).replace("\n", "")
        self.assertIn("如 图 1 所示", flat)
        self.assertIn("见 图 2", flat)
        self.assertNotIn("图 3", flat)
        # The caption of 图 1 is the figure registered second, in place after its sentence.
        first = flat.index("图 1.")
        self.assertLess(flat.index("先引用后注册的那张"), first)
        self.assertLess(first, flat.index("再引用另一张"))

    def test_a_figure_no_sentence_cites_still_renders_in_a_named_plate(self):
        from PIL import Image
        target = self.root / "uncited.png"
        Image.new("RGB", (600, 300), (90, 140, 90)).save(target)
        self.render("# 无引用\n\n正文没有指向任何图。\n\n\\figures",
                    figures=[dict(path=str(target), caption="无人引用的图", artifact_id="fig-orphan")])
        flat = "".join(p.extract_text() or "" for p in self.reader().pages).replace("\n", "")
        self.assertIn("图表", flat)
        self.assertIn("图 1.", flat)

    def test_an_unknown_figure_reference_is_visible(self):
        self.render("正文 \\fig{does-not-exist}。")
        flat = self.reader().pages[0].extract_text().replace("\n", "")
        self.assertIn("未登记图", flat)
        self.assertIn("does-not-exist", flat)

    def test_a_script_run_is_drawn_one_way_or_the_other(self):
        # Per-character resolution produced "κ^-¹": the missing minus became "^-" while
        # the Latin-1 superscript one stayed a real glyph.
        result = self.render("介电 κ⁻¹ = 9.5 Å，速率 m⁻¹，面积 5278 Å³，R² = 0.98。")
        flat = self.reader().pages[0].extract_text().replace("\n", "")
        self.assertNotIn("κ^-¹", flat)
        self.assertIn("κ^-1", flat)
        self.assertIn("m^-1", flat)
        # A run the faces can actually draw keeps its real superscript glyphs.
        self.assertIn("R²", flat)
        self.assertIn("Å³", flat)
        self.assertIn("U+207B", result["transliterated_codepoints"])

    def test_machine_readable_tokens_are_never_split_across_lines(self):
        # An identifier split in two cannot be copied, which defeats the table.
        identifiers = [f"artifact-{index:032x}" for index in range(1, 5)]
        rows = "\n".join(f"| `{value}` | raw | local | local_original / 文献 src-nature2025 |"
                         for value in identifiers)
        self.render(f"# 工件\n\n| ID | 角色 | 可用性 | 来源 |\n| --- | --- | --- | --- |\n{rows}")
        raw = "\n".join(p.extract_text() or "" for p in self.reader().pages)
        for value in identifiers:
            self.assertIn(value, raw.replace("\n", ""))
        self.assertFalse(re.findall(r"artifact-[0-9a-f]{8,}\s+[0-9a-f]{4,}", raw),
                         "an identifier was split across two lines")

    def test_png_jpeg_figures_and_captions(self):
        figures = []
        for index, extension in enumerate(("png", "jpg"), 1):
            path = self.root / f"figure{index}.{extension}"
            Image.new("RGB", (200, 100), (30 * index, 90, 140)).save(path)
            figures.append({"path": str(path), "caption": f"Caption {index}",
                            "artifact_id": f"artifact-{index}"})
        self.render(figures=figures)
        reader = self.reader()
        text = "\n".join(page.extract_text() for page in reader.pages)
        # CJK label and Latin caption are drawn in different fonts, so extraction breaks after 图
        self.assertIn("图", text)
        self.assertIn("1. Caption 1", text)
        self.assertIn("工件：", text)
        self.assertIn("artifact-2", text)
        self.assertEqual(sum(len(page.images) for page in reader.pages), 2)
        self.assertEqual(len(figures), 2)

    def test_extreme_aspect_figures_fit_page(self):
        path = self.root / "tall.png"
        Image.new("RGB", (1, 5000)).save(path)
        result = self.render(figures=[{"path": path, "caption": "Tall image",
                                       "artifact_id": "tall"}])
        self.assertEqual(result["pages"], 1)

    def test_limits_fail_before_output_creation(self):
        invalid = (
            {"markdown_text": "a" * (reporting.MAX_TEXT_CHARS + 1), "figures": []},
            {"markdown_text": "ok", "figures": [{}] * 21},
        )
        for kwargs in invalid:
            with self.subTest(kwargs_size=len(kwargs["markdown_text"])):
                with self.assertRaises(ValueError):
                    reporting.render_report(output_path=self.output, title="Test", **kwargs)
                self.assertFalse(self.output.exists())
        with self.assertRaises(ValueError):
            reporting.render_report("ok", self.output, title="x" * 1025)
        self.assertFalse(self.output.exists())

    def test_maximum_source_size_renders(self):
        result = self.render("bounded words " * (reporting.MAX_TEXT_CHARS // 14))
        self.assertGreater(result["pages"], 1)
        self.assertLess(result["pages"], reporting.MAX_PAGES)

    def test_page_limit_preserves_existing_output(self):
        self.output.write_bytes(b"existing")
        with patch.object(reporting, "MAX_PAGES", 1):
            with self.assertRaisesRegex(ValueError, "pages"):
                self.render("\n\n".join(["line"] * 400))
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_invalid_and_unsupported_images_raise(self):
        cases = [self.root / "missing.png", self.root / "corrupt.png", self.root / "wrong.gif"]
        cases[1].write_bytes(b"not an image")
        Image.new("RGB", (10, 10)).save(cases[2])
        for path in cases:
            with self.subTest(path=path.name):
                with self.assertRaises((ValueError, OSError)):
                    self.render(figures=[{"path": path, "caption": "", "artifact_id": "bad"}])
                self.assertFalse(self.output.exists())

    def test_figure_pixel_limit(self):
        path = self.root / "large.png"
        Image.new("RGB", (11, 10)).save(path)
        with patch.object(reporting, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaisesRegex(ValueError, "pixels"):
                self.render(figures=[{"path": path, "caption": "", "artifact_id": "large"}])
        self.assertFalse(self.output.exists())

    def test_no_overwriting_input_figure(self):
        Image.new("RGB", (10, 10)).save(self.output, format="PNG")
        before = self.output.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.render(figures=[{"path": self.output, "caption": "", "artifact_id": "input"}])
        self.assertEqual(before, self.output.read_bytes())

    def test_write_failure_propagates(self):
        with self.assertRaises(OSError):
            reporting.render_report("ok", self.root / "absent" / "report.pdf", title="Test")


if __name__ == "__main__":
    unittest.main()
