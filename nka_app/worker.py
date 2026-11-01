"""Фоновый расчёт. Рабочий поток не обращается к виджетам."""

from nka_app.common import Event, QThread, Signal, monotonic

from nka_app.navigation import calculate_sample


class CalculationWorker(QThread):
    frame = Signal(int, object, int, int)
    failed = Signal(int, str)
    completed = Signal(int, bool)

    def __init__(self, generation, dataset, observer, settings, offsets=None,
                 satellites=None, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.dataset = dataset
        self.observer = observer
        self.settings = settings
        self.preview = offsets is None
        self.offsets = [0.0] if self.preview else offsets
        # До запуска эксперимента нужен предпросмотр всех НКА. Во время
        # эксперимента главное окно передаёт сюда только выбранные номера.
        self.satellites = tuple(dataset.available_satellites if satellites is None else satellites)
        self.cancelled = Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        success = False
        try:
            for index, dt in enumerate(self.offsets):
                tick = monotonic()
                frame = {}
                for prn in self.satellites:
                    if self.cancelled.is_set():
                        return
                    frame[prn] = calculate_sample(self.dataset, self.observer, prn,
                                                  self.settings.center + dt, dt, self.settings.n4)
                if self.cancelled.is_set():
                    return
                self.frame.emit(self.generation, frame, index, len(self.offsets))
                if not self.preview and index + 1 < len(self.offsets):
                    delay = max(0, 1 / self.settings.speed - (monotonic() - tick))
                    if self.cancelled.wait(delay):
                        return
            success = True
        except Exception as exc:
            self.failed.emit(self.generation, f"{type(exc).__name__}: {exc}")
        finally:
            self.completed.emit(self.generation, success)
