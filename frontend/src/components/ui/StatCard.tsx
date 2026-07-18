import { ReactNode } from "react";
import { clsx } from "clsx";

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  color?: "blue" | "green" | "yellow" | "red" | "purple";
}

const colorMap = {
  blue: "text-blue-400 bg-blue-400/10",
  green: "text-green-400 bg-green-400/10",
  yellow: "text-yellow-400 bg-yellow-400/10",
  red: "text-red-400 bg-red-400/10",
  purple: "text-purple-400 bg-purple-400/10",
};

export function StatCard({ title, value, subtitle, icon, color = "blue" }: StatCardProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex items-start gap-4">
      {icon && (
        <div className={clsx("p-2.5 rounded-lg", colorMap[color])}>
          {icon}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">{title}</p>
        <p className="text-2xl font-bold text-white mt-1">{value}</p>
        {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
      </div>
    </div>
  );
}
