import { useState } from "react";
import { policyApi } from "@/api/endpoints";
import { ApiError } from "@/api/client";
import { POLICY_TYPE_LABELS } from "@/lib/format";
import type { FamilyMember, PolicyType } from "@/api/types";

const FREQUENCIES = ["monthly", "quarterly", "half_yearly", "yearly", "single"];

export function PolicyForm({
  familyId,
  members,
  onDone,
  onCancel,
}: {
  familyId: string;
  members: FamilyMember[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({
    policy_type: "health" as PolicyType,
    insurer: "",
    policy_number: "",
    member_id: "",
    sum_insured: "",
    premium: "",
    premium_frequency: "yearly",
    start_date: "",
    expiry_date: "",
    renewal_date: "",
    nominee: "",
    notes: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function set<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await policyApi.create(familyId, {
        family_id: familyId,
        policy_type: form.policy_type,
        insurer: form.insurer,
        policy_number: form.policy_number,
        member_id: form.member_id || null,
        sum_insured: form.sum_insured || null,
        premium: form.premium || null,
        premium_frequency: form.premium ? form.premium_frequency : null,
        start_date: form.start_date || null,
        expiry_date: form.expiry_date || null,
        renewal_date: form.renewal_date || null,
        nominee: form.nominee || null,
        notes: form.notes || null,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the policy.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="policy_type">Policy type</label>
          <select
            id="policy_type"
            className="input"
            value={form.policy_type}
            onChange={(e) => set("policy_type", e.target.value as PolicyType)}
          >
            {Object.entries(POLICY_TYPE_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="member_id">Covered member</label>
          <select
            id="member_id"
            className="input"
            value={form.member_id}
            onChange={(e) => set("member_id", e.target.value)}
          >
            <option value="">Not specified</option>
            {members.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="insurer">Insurer</label>
          <input id="insurer" className="input" value={form.insurer}
            onChange={(e) => set("insurer", e.target.value)} required />
        </div>
        <div>
          <label className="label" htmlFor="policy_number">Policy number</label>
          <input id="policy_number" className="input" value={form.policy_number}
            onChange={(e) => set("policy_number", e.target.value)} required />
        </div>
        <div>
          <label className="label" htmlFor="sum_insured">Sum insured</label>
          <input id="sum_insured" className="input" inputMode="decimal" value={form.sum_insured}
            onChange={(e) => set("sum_insured", e.target.value)} placeholder="500000" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="label" htmlFor="premium">Premium</label>
            <input id="premium" className="input" inputMode="decimal" value={form.premium}
              onChange={(e) => set("premium", e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="premium_frequency">Frequency</label>
            <select id="premium_frequency" className="input" value={form.premium_frequency}
              onChange={(e) => set("premium_frequency", e.target.value)}>
              {FREQUENCIES.map((f) => (
                <option key={f} value={f}>{f.replace("_", " ")}</option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className="label" htmlFor="start_date">Start date</label>
          <input id="start_date" type="date" className="input" value={form.start_date}
            onChange={(e) => set("start_date", e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="expiry_date">Expiry date</label>
          <input id="expiry_date" type="date" className="input" value={form.expiry_date}
            onChange={(e) => set("expiry_date", e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="renewal_date">Renewal date</label>
          <input id="renewal_date" type="date" className="input" value={form.renewal_date}
            onChange={(e) => set("renewal_date", e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="nominee">Nominee</label>
          <input id="nominee" className="input" value={form.nominee}
            onChange={(e) => set("nominee", e.target.value)} />
        </div>
      </div>
      <div>
        <label className="label" htmlFor="notes">Notes</label>
        <textarea id="notes" className="input" rows={2} value={form.notes}
          onChange={(e) => set("notes", e.target.value)} />
      </div>
      {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <div className="flex justify-end gap-3">
        <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button className="btn-primary" disabled={busy}>{busy ? "Saving…" : "Save policy"}</button>
      </div>
    </form>
  );
}
