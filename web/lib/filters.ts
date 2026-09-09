/**
 * 필터 상태는 URL 쿼리스트링에 담는다.
 * 화면 상태를 서버 컴포넌트가 그대로 읽을 수 있고, 조회 결과 링크를 그대로
 * 공유할 수 있다. (Streamlit 판에서는 세션 상태였던 부분)
 */

export const SEARCH_FIELDS = {
  성분명: {
    dmf: ["ingredient_name_kr", "ingredient_name_en"],
    fin: ["ingredient_name_kr"],
  },
  "원료 제조소": { dmf: ["manufacturer_name", "address"], fin: [] },
  "DMF 등록업체": { dmf: ["registrant_name"], fin: [] },
  "완제 제약사": { dmf: [], fin: ["company_name", "company_name_en"] },
  완제품명: { dmf: [], fin: ["product_name", "product_name_en"] },
  "등록번호·품목코드": { dmf: ["dmf_id"], fin: ["item_seq"] },
} as const;

export type SearchFieldName = keyof typeof SEARCH_FIELDS;

export const CHANGE_TYPES = ["NEW", "MODIFIED", "CANCELLED"] as const;
export const PAGE_SIZES = [100, 500, 1000] as const;

export type Filter = {
  keyword: string;
  searchFields: SearchFieldName[];
  manufacturerQuery: string;
  companyQuery: string;
  matchMode: "BASE" | "EXACT";
  dmfActiveOnly: boolean;
  finishedActiveOnly: boolean;
  countryScope: "전체" | "국내" | "해외";
  countries: string[];
  dmfDateFrom: string;
  dmfDateTo: string;
  permitDateFrom: string;
  permitDateTo: string;
  changeTypes: string[];
  changeSnapshot: string;
  page: number;
  pageSize: number;
};

export type SearchParams = Record<string, string | string[] | undefined>;

/**
 * 같은 키가 여러 번 오면 마지막 값을 쓴다.
 * 체크박스는 hidden "0" 다음에 checkbox "1" 순서로 보내므로,
 * 체크됐을 때만 마지막 값이 "1" 이 된다.
 */
function one(sp: SearchParams, key: string): string {
  const v = sp[key];
  const raw = Array.isArray(v) ? v[v.length - 1] : v;
  return raw?.trim() ?? "";
}

/** 다중 선택은 키가 반복되거나 콤마로 묶여 올 수 있다. 둘 다 받는다. */
function many(sp: SearchParams, key: string): string[] {
  const v = sp[key];
  const arr = Array.isArray(v) ? v : v ? [v] : [];
  return arr
    .flatMap((s) => s.split(","))
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 체크박스류는 값이 없으면 기본값(주로 켜짐)으로 본다. */
function flag(sp: SearchParams, key: string, fallback: boolean): boolean {
  const raw = one(sp, key);
  return raw === "" ? fallback : raw === "1";
}

export function parseFilter(sp: SearchParams): Filter {
  const size = Number(one(sp, "size"));
  const page = Number(one(sp, "page"));
  const scope = one(sp, "scope");
  return {
    keyword: one(sp, "q"),
    searchFields: many(sp, "sf").filter(
      (f): f is SearchFieldName => f in SEARCH_FIELDS
    ),
    manufacturerQuery: one(sp, "mfrq"),
    companyQuery: one(sp, "compq"),
    matchMode: one(sp, "mm") === "EXACT" ? "EXACT" : "BASE",
    dmfActiveOnly: flag(sp, "da", true),
    finishedActiveOnly: flag(sp, "fa", true),
    countryScope: scope === "국내" || scope === "해외" ? scope : "전체",
    countries: many(sp, "ctry"),
    dmfDateFrom: one(sp, "dfrom"),
    dmfDateTo: one(sp, "dto"),
    permitDateFrom: one(sp, "pfrom"),
    permitDateTo: one(sp, "pto"),
    changeTypes: many(sp, "ct").filter((c) =>
      (CHANGE_TYPES as readonly string[]).includes(c)
    ),
    changeSnapshot: one(sp, "snap"),
    page: Number.isFinite(page) && page > 0 ? Math.floor(page) : 1,
    pageSize: (PAGE_SIZES as readonly number[]).includes(size) ? size : 100,
  };
}

/** 필터를 다시 쿼리스트링으로. 기본값은 URL 을 짧게 두려고 생략한다. */
export function toSearchParams(f: Partial<Filter>): URLSearchParams {
  const p = new URLSearchParams();
  const put = (k: string, v: string) => v && p.set(k, v);
  put("q", f.keyword ?? "");
  put("sf", (f.searchFields ?? []).join(","));
  put("mfrq", f.manufacturerQuery ?? "");
  put("compq", f.companyQuery ?? "");
  if (f.matchMode === "EXACT") p.set("mm", "EXACT");
  if (f.dmfActiveOnly === false) p.set("da", "0");
  if (f.finishedActiveOnly === false) p.set("fa", "0");
  if (f.countryScope && f.countryScope !== "전체") p.set("scope", f.countryScope);
  put("ctry", (f.countries ?? []).join(","));
  put("dfrom", f.dmfDateFrom ?? "");
  put("dto", f.dmfDateTo ?? "");
  put("pfrom", f.permitDateFrom ?? "");
  put("pto", f.permitDateTo ?? "");
  put("ct", (f.changeTypes ?? []).join(","));
  put("snap", f.changeSnapshot ?? "");
  if (f.pageSize && f.pageSize !== 100) p.set("size", String(f.pageSize));
  if (f.page && f.page > 1) p.set("page", String(f.page));
  return p;
}

/**
 * 업체명 부분 검색어를 소문자 토큰으로 쪼갠다.
 * 공백으로 나눈 토큰을 모두 포함하는 업체만 걸리게 해(AND),
 * 'zhejiang hongyuan' 한 번으로 'Co., Ltd.' 와 'Co.,Ltd.' 표기를 함께 잡는다.
 */
export function nameTokens(query: string): string[] {
  return query.toLowerCase().replace(/,/g, " ").split(/\s+/).filter(Boolean);
}

/**
 * 통합 검색어 파싱. 공백=AND, "따옴표"=구문 그대로, |=OR.
 * 반환값은 AND 로 묶이는 그룹의 배열이고, 그룹 안 항목끼리는 OR 다.
 */
export function parseSearch(keyword: string): string[][] {
  const text = keyword.trim();
  if (!text) return [];
  const tokens = text.match(/"[^"]*"|[^\s]+/g) ?? [];
  const groups: string[][] = [];
  let pending: string[] = [];
  let expectAlternative = false;

  const clean = (t: string) => t.replace(/^"|"$/g, "").trim().toLowerCase();

  for (const raw of tokens) {
    if (raw === "|") {
      expectAlternative = true;
      continue;
    }
    const parts = raw.split("|");
    for (let i = 0; i < parts.length; i++) {
      const value = clean(parts[i]);
      if (!value) {
        if (parts.length > 1) expectAlternative = true;
        continue;
      }
      if (expectAlternative || (i > 0 && pending.length)) {
        pending.push(value);
      } else {
        if (pending.length) groups.push(pending);
        pending = [value];
      }
      expectAlternative = i < parts.length - 1;
    }
  }
  if (pending.length) groups.push(pending);
  return groups;
}
