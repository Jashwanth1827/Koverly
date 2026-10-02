/* Formatting and presentation helpers. */

export function formatCurrency(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(n)) return "—";
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(2)} Cr`;
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(2)} L`;
  return `₹${n.toLocaleString("en-IN")}`;
}

export function formatPremium(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(n)) return "—";
  return `₹${n.toLocaleString("en-IN")}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function daysUntil(value: string | null | undefined): number | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  d.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / 86_400_000);
}

export const POLICY_TYPE_LABELS: Record<string, string> = {
  life: "Life",
  health: "Health",
  motor: "Motor",
  home: "Home",
  travel: "Travel",
  personal_accident: "Personal Accident",
  other: "Other",
};

export function policyTypeLabel(t: string): string {
  return POLICY_TYPE_LABELS[t] ?? t.replace(/_/g, " ");
}

export const CLAIM_STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  submitted: "Submitted",
  documents_required: "Documents Required",
  under_review: "Under Review",
  approved: "Approved",
  rejected: "Rejected",
  settled: "Settled",
  closed: "Closed",
};

export function claimStatusLabel(s: string): string {
  return CLAIM_STATUS_LABELS[s] ?? s;
}

export const RELATIONSHIP_LABELS: Record<string, string> = {
  self: "Self",
  spouse: "Spouse",
  father: "Father",
  mother: "Mother",
  son: "Son",
  daughter: "Daughter",
  brother: "Brother",
  sister: "Sister",
  other: "Other",
};

export function relationshipLabel(r: string): string {
  return RELATIONSHIP_LABELS[r] ?? r;
}

export function statusTone(status: string): "good" | "warn" | "bad" | "neutral" {
  const s = status.toLowerCase();
  if (["active", "approved", "settled", "processed", "completed", "confirmed"].includes(s))
    return "good";
  if (["pending", "under_review", "submitted", "processing", "documents_required", "triggered", "sent"].includes(s))
    return "warn";
  if (["expired", "lapsed", "cancelled", "rejected", "failed"].includes(s)) return "bad";
  return "neutral";
}

export function severityTone(sev: string): "good" | "warn" | "bad" | "neutral" {
  if (sev === "critical") return "bad";
  if (sev === "warning") return "warn";
  return "neutral";
}

export function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}
