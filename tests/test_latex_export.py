"""LaTeX export and math rendering: the offline path that needs no TeX install."""
import unittest
from pathlib import Path
import tempfile

import latex_export
import reporting


class LatexExportTests(unittest.TestCase):
    def test_headings_tables_and_code_survive(self):
        markdown = "\n".join([
            "# 报告标题",
            "",
            "## 1. 实验目的",
            "",
            "| 量 | 数值 |",
            "| --- | --- |",
            "| rmsd | 2.1 |",
            "",
            "```python",
            "print('x')",
            "```",
        ])
        tex = latex_export.to_latex(markdown, "报告标题")
        self.assertIn(r"\section*{1. 实验目的}", tex)
        self.assertIn(r"\begin{longtable}", tex)
        self.assertIn(r"rmsd & 2.1 \\", tex)
        self.assertIn(r"\begin{codeblock}", tex)
        self.assertTrue(tex.rstrip().endswith(r"\end{document}"))

    def test_the_title_heading_is_not_repeated(self):
        tex = latex_export.to_latex("# 同一个标题\n\n正文\n", "同一个标题")
        self.assertEqual(tex.count("同一个标题"), 1)

    def test_latex_special_characters_are_escaped(self):
        tex = latex_export.to_latex("50% of A_b & C#1 {x} ~ ^", "t")
        for escaped in (r"\%", r"\_", r"\&", r"\#", r"\{x\}", r"\textasciitilde{}"):
            self.assertIn(escaped, tex)

    def test_inline_math_is_preserved_verbatim(self):
        # Math must reach LaTeX as math, not as escaped text.
        tex = latex_export.to_latex(r"能量 $\Delta G = -42.3$ 与 $E_a$", "t")
        self.assertIn(r"$\Delta G = -42.3$", tex)
        self.assertIn("$E_a$", tex)
        self.assertNotIn(r"\$", tex)

    def test_display_math_becomes_a_display_environment(self):
        tex = latex_export.to_latex("$$ a^2 + b^2 = c^2 $$", "t")
        self.assertIn(r"\[a^2 + b^2 = c^2\]", tex)

    def test_inline_styles_map_to_commands(self):
        tex = latex_export.to_latex("**粗** *斜* `code` ~~删~~ __下__", "t")
        self.assertIn(r"\textbf{粗}", tex)
        self.assertIn(r"\textit{斜}", tex)
        self.assertIn(r"\texttt{code}", tex)
        self.assertIn(r"\sout{删}", tex)
        self.assertIn(r"\underline{下}", tex)
        # ulem is only loaded when a strike is actually used.
        self.assertIn(r"\usepackage[normalem]{ulem}", tex)

    def test_page_break_and_rule(self):
        tex = latex_export.to_latex("A\n\n\\pagebreak\n\n---\n\nB", "t")
        self.assertIn(r"\clearpage", tex)
        self.assertIn(r"\rule{\linewidth}", tex)

    def test_bullets_and_ordered_items(self):
        tex = latex_export.to_latex("- 一\n- 二\n\n1. 甲\n2. 乙", "t")
        self.assertIn(r"\begin{itemize}", tex)
        self.assertIn(r"\begin{enumerate}", tex)
        self.assertEqual(tex.count(r"\item"), 4)

    def test_quote_block(self):
        tex = latex_export.to_latex("> 2026-01-01 补充说明", "t")
        self.assertIn(r"\begin{quote}", tex)


class MathRenderTests(unittest.TestCase):
    def test_inline_math_renders_without_a_tex_installation(self):
        png, width, height, depth = reporting.math_image(r"\Delta G = -42.3", 10)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)
        self.assertLessEqual(depth, height)

    def test_identical_expressions_are_cached(self):
        first = reporting.math_image(r"E_a", 10)
        second = reporting.math_image(r"E_a", 10)
        self.assertIs(first, second)

    def test_report_with_math_still_renders_a_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            markdown = ("# 数学\n\n正文 $E_a = 59.5\\ \\mathrm{kJ\\,mol^{-1}}$ 与 "
                        "$\\Delta G_{\\mathrm{bind}}$。\n\n$$ \\Delta G = \\Delta H - T\\Delta S $$\n")
            info = reporting.render_report(markdown, Path(folder) / "m.pdf", title="数学", figures=[])
            self.assertEqual(info["pages"], 1)
            self.assertEqual(info["unsupported_codepoints"], [])
            self.assertGreater((Path(folder) / "m.pdf").stat().st_size, 1000)

    def test_broken_math_falls_back_to_literal_text(self):
        # A malformed expression must not abort the whole report.
        with tempfile.TemporaryDirectory() as folder:
            info = reporting.render_report("# t\n\n坏公式 $\\frac{1}{$ 后面正文\n",
                                           Path(folder) / "b.pdf", title="t", figures=[])
            self.assertEqual(info["pages"], 1)


if __name__ == "__main__":
    unittest.main()
