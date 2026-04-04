"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  TrendingUp,
  Activity,
  Building2,
  Settings,
} from "lucide-react";

const NAV = [
  { href: "/", icon: LayoutDashboard, label: "Home" },
  { href: "/positions", icon: TrendingUp, label: "Positions" },
  { href: "/agents", icon: Activity, label: "Agents" },
  { href: "/office", icon: Building2, label: "Office" },
  { href: "/settings", icon: Settings, label: "Config" },
];

export default function MobileNav() {
  const path = usePathname();

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-[#0A0F0D]/95 backdrop-blur-lg border-t border-cyan-900/20 safe-area-bottom">
      <div className="flex items-center justify-around h-14">
        {NAV.map(({ href, icon: Icon, label }) => {
          const active = path === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex flex-col items-center justify-center gap-0.5 px-3 py-1.5 rounded-lg transition-colors min-w-[56px] ${
                active
                  ? "text-cyan-400"
                  : "text-slate-600 active:text-slate-400"
              }`}
            >
              <Icon size={20} strokeWidth={active ? 2.5 : 1.5} />
              <span className={`text-[9px] mono tracking-wider ${active ? "font-bold" : ""}`}>
                {label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
