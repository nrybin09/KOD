"""Примеры data находятся и после переименования расширений пользователем."""

from pathlib import Path

from nka_app.navigation import format_extension

ROOT = Path(__file__).resolve().parents[1]


def data_file(source, signal):
    extension = format_extension(source, signal)
    matches = sorted(p for p in (ROOT / "data").rglob(f"*.{extension}") if p.is_file())
    if not matches:
        raise FileNotFoundError(
            f"Для проверки нужен хотя бы один файл *.{extension} внутри каталога data."
        )
    # Для воспроизводимости предпочитаем пару архивных файлов одной даты.
    return next((path for path in matches if path.stem == "MCCT_170102"), matches[0])
