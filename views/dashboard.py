"""종합 현황: KPI 카드 + 공급망 분포 + 최근 수집 이력."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from core.export import to_csv_bytes
from core.mapping import MappingFilter
from core.sync import sync_history
from views import _theme as T
from views._shared import (
    cached_country_breakdown,
    cached_kpi,
    cached_snapshots,
    cached_summary,
    data_version,
    filter_payload,
    require_data,
)

T.inject()

# 단일 계열(크기 비교) 차트이므로 색은 한 가지만 쓴다. 범례 없이 직접 라벨로 읽힌다.
BAR = T.PRIMARY
GRID_INK = "#eaedf2"
AXIS_INK = "#8b94a6"

version = data_version()
snapshots = cached_snapshots(version)
options = snapshots or ["(없음)"]

# 헤더 칩이 KPI 값을 쓰므로, 셀렉트박스보다 먼저 값을 알아야 한다.
# 위젯 key 는 리런 사이에 유지되므로 session_state 에서 현재 선택을 읽어 온다.
picked = st.session_state.get("dash_snap_pick", options[0])
snapshot = None if picked == "(없음)" else picked

has_data = require_data()
kpi = cached_kpi(version, snapshot) if has_data else None

chips: list[str] = []
if kpi:
    chips = [
        T.chip(f"스냅샷 <b>{kpi['snapshot'] or '-'}</b>", icon="clock"),
        T.chip(f"DMF <b>{kpi['active_dmf']:,}</b> · 완제 <b>{kpi['finished_items']:,}</b>",
               icon="database"),
    ]
    if kpi["last_run"]:
        chips.append(
            T.chip(f"최근 수집 {kpi['last_run']['finished_at'][:16].replace('T', ' ')}",
                   icon="refresh")
        )

T.page_header("grid", "종합 현황", "DMF 원료 ↔ 완제의약품 공급망을 한 화면에서 확인합니다", chips)

if not has_data:
    st.stop()

pick_col, _rest = st.columns([1, 4])
pick_col.selectbox(
    "기준 스냅샷", options=options, key="dash_snap_pick",
    help="KPI의 '당월 신규/변경' 집계 기준이 되는 수집 회차입니다.",
)

# ---------------------------------------------------------------------------
# KPI 카드
# ---------------------------------------------------------------------------
T.kpi_row([
    T.kpi_card(
        "활성 DMF 등록", f"{kpi['active_dmf']:,}", "건",
        caption=f"전체 등록 {kpi['total_dmf']:,}건",
        badge=f"↑ 당월 신규 {kpi['new_dmf']:,}건" if kpi["new_dmf"] else "당월 신규 없음",
        badge_kind="up" if kpi["new_dmf"] else "flat",
        tile="blue", icon="flask", tone="primary",
    ),
    T.kpi_card(
        "연계 완제 제약사", f"{kpi['linked_companies']:,}", "개사",
        caption="DMF 원료와 주성분 골격이 일치하는 허가 품목 보유사",
        tile="violet", icon="building",
    ),
    T.kpi_card(
        "해외 제조소 비율", f"{kpi['overseas_ratio']:.1f}", "%",
        caption=f"해외 {kpi['overseas_dmf']:,} / 활성 {kpi['active_dmf']:,}건",
        tile="red", icon="globe", tone="danger",
    ),
    T.kpi_card(
        "원료 제조국", f"{kpi['countries']:,}", "개국",
        caption=f"완제 허가품목 {kpi['finished_items']:,}건과 연계",
        tile="teal", icon="factory",
    ),
])

st.write("")

T.kpi_row([
    T.kpi_card(
        "당월 신규 DMF", f"{kpi['new_dmf']:,}", "건",
        caption="이번 스냅샷에서 새로 확인된 원료 등록",
        tile="blue", icon="trend", tone="primary",
    ),
    T.kpi_card(
        "당월 신규 완제 품목", f"{kpi['new_finished']:,}", "건",
        caption="이번 스냅샷에서 새로 확인된 허가 품목",
        tile="green", icon="box", tone="success",
    ),
    T.kpi_card(
        "당월 변경 건", f"{kpi['modified']:,}", "건",
        caption="제조소·주소·상태 등 추적 필드 변경",
        tile="amber", icon="refresh", tone="amber" if kpi["modified"] else "default",
    ),
    T.kpi_card(
        "당월 취하 · 만료", f"{kpi['cancelled']:,}", "건",
        caption="개별 재조회로 삭제가 확인된 건만 집계",
        tile="red", icon="alert", tone="danger" if kpi["cancelled"] else "default",
    ),
])

st.write("")

# ---------------------------------------------------------------------------
# 분포 차트 (크기 비교 -> 가로 막대, 단일 색, 직접 라벨)
# ---------------------------------------------------------------------------
summary = cached_summary(version, filter_payload(MappingFilter(), row_limit=400_000))

left, right = st.columns(2, gap="medium")


def _bar(df: pd.DataFrame, cat: str, val: str, tooltip: list[str] | None = None):
    base = alt.Chart(df).encode(
        y=alt.Y(f"{cat}:N", sort="-x", title=None,
                axis=alt.Axis(labelColor=AXIS_INK, labelFontSize=11, domain=False,
                              ticks=False, labelLimit=170)),
        x=alt.X(f"{val}:Q", title=None,
                axis=alt.Axis(grid=True, gridColor=GRID_INK, labelColor=AXIS_INK,
                              labelFontSize=10, domain=False, ticks=False)),
        **({"tooltip": tooltip} if tooltip else {}),
    )
    return (
        (
            base.mark_bar(color=BAR, cornerRadiusTopRight=4, cornerRadiusBottomRight=4, height=13)
            + base.mark_text(align="left", dx=6, color=AXIS_INK, fontSize=10.5).encode(
                text=alt.Text(f"{val}:Q", format=",")
            )
        )
        # 막대 끝 값 라벨이 카드 테두리에 닿지 않도록 오른쪽 여백을 둔다.
        .properties(height=340, padding={"left": 0, "top": 4, "right": 34, "bottom": 0})
        .configure_view(stroke=None)
    )


with left:
    with st.container(border=True):
        T.card_header("globe", "원료 제조국 분포",
                      "활성 DMF 기준 상위 12개국입니다. 복수 국가 표기는 국가별로 나눠 집계합니다.",
                      tile="teal")
        cb = cached_country_breakdown(version, True)
        if cb.empty:
            st.info("표시할 데이터가 없습니다.")
        else:
            st.altair_chart(_bar(cb.head(12), "제조국", "DMF 건수"), use_container_width=True)
            with st.expander("국가별 전체 표 보기"):
                st.dataframe(cb, use_container_width=True, hide_index=True)

with right:
    with st.container(border=True):
        T.card_header("trend", "성분별 공급망 규모",
                      "연계 완제 품목 수 기준 상위 15개 유효성분입니다. 염 표기가 다른 성분은 하나로 묶었습니다.",
                      tile="blue")
        if summary.empty:
            st.info("표시할 데이터가 없습니다.")
        else:
            st.altair_chart(
                _bar(summary.head(15), "성분명(대표)", "완제 품목 수",
                     ["성분명(대표)", "DMF 건수", "원료 제조소 수", "제조국 수",
                      "완제 제약사 수", "완제 품목 수"]),
                use_container_width=True,
            )

st.write("")

# ---------------------------------------------------------------------------
# 성분 단위 요약
# ---------------------------------------------------------------------------
with st.container(border=True):
    T.card_header("flask", "성분 단위 요약",
                  "공급 다변화 점검용 — 한 성분에 원료 제조소가 1곳뿐이면 단일 소스 리스크 신호입니다.",
                  tile="violet")
    if summary.empty:
        st.info("표시할 데이터가 없습니다.")
    else:
        c1, c2 = st.columns([3, 1])
        with c1:
            only_single = st.checkbox("원료 제조소가 1곳뿐인 성분만 보기", value=False)
        view = summary[summary["원료 제조소 수"] == 1] if only_single else summary
        with c2:
            st.download_button(
                "성분 요약 CSV", data=to_csv_bytes(view),
                file_name="성분요약.csv", mime="text/csv", use_container_width=True,
            )
        st.dataframe(view, use_container_width=True, hide_index=True, height=360)

st.write("")

# ---------------------------------------------------------------------------
# 최근 수집 이력
# ---------------------------------------------------------------------------
with st.container(border=True):
    T.card_header("history", "최근 수집 이력", "회차별 수집 규모와 감지된 변경 건수입니다.", tile="slate")
    runs = sync_history(10)
    if runs:
        rdf = pd.DataFrame(runs)[
            ["run_id", "snapshot_ym", "sync_type", "target", "started_at", "finished_at",
             "status", "dmf_rows", "finished_rows", "new_cnt", "mod_cnt", "cancel_cnt", "message"]
        ].rename(
            columns={
                "run_id": "회차", "snapshot_ym": "스냅샷", "sync_type": "유형", "target": "대상",
                "started_at": "시작", "finished_at": "종료", "status": "상태",
                "dmf_rows": "DMF행", "finished_rows": "완제행", "new_cnt": "신규",
                "mod_cnt": "변경", "cancel_cnt": "취하", "message": "메시지",
            }
        )
        st.dataframe(rdf, use_container_width=True, hide_index=True)
    else:
        st.info("수집 이력이 없습니다.")
