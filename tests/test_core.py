import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from nka_app.models import Experiment, SimulationSettings
from nka_app.navigation import calculate_sample, file_filter, format_extension, load_dataset, state_vector
from nka_app.exporter import HEADER, experiment_folder_name, export_experiment
from nka_app.coordinates import Observer, azimuth_elevation, blh_to_xyz, transform_xyz, xyz_to_blh
from nka_app.math_eph_glonass import glo_ecef_from_icd
from nka_app.math_eph_gps import ecef_from_eph
from copy import copy
from tests.data_files import data_file

ROOT = Path(__file__).resolve().parents[1]
CASES = (("Rinex eph", "L1CA", 32),
         ("Rinex eph", "L1OF", 27),
         ("Rinex alm", "L1CA", 31),
         ("Rinex alm", "L1OF", 24))


class CoordinatesTests(unittest.TestCase):
    def test_roundtrip_both_datums_including_poles(self):
        for datum in ("WGS84", "PZ90"):
            for blh in ((55.75, 37.62, 200), (0, 0, 0), (-33, 151, -20), (90, 0, 100), (-90, 0, 0)):
                with self.subTest(datum=datum, blh=blh):
                    np.testing.assert_allclose(xyz_to_blh(blh_to_xyz(*blh, datum), datum), blh, atol=1e-6)

    def test_known_equator_position(self):
        np.testing.assert_allclose(blh_to_xyz(0, 0, 0), (6378137, 0, 0))

    def test_datum_translation_roundtrip(self):
        position = np.array([1e6, 2e6, 3e6])
        wgs = transform_xyz(position, "PZ90", "WGS84")
        np.testing.assert_allclose(wgs - position, (-0.36, 0.08, 0.18), atol=1e-8)
        np.testing.assert_allclose(transform_xyz(wgs, "WGS84", "PZ90"), position)

    def test_cardinal_directions_and_zenith(self):
        observer = Observer.from_values((0, 0, 0), "BLH", "WGS84")
        xyz = np.array(observer.xyz)
        for delta, az, el in (((0, 1000, 0), 90, 0), ((0, 0, 1000), 0, 0), ((1000, 0, 0), 0, 90)):
            np.testing.assert_allclose(azimuth_elevation(xyz + delta, observer, "WGS84"), (az, el), atol=1e-8)

    def test_invalid_coordinates(self):
        for values, mode in (((0, 0, 0), "XYZ"), ((91, 0, 0), "BLH"), ((0, 181, 0), "BLH"), ((float('nan'), 1, 1), "XYZ")):
            with self.assertRaises(ValueError):
                Observer.from_values(values, mode, "WGS84")


