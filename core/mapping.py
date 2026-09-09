"""DMF x 완제의약품 교차 결합(Cross-Join) 엔진.

SQLite 마스터를 pandas 로 올린 뒤 DuckDB 로 조인한다.
DMF 9천 건 / 완제 6만 행 규모라 인메모리로 충분하고,
정규화 키 기준 N:M 조인은 DuckDB 해시 조인이 가장 빠르다.

조인 키는 두 가지다.
  - EXACT : norm_ingredient_key (염/수화물 표기까지 일치)
  - BASE  : norm_base_key (염 제거 골격 일치, 기본값)
BASE 로 조인하면 두 키가 함께 일치하는 행에 EXACT 라벨이 붙는다.

성분별 조합 폭발을 막기 위해 필터는 조인 **이전**에 각 마스터에 밀어 넣는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from .db import connect

# 완제 품목 상태 중 "현재 유효"로 볼 값
ACTIVE_ITEM_STATUS = ("정상",)


# ---------------------------------------------------------------------------
# 통합 검색어 문법
#
#   anhui poly        -> 'anhui' AND 'poly'  (모두 걸리는 행만)
#   "anhui poly"      -> 연속 문자열 하나로 매칭
#   anhui | zhejiang  -> 둘 중 하나
#
# 예전에는 공백 토큰을 OR 로 묶었는데, 'anhui poly' 를 넣으면 'poly' 가 걸리는
# Polyethylene Glycol 류 성분이 대량으로 딸려 왔다. 사람이 공백으로 단어를 나열할 때
# 기대하는 것은 AND 이므로 기본을 AND 로 바꾸고, OR 는 '|' 로 명시하게 한다.
# ---------------------------------------------------------------------------
_RE_QUOTED = re.compile(r'"([^"]*)"')
_PLACEHOLDER = "\x00{}\x00"
_RE_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")

# 검색 대상 필드 -> (DMF 쪽 컬럼, 완제 쪽 컬럼)
SEARCH_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "성분명": (("ingredient_name_kr", "ingredient_name_en"), ("ingredient_name_kr",)),
    "원료 제조소": (("manufacturer_name", "address"), ()),
    "DMF 등록업체": (("registrant_name",), ()),
    "완제 제약사": ((), ("company_name", "company_name_en")),
    "완제품명": ((), ("product_name", "product_name_en")),
    "등록번호·품목코드": (("dmf_id",), ("item_seq",)),
}


def _escape_like(s: str) -> str:
    """LIKE 메타문자를 이스케이프한다 (검색어에 % 나 _ 가 들어오는 경우)."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_search(query: str | None) -> list[list[str]]:
    """검색어를 AND 그룹 목록으로 파싱한다.

    반환값 [[a, b], [c]] 는 (a OR b) AND (c) 를 뜻한다.
    """
    if not query or not query.strip():
        return []

    phrases: list[str] = []

    def stash(m: re.Match[str]) -> str:
        phrases.append(m.group(1))
        return _PLACEHOLDER.format(len(phrases) - 1)

    s = _RE_QUOTED.sub(stash, query)
    s = re.sub(r"\s*\|\s*", "|", s)  # 'a | b' 와 'a|b' 를 같게 만든다

    groups: list[list[str]] = []
    for chunk in s.split():
        alts: list[str] = []
        for alt in chunk.split("|"):
            alt = _RE_PLACEHOLDER.sub(lambda m: phrases[int(m.group(1))], alt).strip().lower()
            if alt:
                alts.append(alt)
        if alts:
            groups.append(alts)
    return groups


def search_columns(fields: list[str] | None) -> tuple[list[str], list[str]]:
    """선택된 검색 대상을 (DMF 컬럼, 완제 컬럼) 으로 펼친다. 비어 있으면 전체."""
    names = [f for f in (fields or []) if f in SEARCH_FIELDS] or list(SEARCH_FIELDS)
    dmf_cols: list[str] = []
    fin_cols: list[str] = []
    for name in names:
        d, p = SEARCH_FIELDS[name]
        dmf_cols.extend(c for c in d if c not in dmf_cols)
        fin_cols.extend(c for c in p if c not in fin_cols)
    return dmf_cols, fin_cols


