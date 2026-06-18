import json
from pathlib import Path
from typing import Any

import pandas as pd


class DataBus:
    _base_dir: Path | None = None

    @classmethod
    def _ensure_base_dir(cls) -> Path:
        if cls._base_dir is None:
            cls._base_dir = Path.cwd() / "temp_data"
        cls._base_dir.mkdir(parents=True, exist_ok=True)
        return cls._base_dir

    @classmethod
    def _run_dir(cls, run_id: str) -> Path:
        d = cls._ensure_base_dir() / str(run_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def save_data(cls, run_id: str, node_id: str, port: str, data: Any) -> str:
        run_path = cls._run_dir(run_id)
        filename = f"{node_id}__{port}"
        filepath = run_path / filename

        if isinstance(data, pd.DataFrame):
            path = filepath.with_suffix(".parquet")
            data.to_parquet(path, index=False)
        else:
            path = filepath.with_suffix(".json")
            path.write_text(json.dumps(data, default=str, ensure_ascii=False), encoding="utf-8")

        return str(path)

    @classmethod
    def load_data(cls, path: str) -> Any:
        p = Path(path)
        if not p.exists():
            return None
        if p.suffix == ".parquet":
            return pd.read_parquet(p)
        return json.loads(p.read_text(encoding="utf-8"))

    @classmethod
    def cleanup_run(cls, run_id: str) -> None:
        run_path = cls._ensure_base_dir() / str(run_id)
        if run_path.exists():
            import shutil
            shutil.rmtree(run_path)
