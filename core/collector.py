"""공공데이터포털 Open API 비동기 수집기.

두 서비스를 동일한 페이징 패턴으로 긁어온다.
  - 1페이지를 먼저 받아 totalCount 확인 -> 남은 페이지를 세마포어로 동시 요청
  - 429/5xx/타임아웃은 지수 백오프로 재시도
  - 진행률 콜백(progress_cb)으로 Streamlit 프로그레스 바를 갱신

인증키 처리 주의:
포털이 발급하는 "일반 인증키(Encoding)"는 이미 %2B, %3D 로 퍼센트 인코딩된 문자열이다.
httpx 의 params= 로 그대로 넘기면 % 가 다시 %25 로 이중 인코딩되어 인증에 실패한다.
그래서 여기서는 키를 한 번 디코딩한 뒤 직접 quote 해서 쿼리스트링을 조립한다.
(Decoding 키를 붙여넣어도 동일하게 동작한다.)
"""

from __future__ import annotations

import asyncio
import math
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import quote, unquote

import httpx

from .config import (
    DMF_BASE_URL,
    DMF_OPERATION,
    DRUG_BASE_URL,
    DRUG_OPERATION,
    MAX_CONCURRENCY,
    MAX_RETRIES,
    PAGE_SIZE_DMF,
    PAGE_SIZE_DRUG,
    REQUEST_TIMEOUT,
)

ProgressCb = Callable[[int, int, str], None]


class OpenApiError(RuntimeError):
    """포털이 정상 페이로드 대신 오류 헤더를 돌려준 경우."""


def canonical_service_key(raw: str) -> str:
    """Encoding/Decoding 어느 형태로 넣어도 동일한 원본 키로 되돌린다."""
    key = (raw or "").strip()
    if "%" in key:
        key = unquote(key)
    return key


