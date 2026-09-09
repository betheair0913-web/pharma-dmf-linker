/** 상단 KPI 카드 줄. */
export default function StatCards({
  items,
}: {
  items: { label: string; value: number | string; unit?: string; hint?: string }[];
}) {
  return (
    <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(190px,1fr))]">
      {items.map((it) => (
        <div key={it.label} className="rounded-xl border border-line bg-surface px-4 py-3">
          <p className="text-[0.72rem] font-medium text-muted">{it.label}</p>
          <p className="mt-1 text-[1.35rem] font-bold text-primary">
            {typeof it.value === "number" ? it.value.toLocaleString() : it.value}
            {it.unit ? (
              <span className="ml-0.5 text-[0.78rem] font-medium text-text">{it.unit}</span>
            ) : null}
          </p>
          {it.hint ? <p className="mt-0.5 text-[0.68rem] text-muted">{it.hint}</p> : null}
        </div>
      ))}
    </div>
  );
}
