import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { approveCustomer, rejectCustomer } from "../../api/customers.api";
import { queryKeys } from "../../api/query-keys";
import { ConfirmationDialog } from "../../components/feedback/Dialogs";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Textarea } from "../../components/forms/Field";

export type KycDecisionTarget = {
  merchantId: string;
  customerId: string;
  name: string;
  decision: "approve" | "reject";
};

const REASONS = [
  "Document images are unclear or unreadable",
  "Document number does not match the uploaded file",
  "Name on the documents does not match the registration",
  "Required document is missing"
];

/**
 * Approve or reject a pending registration. The backend locks the row, so a second decision
 * (or one racing a colleague's) comes back as a 409 and is shown in the dialog.
 */
export function KycDecisionDialogs({ target, onClose }: { target: KycDecisionTarget | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.customerKyc.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.customers.all });
  }

  function close() {
    setReason("");
    onClose();
  }

  return (
    <>
      <ConfirmationDialog
        open={target?.decision === "approve"}
        title={`Approve ${target?.name ?? "this customer"}?`}
        description="Their KYC is marked verified and they can start placing orders."
        confirmLabel="Approve"
        confirmVariant="primary"
        onClose={close}
        onConfirm={async () => {
          if (!target) return;
          await approveCustomer(target.merchantId, target.customerId);
          toast.success(`${target.name} approved.`);
          refresh();
        }}
      />
      <ConfirmationDialog
        open={target?.decision === "reject"}
        title={`Reject ${target?.name ?? "this registration"}?`}
        description="The customer is shown the reason and can correct their details and resubmit."
        confirmLabel="Reject"
        confirmDisabled={reason.trim().length < 3}
        onClose={close}
        onConfirm={async () => {
          if (!target) return;
          await rejectCustomer(target.merchantId, target.customerId, reason.trim());
          toast.success(`${target.name} rejected.`);
          setReason("");
          refresh();
        }}
      >
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          {REASONS.map((text) => (
            <button key={text} type="button" className="badge badge--neutral" style={{ cursor: "pointer" }} onClick={() => setReason(text)}>
              {text}
            </button>
          ))}
        </div>
        <Field label="Reason" required hint="At least 3 characters. The customer sees this.">
          <Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} maxLength={500} autoFocus />
        </Field>
      </ConfirmationDialog>
    </>
  );
}
