import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { insightApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { AddPolicyModal } from "@/components/AddPolicyModal";
import {
  Disclaimer,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  StatCard,
  StatusBadge,
} from "@/components/ui";
import {

  daysUntil,
  formatCurrency,
  formatDate,
  formatPremium,
  policyTypeLabel,
  severityTone,
} from "@/lib/format";
import { Badge } from "@/components/ui";

export function DashboardPage() {
  const { activeFamilyId } = useAuth();
  const [showAddPolicy, setShowAddPolicy] = useState(false);
  const state = useAsync(
    () => insightApi.dashboard(activeFamilyId!),
    [activeFamilyId],
  );

  if (!activeFamilyId) return null;
  if (state.loading) return <Loading label="Building your family protection overview…" />;
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  const d = state.data!;

  const noData = d.active_policies === 0 && d.recent_claims.length === 0;

  return (
    <div>
      <PageHeader
        title={d.family_name}
        description="Your family's insurance at a glance."
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Active policies" value={String(d.active_policies)} />
        <StatCard
          label="Annual premium"
          value={formatPremium(d.total_annual_premium)}
          hint="Normalized to a yearly figure"
        />
        <StatCard label="Life coverage" value={formatCurrency(d.total_life_coverage)} />
        <StatCard label="Health coverage" value={formatCurrency(d.total_health_coverage)} />
      </div>

      {noData ? (
        <div className="mt-6">
          <EmptyState
            title="No policies recorded yet"
            description="Add a policy manually or upload a policy copy to build your family's insurance profile."
            action={
              <button className="btn-primary" onClick={() => setShowAddPolicy(true)}>
                Add a policy
              </button>
            }
          />
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <section className="card p-5" aria-labelledby="attention-heading">
            <h2 id="attention-heading" className="text-sm font-semibold uppercase tracking-wide text-ink-500">
              Needs attention
            </h2>
            {d.pending_actions.length === 0 && d.upcoming_renewals.length === 0 ? (
              <p className="mt-3 text-sm text-ink-500">Nothing needs your attention right now.</p>
            ) : (
              <ul className="mt-3 divide-y divide-slate-100">
                {[...d.pending_actions, ...d.upcoming_renewals].slice(0, 6).map((item, i) => (
                  <li key={`${item.kind}-${i}`} className="flex items-start gap-3 py-3">
                    <Badge tone={severityTone(item.severity)}>{item.kind.replace(/_/g, " ")}</Badge>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-ink-900">{item.title}</p>
                      <p className="text-sm text-ink-500">{item.detail}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card p-5" aria-labelledby="renewals-heading">
            <h2 id="renewals-heading" className="text-sm font-semibold uppercase tracking-wide text-ink-500">
              Upcoming renewals
            </h2>
            {d.upcoming_renewals.length === 0 ? (
              <p className="mt-3 text-sm text-ink-500">No renewals in the next 60 days.</p>
            ) : (
              <ul className="mt-3 space-y-3">
                {d.upcoming_renewals.map((r, i) => {
                  const days = daysUntil(r.due_date);
                  return (
                    <li key={i} className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-ink-900">{r.title}</p>
                        <p className="text-xs text-ink-500">{formatDate(r.due_date)}</p>
                      </div>
                      <Badge tone={days !== null && days <= 7 ? "bad" : "warn"}>
                        {days !== null ? `in ${days} day${days === 1 ? "" : "s"}` : "—"}
                      </Badge>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="card p-5 lg:col-span-2" aria-labelledby="claims-heading">
            <div className="flex items-center justify-between">
              <h2 id="claims-heading" className="text-sm font-semibold uppercase tracking-wide text-ink-500">
                Recent claims
              </h2>
              <Link to="/claims" className="text-sm font-medium text-brand-700 hover:underline">
                View all
              </Link>
            </div>
            {d.recent_claims.length === 0 ? (
              <p className="mt-3 text-sm text-ink-500">No claims recorded.</p>
            ) : (
              <ul className="mt-3 divide-y divide-slate-100">
                {d.recent_claims.map((c) => (
                  <li key={c.id} className="flex items-center justify-between gap-3 py-3">
                    <div>
                      <Link to={`/claims/${c.id}`} className="text-sm font-medium text-ink-900 hover:underline">
                        {c.claim_type.replace(/_/g, " ")}
                      </Link>
                      <p className="text-xs text-ink-500">
                        {c.provider ?? "—"} · {formatDate(c.incident_date)}
                      </p>
                    </div>
                    <StatusBadge status={c.status} />
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card p-5 lg:col-span-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
              Coverage by type
            </h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(d.by_type).length === 0 && (
                <p className="text-sm text-ink-500">No coverage recorded.</p>
              )}
              {Object.entries(d.by_type).map(([type, count]) => (
                <span key={type} className="badge-neutral">
                  {policyTypeLabel(type)}: {count}
                </span>
              ))}
            </div>
          </section>
        </div>
      )}

      <Disclaimer>
        Coverage totals are summed from the policies you have recorded. Figures such as{" "}
        {formatCurrency(d.total_life_coverage)} reflect recorded sums insured and may not match an
        insurer's settlement. Koverly does not provide financial advice.
      </Disclaimer>

      {showAddPolicy && (
        <AddPolicyModal
          onClose={() => setShowAddPolicy(false)}
          onSaved={() => {
            setShowAddPolicy(false);
            state.reload();
          }}
        />
      )}
    </div>
  );
}