def split_countries(value: str | None) -> list[str]:
    """'대한민국,중국' 처럼 한 필드에 여러 국가가 들어오는 경우를 분해한다."""
    if not value:
        return []
    parts = str(value).replace("/", ",").replace(";", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def name_tokens(query: str) -> list[str]:
    """업체명 부분 검색어를 소문자 토큰으로 쪼갠다.

    공백으로 나눈 토큰을 모두 포함하는 업체만 걸리게 해(AND),
    'zhejiang hongyuan' 한 번으로 'Zhejiang Hongyuan Pharmaceutical Co., Ltd.' 와
    'Zhejiang Hongyuan Pharmaceutical Co.,Ltd.' 를 함께 잡는다.
    원료 제조소·완제 제약사 두 필터가 같은 규칙을 쓴다.
    """
    return [t for t in str(query or "").lower().replace(",", " ").split() if t]


def name_match_clause(column: str, query: str, prefix: str,
                      params: dict[str, Any]) -> str | None:
    """업체명 부분 일치 SQL 조각. 토큰이 없으면 None."""
    tokens = name_tokens(query)
    if not tokens:
        return None
    conds = []
    for i, token in enumerate(tokens):
        key = "%s%d" % (prefix, i)
        params[key] = f"%{token}%"
        conds.append(f"lower({column}) LIKE ${key}")
    return "(" + " AND ".join(conds) + ")"


@dataclass
class MappingFilter:
    """UI 필터를 그대로 담는 값 객체."""

    keyword: str = ""                       # 통합 검색어 (공백=AND, "구", | =OR)
    search_fields: list[str] = field(default_factory=list)  # 비면 전체 필드 검색
    match_mode: str = "BASE"                # BASE | EXACT (성분 매칭 방식. 검색과 무관)
    dmf_active_only: bool = True            # DMF 유효만
    finished_active_only: bool = True       # 완제 허가품목(정상)만
    countries: list[str] = field(default_factory=list)
    country_scope: str = "전체"             # 전체 | 국내 | 해외
    companies: list[str] = field(default_factory=list)      # 완제 제약사 (목록에서 선택)
    company_query: str = ""                 # 완제 제약사 이름 부분 일치 (공백=AND)
    manufacturers: list[str] = field(default_factory=list)  # 원료 제조소 (목록에서 선택)
    manufacturer_query: str = ""            # 원료 제조소 이름 부분 일치 (공백=AND)
    dmf_date_from: str | None = None
    dmf_date_to: str | None = None
    permit_date_from: str | None = None
    permit_date_to: str | None = None
    change_types: list[str] = field(default_factory=list)   # NEW | MODIFIED | CANCELLED
    change_snapshot: str | None = None      # 변동사항 판정 기준 스냅샷 (YYYY-MM)
    row_limit: int = 200_000


# 마스터 프레임 메모이제이션.
# 완제 마스터가 9만 행 규모라 SQLite -> DataFrame 변환이 매 질의마다 수 초씩 든다.
# 데이터가 바뀌지 않았으면(지문이 같으면) 읽어둔 프레임을 재사용한다.
_MASTER_CACHE: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}


def data_fingerprint() -> str:
    """마스터가 바뀌었는지 판별하는 값싼 지문."""
    with connect() as conn:
        row = conn.execute(
            """SELECT (SELECT COALESCE(MAX(run_id), 0) FROM sync_run)            AS r,
                      (SELECT COALESCE(MAX(finished_at), '') FROM sync_run)      AS t,
                      (SELECT COUNT(*) FROM dmf_master)                          AS d,
                      (SELECT COUNT(*) FROM finished_drug_master)                AS f,
                      (SELECT COALESCE(MAX(log_id), 0) FROM change_history_log)  AS l"""
        ).fetchone()
    return f"{row['r']}|{row['t']}|{row['d']}|{row['f']}|{row['l']}"


