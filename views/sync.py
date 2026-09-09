"""데이터 동기화: 인증키 설정 + 전체/증분 수집 실행 + 수집 이력."""

from __future__ import annotations

import time
from datetime import date

import pandas as pd
import streamlit as st

from core import collector, config
from core.db import table_count
from core.ingest import current_snapshot_ym
from core.sync import run_sync, sync_history
from views import _theme as T

T.inject()

saved_key = config.get_service_key()

T.page_header(
    "sliders", "데이터 동기화",
    "식약처 Open API에서 원료·완제 정보를 받아 마스터와 변경 이력을 갱신합니다",
    [
        T.chip("인증키 설정됨" if saved_key else "인증키 미설정",
               kind="" if saved_key else "amber", icon="key"),
        T.chip(f"DMF <b>{table_count('dmf_master'):,}</b>", icon="flask"),
        T.chip(f"완제 <b>{table_count('finished_drug_master'):,}</b>", icon="box"),
    ],
)

# ---------------------------------------------------------------------------
# 1. 인증키
# ---------------------------------------------------------------------------
with st.container(border=True):
    T.card_header(
        "key", "1. 공공데이터포털 인증키",
        "일반 인증키(Encoding)와 Decoding 키 어느 쪽을 넣어도 동작합니다. "
        "저장한 키는 로컬 SQLite(app_setting)에만 보관되며 식약처 API 외부로 전송되지 않습니다.",
        tile="amber",
    )

    if saved_key:
        st.success(f"인증키가 설정되어 있습니다 (…{saved_key[-8:]}).", icon="🔑")
    else:
        st.warning("인증키가 없습니다. 아래에 입력하고 저장하세요.", icon="🔑")

    with st.form("api_key_form"):
        key_input = st.text_input(
            "인증키", value=saved_key, type="password",
            placeholder="공공데이터포털에서 발급받은 인증키",
        )
        kc1, kc2 = st.columns([1, 1])
        save_clicked = kc1.form_submit_button("저장", use_container_width=True, type="primary")
        test_clicked = kc2.form_submit_button("연결 테스트", use_container_width=True)

    if save_clicked:
        config.save_service_key(key_input)
        st.success("인증키를 저장했습니다.")
        st.rerun()

    if test_clicked:
        with st.spinner("두 API에 연결 중…"):
            ok, msg = collector.verify_service_key(key_input or saved_key)
        (st.success if ok else st.error)(msg)

    with st.expander("연결 대상 엔드포인트"):
        st.markdown(
            f"""
| 구분 | 엔드포인트 | 오퍼레이션 | 페이지 크기 |
|---|---|---|---|
| 원료의약품 등록(DMF) | `{config.DMF_BASE_URL}` | `{config.DMF_OPERATION}` | {config.PAGE_SIZE_DMF} |
| 의약품 제품 허가정보 | `{config.DRUG_BASE_URL}` | `{config.DRUG_OPERATION}` | {config.PAGE_SIZE_DRUG} |

동시 요청 수 `{config.MAX_CONCURRENCY}` · 요청 타임아웃 `{config.REQUEST_TIMEOUT:.0f}s` ·
재시도 `{config.MAX_RETRIES}`회(지수 백오프). 429/5xx가 잦으면 `core/config.py`의
`MAX_CONCURRENCY`를 낮추세요.
"""
        )

st.write("")

# ---------------------------------------------------------------------------
# 2. 현재 적재 상태
# ---------------------------------------------------------------------------
T.kpi_row([
    T.kpi_card("DMF 마스터", f"{table_count('dmf_master'):,}", "건",
               caption="원료의약품 등록 현황", tile="blue", icon="flask", tone="primary"),
    T.kpi_card("완제 주성분 행", f"{table_count('finished_drug_master'):,}", "행",
               caption="품목 × 주성분 (복합제는 성분 수만큼)", tile="violet", icon="box"),
    T.kpi_card("변경 로그", f"{table_count('change_history_log'):,}", "행",
               caption="신규 · 변경 · 취하 이력 누적", tile="teal", icon="history"),
])

st.write("")

