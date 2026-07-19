import { clsx } from "clsx";
import { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
}

export function Card({ children, className, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        "bg-gray-900 border border-gray-800 rounded-xl p-5",
        onClick && "cursor-pointer hover:border-blue-600/40 hover:bg-gray-900/80 hover:shadow-lg hover:shadow-blue-950/30 transition-all",
        className
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("mb-4", className)}>{children}</div>;
}

export function CardTitle({ children, className }: { children: ReactNode; className?: string }) {
  return <h3 className={clsx("text-sm font-medium text-gray-400 uppercase tracking-wider", className)}>{children}</h3>;
}
