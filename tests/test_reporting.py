"""Focused offline tests for the fixed-layout reporting module.

Run with: PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p test_reporting.py
Optional pypdf assertions check page contents without making it a runtime dependency.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
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

    def test_unicode_fallback_reports_unavailable_glyphs(self):
        with patch.object(reporting, "_cjk_fonts", return_value=()), \
                patch.dict(reporting.FONTS, {"songti": "NotebookVera", "heiti": "NotebookVeraBold"}):
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
