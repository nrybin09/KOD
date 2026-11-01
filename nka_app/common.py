"""Единая точка общих импортов и именованных констант приложения.

Внутренние модули проекта импортируют отсюда стандартные и сторонние
библиотеки. Импорты классов самого проекта остаются в соответствующих файлах,
чтобы не создавать циклические зависимости.
"""

# Стандартная библиотека.
from copy import copy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from time import monotonic
import json
import math
import random
import re
import sys

# Численные расчёты.
import numpy as np

# Qt-интерфейс.
from PySide6.QtCore import QEvent, QPointF, QRectF, QSignalBlocker, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Графики Matplotlib.
from matplotlib import colormaps, get_data_path, rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Line3DCollection


# Пути проекта.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = PROJECT_ROOT / "maps" / "world.geojson"

# Поддерживаемые источники и сигналы.
SOURCES = ("Rinex eph", "Rinex alm", "NV08C eph", "NV08C alm")
SIGNALS = ("L1OF", "L1CA")

# Поля исходных записей эфемерид.
GPS_FIELDS = (
    "prn", "af0", "af1", "af2", "iode", "crs", "deltan", "m0", "cuc", "e",
    "cus", "sqrtA", "toe", "cic", "OMEGA", "cis", "i0", "crc", "omega",
    "omegaDot", "iDot", "codeL2", "gpsWeekNo", "L2flag", "svaccur", "svhealth",
    "tgd", "iodc", "txTime", "fitInt",
)
GLO_FIELDS = (
    "prn", "tauN", "gammaN", "tb", "x", "dx", "ddx", "svhealth", "y", "dy",
    "ddy", "freqNo", "z", "dz", "ddz", "age",
)

# Понятные обозначения производных координат в заголовках таблицы.
# Исходные имена полей парсера не меняются, чтобы не затрагивать расчёты.
NAVIGATION_TABLE_HEADERS = {
    "dx": "Vx", "dy": "Vy", "dz": "Vz",
    "ddx": "Ax", "ddy": "Ay", "ddz": "Az",
}

# Редактирование навигационных параметров.
INTEGER_FIELDS = {
    "Na", "wna", "gpsWeekNo", "freqNo", "health", "svHealth", "svhealth",
    "iode", "iodc", "codeL2", "L2flag",
}
TIME_FIELDS = {"toa", "wna", "toe", "gpsWeekNo", "Na", "ta"}

# Эллипсоиды и переход ПЗ-90.02 -> WGS-84 (ITRF2000), м.
ELLIPSOIDS = {
    "WGS84": (6378137.0, 298.257223563),
    "PZ90": (6378136.0, 298.257839303),
}
PZ_TO_WGS = np.array([-0.36, 0.08, 0.18])

# Формат TXT-экспорта.
HEADER = "dt\taz\tel\tX\tY\tZ\tVx\tVy\tVz\tR"

# Задержка перестройки таблицы после последнего движения колеса мыши.
TABLE_UPDATE_DELAY_MS = 1000


# Общее регулярное выражение для чтения чисел из RINEX.
FLOAT_RE = re.compile(r"[+\-]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][+\-]?\d+)?")

# Общая физическая константа.
OMEGA_EARTH = 7.2921151467e-5

# GPS.
MU_GPS = 3.986005e14
GPS_WEEK = 604800
GPS_HALF_WEEK = 302400

# ГЛОНАСС (ПЗ-90.02).
SEC_IN_DAY = 86400
DAYS_1461 = 1461
DAYS_1460 = 1460
T_CP = 40544
I_CP = 64.8
# В формате AGL поправка dI отсчитывается от старого опорного наклонения 63°.
AGL_REFERENCE_INCLINATION_DEG = 63.0
MU_GLONASS = 3.986004418e14
EARTH_RADIUS_GLONASS = 6378136.0
J2_GLONASS = 1082.62575e-6


