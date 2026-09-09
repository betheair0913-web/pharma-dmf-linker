import Link from "next/link";
import FilterPanel from "@/components/FilterPanel";
import Shell from "@/components/Shell";
import StatCards from "@/components/StatCards";
import NoData from "@/components/NoData";
import { hasData } from "@/lib/db";
import { parseFilter, toSearchParams } from "@/lib/filters";
import {
  GRID_COLUMNS,
  availableSnapshots,
  distinctCountries,
  fetchGrid,
  fetchStats,
  latestSnapshot,
  matchingNames,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function DetailPage({ searchParams }: PageProps<"/">) {
  const sp = await searchParams;
  const filter = parseFilter(sp);

  if (!(await hasData())) {
    return (
      <Shell title="상세 조회" icon="🔗">
        <NoData />
      </Shell>
    );
  }

  const snapshot = filter.changeSnapshot || (await latestSnapshot());
  const [countries, snapshots, mfrMatches, compMatches, stats, rows] =
    await Promise.all([
      distinctCountries(),
      availableSnapshots(),
      matchingNames("dmf_master", "manufacturer_name", filter.manufacturerQuery),
      matchingNames("finished_drug_master", "company_name", filter.companyQuery),
      fetchStats(filter, snapshot),
      fetchGrid(filter, snapshot),
    ]);

  const totalPages = Math.max(1, Math.ceil(stats.rows / filter.pageSize));
  const pageHref = (page: number) => {
    const p = toSearchParams({ ...filter, page });
    return `/?${p.toString()}`;
  };
  const exportHref = `/api/export?${toSearchParams({ ...filter, page: 1 }).toString()}`;

  return (
    <Shell
      title="상세 조회"
      icon="🔗"
      subtitle="정규화된 성분 키로 DMF 원료와 완제의약품을 교차 결합한 결과입니다"
      sidebar={
        <FilterPanel
          filter={filter}
          countries={countries}
          snapshots={snapshots}
          manufacturerMatches={mfrMatches}
          companyMatches={compMatches}
        />
      }
    >
      <StatCards
        items={[
          { label: "매핑 레코드", value: stats.rows, unit: "건", hint: "현재 필터의 원료 x 완제 조합 수" },
          { label: "유효성분", value: stats.ingredients, unit: "종", hint: "염 표기가 다른 성분은 하나로 집계" },
          { label: "DMF 등록", value: stats.dmf_ids, unit: "건", hint: `연계 완제 품목 ${stats.products.toLocaleString()}건` },
          { label: "원료 제조소", value: stats.manufacturers, unit: "곳", hint: "중복 제거 기준" },
          { label: "완제 제약사", value: stats.companies, unit: "개사", hint: "제조·수입사 합계" },
        ]}
      />

      <section className="rounded-xl border border-line bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-[0.9rem] font-semibold">통합 매핑 그리드</h2>
            <p className="text-[0.72rem] text-muted">
              매칭 구성 — EXACT(염 표기까지 일치){" "}
              {stats.rows ? ((stats.exact / stats.rows) * 100).toFixed(1) : "0.0"}% · BASE(유효성분
              골격만 일치){" "}
              {stats.rows
                ? (((stats.rows - stats.exact) / stats.rows) * 100).toFixed(1)
                : "0.0"}
              %
            </p>
          </div>
          <a
            href={exportHref}
            className="rounded-lg border border-line px-3 py-1.5 text-[0.78rem] font-medium text-text hover:border-primary hover:text-primary"
          >
            ⬇ 현재 필터 CSV
          </a>
        </div>

        <div className="max-h-[62vh] overflow-auto">
          <table className="grid-table w-full">
            <thead>
              <tr>
                {GRID_COLUMNS.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row["DMF등록번호"]}-${row["품목기준코드"]}-${i}`}>
                  {GRID_COLUMNS.map((c) => (
                    <td key={c} title={row[c] ?? ""}>
                      {row[c]}
                    </td>
                  ))}
                </tr>
              ))}
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={GRID_COLUMNS.length} className="p-8 text-center text-muted">
                    조건에 맞는 결과가 없습니다. 좌측 필터를 완화하거나 초기화해 보세요.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5 text-[0.78rem] text-muted">
          <span>
            {stats.rows.toLocaleString()}건 중 {((filter.page - 1) * filter.pageSize + 1).toLocaleString()}–
            {Math.min(filter.page * filter.pageSize, stats.rows).toLocaleString()}행
          </span>
          <span className="flex items-center gap-2">
            <PageLink href={pageHref(filter.page - 1)} disabled={filter.page <= 1}>
              ‹ 이전
            </PageLink>
            <span>
              {filter.page} / {totalPages.toLocaleString()} 페이지
            </span>
            <PageLink href={pageHref(filter.page + 1)} disabled={filter.page >= totalPages}>
              다음 ›
            </PageLink>
          </span>
        </div>
      </section>
    </Shell>
  );
}

function PageLink({
  href,
  disabled,
  children,
}: {
  href: string;
  disabled: boolean;
  children: React.ReactNode;
}) {
  if (disabled)
    return <span className="rounded border border-line px-2 py-1 opacity-40">{children}</span>;
  return (
    <Link
      href={href}
      className="rounded border border-line px-2 py-1 hover:border-primary hover:text-primary"
    >
      {children}
    </Link>
  );
}
