"""Интеграционные проверки Qt без открытия окна на рабочем столе."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
from pathlib import Path
from time import monotonic
import unittest
from unittest.mock import patch
import tempfile

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from nka_app.common import NAVIGATION_TABLE_HEADERS
from nka_app.main_window import MainWindow
from tests.test_core import CASES, ROOT
from tests.data_files import data_file


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.window = MainWindow()
        self.errors = []
        self.error_patch = patch.object(self.window, "_error", self.errors.append)
        self.error_patch.start()

    def wait_until(self, predicate, timeout=25):
        start = monotonic()
        while not predicate() and monotonic() - start < timeout:
            self.app.processEvents()
            QTest.qWait(15)
        self.assertTrue(predicate(), self.window.status.text())
        self.assertEqual(self.errors, [])

    def tearDown(self):
        self.window.stop_experiment()
        self.window.close()
        self.wait_until(lambda: not self.window._workers)
        self.error_patch.stop()
        self.window.deleteLater()
        self.app.processEvents()

    def load(self, source="Rinex alm", signal="L1CA"):
        self.window.source.setCurrentText(source)
        self.window.signal.setCurrentText(signal)
        self.assertTrue(self.window.load_file(data_file(source, signal)))

    def test_initial_locks_loading_and_coordinate_lock(self):
        w = self.window
        self.assertEqual(w.reset_button.text(), "Сбросить данные")
        self.assertFalse(any(label.text() == "МОДЕЛИРОВАНИЕ НКА" for label in w.findChildren(QLabel)))
        self.assertEqual(w.source.currentText(), "")
        self.assertEqual(w.signal.currentText(), "")
        self.assertFalse(w.load_button.isEnabled())
        self.assertEqual(w.lower_mask.value(), 10)
        w.source.setCurrentText("Rinex eph")
        self.assertFalse(w.load_button.isEnabled())
        w.source.setCurrentIndex(0)
        self.assertFalse(w.coordinates_group.isEnabled())
        self.assertFalse(w.model_group.isEnabled())
        self.assertFalse(w.tabs.isTabEnabled(1))
        self.load()
        self.assertEqual(w.table.rowCount(), 31)
        self.assertFalse(w.load_button.isEnabled())
        self.assertTrue(w.coordinates_group.isEnabled())
        w.apply_observer()
        self.wait_until(lambda: bool(w.current_samples) and not w._workers)
        self.assertTrue(all(
            w.angle_table.item(row, column).text() != ""
            for row in range(w.angle_table.rowCount())
            for column in range(w.angle_table.columnCount())
        ))
        self.assertFalse(w.coordinates_group.isEnabled())
        self.assertTrue(w.model_group.isEnabled())
        self.assertFalse(w.start_button.isEnabled())
        w._row_clicked(0, 1)
        self.assertIn(1, w.selected)
        self.assertTrue(w.start_button.isEnabled())
        self.assertEqual(w.table.item(0, 1).background().color().name(), "#c9efd8")
        w._row_clicked(0, 1)
        self.assertNotIn(1, w.selected)

    def test_all_four_modes_complete(self):
        w = self.window
        expected_rows = {
            ("Rinex eph", "L1CA"): 28,
            ("Rinex eph", "L1OF"): 19,
            ("Rinex alm", "L1CA"): 31,
            ("Rinex alm", "L1OF"): 1,
        }
        for source, signal, _count in CASES:
            with self.subTest(source=source, signal=signal):
                self.load(source, signal)
                w.apply_observer()
                w._row_clicked(0, 1)
                w.backward.setValue(-0.1)
                w.forward.setValue(0.1)
                w.step.setValue(6)
                w.speed.setValue(60)
                w.start_experiment()
                self.wait_until(lambda: not w.running and not w._workers)
                self.assertTrue(w.experiment.complete)
                self.assertTrue(w.tabs.isTabEnabled(1))
                self.assertEqual(len(w.experiment.samples[min(w.selected)]), 3)
                self.assertEqual(w.table.rowCount(), expected_rows[source, signal])
                self.assertTrue(w.export_button.isEnabled())
                w.reset_session()

    def test_node_filters_table_and_removes_hidden_selection(self):
        w = self.window
        self.load("Rinex eph", "L1CA")
        first_epoch = w.node.itemData(0)
        second_index = next(i for i in range(w.node.count())
                            if "02:00:00 GPS" in w.node.itemText(i))
        second_epoch = w.node.itemData(second_index)
        first_prns = {record.prn for record in w.dataset.records_at(first_epoch)}
        second_prns = {record.prn for record in w.dataset.records_at(second_epoch)}
        disappearing = min(first_prns - second_prns)
        row = w._table_prns.index(disappearing)
        w._row_clicked(row, 1)
        self.assertIn(disappearing, w.selected)

        w.node.setCurrentIndex(second_index)

        self.assertEqual(w.table.rowCount(), len(w.dataset.records_at(second_epoch)))
        self.assertEqual(w._table_prns, [record.prn for record in w.dataset.records_at(second_epoch)])
        self.assertNotIn(disappearing, w.selected)
        self.assertTrue(all(record in w.dataset.records[record.prn]
                            for record in w._shown_records.values()))

    def test_epsilon_adds_all_records_in_both_time_directions(self):
        w = self.window
        self.load("Rinex eph", "L1CA")
        node_index = next(i for i in range(w.node.count())
                          if "02:00:00 GPS" in w.node.itemText(i))
        w.node.setCurrentIndex(node_index)
        node = w.node.currentData()
        exact_prns = set(w._table_prns)

        w.epsilon.setValue(7200)
        self.wait_until(lambda: len(w._table_prns) > len(exact_prns))

        self.assertGreater(len(w._table_prns), len(exact_prns))
        self.assertGreater(len(w._table_prns), len(set(w._table_prns)))
        deltas = [math.floor(record.epoch) - math.floor(node)
                  for record in w._shown_records.values()]
        self.assertTrue(all(abs(delta) <= 7200 for delta in deltas))
        self.assertTrue(any(delta < 0 for delta in deltas))
        self.assertTrue(any(delta > 0 for delta in deltas))

    def test_same_satellite_is_repeated_for_different_node_times(self):
        w = self.window
        self.load("Rinex eph", "L1CA")
        node_index = next(i for i in range(w.node.count())
                          if "01:59:44 GPS" in w.node.itemText(i))
        w.node.setCurrentIndex(node_index)
        w.epsilon.setValue(62)
        self.wait_until(lambda: w._table_prns.count(2) >= 2)

        records = [record for record in w._shown_records.values() if record.prn == 2]
        self.assertGreaterEqual(len(records), 2)
        self.assertEqual([record.epoch for record in records], sorted(record.epoch for record in records))
        self.assertEqual(w._table_prns.count(2), len(records))
        self.assertIn("· 27 НКА", w.node.currentText())

    def test_glonass_uses_the_same_epsilon_duplicates_and_counts(self):
        w = self.window
        self.load("Rinex eph", "L1OF")
        self.assertIn("ГЛОНАСС", w.node.currentText())
        self.assertIn("ГЛОНАСС", w.file_status.text())

        w.epsilon.setValue(1800)

        expected = w.dataset.records_at(w.node.currentData(), 1800)
        self.wait_until(lambda: w.table.rowCount() == len(expected))
        unique = len({record.prn for record in expected})
        self.assertEqual(w.table.rowCount(), len(expected))
        self.assertGreater(len(expected), unique)
        self.assertIn(f"/ {unique} НКА", w.visibility_label.text())
        self.assertIn(f"строк: {len(expected)}", w.visibility_label.text())

    def test_masks_update_without_a_worker_or_timer(self):
        w = self.window
        self.load()
        w.apply_observer()
        self.wait_until(lambda: bool(w.current_samples) and not w._workers)
        original = w.current_samples
        generation = w._generation
        w.lower_mask.setValue(85)
        self.assertEqual(w.sky.lower, 85)
        self.assertIs(w.current_samples, original)
        self.assertEqual(w._generation, generation)
        w.upper_mask.setValue(20)
        self.assertEqual(w.lower_mask.value(), 20)
        self.assertEqual(w.sky.upper, 20)

    def test_stop_partial_export_then_parameter_change(self):
        w = self.window
        self.load()
        w.apply_observer()
        w._row_clicked(0, 1)
        w.speed.setValue(2)
        w.start_experiment()
        self.wait_until(lambda: len(w.experiment.samples[1]) >= 1)
        w.stop_experiment()
        self.wait_until(lambda: not w._workers)
        self.assertFalse(w.experiment.complete)
        self.assertTrue(w.export_button.isEnabled())
        with tempfile.TemporaryDirectory() as tmp:
            with patch("nka_app.main_window.QFileDialog.getExistingDirectory", return_value=tmp), patch("nka_app.main_window.QMessageBox.information"):
                w.export_results()
            self.assertEqual(len(list(Path(tmp).glob("*/01_L1CA.txt"))), 1)
        w.epsilon.setValue(10)
        self.assertIsNone(w.experiment)
        self.assertFalse(w.export_button.isEnabled())
        self.assertFalse(w.tabs.isTabEnabled(1))

    def test_rapid_preview_changes_and_reset(self):
        w = self.window
        self.load("Rinex eph", "L1OF")
        w.apply_observer()
        for epsilon in (10, -20, 30, 40):
            w.epsilon.setValue(epsilon)
            w._preview()
        w.reset_session()
        self.wait_until(lambda: not w._workers)
        self.assertIsNone(w.dataset)
        self.assertFalse(w.current_samples)
        self.assertEqual(w.table.rowCount(), 0)
        self.assertEqual(w.source.currentText(), "")
        self.assertEqual(w.signal.currentText(), "")
        self.assertFalse(w.load_button.isEnabled())
        self.assertEqual(w.lower_mask.value(), 10)

    def test_point_count_mode_and_unavailable_selection(self):
        w = self.window
        self.load()
        w.apply_observer()
        self.assertEqual(len(w._table_prns), 31)
        w.select_satellites("all")
        self.assertEqual(len(w.selected), 31)
        w.backward.setValue(-0.1)
        w.forward.setValue(0.1)
        w.grid_mode.setCurrentIndex(1)
        w.grid_count.setValue(5)
        w.speed.setValue(60)
        w.start_experiment()
        self.wait_until(lambda: not w.running and not w._workers)
        self.assertEqual(len(w.experiment.samples[1]), 5)
        self.assertEqual(w.experiment.samples[1][0].dt, -6)
        self.assertEqual(w.experiment.samples[1][-1].dt, 6)

    def test_restart_after_stop_ignores_old_frames(self):
        w = self.window
        self.load()
        w.apply_observer()
        w._row_clicked(0, 1)
        w.start_experiment()
        self.wait_until(lambda: bool(w.experiment.samples[1]))
        w.stop_experiment()
        w.backward.setValue(0)
        w.forward.setValue(0)
        w.start_experiment()
        self.wait_until(lambda: not w.running and not w._workers)
        self.assertTrue(w.experiment.complete)
        self.assertEqual(len(w.experiment.samples[1]), 1)
        self.assertEqual(w.experiment.samples[1][0].dt, 0)

    def test_coordinate_switch_and_small_screen_layout(self):
        w = self.window
        self.load()
        original = [v.value() for v in w.coord_values]
        w.coord_format.setCurrentText("XYZ")
        self.assertGreater(sum(v.value() ** 2 for v in w.coord_values), 1e12)
        w.coord_format.setCurrentText("BLH")
        for index, (expected, value) in enumerate(zip(original, w.coord_values)):
            self.assertAlmostEqual(value.value(), expected, delta=0.002 if index == 2 else 1e-7)
        w.resize(1120, 760)
        w.show()
        self.app.processEvents()
        self.assertLessEqual(w.sky.geometry().bottom(), w.visibility_label.geometry().top())

    def test_step_and_speed_do_not_rebuild_but_time_range_does(self):
        w = self.window
        self.load()
        w.apply_observer()
        self.wait_until(lambda: bool(w.current_samples) and not w._workers)
        first_item = w.table.item(0, 1)
        with patch.object(w, "_update_raw_values", wraps=w._update_raw_values) as rebuild:
            w.step.setValue(w.step.value() + 1)
            w.speed.setValue(w.speed.value() + 1)
            self.app.processEvents()
            rebuild.assert_not_called()
        self.assertIs(w.table.item(0, 1), first_item)
        self.assertFalse(w.preview_timer.isActive())
        with patch.object(w, "_update_raw_values", wraps=w._update_raw_values) as rebuild:
            w.backward.setValue(w.backward.value() - 1)
            w.forward.setValue(w.forward.value() + 1)
            rebuild.assert_not_called()
            QTest.qWait(500)
            self.app.processEvents()
            rebuild.assert_not_called()
            QTest.qWait(600)
            self.app.processEvents()
            self.assertEqual(rebuild.call_count, 1)
        with patch.object(w, "_update_raw_values", wraps=w._update_raw_values) as rebuild:
            for epsilon in (10, 20, 30, 40, 50):
                w.epsilon.setValue(epsilon)
            rebuild.assert_not_called()
            QTest.qWait(500)
            self.app.processEvents()
            rebuild.assert_not_called()
            QTest.qWait(600)
            self.app.processEvents()
            self.assertEqual(rebuild.call_count, 1)

    def test_observer_star_uses_entered_coordinates_and_world_view(self):
        w = self.window
        self.load()
        for widget, value in zip(w.coord_values, (-33.87, 151.21, 10)):
            widget.setValue(value)
        w.apply_observer()
        w._row_clicked(0, 1)
        w.backward.setValue(0)
        w.forward.setValue(0)
        w.start_experiment()
        self.wait_until(lambda: not w.running and not w._workers)

        self.assertEqual(
            [w.plots.tabs.tabText(i) for i in range(w.plots.tabs.count())],
            ["1. Карта Земли", "2. 3D-анимация", "3. Временные az/el"],
        )
        self.assertTrue(w.plots.world.isChecked())
        star = next(line for line in w.plots.map_ax.lines if line.get_marker() == "*")
        self.assertAlmostEqual(float(star.get_xdata()[0]), 151.21, places=5)
        self.assertAlmostEqual(float(star.get_ydata()[0]), -33.87, places=5)

    def test_file_columns_and_frozen_angles_scroll_together(self):
        w = self.window
        self.load("Rinex eph", "L1OF")
        headers = [w.table.horizontalHeaderItem(i).text() for i in range(w.table.columnCount())]
        expected_headers = [NAVIGATION_TABLE_HEADERS.get(key, key) for key in w._raw_keys]
        self.assertEqual(headers[3:], expected_headers)
        for old, new in (("dx", "Vx"), ("dy", "Vy"), ("dz", "Vz"),
                         ("ddx", "Ax"), ("ddy", "Ay"), ("ddz", "Az")):
            self.assertNotIn(old, headers)
            self.assertIn(new, headers)
        self.assertNotIn("dt, с", headers)
        self.assertNotIn("R, м", headers)
        self.assertNotIn("az, °", headers)
        self.assertEqual(w.angle_table.horizontalHeaderItem(0).text(), "az, °")
        self.assertEqual(w.angle_table.horizontalHeaderItem(1).text(), "el, °")
        w.resize(1120, 760)
        w.show()
        self.app.processEvents()
        fixed_geometry = w.angle_table.geometry()
        horizontal = w.table.horizontalScrollBar()
        self.assertGreater(horizontal.maximum(), 0)
        horizontal.setValue(horizontal.maximum())
        self.app.processEvents()
        self.assertEqual(w.angle_table.geometry(), fixed_geometry)
        scrollbar = w.angle_table.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(scrollbar.maximum())
        self.assertEqual(w.table.verticalScrollBar().value(), scrollbar.value())
        last_row = w.table.rowCount() - 1
        self.assertEqual(w.table.rowViewportPosition(last_row), w.angle_table.rowViewportPosition(last_row))
        w.table.verticalScrollBar().setValue(0)
        self.assertEqual(scrollbar.value(), 0)

    def test_angle_columns_start_at_node_and_follow_experiment(self):
        w = self.window
        self.load()
        w.apply_observer()
        self.wait_until(lambda: bool(w.node_samples) and not w._workers)
        node_angles = (w.angle_table.item(0, 0).text(), w.angle_table.item(0, 1).text())
        unselected_node_angles = (w.angle_table.item(1, 0).text(), w.angle_table.item(1, 1).text())
        w._row_clicked(0, 1)
        w.backward.setValue(0)
        w.forward.setValue(10)
        w.step.setValue(600)
        w.speed.setValue(60)
        w.start_experiment()
        self.wait_until(lambda: not w.running and not w._workers)
        last = w.current_samples[1]
        final_angles = (f"{last.az:.3f}", f"{last.el:.3f}")
        self.assertNotEqual(final_angles, node_angles)
        self.assertEqual(
            (w.angle_table.item(0, 0).text(), w.angle_table.item(0, 1).text()),
            final_angles,
        )
        self.assertEqual(set(w.current_samples), {1})
        self.assertEqual(
            (w.angle_table.item(1, 0).text(), w.angle_table.item(1, 1).text()),
            unselected_node_angles,
        )

    def test_edit_updates_preview_and_does_not_toggle_selection(self):
        w = self.window
        self.load()
        w.apply_observer()
        self.wait_until(lambda: bool(w.current_samples) and not w._workers)
        old_x = w.current_samples[1].x
        original = w.dataset
        column = w._raw_start + w._raw_keys.index("m0")
        w._row_clicked(0, column)
        self.assertFalse(w.selected)
        item = w.table.item(0, column)
        self.assertTrue(item.flags() & Qt.ItemFlag.ItemIsEditable)
        item.setText(str(original.records[1][0].data.m0 + 0.2))
        self.assertEqual(len(w.dataset.edits), 1)
        self.assertFalse(w.selected)
        self.wait_until(lambda: bool(w.current_samples) and not w._workers and not w.preview_timer.isActive())
        self.assertGreater(abs(w.current_samples[1].x - old_x), 1000)
        self.assertNotEqual(w.angle_table.item(0, 0).text(), "")
        self.assertFalse(w.angle_table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable)

    def test_invalid_edit_restores_value_and_results(self):
        w = self.window
        self.load()
        original = w.dataset
        column = w._raw_start + w._raw_keys.index("e")
        item = w.table.item(0, column)
        old_text = item.text()
        item.setText("not-a-number")
        self.assertEqual(item.text(), old_text)
        self.assertIs(w.dataset, original)
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()

    def test_double_click_editor_commits_with_enter_and_cancels_with_escape(self):
        w = self.window
        self.load()
        w.show()
        self.app.processEvents()
        item = w.table.item(0, w._raw_start)
        key = w._raw_keys[0]
        before = w.dataset.records[1][0].parameters[key]
        point = w.table.visualItemRect(item).center()
        QTest.mouseClick(w.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(w.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
        editor = w.table.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.selectAll()
        QTest.keyClicks(editor, str(before + 1))
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(w.dataset.records[1][0].parameters[key], before + 1)
        self.assertFalse(w.selected)
        QTest.keyClick(w.table, Qt.Key.Key_F2)
        editor = QApplication.focusWidget()
        self.assertIsInstance(editor, QLineEdit)
        editor.selectAll()
        QTest.keyClicks(editor, "123")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(w.dataset.records[1][0].parameters[key], before + 1)
        self.assertEqual(len(w.dataset.edits), 1)

    def test_edit_clears_results_and_is_disabled_during_run(self):
        w = self.window
        self.load()
        w.apply_observer()
        w._row_clicked(0, 1)
        w.backward.setValue(0)
        w.forward.setValue(0)
        w.start_experiment()
        self.assertEqual(w.table.editTriggers(), w.table.EditTrigger.NoEditTriggers)
        self.wait_until(lambda: not w.running and not w._workers)
        column = w._raw_start + w._raw_keys.index("m0")
        w.table.item(0, column).setText("0.123")
        self.assertIsNone(w.experiment)
        self.assertFalse(w.export_button.isEnabled())
        self.assertEqual(w.selected, {1})


if __name__ == "__main__":
    unittest.main()
