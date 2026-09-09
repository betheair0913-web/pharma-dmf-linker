import { ReactNode } from "react";
import NavMenu from "./NavMenu";

/**
 * 좌측 사이드바 + 본문 레이아웃.
 * 사이드바는 항상 표시된다 (접기 버튼 없음).
 * 페이지별 필터는 sidebar 슬롯으로 받아 메뉴 아래에 붙인다.
 */
export default function Shell({
  sidebar,
  title,
  subtitle,
  icon,
  children,
}: {
  sidebar?: ReactNode;
  title: string;
  subtitle?: string;
  icon?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <aside className="w-[268px] shrink-0 bg-sidebar text-sidebar-text border-r border-[#141c2b] sticky top-0 max-h-screen overflow-y-auto">
        <div className="px-4 py-4 flex items-center gap-2 border-b border-sidebar-line">
          <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary text-white">
            💊
          </span>
          <span className="text-[0.8rem] font-semibold text-[#eef2f8] leading-tight">
            원료의약품등록
            <br />
            모니터링 시스템
          </span>
        </div>
        <NavMenu />
        {sidebar ? (
          <div className="px-4 pb-8 border-t border-sidebar-line pt-3">{sidebar}</div>
        ) : null}
      </aside>

      <main className="flex-1 min-w-0 p-5 space-y-4">
        <header className="rounded-xl bg-surface border border-line px-5 py-3.5 flex items-baseline gap-3">
          <h1 className="text-[1.05rem] font-bold text-text">
            {icon ? <span className="mr-1.5">{icon}</span> : null}
            {title}
          </h1>
          {subtitle ? (
            <p className="text-[0.79rem] text-muted">{subtitle}</p>
          ) : null}
        </header>
        {children}
      </main>
    </div>
  );
}
