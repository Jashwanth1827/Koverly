import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { emergencyApi, familyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ApiError } from "@/api/client";
import { Modal } from "@/components/Modal";
import { EmptyState, ErrorState, Loading } from "@/components/ui";
import { formatCurrency, formatDate, relationshipLabel } from "@/lib/format";

export function EmergencyPage() {
  const { activeFamilyId, activeAccess } = useAuth();
  const members = useAsync(() => familyApi.members(activeFamilyId!), [activeFamilyId]);
  const [memberId, setMemberId] = useState<string | undefined>(undefined);
  const profile = useAsync(
    () => emergencyApi.profile(activeFamilyId!, memberId),
    [activeFamilyId, memberId],
  );
  const [shareOpen, setShareOpen] = useState(false);

  const canShare = activeAccess?.role !== "viewer";
  if (!activeFamilyId) return null;

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink-900">Emergency</h1>
          <p className="text-sm text-ink-500">Fast access to the cover that matters right now.</p>
        </div>
        {canShare && (
          <button className="btn-secondary" onClick={() => setShareOpen(true)}>
            Share emergency summary
          </button>
        )}
      </div>

      <div className="mb-5">
        <label className="label" htmlFor="em-member">Family member</label>
        <select
          id="em-member"
          className="input max-w-sm"
          value={memberId ?? ""}
          onChange={(e) => setMemberId(e.target.value || undefined)}
        >
          <option value="">Whole family</option>
          {members.data?.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name} ({relationshipLabel(m.relationship)})
            </option>
          ))}
        </select>
      </div>

      {profile.loading ? (
        <Loading />
      ) : profile.error ? (
        <ErrorState message={profile.error} onRetry={profile.reload} />
      ) : (
        <div className="space-y-5">
          {profile.data!.member && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4">
              <p className="text-lg font-semibold text-ink-900">{profile.data!.member.name}</p>
              <p className="text-sm text-ink-700">
                {relationshipLabel(profile.data!.member.relationship)}
                {profile.data!.member.blood_group && ` · Blood group ${profile.data!.member.blood_group}`}
              </p>
              {profile.data!.member.date_of_birth && (
                <p className="text-sm text-ink-500">Born {formatDate(profile.data!.member.date_of_birth)}</p>
              )}
            </div>
          )}

          {profile.data!.policies.length === 0 ? (
            <EmptyState
              title="No health cover recorded"
              description="Add a health, personal accident, or travel policy to make it available in an emergency."
            />
          ) : (
            <div className="space-y-4">
              {profile.data!.policies.map((p) => (
                <div key={p.policy_id} className="card p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-lg font-semibold text-ink-900">{p.insurer}</p>
                      <p className="font-mono text-base text-ink-700">{p.policy_number}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-ink-500">Sum insured</p>
                      <p className="text-lg font-semibold text-ink-900">
                        {formatCurrency(p.sum_insured)}
                      </p>
                    </div>
                  </div>
                  <dl className="mt-4 grid gap-3 sm:grid-cols-3 text-sm">
                    {p.tpa && (
                      <div>
                        <dt className="text-ink-500">TPA</dt>
                        <dd className="font-medium text-ink-900">{p.tpa}</dd>
                      </div>
                    )}
                    {p.claim_contact && (
                      <div>
                        <dt className="text-ink-500">Claim helpline</dt>
                        <dd className="font-medium text-ink-900">{p.claim_contact}</dd>
                      </div>
                    )}
                    <div>
                      <dt className="text-ink-500">Valid until</dt>
                      <dd className="font-medium text-ink-900">{formatDate(p.expiry_date)}</dd>
                    </div>
                  </dl>
                </div>
              ))}
            </div>
          )}

          {profile.data!.contacts.length > 0 && (
            <div className="card p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
                Emergency contacts
              </h2>
              <ul className="mt-3 space-y-2">
                {profile.data!.contacts.map((c, i) => (
                  <li key={i} className="flex items-center justify-between text-sm">
                    <span className="text-ink-500">{c.label}</span>
                    <a href={`tel:${c.value}`} className="font-medium text-brand-700 hover:underline">
                      {c.value}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="card p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
              What to do
            </h2>
            <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-ink-700">
              {profile.data!.claim_instructions.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </div>
        </div>
      )}

      {shareOpen && (
        <ShareModal
          familyId={activeFamilyId}
          memberId={memberId}
          onClose={() => setShareOpen(false)}
        />
      )}
    </div>
  );
}

function ShareModal({
  familyId,
  memberId,
  onClose,
}: {
  familyId: string;
  memberId?: string;
  onClose: () => void;
}) {
  const [ttl, setTtl] = useState(60);
  const [share, setShare] = useState<{ url: string; expires_at: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const res = await emergencyApi.createShare(familyId, {
        member_id: memberId,
        ttl_minutes: ttl,
      });
      setShare({ url: `${window.location.origin}/emergency/share/${res.token}`, expires_at: res.expires_at });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the share link.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Share emergency summary" onClose={onClose}>
      {share ? (
        <div className="space-y-4">
          <p className="text-sm text-ink-500">
            Anyone with this link can view the emergency summary until it expires. It does not expose
            your full account.
          </p>
          <div className="break-all rounded-lg bg-slate-50 px-3 py-2 font-mono text-xs text-ink-700">
            {share.url}
          </div>
          <p className="text-xs text-ink-500">Expires {formatDate(share.expires_at)}</p>
          <div className="flex gap-2">
            <button
              className="btn-secondary flex-1"
              onClick={() => navigator.clipboard?.writeText(share.url)}
            >
              Copy link
            </button>
            <button className="btn-primary flex-1" onClick={onClose}>Done</button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-ink-500">
            Create a temporary, scoped link to the emergency summary. Only the emergency view is
            exposed — never your documents or full policy vault.
          </p>
          <div>
            <label className="label" htmlFor="s-ttl">Valid for (minutes)</label>
            <input
              id="s-ttl"
              type="number"
              min={5}
              max={1440}
              className="input"
              value={ttl}
              onChange={(e) => setTtl(Number(e.target.value))}
            />
          </div>
          {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          <div className="flex justify-end gap-3">
            <button className="btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn-primary" disabled={busy} onClick={create}>
              {busy ? "Creating…" : "Create link"}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
