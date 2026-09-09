"""수집 원본(raw JSON) -> 마스터 테이블 적재 + 변경 이력(diff) 생성.

증분 판정은 별도의 전체 스냅샷 테이블을 쌓지 않고, 마스터의 현재 상태와
이번 회차 수집분을 비교하는 방식으로 처리한다.

  - 마스터에 없던 PK            -> NEW
  - 추적 필드 값이 달라짐        -> MODIFIED (필드별로 1행씩 로그)
  - 이번 회차 목록에서 사라짐     -> CANCELLED (전체 수집일 때만 판정)

DMF API에는 상태 필드가 없어서, "이번 달 목록에 없으면 취하/만료"로 간주하는
마지막 규칙이 곧 DMF의 status 판정 로직이 된다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Iterable

from .normalize import (
    NORMALIZER_VERSION,
    normalize_ingredient,
    normalize_ingredient_base,
    split_eng_ingredients,
    split_main_ingredients,
)

# 변경 감지 대상 필드 (이 목록에 없는 필드는 조용히 덮어쓴다)
DMF_TRACKED = (
    "ingredient_name_kr",
    "registrant_name",
    "manufacturer_name",
    "country_code",
    "address",
    "registration_date",
    "status",
)
FINISHED_TRACKED = (
    "product_name",
    "company_name",
    "cnsgn_manuf",
    "item_status",
    "permit_date",
    "change_date",
)

# 사람이 읽는 필드 라벨 (변경이력 화면용)
FIELD_LABELS = {
    "ingredient_name_kr": "성분명",
    "registrant_name": "등록업체",
    "manufacturer_name": "원료 제조소",
    "country_code": "제조국",
    "address": "제조소 소재지",
    "registration_date": "등록일자",
    "status": "DMF 상태",
    "product_name": "제품명",
    "company_name": "제약사",
    "cnsgn_manuf": "위탁제조사",
    "item_status": "품목 상태",
    "permit_date": "허가일자",
    "change_date": "최종변경일",
    "-": "-",
}


def current_snapshot_ym(when: datetime | None = None) -> str:
    return (when or datetime.now()).strftime("%Y-%m")


def _clean(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _to_date(v: Any) -> str | None:
    """'20260323' 또는 '2026-03-23' -> '2026-03-23'."""
    s = _clean(v)
    if not s:
        return None
    digits = s.replace("-", "").replace(".", "").replace("/", "")
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return s


# ---------------------------------------------------------------------------
# 변환 (raw -> 마스터 행)
# ---------------------------------------------------------------------------
def transform_dmf(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """DMF API 응답을 dmf_master 행으로 변환. 등록번호 기준 중복은 마지막 것만 남긴다."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        dmf_id = _clean(r.get("DMF_PERMIT_NO"))
        if not dmf_id:
            continue
        name_kr = _clean(r.get("INGR_KOR_NAME")) or ""
        out[dmf_id] = {
            "dmf_id": dmf_id,
            "ingredient_name_kr": name_kr,
            "norm_ingredient_key": normalize_ingredient(name_kr),
            "norm_base_key": normalize_ingredient_base(name_kr),
            "registrant_name": _clean(r.get("ENTP_NAME")),
            "manufacturer_name": _clean(r.get("MNFCTR_NAME")),
            "country_code": _clean(r.get("MANUF_COUNTRY_CODE_NM")),
            "address": _clean(r.get("MNFCTR_PLACE")),
            "registration_date": _to_date(r.get("DMF_PERMIT_DATE")),
            "bizrno": _clean(r.get("BIZRNO")),
            "status": "ACTIVE",
        }
    return list(out.values())


