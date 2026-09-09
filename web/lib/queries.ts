import { query, queryOne } from "./db";
import {
  Filter,
  SEARCH_FIELDS,
  SearchFieldName,
  nameTokens,
  parseSearch,
} from "./filters";

/** $1, $2 … 자리표시자를 붙여 가며 파라미터를 모은다. */
class Binder {
  values: unknown[] = [];
  add(v: unknown): string {
    this.values.push(v);
    return `$${this.values.length}`;
  }
}

/** LIKE 메타문자 이스케이프. 검색어에 % 나 _ 가 들어오는 경우를 막는다. */
function escapeLike(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_");
}

function searchColumns(fields: SearchFieldName[]) {
  const names = fields.length
    ? fields
    : (Object.keys(SEARCH_FIELDS) as SearchFieldName[]);
  const dmf = new Set<string>();
  const fin = new Set<string>();
  for (const n of names) {
    SEARCH_FIELDS[n].dmf.forEach((c) => dmf.add(c));
    SEARCH_FIELDS[n].fin.forEach((c) => fin.add(c));
  }
  return { dmf: [...dmf], fin: [...fin] };
}

/** 업체명 부분 일치 조건. 토큰을 모두 포함해야 한다(AND). */
function nameMatch(column: string, q: string, b: Binder): string | null {
  const tokens = nameTokens(q);
  if (!tokens.length) return null;
  const conds = tokens.map(
    (t) => `lower(coalesce(${column},'')) LIKE ${b.add(`%${escapeLike(t)}%`)} ESCAPE '\\'`
  );
  return `(${conds.join(" AND ")})`;
}

export type CompiledMapping = {
  cte: string;
  where: string;
  values: unknown[];
};

/**
 * 필터를 SQL 로 컴파일한다. 조인 결과(최대 130만 행)가 아니라 CTE 안쪽
 * (수천~수만 행)에서 조건을 모두 끝내는 구조를 그대로 유지했다.
 */
