import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = (p: P) => ({
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  ...p,
});

export const IconTable = (p: P) => (
  <svg {...base(p)}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M9 10v10" /></svg>
);
export const IconTerminal = (p: P) => (
  <svg {...base(p)}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3M13 15h4" /></svg>
);
export const IconClock = (p: P) => (
  <svg {...base(p)}><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>
);
export const IconGraph = (p: P) => (
  <svg {...base(p)}><circle cx="6" cy="5.5" r="2" /><circle cx="6" cy="18.5" r="2" /><circle cx="18" cy="9" r="2" /><path d="M6 7.5v9M18 11c0 4-6 3-11.2 6" /></svg>
);
export const IconMerge = (p: P) => (
  <svg {...base(p)}><circle cx="6" cy="5.5" r="2" /><circle cx="6" cy="18.5" r="2" /><circle cx="18" cy="18.5" r="2" /><path d="M6 7.5v9M6 7.5c0 6 6 8 10 10" /></svg>
);
export const IconStorage = (p: P) => (
  <svg {...base(p)}><ellipse cx="12" cy="6" rx="7.5" ry="2.8" /><path d="M4.5 6v12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8" /></svg>
);
export const IconBranch = (p: P) => (
  <svg {...base(p)}><circle cx="6" cy="5.5" r="2" /><circle cx="6" cy="18.5" r="2" /><circle cx="18" cy="7" r="2" /><path d="M6 7.5v9M18 9c0 5-12 3-12 7.5" /></svg>
);
export const IconTag = (p: P) => (
  <svg {...base(p)}><path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1 1 0 0 1 0 1.4l-7.4 7.4a1 1 0 0 1-1.4 0z" /><circle cx="8" cy="8" r="1.4" /></svg>
);
export const IconPlus = (p: P) => (<svg {...base(p)}><path d="M12 5v14M5 12h14" /></svg>);
export const IconTrash = (p: P) => (
  <svg {...base(p)}><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v6M14 11v6" /></svg>
);
export const IconUndo = (p: P) => (<svg {...base(p)}><path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></svg>);
export const IconDownload = (p: P) => (<svg {...base(p)}><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></svg>);
export const IconSearch = (p: P) => (<svg {...base(p)}><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.3-4.3" /></svg>);
export const IconX = (p: P) => (<svg {...base(p)}><path d="M6 6l12 12M18 6 6 18" /></svg>);
export const IconCheck = (p: P) => (<svg {...base(p)}><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>);
export const IconChevron = (p: P) => (<svg {...base(p)}><path d="m7 10 5 5 5-5" /></svg>);
export const IconPlay = (p: P) => (<svg {...base(p)}><path d="M8 5.5v13l10.5-6.5z" /></svg>);
export const IconColumns = (p: P) => (<svg {...base(p)}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M12 4v16" /></svg>);
export const IconRefresh = (p: P) => (<svg {...base(p)}><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3L19.5 9" /><path d="M19.5 4v5h-5" /></svg>);
export const IconArrowRight = (p: P) => (<svg {...base(p)}><path d="M5 12h14M13 6l6 6-6 6" /></svg>);

export function LogoMark(p: P) {
  // Three commits on a line; the newest is filled — a database seen through time.
  return (
    <svg viewBox="0 0 26 26" aria-hidden className={p.className}>
      <rect x="0.5" y="0.5" width="25" height="25" rx="7" fill="var(--head)" />
      <path d="M5 13h16" stroke="#fff" strokeOpacity=".45" strokeWidth="1.6" />
      <circle cx="6.5" cy="13" r="2.2" fill="none" stroke="#fff" strokeWidth="1.6" />
      <circle cx="13" cy="13" r="2.2" fill="none" stroke="#fff" strokeWidth="1.6" />
      <circle cx="19.5" cy="13" r="2.8" fill="#fff" />
    </svg>
  );
}
