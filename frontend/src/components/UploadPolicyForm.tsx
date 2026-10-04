import { useEffect, useRef, useState } from "react";
import { documentApi } from "@/api/endpoints";
import { errorMessage } from "@/api/client";
import { Badge, Loading } from "@/components/ui";
import type { Document, Extraction } from "@/api/types";

// Display order for the review step; anything else is appended afterwards.
const FIELD_ORDER = [
  "policy_type",
  "insurer",
  "policy_number",
  "policyholder_name",
  "sum_insured",
  "premium",
  "premium_frequency",
  "start_date",
  "expiry_date",
  "renewal_date",
  "nominee",
  "tpa",
  "waiting_period",
  "deductible",
  "claim_contact",
];

// Fields we require before a policy can be created from an upload.
const REQUIRED = ["insurer", "policy_number"] as const;

function orderFields(rows: Extraction[]): Extraction[] {
  return [...rows].sort((a, b) => {
    const ia = FIELD_ORDER.indexOf(a.field_name);
    const ib = FIELD_ORDER.indexOf(b.field_name);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });
}

export function UploadPolicyForm({
  familyId,
  onDone,
  onCancel,
}: {
  familyId: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [doc, setDoc] = useState<Document | null>(null);
  const [extractions, setExtractions] = useState<Extraction[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pollTimer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pollTimer.current) window.clearTimeout(pollTimer.current);
    };
  }, []);

  async function handleFile(file: File) {
    setError(null);
    setUploading(true);
    try {
      const created = await documentApi.upload(familyId, file, { document_type: "policy" });
      setDoc(created);
      poll(created.id, 0);
    } catch (err) {
      setError(errorMessage(err, "Could not upload the document."));
    } finally {
      setUploading(false);
    }
  }

  function poll(documentId: string, attempt: number) {
    documentApi
      .extractions(familyId, documentId)
      .then(async (rows) => {
        // Processing is asynchronous. Wait until fields appear, the document
        // fails, or we time out — never claim success before data exists.
        if (rows.length > 0) {
          setExtractions(orderFields(rows));
          return;
        }
        const latest = await documentApi.get(familyId, documentId);
        if (latest.status === "failed") {
          setError(
            latest.processing_error ??
              "We could not read this document. You can add the policy manually instead.",
          );
          return;
        }
        if (attempt >= 20) {
          setError(
            "Extraction is taking longer than expected. You can retry, or add the policy manually.",
          );
          return;
        }
        pollTimer.current = window.setTimeout(() => poll(documentId, attempt + 1), 3000);
      })
      .catch((err) => setError(errorMessage(err, "Could not read the extraction result.")));
  }

  function currentValue(f: Extraction): string {
    return values[f.field_name] ?? f.value ?? "";
  }

  async function submit() {
    if (!doc) return;
    const confirm: Record<string, string> = {};
    for (const f of extractions ?? []) {
      if (rejected.has(f.field_name)) continue;
      const v = currentValue(f).trim();
      if (v) confirm[f.field_name] = v;
    }
    const missing = REQUIRED.filter((r) => !confirm[r]);
    if (missing.length > 0) {
      setError(
        `Please provide ${missing.map((m) => m.replace(/_/g, " ")).join(" and ")} before saving.`,
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await documentApi.confirm(familyId, doc.id, {
        confirm,
        reject: Array.from(rejected),
      });
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Could not save the reviewed policy."));
    } finally {
      setBusy(false);
    }
  }

  if (!doc) {
    return (
      <div className="space-y-4">
        <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
          Upload a policy copy (PDF or image). Koverly will read it and show you what it found so you
          can check it before saving. Nothing is saved until you confirm.
        </p>
        <div>
          <label className="label" htmlFor="policy-copy">Policy copy</label>
          <input
            id="policy-copy"
            ref={fileRef}
            type="file"
            accept="application/pdf,image/jpeg,image/png"
            className="input"
            disabled={uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
            }}
          />
          <p className="mt-1 text-xs text-ink-300">PDF, JPG or PNG, up to 15 MB.</p>
        </div>
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
        )}
        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    );
  }

  if (error && !extractions) {
    return (
      <div className="space-y-4">
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onCancel}>Close</button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              setError(null);
              setDoc(null);
              if (fileRef.current) fileRef.current.value = "";
            }}
          >
            Try another file
          </button>
        </div>
      </div>
    );
  }

  if (!extractions) return <Loading label="Reading your policy copy…" />;

  return (
    <div className="space-y-4">
      <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
        Koverly read the information below from your upload. Check that it is correct, fix anything
        that is wrong, and reject anything that does not apply. The policy is created only from the
        values you confirm.
      </p>
      <p className="text-xs text-ink-300">Source file: {doc.original_filename}</p>

      <ul className="divide-y divide-slate-100">
        {extractions.map((f) => {
          const isRejected = rejected.has(f.field_name);
          const isRequired = (REQUIRED as readonly string[]).includes(f.field_name);
          return (
            <li key={f.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="w-40 shrink-0">
                <p className="text-sm font-medium capitalize text-ink-900">
                  {f.field_name.replace(/_/g, " ")}
                  {isRequired && <span className="ml-1 text-red-600" aria-label="required">*</span>}
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
                <input
                  className="input"
                  value={currentValue(f)}
                  disabled={isRejected}
                  placeholder={isRequired ? "Required" : "Not found in uploaded document"}
                  onChange={(e) => setValues((v) => ({ ...v, [f.field_name]: e.target.value }))}
                  aria-label={`Value for ${f.field_name}`}
                />
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

      <p className="text-xs text-ink-300">
        Fields shown as “not found” were not present in the readable part of your document. Koverly
        never invents values; you can type them in if you know them.
      </p>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      <div className="flex justify-end gap-3">
        <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button type="button" className="btn-primary" disabled={busy} onClick={submit}>
          {busy ? "Saving…" : "Confirm & save policy"}
        </button>
      </div>
    </div>
  );
}
