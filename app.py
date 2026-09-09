"""원료의약품등록 모니터링 시스템 (Pharma-DMF Linker).

식약처 DMF 등록 원료와 이를 주성분으로 쓰는 완제의약품 제조·수입사를
정규화된 성분 키로 교차 매핑하고, 월별 변경 이력을 추적하는 Streamlit 앱.

실행:  streamlit run app.py   (또는 run.bat)
"""

from __future__ import annotations

import streamlit as st

from core.db import init_db

st.set_page_config(
    page_title="원료의약품등록 모니터링 시스템",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

# 네비게이션 아이콘은 Streamlit 에 내장된 Material Symbols 를 쓴다.
# 외부 CDN 없이 라인 아이콘이 나와 참고 디자인의 사이드바와 결이 맞는다.
PAGES = [
    st.Page("views/mapping.py", title="상세 조회", icon=":material/hub:", default=True),
    st.Page("views/dashboard.py", title="종합 현황", icon=":material/dashboard:"),
    st.Page("views/changes.py", title="변경 이력", icon=":material/history:"),
    st.Page("views/sync.py", title="데이터 동기화", icon=":material/sync:"),
]

st.navigation(PAGES).run()
