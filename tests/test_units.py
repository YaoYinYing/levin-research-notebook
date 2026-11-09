"""Dimensional checking: what it must catch, and what it must not invent."""
import unittest

import units


class UnitParsingTests(unittest.TestCase):
    def test_structural_units_resolve_to_the_expected_dimensions(self):
        cases = {
            "Å": {"L": 1}, "nm": {"L": 1}, "cm": {"L": 1},
            "ps": {"T": 1}, "fs": {"T": 1}, "ns": {"T": 1}, "min": {"T": 1},
            "K": {"TH": 1}, "kJ/mol": {"M": 1, "L": 2, "T": -2, "N": -1},
            "Å²": {"L": 2}, "Å³": {"L": 3}, "g/cm3": {"M": 1, "L": -3},
            "nm/ns": {"L": 1, "T": -1}, "ns^-1": {"T": -1},
            "kJ mol-1 nm-2": {"M": 1, "T": -2, "N": -1},
        }
        for text, expected in cases.items():
            with self.subTest(unit=text):
                dims, _factor = units.parse_unit(text)
                self.assertEqual(dims, expected)

    def test_unknown_and_malformed_units_raise_instead_of_guessing(self):
        for text in ("bogus", "kg//", "zz^2"):
            with self.subTest(unit=text), self.assertRaises(ValueError):
                units.parse_unit(text)

    def test_dimensionless_spellings(self):
        for text in ("fraction", "ratio", "unitless", "%", "frames", ""):
            with self.subTest(unit=text):
                dims, _factor = units.parse_unit(text)
                self.assertEqual(dims, {})


class DimensionCheckTests(unittest.TestCase):
    def codes(self, **quantity):
        return [issue["code"] for issue in units.check(quantity)]

    def test_correct_quantity_passes(self):
        self.assertEqual(self.codes(name="rmsd", value=2.1, unit="Å"), [])
        self.assertEqual(self.codes(name="delta_g", value=-42.3, unit="kJ/mol"), [])
        self.assertEqual(self.codes(name="occupancy", value=0.94, unit="%"), [])

    def test_wrong_dimension_is_an_error(self):
        # A temperature recorded in picoseconds is uninterpretable, not unconventional.
        self.assertIn("dimension_mismatch", self.codes(name="temperature", value=300, unit="ps"))
        self.assertIn("dimension_mismatch", self.codes(name="force_constant", value=1000, unit="kJ mol-1 nm-2"))

    def test_same_dimension_different_scale_is_only_a_convention_note(self):
        # kcal/mol is a legal energy unit; grouping it with kJ/mol is a style issue.
        self.assertEqual(self.codes(name="delta_g", value=-10.1, unit="kcal/mol"), ["unit_scale"])

    def test_missing_unit_only_flagged_when_the_name_implies_a_dimension(self):
        self.assertEqual(self.codes(name="rmsd", value=2.1), ["missing_unit"])
        self.assertEqual(self.codes(name="score", value=0.71), [])

    def test_non_numeric_and_non_finite_values(self):
        self.assertIn("non_numeric", self.codes(name="rmsd", value="2.1", unit="Å"))
        self.assertIn("non_finite", self.codes(name="rmsd", value=float("nan"), unit="Å"))

    def test_unparsable_unit_is_reported_not_dropped(self):
        self.assertIn("unparsable_unit", self.codes(name="rmsd", value=2.1, unit="furlong"))

    def test_uncertainty_unit_must_match_the_value(self):
        issued = units.check({"name": "delta_g", "value": -42.3, "unit": "kJ/mol",
                              "uncertainty": 3.1, "uncertainty_unit": "Å"})
        self.assertIn("uncertainty_unit_mismatch", [issue["code"] for issue in issued])
        clean = units.check({"name": "delta_g", "value": -42.3, "unit": "kJ/mol",
                             "uncertainty": 3.1, "uncertainty_unit": "kJ/mol"})
        self.assertEqual(clean, [])

    def test_negative_uncertainty_is_rejected(self):
        issued = units.check({"name": "rmsd", "value": 2.1, "unit": "Å", "uncertainty": -0.2})
        self.assertIn("negative_uncertainty", [issue["code"] for issue in issued])


class CrossQuantityTests(unittest.TestCase):
    def test_the_same_quantity_in_two_units_is_flagged(self):
        issued = units.check_all([
            {"name": "rmsd", "value": 2.1, "unit": "Å"},
            {"name": "rmsd", "value": 0.21, "unit": "nm"},
        ])
        self.assertIn("inconsistent_unit", [issue["code"] for issue in issued])

    def test_summary_reports_canonical_unit_and_dimension(self):
        rows = units.summary([
            {"name": "delta_g", "value": -42.3, "unit": "kJ/mol"},
            {"name": "temperature", "value": 300, "unit": "ps"},
        ])
        self.assertEqual(rows[0]["canonical"], "kJ/mol")
        self.assertEqual(rows[0]["status"], "通过")
        self.assertEqual(rows[1]["status"], "需修正")
        self.assertTrue(rows[1]["issues"])

    def test_values_are_never_rewritten(self):
        # The checker reports; it must not convert or normalise the stored number.
        quantity = {"name": "rmsd", "value": 0.21, "unit": "nm"}
        before = dict(quantity)
        units.check(quantity)
        units.summary([quantity])
        units.check_all([quantity])
        self.assertEqual(quantity, before)


if __name__ == "__main__":
    unittest.main()
