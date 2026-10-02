import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { configApi, familyApi, insightApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ApiError } from "@/api/client";
import { DangerConfirmModal } from "@/components/Modal";
import { Disclaimer, ErrorState, Loading, PageHeader } from "@/components/ui";
import { formatDate } from "@/lib/format";
import type { Family } from "@/api/types";

export function SettingsPage() {
  const { activeFamilyId, activeAccess, user, families, refreshFamilies } = useAuth();
  const config = useAsync(() => configApi.get(), []);
  const subscription = useAsync(
    () => (activeFamilyId ? insightApi.subscription(activeFamilyId) : Promise.resolve(null)),
    [activeFamilyId],
  );
  const audit = useAsync(
    () => (activeFamilyId ? insightApi.auditLogs(activeFamilyId) : Promise.resolve(null)),
    [activeFamilyId],
  );
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Family | null>(null);

  const isAdmin = activeAccess?.role === "admin" || activeAccess?.role === "owner";

  async function deleteFamily(family: Family) {
    await familyApi.remove(family.id);
    setDeleteTarget(null);
    await refreshFamilies();
  }

  return (
    <div>
      <PageHeader title="Settings" description="Your account, family, plan, and activity." />

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">Account</h2>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-ink-500">Name</dt>
              <dd className="text-ink-900">{user?.full_name}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-500">Email</dt>
              <dd className="text-ink-900">{user?.email}</dd>
            </div>
          </dl>
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">Families</h2>
          <ul className="mt-3 space-y-2 text-sm">
            {families.map((f) => (
              <li key={f.id} className="flex items-center justify-between gap-3">
                <span className="min-w-0 truncate text-ink-900">{f.name}</span>
                <span className="flex shrink-0 items-center gap-2">
                  {f.id === activeFamilyId && <span className="badge-good">active</span>}
                  {user && f.owner_user_id === user.id && (
                    <button
                      className="btn-ghost px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                      onClick={() => setDeleteTarget(f)}
                    >
                      Delete
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <button
            className="btn-secondary mt-4"
            onClick={async () => {
              const name = window.prompt("New family name");
              if (!name) return;
              try {
                await familyApi.create(name);
                await refreshFamilies();
              } catch (err) {
                setError(err instanceof ApiError ? err.message : "Could not create the family.");
              }
            }}
          >
            Create another family
          </button>
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">Plan</h2>
          {subscription.loading ? (
            <Loading />
          ) : subscription.data ? (
            <>
              <p className="mt-3 text-lg font-semibold capitalize text-ink-900">
                {subscription.data.plan.replace(/_/g, " ")}
              </p>
              <p className="text-sm text-ink-500">Status: {subscription.data.status}</p>
              {isAdmin && (
                <div className="mt-4 flex gap-2">
                  {(["free", "pro", "family_pro"] as const).map((plan) => (
                    <button
                      key={plan}
                      className="btn-secondary capitalize"
                      disabled={plan === subscription.data!.plan}
                      onClick={async () => {
                        try {
                          await insightApi.setSubscription(activeFamilyId!, plan);
                          subscription.reload();
                        } catch (err) {
                          setError(err instanceof ApiError ? err.message : "Could not change the plan.");
                        }
                      }}
                    >
                      {plan.replace(/_/g, " ")}
                    </button>
                  ))}
                </div>
              )}
              <Disclaimer>
                Billing is not connected. Changing the plan only records your preference and does not
                process a payment.
              </Disclaimer>
            </>
          ) : null}
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            System status
          </h2>
          {config.loading ? (
            <Loading />
          ) : config.error ? (
            <ErrorState message={config.error} onRetry={config.reload} />
          ) : (
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-500">AI provider</dt>
                <dd className="text-ink-900">{config.data!.ai_provider}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-500">Notifications</dt>
                <dd className="text-ink-900">{config.data!.notification_backend}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-500">Storage</dt>
                <dd className="text-ink-900">{config.data!.storage_backend}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-500">Max upload</dt>
                <dd className="text-ink-900">{config.data!.max_upload_mb} MB</dd>
              </div>
            </dl>
          )}
          {config.data?.ai_provider === "null" && (
            <Disclaimer>
              The deterministic local AI provider is active. It extracts text and answers from your
              records without calling an external model, and never invents missing values. Set
              AI_PROVIDER and an API key to enable an external model.
            </Disclaimer>
          )}
        </section>

        {isAdmin && (
          <section className="card p-5 lg:col-span-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
              Recent activity
            </h2>
            {audit.loading ? (
              <Loading />
            ) : audit.data && audit.data.total > 0 ? (
              <ul className="mt-3 divide-y divide-slate-100">
                {audit.data.items.slice(0, 20).map((a) => (
                  <li key={a.id} className="flex items-center justify-between py-2 text-sm">
                    <span className="text-ink-900">{a.action.replace(/_/g, " ")}</span>
                    <span className="text-xs text-ink-500">{formatDate(a.created_at)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-ink-500">No activity recorded.</p>
            )}
          </section>
        )}
      </div>

      {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <Disclaimer>
        Koverly is an organizational and informational tool. It is not an insurer, lawyer, doctor, or
        financial adviser, and does not guarantee any claim outcome.
      </Disclaimer>

      {deleteTarget && (
        <DangerConfirmModal
          title={`Delete “${deleteTarget.name}”?`}
          warning="This permanently deletes the family and all of its data. This cannot be undone."
          description="All policies, family members, documents, claims, reminders, and emergency shares in this family will be lost. Stored files are removed from private storage."
          confirmLabel="Delete family permanently"
          onConfirm={() => deleteFamily(deleteTarget)}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
