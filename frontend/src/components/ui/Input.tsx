import React from "react";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  icon?: React.ReactNode;
}

export const Input: React.FC<InputProps> = ({
  label,
  error,
  helperText,
  icon,
  className = "",
  disabled,
  id,
  ...props
}) => {
  const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, "-") : undefined);

  return (
    <div className="w-full space-y-1">
      {label && (
        <label
          htmlFor={inputId}
          className="block text-xs font-medium text-gray-300"
        >
          {label}
        </label>
      )}

      <div className="relative flex items-center">
        {icon && (
          <div className="absolute left-3 text-gray-400 pointer-events-none">
            {icon}
          </div>
        )}
        <input
          id={inputId}
          disabled={disabled}
          className={`w-full bg-background border ${
            error
              ? "border-red-500 focus:ring-red-500/40"
              : "border-surfaceBorder focus:border-primary focus:ring-primary/40"
          } rounded-lg px-3 py-2 text-xs text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 transition disabled:opacity-50 disabled:cursor-not-allowed ${
            icon ? "pl-9" : ""
          } ${className}`}
          {...props}
        />
      </div>

      {error ? (
        <p className="text-[11px] text-red-400">{error}</p>
      ) : helperText ? (
        <p className="text-[11px] text-gray-500">{helperText}</p>
      ) : null}
    </div>
  );
};

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  helperText?: string;
}

export const Select: React.FC<SelectProps> = ({
  label,
  error,
  helperText,
  children,
  className = "",
  disabled,
  id,
  ...props
}) => {
  const selectId = id || (label ? label.toLowerCase().replace(/\s+/g, "-") : undefined);

  return (
    <div className="w-full space-y-1">
      {label && (
        <label
          htmlFor={selectId}
          className="block text-xs font-medium text-gray-300"
        >
          {label}
        </label>
      )}

      <select
        id={selectId}
        disabled={disabled}
        className={`w-full bg-background border ${
          error
            ? "border-red-500 focus:ring-red-500/40"
            : "border-surfaceBorder focus:border-primary focus:ring-primary/40"
        } rounded-lg px-3 py-2 text-xs text-gray-100 focus:outline-none focus:ring-2 transition disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
        {...props}
      >
        {children}
      </select>

      {error ? (
        <p className="text-[11px] text-red-400">{error}</p>
      ) : helperText ? (
        <p className="text-[11px] text-gray-500">{helperText}</p>
      ) : null}
    </div>
  );
};
