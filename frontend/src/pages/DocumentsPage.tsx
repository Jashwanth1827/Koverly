import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { configApi, documentApi, policyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ApiError } from "@/api/client";
import { ConfirmButton, Modal } from "@/components/Modal";
import { Badge, Disclaimer, EmptyState, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { ACCEPTED_FORMATS_LABEL, ACCEPTED_UPLOAD_TYPES, POLICY_TYPE_LABELS, formatDate } from "@/lib/format";
import type { Document, Extraction } from "@/api/types";

export function DocumentsPage() {
  const { activeFamilyId, activeAccess } = useAuth();
  const docs = useAsync(() => documentApi.list(activeFamilyId!, { page_size: 100 }), [activeFamilyId]);
  const config = useAsync(() => configApi.get(), []);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewDoc, setReviewDoc] = useState<Document | null>(null);
  const [notice, setNotice] = useState<{ message: string; policyId: string | null } | null>(null);

  const pending = docs.data?.items.some(
    (d) => d.status === "uploaded" || d.status === "processing",
  );

  // Processing runs in the background; refresh while any document is pending.
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => docs.reload(), 2000);
    return () => window.clearInterval(timer);
  }, [pending, docs.reload]);

  const canWrite = activeAccess?.role !== "viewer";
  if (!activeFamilyId) return null;

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const doc = await documentApi.upload(activeFamilyId!, file);
      // Open the scanner immediately; it polls until extraction is complete.
      setReviewDoc(doc);
      docs.reload();
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
        {config.data?.ocr_available
          ? " Scanned pages and photos are read with on-device OCR."
          : config.data
            ? " Image OCR is unavailable in this deployment, so photos and scanned PDFs cannot be read."
            : ""}
      </p>

      {error && <p role="alert" className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {notice && (
        <div
          role="status"
          className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
        >
          <span>{notice.message}</span>
          <span className="flex items-center gap-3">
            {notice.policyId && (
              <Link className="font-medium underline" to={`/policies/${notice.policyId}`}>
                View policy
              </Link>
            )}
            <button className="text-emerald-700" onClick={() => setNotice(null)} aria-label="Dismiss">
              Dismiss
            </button>
          </span>
        </div>
      )}

      {config.data && !config.data.ocr_available && (
        <p className="mb-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          OCR is not configured. Text-based PDFs still work; images and scanned PDFs will fail with a
          clear reason rather than inventing data.
        </p>
      )}

      {docs.loading && !docs.data ? (
        <Loading />
      ) : docs.error && !docs.data ? (
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
                      {d.status === "processing" && (
                        <p className="text-xs text-ink-500">Reading document…</p>
                      )}
                      {d.status === "processed" && d.page_count != null && (
                        <p className="text-xs text-ink-500">
                          {d.page_count} {d.page_count === 1 ? "page" : "pages"}
                        </p>
                      )}
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
        <ExtractionModal
          familyId={activeFamilyId}
          doc={reviewDoc}
          onClose={() => setReviewDoc(null)}
          onDone={(policyId) => {
            setReviewDoc(null);
            docs.reload();
            setNotice({
              message: "Document details saved to a policy.",
              policyId,
            });
          }}
        />
      )}
    </div>
  );
}

type Phase = "scanning" | "failed" | "review";

