import { useEffect, useMemo, useRef, useState } from "react";
import { documentApi } from "@/api/endpoints";
import { errorMessage } from "@/api/client";
import { Badge, Loading } from "@/components/ui";
import type {
  AnalysisDetail,
  CandidateField,
  PolicyCandidate,
} from "@/api/types";

/**
 * Upload-and-understand flow.
 *
 * The user uploads any insurance document and never selects a category, type,
 * or field. Koverly reads the document, classifies it, and shows what it found
 * for review. A document may contain several policies; each is reviewed and
 * confirmed on its own.
 */

// Preferred display order; anything else is appended afterwards.
const FIELD_ORDER = [
  "insurer",
  "policy_number",
  "policyholder_name",
  "sum_insured",
  "premium",
  "premium_frequency",
  "start_date",
  "expiry_date",
  "renewal_date",
  "maturity_date",
  "nominee",
  "tpa",
  "waiting_period",
  "deductible",
  "claim_contact",
];

// The only fields required before a policy can be saved.
const REQUIRED = ["insurer", "policy_number"] as const;

const CATEGORY_LABELS: Record<string, string> = {
  life: "Life Insurance",
  health: "Health Insurance",
  motor: "Motor Insurance",
  property: "Property Insurance",
  travel: "Travel Insurance",
  personal_accident: "Personal Accident Insurance",
  business: "Business Insurance",
  agriculture: "Agriculture Insurance",
  marine: "Marine Insurance",
  cyber: "Cyber Insurance",
  specialty: "Specialty Insurance",
  other: "Other Insurance",
};

const CLASS_LABELS: Record<string, string> = {
  insurance_policy: "Insurance policy",
  policy_schedule: "Policy schedule",
  policy_certificate: "Policy certificate",
  renewal_document: "Renewal document",
  premium_receipt: "Premium receipt",
  claim_document: "Claim document",
  endorsement: "Endorsement",
  policy_wording: "Policy wording",
  proposal_document: "Proposal document",
  other_insurance_document: "Insurance document",
  non_insurance_document: "Not an insurance document",
  unknown: "Unrecognised document",
};

