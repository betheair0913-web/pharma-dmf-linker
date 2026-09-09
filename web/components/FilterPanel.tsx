import Link from "next/link";
import { CHANGE_TYPES, Filter, SEARCH_FIELDS } from "@/lib/filters";

/**
 * 사이드바 필터. 순수 GET 폼이라 자바스크립트 없이도 동작하고,
 * 조회 상태가 그대로 URL 에 남아 링크로 공유할 수 있다.
 *
 * 체크박스는 hidden "0" + checkbox "1" 짝으로 보낸다.
 * 체크를 풀었을 때 값이 아예 빠져 기본값(켜짐)으로 되돌아가는 것을 막는다.
 */
export default function FilterPanel({
  filter,
  countries,
  snapshots,
  manufacturerMatches,
  companyMatches,
}: {
  filter: Filter;
  countries: string[];
  snapshots: string[];
  manufacturerMatches: { names: string[]; total: number };
  companyMatches: { names: string[]; total: number };
}) {
  return (
    <form method="get" action="/" className="space-y-3">
      <div className="flex items-center justify-between pt-1">
        <h2 className="text-[0.9rem] font-semibold text-[#eef2f8]">🔎 필터</h2>
        <Link
          href="/"
          className="rounded-lg border border-sidebar-line px-2 py-1 text-[0.72rem] text-sidebar-muted hover:border-primary hover:text-white"
          title="입력한 검색어·업체·국가·기간을 모두 지우고 기본값으로 되돌립니다."
        >
          초기화
        </Link>
      </div>

      <div>
        <label className="sb-label" htmlFor="q">
          통합 검색
        </label>
        <input
          id="q"
          name="q"
          defaultValue={filter.keyword}
          className="sb-input"
          placeholder='예: anhui poly / "anhui poly" / 인도 | 중국'
        />
        <p className="mt-1 text-[0.68rem] text-sidebar-muted">
          공백=AND, &quot;따옴표&quot;=구문, | =OR
        </p>
      </div>

      <div>
        <label className="sb-label" htmlFor="sf">
          검색 대상
        </label>
        <select
          id="sf"
          name="sf"
          multiple
          size={3}
          defaultValue={filter.searchFields}
          className="sb-select"
        >
          {Object.keys(SEARCH_FIELDS).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <p className="mt-1 text-[0.68rem] text-sidebar-muted">
          선택하지 않으면 전체 항목에서 검색
        </p>
      </div>

      <p className="sb-section">업체 지정</p>

      <div>
        <label className="sb-label" htmlFor="mfrq">
          원료 제조소 이름
        </label>
        <input
          id="mfrq"
          name="mfrq"
          defaultValue={filter.manufacturerQuery}
          className="sb-input"
          placeholder="예: zhejiang hongyuan"
        />
        <MatchPreview label="제조소" matches={manufacturerMatches} query={filter.manufacturerQuery} />
      </div>

      <div>
        <label className="sb-label" htmlFor="compq">
          완제 제약사 이름
        </label>
        <input
          id="compq"
          name="compq"
          defaultValue={filter.companyQuery}
          className="sb-input"
          placeholder="예: 한미약품"
        />
        <MatchPreview label="제약사" matches={companyMatches} query={filter.companyQuery} />
      </div>

      <p className="sb-section">상태 필터</p>
      <Check name="da" label="DMF 유효만 보기" checked={filter.dmfActiveOnly} />
      <Check
        name="fa"
        label="완제 허가품목(정상)만 보기"
        checked={filter.finishedActiveOnly}
      />

      <p className="sb-section">제조국</p>
      <div>
        <label className="sb-label" htmlFor="scope">
          제조 구분
        </label>
        <select id="scope" name="scope" defaultValue={filter.countryScope} className="sb-select">
          <option value="전체">전체</option>
          <option value="국내">국내</option>
          <option value="해외">해외</option>
        </select>
      </div>
      <div>
        <label className="sb-label" htmlFor="ctry">
          국가 선택 (다중)
        </label>
        <select
          id="ctry"
          name="ctry"
          multiple
          size={4}
          defaultValue={filter.countries}
          className="sb-select"
        >
          {countries.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <p className="sb-section">성분 매칭 방식</p>
      <select name="mm" defaultValue={filter.matchMode} className="sb-select">
        <option value="BASE">골격 일치(권장)</option>
        <option value="EXACT">염 표기까지 일치</option>
      </select>
      <p className="text-[0.68rem] text-sidebar-muted">
        위의 검색어와는 무관합니다. DMF 원료와 완제 주성분을 연결할 때 성분명을 어느
        수준까지 같다고 볼지 정합니다.
      </p>

      <p className="sb-section">기간 필터</p>
      <div className="grid grid-cols-2 gap-2">
        <DateField name="dfrom" label="DMF 등록일 ≥" value={filter.dmfDateFrom} />
        <DateField name="dto" label="DMF 등록일 ≤" value={filter.dmfDateTo} />
        <DateField name="pfrom" label="완제 허가일 ≥" value={filter.permitDateFrom} />
        <DateField name="pto" label="완제 허가일 ≤" value={filter.permitDateTo} />
      </div>

      <p className="sb-section">변동사항 필터</p>
      <div>
        <label className="sb-label" htmlFor="snap">
          기준 스냅샷
        </label>
        <select id="snap" name="snap" defaultValue={filter.changeSnapshot} className="sb-select">
          <option value="">최신</option>
          {snapshots.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="sb-label" htmlFor="ct">
          변동 유형
        </label>
        <select
          id="ct"
          name="ct"
          multiple
          size={3}
          defaultValue={filter.changeTypes}
          className="sb-select"
        >
          {CHANGE_TYPES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="sb-label" htmlFor="size">
          페이지당 행
        </label>
        <select id="size" name="size" defaultValue={String(filter.pageSize)} className="sb-select">
          {[100, 500, 1000].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </div>

      <button
        type="submit"
        className="w-full rounded-lg bg-primary py-2 text-[0.82rem] font-semibold text-white hover:brightness-110"
      >
        조회
      </button>
    </form>
  );
}

function Check({
  name,
  label,
  checked,
}: {
  name: string;
  label: string;
  checked: boolean;
}) {
  return (
    <label className="flex items-center gap-2 text-[0.78rem] text-sidebar-text">
      <input type="hidden" name={name} value="0" />
      <input type="checkbox" name={name} value="1" defaultChecked={checked} className="accent-[#2f6fe4]" />
      {label}
    </label>
  );
}

function DateField({
  name,
  label,
  value,
}: {
  name: string;
  label: string;
  value: string;
}) {
  return (
    <div>
      <label className="sb-label" htmlFor={name}>
        {label}
      </label>
      <input id={name} name={name} type="date" defaultValue={value} className="sb-input" />
    </div>
  );
}

function MatchPreview({
  label,
  matches,
  query,
}: {
  label: string;
  matches: { names: string[]; total: number };
  query: string;
}) {
  if (!query.trim()) return null;
  if (!matches.total)
    return (
      <p className="mt-1 text-[0.7rem] text-[#e0a3a3]">
        ⚠️ 일치하는 {label}가 없습니다. 결과가 비게 됩니다.
      </p>
    );
  return (
    <details className="mt-1">
      <summary className="cursor-pointer text-[0.7rem] text-[#8fd3a6]">
        ✅ {label} {matches.total}곳 일치
      </summary>
      <ul className="mt-1 space-y-0.5 text-[0.68rem] text-sidebar-muted">
        {matches.names.map((n) => (
          <li key={n}>· {n}</li>
        ))}
        {matches.total > matches.names.length ? (
          <li>… 외 {matches.total - matches.names.length}곳</li>
        ) : null}
      </ul>
    </details>
  );
}
