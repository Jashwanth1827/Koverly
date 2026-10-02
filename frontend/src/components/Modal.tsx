import { useState, type ReactNode } from "react";

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink-900/40 p-0 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className={`max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl ${
          wide ? "sm:max-w-2xl" : "sm:max-w-lg"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ink-900">{title}</h2>
          <button className="btn-ghost px-2 py-1" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConfirmButton({
  onConfirm,
  children,
  className = "btn-danger",
  confirmLabel = "Confirm",
}: {
  onConfirm: () => void;
  children: ReactNode;
  className?: string;
  confirmLabel?: string;
}) {
  const [armed, setArmed] = useState(false);
  if (armed) {
    return (
      <span className="inline-flex gap-2">
        <button className="btn-danger" onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button className="btn-ghost" onClick={() => setArmed(false)}>
          Cancel
        </button>
      </span>
    );
  }
  return (
    <button className={className} onClick={() => setArmed(true)}>
      {children}
    </button>
  );
}

/** Irreversible action confirmation requiring the user to type a keyword. */
export function DangerConfirmModal({
  title,
  confirmWord = "DELETE",
  warning,
  description,
  confirmLabel = "Delete permanently",
  onConfirm,
  onClose,
}: {
  title: string;
  confirmWord?: string;
  warning: string;
  description?: ReactNode;
  confirmLabel?: string;
  onConfirm: () => Promise<void> | void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const matches = typed.trim() === confirmWord;

  async function confirm() {
    if (!matches) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch {
      setError("The action could not be completed. Please try again.");
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={busy ? () => {} : onClose}>
      <div className="space-y-4">
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-3">
          <p className="text-sm font-medium text-red-800">{warning}</p>
          {description && <div className="mt-1 text-sm text-red-700">{description}</div>}
        </div>

        <div>
          <label className="label" htmlFor="danger-confirm">
            Type <span className="font-mono font-semibold">{confirmWord}</span> to confirm
          </label>
          <input
            id="danger-confirm"
            className="input"
            value={typed}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={confirmWord}
            disabled={busy}
          />
        </div>

        {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        <div className="flex justify-end gap-3">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-danger"
            disabled={!matches || busy}
            onClick={confirm}
          >
            {busy ? "Deleting…" : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
