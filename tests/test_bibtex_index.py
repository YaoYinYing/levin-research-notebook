"""BibTeX indexing via bibtexparser v2, with EndNote-style metadata hygiene."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp" / "runner"))
import bibtex_index  # noqa: E402

SAMPLE = """@article{Doe2024,
  author = {Doe, Jane and Roe, Richard and Poe, Ann},
  title = {Conformational preference in cucurbitacin complexes},
  journal = {Journal of Molecular Biology},
  year = {2024},
  doi = {10.1000/xyz},
  note = {CuIIa binds better in 2 of 3 replicas}
}
@article{Roe2022,
  author = {Roe, Richard},
  title = {No significant difference},
  journal = {J Comput Chem},
  year = {2022}
}
@misc{Unknown1,
  note = {TODO verify}
}
"""


class BibtexIndexTests(unittest.TestCase):
    def test_parses_entries_and_formats_citations(self):
        records, warnings = bibtex_index.parse_bibtex(SAMPLE)
        self.assertEqual([r["id"] for r in records], ["Doe2024", "Roe2022", "Unknown1"])
        self.assertEqual(warnings, [])
        first = records[0]
        self.assertEqual(first["year"], 2024)
        self.assertEqual(first["venue"], "Journal of Molecular Biology")
        self.assertEqual(first["doi"], "10.1000/xyz")
        self.assertEqual(first["key_findings"], "CuIIa binds better in 2 of 3 replicas")
        self.assertEqual(first["authors"], ["Jane Doe", "Richard Roe", "Ann Poe"])
        self.assertIn("Doe et al. 2024", first["citation"])

    def test_metadata_gaps_are_flagged_not_hidden(self):
        records, _ = bibtex_index.parse_bibtex(SAMPLE)
        self.assertEqual(records[0]["metadata_issues"], [])
        self.assertIn("缺 DOI", records[1]["metadata_issues"])
        problems = records[2]["metadata_issues"]
        for expected in ("缺标题", "缺年份", "缺作者"):
            self.assertIn(expected, problems)

    def test_explicit_overrides_win_and_parsed_metadata_fills_gaps(self):
        parsed, _ = bibtex_index.parse_bibtex(SAMPLE)
        merged = bibtex_index.merge([{"id": "Doe2024", "evidence_level": "同行评议", "read_full_text": True}], parsed)
        by_id = {r["id"]: r for r in merged}
        self.assertEqual(by_id["Doe2024"]["evidence_level"], "同行评议")
        self.assertTrue(by_id["Doe2024"]["read_full_text"])
        self.assertEqual(by_id["Doe2024"]["venue"], "Journal of Molecular Biology", "bibtex still supplies venue")
        self.assertIn("Roe2022", by_id)

    def test_reads_a_workspace_bib_file_and_rejects_missing_sources(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "library.bib"
            path.write_text(SAMPLE, encoding="utf-8")
            records, warnings, resolved = bibtex_index.read_bibtex("library.bib", Path(tmp))
            self.assertEqual(len(records), 3)
            self.assertTrue(resolved.endswith("library.bib"))
            with self.assertRaises(ValueError):
                bibtex_index.read_bibtex("missing.bib", Path(tmp))

    def test_inline_bibtex_is_accepted(self):
        records, _, resolved = bibtex_index.read_bibtex(SAMPLE, Path("/tmp"))
        self.assertEqual(len(records), 3)
        self.assertEqual(resolved, "inline")


if __name__ == "__main__":
    unittest.main(verbosity=2)