# ---------------------------------------------------------------------------
# 3. 수집 실행
# ---------------------------------------------------------------------------
with st.container(border=True):
    T.card_header(
        "refresh", "2. 수집 실행",
        "두 API 모두 '변경분만 내려주는' 파라미터가 없어, 증분 수집도 목록은 전량을 "
        "받아오되 마스터와 비교해 달라진 것만 기록합니다.",
    )

    st.info(
        "- **전체 수집(Full Sync)**: 두 소스를 모두 받고, 목록에서 사라진 건을 **취하·만료로 판정**합니다.\n"
        "- **월별 증분 수집(Incremental)**: 선택한 소스만 받고, 취하 판정은 하지 않습니다 "
        "(부분 수집으로 인한 오탐 방지).",
        icon="ℹ️",
    )

    st.warning(
        "**페이징 불안정성 보정** — 이 API들은 `pageNo` 페이징의 정렬이 안정적이지 않아, "
        "전량 크롤 한 번에 레코드가 1~2% 누락됩니다(같은 데이터로 두 번 돌려도 "
        "완제 쪽에서 약 1,100건이 빠졌다 다른 건이 들어옵니다). 보정 없이 두면 "
        "매달 허위 '신규/취하' 알림이 생기므로 기본값을 켠 채로 쓰는 것을 권장합니다.",
        icon="⚠️",
    )

    opt1, opt2, opt3 = st.columns([1, 1, 1])
    with opt1:
        snapshot_ym = st.text_input(
            "스냅샷 라벨 (YYYY-MM)", value=current_snapshot_ym(),
            help="변경 이력이 이 라벨로 기록됩니다. 보통 수집 연월 그대로 둡니다.",
        )
    with opt2:
        targets = st.multiselect(
            "수집 대상", options=["DMF", "FINISHED"], default=["DMF", "FINISHED"],
            format_func=lambda v: "원료(DMF)" if v == "DMF" else "완제의약품",
        )
    with opt3:
        smoke = st.number_input(
            "소스별 최대 페이지 (0=제한 없음)", min_value=0, value=0, step=1,
            help="설정을 시험할 때만 사용하세요. 0이면 전량 수집합니다.",
        )

    o1, o2 = st.columns(2)
    with o1:
        passes = st.select_slider(
            "누락 보정 크롤 횟수", options=[1, 2, 3], value=2,
            help="전량 크롤을 반복해 PK 기준 합집합을 만듭니다. 2회면 누락률이 제곱으로 "
                 "떨어지지만 소요 시간도 배가 됩니다(1회 약 4분).",
        )
    with o2:
        verify = st.toggle(
            "취하 후보 개별 검증", value=True,
            help="목록에서 사라진 건을 개별 조회로 재확인한 뒤에만 취하로 표시합니다. "
                 "끄면 연속 2회 미관측 시 취하로 판정합니다.",
        )

    run1, run2 = st.columns(2)
    full_clicked = run1.button("전체 수집 (Full Sync)", type="primary", use_container_width=True)
    inc_clicked = run2.button("월별 증분 수집 (Incremental)", use_container_width=True)


