"""Снимки реального интерфейса без окна на рабочем столе: python -m tests.render_demo."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from time import monotonic

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from nka_app.main_window import MainWindow
from tests.data_files import data_file


def main():
    root = Path(__file__).resolve().parents[1]
    app = QApplication([])
    app.setStyle("Fusion")
    window = MainWindow()
    window.source.setCurrentText("Rinex alm")
    window.signal.setCurrentText("L1CA")
    window.load_file(data_file("Rinex alm", "L1CA"))
    window.apply_observer()
    window.selected = {4, 9, 16, 26, 28, 31}
    window._selection_changed()
    window.backward.setValue(-30)
    window.forward.setValue(30)
    window.step.setValue(60)
    window.speed.setValue(60)
    window.show()
    window.start_experiment()
    start = monotonic()
    while (window.running or window._workers) and monotonic() - start < 45:
        app.processEvents()
        QTest.qWait(15)
    if window.running or window._workers:
        window.stop_experiment()
        window.close()
        while window._workers:
            app.processEvents()
            QTest.qWait(15)
        raise RuntimeError("Демонстрационный эксперимент не завершился вовремя")
    output = root / "DOCS/IMAGES"
    output.mkdir(parents=True, exist_ok=True)
    app.processEvents()
    window.grab().save(str(output / "data.png"))
    window.tabs.setCurrentIndex(1)
    window._refresh_plots()
    for canvas in (window.plots.map_canvas, window.plots.globe_canvas, window.plots.angles_canvas):
        canvas.draw()
    app.processEvents()
    window.grab().save(str(output / "plots.png"))
    window.close()
    print("Saved DOCS/IMAGES/data.png and plots.png")


if __name__ == "__main__":
    main()
