import React from "react";
import { Loader2 } from "lucide-react";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "accent"
  | "danger"
  | "ghost"
  | "outline";

export type ButtonSize = "xs" | "sm" | "md" | "lg";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  icon?: React.ReactNode;
  iconPosition?: "left" | "right";
  fullWidth?: boolean;
}

const VARIANT_STYLES: Record<ButtonVariant, string> = {
  primary:
    "bg-primary hover:bg-blue-600 text-white font-medium shadow-sm border border-transparent active:scale-[0.98]",
  secondary:
    "bg-surface hover:bg-surfaceBorder text-gray-200 border border-surfaceBorder hover:border-gray-500 active:scale-[0.98]",
  accent:
    "bg-accent hover:bg-emerald-600 text-white font-medium shadow-sm border border-transparent active:scale-[0.98]",
  danger:
    "bg-danger/90 hover:bg-danger text-white font-semibold shadow-sm border border-red-700 active:scale-[0.98]",
  ghost:
    "bg-transparent hover:bg-surface text-gray-300 hover:text-gray-100 border border-transparent",
  outline:
    "bg-transparent hover:bg-primary/10 text-primary border border-primary/40 hover:border-primary active:scale-[0.98]",
};

const SIZE_STYLES: Record<ButtonSize, string> = {
  xs: "text-xs px-2.5 py-1 rounded-md gap-1.5",
  sm: "text-xs px-3.5 py-1.5 rounded-lg gap-2",
  md: "text-sm px-4 py-2 rounded-lg gap-2",
  lg: "text-base px-5 py-2.5 rounded-xl gap-2.5",
};

export const Button: React.FC<ButtonProps> = ({
  variant = "primary",
  size = "sm",
  isLoading = false,
  icon,
  iconPosition = "left",
  fullWidth = false,
  disabled,
  children,
  className = "",
  ...props
}) => {
  const baseClasses =
    "inline-flex items-center justify-center font-medium transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 select-none";

  const variantClass = VARIANT_STYLES[variant];
  const sizeClass = SIZE_STYLES[size];
  const widthClass = fullWidth ? "w-full" : "";

  return (
    <button
      className={`${baseClasses} ${variantClass} ${sizeClass} ${widthClass} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
      ) : icon && iconPosition === "left" ? (
        <span className="shrink-0">{icon}</span>
      ) : null}

      <span>{children}</span>

      {!isLoading && icon && iconPosition === "right" ? (
        <span className="shrink-0">{icon}</span>
      ) : null}
    </button>
  );
};

export default Button;