class NavigationTests(unittest.TestCase):
    def test_all_existing_data_files(self):
        observer = Observer.from_values((55.75, 37.62, 200), "BLH", "WGS84")
        for source, signal, count in CASES:
            with self.subTest(source=source, signal=signal):
                dataset = load_dataset(data_file(source, signal), source, signal)
                self.assertEqual(len(dataset.satellites), count)
                for prn in dataset.available_satellites:
                    sample = calculate_sample(dataset, observer, prn, dataset.epochs[0], 0, 8)
                    self.assertTrue(np.all(np.isfinite(sample.values())))
                    self.assertTrue(2e7 < sample.r < 3e7)
                    self.assertTrue(0 <= sample.az < 360)
                    self.assertTrue(-90 <= sample.el <= 90)

    def test_all_new_almanac_files(self):
        expected_fields = {
            "L1CA": (
                "alm_day", "alm_month", "alm_year", "receive_time", "svid", "svHealth",
                "wna", "toa", "day", "month", "year", "day_time", "af0", "af1",
                "omegaDot", "omega0", "i0", "m0", "e", "sqrtA", "w",
            ),
            "L1OF": (
                "alm_day", "alm_month", "alm_year", "receive_time", "svid", "freqNo",
                "health", "day", "month", "year", "ta", "glo_utc", "gps_glo", "clock",
                "lambda_a", "delta_ia", "w_a", "eps_a", "delta_Ta", "delta_Ta_dot",
            ),
        }
        for signal, folder, extension in (
            ("L1CA", "agp", "ralml1ca"),
            ("L1OF", "agl", "ralml1of"),
        ):
            paths = sorted((ROOT / "data" / folder).rglob(f"*.{extension}"))
            self.assertTrue(paths)
            for path in paths:
                with self.subTest(path=path.name):
                    dataset = load_dataset(path, "Rinex alm", signal)
                    self.assertTrue(dataset.available_satellites)
                    for prn in dataset.available_satellites:
                        record = dataset.records[prn][0]
                        self.assertEqual(tuple(record.parameters), expected_fields[signal])
                        position, velocity = state_vector(dataset, record, record.epoch, 7)
                        self.assertTrue(np.all(np.isfinite(np.r_[position, velocity])))
                        self.assertTrue(2e7 < np.linalg.norm(position) < 3e7)

    def test_records_at_returns_only_the_selected_node_second(self):
        dataset = load_dataset(data_file("Rinex eph", "L1CA"), "Rinex eph", "L1CA")
        epoch = next(value for value in dataset.epochs if dataset.label(value, True).endswith("02:00:00 GPS"))
        records = dataset.records_at(epoch)
        self.assertEqual(len(records), 26)
        self.assertTrue(records)
        self.assertTrue(all(math.floor(record.epoch) == math.floor(epoch)
                            for record in records))
        self.assertEqual([record.prn for record in records], sorted(record.prn for record in records))

    def test_ephemeris_positions_use_original_calculators(self):
        for signal in ("L1CA", "L1OF"):
            d = load_dataset(data_file("Rinex eph", signal), "Rinex eph", signal)
            r = d.records[d.satellites[0]][0]
            position, velocity = state_vector(d, r, r.epoch)
            if signal == "L1CA":
                expected = ecef_from_eph(r.data, r.data.toe)
            else:
                expected = 1000 * np.array([r.data.x, r.data.y, r.data.z])
            np.testing.assert_allclose(position, expected, atol=1e-6)
            self.assertTrue(100 < np.linalg.norm(velocity) < 6000)

    def test_glonass_epoch_is_not_message_time(self):
        d = load_dataset(data_file("Rinex eph", "L1OF"), "Rinex eph", "L1OF")
        r = next(r for r in d.records[1] if r.data.tb == 30)
        self.assertIn("2025-05-17 00:15", d.label(r.epoch))
        self.assertEqual(r.data.tb, 30)  # исходная запись не изменена адаптером

    def test_glonass_integration_step_accuracy(self):
        d = load_dataset(data_file("Rinex eph", "L1OF"), "Rinex eph", "L1OF")
        record = d.records[1][0]
        local = copy(record.data)
        local.tb = 0
        for dt in (-900, 900):
            position, _ = state_vector(d, record, record.epoch + dt)
            np.testing.assert_allclose(position, glo_ecef_from_icd(local, dt), atol=0.03, rtol=0)

    def test_gps_week_crossing_is_continuous(self):
        d = load_dataset(data_file("Rinex alm", "L1CA"), "Rinex alm", "L1CA")
        r = d.records[1][0]
        boundary = (r.data.wna + 1) * 604800
        a, _ = state_vector(d, r, boundary - 1)
        b, _ = state_vector(d, r, boundary + 1)
        self.assertLess(np.linalg.norm(a - b), 10000)

    def test_glonass_almanac_day_crossing(self):
        d = load_dataset(data_file("Rinex alm", "L1OF"), "Rinex alm", "L1OF")
        r = d.records[1][0]
        boundary = r.data.Na * 86400
        a, _ = state_vector(d, r, boundary - 1, 8)
        b, _ = state_vector(d, r, boundary + 1, 8)
        self.assertLess(np.linalg.norm(a - b), 10000)

    def test_nv08c_placeholder(self):
        for signal in ("L1CA", "L1OF"):
            with self.assertRaises(NotImplementedError):
                load_dataset("unused", "NV08C eph", signal)
            self.assertEqual(file_filter("NV08C alm", signal),
                             f"NV08C alm / {signal} (*.{format_extension('NV08C alm', signal)})")

    def test_input_name_is_arbitrary_but_extension_is_required(self):
        source, signal = "Rinex alm", "L1CA"
        original = data_file(source, signal)
        with tempfile.TemporaryDirectory() as tmp:
            arbitrary = Path(tmp) / ("любое-имя." + format_extension(source, signal))
            arbitrary.write_bytes(original.read_bytes())
            self.assertTrue(load_dataset(arbitrary, source, signal).satellites)
            wrong = Path(tmp) / "любое-имя.dat"
            wrong.write_bytes(original.read_bytes())
            with self.assertRaisesRegex(ValueError, "требуется файл формата"):
                load_dataset(wrong, source, signal)

    def test_empty_orbits_remain_visible_but_cannot_be_calculated(self):
        d = load_dataset(data_file("Rinex alm", "L1CA"), "Rinex alm", "L1CA")
        self.assertEqual(d.available_satellites, d.satellites)
        d = load_dataset(data_file("Rinex eph", "L1OF"), "Rinex eph", "L1OF")
        self.assertEqual(set(d.satellites) - set(d.available_satellites), {27})

    def test_wrong_signal_rejected(self):
        for source, signal, _ in CASES:
            with self.subTest(source=source, signal=signal), self.assertRaises(ValueError):
                load_dataset(data_file(source, signal), source, "L1OF" if signal == "L1CA" else "L1CA")

    def test_truncated_almanac_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ("input." + format_extension("Rinex alm", "L1CA"))
            path.write_text("1 1 1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_dataset(path, "Rinex alm", "L1CA")

    def test_original_files_unchanged(self):
        hashes = json.loads((ROOT / "tests/original_hashes.json").read_text())
        for relative, expected in hashes.items():
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected.lower())


