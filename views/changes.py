"""변경 이력: 월별 NEW / MODIFIED / CANCELLED 조회 및 변경분 덤프."""

from __future__ import annotations

import streamlit as st

from core.export import save_csv, to_csv_bytes
from views import _theme as T
from views._shared import cached_change_log, cached_snapshots, data_version

CHANGE_LABEL = {
    "NEW": "신규",
    "MODIFIED": "변경",
    "CANCELLED": "취하·만료",
}
TARGET_LABEL = {"DMF": "원료(DMF)", "FINISHED": "완제의약품"}

# (아이콘, 타일색, 수치색) — 변경 유형별 시각 톤
CHANGE_STYLE = {
    "NEW": ("trend", "green", "success"),
    "MODIFIED": ("refresh", "amber", "amber"),
    "CANCELLED": ("alert", "red", "danger"),
}
TARGET_ICON = {"DMF": "flask", "FINISHED": "box"}

T.inject()

version = data_version()
snapshots = cached_snapshots(version)

T.page_header(
    "clock", "변경 이력",
    "수집 회차마다 마스터와 비교해 감지한 차분입니다",
    [T.chip(f"스냅샷 <b>{len(snapshots)}</b>개 축적", icon="database")] if snapshots else [],
)

st.caption(
    "DMF는 API가 상태 필드를 제공하지 않아, 이번 회차 목록에서 사라진 뒤 "
    "개별 재조회로 삭제가 확인된 건만 취하·만료로 판정합니다."
)

if not snapshots:
    st.info(
        "아직 변경 이력이 없습니다. **데이터 동기화**에서 수집을 실행하세요. "
        "최초 수집은 전 건이 '신규'로 기록되고, 두 번째 회차부터 실제 증분이 잡힙니다.",
        icon="📥",
    )
    st.stop()

with st.container(border=True):
    T.card_header("sliders", "조회 조건", "스냅샷과 대상, 변경 유형을 골라 좁혀 봅니다.", tile="slate")
    f1, f2, f3 = st.columns([1, 2, 2])
    with f1:
        snapshot = st.selectbox("스냅샷", options=snapshots, index=0)
    with f2:
        targets = st.multiselect(
            "대상", options=["DMF", "FINISHED"], default=["DMF", "FINISHED"],
            format_func=lambda v: TARGET_LABEL[v],
        )
    with f3:
        changes = st.multiselect(
            "변경 유형", options=["NEW", "MODIFIED", "CANCELLED"],
            default=["NEW", "MODIFIED", "CANCELLED"],
            format_func=lambda v: CHANGE_LABEL[v],
        )

log = cached_change_log(version, snapshot, tuple(targets), tuple(changes))

if log.empty:
    st.warning("해당 조건의 변경 이력이 없습니다.", icon="🔍")
    st.stop()

# --- 요약 KPI ---------------------------------------------------------------
st.write("")
counts = log.groupby(["구분", "변경유형"])["대상 ID"].nunique().unstack(fill_value=0)
cards: list[str] = []
for tgt, tlabel in TARGET_LABEL.items():
    for ct, clabel in CHANGE_LABEL.items():
        value = int(counts.loc[tgt, ct]) if (tgt in counts.index and ct in counts.columns) else 0
        icon, tile, tone = CHANGE_STYLE[ct]
        cards.append(
            T.kpi_card(
                f"{tlabel} · {clabel}", f"{value:,}", "건",
                caption=f"{snapshot} 스냅샷 기준",
                tile=tile if value else "slate",
                icon=icon,
                tone=tone if value else "default",
            )
        )
T.kpi_row(cards[:3])
st.write("")
T.kpi_row(cards[3:])

st.write("")

# --- 표 ---------------------------------------------------------------------
display = log.copy()
display["구분"] = display["구분"].map(TARGET_LABEL).fillna(display["구분"])
display["변경유형"] = display["변경유형"].map(CHANGE_LABEL).fillna(display["변경유형"])

with st.container(border=True):
    T.card_header(
        "history", "변경 로그",
        f"총 {len(log):,}개 행 — 변경 1건이 여러 필드에 걸치면 필드 수만큼 행이 생깁니다.",
    )
    st.dataframe(display, use_container_width=True, hide_index=True, height=520)

st.write("")

# --- 덤프 -------------------------------------------------------------------
with st.container(border=True):
    T.card_header("download", "월별 변경분 덤프",
                  f"선택한 스냅샷({snapshot})의 신규·변경·취하 내역만 별도 CSV로 추출합니다.",
                  tile="green")
    d1, d2 = st.columns([1, 3])
    with d1:
        st.download_button(
            "변경분 CSV 다운로드",
            data=to_csv_bytes(display),
            file_name=f"변경분_{snapshot}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with d2:
        if st.button("로컬 exports 폴더에 저장"):
            path = save_csv(display, f"변경분_{snapshot}")
            st.success(f"저장 완료: `{path}`")
