"use client";

import { Database, History } from "lucide-react";

type Tab = "sources" | "history";

interface Props {
  activeTab: Tab;
  sourceCount: number;
  onTabChange: (tab: Tab) => void;
}

export default function SideDock({ activeTab, sourceCount, onTabChange }: Props) {
  const tabs: { id: Tab; label: string; icon: typeof Database; badge?: number }[] = [
    { id: "sources", label: "Sources", icon: Database, badge: sourceCount },
    { id: "history", label: "Historique", icon: History },
  ];

  return (
    <div
      className="flex shrink-0 gap-1 border-t p-2"
      style={{ borderColor: "var(--border-color)" }}
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const active = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-md py-2 text-[12.5px] font-medium transition-colors"
            style={{
              background: active ? "var(--accent-soft)" : "transparent",
              color: active ? "var(--accent)" : "var(--text-muted)",
            }}
          >
            <Icon size={14} strokeWidth={1.8} />
            {tab.label}
            {tab.badge !== undefined && tab.badge > 0 && (
              <span
                className="grid size-4 place-items-center rounded-full text-[9px] font-bold"
                style={{ background: "var(--accent)", color: "var(--accent-contrast)" }}
              >
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
