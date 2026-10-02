import { useParams } from "react-router-dom";
import { emergencyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ErrorState, Loading } from "@/components/ui";
import { formatCurrency, formatDate } from "@/lib/format";

export function EmergencySharePage() {
  const { token } = useParams();
  const profile = useAsync(() => emergencyApi.resolve(token!), [token]);

  return (
    <div className="mx-auto min-h-full max-w-2xl px-4 py-8">
      <div className="mb-6 flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-600 text-sm font-bold text-white">
          !
        </span>
        <div>
          <h1 className="text-xl font-bold tracking-tight">Emergency insurance summary</h1>
          <p className="text-sm text-ink-500">Shared via a temporary Koverly link.</p>
        </div>
      </div>

      {profile.loading ? (
        <Loading />
      ) : profile.error ? (
        <ErrorState
          message="This emergency link is invalid, expired, or has reached its view limit."
        />
      ) : (
        <div className="space-y-4">
          <p className="rounded-lg bg-slate-100 px-3 py-2 text-sm text-ink-700">
            {profile.data!.family_name}
            {profile.data!.member ? ` · ${profile.data!.member.name}` : ""}
          </p>

          {profile.data!.policies.map((p) => (
            <div key={p.policy_id} className="card p-5">
              <p className="text-lg font-semibold text-ink-900">{p.insurer}</p>
              <p className="font-mono text-base text-ink-700">{p.policy_number}</p>
              <dl className="mt-3 grid gap-3 sm:grid-cols-2 text-sm">
                <div>
                  <dt className="text-ink-500">Sum insured</dt>
                  <dd className="font-medium">{formatCurrency(p.sum_insured)}</dd>
                </div>
                {p.tpa && (
                  <div>
                    <dt className="text-ink-500">TPA</dt>
                    <dd className="font-medium">{p.tpa}</dd>
                  </div>
                )}
                {p.claim_contact && (
                  <div>
                    <dt className="text-ink-500">Claim helpline</dt>
                    <dd className="font-medium">{p.claim_contact}</dd>
                  </div>
                )}
                <div>
                  <dt className="text-ink-500">Valid until</dt>
                  <dd className="font-medium">{formatDate(p.expiry_date)}</dd>
                </div>
              </dl>
            </div>
          ))}

          {profile.data!.contacts.length > 0 && (
            <div className="card p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">Contacts</h2>
              <ul className="mt-3 space-y-2 text-sm">
                {profile.data!.contacts.map((c, i) => (
                  <li key={i} className="flex justify-between">
                    <span className="text-ink-500">{c.label}</span>
                    <a href={`tel:${c.value}`} className="font-medium text-brand-700">{c.value}</a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="card p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">What to do</h2>
            <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-ink-700">
              {profile.data!.claim_instructions.map((s, i) => <li key={i}>{s}</li>)}
            </ol>
          </div>

          <p className="text-center text-xs text-ink-300">
            This is an informational summary, not an insurer's confirmation of cover.
          </p>
        </div>
      )}
    </div>
  );
}
