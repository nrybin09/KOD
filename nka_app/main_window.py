"""Главное окно по макету из описания программы."""

from nka_app.common import (
    NAVIGATION_TABLE_HEADERS, PROJECT_ROOT, SIGNALS, SOURCES,
    TABLE_UPDATE_DELAY_MS, TIME_FIELDS,
    QAbstractItemView, QApplication, QBrush, QColor, QComboBox, QDoubleSpinBox,
    QEvent, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSignalBlocker, QSpinBox, QSplitter, QTabWidget,
    QTableWidgetItem, QTimer, QVBoxLayout, QWidget, Qt,
)

from nka_app.models import Experiment, SimulationSettings
from nka_app.editing import edit_parameter
from nka_app.navigation import file_filter, load_dataset
from nka_app.worker import CalculationWorker
from nka_app.exporter import export_experiment
from nka_app.coordinates import Observer, blh_to_xyz, xyz_to_blh
from nka_app.theme import configure_font
from nka_app.navigation_table import NavigationTable
from nka_app.sky import SkyMap
from nka_app.trajectories import TrajectoryPlots

def spin(low, high, value, decimals=2, suffix=""):
    widget = QDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(low, high)
    widget.setValue(value)
    widget.setSuffix(suffix)
    widget.setKeyboardTracking(False)
    return widget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        QApplication.instance().installEventFilter(self)
        configure_font()
        self.setWindowTitle("Моделирование движения НКА · GPS / ГЛОНАСС")
        self.resize(1460, 920)
        self.setMinimumSize(1120, 760)
        self.dataset = None
        self.observer = None
        self.selected = set()
        self.current_samples = {}
        self.node_samples = {}
        self.experiment = None
        self.running = False
        self._generation = 0
        self._worker = None
        self._workers = set()
        self._pending_task = None
        self._closing = False
        self._table_prns = []
        self._shown_records = {}
        self.plots = None
        self._refresh_node_labels_pending = False
        self._build_ui()
        # Колёсико мыши может выдавать десятки valueChanged подряд. Тяжёлая
        # перестройка таблицы выполняется один раз после окончания прокрутки.
        self.table_update_timer = QTimer(self)
        self.table_update_timer.setSingleShot(True)
        self.table_update_timer.setInterval(TABLE_UPDATE_DELAY_MS)
        self.table_update_timer.timeout.connect(self._settings_changed)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(140)
        self.preview_timer.timeout.connect(self._preview)
        self.plot_timer = QTimer(self)
        self.plot_timer.setInterval(250)
        self.plot_timer.timeout.connect(self._refresh_plots)
        self.plot_timer.start()
        self._update_enabled()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 10)

        self.file_group = QGroupBox("1. Навигационные данные")
        file_layout = QHBoxLayout(self.file_group)
        self.source = QComboBox()
        self.source.addItem("")
        self.source.addItems(SOURCES)
        self.source.setMinimumWidth(135)
        self.signal = QComboBox()
        self.signal.addItem("")
        self.signal.addItems(SIGNALS)
        self.source.currentTextChanged.connect(lambda: self._update_enabled())
        self.signal.currentTextChanged.connect(lambda: self._update_enabled())
        self.load_button = QPushButton("Загрузить файл.")
        self.load_button.clicked.connect(self.choose_file)
        self.file_status = QLabel("")
        self.file_status.setWordWrap(True)
        for widget in (QLabel("Источник:"), self.source, QLabel("Сигнал:"), self.signal, self.load_button):
            file_layout.addWidget(widget)
        file_layout.addWidget(self.file_status, 1)
        self.reset_button = QPushButton("Сбросить данные")
        self.reset_button.clicked.connect(self.reset_session)
        file_layout.addWidget(self.reset_button)
        layout.addWidget(self.file_group)

        self.coordinates_group = QGroupBox("2. Координаты наблюдателя")
        coordinates = QHBoxLayout(self.coordinates_group)
        self.datum = QComboBox()
        self.datum.addItems(["WGS84", "PZ90"])
        self.coord_format = QComboBox()
        self.coord_format.addItems(["BLH", "XYZ"])
        self.coord_format.currentTextChanged.connect(self._coordinate_format_changed)
        self.coord_labels = [QLabel("B, °:"), QLabel("L, °:"), QLabel("H, м:")]
        self.coord_values = [spin(-90, 90, 55.75, 7), spin(-180, 180, 37.62, 7), spin(-10000, 1e8, 200, 3)]
        coordinates.addWidget(QLabel("ГЦСК:"))
        coordinates.addWidget(self.datum)
        coordinates.addWidget(QLabel("Формат:"))
        coordinates.addWidget(self.coord_format)
        for label, value in zip(self.coord_labels, self.coord_values):
            coordinates.addWidget(label)
            coordinates.addWidget(value)
        coordinates.addStretch(1)
        self.apply_button = QPushButton("Применить")
        self.apply_button.clicked.connect(self.apply_observer)
        coordinates.addWidget(self.apply_button)
        layout.addWidget(self.coordinates_group)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)
        self.tabs = QTabWidget()
        data_tab = QWidget()
        data_layout = QVBoxLayout(data_tab)
        data_layout.setContentsMargins(8, 8, 8, 8)
        bar = QHBoxLayout()
        self.select_all_button = QPushButton("Выбрать все")
        self.select_all_button.clicked.connect(lambda: self.select_satellites("all"))
        self.select_visible_button = QPushButton("Видимые")
        self.select_visible_button.clicked.connect(lambda: self.select_satellites("visible"))
        self.clear_selection_button = QPushButton("Снять выбор")
        self.clear_selection_button.clicked.connect(lambda: self.select_satellites("none"))
        for button in (self.select_all_button, self.select_visible_button, self.clear_selection_button):
            bar.addWidget(button)
        bar.addStretch()
        data_layout.addLayout(bar)
        self.navigation_table = NavigationTable()
        self.table = self.navigation_table.parameters
        self.angle_table = self.navigation_table.angles
        self.table.cellClicked.connect(self._row_clicked)
        self.table.itemChanged.connect(self._parameter_changed)
        data_layout.addWidget(self.navigation_table, 1)
        self.tabs.addTab(data_tab, "Данные")
        self.plot_page = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_page)
        self.plot_layout.setContentsMargins(2, 2, 2, 2)
        self.tabs.addTab(self.plot_page, "Графики")
        self.tabs.setTabEnabled(1, False)
        splitter.addWidget(self.tabs)

        right = QWidget()
        right.setMinimumWidth(355)
        right.setMaximumWidth(490)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 0, 0, 0)
        self.model_group = QGroupBox("3. Параметры моделирования")
        form = QGridLayout(self.model_group)
        self.node = QComboBox()
        self.node.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.node.setMinimumContentsLength(20)
        self.epsilon = spin(0, 86400, 0, 0, " с")
        self.backward = spin(-10080, 0, -10, 3)
        self.forward = spin(0, 10080, 10, 3)
        self.step = spin(0.001, 604800, 10, 3, " с")
        self.grid_mode = QComboBox()
        self.grid_mode.addItems(["Шаг, с", "Точек N"])
        self.grid_count = QSpinBox()
        self.grid_count.setRange(2, 20000)
        self.grid_count.setValue(121)
        self.grid_count.setKeyboardTracking(False)
        self.grid_count.hide()
        self.speed = spin(0.1, 60, 10, 1)
        self.n4 = QSpinBox()
        self.n4.setRange(1, 100)
        self.n4_label = QLabel("N4 (нет в файле):")
        self.n4.setValue(8)
        form.addWidget(QLabel("Узловой\nмомент:"), 0, 0)
        form.addWidget(self.node, 0, 1, 1, 3)
        for row, col, label, widget in ((1, 0, "Epsilon (±):", self.epsilon), (1, 2, self.n4_label, self.n4),
                                         (2, 0, "Назад, мин:", self.backward), (2, 2, "Вперёд, мин:", self.forward),
                                         (3, 2, "Точек/с:", self.speed)):
            form.addWidget(QLabel(label) if isinstance(label, str) else label, row, col)
            form.addWidget(widget, row, col + 1)
        form.addWidget(self.grid_mode, 3, 0)
        form.addWidget(self.step, 3, 1)
        form.addWidget(self.grid_count, 3, 1)
        self.n4.hide()
        self.n4_label.hide()
        self.point_count = QLabel("")
        self.point_count.setWordWrap(True)
        form.addWidget(self.point_count, 4, 0, 1, 4)
        self.epsilon.valueChanged.connect(self._epsilon_changed)
        for widget in (self.step, self.speed, self.grid_count):
            widget.valueChanged.connect(self._experiment_settings_changed)
        for widget in (self.backward, self.forward):
            widget.valueChanged.connect(self._deferred_settings_changed)
        self.n4.valueChanged.connect(self._node_changed)
        self.grid_mode.currentIndexChanged.connect(self._grid_mode_changed)
        self.node.currentIndexChanged.connect(self._node_changed)
        right_layout.addWidget(self.model_group)

        self.mask_group = QGroupBox("4. Небесная карта · маска угла места")
        mask_layout = QVBoxLayout(self.mask_group)
        mask_row = QHBoxLayout()
        self.lower_mask = spin(0, 90, 10, 1, "°")
        self.upper_mask = spin(0, 90, 90, 1, "°")
        self.lower_mask.valueChanged.connect(lambda: self._mask_changed(True))
        self.upper_mask.valueChanged.connect(lambda: self._mask_changed(False))
        for label, widget in (("Нижняя:", self.lower_mask), ("Верхняя:", self.upper_mask)):
            mask_row.addWidget(QLabel(label))
            mask_row.addWidget(widget)
        mask_layout.addLayout(mask_row)
        self.sky = SkyMap()
        mask_layout.addWidget(self.sky, 1)
        self.visibility_label = QLabel("НКА под горизонтом на карте не показываются")
        self.visibility_label.setWordWrap(True)
        mask_layout.addWidget(self.visibility_label)
        right_layout.addWidget(self.mask_group, 1)

        actions = QGridLayout()
        self.start_button = QPushButton("Начать эксперимент")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_experiment)
        self.stop_button = QPushButton("Остановить")
        self.stop_button.clicked.connect(self.stop_experiment)
        self.export_button = QPushButton("Экспортировать TXT…")
        self.export_button.clicked.connect(self.export_results)
        actions.addWidget(self.start_button, 0, 0)
        actions.addWidget(self.stop_button, 0, 1)
        actions.addWidget(self.export_button, 1, 0, 1, 2)
        right_layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        right_layout.addWidget(self.progress)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        right_scroll.setMinimumWidth(390)
        right_scroll.setMaximumWidth(510)
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        splitter.setSizes([980, 420])
        splitter.setStretchFactor(0, 1)
        self.status = QLabel("Выберите источник и нажмите «Загрузить файл».")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.setStyleSheet("""
            QMainWindow, QWidget { font-family: 'Times New Roman'; font-size: 12pt; color: #233047; }
            QMainWindow { background: #f3f6fa; }
            QGroupBox { background: white; border: 1px solid #d5deeb; border-radius: 7px;
                        margin-top: 10px; padding: 12px 8px 8px 8px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
            QPushButton { padding: 7px 10px; border: 1px solid #b9c8dd; border-radius: 5px; background: #f8fafc; }
            QPushButton:hover { background: #e8f0fc; }
            QPushButton:disabled { color: #96a0af; border-color: #dee4ec; background: #f1f3f6; }
            QPushButton#primary:enabled { color: white; background: #245caa; border-color: #245caa; font-weight: 600; }
            QComboBox, QDoubleSpinBox, QSpinBox { padding: 4px; min-height: 21px; }
            QTabWidget::pane { border: 1px solid #d5deeb; background: white; }
            QTabBar::tab { padding: 9px 25px; }
            QTabBar::tab:selected { background: white; color: #245caa; font-weight: 600; }
            QTableWidget { background: white; gridline-color: #e1e7ef; border: 1px solid #d5deeb; }
            QHeaderView::section { background: #eaf0f8; padding: 5px; border: 1px solid #d5deeb; }
            QProgressBar { border: 1px solid #d5deeb; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background: #84b2eb; }
        """)

    def _coordinate_format_changed(self, mode):
        values = [w.value() for w in self.coord_values]
        try:
            converted = (blh_to_xyz(*values, self.datum.currentText()) if mode == "XYZ"
                         else xyz_to_blh(values, self.datum.currentText()))
        except ValueError:
            converted = (0, 0, 0) if mode == "XYZ" else (55.75, 37.62, 200)
        labels = ("X, м:", "Y, м:", "Z, м:") if mode == "XYZ" else ("B, °:", "L, °:", "H, м:")
        ranges = [(-1e9, 1e9)] * 3 if mode == "XYZ" else [(-90, 90), (-180, 180), (-10000, 1e8)]
        for index, widget in enumerate(self.coord_values):
            widget.setRange(*ranges[index])
            widget.setDecimals(3 if mode == "XYZ" or index == 2 else 7)
            widget.setValue(float(converted[index]))
            self.coord_labels[index].setText(labels[index])

    def choose_file(self):
        if not self.source.currentText() or not self.signal.currentText():
            self.status.setText("Сначала выберите источник и сигнал навигационного файла.")
            return
        if self.source.currentText().startswith("NV08C"):
            QMessageBox.information(self, "NV08C", "Выбор NV08C предусмотрен. Парсер и расчёт пока не реализованы.")
            return
        data_folder = PROJECT_ROOT / "data"
        folders = {
            ("Rinex eph", "L1CA"): "26n",
            ("Rinex eph", "L1OF"): "26g",
            ("Rinex alm", "L1CA"): "agp",
            ("Rinex alm", "L1OF"): "agl",
        }
        folder_name = folders.get((self.source.currentText(), self.signal.currentText()))
        candidate = data_folder / folder_name if folder_name else data_folder
        start_folder = candidate if candidate.is_dir() else data_folder
        filename, _ = QFileDialog.getOpenFileName(self, "Загрузка навигационного файла", str(start_folder),
                                                   file_filter(self.source.currentText(), self.signal.currentText()))
        if filename:
            self.load_file(filename)

    def load_file(self, filename):
        try:
            dataset = load_dataset(filename, self.source.currentText(), self.signal.currentText())
        except (OSError, ValueError, IndexError, NotImplementedError, OverflowError) as exc:
            self.file_status.setText("Ошибка загрузки")
            self._error(str(exc))
            return False
        self.dataset = dataset
        self.selected.clear()
        self.node.blockSignals(True)
        self.node.clear()
        for epoch in dataset.epochs:
            self.node.addItem(dataset.label(epoch, True), epoch)
        self.node.blockSignals(False)
        self._refresh_node_labels()
        is_glo_alm = dataset.source == "Rinex alm" and dataset.signal == "L1OF"
        self.n4.setVisible(is_glo_alm)
        self.n4_label.setVisible(is_glo_alm)
        system = "GPS" if dataset.signal == "L1CA" else "ГЛОНАСС"
        self.file_status.setText(
            f"Данные загружены · {system} · {dataset.path.name} · {len(dataset.satellites)} НКА"
        )
        self.status.setText("Задайте координаты наблюдателя и нажмите «Применить».")
        self._build_table()
        self._settings_changed()
        self._update_enabled()
        return True

    def apply_observer(self):
        if self.dataset is None:
            return
        try:
            self.observer = Observer.from_values([w.value() for w in self.coord_values],
                                                 self.coord_format.currentText(), self.datum.currentText())
        except ValueError as exc:
            self._error(str(exc))
            return
        self.node_samples = {}
        self.status.setText("Координаты применены. Выберите НКА и настройте эксперимент.")
        self._update_enabled()
        self._preview()

    def settings(self):
        return SimulationSettings(float(self.node.currentData()), self.epsilon.value(), self.backward.value(),
                                  self.forward.value(), self.step.value(), self.speed.value(), self.n4.value(),
                                  self.grid_count.value() if self.grid_mode.currentIndex() == 1 else None)

    def _grid_mode_changed(self, index):
        self.step.setVisible(index == 0)
        self.grid_count.setVisible(index == 1)
        self._experiment_settings_changed()

    def _epsilon_changed(self, *_):
        """Отложить обновление подписей и таблицы до окончания прокрутки."""
        self._refresh_node_labels_pending = True
        self._deferred_settings_changed()

    def _node_changed(self, *_):
        """Очистить прежние углы и рассчитать их для нового узлового момента."""
        self.node_samples = {}
        self._settings_changed()

    def _refresh_node_labels(self):
        if not self.dataset:
            return
        epsilon = self.epsilon.value()
        with QSignalBlocker(self.node):
            for index in range(self.node.count()):
                epoch = self.node.itemData(index)
                records = self.dataset.records_at(epoch, epsilon)
                count = len({record.prn for record in records})
                self.node.setItemText(
                    index,
                    f"{self.dataset.label(epoch, True)} · {count} НКА",
                )

    def _update_point_count(self):
        """Показать размер временной сетки без изменения навигационной таблицы."""
        try:
            settings = self.settings()
            offsets = settings.offsets()
            self.point_count.setText(f"{len(offsets)} точек · {offsets[0]:+g} … {offsets[-1]:+g} с")
        except ValueError as exc:
            self.point_count.setText(str(exc))

    def _experiment_settings_changed(self, *_):
        """Изменить сетку/скорость эксперимента, не перечитывая строки таблицы."""
        if not self.dataset or self.running:
            return
        self._invalidate_results()
        self._update_point_count()
        # После сброса прежнего эксперимента убираются только его az/el.
        # Исходные строки и предпросмотр положения НКА остаются прежними.
        self._render_samples()
        self._update_enabled()

    def _deferred_settings_changed(self, *_):
        """Объединить частые изменения колёсиком в одно обновление таблицы."""
        if not self.dataset or self.running:
            return
        self._invalidate_results()
        self._update_point_count()
        self.preview_timer.stop()
        self.table_update_timer.start()
        self._update_enabled()

    def _settings_changed(self, *_):
        if not self.dataset or self.running:
            return
        self.table_update_timer.stop()
        if self._refresh_node_labels_pending:
            self._refresh_node_labels_pending = False
            self._refresh_node_labels()
        self._invalidate_results()
        self._update_point_count()
        self._update_raw_values()
        if self.observer:
            self.current_samples = {}
            self.preview_timer.start()
        self._render_samples()
        self._update_enabled()

    def _build_table(self):
        self._raw_keys = list(dict.fromkeys(key for rows in self.dataset.records.values() for row in rows
                                            for key in row.parameters if key not in {"prn", "svid"}))
        self._raw_start = 3 if self.dataset.calendar else 2
        raw_headers = [NAVIGATION_TABLE_HEADERS.get(key, key) for key in self._raw_keys]
        headers = ["Выбор", "НКА"] + (["Эпоха из файла"] if self.dataset.calendar else []) + raw_headers
        with QSignalBlocker(self.table):
            self.table.clear()
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
        self._update_raw_values()
        self._render_samples()

    def _update_raw_values(self):
        if not self.dataset:
            return

        # Узловой момент имеет секундное разрешение. Epsilon расширяет поиск
        # одинаково назад и вперёд. Все попавшие в диапазон записи остаются
        # отдельными строками, даже если номер НКА у них совпадает.
        node = self.node.currentData()
        records = [] if node is None else self.dataset.records_at(node, self.epsilon.value())
        self._table_prns = [record.prn for record in records]
        self._shown_records = dict(enumerate(records))
        available = {record.prn for record in records if not record.error}
        self.selected.intersection_update(available)

        with QSignalBlocker(self.table), QSignalBlocker(self.angle_table):
            self.table.setRowCount(len(records))
            self.angle_table.setRowCount(len(records))
            for row, record in enumerate(records):
                for col in range(self.table.columnCount()):
                    item = QTableWidgetItem("")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if col < self._raw_start:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, col, item)
                self.table.item(row, 1).setText(f"{record.prn:02d}")
                if self.dataset.calendar:
                    self.table.item(row, 2).setText(self.dataset.label(record.file_epoch, True))
                for col, key in enumerate(self._raw_keys, start=self._raw_start):
                    value = record.parameters.get(key)
                    item = self.table.item(row, col)
                    item.setText("" if value is None else f"{value:.15g}")
                for col in range(2):
                    item = QTableWidgetItem("")
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.angle_table.setItem(row, col, item)

    def _parameter_changed(self, item):
        if not self.dataset or item.column() < self._raw_start:
            return
        record = self._shown_records.get(item.row())
        if record is None:
            return
        key = self._raw_keys[item.column() - self._raw_start]
        if self.running:
            with QSignalBlocker(self.table):
                item.setText(f"{record.parameters[key]:.15g}")
            return
        try:
            updated = edit_parameter(self.dataset, record, key, item.text())
        except (ValueError, OverflowError) as exc:
            with QSignalBlocker(self.table):
                item.setText(f"{record.parameters[key]:.15g}")
            self._error(str(exc))
            return
        self.preview_timer.stop()
        self._generation += 1  # игнорировать уже отправленные кадры прежнего предпросмотра
        self._pending_task = None
        if self._worker:
            self._worker.cancel()
        self.dataset = updated
        self.node_samples = {}
        if key in TIME_FIELDS:
            node = self.node.currentData()
            with QSignalBlocker(self.node):
                self.node.clear()
                for epoch in self.dataset.epochs:
                    self.node.addItem(self.dataset.label(epoch, True), epoch)
                nearest = min(range(self.node.count()), key=lambda i: abs(self.node.itemData(i) - node))
                self.node.setCurrentIndex(nearest)
            self._refresh_node_labels()
        self.selected.intersection_update(self.dataset.available_satellites)
        self._settings_changed()
        self._render_samples()
        self._update_enabled()
        self.status.setText(f"НКА {record.prn:02d}: изменён {key}. Параметры применены к текущему сеансу.")

    def _render_samples(self):
        lower, upper = self.lower_mask.value(), self.upper_mask.value()
        visible_prns = set()
        with QSignalBlocker(self.table):
            for row, prn in enumerate(self._table_prns):
                sample = self.current_samples.get(prn)
                node_sample = self.node_samples.get(prn)
                selected = prn in self.selected
                # Во время моделирования углы меняются только у выбранных НКА.
                # Для остальных строк сохраняются az/el в узловой момент.
                angle_sample = sample if self.experiment is not None and selected else node_sample
                visible = sample is not None and lower <= sample.el <= upper
                if visible:
                    visible_prns.add(prn)
                record = self._shown_records.get(row)
                unavailable = record is None or bool(record.error)
                color = QColor("#e0e3e8" if unavailable else "#c9efd8" if selected else "#ffffff" if visible or sample is None else "#e0e3e8")
                self.table.item(row, 0).setText("—" if unavailable else "✓" if selected else "")
                for col in range(self.table.columnCount()):
                    self.table.item(row, col).setBackground(QBrush(color))
                # До запуска показаны углы в узловом моменте. Во время и после
                # моделирования — углы текущей/последней рассчитанной точки.
                values = (angle_sample.az, angle_sample.el) if angle_sample else (None, None)
                for col, value in enumerate(values):
                    item = self.angle_table.item(row, col)
                    item.setText("" if value is None else f"{value:.3f}")
                    item.setBackground(QBrush(color))
        self.sky.update_view(self.current_samples, self.selected, lower, upper)
        unique_prns = len(set(self._table_prns))
        self.visibility_label.setText(
            f"В маске: {len(visible_prns)} / {unique_prns} НКА · "
            f"строк: {len(self._table_prns)} · выбрано: {len(self.selected)}\n"
            "НКА под горизонтом на карте не показываются"
        )

    def _mask_changed(self, lower_changed):
        if self.lower_mask.value() > self.upper_mask.value():
            target = self.upper_mask if lower_changed else self.lower_mask
            target.blockSignals(True)
            target.setValue(self.lower_mask.value() if lower_changed else self.upper_mask.value())
            target.blockSignals(False)
        # Только отрисовка, без фонового расчёта или таймера моделирования.
        self._render_samples()

    def _row_clicked(self, row, _column):
        if self.running or row >= len(self._table_prns) or _column > 1:
            return
        prn = self._table_prns[row]
        record = self._shown_records[row]
        if record.error:
            self.status.setText(f"НКА {prn}: " + record.error)
            return
        if prn in self.selected:
            self.selected.remove(prn)
        else:
            self.selected.add(prn)
        self._selection_changed()

    def select_satellites(self, mode):
        if not self.dataset or self.running:
            return
        if mode == "all":
            self.selected = {record.prn for record in self._shown_records.values() if not record.error}
        elif mode == "visible":
            displayed = set(self._table_prns)
            self.selected = {prn for prn, sample in self.current_samples.items() if prn in displayed
                             if self.lower_mask.value() <= sample.el <= self.upper_mask.value()}
        else:
            self.selected.clear()
        self._selection_changed()

    def _selection_changed(self):
        self._invalidate_results()
        self._render_samples()
        self._update_enabled()

    def _invalidate_results(self):
        if self.experiment is not None:
            self.experiment = None
            self.tabs.setCurrentIndex(0)
            self.tabs.setTabEnabled(1, False)
            if self.plots:
                self.plots.experiment = None
            self.progress.setValue(0)
        self.export_button.setEnabled(False)

    def _preview(self):
        if not self.dataset or not self.observer or self.running or self._closing:
            return
        self._queue_task(self.settings(), None)

    def _queue_task(self, settings, offsets, satellites=None):
        self._generation += 1
        self._pending_task = (
            self._generation,
            self.dataset,
            self.observer,
            settings,
            offsets,
            None if satellites is None else tuple(satellites),
        )
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        else:
            self._dispatch_task()

    def _dispatch_task(self):
        if not self._pending_task or self._closing:
            return
        generation, dataset, observer, settings, offsets, satellites = self._pending_task
        self._pending_task = None
        worker = CalculationWorker(
            generation,
            dataset,
            observer,
            settings,
            offsets=offsets,
            satellites=satellites,
            parent=self,
        )
        self._worker = worker
        self._workers.add(worker)
        worker.frame.connect(self._on_frame)
        worker.failed.connect(self._on_failure)
        worker.completed.connect(self._on_completed)
        worker.finished.connect(lambda w=worker: self._worker_finished(w))
        worker.start()

    def _worker_finished(self, worker):
        self._workers.discard(worker)
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()
        if self._closing:
            if not self._workers:
                self.close()
        elif self._pending_task and self._worker is None:
            self._dispatch_task()

    def _on_frame(self, generation, samples, index, total):
        if generation != self._generation or self._closing:
            return
        displayed = {record.prn for record in self._shown_records.values() if not record.error}
        self.current_samples = {prn: sample for prn, sample in samples.items() if prn in displayed}
        if not self.running:
            self.node_samples = dict(self.current_samples)
        if self.running and self.experiment:
            for prn in self.experiment.selected:
                self.experiment.samples[prn].append(samples[prn])
            self.progress.setValue(round(100 * (index + 1) / total))
            dt = next(iter(samples.values())).dt
            self.status.setText(f"Эксперимент: точка {index + 1} / {total} · dt = {dt:+g} с · {len(self.selected)} НКА")
        self._render_samples()

    def _on_failure(self, generation, message):
        if generation != self._generation:
            return
        self.status.setText("Ошибка расчёта: " + message)
        self.running = False
        self._update_enabled()
        self._error(message)

    def _on_completed(self, generation, success):
        if generation != self._generation:
            return
        if self.running and self.experiment:
            self.experiment.complete = success
            self.running = False
            self.status.setText("Эксперимент завершён. Результаты готовы к экспорту." if success else "Эксперимент остановлен.")
            self._refresh_plots()
        self._update_enabled()

    def start_experiment(self):
        if not self.dataset or not self.observer or self.running:
            return
        # Если пользователь сразу нажал запуск после прокрутки, применяем
        # последнее значение Epsilon/диапазона до формирования эксперимента.
        if self.table_update_timer.isActive():
            self._settings_changed()
        if not self.selected:
            return
        try:
            settings = self.settings()
            offsets = settings.offsets()
            if len(offsets) * len(self.selected) > 300000:
                raise ValueError("Больше 300 000 строк результата. Увеличьте шаг или сократите число НКА.")
        except ValueError as exc:
            self._error(str(exc))
            return
        self.preview_timer.stop()
        self.experiment = Experiment(self.dataset, self.observer, settings, tuple(sorted(self.selected)))
        self.running = True
        self.progress.setValue(0)
        if self.plots is None:
            self.plots = TrajectoryPlots()
            self.plot_layout.addWidget(self.plots)
        self.plots.reset(self.experiment)
        self.tabs.setTabEnabled(1, True)
        self.status.setText("Выполняется расчёт первой точки…")
        self._update_enabled()
        self._queue_task(settings, offsets, self.experiment.selected)

    def stop_experiment(self):
        if not self.running:
            return
        self._generation += 1
        self._pending_task = None
        if self._worker:
            self._worker.cancel()
        self.running = False
        self.status.setText("Эксперимент остановлен. Можно экспортировать уже рассчитанные точки.")
        self._refresh_plots()
        self._update_enabled()

    def _refresh_plots(self):
        if self.plots and self.experiment and self.tabs.currentIndex() == 1:
            self.plots.update_data()

    def export_results(self):
        if not self.experiment or self.running:
            return
        destination = QFileDialog.getExistingDirectory(self, "Папка для результатов TXT", str(PROJECT_ROOT / "export"))
        if not destination:
            return
        try:
            folder = export_experiment(self.experiment, destination)
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return
        self.status.setText(f"Экспортировано {len(self.experiment.selected)} файлов: {folder}")
        QMessageBox.information(self, "Экспорт завершён", f"Сохранены TXT для {len(self.experiment.selected)} НКА:\n{folder}")

    def _update_enabled(self):
        loaded = self.dataset is not None
        ready = loaded and self.observer is not None
        self.source.setEnabled(not loaded)
        self.signal.setEnabled(not loaded)
        format_selected = bool(self.source.currentText() and self.signal.currentText())
        self.load_button.setEnabled(not loaded and format_selected)
        self.coordinates_group.setEnabled(loaded and not ready)
        self.model_group.setEnabled(ready and not self.running)
        self.mask_group.setEnabled(ready)
        self.start_button.setEnabled(ready and bool(self.selected) and not self.running)
        self.stop_button.setEnabled(self.running)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers if self.running else
                                   QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        for button in (self.select_all_button, self.clear_selection_button):
            button.setEnabled(loaded and not self.running)
        self.select_visible_button.setEnabled(ready and bool(self.current_samples) and not self.running)
        has_data = self.experiment is not None and all(self.experiment.samples.values())
        self.export_button.setEnabled(bool(has_data) and not self.running)

    def reset_session(self):
        self.table_update_timer.stop()
        self._refresh_node_labels_pending = False
        self.preview_timer.stop()
        self._generation += 1
        self._pending_task = None
        if self._worker:
            self._worker.cancel()
        self.running = False
        self.dataset = None
        self.observer = None
        with QSignalBlocker(self.source), QSignalBlocker(self.signal):
            self.source.setCurrentIndex(0)
            self.signal.setCurrentIndex(0)
        with QSignalBlocker(self.lower_mask), QSignalBlocker(self.upper_mask):
            self.lower_mask.setValue(10)
            self.upper_mask.setValue(90)
        self.selected.clear()
        self.current_samples = {}
        self.node_samples = {}
        self._invalidate_results()
        self._table_prns = []
        self._shown_records = {}
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.angle_table.setRowCount(0)
        self.node.clear()
        self.file_status.clear()
        self.point_count.clear()
        self.progress.setValue(0)
        self.status.setText("Выберите источник и нажмите «Загрузить файл».")
        self._render_samples()
        self._update_enabled()

    def _error(self, text):
        QMessageBox.warning(self, "Проверьте данные", text)

    def eventFilter(self, watched, event):
        """Не показывать всплывающие подсказки ни для одного элемента интерфейса."""
        if event.type() == QEvent.Type.ToolTip:
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        active = [worker for worker in self._workers if worker.isRunning()]
        if active:
            self._closing = True
            self._generation += 1
            self._pending_task = None
            self.table_update_timer.stop()
            self.preview_timer.stop()
            self.plot_timer.stop()
            for worker in active:
                worker.cancel()
            self.centralWidget().setEnabled(False)
            self.status.setText("Завершение текущего расчёта…")
            event.ignore()
        else:
            QApplication.instance().removeEventFilter(self)
            event.accept()
