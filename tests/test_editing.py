from pathlib import Path
import math
import unittest

import numpy as np

from nka_app.editing import edit_parameter
from nka_app.navigation import load_dataset, state_vector
from tests.data_files import data_file

ROOT = Path(__file__).resolve().parents[1]


class EditingTests(unittest.TestCase):
    def test_gps_edit_changes_calculation_without_mutating_original(self):
        path = data_file("Rinex alm", "L1CA")
        original_bytes = path.read_bytes()
        dataset = load_dataset(path, "Rinex alm", "L1CA")
        record = dataset.records[1][0]
        initial_math = record.data.m0
        initial_raw = record.parameters["m0"]
        changed = edit_parameter(dataset, record, "m0", str(initial_raw + 0.1))
        self.assertEqual(record.data.m0, initial_math)
        self.assertEqual(record.parameters["m0"], initial_raw)
        self.assertAlmostEqual(changed.records[1][0].data.m0, initial_math + 0.1 * math.pi)
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertIsNot(changed.records[1][0].data, record.data)
        a, _ = state_vector(dataset, record, record.epoch)
        b, _ = state_vector(changed, changed.records[1][0], record.epoch)
        self.assertGreater(np.linalg.norm(a - b), 1000)
        self.assertEqual(changed.edits[-1]["field"], "m0")

    def test_glonass_original_inclination_correction_is_displayed_and_mapped(self):
        path = data_file("Rinex alm", "L1OF")
        dataset = load_dataset(path, "Rinex alm", "L1OF")
        record = dataset.records[1][0]
        raw_delta = float(path.read_text().splitlines()[2].split()[1])
        self.assertAlmostEqual(record.parameters["delta_ia"], raw_delta)
        self.assertNotIn("i_a", record.parameters)
        edited = edit_parameter(dataset, record, "delta_ia", str(raw_delta + 0.01)).records[1][0]
        self.assertAlmostEqual(edited.data.delta_ia, record.data.delta_ia + 0.01)

    def test_glonass_eph_edits_are_in_file_units_for_one_epoch(self):
        dataset = load_dataset(data_file("Rinex eph", "L1OF"), "Rinex eph", "L1OF")
        record = dataset.records[1][0]
        changed = edit_parameter(dataset, record, "x", str(record.data.x + 1))
        a, _ = state_vector(dataset, record, record.epoch)
        b, _ = state_vector(changed, changed.records[1][0], record.epoch)
        np.testing.assert_allclose(b - a, (1000, 0, 0), atol=1e-6)
        self.assertIs(changed.records[1][1], dataset.records[1][1])

    def test_time_field_updates_epoch_and_supports_comma_exponent(self):
        d = load_dataset(data_file("Rinex alm", "L1CA"), "Rinex alm", "L1CA")
        r = d.records[1][0]
        changed = edit_parameter(d, r, "toa", str(r.data.toa + 60).replace(".", ",") + "D0")
        self.assertEqual(changed.records[1][0].epoch - r.epoch, 60)
        self.assertIn(math.floor(changed.records[1][0].epoch), changed.epochs)

    def test_invalid_edits_rejected(self):
        d = load_dataset(data_file("Rinex alm", "L1CA"), "Rinex alm", "L1CA")
        r = d.records[1][0]
        for key, text in (("m0", "nan"), ("m0", "inf"), ("m0", "abc"), ("e", "1"),
                          ("e", "-0.1"), ("sqrtA", "-10"), ("wna", "1.5"),
                          ("toa", "604800"), ("svid", "2")):
            with self.subTest(key=key, text=text), self.assertRaises(ValueError):
                edit_parameter(d, r, key, text)
        self.assertEqual(d.edits, [])


if __name__ == "__main__":
    unittest.main()
