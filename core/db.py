"""SQLite 스키마 정의 및 커넥션 관리.

PRD의 3개 테이블(dmf_master / finished_drug_master / change_history_log)을 기준으로 하되,
실제 API 응답에 존재하는 필드(등록업체, 위탁제조사, 사업자번호 등)와
증분 판정에 필요한 스냅샷 컬럼을 덧붙였다.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import DB_PATH

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1. DMF 원료의약품 마스터 --------------------------------------------------
CREATE TABLE IF NOT EXISTS dmf_master (
    dmf_id              TEXT PRIMARY KEY,   -- DMF_PERMIT_NO (등록번호)
    ingredient_name_kr  TEXT,               -- INGR_KOR_NAME (성분명 국문)
    ingredient_name_en  TEXT,               -- 완제 API에서 역매핑한 영문명 (보강)
    norm_ingredient_key TEXT,               -- 정밀 정규화 키
    norm_base_key       TEXT,               -- 염 제거 골격 키
    registrant_name     TEXT,               -- ENTP_NAME (국내 등록/수입 업체)
    manufacturer_name   TEXT,               -- MNFCTR_NAME (실제 원료 제조소)
    country_code        TEXT,               -- MANUF_COUNTRY_CODE_NM (제조국)
    address             TEXT,               -- MNFCTR_PLACE (제조소 소재지)
    registration_date   TEXT,               -- DMF_PERMIT_DATE (YYYY-MM-DD)
    bizrno              TEXT,               -- 사업자등록번호
    status              TEXT DEFAULT 'ACTIVE',   -- ACTIVE / CANCELLED
    first_seen_snapshot TEXT,               -- 최초 관측 스냅샷 (YYYY-MM)
    last_seen_snapshot  TEXT,               -- 최종 관측 스냅샷 (YYYY-MM)
    miss_streak         INTEGER DEFAULT 0,  -- 연속 미관측 횟수 (허위 취하 방지)
    updated_at          TEXT
);
CREATE INDEX IF NOT EXISTS ix_dmf_norm  ON dmf_master(norm_ingredient_key);
CREATE INDEX IF NOT EXISTS ix_dmf_base  ON dmf_master(norm_base_key);
CREATE INDEX IF NOT EXISTS ix_dmf_ctry  ON dmf_master(country_code);
CREATE INDEX IF NOT EXISTS ix_dmf_stat  ON dmf_master(status);

-- 2. 완제의약품 주성분 연계 마스터 (품목 x 주성분 = 1행) ---------------------
CREATE TABLE IF NOT EXISTS finished_drug_master (
    item_seq            TEXT NOT NULL,      -- ITEM_SEQ (품목기준코드)
    norm_ingredient_key TEXT NOT NULL,      -- 정밀 정규화 키
    norm_base_key       TEXT,               -- 염 제거 골격 키
    product_name        TEXT,               -- ITEM_NAME
    product_name_en     TEXT,               -- ITEM_ENG_NAME
    company_name        TEXT,               -- ENTP_NAME (완제 제조/수입사)
    company_name_en     TEXT,               -- ENTP_ENG_NAME
    cnsgn_manuf         TEXT,               -- CNSGN_MANUF (위탁제조사)
    ingredient_code     TEXT,               -- MAIN_ITEM_INGR 내 [M코드]
    ingredient_name_kr  TEXT,               -- 주성분명 (국문)
    ingredient_name_en  TEXT,               -- 단일제일 때만 신뢰 가능 (아래 주석 참조)
    item_status         TEXT,               -- 정상 / 취하 / 유효기간만료 / 폐업
    permit_date         TEXT,               -- ITEM_PERMIT_DATE (YYYY-MM-DD)
    cancel_date         TEXT,               -- CANCEL_DATE
    change_date         TEXT,               -- CHANGE_DATE (최종 변경일)
    etc_otc_code        TEXT,               -- 전문/일반 구분
    atc_code            TEXT,
    bizrno              TEXT,
    first_seen_snapshot TEXT,
    last_seen_snapshot  TEXT,
    miss_streak         INTEGER DEFAULT 0,  -- 연속 미관측 횟수 (허위 취하 방지)
    updated_at          TEXT,
    PRIMARY KEY (item_seq, norm_ingredient_key)
);
CREATE INDEX IF NOT EXISTS ix_fin_norm ON finished_drug_master(norm_ingredient_key);
CREATE INDEX IF NOT EXISTS ix_fin_base ON finished_drug_master(norm_base_key);
CREATE INDEX IF NOT EXISTS ix_fin_stat ON finished_drug_master(item_status);
CREATE INDEX IF NOT EXISTS ix_fin_comp ON finished_drug_master(company_name);

-- 3. 증분 갱신 및 변경 이력 추적 --------------------------------------------
CREATE TABLE IF NOT EXISTS change_history_log (
    log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ym   TEXT,                     -- 감지된 스냅샷 (YYYY-MM)
    target_type   TEXT,                     -- 'DMF' | 'FINISHED'
    target_id     TEXT,                     -- dmf_id 또는 item_seq
    target_label  TEXT,                     -- 사람이 읽을 이름 (성분명/제품명)
    change_type   TEXT,                     -- 'NEW' | 'MODIFIED' | 'CANCELLED'
    field_name    TEXT,                     -- 변경된 필드명 (NEW/CANCELLED는 '-')
    before_val    TEXT,
    after_val     TEXT,
    detected_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_log_snap ON change_history_log(snapshot_ym);
CREATE INDEX IF NOT EXISTS ix_log_type ON change_history_log(target_type, change_type);

-- 4. 수집 실행 이력 (스냅샷 버전 관리) --------------------------------------
CREATE TABLE IF NOT EXISTS sync_run (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_ym   TEXT,                     -- YYYY-MM
    sync_type     TEXT,                     -- 'FULL' | 'INCREMENTAL'
    target        TEXT,                     -- 'DMF' | 'FINISHED' | 'BOTH'
    started_at    TEXT,
    finished_at   TEXT,
    status        TEXT,                     -- 'RUNNING' | 'SUCCESS' | 'FAILED'
    dmf_rows      INTEGER DEFAULT 0,
    finished_rows INTEGER DEFAULT 0,
    new_cnt       INTEGER DEFAULT 0,
    mod_cnt       INTEGER DEFAULT 0,
    cancel_cnt    INTEGER DEFAULT 0,
    message       TEXT
);

-- 5. 앱 설정 (API 키 등) ----------------------------------------------------
CREATE TABLE IF NOT EXISTS app_setting (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);
"""


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """행을 dict 처럼 다루는 SQLite 커넥션을 연다."""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connect(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# 구버전 DB를 위한 컬럼 추가 (SQLite 는 ADD COLUMN IF NOT EXISTS 를 지원하지 않는다)
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("dmf_master", "miss_streak", "INTEGER DEFAULT 0"),
    ("finished_drug_master", "miss_streak", "INTEGER DEFAULT 0"),
)


def init_db(db_path: str | Path | None = None) -> None:
    """스키마를 생성하고 누락된 컬럼을 채운다 (idempotent)."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        for table, column, decl in _MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM app_setting WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    from datetime import datetime

    with connect() as conn:
        conn.execute(
            """INSERT INTO app_setting(key, value, updated_at) VALUES(?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                              updated_at = excluded.updated_at""",
            (key, value, datetime.now().isoformat(timespec="seconds")),
        )


def table_count(table: str) -> int:
    with connect() as conn:
        try:
            return conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
        except sqlite3.OperationalError:
            return 0
