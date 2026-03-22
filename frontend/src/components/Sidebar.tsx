"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  TrendingUp,
  Settings,
  Activity,
  Radio,
  ChevronLeft,
  ChevronRight,
  Building2,
} from "lucide-react";

const NAV = [
  { href: "/", icon: LayoutDashboard, label: "OVERWATCH" },
  { href: "/positions", icon: TrendingUp, label: "POSITIONS" },
  { href: "/agents", icon: Activity, label: "AGENTS" },
  { href: "/office", icon: Building2, label: "OFFICE" },
  { href: "/settings", icon: Settings, label: "CONFIG" },
];

export default function Sidebar() {
  const path = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={`h-full bg-[#0A0F0D] border-r border-cyan-900/20 flex flex-col transition-all duration-300 shrink-0 ${collapsed ? "w-14" : "w-48"}`}
    >
      <div className="px-3 py-4 border-b border-cyan-900/20 flex items-center gap-2">
        <Radio size={18} className="text-cyan-400 shrink-0 animate-pulse" />
        {!collapsed && (
          <span className="text-sm font-black tracking-widest neon-text-cyan mono">
            M-CEX
          </span>
        )}
      </div>

      <nav className="flex-1 py-3 space-y-0.5 px-2">
        {NAV.map(({ href, icon: Icon, label }) => {
          const active = path === href;
          return (
            <Link
              key={href}
              href={href}
              title={label}
              className={`flex items-center gap-2.5 px-2.5 py-2 text-xs mono tracking-wider transition-all ${
                active
                  ? "bg-cyan-500/10 text-cyan-400 border-l-2 border-cyan-400"
                  : "text-slate-500 hover:text-slate-300 hover:bg-white/[0.02] border-l-2 border-transparent"
              }`}
            >
              <Icon size={14} className="shrink-0" />
              {!collapsed && <span>{label}</span>}
            </Link>
          );
        })}

      </nav>

      <button
        onClick={() => setCollapsed((c) => !c)}
        className="p-3 border-t border-cyan-900/20 text-slate-600 hover:text-cyan-400 transition-colors flex justify-center"
        title={collapsed ? "Expand" : "Collapse"}
      >
        {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
      </button>
    </aside>
  );
}
