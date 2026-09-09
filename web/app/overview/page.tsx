import Shell from "@/components/Shell";
import StatCards from "@/components/StatCards";
import NoData from "@/components/NoData";
import { hasData } from "@/lib/db";
import {
  fetchCountryBreakdown,
  fetchIngredientSummary,
  fetchKpi,
  latestSnapshot,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function OverviewPage({ searchParams }: PageProps<"/overview">) {
  const sp = await searchParams;
  const singleSource = sp.single === "1";

  if (!(await hasData())) {
    return (
      <Shell title="종합 현황" icon="📊">
        <NoData />
      </Shell>
    );
  }

  const snapshot = await latestSnapshot();
  const [kpi, countries, ingredients] = await Promise.all([
    fetchKpi(snapshot),
    fetchCountryBreakdown(true),
    fetchIngredientSummary(singleSource),
  ]);

  const topCountry = countries[0]?.dmfCount ?? 1;

  return (
    <Shell
      title="종합 현황"
      icon="📊"
      subtitle={`기준 스냅샷 ${kpi.snapshot ?? "(없음)"} · 유효 DMF 기준 집계`}
    >
      <StatCards
        items={[
          { label: "유효 DMF", value: kpi.activeDmf, unit: "건", hint: `전체 등록 ${kpi.totalDmf.toLocaleString()}건` },
          { label: "해외 제조소 비율", value: `${kpi.overseasRatio.toFixed(1)}%`, hint: `해외 ${kpi.overseasDmf.toLocaleString()}건` },
          { label: "제조국", value: kpi.countries, unit: "개국" },
          { label: "연계 제약사", value: kpi.linkedCompanies, unit: "개사", hint: "성분 골격이 일치하는 완제 제약사" },
          { label: "완제 허가품목", value: kpi.finishedItems, unit: "건", hint: "품목 상태 정상" },
        ]}
      />
      <StatCards
        items={[
          { label: "당월 신규 DMF", value: kpi.newDmf, unit: "건" },
          { label: "당월 신규 완제", value: kpi.newFinished, unit: "건" },
          { label: "당월 변경", value: kpi.modified, unit: "건" },
          { label: "당월 취하", value: kpi.cancelled, unit: "건" },
        ]}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-line bg-surface">
          <h2 className="border-b border-line px-4 py-3 text-[0.9rem] font-semibold">
            제조국 분포
          </h2>
          <div className="max-h-[46vh] overflow-auto p-4">
            <ul className="space-y-2">
              {countries.slice(0, 25).map((c) => (
                <li key={c.country} className="text-[0.79rem]">
                  <div className="flex justify-between">
                    <span>{c.country}</span>
                    <span className="text-muted">
                      {c.dmfCount.toLocaleString()}건 · 제조소 {c.manufacturers.toLocaleString()}곳
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 rounded bg-[#eef2f8]">
                    <div
                      className="h-1.5 rounded bg-primary"
                      style={{ width: `${Math.max(2, (c.dmfCount / topCountry) * 100)}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="rounded-xl border border-line bg-surface">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="text-[0.9rem] font-semibold">성분별 공급망 규모</h2>
            <a
              href={singleSource ? "/overview" : "/overview?single=1"}
              className={`rounded-lg border px-2.5 py-1 text-[0.72rem] ${
                singleSource
                  ? "border-primary bg-primary text-white"
                  : "border-line text-muted hover:border-primary hover:text-primary"
              }`}
            >
              원료 제조소 1곳뿐인 성분만
            </a>
          </div>
          <div className="max-h-[46vh] overflow-auto">
            <table className="grid-table w-full">
              <thead>
                <tr>
                  <th>성분명</th>
                  <th>원료 제조소</th>
                  <th>DMF</th>
                  <th>완제 제약사</th>
                </tr>
              </thead>
              <tbody>
                {ingredients.map((r) => (
                  <tr key={r.ingredient}>
                    <td title={r.ingredient}>{r.ingredient}</td>
                    <td>{r.manufacturers.toLocaleString()}</td>
                    <td>{r.dmfCount.toLocaleString()}</td>
                    <td>{r.companies.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </Shell>
  );
}