function compile(f: Filter, snapshot: string | null): CompiledMapping {
  const b = new Binder();
  const joinCol = f.matchMode === "BASE" ? "norm_base_key" : "norm_ingredient_key";

  const dmfWhere = [`${joinCol} IS NOT NULL AND ${joinCol} <> ''`];
  const finWhere = [`${joinCol} IS NOT NULL AND ${joinCol} <> ''`];

  if (f.dmfActiveOnly) dmfWhere.push("status = 'ACTIVE'");
  if (f.finishedActiveOnly) finWhere.push("item_status = '정상'");

  if (f.countries.length) {
    // country_code 가 '대한민국,중국' 형태일 수 있어 동등 비교가 아닌 포함 비교를 쓴다.
    const p = b.add(f.countries);
    dmfWhere.push(
      `EXISTS (SELECT 1 FROM unnest(${p}::text[]) AS t(c)
               WHERE country_code = t.c OR country_code LIKE '%' || t.c || '%')`
    );
  }
  if (f.countryScope === "국내") dmfWhere.push("country_code = '대한민국'");
  else if (f.countryScope === "해외")
    dmfWhere.push("(country_code IS NULL OR country_code <> '대한민국')");

  // 업체 필터: 이름 부분 검색만 쓴다. 표기 변형(Co., Ltd. / Co.,Ltd.)을
  // 한 번에 잡기 위한 것으로, 목록에서 하나씩 고르는 방식을 대체한다.
  const mfr = nameMatch("manufacturer_name", f.manufacturerQuery, b);
  if (mfr) dmfWhere.push(mfr);
  const comp = nameMatch("company_name", f.companyQuery, b);
  if (comp) finWhere.push(comp);

  if (f.dmfDateFrom) dmfWhere.push(`registration_date >= ${b.add(f.dmfDateFrom)}`);
  if (f.dmfDateTo) dmfWhere.push(`registration_date <= ${b.add(f.dmfDateTo)}`);
  if (f.permitDateFrom) finWhere.push(`permit_date >= ${b.add(f.permitDateFrom)}`);
  if (f.permitDateTo) finWhere.push(`permit_date <= ${b.add(f.permitDateTo)}`);

  // 통합 검색어: 그룹끼리는 AND, 그룹 안 대안끼리는 OR.
  // 한 그룹은 DMF 쪽이든 완제 쪽이든 어느 한 곳에서 걸리면 만족으로 본다.
  const groups = parseSearch(f.keyword);
  const cols = searchColumns(f.searchFields);
  const dmfKwSelect: string[] = [];
  const finKwSelect: string[] = [];
  const keywordJoin: string[] = [];

  groups.forEach((alts, i) => {
    const p = b.add(alts.map(escapeLike));
    const expr = (list: string[]) =>
      list.length
        ? `EXISTS (SELECT 1 FROM unnest(${p}::text[]) AS t(k) WHERE ${list
            .map((c) => `lower(coalesce(${c},'')) LIKE '%' || t.k || '%' ESCAPE '\\'`)
            .join(" OR ")})`
        : "FALSE";
    dmfKwSelect.push(`${expr(cols.dmf)} AS kw${i}`);
    finKwSelect.push(`${expr(cols.fin)} AS kw${i}`);
    keywordJoin.push(`(d.kw${i} OR p.kw${i})`);
  });

  const flagCte = (type: "DMF" | "FINISHED", alias: string) =>
    snapshot
      ? `${alias} AS (
           SELECT DISTINCT ON (target_id) target_id, change_type
             FROM change_history_log
            WHERE target_type = ${b.add(type)} AND snapshot_ym = ${b.add(snapshot)}
            ORDER BY target_id,
                     CASE change_type WHEN 'NEW' THEN 0 WHEN 'CANCELLED' THEN 1
                                      WHEN 'MODIFIED' THEN 2 ELSE 9 END)`
      : `${alias} AS (SELECT NULL::text AS target_id, NULL::text AS change_type WHERE FALSE)`;

  const cte = `WITH d AS (
      SELECT *${dmfKwSelect.length ? ", " + dmfKwSelect.join(", ") : ""}
        FROM dmf_master WHERE ${dmfWhere.join(" AND ")}
    ), p AS (
      SELECT *${finKwSelect.length ? ", " + finKwSelect.join(", ") : ""}
        FROM finished_drug_master WHERE ${finWhere.join(" AND ")}
    ), ${flagCte("DMF", "dflag")}, ${flagCte("FINISHED", "pflag")}`;

  const conds = ["1=1", ...keywordJoin];
  if (f.changeTypes.length) {
    const p = b.add(f.changeTypes);
    conds.push(
      `(coalesce(df.change_type,'') = ANY(${p}::text[])
        OR coalesce(pf.change_type,'') = ANY(${p}::text[]))`
    );
  }

  return {
    cte,
    where: `FROM d
      JOIN p ON d.${joinCol} = p.${joinCol}
      LEFT JOIN dflag df ON df.target_id = d.dmf_id
      LEFT JOIN pflag pf ON pf.target_id = p.item_seq
      WHERE ${conds.join(" AND ")}`,
    values: b.values,
  };
}

export const GRID_COLUMNS = [
  "DMF등록번호",
  "성분명(국문)",
  "성분명(영문)",
  "원료 제조소",
  "제조국",
  "DMF 등록업체",
  "제조소 소재지",
  "DMF 등록일",
  "DMF 상태",
  "완제 제약사",
  "완제품명",
  "위탁제조사",
  "품목기준코드",
  "전문/일반",
  "허가일자",
  "품목 상태",
  "매칭레벨",
  "DMF 변동",
  "완제 변동",
] as const;

const SELECT_LIST = `
    d.dmf_id                            AS "DMF등록번호",
    d.ingredient_name_kr                AS "성분명(국문)",
    coalesce(d.ingredient_name_en,'')   AS "성분명(영문)",
    d.manufacturer_name                 AS "원료 제조소",
    d.country_code                      AS "제조국",
    d.registrant_name                   AS "DMF 등록업체",
    d.address                           AS "제조소 소재지",
    d.registration_date                 AS "DMF 등록일",
    CASE d.status WHEN 'ACTIVE' THEN '유효' ELSE '취하/만료' END AS "DMF 상태",
    p.company_name                      AS "완제 제약사",
    p.product_name                      AS "완제품명",
    p.cnsgn_manuf                       AS "위탁제조사",
    p.item_seq                          AS "품목기준코드",
    p.etc_otc_code                      AS "전문/일반",
    p.permit_date                       AS "허가일자",
    p.item_status                       AS "품목 상태",
    CASE WHEN d.norm_ingredient_key = p.norm_ingredient_key THEN 'EXACT' ELSE 'BASE' END AS "매칭레벨",
    coalesce(df.change_type,'')         AS "DMF 변동",
    coalesce(pf.change_type,'')         AS "완제 변동"`;

