from pydantic import BaseModel, Field, ConfigDict


class ParseOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id_column: str | None = None
    record_path: str | None = None
    max_file_bytes: int = Field(default=1_000_000_000, gt=0)
    max_decompressed_bytes: int = Field(default=4_000_000_000, gt=0)
    max_rows: int = Field(default=1_000_000, gt=0)
    max_columns: int = Field(default=200, gt=0)
    max_depth: int = Field(default=32, gt=0)
    max_field_bytes: int = Field(default=64 * 1024, gt=0)
    max_time_seconds: float = Field(default=300.0, gt=0)
