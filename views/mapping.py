"""상세 조회: 통합 매핑 그리드 + 컬럼 제어 + 페이지네이션 + CSV 내보내기."""

from __future__ import annotations

import math

import streamlit as st

from core.export import save_csv, to_csv_bytes
from views import _theme as T
from views._shared import (
    cached_mapping,
    cached_stats,
    data_version,
    filter_payload,
    require_data,
    sidebar_filters,
)

# 기본 표시 컬럼 (나머지는 컬럼 선택기에서 켤 수 있다)
DEFAULT_COLUMNS = [
    "DMF등록번호", "성분명(국문)", "성분명(영문)", "원료 제조소", "제조국",
    "완제 제약사", "완제품명", "품목 상태", "DMF 상태", "매칭레벨", "DMF 변동", "완제 변동",
]
PAGE_SIZES = [100, 500, 1000]
# 화면 그리드용 상한. 무필터 전량 조인은 130만 행이라 그대로 끌어오면 첫 화면이 느려진다.
# 사용자는 어차피 100~1000행씩 넘겨 보므로, 미리보기는 이 정도면 충분하고
# 전체가 필요하면 아래 '전체 결과셋 CSV'로 내려받는다.
GRID_LIMIT = 50_000
EXPORT_LIMIT = 1_000_000  # CSV 내보내기 상한

T.inject()

version = data_version()
has_data = require_data()

T.page_header("link", "상세 조회",
              "정규화된 성분 키로 DMF 원료와 완제의약품을 교차 결합한 결과입니다")

if not has_data:
    st.stop()

flt = sidebar_filters(version, key_prefix="map")
payload = filter_payload(flt, GRID_LIMIT)
stats = cached_stats(version, payload)
df, total = cached_mapping(version, payload)

if df.empty:
    st.warning("조건에 맞는 결과가 없습니다. 필터를 완화해 보세요.", icon="🔍")
    st.stop()

# --- 요약 지표 (화면에 잘린 미리보기가 아니라 필터 결과 전체 기준) -----------
T.kpi_row([
    T.kpi_card("매핑 레코드", f"{stats['rows']:,}", "건",
               caption="현재 필터의 원료 x 완제 조합 수",
               tile="blue", icon="link", tone="primary"),
    T.kpi_card("유효성분", f"{stats['ingredients']:,}", "종",
               caption="염 표기가 다른 성분은 하나로 집계",
               tile="violet", icon="flask"),
    T.kpi_card("DMF 등록", f"{stats['dmf_ids']:,}", "건",
               caption=f"연계 완제 품목 {stats['products']:,}건",
               tile="teal", icon="database"),
    T.kpi_card("원료 제조소", f"{stats['manufacturers']:,}", "곳",
               caption="중복 제거 기준", tile="amber", icon="factory"),
    T.kpi_card("완제 제약사", f"{stats['companies']:,}", "개사",
               caption="제조 · 수입사 합계", tile="green", icon="building"),
])

st.write("")

if total > len(df):
    st.info(
        f"결과가 {total:,}건이라 화면에는 상위 {len(df):,}건만 불러왔습니다. "
        "위 지표는 잘린 미리보기가 아니라 **필터 결과 전체** 기준입니다. "
        "전체 행이 필요하면 아래 CSV로 내려받으세요.",
        icon="ℹ️",
    )

# --- 그리드 카드 -------------------------------------------------------------
with st.container(border=True):
    T.card_header(
        "grid", "통합 매핑 그리드",
        f"매칭 구성 — EXACT(염 표기까지 일치) {stats['exact_ratio']:.1f}% · "
        f"BASE(유효성분 골격만 일치) {100 - stats['exact_ratio']:.1f}%",
    )

    ctrl1, ctrl2, ctrl3 = st.columns([3, 1, 1])
    with ctrl1:
        columns = st.multiselect(
            "표시 컬럼",
            options=list(df.columns),
            default=[c for c in DEFAULT_COLUMNS if c in df.columns],
        )
    with ctrl2:
        sort_col = st.selectbox("정렬 기준", options=columns or list(df.columns), index=0)
    with ctrl3:
        sort_desc = st.toggle("내림차순", value=False)

    if not columns:
        columns = [c for c in DEFAULT_COLUMNS if c in df.columns]

    view = df[columns].sort_values(sort_col, ascending=not sort_desc, kind="stable")

    p1, p2, p3 = st.columns([1, 1, 4])
    with p1:
        page_size = st.selectbox("페이지당 행", options=PAGE_SIZES, index=0)
    total_pages = max(1, math.ceil(len(view) / page_size))
    with p2:
        page = st.number_input("페이지", min_value=1, max_value=total_pages, value=1, step=1)
    with p3:
        st.write("")
        st.caption(f"{page:,} / {total_pages:,} 페이지 · 필터 결과 {len(view):,}행")

    start = (page - 1) * page_size
    st.dataframe(
        view.iloc[start : start + page_size],
        use_container_width=True,
        hide_index=True,
        height=560,
    )

st.write("")

# --- 내보내기 ---------------------------------------------------------------
with st.container(border=True):
    T.card_header("download", "내보내기",
                  "엑셀에서 한글이 깨지지 않도록 UTF-8 BOM(utf-8-sig)으로 인코딩합니다.",
                  tile="green")

    e1, e2, e3 = st.columns([1, 1, 2])
    with e1:
        st.download_button(
            "현재 화면(필터+컬럼) CSV",
            data=to_csv_bytes(view),
            file_name="DMF_완제_매핑_현재필터.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with e2:
        if st.button("전체 결과셋 CSV 생성", use_container_width=True,
                     help="화면 상한과 무관하게 현재 필터의 전체 결과를 내려받습니다."):
            full, _ = cached_mapping(version, filter_payload(flt, EXPORT_LIMIT))
            st.session_state["export_full"] = full[columns]
            st.session_state["export_path"] = str(save_csv(full[columns], "DMF_완제_매핑_전체"))

    if "export_full" in st.session_state:
        st.download_button(
            f"전체 결과 CSV 다운로드 ({len(st.session_state['export_full']):,}행)",
            data=to_csv_bytes(st.session_state["export_full"]),
            file_name="DMF_완제_매핑_전체.csv",
            mime="text/csv",
        )
        st.caption(f"로컬 사본: `{st.session_state['export_path']}`")
