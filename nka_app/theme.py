"""Единая светлая палитра и шрифт приложения."""

from nka_app.common import QApplication, QColor, QFont, QPalette, rcParams


def _light_palette():
    """Создать палитру, которая не зависит от темы операционной системы."""

    palette = QPalette()
    active = {
        QPalette.ColorRole.Window: "#f3f6fa",
        QPalette.ColorRole.WindowText: "#233047",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#eef2f7",
        QPalette.ColorRole.ToolTipBase: "#fffbe6",
        QPalette.ColorRole.ToolTipText: "#233047",
        QPalette.ColorRole.Text: "#233047",
        QPalette.ColorRole.Button: "#f8fafc",
        QPalette.ColorRole.ButtonText: "#233047",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#d5deeb",
        QPalette.ColorRole.Dark: "#7b8797",
        QPalette.ColorRole.Mid: "#b9c8dd",
        QPalette.ColorRole.Shadow: "#536780",
        QPalette.ColorRole.Link: "#245caa",
        QPalette.ColorRole.Highlight: "#245caa",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#7b8797",
    }
    for role, color in active.items():
        palette.setColor(QPalette.ColorGroup.Active, role, QColor(color))
        palette.setColor(QPalette.ColorGroup.Inactive, role, QColor(color))

    disabled = {
        QPalette.ColorRole.Window: "#f3f6fa",
        QPalette.ColorRole.WindowText: "#96a0af",
        QPalette.ColorRole.Base: "#f1f3f6",
        QPalette.ColorRole.AlternateBase: "#edf0f4",
        QPalette.ColorRole.Text: "#96a0af",
        QPalette.ColorRole.Button: "#f1f3f6",
        QPalette.ColorRole.ButtonText: "#96a0af",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#e4e8ee",
        QPalette.ColorRole.Dark: "#a8b0bc",
        QPalette.ColorRole.Mid: "#cbd2dc",
        QPalette.ColorRole.Shadow: "#7b8797",
        QPalette.ColorRole.Highlight: "#b9c8dd",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#a8b0bc",
    }
    for role, color in disabled.items():
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    return palette


def configure_font():
    app = QApplication.instance()
    app.setStyle("Fusion")
    app.setPalette(_light_palette())
    app.setFont(QFont("Times New Roman", 12))
    rcParams["font.family"] = "Times New Roman"
    rcParams["font.size"] = 11