def load_masters() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """마스터 3종을 DataFrame 으로 읽는다 (지문 기준 메모이제이션)."""
    fp = data_fingerprint()
    cached = _MASTER_CACHE.get(fp)
    if cached is not None:
        return cached

    with connect() as conn:
        dmf = pd.read_sql_query("SELECT * FROM dmf_master", conn)
        fin = pd.read_sql_query("SELECT * FROM finished_drug_master", conn)
        chg = pd.read_sql_query(
            """SELECT snapshot_ym, target_type, target_id, change_type
                 FROM change_history_log
                GROUP BY snapshot_ym, target_type, target_id, change_type""",
            conn,
        )
    _MASTER_CACHE.clear()  # 이전 지문의 프레임은 더 쓸 일이 없다
    _MASTER_CACHE[fp] = (dmf, fin, chg)
    return dmf, fin, chg


def latest_snapshot() -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(snapshot_ym) AS s FROM change_history_log"
        ).fetchone()
    return row["s"] if row and row["s"] else None


def _change_flag_frame(chg: pd.DataFrame, target_type: str, snapshot: str | None) -> pd.DataFrame:
    """대상 유형별 '이번 스냅샷 변동사항' 플래그 (NEW > CANCELLED > MODIFIED 우선순위)."""
    cols = ["target_id", "change_flag"]
    if chg.empty or not snapshot:
        return pd.DataFrame(columns=cols)
    sub = chg[(chg["target_type"] == target_type) & (chg["snapshot_ym"] == snapshot)]
    if sub.empty:
        return pd.DataFrame(columns=cols)
    rank = {"NEW": 0, "CANCELLED": 1, "MODIFIED": 2}
    sub = sub.assign(_r=sub["change_type"].map(rank).fillna(9))
    sub = sub.sort_values("_r").drop_duplicates("target_id")
    return sub[["target_id", "change_type"]].rename(columns={"change_type": "change_flag"})


