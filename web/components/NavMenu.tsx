"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** 메뉴 순서: 상세 조회 -> 종합 현황 -> 변경 이력 */
const ITEMS = [
  { href: "/", label: "상세 조회", icon: "🔗" },
  { href: "/overview", label: "종합 현황", icon: "📊" },
  { href: "/changes", label: "변경 이력", icon: "🕒" },
];

export default function NavMenu() {
  const pathname = usePathname();
  return (
    <nav className="px-3 py-3">
      <p className="px-2 pb-1 text-[0.68rem] uppercase tracking-wide text-sidebar-muted">
        메뉴
      </p>
      <ul className="space-y-0.5">
        {ITEMS.map((item) => {
          const active = pathname === item.href;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                className={`flex items-center gap-2 rounded-lg px-2.5 py-2 text-[0.82rem] transition-colors ${
                  active
                    ? "bg-[#22304a] text-white font-semibold"
                    : "text-sidebar-text hover:bg-[#1f2a3d]"
                }`}
              >
                <span>{item.icon}</span>
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
