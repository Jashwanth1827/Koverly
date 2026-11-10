import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { documentApi, policyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { errorMessage, saveBlob } from "@/api/client";
import { ConfirmButton, Modal } from "@/components/Modal";
import { Badge, Disclaimer, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { daysUntil, formatCurrency, formatDate, formatPremium, policyTypeLabel } from "@/lib/format";

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border-b border-slate-100 py-3">
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-ink-900">{value || "—"}</dd>
    </div>
  );
}

export function PolicyDetailPage() {
  const { policyId } = useParams();
  const { activeFamilyId, activeAccess } = useAuth();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [downloadingSummary, setDownloadingSummary] = useState(false);

  const policy = useAsync(() => policyApi.get(activeFamilyId!, policyId!), [activeFamilyId, policyId]);
  const docs = useAsync(() => documentApi.list(activeFamilyId!, { policy_id: policyId! }), [activeFamilyId, policyId]);

  const canWrite = activeAccess?.role !== "viewer";
  const canDelete = activeAccess?.role === "admin" || activeAccess?.role === "owner";

  if (policy.loading) return <Loading />;
  if (policy.error) return <ErrorState message={policy.error} onRetry={policy.reload} />;
  const p = policy.data!;

  async function saveEdits(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await policyApi.update(activeFamilyId!, p.id, {
        insurer: editForm.insurer,
        policy_number: editForm.policy_number,
        premium: editForm.premium || null,
        premium_frequency: editForm.premium ? editForm.premium_frequency : null,
        sum_insured: editForm.sum_insured || null,
        start_date: editForm.start_date || null,
        expiry_date: editForm.expiry_date || null,
        renewal_date: editForm.renewal_date || null,
        nominee: editForm.nominee || null,
        status: editForm.status,
      });
      setEditing(false);
      policy.reload();
    } catch (err) {
      setError(errorMessage(err, "Could not save changes."));
    }
  }

  async function downloadSummary() {
    setDownloadingSummary(true);
    setError(null);
    try {
      const blob = await policyApi.summaryPdfBlob(activeFamilyId!, p.id);
      saveBlob(blob, `${p.insurer}-${p.policy_number}-summary.pdf`);
    } catch (err) {
      setError(errorMessage(err, "Could not generate the summary PDF."));
    } finally {
      setDownloadingSummary(false);
    }
  }

  function openEdit() {
    setEditForm({
      insurer: p.insurer,
      policy_number: p.policy_number,
      premium: p.premium ?? "",
      premium_frequency: p.premium_frequency ?? "yearly",
      sum_insured: p.sum_insured ?? "",
      start_date: p.start_date ?? "",
      expiry_date: p.expiry_date ?? "",
      renewal_date: p.renewal_date ?? "",
      nominee: p.nominee ?? "",
      status: p.status,
    });
    setEditing(true);
  }

  const expiry = p.renewal_date ?? p.expiry_date;
  const days = daysUntil(expiry);

  return (
    <div>
      <div className="mb-2 text-sm text-ink-500">
        <Link to="/policies" className="hover:underline">Policies</Link> / {p.insurer}
      </div>
      <PageHeader
        title={`${p.insurer} — ${policyTypeLabel(p.policy_type)}`}
        description={p.policy_number}
        action={
          canWrite ? (
            <div className="flex gap-2">
              <button className="btn-secondary" onClick={downloadSummary} disabled={downloadingSummary}>
                {downloadingSummary ? "Preparing…" : "Download summary PDF"}
              </button>
              <button className="btn-secondary" onClick={openEdit}>Edit</button>
              {canDelete && (
                <ConfirmButton
                  confirmLabel="Delete policy"
                  onConfirm={async () => {
                    await policyApi.remove(activeFamilyId!, p.id);
                    navigate("/policies");
                  }}
                >
                  Delete
                </ConfirmButton>
              )}
            </div>
          ) : undefined
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <StatusBadge status={p.status} />
        {days !== null && days >= 0 && days <= 60 && (
          <Badge tone={days <= 7 ? "bad" : "warn"}>Renewal in {days} days</Badge>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">Policy details</h2>
          <dl className="mt-2 grid gap-x-8 sm:grid-cols-2">
            <Field label="Sum insured" value={formatCurrency(p.sum_insured)} />
            <Field label="Premium" value={`${formatPremium(p.premium)}${p.premium_frequency ? ` / ${p.premium_frequency}` : ""}`} />
            <Field label="Start date" value={formatDate(p.start_date)} />
            <Field label="Expiry date" value={formatDate(p.expiry_date)} />
            <Field label="Renewal date" value={formatDate(p.renewal_date)} />
            <Field label="Maturity date" value={formatDate(p.maturity_date)} />
            <Field label="Nominee" value={p.nominee} />
            <Field label="Policyholder" value={p.policyholder_name} />
          </dl>
          {p.notes && <p className="mt-4 text-sm text-ink-700">{p.notes}</p>}
        </section>

        <section className="card p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">Documents</h2>
            <Link to="/documents" className="text-xs font-medium text-brand-700 hover:underline">
              Upload
            </Link>
          </div>
          {docs.loading ? (
            <p className="mt-3 text-sm text-ink-500">Loading…</p>
          ) : docs.data && docs.data.total > 0 ? (
            <ul className="mt-3 space-y-2">
              {docs.data.items.map((d) => (
                <li key={d.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate text-ink-900">{d.original_filename}</span>
                  <StatusBadge status={d.status} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-ink-500">No documents linked to this policy.</p>
          )}
        </section>
      </div>

      <Disclaimer>
        Policy details shown here are the values you or the AI extraction recorded. Always confirm
        against the original policy document issued by your insurer.
      </Disclaimer>

      {editing && (
        <Modal title="Edit policy" onClose={() => setEditing(false)} wide>
          <form onSubmit={saveEdits} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              {(["insurer", "policy_number", "premium", "sum_insured", "start_date", "expiry_date", "renewal_date", "nominee"] as const).map((key) => (
                <div key={key}>
                  <label className="label" htmlFor={key}>{key.replace(/_/g, " ")}</label>
                  <input
                    id={key}
                    type={key.endsWith("_date") ? "date" : "text"}
                    className="input"
                    value={editForm[key] ?? ""}
                    onChange={(e) => setEditForm((f) => ({ ...f, [key]: e.target.value }))}
                  />
                </div>
              ))}
              <div>
                <label className="label" htmlFor="status">Status</label>
                <select
                  id="status"
                  className="input"
                  value={editForm.status}
                  onChange={(e) => setEditForm((f) => ({ ...f, status: e.target.value }))}
                >
                  {["active", "lapsed", "expired", "cancelled", "pending"].map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </div>
            {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            <div className="flex justify-end gap-3">
              <button type="button" className="btn-secondary" onClick={() => setEditing(false)}>Cancel</button>
              <button className="btn-primary">Save changes</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
