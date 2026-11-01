"""Единственная точка запуска приложения: ``python main.py``."""

from nka_app.common import QApplication, sys
from nka_app.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Моделирование НКА")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
