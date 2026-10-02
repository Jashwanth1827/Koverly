import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { claimApi, policyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ApiError } from "@/api/client";
import { Modal } from "@/components/Modal";
import { EmptyState, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { claimStatusLabel, formatDate, formatPremium } from "@/lib/format";
import type { ClaimStatus } from "@/api/types";

const STATUSES: ClaimStatus[] = [
  "draft",
  "submitted",
  "documents_required",
  "under_review",
  "approved",
  "rejected",
  "settled",
  "closed",
];

export function ClaimsPage() {
  const { activeFamilyId, activeAccess } = useAuth();
  const [statusFilter, setStatusFilter] = useState("");
  const [showNew, setShowNew] = useState(false);
  const claims = useAsync(
    () => claimApi.list(activeFamilyId!, statusFilter ? { status: statusFilter } : {}),
    [activeFamilyId, statusFilter],
  );

  const canWrite = activeAccess?.role !== "viewer";
  if (!activeFamilyId) return null;

  return (
    <div>
      <PageHeader
        title="Claims"
        description="Track every claim and its progress."
        action={canWrite ? <button className="btn-primary" onClick={() => setShowNew(true)}>New claim</button> : undefined}
      />

      <div className="mb-4">
        <select className="input max-w-xs" value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{claimStatusLabel(s)}</option>)}
        </select>
      </div>

      {claims.loading ? (
        <Loading />
      ) : claims.error ? (
        <ErrorState message={claims.error} onRetry={claims.reload} />
      ) : claims.data!.total === 0 ? (
        <EmptyState
          title="No claims"
          description="When something happens, record the claim here to track its progress and documents."
          action={canWrite ? <button className="btn-primary" onClick={() => setShowNew(true)}>New claim</button> : undefined}
        />
      ) : (
        <div className="space-y-3">
          {claims.data!.items.map((c) => (
            <Link key={c.id} to={`/claims/${c.id}`} className="card block p-4 hover:border-brand-300">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium text-ink-900">{c.claim_type.replace(/_/g, " ")}</p>
                  <p className="text-sm text-ink-500">
                    {c.provider ?? "Provider not recorded"} · incident {formatDate(c.incident_date)}
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-sm font-medium text-ink-900">{formatPremium(c.claim_amount)}</span>
                  <StatusBadge status={c.status} />
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {showNew && (
        <NewClaimModal
          familyId={activeFamilyId}
          onClose={() => setShowNew(false)}
          onDone={() => { setShowNew(false); claims.reload(); }}
        />
      )}
    </div>
  );
}

function NewClaimModal({
  familyId,
  onClose,
  onDone,
}: {
  familyId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const policies = useAsync(() => policyApi.list(familyId, { page_size: 100 }), [familyId]);
  const [form, setForm] = useState({
    policy_id: "",
    claim_type: "hospitalisation",
    claim_amount: "",
    provider: "",
    incident_date: "",
    description: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.policy_id) {
      setError("Select the policy this claim is under.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await claimApi.create(familyId, {
        family_id: familyId,
        policy_id: form.policy_id,
        claim_type: form.claim_type,
        claim_amount: form.claim_amount || null,
        provider: form.provider || null,
        incident_date: form.incident_date || null,
        description: form.description || null,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the claim.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="New claim" onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="c-policy">Policy</label>
          <select id="c-policy" className="input" value={form.policy_id}
            onChange={(e) => setForm((f) => ({ ...f, policy_id: e.target.value }))} required>
            <option value="">Select a policy…</option>
            {policies.data?.items.map((p) => (
              <option key={p.id} value={p.id}>{p.insurer} — {p.policy_number}</option>
            ))}
          </select>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="c-type">Claim type</label>
            <input id="c-type" className="input" value={form.claim_type}
              onChange={(e) => setForm((f) => ({ ...f, claim_type: e.target.value }))} required />
          </div>
          <div>
            <label className="label" htmlFor="c-amount">Claim amount</label>
            <input id="c-amount" className="input" inputMode="decimal" value={form.claim_amount}
              onChange={(e) => setForm((f) => ({ ...f, claim_amount: e.target.value }))} />
          </div>
          <div>
            <label className="label" htmlFor="c-provider">Hospital / provider</label>
            <input id="c-provider" className="input" value={form.provider}
              onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))} />
          </div>
          <div>
            <label className="label" htmlFor="c-date">Incident date</label>
            <input id="c-date" type="date" className="input" value={form.incident_date}
              onChange={(e) => setForm((f) => ({ ...f, incident_date: e.target.value }))} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="c-desc">Description</label>
          <textarea id="c-desc" className="input" rows={3} value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
        </div>
        {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy}>{busy ? "Creating…" : "Create claim"}</button>
        </div>
      </form>
    </Modal>
  );
}
