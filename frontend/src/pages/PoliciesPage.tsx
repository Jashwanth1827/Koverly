import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { policyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { AddPolicyModal } from "@/components/AddPolicyModal";
import { useToast } from "@/components/Toast";
import { usePageMeta } from "@/lib/pageMeta";
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
  const toast = useToast();
  usePageMeta("Policies", "Every insurance policy your family holds, in one place.");

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
        <>
        <div className="card hidden overflow-hidden sm:block">
          <table className="w-full">
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

        <ul className="space-y-3 sm:hidden">
          {policies.data!.items.map((p) => {
            const expiry = p.renewal_date ?? p.expiry_date;
            const days = daysUntil(expiry);
            return (
              <li key={p.id} className="card p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Link to={`/policies/${p.id}`} className="font-medium text-ink-900">
                      {p.insurer}
                    </Link>
                    <p className="break-all text-xs text-ink-500">{p.policy_number}</p>
                  </div>
                  <StatusBadge status={p.status} />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <dt className="text-xs text-ink-500">Type</dt>
                    <dd className="text-ink-900">{policyTypeLabel(p.policy_type)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-500">Sum insured</dt>
                    <dd className="text-ink-900">{formatCurrency(p.sum_insured)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-500">Premium</dt>
                    <dd className="text-ink-900">
                      {formatPremium(p.premium)}
                      {p.premium_frequency && <span className="text-xs"> /{p.premium_frequency}</span>}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-500">Renewal / expiry</dt>
                    <dd className="text-ink-900">
                      {formatDate(expiry)}
                      {days !== null && days >= 0 && days <= 60 && (
                        <span className="ml-1 text-xs font-medium text-amber-700">in {days}d</span>
                      )}
                    </dd>
                  </div>
                </dl>
              </li>
            );
          })}
        </ul>
        </>
      )}

      {showForm && (
        <AddPolicyModal
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false);
            toast.success("Policy added to your family.");
            policies.reload();
          }}
        />
      )}
    </div>
  );
}