function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function orderFields(fields: CandidateField[]): CandidateField[] {
  return [...fields].sort((a, b) => {
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
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AnalysisDetail | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
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
      const created = await documentApi.upload(familyId, file);
      setDocumentId(created.id);
      poll(created.id, 0);
    } catch (err) {
      setError(errorMessage(err, "Could not upload the document."));
    } finally {
      setUploading(false);
    }
  }

  function poll(id: string, attempt: number) {
    documentApi
      .analysis(familyId, id)
      .then(async (result) => {
        // Processing is asynchronous. Wait until the analysis exists, the
        // document fails, or we time out — never claim success before data.
        if (result.analysis) {
          setDetail(result);
          return;
        }
        const latest = await documentApi.get(familyId, id);
        if (latest.status === "failed") {
          setError(
            latest.processing_error ??
              "We couldn't read this document. Please upload another copy.",
          );
          return;
        }
        if (attempt >= 20) {
          setError(
            "This is taking longer than expected. You can retry, or add the policy manually.",
          );
          return;
        }
        pollTimer.current = window.setTimeout(() => poll(id, attempt + 1), 3000);
      })
      .catch((err) => setError(errorMessage(err, "Could not read the result.")));
  }

  function reset() {
    setDetail(null);
    setDocumentId(null);
    setError(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  if (!documentId) {
    return (
      <div className="space-y-4">
        <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
          Upload any insurance document. Koverly works out what it is, which
          policy it describes, and what it covers — then shows you what it found
          so you can check it. Nothing is saved until you confirm.
        </p>
        <div>
          <label className="label" htmlFor="policy-copy">Insurance document</label>
          <input
            id="policy-copy"
            ref={fileRef}
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.rtf,.txt,application/pdf,image/*,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/rtf,text/plain"
            className="input"
            disabled={uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
            }}
          />
          <p className="mt-1 text-xs text-ink-300">
            PDF, scan, photo, Word, or text — up to 15 MB. No need to pick a type.
          </p>
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

  if (error && !detail) {
    return (
      <div className="space-y-4">
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onCancel}>Close</button>
          <button type="button" className="btn-primary" onClick={reset}>Try another file</button>
        </div>
      </div>
    );
  }

  if (!detail) {
    return (
      <Loading label="Reading your document and working out what it is…" />
    );
  }

  const analysis = detail.analysis!;

  // Not an insurance document — say so plainly, never invent a policy.
  if (!analysis.is_insurance || detail.candidate_count === 0) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm font-medium text-amber-900">
            {analysis.message ??
              "This document does not appear to be an insurance policy or document."}
          </p>
          <p className="mt-1 text-xs text-amber-800">
            Detected: {CLASS_LABELS[analysis.document_class] ?? analysis.document_class}
          </p>
        </div>
        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onCancel}>Close</button>
          <button type="button" className="btn-primary" onClick={reset}>Upload another document</button>
        </div>
      </div>
    );
  }

  const multi = detail.candidate_count > 1;

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
        <p className="font-medium">
          {multi
            ? `We found ${detail.candidate_count} insurance policies in this document.`
            : "We found your policy."}
        </p>
        <p className="mt-1 text-xs text-brand-700">
          {CLASS_LABELS[analysis.document_class] ?? analysis.document_class}
          {analysis.ocr_used ? " · read with OCR" : ""}
          {analysis.page_count ? ` · ${analysis.page_count} page(s)` : ""}
          {analysis.provider !== "null" ? ` · ${analysis.provider}` : ""}
        </p>
      </div>

      <ul className="space-y-4">
        {detail.candidates.map((candidate) => (
          <li key={candidate.id}>
            <CandidateReview
              familyId={familyId}
              documentId={documentId}
              candidate={candidate}
              onDone={onDone}
              onReviewing={setReviewing}
              reviewing={reviewing === candidate.id}
              onError={setError}
            />
          </li>
        ))}
      </ul>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      <div className="flex justify-end gap-3">
        <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function CandidateReview({
  familyId,
  documentId,
  candidate,
  onDone,
  reviewing,
  onReviewing,
  onError,
}: {
  familyId: string;
  documentId: string;
  candidate: PolicyCandidate;
  onDone: () => void;
  reviewing: boolean;
  onReviewing: (id: string | null) => void;
  onError: (message: string) => void;
}) {
  const fields = useMemo(() => orderFields(candidate.fields), [candidate.fields]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  function currentValue(f: CandidateField): string {
    return values[f.field_name] ?? f.value ?? "";
  }

  async function confirm() {
    const confirm: Record<string, string> = {};
    for (const f of fields) {
      if (rejected.has(f.field_name)) continue;
      const v = currentValue(f).trim();
      if (v) confirm[f.field_name] = v;
    }
    const missing = REQUIRED.filter((r) => !confirm[r]);
    if (missing.length > 0) {
      onError(
        `Please provide ${missing.map((m) => m.replace(/_/g, " ")).join(" and ")} before saving.`,
      );
      return;
    }
    setBusy(true);
    try {
      await documentApi.confirmCandidate(familyId, documentId, candidate.id, {
        confirm,
        reject: Array.from(rejected),
      });
      onDone();
    } catch (err) {
      onError(errorMessage(err, "Could not save the reviewed policy."));
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    setBusy(true);
    try {
      await documentApi.rejectCandidate(familyId, documentId, candidate.id);
      onDone();
    } catch (err) {
      onError(errorMessage(err, "Could not dismiss this policy."));
    } finally {
      setBusy(false);
    }
  }

  const categoryLabel = CATEGORY_LABELS[candidate.category] ?? titleCase(candidate.category);
  const typeLabel = titleCase(candidate.policy_type);
  const subtype = candidate.policy_subtype ? titleCase(candidate.policy_subtype) : null;
  const highlighted = fields.filter((f) => f.value);
  const notFound = fields.filter((f) => !f.value);

  return (
    <div className="rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-ink-900">{categoryLabel}</p>
          <p className="text-xs text-ink-500">
            {typeLabel}
            {subtype ? ` · ${subtype}` : ""}
            {candidate.page_start
              ? ` · pages ${candidate.page_start}${candidate.page_end && candidate.page_end !== candidate.page_start ? `–${candidate.page_end}` : ""}`
              : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={candidate.category_confidence >= 0.7 ? "good" : "warn"}>
            {Math.round(candidate.category_confidence * 100)}% confidence
          </Badge>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
        {highlighted.map((f) => (
          <div key={f.id} className="flex items-baseline justify-between gap-2">
            <dt className="text-xs uppercase tracking-wide text-ink-400">
              {titleCase(f.field_name)}
            </dt>
            <dd className="text-right text-sm text-ink-900">{f.value}</dd>
          </div>
        ))}
      </dl>

      {notFound.length > 0 && (
        <p className="mt-3 text-xs text-ink-300">
          Not found in the uploaded document: {notFound.map((f) => titleCase(f.field_name)).join(", ")}.
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-3">
        <button
          type="button"
          className="btn-primary"
          disabled={busy}
          onClick={confirm}
        >
          {busy ? "Saving…" : "Confirm policy"}
        </button>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => onReviewing(reviewing ? null : candidate.id)}
        >
          {reviewing ? "Hide fields" : "Review & edit"}
        </button>
        <button
          type="button"
          className="btn-secondary"
          disabled={busy}
          onClick={reject}
        >
          Dismiss
        </button>
      </div>

      {reviewing && (
        <ul className="mt-4 divide-y divide-slate-100 border-t border-slate-100 pt-2">
          {fields.map((f) => {
            const isRejected = rejected.has(f.field_name);
            const isRequired = (REQUIRED as readonly string[]).includes(f.field_name);
            return (
              <li key={f.id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="w-40 shrink-0">
                  <p className="text-sm font-medium capitalize text-ink-900">
                    {f.field_name.replace(/_/g, " ")}
                    {isRequired && <span className="ml-1 text-red-600" aria-label="required">*</span>}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {f.value ? (
                      <Badge tone={f.confidence >= 0.7 ? "good" : "warn"}>
                        {Math.round(f.confidence * 100)}%
                      </Badge>
                    ) : (
                      <Badge tone="neutral">not found</Badge>
                    )}
                    {f.source_page && (
                      <span className="text-xs text-ink-300">p.{f.source_page}</span>
                    )}
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
                  {f.source_text && (
                    <p className="mt-1 truncate text-xs text-ink-300" title={f.source_text}>
                      Source: “{f.source_text}”
                    </p>
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
      )}

      <p className="mt-3 text-xs text-ink-300">
        Koverly never invents values. Fields shown as “not found” were not present in the readable
        part of your document; you can type them in if you know them.
      </p>
    </div>
  );
}
