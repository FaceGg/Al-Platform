import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class _NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles numpy types."""

    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if isinstance(obj, (pd.Period,)):
            return str(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)


class DataBus:
    _base_dir: Path | None = None
    _workspace_component_pattern = re.compile(r"[^A-Za-z0-9_-]+")

    @classmethod
    def set_base_dir(cls, path: str | Path) -> None:
        """Override the default temporary directory for tests."""
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        cls._base_dir = p

    @classmethod
    def _ensure_base_dir(cls) -> Path:
        if cls._base_dir is not None:
            cls._base_dir.mkdir(parents=True, exist_ok=True)
            return cls._base_dir
        configured = os.getenv("ML_PLATFORM_TEMP_DIR")
        if configured:
            default = Path(configured)
        else:
            default = Path(tempfile.gettempdir()) / "ml_platform_data"
        try:
            default.mkdir(parents=True, exist_ok=True)
            probe = default / ".write_test"
            probe.touch()
            probe.unlink()
            cls._base_dir = default
        except (OSError, PermissionError):
            cls._base_dir = Path(tempfile.gettempdir()) / "ml_platform_data"
        cls._base_dir.mkdir(parents=True, exist_ok=True)
        return cls._base_dir

    @classmethod
    def _workspace_component(cls, value: str, fallback: str) -> str:
        """Keep workflow-scoped directories within the configured base directory."""
        component = cls._workspace_component_pattern.sub("_", str(value)).strip("_")
        return component or fallback

    @classmethod
    def workspace_dir(cls, run_id: str, workflow_id: str | None = None) -> Path:
        """Return the run workspace, preserving the legacy layout without a workflow ID."""
        base_dir = cls._ensure_base_dir()
        if workflow_id is None:
            d = base_dir / str(run_id)
        else:
            d = (
                base_dir
                / "workflows"
                / cls._workspace_component(workflow_id, "workflow")
                / "runs"
                / cls._workspace_component(run_id, "run")
            )
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def _run_dir(cls, run_id: str, workflow_id: str | None = None) -> Path:
        return cls.workspace_dir(run_id, workflow_id)

    @classmethod
    def save_data(
        cls,
        run_id: str,
        node_id: str,
        port: str,
        data: Any,
        workflow_id: str | None = None,
    ) -> str:
        run_path = cls._run_dir(run_id, workflow_id)
        filename = f"{node_id}__{port}"
        filepath = run_path / filename

        # Handle bytes - save as binary
        if isinstance(data, bytes):
            path = filepath.with_suffix(".bin")
            path.write_bytes(data)
            return str(path)

        # Normalize data to DataFrame for efficient storage
        df = cls._to_dataframe(data)
        if df is not None:
            path = filepath.with_suffix(".jsonl")
            cls._write_jsonl(path, df)
            return str(path)

        # Fallback: small objects as JSON
        path = filepath.with_suffix(".json")
        path.write_text(json.dumps(data, default=str, ensure_ascii=False), encoding="utf-8")
        return str(path)

    @staticmethod
    def _to_dataframe(data: Any) -> pd.DataFrame | None:
        """Convert common data types to DataFrame, or return None.
        Empty dicts/lists are not converted (they fall through to JSON)."""
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, (list, tuple)):
            if len(data) > 0 and isinstance(data[0], dict):
                return pd.DataFrame(data)
            return None
        if isinstance(data, dict):
            if len(data) == 0:
                return None  # empty dict -> JSON
            if all(isinstance(v, (list, tuple)) for v in data.values()):
                return pd.DataFrame(data)
            return None
        return None

    @staticmethod
    def _write_jsonl(path: Path, df: pd.DataFrame) -> None:
        """Write DataFrame as JSON Lines with metadata header."""
        cols = list(df.columns)
        header = {"__type__": "DataFrame", "columns": cols, "rows": len(df)}
        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(header, ensure_ascii=False) + "\n")
            for _, row in df.iterrows():
                record = {}
                for col in cols:
                    val = row[col]
                    if isinstance(val, (np.integer,)):
                        val = int(val)
                    elif isinstance(val, (np.floating,)):
                        val = float(val)
                    elif isinstance(val, (np.ndarray,)):
                        val = val.tolist()
                    elif isinstance(val, pd.Timestamp):
                        val = val.isoformat()
                    elif isinstance(val, bytes):
                        val = val.decode("utf-8", errors="replace")
                    elif pd.isna(val):
                        val = None
                    record[col] = val
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @classmethod
    def load_data(cls, path: str) -> Any:
        p = Path(path)
        if not p.exists():
            return None

        if p.suffix == ".bin":
            return p.read_bytes()

        if p.suffix == ".jsonl":
            return cls._read_jsonl(p)

        if p.suffix == ".json":
            with p.open("r", encoding="utf-8") as f:
                raw = json.loads(f.read())
            return raw

        return None

    @staticmethod
    def _read_jsonl(p: Path) -> pd.DataFrame | Any:
        """Read JSON Lines file back to DataFrame or raw data."""
        with p.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
            if not header_line:
                return pd.DataFrame()
            header = json.loads(header_line)

            if header.get("__type__") == "DataFrame":
                records = []
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
                df = pd.DataFrame(records)
                cols = header.get("columns", [])
                if cols:
                    for col in cols:
                        if col not in df.columns:
                            df[col] = None
                    df = df[cols]
                return df

            return header

    @classmethod
    def cleanup_run(cls, run_id: str, workflow_id: str | None = None) -> None:
        run_path = cls._run_dir(run_id, workflow_id)
        if run_path.exists():
            import shutil
            shutil.rmtree(run_path)
