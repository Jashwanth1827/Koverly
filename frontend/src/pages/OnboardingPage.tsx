import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { documentApi, familyApi } from "@/api/endpoints";
import { ApiError } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { StatusBadge } from "@/components/ui";
import type { Document } from "@/api/types";

const STEPS = ["Create family", "Add members", "Upload documents"];

export function OnboardingPage() {
  const { refreshFamilies, setActiveFamily, logout } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [familyName, setFamilyName] = useState("");
  const [familyId, setFamilyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function createFamily(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const family = await familyApi.create(familyName);
      setFamilyId(family.id);
      await refreshFamilies();
      setActiveFamily(family.id);
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
                placeholder="e.g. The Sharmas"
                required
              />
            </div>
            {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            <button className="btn-primary w-full" disabled={busy}>
              {busy ? "Creating…" : "Create family"}
            </button>
          </form>
        )}

        {step === 1 && familyId && (
          <div className="space-y-4">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Add family members</h1>
              <p className="mt-1 text-sm text-ink-500">
                Add the people you manage insurance for. You can do this now or later.
              </p>
            </div>
            <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
              Your own member profile was created automatically.
            </p>
            <div className="flex gap-3">
              <button className="btn-secondary flex-1" onClick={() => navigate("/family")}>
                Add members
              </button>
              <button className="btn-primary flex-1" onClick={() => setStep(2)}>
                Continue
              </button>
            </div>
          </div>
        )}

        {step === 2 && familyId && (
          <OnboardingUpload familyId={familyId} onFinish={() => navigate("/", { replace: true })} />
        )}
      </div>

      <div className="mt-6 flex items-center justify-between text-xs text-ink-300">
        <span>Koverly is not an insurer or financial adviser.</span>
        <button className="hover:text-ink-700" onClick={logout}>
          Sign out
        </button>
      </div>
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
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const page = await documentApi.list(familyId, { page_size: 100 });
      setDocs(page.items);
    } catch {
      /* non-fatal — the user can review documents later */
    }
  }

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    try {
      await documentApi.upload(familyId, file);
      // Processing is asynchronous; poll briefly so the status becomes visible.
      setTimeout(refresh, 800);
      setTimeout(refresh, 2500);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not upload the document.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Upload insurance documents</h1>
        <p className="mt-1 text-sm text-ink-500">
          Upload a policy PDF or a photo. Koverly extracts the key details for you to review before
          anything is applied to a policy.
        </p>
      </div>

      <label className="btn-primary w-full cursor-pointer text-center">
        {uploading ? "Uploading…" : "Choose a file to upload"}
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

      <p className="text-xs text-ink-300">
        Accepted formats: PDF, JPG, PNG. Files are stored privately.
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