def _compile(f: MappingFilter) -> tuple[duckdb.DuckDBPyConnection, str, str, dict[str, Any]] | None:
    """필터를 SQL로 컴파일하고, 프레임이 등록된 DuckDB 커넥션과 함께 돌려준다.

    Returns:
        (con, sql, order_by, params) 또는 데이터가 없으면 None.
        sql 에는 ORDER BY 가 붙어 있지 않아 집계 쿼리로 감쌀 수 있다.
        호출자가 con.close() 를 책임진다.
    """
    dmf, fin, chg = load_masters()
    if dmf.empty or fin.empty:
        return None

    snapshot = f.change_snapshot or latest_snapshot()
    dmf_flag = _change_flag_frame(chg, "DMF", snapshot)
    fin_flag = _change_flag_frame(chg, "FINISHED", snapshot)

    join_col = "norm_base_key" if f.match_mode == "BASE" else "norm_ingredient_key"

    # 각 마스터에 먼저 적용할 조건 (컬럼 접두사 없이 CTE 내부에서 평가된다)
    dmf_where: list[str] = [f"{join_col} IS NOT NULL AND {join_col} <> ''"]
    fin_where: list[str] = [f"{join_col} IS NOT NULL AND {join_col} <> ''"]
    params: dict[str, Any] = {}

    if f.dmf_active_only:
        dmf_where.append("status = 'ACTIVE'")
    if f.finished_active_only:
        fin_where.append("item_status = '정상'")
    if f.countries:
        # country_code 가 '대한민국,중국' 형태일 수 있어 동등 비교가 아닌 포함 비교를 쓴다.
        params["countries"] = f.countries
        dmf_where.append(
            "EXISTS (SELECT 1 FROM UNNEST($countries) AS t(c) "
            "WHERE country_code = c OR country_code LIKE '%' || c || '%')"
        )
    if f.country_scope == "국내":
        dmf_where.append("country_code = '대한민국'")
    elif f.country_scope == "해외":
        dmf_where.append("(country_code IS NULL OR country_code <> '대한민국')")
    # 업체 필터는 목록에서 고른 값과 이름 검색어를 OR 로 합친다.
    # 같은 회사가 'Co., Ltd.' / 'Co.,Ltd.' 처럼 표기만 달리 등록돼 있어,
    # 이름 일부만 입력해도 표기 변형을 한 번에 잡을 수 있어야 한다.
    def add_entity_filter(where: list[str], column: str, selected: list[str],
                          query: str, prefix: str) -> None:
        clauses: list[str] = []
        if selected:
            params[prefix] = selected
            clauses.append(f"{column} IN (SELECT * FROM UNNEST(${prefix}))")
        like = name_match_clause(column, query, prefix + "q", params)
        if like:
            clauses.append(like)
        if clauses:
            where.append("(" + " OR ".join(clauses) + ")")

    add_entity_filter(dmf_where, "manufacturer_name",
                      f.manufacturers, f.manufacturer_query, "manufacturers")
    add_entity_filter(fin_where, "company_name",
                      f.companies, f.company_query, "companies")
    if f.dmf_date_from:
        params["dmf_from"] = f.dmf_date_from
        dmf_where.append("registration_date >= $dmf_from")
    if f.dmf_date_to:
        params["dmf_to"] = f.dmf_date_to
        dmf_where.append("registration_date <= $dmf_to")
    if f.permit_date_from:
        params["permit_from"] = f.permit_date_from
        fin_where.append("permit_date >= $permit_from")
    if f.permit_date_to:
        params["permit_to"] = f.permit_date_to
        fin_where.append("permit_date <= $permit_to")

    # 통합 검색어.
    # 그룹 간에는 AND, 그룹 안의 대안끼리는 OR 다. 한 그룹은 DMF 쪽이든 완제 쪽이든
    # 어느 한 곳에서 걸리면 만족한 것으로 본다(성분은 완제에, 제조소는 DMF에 있으므로).
    # LIKE 평가는 조인 결과(수십만~수백만 행)가 아니라 CTE 내부(수천~수만 행)에서 끝낸다.
    groups = parse_search(f.keyword)
    dmf_cols, fin_cols = search_columns(f.search_fields)
    dmf_kw_select = ""
    fin_kw_select = ""
    keyword_join = ""
    if groups:
        def kw_expr(cols: list[str], pname: str) -> str:
            if not cols:
                return "FALSE"
            ors = " OR ".join(
                f"lower(COALESCE({c},'')) LIKE '%' || k || '%' ESCAPE '\\'" for c in cols
            )
            return f"EXISTS (SELECT 1 FROM UNNEST(${pname}) AS t(k) WHERE {ors})"

        dmf_parts: list[str] = []
        fin_parts: list[str] = []
        for i, alts in enumerate(groups):
            params[f"kw{i}"] = [_escape_like(a) for a in alts]
            dmf_parts.append(f"{kw_expr(dmf_cols, f'kw{i}')} AS _kw{i}")
            fin_parts.append(f"{kw_expr(fin_cols, f'kw{i}')} AS _kw{i}")
        dmf_kw_select = ", " + ", ".join(dmf_parts)
        fin_kw_select = ", " + ", ".join(fin_parts)
        keyword_join = " AND " + " AND ".join(
            f"(d._kw{i} OR p._kw{i})" for i in range(len(groups))
        )

    change_where = ""
    if f.change_types:
        params["chg"] = f.change_types
        change_where = """
          AND (COALESCE(df.change_flag,'') IN (SELECT * FROM UNNEST($chg))
            OR COALESCE(pf.change_flag,'') IN (SELECT * FROM UNNEST($chg)))"""

    sql = f"""
    WITH d AS (SELECT *{dmf_kw_select} FROM dmf WHERE {' AND '.join(dmf_where)}),
         p AS (SELECT *{fin_kw_select} FROM fin WHERE {' AND '.join(fin_where)})
    SELECT
        d.dmf_id                                   AS "DMF등록번호",
        d.ingredient_name_kr                       AS "성분명(국문)",
        COALESCE(d.ingredient_name_en, '')         AS "성분명(영문)",
        d.manufacturer_name                        AS "원료 제조소",
        d.country_code                             AS "제조국",
        CASE WHEN d.country_code = '대한민국' THEN '국내' ELSE '해외' END AS "국내/해외",
        d.registrant_name                          AS "DMF 등록업체",
        d.address                                  AS "제조소 소재지",
        d.registration_date                        AS "DMF 등록일",
        CASE d.status WHEN 'ACTIVE' THEN '유효' ELSE '취하/만료' END AS "DMF 상태",
        p.company_name                             AS "완제 제약사",
        p.product_name                             AS "완제품명",
        p.cnsgn_manuf                              AS "위탁제조사",
        p.item_seq                                 AS "품목기준코드",
        p.ingredient_name_kr                       AS "완제 주성분명",
        p.etc_otc_code                             AS "전문/일반",
        p.permit_date                              AS "허가일자",
        p.item_status                              AS "품목 상태",
        d.{join_col}                               AS "성분 매칭키",
        CASE WHEN d.norm_ingredient_key = p.norm_ingredient_key
             THEN 'EXACT' ELSE 'BASE' END          AS "매칭레벨",
        COALESCE(df.change_flag, '')               AS "DMF 변동",
        COALESCE(pf.change_flag, '')               AS "완제 변동"
    FROM d
    JOIN p  ON d.{join_col} = p.{join_col}
    LEFT JOIN dmf_flag df ON df.target_id = d.dmf_id
    LEFT JOIN fin_flag pf ON pf.target_id = p.item_seq
    WHERE 1=1 {keyword_join} {change_where}
    """
    order_by = 'ORDER BY "성분명(국문)", "DMF등록번호", "완제 제약사", "완제품명"'

    con = duckdb.connect()
    con.register("dmf", dmf)
    con.register("fin", fin)
    con.register("dmf_flag", dmf_flag)
    con.register("fin_flag", fin_flag)
    return con, sql, order_by, params


