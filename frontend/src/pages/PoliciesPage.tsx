import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { policyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { AddPolicyModal } from "@/components/AddPolicyModal";
import {
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import {
  POLICY_TYPE_LABELS,
  daysUntil,
  formatCurrency,
  formatDate,
  formatPremium,
  policyTypeLabel,
} from "@/lib/format";

export function PoliciesPage() {
  const { activeFamilyId, activeAccess } = useAuth();
  const [showForm, setShowForm] = useState(false);
  const [typeFilter, setTypeFilter] = useState("");
  const [search, setSearch] = useState("");

  const policies = useAsync(
    () =>
      policyApi.list(activeFamilyId!, {
        ...(typeFilter ? { policy_type: typeFilter } : {}),
        ...(search ? { search } : {}),
      }),
    [activeFamilyId, typeFilter, search],
  );

  const canWrite = activeAccess?.role !== "viewer";
  if (!activeFamilyId) return null;

  return (
    <div>
      <PageHeader
        title="Policies"
        description="Every insurance policy your family holds, in one place."
        action={
          canWrite ? (
            <button className="btn-primary" onClick={() => setShowForm(true)}>Add policy</button>
          ) : undefined
        }
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <input
          className="input max-w-xs"
          placeholder="Search insurer or policy number…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search policies"
        />
        <select
          className="input max-w-xs"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          aria-label="Filter by type"
        >
          <option value="">All types</option>
          {Object.entries(POLICY_TYPE_LABELS).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
      </div>

      {policies.loading ? (
        <Loading />
      ) : policies.error ? (
        <ErrorState message={policies.error} onRetry={policies.reload} />
      ) : policies.data!.total === 0 ? (
        <EmptyState
          title="No policies found"
          description="Add a policy manually or upload a policy document to have it extracted automatically."
          action={canWrite ? (
            <button className="btn-primary" onClick={() => setShowForm(true)}>Add policy</button>
          ) : undefined}
        />
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead>
                <tr>
                  <th className="table-head">Policy</th>
                  <th className="table-head">Type</th>
                  <th className="table-head">Sum insured</th>
                  <th className="table-head">Premium</th>
                  <th className="table-head">Renewal / expiry</th>
                  <th className="table-head">Status</th>
                </tr>
              </thead>
              <tbody>
                {policies.data!.items.map((p) => {
                  const expiry = p.renewal_date ?? p.expiry_date;
                  const days = daysUntil(expiry);
                  return (
                    <tr key={p.id} className="hover:bg-slate-50">
                      <td className="table-cell">
                        <Link to={`/policies/${p.id}`} className="font-medium text-ink-900 hover:underline">
                          {p.insurer}
                        </Link>
                        <p className="text-xs text-ink-500">{p.policy_number}</p>
                      </td>
                      <td className="table-cell">{policyTypeLabel(p.policy_type)}</td>
                      <td className="table-cell">{formatCurrency(p.sum_insured)}</td>
                      <td className="table-cell">
                        {formatPremium(p.premium)}
                        {p.premium_frequency && (
                          <span className="text-xs text-ink-500"> /{p.premium_frequency}</span>
                        )}
                      </td>
                      <td className="table-cell">
                        {formatDate(expiry)}
                        {days !== null && days >= 0 && days <= 60 && (
                          <span className="ml-2 text-xs font-medium text-amber-700">in {days}d</span>
                        )}
                      </td>
                      <td className="table-cell"><StatusBadge status={p.status} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showForm && (
        <AddPolicyModal
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false);
            policies.reload();
          }}
        />
      )}
    </div>
  );
}
