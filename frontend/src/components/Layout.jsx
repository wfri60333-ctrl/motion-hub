import { Outlet, NavLink } from "react-router-dom";
import { Terminal, Sliders, ListChecks, ScrollText } from "lucide-react";
import HeaderBar from "@/components/HeaderBar";

const NAV = [
  { to: "/", label: "Overview", icon: Terminal, testid: "nav-overview" },
  { to: "/commands", label: "Commands", icon: ListChecks, testid: "nav-commands" },
  { to: "/config", label: "Config", icon: Sliders, testid: "nav-config" },
  { to: "/audit", label: "Audit", icon: ScrollText, testid: "nav-audit" },
];

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col bg-[#050505] text-white grid-bg">
      <HeaderBar />
      <div className="flex-1 flex">
        {/* Sidebar */}
        <aside
          data-testid="sidebar"
          className="hidden md:flex w-56 shrink-0 flex-col border-r border-white/10 bg-[#080808]"
        >
          <div className="px-4 py-3 border-b border-white/10">
            <div className="text-[10px] tracking-[0.25em] uppercase text-white/40 font-bold">
              Sector
            </div>
            <div className="text-sm text-white/70 mt-1">Control</div>
          </div>
          <nav className="flex-1 py-2">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                data-testid={item.testid}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors duration-75 border-l-2 ${
                    isActive
                      ? "border-[#007AFF] text-white bg-white/[0.04]"
                      : "border-transparent text-white/50 hover:text-white hover:bg-white/[0.03]"
                  }`
                }
              >
                <item.icon className="w-4 h-4" />
                <span className="uppercase tracking-widest text-[11px] font-bold">
                  {item.label}
                </span>
              </NavLink>
            ))}
          </nav>
          <div className="border-t border-white/10 p-4 text-[10px] text-white/30 tracking-[0.2em] uppercase font-mono">
            v0.1.0 · mod_ctrl
          </div>
        </aside>

        {/* Mobile nav */}
        <div className="md:hidden fixed bottom-0 left-0 right-0 z-40 flex border-t border-white/10 bg-[#080808]">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              data-testid={`${item.testid}-mobile`}
              className={({ isActive }) =>
                `flex-1 py-3 flex flex-col items-center gap-1 text-[10px] uppercase tracking-widest ${
                  isActive ? "text-[#007AFF]" : "text-white/50"
                }`
              }
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </NavLink>
          ))}
        </div>

        <main className="flex-1 min-w-0 pb-20 md:pb-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