def build_mapping(f: MappingFilter) -> tuple[pd.DataFrame, int]:
    """필터를 적용한 매핑 결과와 (제한 전) 전체 행 수를 돌려준다."""
    compiled = _compile(f)
    if compiled is None:
        return pd.DataFrame(), 0
    con, sql, order_by, params = compiled
    try:
        total = con.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
        df = con.execute(f"{sql} {order_by} LIMIT {int(f.row_limit)}", params).fetchdf()
    finally:
        con.close()
    return df, int(total)


def mapping_stats(f: MappingFilter) -> dict[str, Any]:
    """필터 결과 **전체**에 대한 요약 지표.

    화면 그리드는 상한(GRID_LIMIT)까지만 가져오므로, 잘린 프레임으로 세면
    '매핑 1,347,064건 / 성분 100종' 처럼 앞뒤가 맞지 않는 숫자가 나온다.
    그래서 지표는 DuckDB 안에서 전체 결과 기준으로 집계한다.
    """
    empty = {
        "rows": 0, "ingredients": 0, "dmf_ids": 0, "manufacturers": 0,
        "companies": 0, "products": 0, "exact": 0, "exact_ratio": 0.0,
    }
    compiled = _compile(f)
    if compiled is None:
        return empty
    con, sql, _order, params = compiled
    try:
        row = con.execute(
            f"""
            SELECT COUNT(*)                             AS rows,
                   COUNT(DISTINCT "성분 매칭키")          AS ingredients,
                   COUNT(DISTINCT "DMF등록번호")          AS dmf_ids,
                   COUNT(DISTINCT "원료 제조소")           AS manufacturers,
                   COUNT(DISTINCT "완제 제약사")           AS companies,
                   COUNT(DISTINCT "품목기준코드")           AS products,
                   COUNT(*) FILTER (WHERE "매칭레벨" = 'EXACT') AS exact
              FROM ({sql})
            """,
            params,
        ).fetchone()
    finally:
        con.close()
    if not row or not row[0]:
        return empty
    return {
        "rows": int(row[0]), "ingredients": int(row[1]), "dmf_ids": int(row[2]),
        "manufacturers": int(row[3]), "companies": int(row[4]), "products": int(row[5]),
        "exact": int(row[6]), "exact_ratio": row[6] / row[0] * 100,
    }