const ORDER_BY = `ORDER BY "성분명(국문)", "DMF등록번호", "완제 제약사", "완제품명"`;

export type GridRow = Record<string, string | null>;

export async function latestSnapshot(): Promise<string | null> {
  const row = await queryOne<{ s: string | null }>(
    "SELECT MAX(snapshot_ym) AS s FROM change_history_log"
  );
  return row?.s ?? null;
}

export async function fetchGrid(f: Filter, snapshot: string | null) {
  const c = compile(f, snapshot);
  const offset = (f.page - 1) * f.pageSize;
  const rows = await query<GridRow>(
    `${c.cte} SELECT ${SELECT_LIST} ${c.where} ${ORDER_BY} LIMIT $${
      c.values.length + 1
    } OFFSET $${c.values.length + 2}`,
    [...c.values, f.pageSize, offset]
  );
  return rows;
}

export type MappingStats = {
  rows: number;
  ingredients: number;
  dmf_ids: number;
  manufacturers: number;
  companies: number;
  products: number;
  exact: number;
};

export async function fetchStats(
  f: Filter,
  snapshot: string | null
): Promise<MappingStats> {
  const c = compile(f, snapshot);
  const row = await queryOne<Record<string, string>>(
    `${c.cte}
     SELECT COUNT(*)                                  AS rows,
            COUNT(DISTINCT d.${
              f.matchMode === "BASE" ? "norm_base_key" : "norm_ingredient_key"
            })                                        AS ingredients,
            COUNT(DISTINCT d.dmf_id)                  AS dmf_ids,
            COUNT(DISTINCT d.manufacturer_name)       AS manufacturers,
            COUNT(DISTINCT p.company_name)            AS companies,
            COUNT(DISTINCT p.item_seq)                AS products,
            COUNT(*) FILTER (WHERE d.norm_ingredient_key = p.norm_ingredient_key) AS exact
     ${c.where}`,
    c.values
  );
  const n = (k: string) => Number(row?.[k] ?? 0);
  return {
    rows: n("rows"),
    ingredients: n("ingredients"),
    dmf_ids: n("dmf_ids"),
    manufacturers: n("manufacturers"),
    companies: n("companies"),
    products: n("products"),
    exact: n("exact"),
  };
}

/** CSV 내보내기용. 페이지네이션 없이 상한까지 한 번에 읽는다. */
export async function fetchAllRows(
  f: Filter,
  snapshot: string | null,
  limit: number
): Promise<GridRow[]> {
  const c = compile(f, snapshot);
  return query<GridRow>(
    `${c.cte} SELECT ${SELECT_LIST} ${c.where} ${ORDER_BY} LIMIT $${
      c.values.length + 1
    }`,
    [...c.values, limit]
  );
}

/** 사이드바 미리보기: 이름 검색어에 걸리는 업체 목록. */
export async function matchingNames(
  table: "dmf_master" | "finished_drug_master",
  column: "manufacturer_name" | "company_name",
  q: string,
  limit = 50
): Promise<{ names: string[]; total: number }> {
  const tokens = nameTokens(q);
  if (!tokens.length) return { names: [], total: 0 };
  const b = new Binder();
  const conds = tokens.map(
    (t) => `lower(coalesce(${column},'')) LIKE ${b.add(`%${escapeLike(t)}%`)} ESCAPE '\\'`
  );
  const rows = await query<{ name: string }>(
    `SELECT DISTINCT ${column} AS name FROM ${table}
      WHERE ${column} IS NOT NULL AND ${conds.join(" AND ")}
      ORDER BY 1 LIMIT ${limit + 1}`,
    b.values
  );
  const total = await queryOne<{ n: string }>(
    `SELECT COUNT(DISTINCT ${column}) AS n FROM ${table}
      WHERE ${column} IS NOT NULL AND ${conds.join(" AND ")}`,
    b.values
  );
  return { names: rows.slice(0, limit).map((r) => r.name), total: Number(total?.n ?? 0) };
}