def _execute(sync_type: str) -> None:
    key = config.get_service_key()
    if not key:
        st.error("인증키를 먼저 저장하세요.")
        return
    if not targets:
        st.error("수집 대상을 하나 이상 선택하세요.")
        return

    bar = st.progress(0, text="수집을 시작합니다…")
    status = st.empty()
    started = time.time()

    def on_progress(done: int, total: int, msg: str) -> None:
        elapsed = time.time() - started
        bar.progress(min(done, 100) / 100, text=f"{msg}　·　경과 {elapsed:,.0f}초")

    try:
        result = run_sync(
            key,
            sync_type=sync_type,
            targets=tuple(targets),
            snapshot_ym=snapshot_ym.strip() or None,
            progress_cb=on_progress,
            max_pages=int(smoke) or None,
            passes=int(passes),
            verify_cancellations=bool(verify),
        )
    except Exception as exc:  # noqa: BLE001 - 화면에 원인을 그대로 보여준다
        bar.empty()
        status.error(f"수집 실패: {exc}")
        return

    bar.progress(1.0, text=f"완료 · 총 {time.time() - started:,.0f}초")
    d = result.get("dmf") or {}
    p = result.get("finished") or {}
    status.success(
        f"**{result['snapshot']}** {sync_type} 수집 완료 "
        f"({time.time() - started:,.0f}초)\n\n"
        f"- 원료(DMF): 수집 {d.get('rows', 0):,}건 · 신규 {d.get('new', 0):,} · "
        f"변경 {d.get('modified', 0):,} · 취하 {d.get('cancelled', 0):,} · "
        f"미확정 미관측 {d.get('missed', 0):,}\n"
        f"- 완제의약품: 주성분 {p.get('rows', 0):,}행 · 신규 {p.get('new', 0):,} · "
        f"변경 {p.get('modified', 0):,} · 취하 {p.get('cancelled', 0):,} · "
        f"미확정 미관측 {p.get('missed', 0):,}\n"
        f"- 영문 성분명이 채워진 DMF: {result.get('enriched_en', 0):,}건"
    )

    # 수집 완전성 리포트 - 페이징 누락이 얼마나 보정됐는지 보여준다.
    rows = []
    for key_name, label in (("dmf_completeness", "원료(DMF)"),
                            ("finished_completeness", "완제의약품")):
        c = result.get(key_name)
        if not c:
            continue
        rows.append({
            "소스": label,
            "API 총건수": f"{c['api_total']:,}",
            "수집 고유건수": f"{c['collected']:,}",
            "1차만으로": f"{c['first_pass_unique']:,}",
            "추가 크롤로 복구": f"{c['recovered_by_extra_pass']:,}",
            "수집률": f"{(c['collected'] / c['api_total'] * 100) if c['api_total'] else 0:.2f}%",
        })
    if rows:
        st.caption("**수집 완전성**")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    cand = result.get("cancel_candidates")
    conf = result.get("cancel_confirmed")
    if cand and conf:
        st.caption(
            f"취하 후보 검증: DMF {cand['dmf']:,}건 중 {conf['dmf']:,}건 확정 · "
            f"완제 {cand['finished']:,}건 중 {conf['finished']:,}건 확정 "
            "(확정되지 않은 건은 페이징 누락으로 보고 취하 처리하지 않았습니다)."
        )
    st.cache_data.clear()


if full_clicked:
    _execute("FULL")
if inc_clicked:
    _execute("INCREMENTAL")

st.write("")

# ---------------------------------------------------------------------------
# 4. 수집 이력
# ---------------------------------------------------------------------------
with st.container(border=True):
    T.card_header("history", "3. 수집 이력", "회차별 수집 규모와 감지된 변경 건수입니다.", tile="slate")
    runs = sync_history(30)
    if runs:
        st.dataframe(
            pd.DataFrame(runs).rename(
                columns={
                    "run_id": "회차", "snapshot_ym": "스냅샷", "sync_type": "유형",
                    "target": "대상", "started_at": "시작", "finished_at": "종료",
                    "status": "상태", "dmf_rows": "DMF행", "finished_rows": "완제행",
                    "new_cnt": "신규", "mod_cnt": "변경", "cancel_cnt": "취하",
                    "message": "메시지",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("아직 수집 이력이 없습니다.")

st.write("")

with st.container(border=True):
    T.card_header("alert", "데이터 초기화",
                  "마스터와 변경 이력을 모두 삭제합니다. 되돌릴 수 없으며, 다음 전체 수집에서 "
                  "모든 레코드가 다시 '신규'로 기록됩니다.", tile="red")
    with st.expander("초기화 실행"):
        confirm = st.text_input("확인을 위해 `RESET` 을 입력하세요", key="reset_confirm")
        if st.button("전체 삭제", disabled=confirm != "RESET"):
            from core.db import connect

            with connect() as conn:
                for t in ("dmf_master", "finished_drug_master", "change_history_log", "sync_run"):
                    conn.execute(f"DELETE FROM {t}")
            st.cache_data.clear()
            st.success("초기화했습니다.")
            st.rerun()

st.caption(f"오늘: {date.today().isoformat()}")
