"""CSV / Parquet 내보내기.

엑셀에서 한글이 깨지지 않도록 CSV 는 항상 utf-8-sig(BOM) 로 인코딩한다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import EXPORT_DIR


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """엑셀 호환 CSV 바이트 (UTF-8 BOM). Streamlit download_button 에 그대로 전달."""
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def timestamped_name(prefix: str, ext: str = "csv") -> str:
    return f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.{ext}"


def save_csv(df: pd.DataFrame, prefix: str, out_dir: Path | None = None) -> Path:
    """서버(로컬) 측에도 스냅샷 파일을 남긴다."""
    target = Path(out_dir or EXPORT_DIR)
    target.mkdir(parents=True, exist_ok=True)
    path = target / timestamped_name(prefix)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def save_parquet(df: pd.DataFrame, prefix: str, out_dir: Path | None = None) -> Path:
    target = Path(out_dir or EXPORT_DIR)
    target.mkdir(parents=True, exist_ok=True)
    path = target / timestamped_name(prefix, "parquet")
    df.to_parquet(path, index=False)
    return path