export async function distinctCountries(): Promise<string[]> {
  const rows = await query<{ country_code: string }>(
    "SELECT DISTINCT country_code FROM dmf_master WHERE country_code IS NOT NULL AND country_code <> ''"
  );
  const set = new Set<string>();
  for (const r of rows)
    r.country_code.split(/[,/;]/).forEach((c) => c.trim() && set.add(c.trim()));
  return [...set].sort((a, b) => a.localeCompare(b, "ko"));
}

export async function availableSnapshots(): Promise<string[]> {
  const rows = await query<{ snapshot_ym: string }>(
    "SELECT DISTINCT snapshot_ym FROM change_history_log ORDER BY 1 DESC"
  );
  return rows.map((r) => r.snapshot_ym);
}

// ---------------------------------------------------------------------------
// 종합 현황
// ---------------------------------------------------------------------------
export type Kpi = {
  snapshot: string | null;
  activeDmf: number;
  totalDmf: number;
  overseasDmf: number;
  overseasRatio: number;
  countries: number;
  finishedItems: number;
  linkedCompanies: number;
  newDmf: number;
  newFinished: number;
  modified: number;
  cancelled: number;
};

export async function fetchKpi(snapshot: string | null): Promise<Kpi> {
  const base = await queryOne<Record<string, string>>(`
    SELECT
      (SELECT COUNT(*) FROM dmf_master WHERE status='ACTIVE')                     AS active_dmf,
      (SELECT COUNT(*) FROM dmf_master)                                           AS total_dmf,
      (SELECT COUNT(*) FROM dmf_master
        WHERE status='ACTIVE' AND coalesce(country_code,'') <> '대한민국')        AS overseas,
      (SELECT COUNT(DISTINCT item_seq) FROM finished_drug_master
        WHERE item_status='정상')                                                 AS fin_items,
      (SELECT COUNT(DISTINCT p.company_name)
         FROM finished_drug_master p
         JOIN (SELECT DISTINCT norm_base_key FROM dmf_master WHERE status='ACTIVE') d
           ON p.norm_base_key = d.norm_base_key
        WHERE p.item_status='정상')                                               AS linked_companies`);

  const changes = snapshot
    ? await queryOne<Record<string, string>>(
        `SELECT
           COUNT(*) FILTER (WHERE target_type='DMF' AND change_type='NEW')        AS new_dmf,
           COUNT(DISTINCT target_id) FILTER (WHERE target_type='FINISHED' AND change_type='NEW') AS new_fin,
           COUNT(DISTINCT target_id) FILTER (WHERE change_type='MODIFIED')        AS modified,
           COUNT(DISTINCT target_id) FILTER (WHERE change_type='CANCELLED')       AS cancelled
         FROM change_history_log WHERE snapshot_ym = $1`,
        [snapshot]
      )
    : null;

  const countries = await distinctCountries();
  const n = (r: Record<string, string> | null, k: string) => Number(r?.[k] ?? 0);
  const active = n(base, "active_dmf");
  const overseas = n(base, "overseas");

  return {
    snapshot,
    activeDmf: active,
    totalDmf: n(base, "total_dmf"),
    overseasDmf: overseas,
    overseasRatio: active ? (overseas / active) * 100 : 0,
    countries: countries.length,
    finishedItems: n(base, "fin_items"),
    linkedCompanies: n(base, "linked_companies"),
    newDmf: n(changes, "new_dmf"),
    newFinished: n(changes, "new_fin"),
    modified: n(changes, "modified"),
    cancelled: n(changes, "cancelled"),
  };
}

export type CountryRow = { country: string; dmfCount: number; manufacturers: number };