class ExperimentTests(unittest.TestCase):
    def test_symmetric_time_grid(self):
        settings = SimulationSettings(0, backward_minutes=-1 / 3, forward_minutes=1 / 3, step_seconds=10)
        np.testing.assert_allclose(settings.offsets(), [-20, -10, 0, 10, 20])

    def test_uneven_grid_keeps_endpoint(self):
        settings = SimulationSettings(0, backward_minutes=0, forward_minutes=1, step_seconds=17)
        np.testing.assert_allclose(settings.offsets(), [0, 17, 34, 51, 60])

    def test_grid_by_number_of_points(self):
        settings = SimulationSettings(0, backward_minutes=-1, forward_minutes=1, sample_count=5)
        np.testing.assert_allclose(settings.offsets(), [-60, -30, 0, 30, 60])
        with self.assertRaises(ValueError):
            SimulationSettings(0, sample_count=1).offsets()

    def test_epsilon_is_symmetric_tolerance_and_does_not_shift_center(self):
        settings = SimulationSettings(100, epsilon=10, backward_minutes=0, forward_minutes=0)
        self.assertEqual(settings.center, 100)
        np.testing.assert_array_equal(settings.offsets(), [0])
        with self.assertRaises(ValueError):
            SimulationSettings(100, epsilon=-1).offsets()

    def test_invalid_settings(self):
        for kwargs in ({"step_seconds": 0}, {"speed": 0}, {"backward_minutes": 1},
                       {"forward_minutes": -1}, {"step_seconds": 0.0001}, {"epsilon": float('inf')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SimulationSettings(0, **kwargs).offsets()

    def test_export_columns_rows_radius_and_no_overwrite(self):
        dataset = load_dataset(data_file("Rinex alm", "L1CA"), "Rinex alm", "L1CA")
        observer = Observer.from_values((55.75, 37.62, 200), "BLH", "WGS84")
        settings = SimulationSettings(dataset.epochs[0], epsilon=7, backward_minutes=-1 / 3,
                                      forward_minutes=1 / 3, step_seconds=10)
        experiment = Experiment(dataset, observer, settings, (1, 2))
        for prn in experiment.selected:
            for dt in settings.offsets():
                experiment.samples[prn].append(calculate_sample(dataset, observer, prn, settings.center + dt, dt))
        experiment.complete = True
        with tempfile.TemporaryDirectory() as tmp:
            first = export_experiment(experiment, tmp)
            second = export_experiment(experiment, tmp)
            self.assertNotEqual(first, second)
            self.assertRegex(first.name, r"^experiment_GPS_W\d+_D\d+_\d{6}$")
            self.assertEqual(second.name, first.name + "_01")
            for prn in (1, 2):
                path = first / f"{prn:02d}_L1CA.txt"
                lines = path.read_text().splitlines()
                self.assertEqual(lines[0], HEADER)
                self.assertFalse(any(line.startswith("#") for line in lines))
                data = np.loadtxt(lines[1:])
                self.assertEqual(data.shape, (5, 10))
                np.testing.assert_allclose(data[:, 0], [-20, -10, 0, 10, 20])
                np.testing.assert_allclose(data[:, 9], np.linalg.norm(data[:, 3:6], axis=1))
            manifest = json.loads((first / "experiment.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["complete"])
            self.assertEqual(manifest["settings"]["epsilon"], 7)
            self.assertNotIn("source_file", manifest)

    def test_calendar_export_folder_uses_node_time(self):
        dataset = load_dataset(data_file("Rinex eph", "L1OF"), "Rinex eph", "L1OF")
        self.assertEqual(
            experiment_folder_name(dataset, dataset.epochs[0]),
            "experiment_GLONASS_20250517_001500",
        )
        gps = load_dataset(data_file("Rinex eph", "L1CA"), "Rinex eph", "L1CA")
        self.assertEqual(
            experiment_folder_name(gps, gps.epochs[0]),
            "experiment_GPS_20250118_000000",
        )


if __name__ == "__main__":
    unittest.main()
