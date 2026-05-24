import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Users,
  PhoneCall,
  Megaphone,
  ShieldCheck,
  Activity,
  Phone,
  BrainCircuit,
  Settings,
  CreditCard,
  Key,
  UserCog,
  Webhook,
} from "lucide-react";
import { cn } from "@/lib/utils";

const nav = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/borrowers", icon: Users, label: "Borrowers" },
  { to: "/calls", icon: PhoneCall, label: "Calls" },
  { to: "/campaigns", icon: Megaphone, label: "Campaigns" },
  { to: "/compliance", icon: ShieldCheck, label: "Compliance" },
  { to: "/call-quality", icon: Activity, label: "Call Quality" },
];

const intelligenceNav = [
  { to: "/human-calls", icon: BrainCircuit, label: "Human Calls" },
];

const settingsNav = [
  { to: "/settings/team", icon: UserCog, label: "Team" },
  { to: "/settings/billing", icon: CreditCard, label: "Billing" },
  { to: "/settings/api-keys", icon: Key, label: "API Keys" },
];

export default function Sidebar() {
  return (
    <aside className="w-56 min-h-screen bg-slate-900 text-slate-100 flex flex-col">
      <div className="px-5 py-5 flex items-center gap-2 border-b border-slate-700">
        <Phone size={20} className="text-indigo-400" />
        <span className="font-semibold text-sm leading-tight">
          likhith Recovery
          <br />
          <span className="text-slate-400 font-normal text-xs">AI Debt Collector</span>
        </span>
      </div>
      <nav className="flex-1 py-3">
        {nav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-5 py-2.5 text-sm transition-colors",
                isActive
                  ? "bg-indigo-600 text-white"
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}

        <div className="mx-5 my-3 border-t border-slate-700" />
        <p className="px-5 pb-1.5 text-xs font-semibold text-slate-500 uppercase tracking-widest">
          Intelligence
        </p>
        {intelligenceNav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-5 py-2.5 text-sm transition-colors",
                isActive
                  ? "bg-indigo-600 text-white"
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}

        <div className="mx-5 my-3 border-t border-slate-700" />
        <p className="px-5 pb-1.5 text-xs font-semibold text-slate-500 uppercase tracking-widest">
          Settings
        </p>
        {settingsNav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-5 py-2.5 text-sm transition-colors",
                isActive
                  ? "bg-indigo-600 text-white"
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="px-5 py-4 text-xs text-slate-500 border-t border-slate-700">
        v2.0 · SaaS · FDCPA Compliant
      </div>
    </aside>
  );
}