def summarize_by_ingredient(f: MappingFilter) -> pd.DataFrame:
    """성분 단위 요약: 성분별 DMF 수 / 제조소 수 / 국가 수 / 완제 제약사 수 / 품목 수.

    집계 단위는 **매칭키(유효성분)** 다. 성분명 원문으로 묶으면 암로디핀베실산염,
    암로디핀메실산염, 암로디핀말레산염이 각각 한 줄씩 잡히면서 같은 완제 품목 수를
    반복하게 되어 공급망 규모를 읽을 수 없다. 라벨은 그 그룹에서 가장 많이 쓰인
    성분 표기를 대표로 쓴다.

    조인 결과를 파이썬으로 끌어오지 않고 DuckDB 안에서 바로 집계한다
    (전량 조인은 100만 행이 넘어 materialize 하면 화면이 눈에 띄게 느려진다).
    """
    compiled = _compile(f)
    if compiled is None:
        return pd.DataFrame()
    con, sql, _order, params = compiled
    try:
        return con.execute(
            f"""
            SELECT mode("성분명(국문)")            AS "성분명(대표)",
                   COUNT(DISTINCT "DMF등록번호")   AS "DMF 건수",
                   COUNT(DISTINCT "원료 제조소")    AS "원료 제조소 수",
                   COUNT(DISTINCT "제조국")        AS "제조국 수",
                   COUNT(DISTINCT "완제 제약사")    AS "완제 제약사 수",
                   COUNT(DISTINCT "품목기준코드")    AS "완제 품목 수",
                   COUNT(DISTINCT "성분명(국문)")   AS "성분 표기수",
                   "성분 매칭키"                   AS "매칭키"
              FROM ({sql})
             GROUP BY "성분 매칭키"
             ORDER BY "완제 품목 수" DESC, "DMF 건수" DESC
            """,
            params,
        ).fetchdf()
    finally:
        con.close()


def kpi_snapshot(snapshot_ym: str | None = None) -> dict[str, Any]:
    """대시보드 상단 KPI 카드용 집계."""
    snap = snapshot_ym or latest_snapshot()
    with connect() as conn:
        q = conn.execute
        active_dmf = q("SELECT COUNT(*) c FROM dmf_master WHERE status='ACTIVE'").fetchone()["c"]
        total_dmf = q("SELECT COUNT(*) c FROM dmf_master").fetchone()["c"]
        overseas = q(
            "SELECT COUNT(*) c FROM dmf_master WHERE status='ACTIVE' AND COALESCE(country_code,'') <> '대한민국'"
        ).fetchone()["c"]
        new_dmf = q(
            "SELECT COUNT(*) c FROM change_history_log WHERE target_type='DMF' AND change_type='NEW' AND snapshot_ym=?",
            (snap,),
        ).fetchone()["c"] if snap else 0
        new_fin = q(
            "SELECT COUNT(DISTINCT target_id) c FROM change_history_log WHERE target_type='FINISHED' AND change_type='NEW' AND snapshot_ym=?",
            (snap,),
        ).fetchone()["c"] if snap else 0
        mod_cnt = q(
            "SELECT COUNT(DISTINCT target_id) c FROM change_history_log WHERE change_type='MODIFIED' AND snapshot_ym=?",
            (snap,),
        ).fetchone()["c"] if snap else 0
        cancel_cnt = q(
            "SELECT COUNT(DISTINCT target_id) c FROM change_history_log WHERE change_type='CANCELLED' AND snapshot_ym=?",
            (snap,),
        ).fetchone()["c"] if snap else 0
        # country_code 에는 '대한민국,중국' 처럼 복수 국가가 한 값에 들어오는 경우가 있어
        # 단순 DISTINCT 로 세면 국가 수가 부풀려진다. 구분자로 쪼갠 뒤 집합으로 센다.
        country_set: set[str] = set()
        for row in q(
            "SELECT DISTINCT country_code FROM dmf_master WHERE status='ACTIVE' AND country_code IS NOT NULL"
        ):
            country_set.update(split_countries(row["country_code"]))
        countries = len(country_set)
        fin_items = q(
            "SELECT COUNT(DISTINCT item_seq) c FROM finished_drug_master WHERE item_status='정상'"
        ).fetchone()["c"]
        # 연계된(= DMF와 성분 골격이 일치하는) 완제 제약사 수
        linked_companies = q(
            """SELECT COUNT(DISTINCT p.company_name) c
                 FROM finished_drug_master p
                 JOIN (SELECT DISTINCT norm_base_key FROM dmf_master WHERE status='ACTIVE') d
                   ON p.norm_base_key = d.norm_base_key
                WHERE p.item_status='정상'"""
        ).fetchone()["c"]
        last_run = q(
            "SELECT * FROM sync_run WHERE status='SUCCESS' ORDER BY run_id DESC LIMIT 1"
        ).fetchone()

    return {
        "snapshot": snap,
        "active_dmf": active_dmf,
        "total_dmf": total_dmf,
        "overseas_dmf": overseas,
        "overseas_ratio": (overseas / active_dmf * 100) if active_dmf else 0.0,
        "new_dmf": new_dmf,
        "new_finished": new_fin,
        "modified": mod_cnt,
        "cancelled": cancel_cnt,
        "countries": countries,
        "finished_items": fin_items,
        "linked_companies": linked_companies,
        "last_run": dict(last_run) if last_run else None,
    }


