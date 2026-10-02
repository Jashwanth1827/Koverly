import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { insightApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ApiError } from "@/api/client";
import { Modal } from "@/components/Modal";
import { EmptyState, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { formatDate } from "@/lib/format";

const KINDS: Record<string, string> = {
  renewal: "Renewal",
  premium: "Premium",
  policy: "Policy",
  claim: "Claim",
  document: "Document",
};

export function CalendarPage() {
  const { activeFamilyId, activeAccess } = useAuth();
  const events = useAsync(() => insightApi.calendar(activeFamilyId!), [activeFamilyId]);
  const reminders = useAsync(() => insightApi.reminders(activeFamilyId!), [activeFamilyId]);
  const [showNew, setShowNew] = useState(false);

  const canWrite = activeAccess?.role !== "viewer";
  if (!activeFamilyId) return null;

  const grouped = (events.data ?? []).reduce<Record<string, typeof events.data>>((acc, ev) => {
    const key = ev.date;
    acc[key] = acc[key] ?? [];
    acc[key]!.push(ev);
    return acc;
  }, {});

  return (
    <div>
      <PageHeader
        title="Insurance Calendar"
        description="Renewals, premiums, claims, and document dates in one timeline."
        action={canWrite ? <button className="btn-primary" onClick={() => setShowNew(true)}>New reminder</button> : undefined}
      />

      {events.loading ? (
        <Loading />
      ) : events.error ? (
        <ErrorState message={events.error} onRetry={events.reload} />
      ) : events.data!.length === 0 ? (
        <EmptyState
          title="Nothing scheduled"
          description="Renewals and reminders will appear here once your policies have dates recorded."
        />
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([date, list]) => (
            <div key={date}>
              <h2 className="mb-2 text-sm font-semibold text-ink-700">{formatDate(date)}</h2>
              <ul className="space-y-2">
                {list!.map((ev) => (
                  <li key={ev.id} className="card flex items-center justify-between gap-3 p-3">
                    <div className="flex items-center gap-3">
                      <span className="badge-neutral">{KINDS[ev.kind] ?? ev.kind}</span>
                      <span className="text-sm text-ink-900">{ev.title}</span>
                    </div>
                    {ev.status && <StatusBadge status={ev.status} />}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-500">Reminders</h2>
        {reminders.loading ? (
          <Loading />
        ) : reminders.data && reminders.data.total > 0 ? (
          <ul className="space-y-2">
            {reminders.data.items.map((r) => (
              <li key={r.id} className="card flex flex-wrap items-center justify-between gap-3 p-3">
                <div>
                  <p className="text-sm font-medium text-ink-900">{r.title}</p>
                  <p className="text-xs text-ink-500">
                    Due {formatDate(r.due_date)} · {r.offsets.map((o) => `${o}d`).join(", ")} before
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={r.status} />
                  {canWrite && r.status !== "completed" && (
                    <>
                      {r.status === "scheduled" || r.status === "triggered" || r.status === "sent" ? (
                        <button
                          className="btn-secondary px-3 py-1 text-xs"
                          onClick={async () => { await insightApi.acknowledgeReminder(activeFamilyId, r.id); reminders.reload(); }}
                        >
                          Acknowledge
                        </button>
                      ) : null}
                      <button
                        className="btn-secondary px-3 py-1 text-xs"
                        onClick={async () => { await insightApi.completeReminder(activeFamilyId, r.id); reminders.reload(); }}
                      >
                        Complete
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-500">No reminders yet.</p>
        )}
      </section>

      {showNew && (
        <NewReminderModal
          familyId={activeFamilyId}
          onClose={() => setShowNew(false)}
          onDone={() => { setShowNew(false); reminders.reload(); events.reload(); }}
        />
      )}
    </div>
  );
}

function NewReminderModal({
  familyId,
  onClose,
  onDone,
}: {
  familyId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    title: "",
    reminder_type: "renewal",
    due_date: "",
    offsets: "30,14,7,1",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const offsets = form.offsets
        .split(",")
        .map((s) => Number(s.trim()))
        .filter((n) => Number.isFinite(n));
      await insightApi.createReminder(familyId, {
        family_id: familyId,
        title: form.title,
        reminder_type: form.reminder_type,
        due_date: form.due_date,
        offsets,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the reminder.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="New reminder" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="r-title">Title</label>
          <input id="r-title" className="input" value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} required />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label" htmlFor="r-type">Type</label>
            <select id="r-type" className="input" value={form.reminder_type}
              onChange={(e) => setForm((f) => ({ ...f, reminder_type: e.target.value }))}>
              {Object.keys({ renewal: 1, premium_payment: 1, policy_expiry: 1, document_expiry: 1, claim_follow_up: 1 }).map((t) => (
                <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="r-due">Due date</label>
            <input id="r-due" type="date" className="input" value={form.due_date}
              onChange={(e) => setForm((f) => ({ ...f, due_date: e.target.value }))} required />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="r-offsets">Remind me (days before, comma-separated)</label>
          <input id="r-offsets" className="input" value={form.offsets}
            onChange={(e) => setForm((f) => ({ ...f, offsets: e.target.value }))} />
        </div>
        {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy}>{busy ? "Saving…" : "Create reminder"}</button>
        </div>
      </form>
    </Modal>
  );
}
