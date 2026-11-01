"""Две синхронные части таблицы: параметры и закреплённые az/el."""

from nka_app.common import QAbstractItemView, QHBoxLayout, QHeaderView, QTableWidget, QWidget, Qt


class NavigationTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.parameters = QTableWidget()
        self.angles = QTableWidget(0, 2)
        self.angles.setHorizontalHeaderLabels(["az, °", "el, °"])
        for table in (self.parameters, self.angles):
            table.verticalHeader().hide()
            table.verticalHeader().setDefaultSectionSize(30)
            table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            table.horizontalHeader().setFixedHeight(32)
            table.setWordWrap(False)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            # Одинаковый нижний отступ нужен для точного совмещения строк.
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.parameters.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Ширина каждого столбца определяется его заголовком и самым длинным значением.
        self.parameters.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.angles.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.angles.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.angles.setFixedWidth(220)
        self.angles.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.angles.setStyleSheet("QTableWidget { border-left: 2px solid #536780; }")
        self.parameters.verticalScrollBar().valueChanged.connect(self.angles.verticalScrollBar().setValue)
        self.angles.verticalScrollBar().valueChanged.connect(self.parameters.verticalScrollBar().setValue)
        layout.addWidget(self.parameters, 1)
        layout.addWidget(self.angles)
