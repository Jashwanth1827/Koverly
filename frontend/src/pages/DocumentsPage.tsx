import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { documentApi, policyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ApiError } from "@/api/client";
import { ConfirmButton, Modal } from "@/components/Modal";
import { Badge, Disclaimer, EmptyState, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { formatDate } from "@/lib/format";
import type { Document, Extraction } from "@/api/types";

const ACCEPT = "application/pdf,image/jpeg,image/png";

export function DocumentsPage() {
  const { activeFamilyId, activeAccess } = useAuth();
  const docs = useAsync(() => documentApi.list(activeFamilyId!, { page_size: 100 }), [activeFamilyId]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewDoc, setReviewDoc] = useState<Document | null>(null);

  const canWrite = activeAccess?.role !== "viewer";
  if (!activeFamilyId) return null;

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    try {
      await documentApi.upload(activeFamilyId!, file);
      // Processing runs in the background; poll briefly for the result.
      setTimeout(() => docs.reload(), 800);
      setTimeout(() => docs.reload(), 2500);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not upload the document.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Documents"
        description="Your private policy document vault. Files are stored privately and never public."
        action={
          canWrite ? (
            <label className="btn-primary cursor-pointer">
              {uploading ? "Uploading…" : "Upload document"}
              <input
                type="file"
                className="sr-only"
                accept={ACCEPT}
                disabled={uploading}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) upload(f);
                  e.target.value = "";
                }}
              />
            </label>
          ) : undefined
        }
      />

      <p className="mb-4 text-sm text-ink-500">
        Accepted formats: PDF, JPG, PNG. Text is extracted automatically and proposed fields must be
        reviewed by you before they are applied to a policy.
      </p>

      {error && <p role="alert" className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {docs.loading ? (
        <Loading />
      ) : docs.error ? (
        <ErrorState message={docs.error} onRetry={docs.reload} />
      ) : docs.data!.total === 0 ? (
        <EmptyState
          title="No documents yet"
          description="Upload a policy PDF or a photo of a policy and Koverly will extract the key details for you to review."
        />
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead>
                <tr>
                  <th className="table-head">File</th>
                  <th className="table-head">Type</th>
                  <th className="table-head">Status</th>
                  <th className="table-head">Uploaded</th>
                  <th className="table-head"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {docs.data!.items.map((d) => (
                  <tr key={d.id} className="hover:bg-slate-50">
                    <td className="table-cell">
                      <span className="font-medium text-ink-900">{d.original_filename}</span>
                      {d.processing_error && (
                        <p className="text-xs text-red-600">{d.processing_error}</p>
                      )}
                    </td>
                    <td className="table-cell">{d.document_type}</td>
                    <td className="table-cell"><StatusBadge status={d.status} /></td>
                    <td className="table-cell">{formatDate(d.created_at)}</td>
                    <td className="table-cell">
                      <div className="flex items-center justify-end gap-2">
                        {d.status === "processed" && (
                          <button className="btn-secondary px-3 py-1 text-xs" onClick={() => setReviewDoc(d)}>
                            Review fields
                          </button>
                        )}
                        {d.status === "failed" && canWrite && (
                          <button
                            className="btn-secondary px-3 py-1 text-xs"
                            onClick={async () => {
                              await documentApi.reprocess(activeFamilyId, d.id);
                              docs.reload();
                            }}
                          >
                            Retry
                          </button>
                        )}
                        <button
                          className="btn-secondary px-3 py-1 text-xs"
                          onClick={async () => {
                            const res = await documentApi.signedUrl(activeFamilyId, d.id);
                            window.open(res.url, "_blank", "noopener,noreferrer");
                          }}
                        >
                          Open
                        </button>
                        {canWrite && (
                          <ConfirmButton
                            className="btn-ghost px-2 py-1 text-xs"
                            confirmLabel="Delete"
                            onConfirm={async () => {
                              await documentApi.remove(activeFamilyId, d.id);
                              docs.reload();
                            }}
                          >
                            Delete
                          </ConfirmButton>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Disclaimer>
        Document access uses short-lived signed URLs. Files are stored in private storage and are
        never exposed publicly.
      </Disclaimer>

      {reviewDoc && (
        <ReviewModal
          familyId={activeFamilyId}
          doc={reviewDoc}
          onClose={() => setReviewDoc(null)}
          onDone={() => { setReviewDoc(null); docs.reload(); }}
        />
      )}
    </div>
  );
}

function ReviewModal({
  familyId,
  doc,
  onClose,
  onDone,
}: {
  familyId: string;
  doc: Document;
  onClose: () => void;
  onDone: () => void;
}) {
  const extractions = useAsync(() => documentApi.extractions(familyId, doc.id), [familyId, doc.id]);
  const policies = useAsync(() => policyApi.list(familyId, { page_size: 100 }), [familyId]);
  const [policyId, setPolicyId] = useState(doc.policy_id ?? "");
  const [values, setValues] = useState<Record<string, string>>({});
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function currentValue(f: Extraction): string {
    return values[f.field_name] ?? f.value ?? "";
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const confirm: Record<string, string> = {};
      for (const f of extractions.data ?? []) {
        if (rejected.has(f.field_name)) continue;
        const v = currentValue(f);
        if (v) confirm[f.field_name] = v;
      }
      await documentApi.confirm(familyId, doc.id, {
        policy_id: policyId || undefined,
        confirm,
        reject: Array.from(rejected),
      });
      onDone();
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "POLICY_REQUIRED"
          ? "Select a policy to apply the confirmed fields to."
          : err instanceof ApiError
            ? err.message
            : "Could not save the review.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Review extracted information" onClose={onClose} wide>
      <p className="mb-4 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
        AI extracted the information below. Confirm what is correct, edit anything that is wrong, and
        reject anything that does not apply. Nothing is applied to a policy until you confirm.
      </p>

      {extractions.loading ? (
        <Loading />
      ) : extractions.error ? (
        <ErrorState message={extractions.error} onRetry={extractions.reload} />
      ) : (
        <div className="space-y-3">
          <div>
            <label className="label" htmlFor="r-policy">Apply to policy</label>
            <select id="r-policy" className="input" value={policyId}
              onChange={(e) => setPolicyId(e.target.value)}>
              <option value="">Don't apply to a policy</option>
              {policies.data?.items.map((p) => (
                <option key={p.id} value={p.id}>{p.insurer} — {p.policy_number}</option>
              ))}
            </select>
          </div>

          <ul className="divide-y divide-slate-100">
            {extractions.data!.map((f) => {
              const isRejected = rejected.has(f.field_name);
              return (
                <li key={f.id} className="flex flex-wrap items-center gap-3 py-3">
                  <div className="w-40 shrink-0">
                    <p className="text-sm font-medium capitalize text-ink-900">
                      {f.field_name.replace(/_/g, " ")}
                    </p>
                    <div className="mt-1 flex items-center gap-2">
                      {f.found ? (
                        <Badge tone={f.confidence >= 0.7 ? "good" : "warn"}>
                          {Math.round(f.confidence * 100)}% confidence
                        </Badge>
                      ) : (
                        <Badge tone="neutral">not found</Badge>
                      )}
                      {f.source_page && <span className="text-xs text-ink-300">p.{f.source_page}</span>}
                    </div>
                  </div>
                  <div className="min-w-[180px] flex-1">
                    {f.found ? (
                      <input
                        className="input"
                        value={currentValue(f)}
                        disabled={isRejected}
                        onChange={(e) => setValues((v) => ({ ...v, [f.field_name]: e.target.value }))}
                        aria-label={`Value for ${f.field_name}`}
                      />
                    ) : (
                      <p className="text-sm italic text-ink-300">Not found in uploaded document</p>
                    )}
                  </div>
                  <label className="flex items-center gap-1 text-xs text-ink-500">
                    <input
                      type="checkbox"
                      checked={isRejected}
                      onChange={(e) => {
                        setRejected((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(f.field_name);
                          else next.delete(f.field_name);
                          return next;
                        });
                      }}
                    />
                    Reject
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="mt-5 flex justify-end gap-3">
        <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={busy || extractions.loading} onClick={submit}>
          {busy ? "Saving…" : "Confirm & apply"}
        </button>
      </div>
    </Modal>
  );
}
