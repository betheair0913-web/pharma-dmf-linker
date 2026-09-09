"""페이지 공용 유틸: 캐시 래퍼, 사이드바 필터, 공통 위젯."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from core import mapping
from core.db import connect
from core.mapping import MappingFilter


# ---------------------------------------------------------------------------
# 데이터 버전 - 수집이 끝날 때마다 값이 바뀌어 캐시를 자연스럽게 무효화한다.
# ---------------------------------------------------------------------------
def data_version() -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(run_id), 0) AS r, COALESCE(MAX(finished_at), '') AS t FROM sync_run"
        ).fetchone()
    return f"{row['r']}|{row['t']}"


@st.cache_data(show_spinner=False)
def cached_kpi(version: str, snapshot: str | None) -> dict[str, Any]:
    return mapping.kpi_snapshot(snapshot)


@st.cache_data(show_spinner="매핑 결과를 계산하는 중…")
def cached_mapping(version: str, payload: dict[str, Any]) -> tuple[pd.DataFrame, int]:
    return mapping.build_mapping(MappingFilter(**payload))


@st.cache_data(show_spinner=False)
def cached_stats(version: str, payload: dict[str, Any]) -> dict[str, Any]:
    return mapping.mapping_stats(MappingFilter(**payload))


@st.cache_data(show_spinner=False)
def cached_summary(version: str, payload: dict[str, Any]) -> pd.DataFrame:
    return mapping.summarize_by_ingredient(MappingFilter(**payload))


@st.cache_data(show_spinner=False)
def cached_countries(version: str) -> list[str]:
    return mapping.distinct_countries(active_only=False)


@st.cache_data(show_spinner=False)
def cached_companies(version: str) -> list[str]:
    return mapping.distinct_values("finished_drug_master", "company_name", active_only=False)


@st.cache_data(show_spinner=False)
def cached_manufacturers(version: str) -> list[str]:
    return mapping.distinct_values("dmf_master", "manufacturer_name", active_only=False)


@st.cache_data(show_spinner=False)
def cached_country_breakdown(version: str, active_only: bool) -> pd.DataFrame:
    return mapping.country_breakdown(active_only)


@st.cache_data(show_spinner=False)
def cached_snapshots(version: str) -> list[str]:
    return mapping.available_snapshots()


@st.cache_data(show_spinner=False)
def cached_change_log(
    version: str, snapshot: str | None, targets: tuple[str, ...], changes: tuple[str, ...]
) -> pd.DataFrame:
    return mapping.change_log_frame(snapshot, list(targets) or None, list(changes) or None)


# ---------------------------------------------------------------------------
# 공통 위젯
# ---------------------------------------------------------------------------
def require_data() -> bool:
    """데이터가 비어 있으면 안내를 띄우고 False 를 돌려준다."""
    from core.db import table_count

    if table_count("dmf_master") == 0 or table_count("finished_drug_master") == 0:
        st.info(
            "아직 수집된 데이터가 없습니다. 좌측 메뉴의 **⚙️ 데이터 동기화**에서 "
            "인증키를 저장하고 **전체 수집(Full Sync)** 을 먼저 실행하세요.",
            icon="📥",
        )
        return False
    return True


def matching_names(options: list[str], query: str) -> list[str]:
    """이름 검색어에 걸리는 업체 목록. 사이드바 미리보기용."""
    tokens = mapping.name_tokens(query)
    if not tokens:
        return []
    return [n for n in options if all(t in n.lower() for t in tokens)]


def _match_preview(sb, label: str, options: list[str], query: str) -> None:
    """입력한 이름에 몇 곳이 걸렸는지 즉시 보여준다."""
    if not query.strip():
        return
    matched = matching_names(options, query)
    if not matched:
        sb.caption(f"⚠️ 일치하는 {label}가 없습니다. 결과가 비게 됩니다.")
        return
    sb.caption(f"✅ {label} {len(matched)}곳 일치")
    with sb.expander(f"일치한 {label} {len(matched)}곳 보기"):
        for name in matched[:50]:
            st.write(f"· {name}")
        if len(matched) > 50:
            st.caption(f"… 외 {len(matched) - 50}곳")


def reset_filters(key_prefix: str) -> None:
    """해당 페이지 필터 위젯의 입력값을 모두 지운다.

    세션 상태에서 키를 지우기만 하면 값은 기본값으로 돌아가지만 입력창에 찍힌
    글자가 화면에 그대로 남는다. 그래서 위젯 키에 붙는 일련번호(nonce)를 올려
    Streamlit 이 아예 새 위젯으로 다시 그리게 한다.
    """
    keep = {f"{key_prefix}_reset", f"{key_prefix}_nonce"}
    for k in [k for k in st.session_state if k.startswith(key_prefix) and k not in keep]:
        del st.session_state[k]
    st.session_state[f"{key_prefix}_nonce"] = st.session_state.get(f"{key_prefix}_nonce", 0) + 1


def sidebar_filters(version: str, key_prefix: str = "f") -> MappingFilter:
    """PRD 5.1 필터 컨트롤 바. 반환값은 그대로 MappingFilter 로 쓴다."""
    sb = st.sidebar
    nonce = st.session_state.get(f"{key_prefix}_nonce", 0)

    def k(name: str) -> str:
        """초기화할 때마다 달라지는 위젯 키."""
        return f"{key_prefix}{nonce}_{name}"

    head, action = sb.columns([1, 1], vertical_alignment="bottom")
    head.markdown("### 🔎 필터")
    if action.button(
        "초기화",
        key=f"{key_prefix}_reset",
        use_container_width=True,
        help="입력한 검색어·업체·국가·기간 등 필터를 모두 지우고 기본값으로 되돌립니다.",
    ):
        reset_filters(key_prefix)
        st.rerun()

    keyword = sb.text_input(
        "통합 검색",
        key=k("kw"),
        placeholder='예: anhui poly   /   "anhui poly"   /   인도 | 중국',
        help=(
            "**공백 = AND** — `anhui poly` 는 두 단어가 모두 걸리는 행만 찾습니다.\n\n"
            '**따옴표** — `"anhui poly"` 는 연속된 문자열 그대로 찾습니다.\n\n'
            "**세로줄 = OR** — `인도 | 중국` 은 둘 중 하나면 됩니다.\n\n"
            "국문·영문 모두 검색되며, 대소문자는 구분하지 않습니다."
        ),
    )
    search_fields = sb.multiselect(
        "검색 대상",
        options=list(mapping.SEARCH_FIELDS),
        key=k("sf"),
        placeholder="전체 항목에서 검색",
        help="특정 항목만 지정하면 다른 항목에 우연히 걸리는 결과를 배제할 수 있습니다. "
             "예: '원료 제조소'만 선택하고 anhui 검색.",
    )

    # 업체는 이름을 정확히 골라야 하는 경우가 많아 접어두지 않고 바로 노출한다.
    # 목록이 길어도 입력창에 몇 글자만 치면 후보가 좁혀진다.
    sb.markdown("**업체 지정**")

    all_manufacturers = cached_manufacturers(version)
    manufacturer_query = sb.text_input(
        "원료 제조소 이름",
        key=k("mfrq"),
        placeholder="예: zhejiang hongyuan",
        help=(
            "이름 일부만 입력하면 **하나씩 고르지 않아도 바로 조회**됩니다.\n\n"
            "공백으로 띄운 단어는 **모두 포함**된 제조소만 걸립니다. "
            "같은 회사가 `Co., Ltd.` / `Co.,Ltd.` 처럼 표기만 달라도 한 번에 잡히고, "
            "대소문자는 구분하지 않습니다."
        ),
    )
    _match_preview(sb, "제조소", all_manufacturers, manufacturer_query)

    manufacturers = sb.multiselect(
        "원료 제조소 직접 선택", options=all_manufacturers, key=k("mfr"),
        placeholder="표기까지 정확히 지정할 때만 사용",
        help="여기서 고른 값은 정확히 그 표기만 매칭합니다. "
             "위 이름 검색과 함께 쓰면 **둘 중 하나라도** 해당하는 제조소가 나옵니다.",
    )

    all_companies = cached_companies(version)
    company_query = sb.text_input(
        "완제 제약사 이름",
        key=k("compq"),
        placeholder="예: 한미약품",
        help=(
            "이름 일부만 입력하면 **하나씩 고르지 않아도 바로 조회**됩니다.\n\n"
            "공백으로 띄운 단어는 **모두 포함**된 제약사만 걸립니다. "
            "`(주)한미약품` / `한미약품(주)` 처럼 표기만 달라도 한 번에 잡히고, "
            "대소문자는 구분하지 않습니다."
        ),
    )
    _match_preview(sb, "제약사", all_companies, company_query)

    companies = sb.multiselect(
        "완제 제약사 직접 선택", options=all_companies, key=k("comp"),
        placeholder="표기까지 정확히 지정할 때만 사용",
        help="여기서 고른 값은 정확히 그 표기만 매칭합니다. "
             "위 이름 검색과 함께 쓰면 **둘 중 하나라도** 해당하는 제약사가 나옵니다.",
    )

    sb.markdown("**상태 필터**")
    dmf_active = sb.checkbox("DMF 유효만 보기", value=True, key=k("da"))
    fin_active = sb.checkbox("완제 허가품목(정상)만 보기", value=True, key=k("fa"))
    if not dmf_active or not fin_active:
        sb.caption("⚠️ 취하·만료 품목이 결과에 포함됩니다.")

    sb.markdown("**제조국**")
    scope = sb.radio(
        "제조 구분",
        options=["전체", "국내", "해외"],
        index=0,
        horizontal=True,
        key=k("scope"),
        label_visibility="collapsed",
    )
    countries = sb.multiselect(
        "국가 선택 (다중)", options=cached_countries(version), key=k("ctry"),
        placeholder="전체 국가",
    )

    # --- 이하는 자주 손대지 않는 항목 ---------------------------------------
    sb.divider()

    match_mode = sb.radio(
        "성분 매칭 방식",
        options=["BASE", "EXACT"],
        index=0,
        horizontal=True,
        key=k("mm"),
        format_func=lambda v: "골격 일치(권장)" if v == "BASE" else "염 표기까지 일치",
        help=(
            "**위의 검색어와는 무관합니다.** DMF 원료와 완제 주성분을 서로 연결할 때 "
            "성분명을 어느 수준까지 같다고 볼지 정하는 옵션입니다.\n\n"
            "- **골격 일치**: 염·수화물 표기를 떼고 유효성분 기준으로 연결 "
            "(암로디핀베실산염 ↔ 암로디핀캄실산염)\n"
            "- **염 표기까지 일치**: 염 표기가 완전히 같은 경우만 연결"
        ),
    )

    with sb.expander("기간 필터"):
        use_dmf_date = st.checkbox("DMF 등록일 범위", key=k("udd"))
        dmf_range = st.date_input(
            "DMF 등록일", value=(date(2000, 1, 1), date.today()),
            key=k("dd"), disabled=not use_dmf_date, label_visibility="collapsed",
        )
        use_permit_date = st.checkbox("완제 허가일 범위", key=k("upd"))
        permit_range = st.date_input(
            "완제 허가일", value=(date(2000, 1, 1), date.today()),
            key=k("pd"), disabled=not use_permit_date, label_visibility="collapsed",
        )

    snapshots = cached_snapshots(version)
    with sb.expander("변동사항 필터"):
        snapshot = st.selectbox(
            "기준 스냅샷", options=snapshots or ["(없음)"], index=0, key=k("snap")
        )
        change_types = st.multiselect(
            "변동 유형", options=["NEW", "MODIFIED", "CANCELLED"], key=k("ct"),
            placeholder="전체",
        )

    def _range(flag: bool, value: Any) -> tuple[str | None, str | None]:
        if not flag or not isinstance(value, (tuple, list)) or len(value) != 2:
            return None, None
        return value[0].isoformat(), value[1].isoformat()

    dmf_from, dmf_to = _range(use_dmf_date, dmf_range)
    permit_from, permit_to = _range(use_permit_date, permit_range)

    return MappingFilter(
        keyword=keyword,
        search_fields=search_fields,
        match_mode=match_mode,
        dmf_active_only=dmf_active,
        finished_active_only=fin_active,
        countries=countries,
        country_scope=scope,
        companies=companies,
        company_query=company_query,
        manufacturers=manufacturers,
        manufacturer_query=manufacturer_query,
        dmf_date_from=dmf_from,
        dmf_date_to=dmf_to,
        permit_date_from=permit_from,
        permit_date_to=permit_to,
        change_types=change_types,
        change_snapshot=None if snapshot == "(없음)" else snapshot,
    )


def filter_payload(f: MappingFilter, row_limit: int) -> dict[str, Any]:
    """MappingFilter 를 캐시 키로 쓸 수 있는 해시 가능 dict 로 변환."""
    d = f.__dict__.copy()
    d["row_limit"] = row_limit
    for k in ("countries", "companies", "manufacturers", "change_types", "search_fields"):
        d[k] = list(d[k])
    return d
