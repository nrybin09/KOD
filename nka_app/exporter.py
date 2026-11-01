"""Табличный экспорт: один файл на выбранный НКА, без перезаписи."""

from nka_app.common import HEADER, Path, datetime, json, math, timezone

from nka_app.models import Experiment

def experiment_folder_name(dataset, node) -> str:
    """Имя папки по узловому моменту без недопустимых символов пути."""
    node = math.floor(float(node))
    if dataset.calendar:
        moment = datetime.fromtimestamp(node, timezone.utc).strftime("%Y%m%d_%H%M%S")
        system = "GPS" if dataset.signal == "L1CA" else "GLONASS"
        return f"experiment_{system}_{moment}"

    if dataset.signal == "L1CA":
        week, tow = divmod(node, 604800)
        day, seconds = divmod(tow, 86400)
        system = f"GPS_W{week}_D{day}"
    else:
        day, seconds = divmod(node, 86400)
        system = f"GLONASS_D{day + 1}"
    hour, seconds = divmod(seconds, 3600)
    minute, second = divmod(seconds, 60)
    return f"experiment_{system}_{hour:02d}{minute:02d}{second:02d}"


def export_experiment(experiment: Experiment, destination) -> Path:
    if not experiment.samples or not all(experiment.samples.values()):
        raise ValueError("Нет рассчитанных данных для экспорта.")
    # Каждый экспорт — отдельный каталог, прежние результаты не затираются.
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    name = experiment_folder_name(experiment.dataset, experiment.settings.node)
    folder = root / name
    suffix = 1
    while True:
        try:
            folder.mkdir()
            break
        except FileExistsError:
            # Повторный экспорт того же узлового момента не затирает предыдущий.
            folder = root / f"{name}_{suffix:02d}"
            suffix += 1
    dataset = experiment.dataset
    for prn, samples in sorted(experiment.samples.items()):
        path = folder / f"{prn:02d}_{dataset.signal}.txt"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(HEADER + "\n")
            for sample in samples:
                values = sample.values()
                stream.write(f"{values[0]:+.6f}\t" + "\t".join(f"{v:.9f}" for v in values[1:]) + "\n")
    manifest = {
        "source": dataset.source, "signal": dataset.signal, "datum": dataset.datum,
        "time_system": dataset.time_system, "complete": experiment.complete,
        "observer": {"xyz_m": experiment.observer.xyz, "datum": experiment.observer.datum},
        "settings": vars(experiment.settings), "satellites": list(experiment.selected),
        "rows": {str(prn): len(rows) for prn, rows in experiment.samples.items()}, "notes": dataset.notes,
        "parameter_edits": dataset.edits,
    }
    (folder / "experiment.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder
