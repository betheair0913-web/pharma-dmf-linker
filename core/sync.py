"""수집 오케스트레이션 (Full / Incremental Sync).

두 API 모두 "변경분만 주는" 파라미터를 제공하지 않는다. 그래서 증분 수집도
목록 자체는 전량을 받아오되, 마스터와 비교해 달라진 것만 기록하는 방식으로 동작한다.

  FULL        : 두 소스를 모두 받고, 목록에서 사라진 건을 취하(CANCELLED)로 판정한다.
  INCREMENTAL : 선택한 소스만 받고, 취하 판정을 하지 않는다(부분 수집으로 인한 오탐 방지).

**페이징 불안정성 대응**

이 API들은 pageNo 페이징의 정렬이 안정적이지 않아, 전량 크롤 한 번에 레코드가
1~2% 정도 누락된다(같은 데이터로 두 번 돌리면 완제 쪽에서 약 1,100건이 빠졌다가
다른 1,100건이 새로 들어온다). 보정 없이 두면 매달 허위 '신규/취하' 알림이 생긴다.
두 겹으로 막는다.

  1. 누락 보정 수집(passes=2): 전량 크롤을 두 번 돌려 PK 기준으로 합집합을 만든다.
     한 번에 누락될 확률이 p 라면 두 번 모두 누락될 확률은 p^2 로 떨어진다.
  2. 취하 후보 검증: 그래도 목록에 없는 건은 개별 조회로 실제 삭제를 확인한 뒤에만
     취하로 표시한다. 확인되지 않으면 miss_streak 만 올리고 넘어간다.
"""

from __future__ import annotations

from typing import Any, Callable

from . import collector, ingest
from .db import connect, init_db

ProgressCb = Callable[[int, int, str], None]

DMF_PK = "DMF_PERMIT_NO"
DRUG_PK = "ITEM_SEQ"


def _merge_passes(
    fetch: Callable[[ProgressCb | None], tuple[list[dict[str, Any]], int]],
    pk: str,
    passes: int,
    stage_cb: Callable[[int], ProgressCb | None],
) -> tuple[list[dict[str, Any]], int, int]:
    """전량 크롤을 passes 회 반복해 PK 기준 합집합을 만든다.

    Returns:
        (합쳐진 레코드, 서버가 알려준 총 건수, 1회차만으로 얻은 고유 건수)
    """
    merged: dict[str, dict[str, Any]] = {}
    total = 0
    first_unique = 0
    for i in range(max(1, passes)):
        rows, total = fetch(stage_cb(i))
        for r in rows:
            key = str(r.get(pk) or "")
            if key:
                merged[key] = r
        if i == 0:
            first_unique = len(merged)
    return list(merged.values()), total, first_unique


