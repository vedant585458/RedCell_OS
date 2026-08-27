import React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Building2,
  Target,
  FileText,
  Settings,
} from "lucide-react";

interface NavItem {
  name: string;
  to: string;
  icon: React.ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  {
    name: "Dashboard",
    to: "/",
    icon: <LayoutDashboard className="w-4 h-4" />,
  },
  {
    name: "Office Sim",
    to: "/office",
    icon: <Building2 className="w-4 h-4" />,
  },
  {
    name: "Engagements",
    to: "/engagements",
    icon: <Target className="w-4 h-4" />,
  },
  {
    name: "Reports",
    to: "/reports",
    icon: <FileText className="w-4 h-4" />,
  },
  {
    name: "Settings",
    to: "/settings",
    icon: <Settings className="w-4 h-4" />,
  },
];

export const AppNavigation: React.FC = () => {
  return (
    <nav className="flex items-center gap-1 bg-background/90 px-6 py-2 border-b border-surfaceBorder overflow-x-auto">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap ${
              isActive
                ? "bg-primary/15 text-primary border border-primary/30"
                : "text-gray-400 hover:text-gray-200 hover:bg-surface"
            }`
          }
        >
          {item.icon}
          <span>{item.name}</span>
        </NavLink>
      ))}
    </nav>
  );
};
