/** Postgres 에 아직 데이터가 없을 때의 안내. */
export default function NoData() {
  return (
    <div className="rounded-xl border border-line bg-surface p-6 text-[0.85rem] leading-relaxed">
      <p className="font-semibold">📥 아직 적재된 데이터가 없습니다.</p>
      <p className="mt-2 text-muted">
        공공데이터 수집은 로컬 Streamlit 앱이 담당합니다. 수집을 끝낸 뒤 아래 명령으로
        결과를 이 배포본의 Postgres 로 올리세요.
      </p>
      <pre className="mt-3 overflow-x-auto rounded-lg bg-[#1b2537] p-3 text-[0.75rem] text-[#c7cedb]">
{`vercel env pull web/.env.local
pip install "psycopg[binary]"
python scripts/push_to_postgres.py`}
      </pre>
    </div>
  );
}
