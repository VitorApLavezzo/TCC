import { clsx } from "clsx";
import { SEVERITY_COLORS, SEVERITY_LABELS } from "../../types";

interface BadgeProps {
  severity: string;
  className?: string;
}

export function SeverityBadge({ severity, className }: BadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border",
        SEVERITY_COLORS[severity] || "text-gray-400 bg-gray-400/10 border-gray-400/30",
        className
      )}
    >
      {SEVERITY_LABELS[severity] || severity}
    </span>
  );
}
