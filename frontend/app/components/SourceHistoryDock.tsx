"use client";

import { AnimatePresence, motion, useMotionValue, useSpring, useTransform } from "motion/react";
import { useRef, useState } from "react";

type Tab = "sources" | "history";

interface Props {
  activeTab: Tab;
  sourceCount: number;
  onTabChange: (tab: Tab) => void;
}

const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
  {
    id: "sources",
    label: "Sources",
    icon: <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3.75 6.75A2.25 2.25 0 0 1 6 4.5h4.2c.5 0 .97.25 1.25.67l.82 1.23c.28.42.75.67 1.25.67H18a2.25 2.25 0 0 1 2.25 2.25v8.25A2.25 2.25 0 0 1 18 19.8H6a2.25 2.25 0 0 1-2.25-2.25V6.75Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  },
  {
    id: "history",
    label: "Historique",
    icon: <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3.75 5.75A2.25 2.25 0 0 1 6 3.5h12a2.25 2.25 0 0 1 2.25 2.25v8.5A2.25 2.25 0 0 1 18 16.5H8.1L3.75 20v-14.25Z" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  },
];

export default function SourceHistoryDock({ activeTab, sourceCount, onTabChange }: Props) {
  const mouseX = useMotionValue(Number.POSITIVE_INFINITY);

  return (
    <nav
      aria-label="Navigation des données"
      className="source-history-dock"
      onMouseMove={(event) => mouseX.set(event.clientX)}
      onMouseLeave={() => mouseX.set(Number.POSITIVE_INFINITY)}
    >
      {tabs.map((tab) => (
        <DockItem
          key={tab.id}
          tab={tab}
          mouseX={mouseX}
          active={activeTab === tab.id}
          badge={tab.id === "sources" ? sourceCount : undefined}
          onClick={() => onTabChange(tab.id)}
        />
      ))}
    </nav>
  );
}

function DockItem({
  tab,
  mouseX,
  active,
  badge,
  onClick,
}: {
  tab: (typeof tabs)[number];
  mouseX: ReturnType<typeof useMotionValue<number>>;
  active: boolean;
  badge?: number;
  onClick: () => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const [hovered, setHovered] = useState(false);
  const distance = useTransform(mouseX, (value) => {
    const bounds = ref.current?.getBoundingClientRect();
    return bounds ? value - bounds.left - bounds.width / 2 : 999;
  });
  const size = useSpring(useTransform(distance, [-115, 0, 115], [42, 64, 42]), {
    mass: 0.14,
    stiffness: 220,
    damping: 17,
  });
  const iconSize = useSpring(useTransform(distance, [-115, 0, 115], [18, 26, 18]), {
    mass: 0.14,
    stiffness: 220,
    damping: 17,
  });

  return (
    <motion.button
      ref={ref}
      type="button"
      aria-label={tab.label}
      aria-pressed={active}
      style={{ width: size, height: size }}
      className={`source-history-dock__item${active ? " source-history-dock__item--active" : ""}`}
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
    >
      <AnimatePresence>
        {hovered && (
          <motion.span
            className="source-history-dock__tooltip"
            initial={{ opacity: 0, y: 7, x: "-50%" }}
            animate={{ opacity: 1, y: 0, x: "-50%" }}
            exit={{ opacity: 0, y: 4, x: "-50%" }}
            transition={{ duration: 0.16 }}
          >
            {tab.label}{badge !== undefined ? ` · ${badge}` : ""}
          </motion.span>
        )}
      </AnimatePresence>
      <motion.span className="source-history-dock__icon" style={{ width: iconSize, height: iconSize }}>
        {tab.icon}
      </motion.span>
      {badge !== undefined && badge > 0 && <span className="source-history-dock__badge">{badge}</span>}
    </motion.button>
  );
}
