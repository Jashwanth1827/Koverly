import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { documentApi, policyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ApiError, errorMessage, saveBlob } from "@/api/client";
import { ConfirmButton, Modal } from "@/components/Modal";
import { Badge, Disclaimer, EmptyState, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { ACCEPTED_FORMATS_LABEL, ACCEPTED_UPLOAD_TYPES, formatDate } from "@/lib/format";
import { compressedImageDataUrl } from "@/lib/images";
import { useToast } from "@/components/Toast";
import { usePageMeta } from "@/lib/pageMeta";
import type { Document, Extraction } from "@/api/types";

export function DocumentsPage() {
  const { activeFamilyId, activeAccess } = useAuth();
  const docs = useAsync(() => documentApi.list(activeFamilyId!, { page_size: 100 }), [activeFamilyId]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewDoc, setReviewDoc] = useState<Document | null>(null);
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null);
  const toast = useToast();
  usePageMeta("Documents", "Your private policy document vault.");

  const canWrite = activeAccess?.role !== "viewer";
  if (!activeFamilyId) return null;

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    try {
      await documentApi.upload(activeFamilyId!, file);
      toast.success("Document uploaded. Extracted details will appear shortly.");
      // Processing runs in the background; poll briefly for the result.
      setTimeout(() => docs.reload(), 800);
      setTimeout(() => docs.reload(), 2500);
    } catch (err) {
      const message = errorMessage(err, "Could not upload the document.");
      setError(message);
      toast.error(message);
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
                accept={ACCEPTED_UPLOAD_TYPES}
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
        Accepted formats: {ACCEPTED_FORMATS_LABEL}. Text is extracted automatically and proposed
        fields must be reviewed by you before they are applied to a policy.
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
        <>
        <div className="card hidden overflow-hidden sm:block">
          <table className="w-full">
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
                              try {
                                await documentApi.reprocess(activeFamilyId, d.id);
                                toast.success("Reprocessing started.");
                                docs.reload();
                              } catch (err) {
                                const message = errorMessage(err, "Could not reprocess the document.");
                                setError(message);
                                toast.error(message);
                              }
                            }}
                          >
                            Retry
                          </button>
                        )}
                        <button
                          className="btn-secondary px-3 py-1 text-xs"
                          onClick={() => setPreviewDoc(d)}
                        >
                          Open
                        </button>
                        {canWrite && (
                          <ConfirmButton
                            className="btn-ghost px-2 py-1 text-xs"
                            confirmLabel="Delete"
                            busyLabel="Deleting…"
                            onConfirm={async () => {
                              await documentApi.remove(activeFamilyId, d.id);
                              toast.success("Document deleted.");
                              await docs.reload();
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

        <ul className="space-y-3 sm:hidden">
          {docs.data!.items.map((d) => (
            <li key={d.id} className="card p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="break-all font-medium text-ink-900">{d.original_filename}</p>
                  <p className="mt-1 text-xs text-ink-500">
                    {d.document_type} · {formatDate(d.created_at)}
                  </p>
                </div>
                <StatusBadge status={d.status} />
              </div>
              {d.processing_error && (
                <p className="mt-2 break-words text-xs text-red-600">{d.processing_error}</p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {d.status === "processed" && (
                  <button className="btn-secondary px-3 py-1 text-xs" onClick={() => setReviewDoc(d)}>
                    Review fields
                  </button>
                )}
                {d.status === "failed" && canWrite && (
                  <button
                    className="btn-secondary px-3 py-1 text-xs"
                    onClick={async () => {
                      try {
                        await documentApi.reprocess(activeFamilyId, d.id);
                        toast.success("Reprocessing started.");
                        docs.reload();
                      } catch (err) {
                        const message = errorMessage(err, "Could not reprocess the document.");
                        setError(message);
                        toast.error(message);
                      }
                    }}
                  >
                    Retry
                  </button>
                )}
                <button
                  className="btn-secondary px-3 py-1 text-xs"
                  onClick={() => setPreviewDoc(d)}
                >
                  Open
                </button>
                {canWrite && (
                  <ConfirmButton
                    className="btn-ghost px-2 py-1 text-xs"
                    confirmLabel="Delete"
                    busyLabel="Deleting…"
                    onConfirm={async () => {
                      await documentApi.remove(activeFamilyId, d.id);
                      toast.success("Document deleted.");
                      await docs.reload();
                    }}
                  >
                    Delete
                  </ConfirmButton>
                )}
              </div>
            </li>
          ))}
        </ul>
        </>
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

      {previewDoc && (
        <DocumentPreviewModal
          familyId={activeFamilyId}
          doc={previewDoc}
          onClose={() => setPreviewDoc(null)}
        />
      )}
    </div>
  );
}

/** In-app preview (PDF/image) plus download options.
 *
 * The uploaded file is fetched as an authenticated blob and rendered from an
 * in-memory object URL, so it is never placed in a URL the browser stores.
 * When the document is linked to a policy, a Koverly-generated summary PDF
 * (built from the recorded values, not the raw upload) can be downloaded too.
 */
function DocumentPreviewModal({
  familyId,
  doc,
  onClose,
}: {
  familyId: string;
  doc: Document;
  onClose: () => void;
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const toast = useToast();
  const isPdf = doc.content_type === "application/pdf";

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setBlobUrl(null);
    setError(null);
    documentApi
      .previewBlob(familyId, doc.id)
      .then(async (blob) => {
        if (cancelled) return;
        if (!isPdf) {
          try {
            // Smaller in-memory preview; the stored document stays untouched.
            const dataUrl = await compressedImageDataUrl(blob);
            if (!cancelled) setBlobUrl(dataUrl);
            return;
          } catch {
            /* fall back to the original blob below */
          }
        }
        url = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(url);
          url = null;
        } else {
          setBlobUrl(url);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err, "Could not open the document."));
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [familyId, doc.id, isPdf, reloadKey]);

  async function download() {
    setDownloading(true);
    try {
      const blob = await documentApi.previewBlob(familyId, doc.id);
      saveBlob(blob, doc.original_filename);
      toast.success("Download started.");
    } catch (err) {
      const message = errorMessage(err, "Could not download the document.");
      setError(message);
      toast.error(message);
    } finally {
      setDownloading(false);
    }
  }

  async function downloadSummary() {
    if (!doc.policy_id) return;
    setSummarizing(true);
    try {
      const blob = await policyApi.summaryPdfBlob(familyId, doc.policy_id);
      saveBlob(blob, `${doc.original_filename.replace(/\.[^.]+$/, "")}-summary.pdf`);
      toast.success("Summary PDF downloaded.");
    } catch (err) {
      const message = errorMessage(err, "Could not generate the summary PDF.");
      setError(message);
      toast.error(message);
    } finally {
      setSummarizing(false);
    }
  }

  return (
    <Modal title={doc.original_filename} onClose={onClose} wide>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <span className="text-xs text-ink-500">
          {doc.document_type} · {(doc.size_bytes / 1024).toFixed(0)} KB
        </span>
        <div className="flex gap-2">
          {doc.policy_id && (
            <button
              className="btn-secondary px-3 py-1 text-xs"
              onClick={downloadSummary}
              disabled={summarizing}
            >
              {summarizing ? "Preparing…" : "Download summary PDF"}
            </button>
          )}
          <button className="btn-secondary px-3 py-1 text-xs" onClick={download} disabled={downloading}>
            {downloading ? "Preparing…" : "Download copy"}
          </button>
        </div>
      </div>

      {error ? (
        <div className="space-y-3">
          <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />
        </div>
      ) : !blobUrl ? (
        <Loading />
      ) : isPdf ? (
        <iframe
          title={`Preview of ${doc.original_filename}`}
          src={blobUrl}
          className="h-[70vh] w-full rounded-lg border border-slate-200"
        />
      ) : (
        <img
          src={blobUrl}
          alt={`Preview of ${doc.original_filename}`}
          loading="lazy"
          decoding="async"
          className="mx-auto max-h-[70vh] max-w-full rounded-lg border border-slate-200 object-contain"
        />
      )}

      <p className="mt-3 text-xs text-ink-300">
        This preview is fetched over an authenticated request. The file stays in private storage and
        is never exposed publicly. The summary PDF is generated by Koverly from the recorded values,
        not copied from your upload.
      </p>
    </Modal>
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
  const toast = useToast();

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
      toast.success("Extracted fields confirmed and applied.");
      onDone();
    } catch (err) {
      const message =
        err instanceof ApiError && err.code === "POLICY_REQUIRED"
          ? "Select a policy to apply the confirmed fields to."
          : errorMessage(err, "Could not save the review.");
      setError(message);
      toast.error(message);
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
                  <div className="w-full shrink-0 sm:w-40">
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
                  <div className="min-w-0 w-full flex-1 sm:min-w-[180px]">
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
