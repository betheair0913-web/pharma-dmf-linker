import { neon } from "@neondatabase/serverless";

/**
 * Neon 커넥션. 모듈 최상위에서 만들면 DATABASE_URL 이 아직 없는 첫 빌드에서
 * 터지므로, 처음 질의할 때 만들고 재사용한다.
 */
let client: ReturnType<typeof neon> | null = null;

function sql() {
  if (!client) {
    const url = process.env.DATABASE_URL;
    if (!url) throw new Error("DATABASE_URL 이 설정되지 않았습니다.");
    client = neon(url);
  }
  return client;
}

/** 파라미터 바인딩 질의. $1, $2 … 자리표시자를 쓴다. */
export async function query<T = Record<string, unknown>>(
  text: string,
  params: unknown[] = []
): Promise<T[]> {
  const rows = await sql().query(text, params);
  return rows as T[];
}

/** 한 행만 필요한 집계 질의용. */
export async function queryOne<T = Record<string, unknown>>(
  text: string,
  params: unknown[] = []
): Promise<T | null> {
  const rows = await query<T>(text, params);
  return rows[0] ?? null;
}

/** 데이터가 적재돼 있는지. 미적재 상태에서 안내 문구를 띄우는 데 쓴다. */
export async function hasData(): Promise<boolean> {
  try {
    const row = await queryOne<{ n: number }>(
      "SELECT (SELECT COUNT(*) FROM dmf_master) + (SELECT COUNT(*) FROM finished_drug_master) AS n"
    );
    return Number(row?.n ?? 0) > 0;
  } catch {
    return false;
  }
}
