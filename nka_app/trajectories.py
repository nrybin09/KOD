"""Три вкладки графиков эксперимента с локальной картой Земли."""

from nka_app.common import (
    MAP_PATH, Figure, FigureCanvasQTAgg, Line3DCollection, NavigationToolbar2QT,
    QCheckBox, QHBoxLayout, QLabel, QSignalBlocker, QTabWidget, QVBoxLayout,
    QWidget, colormaps, json, np,
)

from nka_app.coordinates import transform_xyz, xyz_to_blh

def map_rings():
    data = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    for feature in data["features"]:
        geometry = feature["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for polygon in polygons:
            yield np.asarray(polygon[0], dtype=float), feature["properties"].get("ADMIN") == "Russia"


def break_jumps(x, y, threshold=180):
    """Не соединять концы траектории через разрыв долготы/азимута."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    splits = np.flatnonzero(np.abs(np.diff(y)) > threshold) + 1
    return np.insert(x, splits, np.nan), np.insert(y, splits, np.nan)


class TrajectoryPlots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Каждая группа графиков получает отдельную внутреннюю вкладку,
        # Matplotlib-холст и собственную панель управления масштабом.
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        map_page = QWidget()
        map_layout = QVBoxLayout(map_page)
        map_layout.setContentsMargins(4, 4, 4, 4)
        controls = QHBoxLayout()
        self.world = QCheckBox("Весь мир")
        controls.addWidget(self.world)
        controls.addWidget(QLabel("Красная звезда — введённое положение наблюдателя"))
        controls.addStretch()
        map_layout.addLayout(controls)
        self.map_figure = Figure(figsize=(9, 6), layout="constrained", facecolor="white")
        self.map_canvas = FigureCanvasQTAgg(self.map_figure)
        map_layout.addWidget(self.map_canvas, 1)
        map_layout.addWidget(NavigationToolbar2QT(self.map_canvas, map_page))
        self.tabs.addTab(map_page, "1. Карта Земли")

        globe_page = QWidget()
        globe_layout = QVBoxLayout(globe_page)
        globe_layout.setContentsMargins(4, 4, 4, 4)
        globe_layout.addWidget(QLabel("Вращение — мышью • координаты и орбиты в км"))
        self.globe_figure = Figure(figsize=(8, 6), layout="constrained", facecolor="white")
        self.globe_canvas = FigureCanvasQTAgg(self.globe_figure)
        globe_layout.addWidget(self.globe_canvas, 1)
        globe_layout.addWidget(NavigationToolbar2QT(self.globe_canvas, globe_page))
        self.tabs.addTab(globe_page, "2. 3D-анимация")

        angles_page = QWidget()
        angles_layout = QVBoxLayout(angles_page)
        angles_layout.setContentsMargins(4, 4, 4, 4)
        self.angles_figure = Figure(figsize=(9, 6), layout="constrained", facecolor="white")
        self.angles_canvas = FigureCanvasQTAgg(self.angles_figure)
        angles_layout.addWidget(self.angles_canvas, 1)
        angles_layout.addWidget(NavigationToolbar2QT(self.angles_canvas, angles_page))
        self.tabs.addTab(angles_page, "3. Временные az/el")

        # Совместимость со вспомогательным созданием снимков старого интерфейса.
        self.figure = self.map_figure
        self.canvas = self.map_canvas
        self.experiment = None
        self._lines = {}
        self._cached_count = -1
        self._plot_cache = {}
        self.world.toggled.connect(self._rebuild)

    def reset(self, experiment=None):
        self.experiment = experiment
        self._plot_cache = {}
        if experiment and not self.world.isChecked():
            observer = experiment.observer.in_datum("WGS84")
            lat, lon, _ = xyz_to_blh(observer)
            regional_lon = lon + 360 if lon < 0 else lon
            # Региональный вид охватывает Россию. Для любой другой введённой
            # точки автоматически показываем весь мир, чтобы звезда не исчезла
            # за границами осей.
            if not (35 <= lat <= 83 and 18 <= regional_lon <= 195):
                with QSignalBlocker(self.world):
                    self.world.setChecked(True)
        self._rebuild()

    def _rebuild(self):
        self.map_figure.clear()
        self.globe_figure.clear()
        self.angles_figure.clear()
        self._lines = {}
        self._cached_count = -1
        self.map_ax = self.map_figure.add_subplot(111)
        self.globe_ax = self.globe_figure.add_subplot(111, projection="3d")
        angle_grid = self.angles_figure.add_gridspec(2, 1)
        self.az_ax = self.angles_figure.add_subplot(angle_grid[0, 0])
        self.el_ax = self.angles_figure.add_subplot(angle_grid[1, 0], sharex=self.az_ax)
        self.map_ax.set_title("Проекции траекторий · мир" if self.world.isChecked() else "Проекции траекторий · Россия", fontsize=10)
        self.map_ax.set_facecolor("#eaf3fa")
        self.map_ax.set_xlim((-180, 180) if self.world.isChecked() else (18, 195))
        self.map_ax.set_ylim((-80, 85) if self.world.isChecked() else (35, 83))
        self.map_ax.set_xlabel("Долгота, °", fontsize=8)
        self.map_ax.set_ylabel("Широта, °", fontsize=8)
        self.map_ax.grid(alpha=0.25)
        globe_lines = []
        try:
            for ring, russia in map_rings():
                lon, lat = ring.T
                unwrapped = np.degrees(np.unwrap(np.radians(lon)))
                for shift in (-360, 0, 360):
                    self.map_ax.fill(unwrapped + shift, lat, facecolor="#c8dec6" if russia else "#eef0e6",
                                     edgecolor="#94a390", linewidth=0.4, zorder=1)
                lon, lat = np.radians(lon), np.radians(lat)
                globe_lines.append(6380 * np.column_stack((np.cos(lat) * np.cos(lon),
                                                           np.cos(lat) * np.sin(lon), np.sin(lat))))
        except (OSError, ValueError, KeyError) as exc:
            self.map_ax.text(0.5, 0.5, f"Не найдена подложка\nmaps/world.geojson\n{type(exc).__name__}",
                             transform=self.map_ax.transAxes, ha="center", fontsize=8)
        u, v = np.meshgrid(np.linspace(0, 2 * np.pi, 40), np.linspace(0, np.pi, 24))
        self.globe_ax.plot_surface(6378 * np.cos(u) * np.sin(v), 6378 * np.sin(u) * np.sin(v),
                                   6378 * np.cos(v), color="#9bc3df", alpha=0.65, linewidth=0)
        self.globe_ax.add_collection3d(Line3DCollection(globe_lines, colors="#55775c", linewidths=0.4))
        self.globe_ax.set_title("Земля и траектории НКА · ECEF", fontsize=10)
        self.globe_ax.set(xlabel="X, км", ylabel="Y, км", zlabel="Z, км", xlim=(-29000, 29000),
                          ylim=(-29000, 29000), zlim=(-29000, 29000))
        self.globe_ax.set_box_aspect((1, 1, 1))
        self.globe_ax.view_init(elev=25, azim=35)
        for ax, title, limits in ((self.az_ax, "Азимут az, °", (0, 360)), (self.el_ax, "Угол места el, °", (-90, 90))):
            ax.set_ylabel(title, fontsize=9)
            ax.set_ylim(*limits)
            ax.set_xlabel("dt от узлового момента, с", fontsize=9)
            ax.grid(alpha=0.25)
        if self.experiment:
            for prn in self.experiment.selected:
                color = colormaps["tab20"]((prn - 1) % 20)
                self._lines[prn] = (
                    self.map_ax.plot([], [], color=color, linewidth=1.5, label=f"{prn:02d}", zorder=3)[0],
                    self.globe_ax.plot([], [], [], color=color, linewidth=1.4, marker="o", markersize=3, markevery=[-1])[0],
                    self.az_ax.plot([], [], color=color, linewidth=1.2, label=f"{prn:02d}")[0],
                    self.el_ax.plot([], [], color=color, linewidth=1.2)[0],
                    self.map_ax.plot([], [], "o", color=color, markersize=4, zorder=4)[0],
                )
            observer = self.experiment.observer.in_datum("WGS84")
            lat, lon, _ = xyz_to_blh(observer)
            if not self.world.isChecked() and lon < 0:
                lon += 360
            self.map_ax.plot(lon, lat, "*", color="#d83238", markersize=10, zorder=5)
            self.globe_ax.scatter(*(observer / 1000), color="#d83238", marker="*", s=35)
            self.az_ax.legend(loc="upper right", ncol=min(10, len(self._lines)), fontsize=7)
        for ax in (self.map_ax, self.globe_ax, self.az_ax, self.el_ax):
            ax.tick_params(labelsize=7)
        self.update_data(force=True)

    def update_data(self, force=False):
        if not self.experiment:
            self._draw_all()
            return
        count = sum(len(rows) for rows in self.experiment.samples.values())
        if count == self._cached_count and not force:
            return
        self._cached_count = count
        for prn, rows in self.experiment.samples.items():
            if not rows:
                continue
            cache = self._plot_cache.setdefault(prn, [])
            for sample in rows[len(cache):]:
                xyz = transform_xyz((sample.x, sample.y, sample.z), self.experiment.dataset.datum, "WGS84")
                lat, lon, _ = xyz_to_blh(xyz)
                cache.append((lat, lon, *xyz / 1000))
            positions = np.asarray(cache)
            values = np.array([s.values() for s in rows])
            lat, lon = positions[:, 0], positions[:, 1].copy()
            if not self.world.isChecked():
                lon[lon < 0] += 360
            split_lat, split_lon = break_jumps(lat, lon)
            map_line, globe_line, az_line, el_line, marker = self._lines[prn]
            map_line.set_data(split_lon, split_lat)
            marker.set_data([lon[-1]], [lat[-1]])
            globe_line.set_data_3d(*positions[:, 2:].T)
            az_line.set_data(*break_jumps(values[:, 0], values[:, 1]))
            el_line.set_data(values[:, 0], values[:, 2])
            az_line.set_marker("." if len(rows) == 1 else "")
            el_line.set_marker("." if len(rows) == 1 else "")
        for ax in (self.az_ax, self.el_ax):
            ax.relim()
            ax.autoscale_view(scalex=True, scaley=False)
        self._draw_all()

    def _draw_all(self):
        """Перерисовать все внутренние вкладки после поступления новых точек."""
        self.map_canvas.draw_idle()
        self.globe_canvas.draw_idle()
        self.angles_canvas.draw_idle()
