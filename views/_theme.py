"""디자인 테마: 색 토큰, 전역 CSS, 카드/헤더 컴포넌트.

참고 디자인(다크 네이비 사이드바 + 라이트 그레이 본문 + 흰색 카드)을 Streamlit 위에
CSS 로 얹는다. 기능에는 관여하지 않고 표현만 담당한다.

아이콘은 외부 폰트나 CDN 없이 인라인 SVG 로 그린다. 사내망에서 외부 리소스가 막혀도
아이콘이 깨지지 않고, 색을 currentColor 로 물려받아 타일 색과 항상 맞는다.
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# 색 토큰
# ---------------------------------------------------------------------------
INK = "#1a2233"          # 본문 텍스트
INK_2 = "#5b6577"        # 보조 텍스트
INK_3 = "#98a1b3"        # 흐린 캡션
PRIMARY = "#2f6fe4"      # 주 강조 (버튼, 차트 막대)
PRIMARY_SOFT = "#93b4f2"
DANGER = "#e2453d"       # 위험 신호 수치
SUCCESS = "#16a34a"
AMBER = "#e08c12"
VIOLET = "#7159d6"
TEAL = "#0f9b8e"

# KPI 아이콘 타일 색 (배경, 글리프)
TILES = {
    "blue":   ("#e8f0fe", "#2f6fe4"),
    "red":    ("#fdeceb", "#e2453d"),
    "amber":  ("#fef3e2", "#d98014"),
    "green":  ("#e6f6ec", "#16a34a"),
    "violet": ("#eeebfb", "#7159d6"),
    "teal":   ("#e2f5f2", "#0f9b8e"),
    "slate":  ("#eef1f6", "#5b6577"),
}

# 수치 색 톤
TONES = {
    "default": INK,
    "primary": PRIMARY,
    "danger": DANGER,
    "success": SUCCESS,
    "amber": AMBER,
}

# ---------------------------------------------------------------------------
# 인라인 SVG 아이콘 (24x24 viewBox, stroke 기반 라인 아이콘)
# ---------------------------------------------------------------------------
ICONS: dict[str, str] = {
    "pill": '<rect x="2.5" y="9" width="19" height="6" rx="3" transform="rotate(-45 12 12)"/>'
            '<line x1="8.4" y1="8.4" x2="15.6" y2="15.6"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/>'
            '<rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>',
    "link": '<path d="M10 13.5a4.5 4.5 0 0 0 6.8.5l2.7-2.7a4.5 4.5 0 0 0-6.4-6.4L11.6 6.4"/>'
            '<path d="M14 10.5a4.5 4.5 0 0 0-6.8-.5l-2.7 2.7a4.5 4.5 0 0 0 6.4 6.4l1.5-1.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><polyline points="12 6.8 12 12 15.8 14"/>',
    "sliders": '<line x1="3.5" y1="6.5" x2="20.5" y2="6.5"/><line x1="3.5" y1="12" x2="20.5" y2="12"/>'
               '<line x1="3.5" y1="17.5" x2="20.5" y2="17.5"/><circle cx="9" cy="6.5" r="2.1"/>'
               '<circle cx="15.5" cy="12" r="2.1"/><circle cx="7.5" cy="17.5" r="2.1"/>',
    "factory": '<path d="M3 21V10.5l6 3.6V10.5l6 3.6V5.5h6V21z"/><line x1="2.2" y1="21" x2="21.8" y2="21"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><line x1="3" y1="12" x2="21" y2="12"/>'
             '<path d="M12 3a13 13 0 0 1 0 18a13 13 0 0 1 0-18"/>',
    "alert": '<path d="M10.3 4.4 2.7 17.9A2 2 0 0 0 4.4 21h15.2a2 2 0 0 0 1.7-3.1L13.7 4.4a2 2 0 0 0-3.4 0z"/>'
             '<line x1="12" y1="9.5" x2="12" y2="14"/><line x1="12" y1="17.3" x2="12.01" y2="17.3"/>',
    "box": '<path d="M21 8.2 12 3.2 3 8.2v7.6l9 5 9-5z"/><path d="M3 8.2l9 5 9-5"/>'
           '<line x1="12" y1="13.2" x2="12" y2="20.8"/>',
    "trend": '<polyline points="3 17 9 11 13 15 21 7"/><polyline points="15.5 7 21 7 21 12.5"/>',
    "check": '<circle cx="12" cy="12" r="9"/><polyline points="8 12.2 10.9 15 16 9.4"/>',
    "building": '<rect x="4" y="3" width="16" height="18" rx="2"/>'
                '<path d="M9 8h.01M15 8h.01M9 12h.01M15 12h.01"/><path d="M9.5 21v-4h5v4"/>',
    "refresh": '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><polyline points="20.5 3.6 20.5 9 15.1 9"/>',
    "download": '<path d="M12 3.5v11.5"/><polyline points="7.2 10.5 12 15.3 16.8 10.5"/>'
                '<line x1="4" y1="20" x2="20" y2="20"/>',
    "search": '<circle cx="10.8" cy="10.8" r="7"/><line x1="16" y1="16" x2="21" y2="21"/>',
    "database": '<ellipse cx="12" cy="5.8" rx="8" ry="2.9"/>'
                '<path d="M4 5.8v6c0 1.6 3.6 2.9 8 2.9s8-1.3 8-2.9v-6"/>'
                '<path d="M4 11.8v6.4c0 1.6 3.6 2.9 8 2.9s8-1.3 8-2.9v-6.4"/>',
    "flask": '<path d="M9.5 3v6.2L4.6 18a2 2 0 0 0 1.7 3h11.4a2 2 0 0 0 1.7-3l-4.9-8.8V3"/>'
             '<line x1="8.4" y1="3" x2="15.6" y2="3"/><line x1="7.2" y1="14.2" x2="16.8" y2="14.2"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4"/><path d="M10.4 12.6 20 3"/>'
           '<line x1="16.6" y1="6.4" x2="19" y2="8.8"/><line x1="14.2" y1="8.8" x2="16.4" y2="11"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><polyline points="3.5 3.6 3.5 9 8.9 9"/>'
               '<polyline points="12 7.6 12 12 15.5 13.8"/>',
}


def icon_svg(name: str, size: int = 18, stroke: float = 1.7) -> str:
    """이름으로 인라인 SVG 아이콘 마크업을 만든다."""
    body = ICONS.get(name, ICONS["grid"])
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
        f'stroke="currentColor" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )


# ---------------------------------------------------------------------------
# 전역 CSS
# ---------------------------------------------------------------------------
_CSS = """
<style>
/* ---------- 기본 캔버스 ---------- */
[data-testid="stAppViewContainer"] { background: #f4f6f9; }
[data-testid="stHeader"] { background: transparent; height: 0; }
[data-testid="stMain"] .block-container {
    padding: 1.3rem 1.9rem 3rem 1.9rem;
    max-width: 100%;          /* 참고 디자인처럼 화면 폭을 꽉 채운다 */
}
body, [data-testid="stAppViewContainer"] {
    color: #1a2233;
    font-family: "Pretendard", "Noto Sans KR", -apple-system, BlinkMacSystemFont,
                 "Segoe UI", Roboto, sans-serif;
}
#MainMenu, footer { visibility: hidden; }

/* ---------- 사이드바 : 다크 네이비 ---------- */
section[data-testid="stSidebar"] {
    background: #1b2537;
    border-right: 1px solid #141c2b;
    width: 268px !important;
    /* 항상 펼쳐진 상태로 고정 - 접기 동작을 무력화한다 */
    min-width: 268px !important;
    max-width: 268px !important;
    transform: none !important;
    visibility: visible !important;
    margin-left: 0 !important;
}
section[data-testid="stSidebar"][aria-expanded="false"] {
    transform: none !important;
    visibility: visible !important;
}
/* 사이드바 접기(×) 버튼과 접힌 뒤 나타나는 펼치기(») 버튼을 숨긴다 */
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"],
section[data-testid="stSidebar"] button[kind="header"],
section[data-testid="stSidebar"] [data-testid="baseButton-header"] {
    display: none !important;
}
/* 폭 조절 손잡이도 함께 고정 */
[data-testid="stSidebarResizeHandle"] { display: none !important; }
section[data-testid="stSidebar"] > div { background: #1b2537; }
section[data-testid="stSidebar"] * { color: #c7cedb; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: #eef2f8; }
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #aeb8c8; }
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong {
    color: #8592a8;
    font-size: .72rem;
    letter-spacing: .04em;
    font-weight: 600;
    text-transform: none;
}
section[data-testid="stSidebar"] label p,
section[data-testid="stSidebar"] label span { color: #aeb8c8 !important; font-size: .8rem; }
section[data-testid="stSidebar"] hr { border-color: #2b364c; }
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: #7c879b; }

/* 사이드바 입력 위젯 */
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] textarea,
section[data-testid="stSidebar"] [data-baseweb="select"] > div,
section[data-testid="stSidebar"] [data-baseweb="input"] > div {
    background: #232f45 !important;
    border-color: #33415c !important;
    color: #e6ebf3 !important;
}
section[data-testid="stSidebar"] input::placeholder { color: #6f7c92 !important; }
section[data-testid="stSidebar"] [data-baseweb="tag"] {
    background: #2f6fe4 !important;
    border-radius: 6px !important;
}
section[data-testid="stSidebar"] [data-baseweb="tag"] span { color: #fff !important; }
section[data-testid="stSidebar"] [data-testid="stExpander"] {
    border: 1px solid #2b364c !important;
}
section[data-testid="stSidebar"] details {
    background: #232f45 !important;
    border: 1px solid #33415c !important;
    border-radius: 10px !important;
}
section[data-testid="stSidebar"] summary { color: #c7cedb !important; }

/* ---------- 사이드바 브랜드 ----------
   st.navigation 이 네비게이션을 먼저 그리기 때문에, 파이썬에서 위젯을 추가하면
   메뉴 아래에 붙는다. 브랜드 블록은 메뉴 위에 와야 하므로 의사요소로 그린다.
   로고는 data URI SVG 라 외부 리소스에 의존하지 않는다. */
[data-testid="stSidebarNav"]::before {
    content: "원료의약품등록 모니터링";
    display: block;
    margin: 0 0 .55rem 0;
    padding: .2rem 1rem 1rem 4.05rem;
    min-height: 38px;
    font-size: .96rem; font-weight: 700; color: #f2f5fa; line-height: 1.3;
    border-bottom: 1px solid #2b364c;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='38' height='38' viewBox='0 0 38 38'%3E%3Crect width='38' height='38' rx='11' fill='%232f6fe4'/%3E%3Cg transform='rotate(-45 19 19)' stroke='%23ffffff' stroke-width='1.9' fill='none' stroke-linecap='round'%3E%3Crect x='9' y='15.5' width='20' height='7' rx='3.5'/%3E%3Cline x1='19' y1='15.5' x2='19' y2='22.5'/%3E%3C/g%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: 1rem .1rem;
    background-size: 38px 38px;
}
[data-testid="stSidebarNav"] ul::before {
    content: "메뉴";
    display: block;
    padding: 0 .8rem .4rem .8rem;
    font-size: .72rem; font-weight: 600; color: #7c879b; letter-spacing: .02em;
}

/* ---------- 사이드바 네비게이션 ---------- */
[data-testid="stSidebarNav"] { padding-top: .2rem; }
[data-testid="stSidebarNav"] ul { padding: 0 .55rem; gap: 2px; }
[data-testid="stSidebarNav"] li { margin: 1px 0; }
[data-testid="stSidebarNav"] a {
    border-radius: 9px;
    padding: .5rem .7rem !important;
    transition: background .12s ease;
}
[data-testid="stSidebarNav"] a span { color: #b6c0d0 !important; font-size: .88rem; }
[data-testid="stSidebarNav"] a:hover { background: rgba(255,255,255,.06); }
[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebarNav"] li a[aria-selected="true"] {
    background: #2f5fbf !important;
}
[data-testid="stSidebarNav"] a[aria-current="page"] span,
[data-testid="stSidebarNav"] a[aria-current="page"] * { color: #ffffff !important; font-weight: 600; }

/* ---------- 사이드바 브랜드 블록 ---------- */
.brand {
    display: flex; align-items: center; gap: .7rem;
    padding: .35rem .35rem 1rem .35rem;
    margin-bottom: .5rem;
    border-bottom: 1px solid #2b364c;
}
.brand-mark {
    width: 38px; height: 38px; border-radius: 11px; flex: 0 0 38px;
    background: linear-gradient(135deg, #3b7ae4, #2f5fbf);
    display: flex; align-items: center; justify-content: center; color: #fff;
}
.brand-title { font-size: .98rem; font-weight: 700; color: #f2f5fa; line-height: 1.25; }
.brand-sub { font-size: .74rem; color: #8592a8; margin-top: 1px; }
.nav-label {
    color: #7c879b; font-size: .72rem; font-weight: 600;
    padding: .2rem .8rem .35rem .8rem; letter-spacing: .02em;
}

/* ---------- 페이지 헤더 ---------- */
.pagehead {
    display: flex; align-items: center; justify-content: space-between;
    gap: 1rem; margin: 0 0 1.15rem 0; flex-wrap: wrap;
}
.pagehead-left { display: flex; align-items: center; gap: .7rem; }
.pagehead-ico {
    width: 34px; height: 34px; border-radius: 10px; flex: 0 0 34px;
    background: #e8f0fe; color: #2f6fe4;
    display: flex; align-items: center; justify-content: center;
}
.pagehead h1 { font-size: 1.32rem; font-weight: 700; color: #1a2233; margin: 0; padding: 0; }
.pagehead .sub { font-size: .84rem; color: #7a8497; margin-left: .55rem; }
.chips { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.chip {
    display: inline-flex; align-items: center; gap: .4rem;
    background: #fff; border: 1px solid #e6e9ef; border-radius: 999px;
    padding: .34rem .8rem; font-size: .78rem; color: #4a5568; white-space: nowrap;
    box-shadow: 0 1px 2px rgba(16,24,40,.04);
}
.chip.amber { background: #fff8ec; border-color: #f5e0bd; color: #b8770f; }
.chip.blue  { background: #2f6fe4; border-color: #2f6fe4; color: #fff; font-weight: 600; }
.chip b { color: #1a2233; font-weight: 600; }
.chip.blue b { color: #fff; }

/* ---------- KPI 카드 ---------- */
.kpi {
    background: #fff; border: 1px solid #e6e9ef; border-radius: 13px;
    padding: .95rem 1.05rem 1rem 1.05rem; height: 100%;
    box-shadow: 0 1px 2px rgba(16,24,40,.05);
}
.kpi-head { display: flex; align-items: center; gap: .55rem; margin-bottom: .55rem; }
.kpi-ico {
    width: 29px; height: 29px; border-radius: 9px; flex: 0 0 29px;
    display: flex; align-items: center; justify-content: center;
}
.kpi-label { font-size: .8rem; color: #5b6577; font-weight: 500; line-height: 1.25; }
.kpi-value { font-size: 1.92rem; font-weight: 700; letter-spacing: -.02em; line-height: 1.1; }
.kpi-unit { font-size: .95rem; font-weight: 600; margin-left: .12rem; color: inherit; opacity: .82; }
.kpi-badge {
    display: inline-block; margin-top: .45rem; padding: .16rem .5rem;
    border-radius: 6px; font-size: .74rem; font-weight: 600;
}
.kpi-badge.up   { background: #e6f6ec; color: #16a34a; }
.kpi-badge.flat { background: #eef1f6; color: #5b6577; }
.kpi-badge.down { background: #fdeceb; color: #e2453d; }
.kpi-sub { margin-top: .4rem; font-size: .755rem; color: #98a1b3; line-height: 1.35; }

/* ---------- 카드 컨테이너 ----------
   Streamlit 은 여러 레이아웃 블록을 같은 testid 로 감싸기 때문에, 컨테이너를
   통째로 겨냥하면 컬럼 같은 무관한 블록까지 흰 카드가 된다. card_header() 가 넣는
   .cardhead 를 표식으로 삼아 실제 카드만 골라 칠한다. */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(.cardhead) {
    background: #fff;
    border: 1px solid #e6e9ef !important;
    border-radius: 13px !important;
    box-shadow: 0 1px 2px rgba(16,24,40,.05);
    padding: .25rem;
}

/* ---------- Streamlit 기본 장식 정리 ---------- */
[data-testid="stDecoration"] { display: none; }
[data-testid="stAppDeployButton"] { display: none; }

/* 카드 헤더 */
.cardhead { display: flex; align-items: flex-start; gap: .6rem; margin-bottom: .2rem; }
.cardhead-ico {
    width: 29px; height: 29px; border-radius: 9px; flex: 0 0 29px;
    display: flex; align-items: center; justify-content: center; margin-top: 1px;
}
.cardhead-title { font-size: .97rem; font-weight: 700; color: #1a2233; line-height: 1.3; }
.cardhead-desc { font-size: .78rem; color: #8b94a6; margin-top: .18rem; line-height: 1.45; }

/* ---------- 일반 요소 ---------- */
[data-testid="stMain"] h2 { font-size: 1.05rem; font-weight: 700; color: #1a2233; }
[data-testid="stMain"] h3 { font-size: .97rem; font-weight: 700; color: #1a2233; }
[data-testid="stMain"] hr { border-color: #e6e9ef; margin: 1.1rem 0; }
[data-testid="stMain"] [data-testid="stCaptionContainer"] p { color: #8b94a6; font-size: .79rem; }

/* 버튼 */
[data-testid="stMain"] button[kind="primary"] {
    background: #2f6fe4; border-color: #2f6fe4; border-radius: 9px; font-weight: 600;
}
[data-testid="stMain"] button[kind="secondary"],
[data-testid="stMain"] [data-testid="stDownloadButton"] button {
    background: #fff; border: 1px solid #dbe0e9; border-radius: 9px;
    color: #33405a; font-weight: 500;
}
[data-testid="stMain"] button[kind="secondary"]:hover,
[data-testid="stMain"] [data-testid="stDownloadButton"] button:hover {
    border-color: #2f6fe4; color: #2f6fe4;
}

/* 사이드바 '초기화' 버튼 - 어두운 배경에 맞춘 외곽선 버튼 */
section[data-testid="stSidebar"] .stButton button {
    background: transparent;
    border: 1px solid #3a465e;
    border-radius: 8px;
    color: #aeb8c8 !important;
    font-size: .78rem;
    font-weight: 500;
    padding: .15rem .4rem;
    min-height: 1.9rem;
}
section[data-testid="stSidebar"] .stButton button:hover {
    border-color: #2f6fe4;
    color: #eef2f8 !important;
    background: #22304a;
}

/* 입력 위젯 (본문) */
[data-testid="stMain"] [data-baseweb="select"] > div,
[data-testid="stMain"] [data-baseweb="input"] > div {
    border-radius: 9px; border-color: #dbe0e9; background: #fff;
}
[data-testid="stMain"] [data-baseweb="tag"] { background: #2f6fe4 !important; border-radius: 6px !important; }

/* 표 */
[data-testid="stDataFrame"] { border: 1px solid #e6e9ef; border-radius: 11px; overflow: hidden; }

/* 알림 박스 */
[data-testid="stAlert"] { border-radius: 11px; border: 1px solid #e6e9ef; }

/* 사이드바 접기 버튼 */
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarCollapsedControl"] button { color: #c7cedb; }
</style>
"""


def inject() -> None:
    """전역 CSS 를 주입한다. 각 페이지 최상단에서 한 번 호출한다."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 컴포넌트
# ---------------------------------------------------------------------------
def page_header(icon: str, title: str, subtitle: str = "", chips: list[str] | None = None) -> None:
    """페이지 상단 제목 줄 (좌: 아이콘+제목+설명, 우: 요약 칩)."""
    chip_html = "".join(chips or [])
    sub = f'<span class="sub">{subtitle}</span>' if subtitle else ""
    st.markdown(
        f'<div class="pagehead">'
        f'  <div class="pagehead-left">'
        f'    <div class="pagehead-ico">{icon_svg(icon, 19)}</div>'
        f"    <div><h1>{title}{sub}</h1></div>"
        f"  </div>"
        f'  <div class="chips">{chip_html}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def chip(text: str, kind: str = "", icon: str | None = None) -> str:
    """헤더 우측에 놓을 칩 마크업을 만든다."""
    ico = icon_svg(icon, 14) if icon else ""
    cls = f"chip {kind}".strip()
    return f'<span class="{cls}">{ico}{text}</span>'


def kpi_card(
    label: str,
    value: str,
    unit: str = "",
    caption: str = "",
    badge: str = "",
    badge_kind: str = "flat",
    tile: str = "blue",
    icon: str = "grid",
    tone: str = "default",
) -> str:
    """KPI 카드 HTML. 아이콘 타일 + 라벨 + 큰 수치 + 배지 + 캡션."""
    bg, fg = TILES.get(tile, TILES["blue"])
    color = TONES.get(tone, INK)
    unit_html = f'<span class="kpi-unit">{unit}</span>' if unit else ""
    badge_html = f'<div class="kpi-badge {badge_kind}">{badge}</div>' if badge else ""
    cap_html = f'<div class="kpi-sub">{caption}</div>' if caption else ""
    return (
        f'<div class="kpi">'
        f'  <div class="kpi-head">'
        f'    <span class="kpi-ico" style="background:{bg};color:{fg}">{icon_svg(icon, 16)}</span>'
        f'    <span class="kpi-label">{label}</span>'
        f"  </div>"
        f'  <div class="kpi-value" style="color:{color}">{value}{unit_html}</div>'
        f"  {badge_html}{cap_html}"
        f"</div>"
    )


def kpi_row(cards: list[str], gap: str = "small") -> None:
    """KPI 카드들을 한 줄로 배치한다."""
    cols = st.columns(len(cards), gap=gap)
    for col, html in zip(cols, cards):
        col.markdown(html, unsafe_allow_html=True)


def card_header(icon: str, title: str, desc: str = "", tile: str = "blue") -> None:
    """카드 컨테이너 안쪽 상단 헤더."""
    bg, fg = TILES.get(tile, TILES["blue"])
    desc_html = f'<div class="cardhead-desc">{desc}</div>' if desc else ""
    st.markdown(
        f'<div class="cardhead">'
        f'  <span class="cardhead-ico" style="background:{bg};color:{fg}">{icon_svg(icon, 16)}</span>'
        f'  <div><div class="cardhead-title">{title}</div>{desc_html}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