def run_sync(
    service_key: str,
    sync_type: str = "FULL",
    targets: tuple[str, ...] = ("DMF", "FINISHED"),
    snapshot_ym: str | None = None,
    progress_cb: ProgressCb | None = None,
    max_pages: int | None = None,
    passes: int = 2,
    verify_cancellations: bool = True,
) -> dict[str, Any]:
    """수집 -> 변환 -> 적재 -> 차분 기록까지 한 번에 수행한다.

    Args:
        service_key: 공공데이터포털 인증키 (Encoding/Decoding 무관).
        sync_type: 'FULL' | 'INCREMENTAL'
        targets: 수집 대상 ('DMF', 'FINISHED')
        snapshot_ym: 스냅샷 라벨. 기본값은 현재 연월(YYYY-MM).
        progress_cb: (done, total, message) 콜백.
        max_pages: 소스별 최대 페이지 수 (테스트/스모크용).
        passes: 누락 보정을 위한 전량 크롤 반복 횟수. 1이면 보정 없음.
        verify_cancellations: 취하 후보를 개별 조회로 재확인할지 여부.

    Returns:
        수집 및 변경 건수 요약 dict.
    """
    init_db()
    # 정규화 규칙이 바뀐 채로 적재하면 기존 행이 새 키와 매칭되지 않아 고아가 된다.
    # 수집 전에 마스터 키를 현재 규칙으로 맞춰 둔다.
    with connect() as conn:
        rekeyed = ingest.ensure_normalizer_version(conn)
    snap = snapshot_ym or ingest.current_snapshot_ym()
    detect_cancel = sync_type == "FULL"

    def stage(label: str, offset: int, span: int) -> ProgressCb | None:
        """소스별 진행률을 전체 진행률(0~100) 구간에 매핑한다."""
        if progress_cb is None:
            return None

        def cb(done: int, total: int, msg: str) -> None:
            pct = offset + int(span * (done / max(total, 1)))
            progress_cb(min(pct, 100), 100, msg)

        return cb

    with connect() as conn:
        run_id = ingest.start_run(conn, snap, sync_type, "+".join(targets))

    result: dict[str, Any] = {
        "rekeyed": rekeyed,
        "run_id": run_id,
        "snapshot": snap,
        "sync_type": sync_type,
        "dmf": None,
        "finished": None,
    }

    try:
        dmf_records: list[dict[str, Any]] = []
        fin_records: list[dict[str, Any]] = []
        n_passes = max(1, int(passes))

        # 진행률 배분: DMF 0~20%, 완제 20~65%, 취하 검증 65~78%, 적재 78~100%
        if "DMF" in targets:
            raw, api_total, first_unique = _merge_passes(
                lambda cb: collector.fetch_dmf(service_key, cb, max_pages),
                DMF_PK, n_passes,
                lambda i: stage(f"DMF {i + 1}차", 0 + i * (20 // n_passes), 20 // n_passes),
            )
            dmf_records = ingest.transform_dmf(raw)
            result["dmf_completeness"] = {
                "api_total": api_total, "collected": len(raw),
                "first_pass_unique": first_unique,
                "recovered_by_extra_pass": len(raw) - first_unique,
            }
        if "FINISHED" in targets:
            raw, api_total, first_unique = _merge_passes(
                lambda cb: collector.fetch_finished_drugs(service_key, cb, max_pages),
                DRUG_PK, n_passes,
                lambda i: stage(f"완제 {i + 1}차", 20 + i * (45 // n_passes), 45 // n_passes),
            )
            fin_records = ingest.transform_finished(raw)
            result["finished_completeness"] = {
                "api_total": api_total, "collected": len(raw),
                "first_pass_unique": first_unique,
                "recovered_by_extra_pass": len(raw) - first_unique,
            }

        # --- 취하 후보 검증 -------------------------------------------------
        dmf_confirmed: set[str] | None = None
        fin_confirmed: set[str] | None = None
        if detect_cancel and verify_cancellations:
            with connect() as conn:
                dmf_cand = (
                    ingest.missing_candidates_dmf(conn, dmf_records)
                    if "DMF" in targets else {}
                )
                fin_cand = (
                    ingest.missing_candidates_finished(conn, fin_records)
                    if "FINISHED" in targets else []
                )
            result["cancel_candidates"] = {"dmf": len(dmf_cand), "finished": len(fin_cand)}
            if dmf_cand:
                if progress_cb:
                    progress_cb(66, 100, f"DMF 취하 후보 {len(dmf_cand):,}건 개별 검증 중…")
                dmf_confirmed = collector.confirm_missing_dmf(
                    service_key, dmf_cand, stage("DMF 취하 검증", 66, 5)
                )
            else:
                dmf_confirmed = set()
            if fin_cand:
                if progress_cb:
                    progress_cb(71, 100, f"완제 취하 후보 {len(fin_cand):,}건 개별 검증 중…")
                fin_confirmed = collector.confirm_missing_finished(
                    service_key, fin_cand, stage("완제 취하 검증", 71, 7)
                )
            else:
                fin_confirmed = set()
            result["cancel_confirmed"] = {
                "dmf": len(dmf_confirmed), "finished": len(fin_confirmed)
            }

        if progress_cb:
            progress_cb(80, 100, "DB 적재 및 변경분 비교 중…")

        with connect() as conn:
            if "DMF" in targets:
                result["dmf"] = ingest.ingest_dmf(
                    conn, dmf_records, snap, detect_cancel, dmf_confirmed
                )
            if progress_cb:
                progress_cb(88, 100, "완제의약품 적재 중…")
            if "FINISHED" in targets:
                result["finished"] = ingest.ingest_finished(
                    conn, fin_records, snap, detect_cancel, fin_confirmed
                )
            if progress_cb:
                progress_cb(96, 100, "영문 성분명 보강 중…")
            result["enriched_en"] = ingest.enrich_dmf_english_names(conn)

            d = result["dmf"] or {}
            p = result["finished"] or {}
            ingest.finish_run(
                conn, run_id, "SUCCESS",
                dmf_rows=d.get("rows", 0),
                finished_rows=p.get("rows", 0),
                new_cnt=d.get("new", 0) + p.get("new", 0),
                mod_cnt=d.get("modified", 0) + p.get("modified", 0),
                cancel_cnt=d.get("cancelled", 0) + p.get("cancelled", 0),
                message=(
                    f"passes={n_passes} verify={verify_cancellations} "
                    f"미확정 미관측 DMF={d.get('missed', 0)} 완제={p.get('missed', 0)}"
                ),
            )

        if progress_cb:
            progress_cb(100, 100, "완료")
        result["status"] = "SUCCESS"
        return result

    except Exception as exc:  # noqa: BLE001 - 실패도 이력에 남겨야 한다
        with connect() as conn:
            ingest.finish_run(conn, run_id, "FAILED", message=str(exc))
        result["status"] = "FAILED"
        result["error"] = str(exc)
        raise


def sync_history(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_run ORDER BY run_id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
