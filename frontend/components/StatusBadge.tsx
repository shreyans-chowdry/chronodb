"use client";

interface StatusBadgeProps {
  label: string;
  variant?: "default" | "success" | "warning" | "error" | "info";
}

const variantStyles: Record<string, string> = {
  default:
    "bg-zinc-100/50 dark:bg-zinc-700/50 text-zinc-700 dark:text-zinc-300 border-zinc-300/50 dark:border-zinc-600/50",
  success:
    "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  warning:
    "bg-amber-500/15 text-amber-400 border-amber-500/30",
  error:
    "bg-red-500/15 text-red-400 border-red-500/30",
  info:
    "bg-sky-500/15 text-sky-400 border-sky-500/30",
};

export default function StatusBadge({
  label,
  variant = "default",
}: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium tracking-wide transition-colors ${
        variantStyles[variant] || variantStyles.default
      }`}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-80" />
      {label}
    </span>
  );
}
