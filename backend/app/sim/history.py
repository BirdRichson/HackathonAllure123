"""Генерация истории работы завода для обучения ИИ и графиков.

Запуск из папки backend:  python -m app.sim.history [--days 60] [--seed 42]
Результат — data/synthetic/*.parquet и сводка калибровки в консоли.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from app.config import DATA_DIR, plant_config
from app.sim.engine import PlantSim
from app.sim.summary import calibration_report, frames, shift_summary


def generate(days: int | None = None, seed: int | None = None, out_dir: Path | None = None) -> dict:
    plant = plant_config()
    days = days or int(plant["simulation"]["history_days"])
    out = out_dir or DATA_DIR / "synthetic"
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    sim = PlantSim(plant, seed=seed)
    sim.run_days(days)
    fr = frames(sim)
    fr["shifts"] = shift_summary(sim)

    for name, df in fr.items():
        df.drop(columns=[c for c in ("t", "t_start", "t_end") if c in df.columns]).to_parquet(
            out / f"{name}.parquet", index=False
        )
    meta = {
        "seed": sim.seed,
        "days": days,
        "start": sim.cal.dt(0).isoformat(),
        "end": sim.cal.dt(sim.now).isoformat(),
        "rows": {k: len(v) for k, v in fr.items()},
        "seconds": round(time.time() - t0, 1),
        "note": "Синтетическая история (демо-данные), откалибрована по тестовым данным организаторов.",
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"meta": meta, "calibration": calibration_report(fr["shifts"])}


def main() -> None:
    ap = argparse.ArgumentParser(description="Сгенерировать историю завода")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    res = generate(args.days, args.seed)
    pd.set_option("display.width", 200)
    print(json.dumps(res["meta"], ensure_ascii=False, indent=2))
    print("\nКалибровка (средние по сменам):")
    print(res["calibration"].to_string())


if __name__ == "__main__":
    main()
