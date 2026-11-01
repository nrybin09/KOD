"""Настройка стандартного шрифта интерфейса Windows."""

from nka_app.common import QApplication, QFont, rcParams


def configure_font():
    QApplication.instance().setFont(QFont("Times New Roman", 12))
    rcParams["font.family"] = "Times New Roman"
    rcParams["font.size"] = 11