function fieldLabel(name: string): string {
  const label = name.replace(/_/g, " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function ExtractionModal({
  familyId,
  doc,
  onClose,
  onDone,
}: {
  familyId: string;
  doc: Document;
  onClose: () => void;
  onDone: (policyId: string | null) => void;
}) {
  const [phase, setPhase] = useState<Phase>(
    doc.status === "processed" ? "review" : doc.status === "failed" ? "failed" : "scanning",
  );
  const [current, setCurrent] = useState<Document>(doc);
  const [pollNonce, setPollNonce] = useState(0);
  const [extractions, setExtractions] = useState<Extraction[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  const [destination, setDestination] = useState<"create" | "existing">(
    doc.policy_id ? "existing" : "create",
  );
  const [policyId, setPolicyId] = useState(doc.policy_id ?? "");
  const [policyType, setPolicyType] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const policies = useAsync(() => policyApi.list(familyId, { page_size: 100 }), [familyId]);

  async function loadReview() {
    const rows = await documentApi.extractions(familyId, doc.id);
    const initial: Record<string, string> = {};
    for (const row of rows) initial[row.field_name] = row.value ?? "";
    setExtractions(rows);
    setValues(initial);
    setDrafts(initial);
    setPhase("review");
  }

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const latest = await documentApi.get(familyId, doc.id);
        if (cancelled) return;
        setCurrent(latest);
        if (latest.status === "processed") {
          await loadReview();
        } else if (latest.status === "failed") {
          setPhase("failed");
        } else {
          setPhase("scanning");
          timer = window.setTimeout(poll, 1500);
        }
      } catch (err) {
        if (cancelled) return;
        setLoadError(
          err instanceof ApiError ? err.message : "Could not check the document status.",
        );
        setPhase("failed");
      }
    }

    if (current.status === "processed") {
      setPhase("review");
      loadReview().catch(() => setPhase("failed"));
    } else if (current.status === "failed") {
      setPhase("failed");
    } else {
      setPhase("scanning");
      poll();
    }

    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [familyId, doc.id, pollNonce]);

  function startEdit() {
    setDrafts(values);
    setEditing(true);
    setError(null);
  }

  function cancelEdit() {
    setDrafts(values);
    setEditing(false);
    setError(null);
  }

  function saveEdit() {
    setValues(drafts);
    setEditing(false);
    setError(null);
  }

  function retry() {
    setLoadError(null);
    setError(null);
    setPhase("scanning");
    documentApi
      .reprocess(familyId, doc.id)
      .then((updated) => {
        setCurrent(updated);
        setPollNonce((n) => n + 1);
      })
      .catch((err) => {
        setLoadError(err instanceof ApiError ? err.message : "Could not restart processing.");
        setPhase("failed");
      });
  }

  async function submit() {
    const confirm: Record<string, string> = {};
    const reject: string[] = [];
    for (const field of extractions ?? []) {
      const value = (values[field.field_name] ?? "").trim();
      if (value) confirm[field.field_name] = value;
      else reject.push(field.field_name);
    }

    const creating = !doc.policy_id && destination === "create";
    if (creating && (!confirm.insurer || !confirm.policy_number)) {
      setError("Add the insurer and policy number before creating a policy. Use Edit to fill them in.");
      setDrafts(values);
      setEditing(true);
      return;
    }
    if (!creating && !policyId) {
      setError("Choose an existing policy or create a new one.");
      return;
    }
    if (Object.keys(confirm).length === 0) {
      setError("Add at least one detail before submitting. Use Edit to fill in a field.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const rows = await documentApi.confirm(familyId, doc.id, {
        policy_id: creating ? undefined : policyId || undefined,
        create_policy: creating,
        policy_type: creating && policyType ? policyType : undefined,
        confirm,
        reject,
      });
      const resultingPolicyId = rows.find((row) => row.policy_id)?.policy_id ?? policyId ?? null;
      onDone(resultingPolicyId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the extracted details.");
    } finally {
      setBusy(false);
    }
  }

  const title =
    phase === "scanning"
      ? "Scanning document"
      : phase === "failed"
        ? "Could not read document"
        : "Review extracted details";
  const activePolicy = policies.data?.items.find((p) => p.id === policyId);

  return (
    <Modal title={title} onClose={busy ? () => {} : onClose} wide>
      {phase === "scanning" && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 rounded-xl border border-brand-100 bg-brand-50 px-4 py-4">
            <span className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
            <div>
              <p className="text-sm font-medium text-brand-900">Scanning and extracting details…</p>
              <p className="text-xs text-brand-700">{current.original_filename}</p>
            </div>
          </div>
          <ul className="space-y-2 text-sm text-ink-600">
            <li className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
              Reading the document text, including OCR for scans and photos
            </li>
            <li className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
              Extracting policy fields with confidence and page numbers
            </li>
          </ul>
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-ink-500">
            This usually takes a few seconds. You can close this window — processing continues in the
            background and the result stays available in the vault.
          </p>
        </div>
      )}

      {phase === "failed" && (
        <div className="space-y-4">
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-3">
            <p className="text-sm font-medium text-red-800">
              {current.processing_error || loadError || "The document could not be processed."}
            </p>
          </div>
          <p className="text-sm text-ink-500">
            You can retry processing, or close this window and enter the details manually from the
            policy page.
          </p>
          <div className="flex justify-end gap-3">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
            <button type="button" className="btn-primary" onClick={retry}>
              Retry processing
            </button>
          </div>
        </div>
      )}

      {phase === "review" && (
        <div className="space-y-4">
          <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
            These details were read from the document. Check them, edit anything that is wrong, then
            submit. Nothing is saved until you submit.
          </p>

          {extractions === null ? (
            <Loading />
          ) : extractions.length === 0 ? (
            <div className="space-y-4">
              <p className="text-sm text-ink-500">
                No policy fields were found in this document. You can enter the details manually from
                the policy page.
              </p>
              <div className="flex justify-end">
                <button type="button" className="btn-secondary" onClick={onClose}>
                  Close
                </button>
              </div>
            </div>
          ) : (
            <>
              {doc.policy_id ? (
                <p className="text-sm text-ink-600">
                  These details will be applied to
                  {activePolicy
                    ? ` ${activePolicy.insurer} — ${activePolicy.policy_number}.`
                    : " the linked policy."}
                </p>
              ) : (
                <fieldset className="rounded-xl border border-slate-200 p-3">
                  <legend className="px-1 text-sm font-medium text-ink-700">Save as</legend>
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 text-sm text-ink-700">
                      <input
                        type="radio"
                        name="destination"
                        checked={destination === "create"}
                        onChange={() => setDestination("create")}
                      />
                      Create a new policy
                    </label>
                    <label className="flex items-center gap-2 text-sm text-ink-700">
                      <input
                        type="radio"
                        name="destination"
                        checked={destination === "existing"}
                        onChange={() => setDestination("existing")}
                        disabled={!policies.data?.items.length}
                      />
                      Add to an existing policy
                    </label>
                    {destination === "existing" && (
                      <select
                        className="input"
                        value={policyId}
                        onChange={(e) => setPolicyId(e.target.value)}
                        aria-label="Existing policy"
                      >
                        <option value="">Select a policy…</option>
                        {policies.data?.items.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.insurer} — {p.policy_number}
                          </option>
                        ))}
                      </select>
                    )}
                    {destination === "create" && (
                      <>
                        <select
                          className="input"
                          value={policyType}
                          onChange={(e) => setPolicyType(e.target.value)}
                          aria-label="Policy type"
                        >
                          <option value="">Detect policy type automatically</option>
                          {Object.entries(POLICY_TYPE_LABELS).map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                        <p className="text-xs text-ink-500">
                          If a policy with the same number and insurer already exists, its details are
                          updated instead of creating a duplicate.
                        </p>
                      </>
                    )}
                  </div>
                </fieldset>
              )}

              <div className="divide-y divide-slate-100">
                {extractions.map((field) => {
                  const value = editing
                    ? drafts[field.field_name] ?? ""
                    : values[field.field_name] ?? "";
                  return (
                    <div key={field.id} className="flex flex-wrap items-center gap-3 py-3">
                      <div className="w-40 shrink-0">
                        <p className="text-sm font-medium text-ink-900">{fieldLabel(field.field_name)}</p>
                        <div className="mt-1 flex items-center gap-2">
                          {field.found ? (
                            <Badge tone={field.confidence >= 0.7 ? "good" : "warn"}>
                              {Math.round(field.confidence * 100)}% confidence
                            </Badge>
                          ) : (
                            <Badge tone="neutral">not in document</Badge>
                          )}
                          {field.source_page && (
                            <span className="text-xs text-ink-300">p.{field.source_page}</span>
                          )}
                        </div>
                      </div>
                      <div className="min-w-[180px] flex-1">
                        {editing ? (
                          <input
                            className="input"
                            value={value}
                            onChange={(e) =>
                              setDrafts((prev) => ({
                                ...prev,
                                [field.field_name]: e.target.value,
                              }))
                            }
                            placeholder={
                              field.found ? undefined : "Not found — enter manually if you know it"
                            }
                            aria-label={`Value for ${field.field_name}`}
                          />
                        ) : value ? (
                          <p className="text-sm text-ink-800">{value}</p>
                        ) : (
                          <p className="text-sm italic text-ink-300">
                            Not found in uploaded document
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {error && (
                <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                  {error}
                </p>
              )}

              <div className="flex flex-wrap justify-end gap-3 pt-2">
                {editing ? (
                  <>
                    <button type="button" className="btn-secondary" onClick={cancelEdit}>
                      Cancel edits
                    </button>
                    <button type="button" className="btn-primary" onClick={saveEdit}>
                      Save changes
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" className="btn-secondary" onClick={startEdit}>
                      Edit
                    </button>
                    <button type="button" className="btn-primary" disabled={busy} onClick={submit}>
                      {busy ? "Submitting…" : "Submit"}
                    </button>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  );
}
