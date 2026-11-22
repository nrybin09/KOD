"""Окна подключения и получения альманахов/эфемерид от NV08C."""

from nka_app.common import (
    Event, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QThread,
    QVBoxLayout, Qt, Signal, monotonic, serial, serial_list_ports,
)

from nka_app.nv08c_protocol import (
    BINRStreamParser, GLONASS_SYSTEM, GPS_SYSTEM, decode_navigation_frame,
    request_almanac, request_ephemeris, write_nv08c_file,
)


class NV08CSettingsDialog(QDialog):
    """Минимальные настройки, которые пользователь просил оставить в интерфейсе."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подключение NV08C")
        self.setModal(True)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.port = QComboBox()
        self.port.setEditable(True)
        if serial_list_ports is not None:
            names = sorted(info.device for info in serial_list_ports.comports())
            self.port.addItems(names)
        self.speed = QComboBox()
        self.speed.setEditable(True)
        self.speed.addItems(["9600", "19200", "38400", "57600", "115200", "230400"])
        self.speed.setCurrentText("115200")
        form.addRow("Порт:", self.port)
        form.addRow("Скорость:", self.speed)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Принять")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(330)

    @property
    def port_name(self):
        return self.port.currentText().strip()

    @property
    def baud_rate(self):
        return int(self.speed.currentText().strip())

    def accept(self):
        if serial is None:
            QMessageBox.warning(self, "NV08C", "Не установлена библиотека pyserial.")
            return
        if not self.port_name:
            QMessageBox.warning(self, "NV08C", "Выберите или введите COM-порт.")
            return
        try:
            speed = self.baud_rate
        except ValueError:
            QMessageBox.warning(self, "NV08C", "Скорость должна быть целым числом.")
            return
        if speed <= 0:
            QMessageBox.warning(self, "NV08C", "Скорость должна быть больше нуля.")
            return
        super().accept()


class NV08CWorker(QThread):
    """Последовательный обмен выполняется вне потока интерфейса."""

    record_received = Signal(object)
    progress_changed = Signal(int, int)
    failed = Signal(str)

    def __init__(self, port_name, baud_rate, kind, system, parent=None):
        super().__init__(parent)
        self.port_name = port_name
        self.baud_rate = baud_rate
        self.kind = kind
        self.system = system
        self._cancel = Event()

    def cancel(self):
        self._cancel.set()

    def _matching_frame(self, frame, message_id, prn=None):
        if frame.message_id != message_id or len(frame.payload) < 2:
            return False
        if frame.payload[0] != self.system:
            return False
        return prn is None or frame.payload[1] == prn

    def _request_almanacs(self, port, parser):
        count = 32 if self.system == GPS_SYSTEM else 24
        for prn in range(1, count + 1):
            if self._cancel.is_set():
                break
            port.write(request_almanac(self.system, prn))
            port.flush()
            deadline = monotonic() + 0.8
            answered = False
            while not self._cancel.is_set() and monotonic() < deadline and not answered:
                chunk = port.read(max(1, port.in_waiting))
                for frame in parser.feed(chunk):
                    if not self._matching_frame(frame, 0x40, prn):
                        continue
                    answered = True
                    try:
                        record = decode_navigation_frame(frame)
                    except ValueError:
                        record = None
                    if record is not None:
                        self.record_received.emit(record)
            self.progress_changed.emit(prn, count)

    def _request_ephemerides(self, port, parser):
        count = 32 if self.system == GPS_SYSTEM else 24
        # Запрашиваем только выбранную систему. Следующий запрос отправляется
        # после ответа или тайм-аута предыдущего, чтобы не переполнять буфер
        # приёмника серией из 24/32 команд.
        for prn in range(1, count + 1):
            if self._cancel.is_set():
                break
            port.write(request_ephemeris(self.system, prn))
            port.flush()
            deadline = monotonic() + 0.8
            answered = False
            while not self._cancel.is_set() and monotonic() < deadline and not answered:
                chunk = port.read(max(1, port.in_waiting))
                for frame in parser.feed(chunk):
                    if not self._matching_frame(frame, 0x49, prn):
                        continue
                    answered = True
                    try:
                        record = decode_navigation_frame(frame)
                    except ValueError:
                        record = None
                    if record is not None:
                        self.record_received.emit(record)
            self.progress_changed.emit(prn, count)

    def run(self):
        if serial is None:
            self.failed.emit("Не установлена библиотека pyserial.")
            return
        try:
            with serial.Serial(
                port=self.port_name,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_ODD,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.15,
                write_timeout=1.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            ) as port:
                port.reset_input_buffer()
                parser = BINRStreamParser()
                if self.kind == "alm":
                    self._request_almanacs(port, parser)
                else:
                    self._request_ephemerides(port, parser)
        except (OSError, ValueError, serial.SerialException) as exc:
            self.failed.emit(f"Не удалось выполнить обмен с NV08C: {exc}")


class NV08CReceiverDialog(QDialog):
    """Индикация только выбранной системы и выбранного типа данных."""

    records_changed = Signal(object)

    def __init__(self, port_name, baud_rate, source, signal, parent=None):
        super().__init__(parent)
        self.port_name = port_name
        self.baud_rate = baud_rate
        self.kind = "eph" if source.endswith("eph") else "alm"
        self.signal = signal
        self.system = GPS_SYSTEM if signal == "L1CA" else GLONASS_SYSTEM
        self.count = 32 if self.system == GPS_SYSTEM else 24
        self.records = {}
        self.worker = None
        system_name = "GPS" if self.system == GPS_SYSTEM else "ГЛОНАСС"
        kind_name = "эфемериды" if self.kind == "eph" else "альманах"
        self.setWindowTitle(f"NV08C — {kind_name}, {system_name}")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Порт: {port_name} · {baud_rate} бод"))
        group = QGroupBox(system_name)
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(5)
        self.indicators = {}
        for index, prn in enumerate(range(1, self.count + 1)):
            number = QLabel(str(prn))
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            circle = QLabel("")
            circle.setFixedSize(20, 20)
            self._set_received(circle, False)
            grid.addWidget(number, 0, index)
            grid.addWidget(circle, 1, index)
            self.indicators[prn] = circle
        layout.addWidget(group)
        self.status = QLabel("Нажмите «Запросить данные».")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.request_button = QPushButton("Запросить данные")
        self.request_button.clicked.connect(self.request_data)
        self.save_button = QPushButton("Записать в файл")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_file)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.request_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.setMinimumWidth(max(780, self.count * 32 + 45))

    @staticmethod
    def _set_received(label, received):
        color = "#239b56" if received else "#9aa4b2"
        border = "#16743e" if received else "#667384"
        label.setStyleSheet(
            f"background-color: {color}; border: 2px solid {border}; border-radius: 10px;"
        )

    def request_data(self):
        if self.worker and self.worker.isRunning():
            return
        self.records.clear()
        for indicator in self.indicators.values():
            self._set_received(indicator, False)
        self.save_button.setEnabled(False)
        self.request_button.setEnabled(False)
        self.status.setText("Получение данных… 0")
        self.worker = NV08CWorker(
            self.port_name, self.baud_rate, self.kind, self.system, self
        )
        self.worker.record_received.connect(self._record_received)
        self.worker.progress_changed.connect(self._progress_changed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _record_received(self, record):
        self.records[record.prn] = record
        indicator = self.indicators.get(record.prn)
        if indicator is not None:
            self._set_received(indicator, True)
        self.save_button.setEnabled(True)
        self.records_changed.emit(tuple(self.records[key] for key in sorted(self.records)))

    def _progress_changed(self, current, total):
        self.status.setText(f"Получено: {len(self.records)} НКА · обработано {current} из {total}")

    def _failed(self, message):
        self.status.setText(message)

    def _finished(self):
        self.request_button.setEnabled(True)
        if self.records:
            self.status.setText(f"Получение завершено · {len(self.records)} НКА")
        elif not self.status.text().startswith("Не удалось"):
            self.status.setText("Получение завершено · данных нет")
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()

    def save_file(self):
        try:
            path = write_nv08c_file(self.records.values(), self.kind, self.signal)
        except (OSError, ValueError, OverflowError) as exc:
            QMessageBox.warning(self, "NV08C", str(exc))
            return
        self.status.setText(f"Файл сохранён: {path}")
        QMessageBox.information(self, "NV08C", f"Данные сохранены:\n{path}")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            if not self.worker.wait(2000):
                self.status.setText("Завершение обмена с приёмником…")
                event.ignore()
                return
        event.accept()
