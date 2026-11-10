import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { familyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { ApiError, errorMessage } from "@/api/client";
import { ConfirmButton, Modal } from "@/components/Modal";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "@/components/ui";
import { RELATIONSHIP_LABELS, formatDate, initials, relationshipLabel } from "@/lib/format";
import type { FamilyMember } from "@/api/types";

const ROLES = ["admin", "member", "viewer"];

export function FamilyPage() {
  const { activeFamilyId, activeAccess, user } = useAuth();
  const members = useAsync(() => familyApi.members(activeFamilyId!), [activeFamilyId]);
  const [showAdd, setShowAdd] = useState(false);
  const [inviteFor, setInviteFor] = useState<FamilyMember | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canManage = activeAccess?.role === "admin" || activeAccess?.role === "owner";
  if (!activeFamilyId) return null;

  return (
    <div>
      <PageHeader
        title="Family"
        description="The people whose insurance you manage."
        action={canManage ? <button className="btn-primary" onClick={() => setShowAdd(true)}>Add member</button> : undefined}
      />

      {members.loading ? (
        <Loading />
      ) : members.error ? (
        <ErrorState message={members.error} onRetry={members.reload} />
      ) : members.data!.length === 0 ? (
        <EmptyState title="No family members" description="Add the people you manage insurance for." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {members.data!.map((m) => (
            <div key={m.id} className="card p-5">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-50 text-sm font-semibold text-brand-700">
                  {initials(m.name)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-ink-900">{m.name}</p>
                  <p className="text-sm text-ink-500">{relationshipLabel(m.relationship)}</p>
                </div>
                <Badge tone={m.role === "owner" ? "good" : "neutral"}>{m.role}</Badge>
              </div>

              <dl className="mt-4 space-y-1 text-sm text-ink-700">
                {m.date_of_birth && <div>Born {formatDate(m.date_of_birth)}</div>}
                {m.blood_group && <div>Blood group {m.blood_group}</div>}
                {m.phone && <div>{m.phone}</div>}
                {m.email && <div className="truncate">{m.email}</div>}
              </dl>

              {canManage && m.role !== "owner" && (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {!m.is_account_linked && !m.user_id && (
                    <button className="btn-secondary px-3 py-1 text-xs" onClick={() => setInviteFor(m)}>
                      Invite
                    </button>
                  )}
                  {m.user_id && (
                    <select
                      className="input max-w-[110px] py-1 text-xs"
                      value={m.role}
                      aria-label={`Role for ${m.name}`}
                      onChange={async (e) => {
                        try {
                          await familyApi.changeRole(activeFamilyId, m.id, e.target.value);
                          members.reload();
                        } catch (err) {
                          setError(errorMessage(err, "Could not change role."));
                        }
                      }}
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  )}
                  <ConfirmButton
                    className="btn-ghost px-2 py-1 text-xs"
                    confirmLabel="Remove"
                    onConfirm={async () => {
                      await familyApi.removeMember(activeFamilyId, m.id);
                      members.reload();
                    }}
                  >
                    Remove
                  </ConfirmButton>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {showAdd && (
        <AddMemberModal
          familyId={activeFamilyId}
          onClose={() => setShowAdd(false)}
          onDone={() => { setShowAdd(false); members.reload(); }}
        />
      )}
      {inviteFor && (
        <InviteModal
          familyId={activeFamilyId}
          member={inviteFor}
          defaultEmail={inviteFor.email ?? user?.email ?? ""}
          onClose={() => setInviteFor(null)}
          onDone={() => { setInviteFor(null); members.reload(); }}
        />
      )}
    </div>
  );
}

function AddMemberModal({
  familyId,
  onClose,
  onDone,
}: {
  familyId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    name: "",
    relationship: "father",
    date_of_birth: "",
    blood_group: "",
    phone: "",
    email: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await familyApi.addMember(familyId, {
        name: form.name.trim(),
        relationship: form.relationship,
        date_of_birth: form.date_of_birth || null,
        blood_group: form.blood_group || null,
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
      } as Partial<FamilyMember>);
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Could not add the member."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Add family member" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="m-name">Name</label>
          <input id="m-name" className="input" value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
        </div>
        <div>
          <label className="label" htmlFor="m-rel">Relationship</label>
          <select id="m-rel" className="input" value={form.relationship}
            onChange={(e) => setForm((f) => ({ ...f, relationship: e.target.value }))}>
            {Object.entries(RELATIONSHIP_LABELS).filter(([v]) => v !== "self").map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label" htmlFor="m-dob">Date of birth</label>
            <input id="m-dob" type="date" className="input" value={form.date_of_birth}
              onChange={(e) => setForm((f) => ({ ...f, date_of_birth: e.target.value }))} />
          </div>
          <div>
            <label className="label" htmlFor="m-blood">Blood group</label>
            <input id="m-blood" className="input" list="blood-groups" placeholder="e.g. O+"
              value={form.blood_group}
              onChange={(e) => setForm((f) => ({ ...f, blood_group: e.target.value }))} />
            <datalist id="blood-groups">
              {["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"].map((bg) => (
                <option key={bg} value={bg} />
              ))}
            </datalist>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label" htmlFor="m-phone">Phone</label>
            <input id="m-phone" className="input" value={form.phone}
              onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))} />
          </div>
          <div>
            <label className="label" htmlFor="m-email">Email</label>
            <input id="m-email" type="email" className="input" value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
          </div>
        </div>
        {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy}>{busy ? "Adding…" : "Add member"}</button>
        </div>
      </form>
    </Modal>
  );
}

function InviteModal({
  familyId,
  member,
  defaultEmail,
  onClose,
  onDone,
}: {
  familyId: string;
  member: FamilyMember;
  defaultEmail: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [email, setEmail] = useState(defaultEmail);
  const [role, setRole] = useState("member");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await familyApi.invite(familyId, email, role, member.id);
      onDone();
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "USER_NOT_FOUND"
          ? "No Koverly account uses that email yet. Ask them to sign up first."
          : errorMessage(err, "Could not send the invite."),
      );
    }
  }

  return (
    <Modal title={`Invite ${member.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-ink-500">
          Link an existing Koverly account to this family member and grant them access.
        </p>
        <div>
          <label className="label" htmlFor="i-email">Email</label>
          <input id="i-email" type="email" className="input" value={email}
            onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div>
          <label className="label" htmlFor="i-role">Role</label>
          <select id="i-role" className="input" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary">Send invite</button>
        </div>
      </form>
    </Modal>
  );
}
