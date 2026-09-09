import Shell from "@/components/Shell";
import NoData from "@/components/NoData";
import { hasData } from "@/lib/db";
import { CHANGE_TYPES } from "@/lib/filters";
import {
  availableSnapshots,
  countChanges,
  fetchChanges,
  latestSnapshot,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

const LIMIT = 1000;
const TARGETS = ["DMF", "FINISHED"] as const;

function list(v: string | string[] | undefined): string[] {
  const arr = Array.isArray(v) ? v : v ? [v] : [];
  return arr.flatMap((s) => s.split(",")).map((s) => s.trim()).filter(Boolean);
}

export default async function ChangesPage({ searchParams }: PageProps<"/changes">) {
  const sp = await searchParams;

  if (!(await hasData())) {
    return (
      <Shell title="변경 이력" icon="🕒">
        <NoData />
      </Shell>
    );
  }

  const snapshots = await availableSnapshots();
  const picked = (Array.isArray(sp.snap) ? sp.snap[0] : sp.snap) ?? "";
  const snapshot = picked || (await latestSnapshot());
  const targets = list(sp.tt);
  const types = list(sp.ct);

  const [rows, total] = await Promise.all([
    fetchChanges(snapshot, targets, types, LIMIT),
    countChanges(snapshot, targets, types),
  ]);

  return (
    <Shell
      title="변경 이력"
      icon="🕒"
      subtitle="스냅샷 간 비교로 감지한 신규·변경·취하 내역입니다"
      sidebar={
        <form method="get" action="/changes" className="space-y-3">
          <h2 className="pt-1 text-[0.9rem] font-semibold text-[#eef2f8]">🔎 필터</h2>
          <div>
            <label className="sb-label" htmlFor="snap">
              기준 스냅샷
            </label>
            <select id="snap" name="snap" defaultValue={picked} className="sb-select">
              <option value="">최신</option>
              {snapshots.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="sb-label" htmlFor="tt">
              대상
            </label>
            <select id="tt" name="tt" multiple size={2} defaultValue={targets} className="sb-select">
              <option value="DMF">DMF 원료</option>
              <option value="FINISHED">완제 품목</option>
            </select>
          </div>
          <div>
            <label className="sb-label" htmlFor="ct">
              변동 유형
            </label>
            <select id="ct" name="ct" multiple size={3} defaultValue={types} className="sb-select">
              {CHANGE_TYPES.map((c) => (
                <option key={c} value={c}>
                  {c}
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
      }
    >
      <section className="rounded-xl border border-line bg-surface">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-[0.9rem] font-semibold">
            {snapshot ?? "(스냅샷 없음)"} · {total.toLocaleString()}건
          </h2>
          {total > LIMIT ? (
            <p className="text-[0.72rem] text-muted">
              화면에는 최근 {LIMIT.toLocaleString()}건만 표시합니다.
            </p>
          ) : null}
        </div>
        <div className="max-h-[70vh] overflow-auto">
          <table className="grid-table w-full">
            <thead>
              <tr>
                <th>스냅샷</th>
                <th>대상</th>
                <th>대상 ID</th>
                <th>대상명</th>
                <th>변동</th>
                <th>항목</th>
                <th>이전</th>
                <th>이후</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.target_type}-${r.target_id}-${r.field_name}-${i}`}>
                  <td>{r.snapshot_ym}</td>
                  <td>{r.target_type === "DMF" ? "DMF 원료" : "완제 품목"}</td>
                  <td>{r.target_id}</td>
                  <td title={r.target_label}>{r.target_label}</td>
                  <td>{r.change_type}</td>
                  <td>{r.field_name}</td>
                  <td title={r.before_val}>{r.before_val}</td>
                  <td title={r.after_val}>{r.after_val}</td>
                </tr>
              ))}
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="p-8 text-center text-muted">
                    해당 조건의 변경 이력이 없습니다.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </Shell>
  );
}
