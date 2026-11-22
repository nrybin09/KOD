"""Проверки BINR и совместимости файлов NV08C с текущими парсерами."""

import math
import struct
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nka_app.navigation import load_dataset
from nka_app.nv08c_protocol import (
    BINRStreamParser, GLONASS_SYSTEM, GPS_SYSTEM, NV08CRecord,
    build_binr_message, crc16_binr, decode_almanac, decode_ephemeris,
    request_all_ephemerides, request_almanac, request_ephemeris, write_nv08c_file,
)


NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def pack_f80(value):
    if value == 0:
        return b"\0" * 10
    mantissa, exponent = math.frexp(abs(value))
    significand = int(mantissa * 2 * (1 << 63))
    biased = exponent - 1 + 16383
    if value < 0:
        biased |= 0x8000
    return significand.to_bytes(8, "little") + biased.to_bytes(2, "little")


def gps_almanac_payload():
    data = bytearray(60)
    struct.pack_into("<BBBBfff", data, 0, GPS_SYSTEM, 3, 0, 3, 0.01, 0.95, -8e-12)
    struct.pack_into("<dffffff", data, 16, 5153.7, 1.0, 0.5, 0.4, 0.02, 1e-12, 0.0)
    data[48:58] = pack_f80(147456000.0)
    struct.pack_into("<H", data, 58, 396)
    return bytes(data)


def glonass_almanac_payload():
    data = bytearray(42)
    struct.pack_into("<BBBBffffff", data, 0, GLONASS_SYSTEM, 7, 0, 0x1C,
                     -0.02, 0.7, 1.13, 0.001, 0.5, 36000000.0)
    struct.pack_into("<d", data, 28, 40544000.0)
    struct.pack_into("<fH", data, 36, 0.01, 300)
    return bytes(data)


def gps_ephemeris_payload():
    data = bytearray(130)
    struct.pack_into("<BBffdfdfd", data, 0, GPS_SYSTEM, 5, 50.0, 4e-12, 0.4,
                     1e-6, 0.01, 2e-6, 5153.795)
    struct.pack_into("<dfdfdfdd", data, 42, 345600000.0, 1e-7, 1.0, 1e-7,
                     0.95, 200.0, 0.5, -8e-12)
    struct.pack_into("<d", data, 94, 1e-13)
    struct.pack_into("<f", data, 102, -0.002)
    struct.pack_into("<dfffHH", data, 106, 345600000.0, 0.0, 1e-12, 0.02, 2, 10)
    return bytes(data)


def glonass_ephemeris_payload():
    data = bytearray(93)
    struct.pack_into("<BBb", data, 0, GLONASS_SYSTEM, 8, -4)
    values = (1.2e7, 2.0e7, 1.0e7, 1.0, -2.0, 2.5,
              1e-12, -2e-12, 1e-12, 54000000.0)
    for offset, value in zip(range(3, 83, 8), values):
        struct.pack_into("<d", data, offset, value)
    struct.pack_into("<ffH", data, 83, 1e-10, -0.02, 0)
    return bytes(data)


class BinrProtocolTests(unittest.TestCase):
    def test_examples_from_protocol(self):
        self.assertEqual(request_all_ephemerides().hex(" "), "10 19 ff 01 10 03")
        self.assertEqual(request_ephemeris(GPS_SYSTEM, 2).hex(" "), "10 19 01 02 10 03")
        self.assertEqual(request_almanac(GPS_SYSTEM, 10).hex(" "), "10 20 01 0a 10 03")
        self.assertEqual(request_almanac(GLONASS_SYSTEM, 1).hex(" "), "10 20 02 01 10 03")
        self.assertEqual(crc16_binr(b"\x21\x01"), 0x25F6)
        self.assertEqual(build_binr_message(0x21, b"\x01", True).hex(" "),
                         "10 21 01 10 ff f6 25 10 03")

    def test_fragmented_stream_and_dle_escaping(self):
        message = build_binr_message(0x40, b"\x01\x10\x02", True)
        parser = BINRStreamParser()
        self.assertEqual(parser.feed(message[:4]), [])
        frames = parser.feed(message[4:])
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].payload, b"\x01\x10\x02")
        self.assertTrue(frames[0].checksum_valid)

    def test_decode_all_four_responses(self):
        records = (
            decode_almanac(gps_almanac_payload()),
            decode_almanac(glonass_almanac_payload()),
            decode_ephemeris(gps_ephemeris_payload()),
            decode_ephemeris(glonass_ephemeris_payload()),
        )
        self.assertEqual([(r.kind, r.system, r.prn) for r in records],
                         [("alm", 1, 3), ("alm", 2, 7), ("eph", 1, 5), ("eph", 2, 8)])
        self.assertEqual(records[1].fields["freq_no"], -4)
        self.assertAlmostEqual(records[0].fields["toa"], 147456000.0)


class NV08CFileCompatibilityTests(unittest.TestCase):
    def test_files_are_loaded_by_existing_parsers(self):
        cases = (
            (decode_almanac(gps_almanac_payload()), "alm", "L1CA", "Rinex alm"),
            (decode_almanac(glonass_almanac_payload()), "alm", "L1OF", "Rinex alm"),
            (decode_ephemeris(gps_ephemeris_payload()), "eph", "L1CA", "Rinex eph"),
            (decode_ephemeris(glonass_ephemeris_payload()), "eph", "L1OF", "Rinex eph"),
        )
        extensions = {
            ("alm", "L1CA"): "ralml1ca", ("alm", "L1OF"): "ralml1of",
            ("eph", "L1CA"): "rephl1ca", ("eph", "L1OF"): "rephl1of",
        }
        with tempfile.TemporaryDirectory() as folder:
            for record, kind, signal, source in cases:
                with self.subTest(kind=kind, signal=signal):
                    path = Path(folder) / f"one.{extensions[kind, signal]}"
                    write_nv08c_file([record], kind, signal, path, NOW)
                    dataset = load_dataset(path, source, signal)
                    self.assertEqual(dataset.satellites, [record.prn])
                    self.assertEqual(dataset.available_satellites, [record.prn])


if __name__ == "__main__":
    unittest.main()
