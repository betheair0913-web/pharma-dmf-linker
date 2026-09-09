# -*- coding: utf-8 -*-
"""로컬 SQLite 데이터를 Vercel 배포용 Neon Postgres 로 밀어 넣는다.

수집(공공데이터 API 호출)과 정규화는 로컬 Streamlit 앱이 계속 담당한다.
이 스크립트는 그 결과 스냅샷만 Postgres 로 옮기는 단방향 적재기다.

    pip install psycopg[binary]
    # web/.env.local 의 DATABASE_URL 을 읽는다 (또는 환경변수로 지정)
    python scripts/push_to_postgres.py

전체 재적재(약 15만 행)라 몇 분 걸린다. --tables 로 일부만 올릴 수 있다.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SQLITE_PATH = BASE / "data" / "dmf_linker.db"
SCHEMA_SQL = Path(__file__).with_name("schema.sql")

# (테이블, 옮길 컬럼) - SQLite 쪽 miss_streak 등 운영 전용 컬럼은 제외한다.
TABLES: dict[str, list[str]] = {
    "dmf_master": [
        "dmf_id", "ingredient_name_kr", "ingredient_name_en", "norm_ingredient_key",
        "norm_base_key", "registrant_name", "manufacturer_name", "country_code",
        "address", "registration_date", "bizrno", "status",
        "first_seen_snapshot", "last_seen_snapshot", "updated_at",
    ],
    "finished_drug_master": [
        "item_seq", "norm_ingredient_key", "norm_base_key", "product_name",
        "product_name_en", "company_name", "company_name_en", "cnsgn_manuf",
        "ingredient_code", "ingredient_name_kr", "ingredient_name_en", "item_status",
        "permit_date", "cancel_date", "change_date", "etc_otc_code", "atc_code",
        "bizrno", "first_seen_snapshot", "last_seen_snapshot", "updated_at",
    ],
    "change_history_log": [
        "log_id", "snapshot_ym", "target_type", "target_id", "target_label",
        "change_type", "field_name", "before_val", "after_val", "detected_at",
    ],
}

BATCH = 5_000


def database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    if not url:
        # Vercel 이 내려준 web/.env.local 을 그대로 읽는다.
        env_file = BASE / "web" / ".env.local"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() in ("DATABASE_URL", "POSTGRES_URL") and value.strip():
                    url = value.strip().strip('"').strip("'")
                    break
    if not url:
        sys.exit(
            "DATABASE_URL 을 찾지 못했습니다.\n"
            "  vercel env pull web/.env.local   을 먼저 실행하거나\n"
            "  DATABASE_URL=... python scripts/push_to_postgres.py  로 지정하세요."
        )
    return url


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", nargs="*", default=list(TABLES),
                    help="옮길 테이블 (기본: 전체)")
    ap.add_argument("--skip-schema", action="store_true",
                    help="스키마 재생성 없이 데이터만 다시 넣는다")
    args = ap.parse_args()

    try:
        import psycopg
    except ImportError:
        sys.exit("psycopg 가 필요합니다:  pip install \"psycopg[binary]\"")

    if not SQLITE_PATH.exists():
        sys.exit(f"로컬 데이터가 없습니다: {SQLITE_PATH}")

    lite = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    lite.row_factory = sqlite3.Row

    with psycopg.connect(database_url(), autocommit=False) as pg:
        if not args.skip_schema:
            print("스키마 생성…", flush=True)
            with pg.cursor() as cur:
                cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
            pg.commit()

        for table in args.tables:
            cols = TABLES[table]
            total = lite.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            started = time.time()
            print(f"{table}: {total:,}행 적재 중…", end="", flush=True)

            rows = lite.execute(f"SELECT {', '.join(cols)} FROM {table}")
            copy_sql = f"COPY {table} ({', '.join(cols)}) FROM STDIN"
            done = 0
            with pg.cursor() as cur:
                if args.skip_schema:
                    cur.execute(f"TRUNCATE {table}")
                with cur.copy(copy_sql) as copy:
                    while batch := rows.fetchmany(BATCH):
                        for row in batch:
                            copy.write_row(tuple(row))
                        done += len(batch)
                        print(".", end="", flush=True)
            pg.commit()
            print(f" 완료 ({done:,}행, {time.time() - started:.1f}초)", flush=True)

        with pg.cursor() as cur:
            cur.execute("ANALYZE")
        pg.commit()

    lite.close()
    print("\n적재 완료. Vercel 앱을 새로고침하면 반영됩니다.")


if __name__ == "__main__":
    main()
