import React from "react";
import { AlertCircle, CheckCircle, AlertTriangle, Info, X } from "lucide-react";

export type AlertVariant = "info" | "success" | "warning" | "danger";

export interface AlertProps {
  variant?: AlertVariant;
  title?: string;
  children: React.ReactNode;
  onDismiss?: () => void;
  className?: string;
}

const VARIANT_CONFIG: Record<
  AlertVariant,
  { container: string; icon: React.ReactNode; titleColor: string }
> = {
  info: {
    container: "bg-blue-950/40 border-blue-800/80 text-blue-300",
    icon: <Info className="w-4 h-4 text-blue-400 shrink-0" />,
    titleColor: "text-blue-200",
  },
  success: {
    container: "bg-emerald-950/40 border-emerald-800/80 text-emerald-300",
    icon: <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />,
    titleColor: "text-emerald-200",
  },
  warning: {
    container: "bg-amber-950/40 border-amber-800/80 text-amber-300",
    icon: <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />,
    titleColor: "text-amber-200",
  },
  danger: {
    container: "bg-red-950/50 border-red-800/80 text-red-300",
    icon: <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />,
    titleColor: "text-red-200",
  },
};

export const Alert: React.FC<AlertProps> = ({
  variant = "info",
  title,
  children,
  onDismiss,
  className = "",
}) => {
  const config = VARIANT_CONFIG[variant];

  return (
    <div
      className={`p-4 rounded-xl border flex items-start gap-3 text-xs leading-relaxed ${config.container} ${className}`}
      role="alert"
    >
      <div className="mt-0.5">{config.icon}</div>
      <div className="flex-1">
        {title && (
          <h4 className={`font-semibold mb-1 text-sm ${config.titleColor}`}>
            {title}
          </h4>
        )}
        <div>{children}</div>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="text-gray-400 hover:text-gray-200 transition p-0.5"
          aria-label="Dismiss alert"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};

export default Alert;
