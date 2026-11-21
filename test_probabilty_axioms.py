"""Tests for the pure validation and history logic.

Run with:  python -m unittest -v
"""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import probabilty_axioms as ax


class ParsePmfTests(unittest.TestCase):
    def test_parses_whitespace_and_colons(self):
        self.assertEqual(
            ax.parse_pmf(" a : 0.2, b: 0.3 , c :0.5 "),
            {"a": 0.2, "b": 0.3, "c": 0.5},
        )

    def test_empty_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one outcome"):
            ax.parse_pmf("   ")

    def test_missing_colon_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outcome:probability"):
            ax.parse_pmf("a 0.5")

    def test_empty_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "name is empty"):
            ax.parse_pmf(":0.5")

    def test_duplicate_outcome_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "listed twice"):
            ax.parse_pmf("a:0.5, a:0.5")

    def test_non_number_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a number"):
            ax.parse_pmf("a:banana")

    def test_nan_and_infinity_are_rejected(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite"):
                    ax.parse_pmf(f"a:{value}")


class ParseEventsTests(unittest.TestCase):
    def setUp(self):
        self.pmf = {"a": 0.2, "b": 0.3, "c": 0.5}

    def test_parses_events_and_trims(self):
        self.assertEqual(
            ax.parse_events(" a, b ; c ", self.pmf),
            [{"a", "b"}, {"c"}],
        )

    def test_blank_chunks_are_ignored(self):
        self.assertEqual(ax.parse_events(" ; a ;; ", self.pmf), [{"a"}])

    def test_unknown_outcome_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Not in the sample space"):
            ax.parse_events("a, z", self.pmf)


class AxiomTests(unittest.TestCase):
    def test_axiom1_passes_for_non_negative_values(self):
        ok, negatives = ax.check_axiom1({"a": 0.2, "b": 0.8})
        self.assertTrue(ok)
        self.assertEqual(negatives, {})

    def test_axiom1_fails_for_negative_values(self):
        ok, negatives = ax.check_axiom1({"a": 0.5, "b": -0.1})
        self.assertFalse(ok)
        self.assertEqual(negatives, {"b": -0.1})

    def test_axiom1_ignores_tiny_rounding_noise(self):
        self.assertTrue(ax.check_axiom1({"a": -1e-13})[0])

    def test_axiom2_passes_when_sum_is_one(self):
        ok, total = ax.check_axiom2({"a": 0.2, "b": 0.3, "c": 0.5})
        self.assertTrue(ok)
        self.assertAlmostEqual(total, 1.0)

    def test_axiom2_fails_when_sum_is_not_one(self):
        ok, total = ax.check_axiom2({"a": 0.2, "b": 0.3})
        self.assertFalse(ok)
        self.assertAlmostEqual(total, 0.5)

    def test_are_disjoint(self):
        self.assertTrue(ax.are_disjoint([]))
        self.assertTrue(ax.are_disjoint([{"a"}, {"b"}, {"c"}]))
        self.assertFalse(ax.are_disjoint([{"a", "b"}, {"b", "c"}]))

    def test_check_axiom3(self):
        pmf = {"a": 0.2, "b": 0.3, "c": 0.5}
        ok, p_union, p_sum = ax.check_axiom3(pmf, [{"a"}, {"b"}])
        self.assertTrue(ok)
        self.assertAlmostEqual(p_union, 0.5)
        self.assertAlmostEqual(p_sum, 0.5)

    def test_check_axiom3_detects_overlap(self):
        pmf = {"a": 0.2, "b": 0.3, "c": 0.5}
        ok, p_union, p_sum = ax.check_axiom3(pmf, [{"a"}, {"a", "b"}])
        self.assertFalse(ok)
        self.assertAlmostEqual(p_union, 0.5)
        self.assertAlmostEqual(p_sum, 0.7)


class ValidateAssignmentTests(unittest.TestCase):
    def test_valid_assignment(self):
        report = ax.validate_assignment(
            {"a": 0.2, "b": 0.3, "c": 0.5}, [{"a"}, {"b"}]
        )
        self.assertTrue(report.valid)
        self.assertTrue(all(check.ok is True for check in report.checks))

    def test_invalid_assignment(self):
        report = ax.validate_assignment(
            {"a": 0.5, "b": -0.1, "c": 0.6}, [{"a"}, {"b"}]
        )
        self.assertFalse(report.valid)
        self.assertFalse(report.checks[0].ok)
        # The example still sums to 1, so only axiom 1 fails.
        self.assertTrue(report.checks[1].ok)

    def test_axiom3_is_skipped_with_fewer_than_two_events(self):
        report = ax.validate_assignment({"a": 0.5, "b": 0.5}, [])
        self.assertTrue(report.valid)
        self.assertIsNone(report.checks[2].ok)

    def test_axiom3_fails_for_overlapping_events(self):
        report = ax.validate_assignment(
            {"a": 0.5, "b": 0.5}, [{"a"}, {"a", "b"}]
        )
        self.assertFalse(report.valid)
        self.assertFalse(report.checks[2].ok)

    def test_rendered_report_tags(self):
        report = ax.validate_assignment(
            {"a": 0.2, "b": 0.3, "c": 0.5}, [{"a"}, {"b"}]
        )
        lines = ax.render_report(report)
        self.assertIn(("RESULTS", "head"), lines)
        self.assertTrue(any(text.startswith("Axiom 1") and tag == "pass" for text, tag in lines))
        self.assertEqual(lines[-1][1], "pass")

    def test_rendered_invalid_report(self):
        report = ax.validate_assignment({"a": 0.4, "b": 0.4}, [])
        lines = ax.render_report(report)
        self.assertEqual(lines[-1][1], "fail")
        self.assertTrue(any(tag == "fail" for _text, tag in lines))


def make_entry_dict(**overrides):
    data = {
        "id": "abc123",
        "session_number": 1,
        "title": "Session 1",
        "created_at": "2026-01-02T03:04:05+00:00",
        "pmf": "a:1",
        "events": "",
        "lines": [["RESULTS", "head"], ["VERDICT: VALID probability assignment", "pass"]],
        "verdict": "valid",
        "pinned": False,
    }
    data.update(overrides)
    return data


class HistoryEntryTests(unittest.TestCase):
    def test_round_trip(self):
        entry = ax.HistoryEntry.from_dict(make_entry_dict())
        self.assertEqual(entry.to_dict(), make_entry_dict())

    def test_rejects_non_object(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            ax.HistoryEntry.from_dict([])

    def test_rejects_bool_session_number(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            ax.HistoryEntry.from_dict(make_entry_dict(session_number=True))

    def test_rejects_bad_verdict(self):
        with self.assertRaisesRegex(ValueError, "verdict"):
            ax.HistoryEntry.from_dict(make_entry_dict(verdict="maybe"))

    def test_rejects_bad_lines(self):
        with self.assertRaisesRegex(ValueError, "pair"):
            ax.HistoryEntry.from_dict(make_entry_dict(lines=[["only one"]]))

    def test_rejects_bad_timestamp(self):
        with self.assertRaisesRegex(ValueError, "ISO-8601"):
            ax.HistoryEntry.from_dict(make_entry_dict(created_at="yesterday"))


class HistoryStoreTests(unittest.TestCase):
    def test_missing_file_loads_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ax.HistoryStore(Path(tmp) / "history.json")
            self.assertEqual(store.load(), [])

    def test_save_then_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            store = ax.HistoryStore(path)
            entry = ax.HistoryEntry.from_dict(make_entry_dict())
            store.save([entry])

            self.assertTrue(path.exists())
            self.assertEqual(store.load(), [entry])

    def test_save_is_valid_json_and_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            store = ax.HistoryStore(path)
            store.save([ax.HistoryEntry.from_dict(make_entry_dict())])

            with path.open(encoding="utf-8") as history_file:
                self.assertIsInstance(json.load(history_file), list)
            self.assertEqual(
                sorted(item.name for item in Path(tmp).iterdir()),
                ["history.json"],
            )

    def test_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            path.write_text(
                json.dumps([make_entry_dict(), make_entry_dict()]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                ax.HistoryStore(path).load()

    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                ax.HistoryStore(path).load()


class PerformanceCharacteristicTests(unittest.TestCase):
    """Guard the O(n) disjointness check against a return to O(n^2)."""

    def test_many_events_are_checked_quickly(self):
        events = [{str(index)} for index in range(20_000)]
        self.assertTrue(ax.are_disjoint(events))

    def test_tiny_float_noise_does_not_break_axiom2(self):
        pmf = {"a": 0.1, "b": 0.2, "c": 0.3, "d": 0.4}
        ok, total = ax.check_axiom2(pmf)
        self.assertTrue(ok)
        self.assertTrue(math.isclose(total, 1.0))


if __name__ == "__main__":
    unittest.main()
