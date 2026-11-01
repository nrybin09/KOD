from nka_app.common import Path, dataclass, datetime, field, math, np, timedelta, timezone

from nka_app.coordinates import Observer


@dataclass(frozen=True)
class NavRecord:
    prn: int
    epoch: float
    data: object
    parameters: dict
    error: str = ""
    file_epoch: float | None = None


@dataclass
class Dataset:
    path: Path
    source: str
    signal: str
    records: dict[int, list[NavRecord]]
    time_system: str
    calendar: bool = False
    notes: list[str] = field(default_factory=list)
    edits: list[dict] = field(default_factory=list)

    @property
    def datum(self):
        return "WGS84" if self.signal == "L1CA" else "PZ90"

    @property
    def satellites(self):
        return sorted(self.records)

    @property
    def available_satellites(self):
        return [prn for prn in self.satellites if any(not r.error for r in self.records[prn])]

    @property
    def epochs(self):
        # Узловой момент и фильтрация таблицы имеют секундное разрешение.
        rows = [r for group in self.records.values() for r in group]
        valid = [r for r in rows if not r.error]
        return sorted({math.floor(r.epoch) for r in valid or rows})

    def records_at(self, epoch, epsilon=0):
        """Все записи НКА в диапазоне ``epoch ± epsilon``."""
        second = math.floor(float(epoch))
        tolerance = abs(float(epsilon))
        rows = (
            record
            for group in self.records.values()
            for record in group
            if abs(math.floor(record.epoch) - second) <= tolerance
        )
        # Одинаковые НКА не объединяются: записи разных эпох идут отдельно.
        return sorted(rows, key=lambda record: (record.prn, record.epoch))

    def nearest(self, prn, epoch):
        valid = [r for r in self.records[prn] if not r.error]
        return min(valid or self.records[prn], key=lambda r: (abs(r.epoch - epoch), r.epoch))

    def label(self, epoch, seconds=False):
        fmt = "%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M"
        if self.calendar:
            system = "ГЛОНАСС" if self.signal == "L1OF" else self.time_system
            return datetime.fromtimestamp(epoch, timezone.utc).strftime(fmt) + " " + system
        if self.signal == "L1CA":
            week, tow = divmod(epoch, 604800)
            day, sod = divmod(tow, 86400)
            prefix = f"GPS W{int(week)}, день {int(day)}"
        else:
            day, sod = divmod(epoch, 86400)
            prefix = f"ГЛОНАСС, день {int(day) + 1}"
        clock = (datetime(2000, 1, 1) + timedelta(seconds=sod)).strftime("%H:%M:%S" if seconds else "%H:%M")
        return f"{prefix} {clock}"


@dataclass(frozen=True)
class SimulationSettings:
    node: float
    epsilon: float = 0
    backward_minutes: float = -10
    forward_minutes: float = 10
    step_seconds: float = 10
    speed: float = 10
    n4: int = 1
    sample_count: int | None = None

    @property
    def center(self):
        # Epsilon задаёт симметричный допуск выбора записей, а не сдвиг времени.
        return self.node

    def offsets(self):
        vals = [self.node, self.epsilon, self.backward_minutes, self.forward_minutes, self.step_seconds, self.speed]
        if not all(math.isfinite(v) for v in vals):
            raise ValueError("Параметры моделирования должны быть конечными числами.")
        if self.epsilon < 0:
            raise ValueError("Epsilon должен быть неотрицательным допуском ± времени.")
        if self.backward_minutes > 0 or self.forward_minutes < 0:
            raise ValueError("Интервал назад должен быть ≤ 0, вперёд — ≥ 0.")
        if self.step_seconds <= 0 or self.speed <= 0:
            raise ValueError("Шаг и скорость моделирования должны быть больше нуля.")
        if not 1 <= self.n4 <= 100:
            raise ValueError("N4 должен быть от 1 до 100.")
        start, end = 60 * self.backward_minutes, 60 * self.forward_minutes
        if self.sample_count is not None:
            if not isinstance(self.sample_count, int) or not 2 <= self.sample_count <= 20000:
                raise ValueError("Количество точек N должно быть целым числом от 2 до 20 000.")
            return np.linspace(start, end, self.sample_count) if end > start else np.array([0.0])
        count = int(math.floor((end - start) / self.step_seconds + 1e-10)) + 1
        if count > 20000:
            raise ValueError("Слишком много точек (максимум 20 000). Увеличьте шаг.")
        values = start + np.arange(count) * self.step_seconds
        # Сохраняем обе границы; последний шаг может быть короче заданного.
        if end - values[-1] > 1e-8:
            values = np.append(values, end)
        if len(values) > 20000:
            raise ValueError("С учётом конечной границы получилось больше 20 000 точек. Увеличьте шаг.")
        return values


@dataclass(frozen=True)
class Sample:
    dt: float
    az: float
    el: float
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    r: float

    def values(self):
        return (self.dt, self.az, self.el, self.x, self.y, self.z, self.vx, self.vy, self.vz, self.r)


@dataclass
class Experiment:
    dataset: Dataset
    observer: Observer
    settings: SimulationSettings
    selected: tuple[int, ...]
    samples: dict[int, list[Sample]] = field(default_factory=dict)
    complete: bool = False

    def __post_init__(self):
        self.samples = {prn: [] for prn in self.selected}
