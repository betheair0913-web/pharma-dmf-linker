import { NextRequest } from "next/server";
import { parseFilter } from "@/lib/filters";
import { GRID_COLUMNS, fetchAllRows, latestSnapshot } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

/** 서버리스 함수 응답 시간과 메모리를 고려한 상한. */
const EXPORT_LIMIT = 200_000;

/** 현재 필터 결과를 CSV 로 내려준다. 엑셀용으로 BOM 을 붙인다. */
export async function GET(req: NextRequest) {
  const sp = Object.fromEntries(req.nextUrl.searchParams.entries());
  const filter = parseFilter(sp);
  const snapshot = filter.changeSnapshot || (await latestSnapshot());
  const rows = await fetchAllRows(filter, snapshot, EXPORT_LIMIT);

  const escape = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const body =
    "﻿" +
    [
      GRID_COLUMNS.join(","),
      ...rows.map((r) => GRID_COLUMNS.map((c) => escape(r[c])).join(",")),
    ].join("\r\n");

  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  return new Response(body, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="DMF_mapping_${stamp}.csv"`,
      "Cache-Control": "no-store",
    },
  });
}
