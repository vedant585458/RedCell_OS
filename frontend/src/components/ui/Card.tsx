import React from "react";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "surface" | "bordered" | "highlight";
  glow?: boolean;
}

export const Card: React.FC<CardProps> = ({
  variant = "default",
  glow = false,
  className = "",
  children,
  ...props
}) => {
  const variantStyles = {
    default: "bg-surface border border-surfaceBorder",
    surface: "bg-background border border-surfaceBorder/80",
    bordered: "bg-surface/50 border-2 border-surfaceBorder",
    highlight: "bg-surface border border-primary/40 shadow-[0_0_15px_rgba(88,166,255,0.08)]",
  }[variant];

  const glowStyle = glow ? "hover:border-primary/50 transition-colors shadow-lg" : "";

  return (
    <div
      className={`rounded-xl ${variantStyles} ${glowStyle} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};

export const CardHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className = "",
  children,
  ...props
}) => (
  <div className={`p-5 pb-3 border-b border-surfaceBorder/60 flex items-center justify-between ${className}`} {...props}>
    {children}
  </div>
);

export const CardTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>> = ({
  className = "",
  children,
  ...props
}) => (
  <h3 className={`text-sm font-semibold text-gray-100 flex items-center gap-2 ${className}`} {...props}>
    {children}
  </h3>
);

export const CardDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>> = ({
  className = "",
  children,
  ...props
}) => (
  <p className={`text-xs text-gray-400 mt-1 ${className}`} {...props}>
    {children}
  </p>
);

export const CardContent: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className = "",
  children,
  ...props
}) => (
  <div className={`p-5 ${className}`} {...props}>
    {children}
  </div>
);

export const CardFooter: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className = "",
  children,
  ...props
}) => (
  <div className={`p-5 pt-3 border-t border-surfaceBorder/60 flex items-center justify-between ${className}`} {...props}>
    {children}
  </div>
);
