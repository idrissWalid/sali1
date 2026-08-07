import type { CSSProperties } from "react";

type SaliMarkProps = {
  size?: number;
  mono?: boolean;
  color?: string;
  className?: string;
  style?: CSSProperties;
  title?: string;
};

export default function SaliMark({ size = 32, mono = false, color, className, style, title }: SaliMarkProps) {
  const ringColor = mono ? "currentColor" : color ?? "#7A8A5E";
  const dotColor = mono ? "currentColor" : "#C67139";

  return (
    <svg aria-hidden={title ? undefined : true} aria-label={title} className={className} height={size}
      role={title ? "img" : undefined} style={{ display: "block", flexShrink: 0, ...style }}
      viewBox="0 0 100 100" width={size} xmlns="http://www.w3.org/2000/svg">
      <circle cx="50" cy="53.8" fill="none" r="37" stroke={ringColor} strokeWidth="10.9" />
      <circle cx="79.4" cy="15.7" fill={dotColor} r="12" />
    </svg>
  );
}

export function SaliLoadingMark({ size = 30 }: { size?: number }) {
  return (
    <svg aria-label="Sali AI réfléchit" height={size} role="img" style={{ display: "block", flexShrink: 0 }}
      viewBox="0 0 100 100" width={size} xmlns="http://www.w3.org/2000/svg">
      <circle cx="50" cy="53.8" fill="none" r="37" stroke="#7A8A5E" strokeWidth="10.9" />
      <circle className="sali-loading-dot" cx="79.4" cy="15.7" fill="#C67139" r="12" />
    </svg>
  );
}
