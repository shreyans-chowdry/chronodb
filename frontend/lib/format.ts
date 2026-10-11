export const short = (hash?: string | null) => (hash ? hash.slice(0, 7) : "");

export function timeAgo(ts?: number): string {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 45) return "just now";
  if (s < 90) return "a minute ago";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} minutes ago`;
  const h = Math.round(m / 60);
  if (h < 24) return h === 1 ? "an hour ago" : `${h} hours ago`;
  const d = Math.round(h / 24);
  if (d < 30) return d === 1 ? "yesterday" : `${d} days ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function stamp(ts?: number): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function bytes(n?: number): string {
  if (n === undefined || n === null) return "–";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function cell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Turn text typed into a grid cell into a JSON value: numbers, booleans, null stay typed. */
export function parseCell(text: string, previous?: unknown): unknown {
  const t = text.trim();
  if (t === "") return previous === undefined ? "" : typeof previous === "number" ? null : "";
  if (t === "null") return null;
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(t) && (typeof previous === "number" || previous === undefined || previous === null)) return Number(t);
  if ((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"))) {
    try { return JSON.parse(t); } catch { /* keep as text */ }
  }
  return text;
}

export function toCSV(columns: string[], rows: Record<string, unknown>[]): string {
  const esc = (v: unknown) => {
    const s = cell(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.join(","), ...rows.map((r) => columns.map((c) => esc(r[c])).join(","))].join("\n");
}

export function download(name: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
