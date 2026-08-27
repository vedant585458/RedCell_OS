import React from "react";

export type BadgeVariant =
  | "default"
  | "primary"
  | "success"
  | "warning"
  | "danger"
  | "purple"
  | "outline";

export type BadgeSize = "sm" | "md";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
  pulse?: boolean;
  icon?: React.ReactNode;
}

const VARIANT_STYLES: Record<BadgeVariant, { badge: string; dot: string }> = {
  default: {
    badge: "bg-surfaceBorder text-gray-300 border-gray-600",
    dot: "bg-gray-400",
  },
  primary: {
    badge: "bg-blue-950/70 text-blue-400 border-blue-800/80",
    dot: "bg-blue-400",
  },
  success: {
    badge: "bg-emerald-950/70 text-emerald-400 border-emerald-800/80",
    dot: "bg-emerald-400",
  },
  warning: {
    badge: "bg-amber-950/70 text-amber-400 border-amber-800/80",
    dot: "bg-amber-400",
  },
  danger: {
    badge: "bg-red-950/80 text-red-400 border-red-800/80",
    dot: "bg-red-400",
  },
  purple: {
    badge: "bg-purple-950/70 text-purple-400 border-purple-800/80",
    dot: "bg-purple-400",
  },
  outline: {
    badge: "bg-transparent text-gray-300 border-surfaceBorder",
    dot: "bg-gray-400",
  },
};

export const Badge: React.FC<BadgeProps> = ({
  variant = "default",
  size = "sm",
  dot = false,
  pulse = false,
  icon,
  children,
  className = "",
  ...props
}) => {
  const styles = VARIANT_STYLES[variant] || VARIANT_STYLES.default;
  const sizeClass = size === "sm" ? "text-[11px] px-2.5 py-0.5" : "text-xs px-3 py-1";

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium rounded-full border transition-colors ${styles.badge} ${sizeClass} ${className}`}
      {...props}
    >
      {dot && (
        <span className="relative flex h-1.5 w-1.5">
          {pulse && (
            <span
              className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${styles.dot}`}
            ></span>
          )}
          <span className={`relative inline-flex rounded-full h-1.5 w-1.5 ${styles.dot}`}></span>
        </span>
      )}
      {icon && <span className="shrink-0">{icon}</span>}
      <span>{children}</span>
    </span>
  );
};

export default Badge;
