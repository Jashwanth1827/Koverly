import type { ReactNode } from "react";
import { statusTone } from "@/lib/format";

export function Badge({ children, tone }: { children: ReactNode; tone?: string }) {
  const t = tone ?? "neutral";
  return <span className={`badge-${t}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{status.replace(/_/g, " ")}</Badge>;
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white/60 px-6 py-12 text-center">
      <h3 className="text-base font-semibold text-ink-900">{title}</h3>
      <p className="mt-1 max-w-md text-sm text-ink-500">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center justify-center gap-3 py-16 text-sm text-ink-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-5 py-4">
      <p className="text-sm font-medium text-red-800">{message}</p>
      {onRetry && (
        <button className="btn-secondary mt-3" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-ink-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink-900 sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-ink-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Disclaimer({ children }: { children: ReactNode }) {
  return (
    <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-ink-500">
      {children}
    </p>
  );
}

/** Render a recorded phone number or email address as a tappable link. */
export function ContactLink({ value, className = "" }: { value: string; className?: string }) {
  const text = value.trim();
  const isEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text);
  const isPhone = /^[+\d][\d\s().-]*$/.test(text) && text.replace(/\D/g, "").length >= 6;

  if (isEmail) {
    return (
      <a href={`mailto:${text}`} className={`break-all hover:underline ${className}`}>
        {text}
      </a>
    );
  }
  if (isPhone) {
    return (
      <a href={`tel:${text.replace(/[^\d+]/g, "")}`} className={`hover:underline ${className}`}>
        {text}
      </a>
    );
  }
  return <span className={`break-words ${className}`}>{text}</span>;
}
