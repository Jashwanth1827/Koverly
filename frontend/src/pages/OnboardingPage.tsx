import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { documentApi, familyApi } from "@/api/endpoints";
import { ApiError, errorMessage } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { StatusBadge } from "@/components/ui";
import { AppFooter } from "@/components/Footer";
import { useToast } from "@/components/Toast";
import { usePageMeta } from "@/lib/pageMeta";
import { ACCEPTED_FORMATS_LABEL, ACCEPTED_UPLOAD_TYPES } from "@/lib/format";
import type { Document, Extraction } from "@/api/types";

const STEPS = ["Create family", "Upload documents"];

export function OnboardingPage() {
  const { refreshFamilies, setActiveFamily, logout } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [familyName, setFamilyName] = useState("");
  const [familyId, setFamilyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  usePageMeta("Set up your family", "Create your family group and start recording your insurance.");

  async function createFamily(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const family = await familyApi.create(familyName);
      setFamilyId(family.id);
      await refreshFamilies();
      setActiveFamily(family.id);
      toast.success("Family created.");
      setStep(1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the family.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-full max-w-xl flex-col justify-center px-4 py-12">
      <ol className="mb-8 flex items-center gap-2 text-xs font-medium text-ink-500">
        {STEPS.map((label, i) => (
          <li key={label} className="flex items-center gap-2">
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full ${
                i <= step ? "bg-brand-600 text-white" : "bg-slate-200 text-ink-500"
              }`}
            >
              {i + 1}
            </span>
            <span className={i <= step ? "text-ink-900" : ""}>{label}</span>
            {i < STEPS.length - 1 && <span aria-hidden>—</span>}
          </li>
        ))}
      </ol>

      <div className="card p-6">
        {step === 0 && (
          <form onSubmit={createFamily} className="space-y-4">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Create your family</h1>
              <p className="mt-1 text-sm text-ink-500">
                Policies, claims, and documents all belong to a family group. You can add more
                families later.
              </p>
            </div>
            <div>
              <label className="label" htmlFor="family-name">
                Family name
              </label>
              <input
                id="family-name"
                className="input"
                value={familyName}
                onChange={(e) => setFamilyName(e.target.value)}
                required
              />
            </div>
            {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            <button className="btn-primary w-full" disabled={busy}>
              {busy ? "Creating…" : "Create family"}
            </button>
          </form>
        )}

        {step === 1 && familyId && (
          <OnboardingUpload familyId={familyId} onFinish={() => navigate("/", { replace: true })} />
        )}
      </div>

      <div className="mt-6 flex items-center justify-between text-xs text-ink-300">
        <span>Koverly is not an insurer or financial adviser.</span>
        <button className="hover:text-ink-700" onClick={logout}>
          Sign out
        </button>
      </div>
      <AppFooter />
    </div>
  );
}

function OnboardingUpload({
  familyId,
  onFinish,
}: {
  familyId: string;
  onFinish: () => void;
}) {
  const [docs, setDocs] = useState<Document[]>([]);
  const [uploading, setUploading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [readyDoc, setReadyDoc] = useState<Document | null>(null);
  const [extractions, setExtractions] = useState<Extraction[]>([]);
  const [applied, setApplied] = useState(false);
  const toast = useToast();

  async function refresh(): Promise<Document[]> {
    try {
      const page = await documentApi.list(familyId, { page_size: 100 });
      setDocs(page.items);
      return page.items;
    } catch {
      return [];
    }
  }

  async function waitForProcessing(documentId: string): Promise<Document | null> {
    // Processing runs in the background. Poll until it reaches a final state.
    for (let attempt = 0; attempt < 15; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      const items = await refresh();
      const doc = items.find((d) => d.id === documentId) ?? null;
      if (!doc || doc.status === "processed" || doc.status === "failed") return doc;
    }
    return null;
  }

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    setReadyDoc(null);
    setExtractions([]);
    setApplied(false);
    try {
      const created = await documentApi.upload(familyId, file);
      toast.success("Document uploaded. Reading its details now…");
      const done = await waitForProcessing(created.id);
      if (!done) {
        setError("Still processing. Check the Documents page in a moment.");
        return;
      }
      if (done.status === "failed") {
        setError(
          done.processing_error ||
            "This document could not be read. You can add the policy manually.",
        );
        return;
      }
      setExtractions(await documentApi.extractions(familyId, created.id));
      setReadyDoc(done);
    } catch (err) {
      setError(errorMessage(err, "Could not upload the document."));
    } finally {
      setUploading(false);
    }
  }

  const found = extractions.filter((e) => e.found && e.value);

  async function applyExtractedDetails() {
    if (!readyDoc) return;
    setApplying(true);
    setError(null);
    try {
      await documentApi.confirm(familyId, readyDoc.id, {
        confirm: Object.fromEntries(found.map((e) => [e.field_name, e.value!])),
        reject: [],
        create_policy: true,
      });
      setApplied(true);
      toast.success("Policy created from the extracted details.");
    } catch (err) {
      setError(errorMessage(err, "Could not create the policy from these details."));
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Upload insurance documents</h1>
        <p className="mt-1 text-sm text-ink-500">
          Upload a policy document or a photo — PDF, images, Word, Excel, CSV, Markdown, or plain
          text. Koverly reads the key details and lets you create the policy from them.
        </p>
      </div>

      <label className="btn-primary w-full cursor-pointer text-center">
        {uploading ? "Reading document…" : "Choose a file to upload"}
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

      {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {docs.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {docs.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 truncate text-ink-900">{d.original_filename}</span>
              <StatusBadge status={d.status} />
            </li>
          ))}
        </ul>
      )}

      {readyDoc && !applied && (
        <div className="rounded-lg border border-brand-200 bg-brand-50 p-3">
          <p className="text-sm font-medium text-brand-900">
            {found.length ? `${found.length} details found` : "No details could be read"}
          </p>
          {found.length > 0 ? (
            <>
              <ul className="mt-2 grid gap-1 text-xs text-brand-800 sm:grid-cols-2">
                {found.map((e) => (
                  <li key={e.id}>
                    <span className="font-medium">{e.field_name.replace(/_/g, " ")}:</span>{" "}
                    {e.value}
                  </li>
                ))}
              </ul>
              <button className="btn-primary mt-3 w-full" disabled={applying} onClick={applyExtractedDetails}>
                {applying ? "Creating policy…" : "Create policy from these details"}
              </button>
            </>
          ) : (
            <p className="mt-1 text-xs text-brand-800">
              You can still add the policy manually from the Policies page.
            </p>
          )}
        </div>
      )}

      {applied && (
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          Policy created. You can review it on the dashboard.
        </p>
      )}

      <p className="text-xs text-ink-300">
        Accepted formats: {ACCEPTED_FORMATS_LABEL}. Files are stored privately.
      </p>

      <div className="flex gap-3">
        <button className="btn-secondary flex-1" onClick={onFinish}>
          Skip for now
        </button>
        <button className="btn-primary flex-1" onClick={onFinish}>
          Go to dashboard
        </button>
      </div>
    </div>
  );
}