def country_breakdown(active_only: bool = True) -> pd.DataFrame:
    """제조국별 DMF 건수. 복수 국가 표기는 국가별로 각각 집계한다."""
    where = "WHERE status='ACTIVE'" if active_only else ""
    with connect() as conn:
        raw = pd.read_sql_query(
            f"SELECT country_code, manufacturer_name FROM dmf_master {where}", conn
        )
    if raw.empty:
        return pd.DataFrame(columns=["제조국", "DMF 건수", "제조소 수"])
    raw["제조국"] = raw["country_code"].map(lambda v: split_countries(v) or ["(미상)"])
    exploded = raw.explode("제조국")
    out = (
        exploded.groupby("제조국")
        .agg(**{"DMF 건수": ("제조국", "size"),
                "제조소 수": ("manufacturer_name", "nunique")})
        .reset_index()
        .sort_values("DMF 건수", ascending=False)
    )
    return out


def distinct_countries(active_only: bool = False) -> list[str]:
    """필터 드롭다운용 국가 목록 (복수 국가 표기를 분해한 고유 집합)."""
    guard = "WHERE status='ACTIVE'" if active_only else ""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT country_code FROM dmf_master {guard}"
        ).fetchall()
    out: set[str] = set()
    for r in rows:
        out.update(split_countries(r["country_code"]))
    return sorted(out)


def distinct_values(table: str, column: str, active_only: bool = True) -> list[str]:
    """필터 드롭다운용 고유값 목록."""
    conds = [f"{column} IS NOT NULL", f"{column} <> ''"]
    if active_only and table == "dmf_master":
        conds.append("status = 'ACTIVE'")
    elif active_only and table == "finished_drug_master":
        conds.append("item_status = '정상'")
    sql = f"SELECT DISTINCT {column} AS v FROM {table} WHERE {' AND '.join(conds)} ORDER BY 1"
    with connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [r["v"] for r in rows]


def change_log_frame(
    snapshot_ym: str | None = None,
    target_types: list[str] | None = None,
    change_types: list[str] | None = None,
) -> pd.DataFrame:
    """변경 이력 조회 (월별 변경분 덤프의 원천)."""
    from .ingest import FIELD_LABELS

    sql = ["SELECT * FROM change_history_log WHERE 1=1"]
    args: list[Any] = []
    if snapshot_ym:
        sql.append("AND snapshot_ym = ?")
        args.append(snapshot_ym)
    if target_types:
        sql.append(f"AND target_type IN ({','.join('?' * len(target_types))})")
        args.extend(target_types)
    if change_types:
        sql.append(f"AND change_type IN ({','.join('?' * len(change_types))})")
        args.extend(change_types)
    sql.append("ORDER BY log_id DESC")

    with connect() as conn:
        df = pd.read_sql_query(" ".join(sql), conn, params=args)
    if df.empty:
        return df
    df["field_label"] = df["field_name"].map(lambda x: FIELD_LABELS.get(x, x))
    # NEW/CANCELLED 행은 before/after 가 비어 있다. None 이 그대로 찍히면 값처럼 보인다.
    for col in ("before_val", "after_val", "target_label"):
        df[col] = df[col].fillna("")
    return df.rename(
        columns={
            "snapshot_ym": "스냅샷",
            "target_type": "구분",
            "target_id": "대상 ID",
            "target_label": "대상명",
            "change_type": "변경유형",
            "field_label": "변경 항목",
            "before_val": "변경 전",
            "after_val": "변경 후",
            "detected_at": "감지시각",
        }
    )[
        ["스냅샷", "구분", "변경유형", "대상 ID", "대상명", "변경 항목", "변경 전", "변경 후", "감지시각"]
    ]


def available_snapshots() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT snapshot_ym FROM change_history_log ORDER BY 1 DESC"
        ).fetchall()
    return [r["snapshot_ym"] for r in rows if r["snapshot_ym"]]