def transform_finished(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """완제 허가 응답을 '품목 x 주성분' 행으로 펼친다.

    MAIN_ITEM_INGR 이 '|' 로 구분된 복합제는 성분 수만큼 행이 생긴다.
    MAIN_INGR_ENG 는 알파벳순으로 재정렬되어 있어 한글 성분과 위치가 대응하지 않으므로,
    단일제(주성분 1개 & 영문 1개)일 때만 영문명을 성분에 귀속시킨다.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        item_seq = _clean(r.get("ITEM_SEQ"))
        if not item_seq:
            continue
        ingredients = split_main_ingredients(r.get("MAIN_ITEM_INGR"))
        if not ingredients:
            continue
        eng_list = split_eng_ingredients(r.get("MAIN_INGR_ENG"))
        single_en = eng_list[0] if (len(ingredients) == 1 and len(eng_list) == 1) else None

        base = {
            "item_seq": item_seq,
            "product_name": _clean(r.get("ITEM_NAME")),
            "product_name_en": _clean(r.get("ITEM_ENG_NAME")),
            "company_name": _clean(r.get("ENTP_NAME")),
            "company_name_en": _clean(r.get("ENTP_ENG_NAME")),
            "cnsgn_manuf": _clean(r.get("CNSGN_MANUF")),
            "item_status": _clean(r.get("CANCEL_NAME")) or "정상",
            "permit_date": _to_date(r.get("ITEM_PERMIT_DATE")),
            "cancel_date": _to_date(r.get("CANCEL_DATE")),
            "change_date": _to_date(r.get("CHANGE_DATE")),
            "etc_otc_code": _clean(r.get("ETC_OTC_CODE")),
            "atc_code": _clean(r.get("ATC_CODE")),
            "bizrno": _clean(r.get("BIZRNO")),
        }
        for code, name in ingredients:
            key = normalize_ingredient(name)
            if not key:
                continue
            out[(item_seq, key)] = {
                **base,
                "norm_ingredient_key": key,
                "norm_base_key": normalize_ingredient_base(name),
                "ingredient_code": code or None,
                "ingredient_name_kr": name,
                "ingredient_name_en": single_en,
            }
    return list(out.values())


# ---------------------------------------------------------------------------
# 적재 + 차분
# ---------------------------------------------------------------------------
def _log(
    conn: sqlite3.Connection,
    snapshot_ym: str,
    target_type: str,
    target_id: str,
    label: str | None,
    change_type: str,
    field: str,
    before: Any,
    after: Any,
    detected_at: str,
) -> None:
    conn.execute(
        """INSERT INTO change_history_log
           (snapshot_ym, target_type, target_id, target_label, change_type,
            field_name, before_val, after_val, detected_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (snapshot_ym, target_type, target_id, label, change_type,
         field, None if before is None else str(before),
         None if after is None else str(after), detected_at),
    )


# 개별 재조회로 확인하지 못했을 때, 몇 회 연속 미관측이면 취하로 볼 것인가.
MISS_THRESHOLD = 2


def missing_candidates_dmf(
    conn: sqlite3.Connection, records: list[dict[str, Any]]
) -> dict[str, str]:
    """이번 회차 목록에 없는 활성 DMF 후보 {dmf_id: 성분명}."""
    seen = {r["dmf_id"] for r in records}
    return {
        row["dmf_id"]: row["ingredient_name_kr"] or ""
        for row in conn.execute(
            "SELECT dmf_id, ingredient_name_kr FROM dmf_master WHERE status <> 'CANCELLED'"
        )
        if row["dmf_id"] not in seen
    }


def missing_candidates_finished(
    conn: sqlite3.Connection, records: list[dict[str, Any]]
) -> list[str]:
    """이번 회차 목록에 없는 완제 품목기준코드 후보."""
    seen = {(r["item_seq"], r["norm_ingredient_key"]) for r in records}
    out: set[str] = set()
    for row in conn.execute(
        "SELECT item_seq, norm_ingredient_key FROM finished_drug_master WHERE item_status <> '목록삭제'"
    ):
        if (row["item_seq"], row["norm_ingredient_key"]) not in seen:
            out.add(row["item_seq"])
    return sorted(out)


def ingest_dmf(
    conn: sqlite3.Connection,
    records: list[dict[str, Any]],
    snapshot_ym: str,
    detect_cancel: bool = True,
    confirmed_missing: set[str] | None = None,
) -> dict[str, int]:
    """dmf_master 갱신 + change_history_log 기록. 반환: 변경 건수 요약."""
    now = datetime.now().isoformat(timespec="seconds")
    existing = {
        row["dmf_id"]: dict(row)
        for row in conn.execute("SELECT * FROM dmf_master")
    }
    stats = {"new": 0, "modified": 0, "cancelled": 0, "rows": len(records)}

    for rec in records:
        did = rec["dmf_id"]
        prev = existing.get(did)
        if prev is None:
            conn.execute(
                """INSERT INTO dmf_master
                   (dmf_id, ingredient_name_kr, norm_ingredient_key, norm_base_key,
                    registrant_name, manufacturer_name, country_code, address,
                    registration_date, bizrno, status,
                    first_seen_snapshot, last_seen_snapshot, updated_at)
                   VALUES (:dmf_id,:ingredient_name_kr,:norm_ingredient_key,:norm_base_key,
                           :registrant_name,:manufacturer_name,:country_code,:address,
                           :registration_date,:bizrno,:status,:snap,:snap,:now)""",
                {**rec, "snap": snapshot_ym, "now": now},
            )
            stats["new"] += 1
            _log(conn, snapshot_ym, "DMF", did, rec["ingredient_name_kr"],
                 "NEW", "-", None, rec["manufacturer_name"], now)
        else:
            changed = [
                (f, prev.get(f), rec.get(f))
                for f in DMF_TRACKED
                if (prev.get(f) or "") != (rec.get(f) or "")
            ]
            if changed:
                stats["modified"] += 1
                for f, b, a in changed:
                    _log(conn, snapshot_ym, "DMF", did, rec["ingredient_name_kr"],
                         "MODIFIED", f, b, a, now)
            conn.execute(
                """UPDATE dmf_master SET
                     ingredient_name_kr=:ingredient_name_kr,
                     norm_ingredient_key=:norm_ingredient_key,
                     norm_base_key=:norm_base_key,
                     registrant_name=:registrant_name,
                     manufacturer_name=:manufacturer_name,
                     country_code=:country_code,
                     address=:address,
                     registration_date=:registration_date,
                     bizrno=:bizrno,
                     status=:status,
                     last_seen_snapshot=:snap,
                     miss_streak=0,
                     updated_at=:now
                   WHERE dmf_id=:dmf_id""",
                {**rec, "snap": snapshot_ym, "now": now},
            )

    if detect_cancel:
        seen = {r["dmf_id"] for r in records}
        for did, prev in existing.items():
            if did in seen or prev.get("status") == "CANCELLED":
                continue
            streak = int(prev.get("miss_streak") or 0) + 1
            if confirmed_missing is not None:
                gone = did in confirmed_missing
            else:
                gone = streak >= MISS_THRESHOLD
            if not gone:
                # 페이징 누락일 수 있으므로 취하로 단정하지 않고 미관측만 기록한다.
                conn.execute(
                    "UPDATE dmf_master SET miss_streak=?, updated_at=? WHERE dmf_id=?",
                    (streak, now, did),
                )
                stats["missed"] = stats.get("missed", 0) + 1
                continue
            conn.execute(
                "UPDATE dmf_master SET status='CANCELLED', miss_streak=?, updated_at=? WHERE dmf_id=?",
                (streak, now, did),
            )
            stats["cancelled"] += 1
            _log(conn, snapshot_ym, "DMF", did, prev.get("ingredient_name_kr"),
                 "CANCELLED", "status", prev.get("status"), "CANCELLED", now)

    return stats


def ingest_finished(
    conn: sqlite3.Connection,
    records: list[dict[str, Any]],
    snapshot_ym: str,
    detect_cancel: bool = True,
    confirmed_missing: set[str] | None = None,
) -> dict[str, int]:
    """finished_drug_master 갱신 + change_history_log 기록."""
    now = datetime.now().isoformat(timespec="seconds")
    existing = {
        (row["item_seq"], row["norm_ingredient_key"]): dict(row)
        for row in conn.execute("SELECT * FROM finished_drug_master")
    }
    stats = {"new": 0, "modified": 0, "cancelled": 0, "rows": len(records)}
    logged_new: set[str] = set()
    logged_mod: set[str] = set()

    for rec in records:
        pk = (rec["item_seq"], rec["norm_ingredient_key"])
        prev = existing.get(pk)
        if prev is None:
            conn.execute(
                """INSERT INTO finished_drug_master
                   (item_seq, norm_ingredient_key, norm_base_key, product_name,
                    product_name_en, company_name, company_name_en, cnsgn_manuf,
                    ingredient_code, ingredient_name_kr, ingredient_name_en,
                    item_status, permit_date, cancel_date, change_date,
                    etc_otc_code, atc_code, bizrno,
                    first_seen_snapshot, last_seen_snapshot, updated_at)
                   VALUES (:item_seq,:norm_ingredient_key,:norm_base_key,:product_name,
                           :product_name_en,:company_name,:company_name_en,:cnsgn_manuf,
                           :ingredient_code,:ingredient_name_kr,:ingredient_name_en,
                           :item_status,:permit_date,:cancel_date,:change_date,
                           :etc_otc_code,:atc_code,:bizrno,:snap,:snap,:now)""",
                {**rec, "snap": snapshot_ym, "now": now},
            )
            # 복합제는 성분 수만큼 행이 생기므로, 품목 단위로 1회만 카운트/로그한다.
            if rec["item_seq"] not in logged_new:
                logged_new.add(rec["item_seq"])
                stats["new"] += 1
                _log(conn, snapshot_ym, "FINISHED", rec["item_seq"], rec["product_name"],
                     "NEW", "-", None, rec["company_name"], now)
        else:
            changed = [
                (f, prev.get(f), rec.get(f))
                for f in FINISHED_TRACKED
                if (prev.get(f) or "") != (rec.get(f) or "")
            ]
            if changed and rec["item_seq"] not in logged_mod:
                logged_mod.add(rec["item_seq"])
                stats["modified"] += 1
                for f, b, a in changed:
                    _log(conn, snapshot_ym, "FINISHED", rec["item_seq"], rec["product_name"],
                         "MODIFIED", f, b, a, now)
            conn.execute(
                """UPDATE finished_drug_master SET
                     norm_base_key=:norm_base_key,
                     product_name=:product_name,
                     product_name_en=:product_name_en,
                     company_name=:company_name,
                     company_name_en=:company_name_en,
                     cnsgn_manuf=:cnsgn_manuf,
                     ingredient_code=:ingredient_code,
                     ingredient_name_kr=:ingredient_name_kr,
                     ingredient_name_en=COALESCE(:ingredient_name_en, ingredient_name_en),
                     item_status=:item_status,
                     permit_date=:permit_date,
                     cancel_date=:cancel_date,
                     change_date=:change_date,
                     etc_otc_code=:etc_otc_code,
                     atc_code=:atc_code,
                     bizrno=:bizrno,
                     last_seen_snapshot=:snap,
                     miss_streak=0,
                     updated_at=:now
                   WHERE item_seq=:item_seq AND norm_ingredient_key=:norm_ingredient_key""",
                {**rec, "snap": snapshot_ym, "now": now},
            )

    if detect_cancel:
        seen = {(r["item_seq"], r["norm_ingredient_key"]) for r in records}
        logged_gone: set[str] = set()
        for pk, prev in existing.items():
            if pk in seen or prev.get("item_status") == "목록삭제":
                continue
            streak = int(prev.get("miss_streak") or 0) + 1
            if confirmed_missing is not None:
                gone = pk[0] in confirmed_missing
            else:
                gone = streak >= MISS_THRESHOLD
            if not gone:
                conn.execute(
                    """UPDATE finished_drug_master SET miss_streak=?, updated_at=?
                        WHERE item_seq=? AND norm_ingredient_key=?""",
                    (streak, now, pk[0], pk[1]),
                )
                stats["missed"] = stats.get("missed", 0) + 1
                continue
            conn.execute(
                """UPDATE finished_drug_master SET item_status='목록삭제', miss_streak=?, updated_at=?
                    WHERE item_seq=? AND norm_ingredient_key=?""",
                (streak, now, pk[0], pk[1]),
            )
            if pk[0] not in logged_gone:
                logged_gone.add(pk[0])
                stats["cancelled"] += 1
                _log(conn, snapshot_ym, "FINISHED", pk[0], prev.get("product_name"),
                     "CANCELLED", "item_status", prev.get("item_status"), "목록삭제", now)

    return stats


SETTING_KEY_NORMALIZER = "normalizer_version"

_FINISHED_COLUMNS = (
    "item_seq", "norm_ingredient_key", "norm_base_key", "product_name",
    "product_name_en", "company_name", "company_name_en", "cnsgn_manuf",
    "ingredient_code", "ingredient_name_kr", "ingredient_name_en",
    "item_status", "permit_date", "cancel_date", "change_date",
    "etc_otc_code", "atc_code", "bizrno",
    "first_seen_snapshot", "last_seen_snapshot", "miss_streak", "updated_at",
)


def rekey_masters(conn: sqlite3.Connection) -> dict[str, int]:
    """정규화 규칙이 바뀐 뒤 마스터의 정규화 키를 다시 계산한다.

    norm_ingredient_key 는 finished_drug_master 의 기본키 일부라 단순 UPDATE 로는
    중복 충돌이 날 수 있다. 그래서 전 행을 읽어 새 키로 다시 묶은 뒤 통째로 다시 쓴다.
    같은 (품목, 새 키)로 합쳐지는 행은 최근 관측분을 남긴다.
    """
    stats = {"dmf": 0, "finished_before": 0, "finished_after": 0}

    dmf_rows = conn.execute(
        "SELECT dmf_id, ingredient_name_kr FROM dmf_master"
    ).fetchall()
    conn.executemany(
        "UPDATE dmf_master SET norm_ingredient_key=?, norm_base_key=? WHERE dmf_id=?",
        [
            (normalize_ingredient(r["ingredient_name_kr"]),
             normalize_ingredient_base(r["ingredient_name_kr"]),
             r["dmf_id"])
            for r in dmf_rows
        ],
    )
    stats["dmf"] = len(dmf_rows)

    fin_rows = [dict(r) for r in conn.execute("SELECT * FROM finished_drug_master")]
    stats["finished_before"] = len(fin_rows)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in fin_rows:
        name = row.get("ingredient_name_kr")
        row["norm_ingredient_key"] = normalize_ingredient(name)
        row["norm_base_key"] = normalize_ingredient_base(name)
        if not row["norm_ingredient_key"]:
            continue
        pk = (row["item_seq"], row["norm_ingredient_key"])
        prev = merged.get(pk)
        if prev is None or (row.get("last_seen_snapshot") or "") >= (prev.get("last_seen_snapshot") or ""):
            merged[pk] = row

    placeholders = ",".join("?" * len(_FINISHED_COLUMNS))
    conn.execute("DELETE FROM finished_drug_master")
    conn.executemany(
        f"INSERT INTO finished_drug_master ({','.join(_FINISHED_COLUMNS)}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in _FINISHED_COLUMNS) for r in merged.values()],
    )
    stats["finished_after"] = len(merged)
    return stats


def ensure_normalizer_version(conn: sqlite3.Connection) -> dict[str, int] | None:
    """저장된 정규화 버전이 현재와 다르면 마스터를 재계산한다."""
    row = conn.execute(
        "SELECT value FROM app_setting WHERE key = ?", (SETTING_KEY_NORMALIZER,)
    ).fetchone()
    saved = row["value"] if row else None
    if saved == NORMALIZER_VERSION:
        return None

    stats = rekey_masters(conn)
    conn.execute(
        """INSERT INTO app_setting(key, value, updated_at) VALUES(?,?,?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (SETTING_KEY_NORMALIZER, NORMALIZER_VERSION,
         datetime.now().isoformat(timespec="seconds")),
    )
    return stats


def enrich_dmf_english_names(conn: sqlite3.Connection) -> int:
    """DMF에 없는 영문 성분명을 완제 데이터에서 역매핑해 채운다.

    복합제는 MAIN_INGR_ENG의 순서가 한글과 대응하지 않으므로,
    단일제에서 수집된 (정규화 키 -> 영문명) 쌍만 사용한다.
    """
    cur = conn.execute(
        """SELECT norm_ingredient_key, ingredient_name_en, COUNT(*) AS c
             FROM finished_drug_master
            WHERE ingredient_name_en IS NOT NULL AND ingredient_name_en <> ''
            GROUP BY norm_ingredient_key, ingredient_name_en
            ORDER BY c DESC"""
    )
    best: dict[str, str] = {}
    for row in cur:
        best.setdefault(row["norm_ingredient_key"], row["ingredient_name_en"])
    if not best:
        return 0
    conn.executemany(
        """UPDATE dmf_master SET ingredient_name_en=?
            WHERE norm_ingredient_key=?
              AND (ingredient_name_en IS NULL OR ingredient_name_en='')""",
        [(en, key) for key, en in best.items()],
    )
    return conn.execute(
        "SELECT COUNT(*) AS c FROM dmf_master WHERE ingredient_name_en IS NOT NULL"
    ).fetchone()["c"]


# ---------------------------------------------------------------------------
# 수집 실행 이력
# ---------------------------------------------------------------------------
def start_run(conn: sqlite3.Connection, snapshot_ym: str, sync_type: str, target: str) -> int:
    cur = conn.execute(
        """INSERT INTO sync_run (snapshot_ym, sync_type, target, started_at, status)
           VALUES (?,?,?,?, 'RUNNING')""",
        (snapshot_ym, sync_type, target, datetime.now().isoformat(timespec="seconds")),
    )
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    dmf_rows: int = 0,
    finished_rows: int = 0,
    new_cnt: int = 0,
    mod_cnt: int = 0,
    cancel_cnt: int = 0,
    message: str = "",
) -> None:
    conn.execute(
        """UPDATE sync_run SET finished_at=?, status=?, dmf_rows=?, finished_rows=?,
                               new_cnt=?, mod_cnt=?, cancel_cnt=?, message=?
            WHERE run_id=?""",
        (datetime.now().isoformat(timespec="seconds"), status, dmf_rows, finished_rows,
         new_cnt, mod_cnt, cancel_cnt, message[:2000], run_id),
    )
