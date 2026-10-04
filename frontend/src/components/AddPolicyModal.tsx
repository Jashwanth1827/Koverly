import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { familyApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { Modal } from "@/components/Modal";
import { PolicyForm } from "@/components/PolicyForm";
import { UploadPolicyForm } from "@/components/UploadPolicyForm";

/**
 * Add-policy entry point. When the family has no policies, the user is asked
 * whether to add the policy manually or upload a policy copy for extraction.
 */
export function AddPolicyModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const { activeFamilyId } = useAuth();
  const [mode, setMode] = useState<"choose" | "manual" | "upload">("choose");
  const members = useAsync(() => familyApi.members(activeFamilyId!), [activeFamilyId]);

  const familyId = activeFamilyId!;

  return (
    <Modal
      title={
        mode === "manual"
          ? "Add policy manually"
          : mode === "upload"
            ? "Upload a policy copy"
            : "Add a policy"
      }
      onClose={onClose}
      wide={mode !== "choose"}
    >
      {mode === "choose" ? (
        <div className="space-y-4">
          <p className="text-sm text-ink-500">
            How would you like to add this policy?
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              className="card p-4 text-left transition hover:border-brand-400"
              onClick={() => setMode("manual")}
            >
              <p className="font-medium text-ink-900">Add manually</p>
              <p className="mt-1 text-sm text-ink-500">
                Enter the policy details yourself.
              </p>
            </button>
            <button
              type="button"
              className="card p-4 text-left transition hover:border-brand-400"
              onClick={() => setMode("upload")}
            >
              <p className="font-medium text-ink-900">Upload a policy copy</p>
              <p className="mt-1 text-sm text-ink-500">
                Upload a PDF or image and review what Koverly reads from it.
              </p>
            </button>
          </div>
        </div>
      ) : mode === "manual" ? (
        <PolicyForm
          familyId={familyId}
          members={members.data ?? []}
          onCancel={onClose}
          onDone={onSaved}
        />
      ) : (
        <UploadPolicyForm familyId={familyId} onCancel={onClose} onDone={onSaved} />
      )}
    </Modal>
  );
}
