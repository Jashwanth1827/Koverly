import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { claimApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ApiError } from "@/api/client";
import { Disclaimer, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { claimStatusLabel, formatDate, formatPremium } from "@/lib/format";
import type { ClaimStatus } from "@/api/types";

const NEXT_STATUSES: Record<string, ClaimStatus[]> = {
  draft: ["submitted"],
  submitted: ["documents_required", "under_review"],
  documents_required: ["under_review"],
  under_review: ["approved", "rejected"],
  approved: ["settled"],
  settled: ["closed"],
  rejected: ["closed"],
  closed: [],
};

export function ClaimDetailPage() {
  const { claimId } = useParams();
  const { activeFamilyId, activeAccess } = useAuth();
  const claim = useAsync(() => claimApi.get(activeFamilyId!, claimId!), [activeFamilyId, claimId]);
  const docs = useAsync(() => claimApi.documents(activeFamilyId!, claimId!), [activeFamilyId, claimId]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const canWrite = activeAccess?.role !== "viewer";

  if (claim.loading) return <Loading />;
  if (claim.error) return <ErrorState message={claim.error} onRetry={claim.reload} />;
  const c = claim.data!;

  async function changeStatus(next: ClaimStatus) {
    setError(null);
    try {
      await claimApi.update(activeFamilyId!, c.id, { status: next });
      claim.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the claim.");
    }
  }

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    try {
      await claimApi.uploadDocument(activeFamilyId!, c.id, file);
      docs.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not upload the document.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div>
      <div className="mb-2 text-sm text-ink-500">
        <Link to="/claims" className="hover:underline">Claims</Link> / {c.claim_type}
      </div>
      <PageHeader title={c.claim_type.replace(/_/g, " ")} description={c.provider ?? undefined} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <StatusBadge status={c.status} />
        <span className="text-sm text-ink-700">Claimed {formatPremium(c.claim_amount)}</span>
        {c.approved_amount && (
          <span className="text-sm text-ink-700">Approved {formatPremium(c.approved_amount)}</span>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">Details</h2>
          <dl className="mt-3 grid gap-x-8 gap-y-3 sm:grid-cols-2 text-sm">
            <div><dt className="text-ink-500">Incident date</dt><dd>{formatDate(c.incident_date)}</dd></div>
            <div><dt className="text-ink-500">Submitted</dt><dd>{formatDate(c.submission_date)}</dd></div>
          </dl>
          {c.description && <p className="mt-4 text-sm text-ink-700">{c.description}</p>}
          {c.notes && <p className="mt-2 text-sm text-ink-500">{c.notes}</p>}

          {canWrite && NEXT_STATUSES[c.status]?.length > 0 && (
            <div className="mt-5 flex flex-wrap gap-2">
              {NEXT_STATUSES[c.status].map((next) => (
                <button key={next} className="btn-secondary" onClick={() => changeStatus(next)}>
                  Mark {claimStatusLabel(next)}
                </button>
              ))}
            </div>
          )}
          {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">Timeline</h2>
          <ol className="mt-3 space-y-3">
            {c.events.map((ev) => (
              <li key={ev.id} className="border-l-2 border-brand-200 pl-3">
                <p className="text-sm font-medium text-ink-900">{claimStatusLabel(ev.status)}</p>
                <p className="text-xs text-ink-500">{formatDate(ev.created_at)}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="card p-5 lg:col-span-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">Claim documents</h2>
            {canWrite && (
              <label className="btn-secondary cursor-pointer">
                {uploading ? "Uploading…" : "Upload"}
                <input
                  type="file"
                  className="sr-only"
                  accept="application/pdf,image/jpeg,image/png"
                  disabled={uploading}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) upload(f);
                    e.target.value = "";
                  }}
                />
              </label>
            )}
          </div>
          {docs.loading ? (
            <p className="mt-3 text-sm text-ink-500">Loading…</p>
          ) : docs.data && docs.data.length > 0 ? (
            <ul className="mt-3 divide-y divide-slate-100">
              {docs.data.map((d) => (
                <li key={d.id} className="flex items-center justify-between py-3">
                  <span className="text-sm text-ink-900">{d.original_filename}</span>
                  <StatusBadge status={d.status} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-ink-500">No documents uploaded for this claim.</p>
          )}
        </section>
      </div>

      <Disclaimer>
        Koverly tracks your claim and its documents. It does not decide claim outcomes — only your
        insurer can approve or reject a claim.
      </Disclaimer>
    </div>
  );
}