export async function fetchCountryBreakdown(activeOnly = true): Promise<CountryRow[]> {
  const rows = await query<{ country: string; dmf_count: string; mfr: string }>(
    `SELECT trim(c)                       AS country,
            COUNT(*)                      AS dmf_count,
            COUNT(DISTINCT manufacturer_name) AS mfr
       FROM dmf_master,
            LATERAL unnest(string_to_array(coalesce(country_code,'(미상)'), ',')) AS c
      ${activeOnly ? "WHERE status='ACTIVE'" : ""}
      GROUP BY 1 ORDER BY 2 DESC`
  );
  return rows.map((r) => ({
    country: r.country || "(미상)",
    dmfCount: Number(r.dmf_count),
    manufacturers: Number(r.mfr),
  }));
}

export type IngredientRow = {
  ingredient: string;
  manufacturers: number;
  dmfCount: number;
  companies: number;
};

/** 성분별 공급망 규모. 원료 제조소가 1곳뿐인 성분을 찾는 데 쓴다. */
export async function fetchIngredientSummary(
  singleSourceOnly: boolean,
  limit = 300
): Promise<IngredientRow[]> {
  return (
    await query<Record<string, string>>(
      `WITH d AS (SELECT * FROM dmf_master WHERE status='ACTIVE' AND coalesce(norm_base_key,'') <> '')
       SELECT max(d.ingredient_name_kr)          AS ingredient,
              COUNT(DISTINCT d.manufacturer_name) AS mfr,
              COUNT(DISTINCT d.dmf_id)            AS dmf_count,
              COUNT(DISTINCT p.company_name)      AS companies
         FROM d
         LEFT JOIN finished_drug_master p
                ON p.norm_base_key = d.norm_base_key AND p.item_status='정상'
        GROUP BY d.norm_base_key
        ${singleSourceOnly ? "HAVING COUNT(DISTINCT d.manufacturer_name) = 1" : ""}
        ORDER BY 2 DESC, 3 DESC
        LIMIT ${limit}`
    )
  ).map((r) => ({
    ingredient: r.ingredient,
    manufacturers: Number(r.mfr),
    dmfCount: Number(r.dmf_count),
    companies: Number(r.companies),
  }));
}

// ---------------------------------------------------------------------------
// 변경 이력
// ---------------------------------------------------------------------------
export type ChangeRow = {
  snapshot_ym: string;
  target_type: string;
  target_id: string;
  target_label: string;
  change_type: string;
  field_name: string;
  before_val: string;
  after_val: string;
};

export async function fetchChanges(
  snapshot: string | null,
  targets: string[],
  types: string[],
  limit = 1000
): Promise<ChangeRow[]> {
  const b = new Binder();
  const where: string[] = [];
  if (snapshot) where.push(`snapshot_ym = ${b.add(snapshot)}`);
  if (targets.length) where.push(`target_type = ANY(${b.add(targets)}::text[])`);
  if (types.length) where.push(`change_type = ANY(${b.add(types)}::text[])`);
  return query<ChangeRow>(
    `SELECT snapshot_ym, target_type, target_id, coalesce(target_label,'') AS target_label,
            change_type, coalesce(field_name,'') AS field_name,
            coalesce(before_val,'') AS before_val, coalesce(after_val,'') AS after_val
       FROM change_history_log
      ${where.length ? "WHERE " + where.join(" AND ") : ""}
      ORDER BY snapshot_ym DESC, target_type, target_id
      LIMIT ${limit}`,
    b.values
  );
}

export async function countChanges(
  snapshot: string | null,
  targets: string[],
  types: string[]
): Promise<number> {
  const b = new Binder();
  const where: string[] = [];
  if (snapshot) where.push(`snapshot_ym = ${b.add(snapshot)}`);
  if (targets.length) where.push(`target_type = ANY(${b.add(targets)}::text[])`);
  if (types.length) where.push(`change_type = ANY(${b.add(types)}::text[])`);
  const row = await queryOne<{ n: string }>(
    `SELECT COUNT(*) AS n FROM change_history_log ${
      where.length ? "WHERE " + where.join(" AND ") : ""
    }`,
    b.values
  );
  return Number(row?.n ?? 0);
}