def _build_url(base: str, operation: str, service_key: str, params: dict[str, Any]) -> str:
    qs = [f"serviceKey={quote(canonical_service_key(service_key), safe='')}"]
    for k, v in params.items():
        if v is None or v == "":
            continue
        qs.append(f"{k}={quote(str(v), safe='')}")
    return f"{base}/{operation}?" + "&".join(qs)


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """정상 응답이면 body를 반환, 오류 응답이면 OpenApiError를 던진다."""
    if "OpenAPI_ServiceResponse" in payload:
        hdr = payload["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {})
        raise OpenApiError(
            f"{hdr.get('errMsg', 'UNKNOWN')} / {hdr.get('returnAuthMsg', '')} "
            f"(code={hdr.get('returnReasonCode', '')})"
        )
    header = payload.get("header") or {}
    if header.get("resultCode") not in (None, "00"):
        raise OpenApiError(f"{header.get('resultCode')} {header.get('resultMsg')}")
    body = payload.get("body")
    if body is None:
        raise OpenApiError(f"예상치 못한 응답 형식입니다: {str(payload)[:200]}")
    return body


async def _fetch_page(
    client: httpx.AsyncClient,
    url: str,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    """단일 페이지 요청 + 지수 백오프 재시도."""
    last_err: Exception | None = None
    async with sem:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(url)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return _unwrap(resp.json())
            except OpenApiError:
                # 인증 실패/서비스 없음은 재시도해도 동일하므로 즉시 전파
                raise
            except Exception as exc:  # noqa: BLE001 - 네트워크/파싱 오류 전반
                last_err = exc
                if attempt == MAX_RETRIES - 1:
                    break
                await asyncio.sleep(1.5 * (2**attempt))
    raise RuntimeError(f"페이지 수집 실패: {url.split('&')[1:3]} / {last_err}")


async def _collect(
    base: str,
    operation: str,
    service_key: str,
    page_size: int,
    extra_params: dict[str, Any] | None,
    label: str,
    progress_cb: ProgressCb | None,
    max_pages: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    extra = dict(extra_params or {})
    extra["type"] = "json"

    limits = httpx.Limits(max_connections=MAX_CONCURRENCY, max_keepalive_connections=MAX_CONCURRENCY)
    timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=20.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout, http2=False) as client:
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

        first_url = _build_url(base, operation, service_key, {**extra, "pageNo": 1, "numOfRows": page_size})
        first = await _fetch_page(client, first_url, sem)

        total = int(first.get("totalCount") or 0)
        rows: list[dict[str, Any]] = list(first.get("items") or [])
        total_pages = max(1, math.ceil(total / page_size)) if total else 1
        if max_pages:
            total_pages = min(total_pages, max_pages)

        if progress_cb:
            progress_cb(1, total_pages, f"{label} 1/{total_pages} 페이지")

        if total_pages > 1:
            done = 1

            async def worker(page: int) -> list[dict[str, Any]]:
                nonlocal done
                url = _build_url(
                    base, operation, service_key,
                    {**extra, "pageNo": page, "numOfRows": page_size},
                )
                body = await _fetch_page(client, url, sem)
                done += 1
                if progress_cb:
                    progress_cb(done, total_pages, f"{label} {done}/{total_pages} 페이지")
                return list(body.get("items") or [])

            results = await asyncio.gather(*(worker(p) for p in range(2, total_pages + 1)))
            for chunk in results:
                rows.extend(chunk)

    return rows, total


# ---------------------------------------------------------------------------
# 공개 API (동기 래퍼) - Streamlit 에서 그대로 호출한다.
# ---------------------------------------------------------------------------
def fetch_dmf(
    service_key: str,
    progress_cb: ProgressCb | None = None,
    max_pages: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """DMF 원료의약품 등록 현황 전량 수집. 반환: (레코드, 서버가 알려준 총 건수)."""
    return asyncio.run(
        _collect(
            DMF_BASE_URL, DMF_OPERATION, service_key, PAGE_SIZE_DMF,
            None, "DMF", progress_cb, max_pages,
        )
    )


def fetch_finished_drugs(
    service_key: str,
    progress_cb: ProgressCb | None = None,
    max_pages: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """완제의약품 허가 상세 정보 전량 수집. 반환: (레코드, 서버가 알려준 총 건수)."""
    return asyncio.run(
        _collect(
            DRUG_BASE_URL, DRUG_OPERATION, service_key, PAGE_SIZE_DRUG,
            None, "완제의약품", progress_cb, max_pages,
        )
    )


def fetch_dmf_by_ingredient(service_key: str, ingredient_kr: str) -> list[dict[str, Any]]:
    """성분명으로 DMF를 조회한다 (증분/스팟 확인용)."""
    rows, _ = asyncio.run(
        _collect(
            DMF_BASE_URL, DMF_OPERATION, service_key, PAGE_SIZE_DMF,
            {"ingr_kor_name": ingredient_kr}, "DMF", None, None,
        )
    )
    return rows


# ---------------------------------------------------------------------------
# 취하 판정 검증
#
# 이 API들은 pageNo 기반 페이징의 정렬이 안정적이지 않아, 전량 크롤 한 번에
# 일부 레코드가 누락되는 일이 실제로 발생한다(같은 데이터로 두 번 돌리면
# 완제 쪽에서 약 1,100건이 빠졌다가 다른 1,100건이 새로 들어온다).
# 그대로 두면 매달 허위 '취하' 알림이 쏟아지므로, 취하로 표시하기 전에
# 대상 건을 개별 조회해 실제로 사라졌는지 확인한다.
# ---------------------------------------------------------------------------
async def _lookup_many(
    service_key: str,
    base: str,
    operation: str,
    param_name: str,
    values: Sequence[str],
    progress_cb: ProgressCb | None = None,
) -> dict[str, list[dict[str, Any]]]:
    timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=20.0)
    limits = httpx.Limits(max_connections=MAX_CONCURRENCY)
    out: dict[str, list[dict[str, Any]]] = {}
    done = 0
    total = len(values)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

        async def one(value: str) -> tuple[str, list[dict[str, Any]]]:
            nonlocal done
            url = _build_url(
                base, operation, service_key,
                {"type": "json", "pageNo": 1, "numOfRows": 100, param_name: value},
            )
            try:
                body = await _fetch_page(client, url, sem)
                items = list(body.get("items") or [])
            except OpenApiError:
                raise
            except Exception:
                # 개별 조회 실패는 "사라졌다"는 근거가 못 되므로 빈 결과 대신 None 취급
                items = []
            done += 1
            if progress_cb and done % 25 == 0:
                progress_cb(done, total, f"취하 후보 검증 {done}/{total}")
            return value, items

        for value, items in await asyncio.gather(*(one(v) for v in values)):
            out[value] = items
    return out


def fetch_finished_by_item_seq(
    service_key: str, item_seqs: Sequence[str], progress_cb: ProgressCb | None = None
) -> dict[str, list[dict[str, Any]]]:
    """품목기준코드별 완제 허가정보를 개별 조회한다."""
    return asyncio.run(
        _lookup_many(service_key, DRUG_BASE_URL, DRUG_OPERATION, "item_seq",
                     list(item_seqs), progress_cb)
    )


def confirm_missing_finished(
    service_key: str, item_seqs: Sequence[str], progress_cb: ProgressCb | None = None
) -> set[str]:
    """개별 조회에서도 응답이 없는 품목만 '실제 삭제'로 확정한다."""
    if not item_seqs:
        return set()
    found = fetch_finished_by_item_seq(service_key, item_seqs, progress_cb)
    return {seq for seq, items in found.items() if not items}


def confirm_missing_dmf(
    service_key: str,
    candidates: dict[str, str],
    progress_cb: ProgressCb | None = None,
) -> set[str]:
    """DMF 취하 후보를 성분명으로 재조회해 확정한다.

    Args:
        candidates: {dmf_id: 성분명(국문)}. DMF API 는 등록번호 단건 조회를 지원하지
            않으므로 성분명으로 조회한 뒤 등록번호가 목록에 있는지 확인한다.
    """
    if not candidates:
        return set()
    by_name: dict[str, list[str]] = {}
    for dmf_id, name in candidates.items():
        if name:
            by_name.setdefault(name, []).append(dmf_id)
    if not by_name:
        return set()

    found = asyncio.run(
        _lookup_many(service_key, DMF_BASE_URL, DMF_OPERATION, "ingr_kor_name",
                     list(by_name), progress_cb)
    )
    confirmed: set[str] = set()
    for name, ids in by_name.items():
        items = found.get(name) or []
        if not items:
            # 조회 자체가 비었으면 판단 근거가 약하므로 취하로 보지 않는다.
            continue
        alive = {str(i.get("DMF_PERMIT_NO") or "") for i in items}
        confirmed.update(i for i in ids if i not in alive)
    return confirmed


def verify_service_key(service_key: str) -> tuple[bool, str]:
    """인증키 유효성을 두 서비스 모두에 대해 확인한다."""
    async def run() -> tuple[bool, str]:
        timeout = httpx.Timeout(30.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            sem = asyncio.Semaphore(2)
            msgs: list[str] = []
            ok = True
            targets: Iterable[tuple[str, str, str]] = (
                ("DMF", DMF_BASE_URL, DMF_OPERATION),
                ("완제의약품", DRUG_BASE_URL, DRUG_OPERATION),
            )
            for name, base, op in targets:
                url = _build_url(base, op, service_key, {"type": "json", "pageNo": 1, "numOfRows": 1})
                try:
                    body = await _fetch_page(client, url, sem)
                    msgs.append(f"{name}: 정상 (총 {int(body.get('totalCount') or 0):,}건)")
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    msgs.append(f"{name}: 실패 - {exc}")
            return ok, " / ".join(msgs)

    return asyncio.run(run())
