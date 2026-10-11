"use client";

import { useEffect, useRef } from "react";
import { useApp } from "@/lib/store";
import { short } from "@/lib/format";
import { IconX } from "./icons";

export function Hash({ value, full = false }: { value?: string | null; full?: boolean }) {
  const { toast } = useApp();
  if (!value) return null;
  return (
    <button
      type="button"
      className="hash"
      title="Copy commit hash"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(value).then(() => toast(`Copied ${short(value)}`, "info"));
      }}
    >
      {full ? value : short(value)}
    </button>
  );
}

export function Dialog({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="panel-head">
          <div className="panel-title" style={{ flex: 1 }}>{title}</div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>
        <div style={{ padding: 16, display: "grid", gap: 14 }}>{children}</div>
        {footer && (
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, padding: "0 16px 16px" }}>{footer}</div>
        )}
      </div>
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {children && <div style={{ maxWidth: "52ch" }}>{children}</div>}
      {action && <div style={{ marginTop: 6 }}>{action}</div>}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="panel" style={{ padding: 14, display: "flex", gap: 12, alignItems: "center", borderColor: "var(--del)" }}>
      <span style={{ color: "var(--del)", fontWeight: 600 }}>Error</span>
      <span style={{ flex: 1 }}>{message}</span>
      {onRetry && <button className="btn btn-sm" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Toasts() {
  const { toasts, dismiss } = useApp();
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="toast" data-kind={t.kind}>
          <span style={{ flex: 1 }}>{t.text}</span>
          <button onClick={() => dismiss(t.id)} aria-label="Dismiss" style={{ opacity: 0.7 }}>
            <IconX width={14} height={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div style={{ padding: 16, display: "grid", gap: 10 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 18, width: `${90 - (i % 3) * 15}%` }} />
      ))}
    </div>
  );
}
