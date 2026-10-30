import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { normalizeError } from "../../api/errors";
import {
  createCustomerType,
  createCylinderType,
  createKycDocumentType,
  updateCustomerType,
  updateCylinderType,
  updateKycDocumentType,
  type CustomerType,
  type CylinderType,
  type KycDocumentType
} from "../../api/catalogue.api";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";

/**
 * A catalogue code is the identity every order, invoice and stock row already carries, so it is
 * typed once on creation and read-only afterwards. Changing it would orphan that history.
 */
const CODE_HINT = "1-40 uppercase letters, numbers or underscores. Cannot be changed later.";

function normaliseCode(value: string) {
  return value.toUpperCase().replace(/[^A-Z0-9_]/g, "");
}

function codeError(value: string): string | undefined {
  if (!value.trim()) return "A code is required.";
  if (value.length > 40) return "Use at most 40 characters.";
  return undefined;
}

/** Numbers come back from the API as numbers but are edited as text, so empty means "unset". */
function num(value: string, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  const normalised = normalizeError(error);
  const field = normalised.fieldErrors ? Object.values(normalised.fieldErrors)[0] : undefined;
  return <Alert tone="error">{field || normalised.userMessage}</Alert>;
}

// --- Cylinder type ------------------------------------------------------------------------------

export function CylinderTypeDialog({
  item,
  onClose,
  onSaved
}: {
  item: CylinderType | "new" | null;
  onClose: () => void;
  onSaved: (saved: CylinderType, created: boolean) => void;
}) {
  const existing = item && item !== "new" ? item : null;
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [shortLabel, setShortLabel] = useState("");
  const [weightKg, setWeightKg] = useState("");
  const [variant, setVariant] = useState("");
  const [hsnSac, setHsnSac] = useState("");
  const [unit, setUnit] = useState("PCS");
  const [baseRate, setBaseRate] = useState("0");
  const [markup, setMarkup] = useState("0");
  const [gst, setGst] = useState("18");
  const [reorder, setReorder] = useState("0");
  const [sortOrder, setSortOrder] = useState("0");
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (item === null) return;
    setSubmitted(false);
    setCode(existing?.code ?? "");
    setLabel(existing?.label ?? "");
    setShortLabel(existing?.shortLabel ?? "");
    setWeightKg(existing ? String(existing.weightKg) : "");
    setVariant(existing?.variant ?? "");
    setHsnSac(existing?.hsnSac ?? "");
    setUnit(existing?.unit ?? "PCS");
    setBaseRate(existing ? String(existing.defaultBaseRate) : "0");
    setMarkup(existing ? String(existing.defaultMarkup) : "0");
    setGst(existing ? String(existing.gstPercent) : "18");
    setReorder(existing ? String(existing.reorderThreshold) : "0");
    setSortOrder(existing ? String(existing.sortOrder) : "0");
  }, [item, existing]);

  const mutation = useMutation({
    mutationFn: async () => {
      const body = {
        label: label.trim(),
        shortLabel: shortLabel.trim() || null,
        weightKg: num(weightKg),
        variant: variant.trim() || null,
        hsnSac: hsnSac.trim() || null,
        unit: unit.trim() || "PCS",
        defaultBaseRate: num(baseRate),
        defaultMarkup: num(markup),
        gstPercent: num(gst, 18),
        reorderThreshold: num(reorder),
        sortOrder: num(sortOrder)
      };
      return existing ? updateCylinderType(existing.code, body) : createCylinderType({ ...body, code: code.trim() });
    },
    onSuccess: (saved) => {
      onSaved(saved, !existing);
      onClose();
    }
  });

  function submit() {
    setSubmitted(true);
    if (!existing && codeError(code)) return;
    if (!label.trim() || num(weightKg) <= 0) return;
    mutation.mutate();
  }

  const unitPrice = num(baseRate) + num(markup);

  return (
    <Modal
      open={item !== null}
      title={existing ? `Edit ${existing.label}` : "Add cylinder type"}
      description={
        existing
          ? "Price and limits apply to orders placed from now on; past orders keep what they were billed."
          : "A new size on the price card. It becomes orderable once a customer type is allowed to buy it."
      }
      onClose={() => {
        mutation.reset();
        onClose();
      }}
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button icon="check" onClick={submit} loading={mutation.isPending} loadingText="Saving…">
            {existing ? "Save changes" : "Add cylinder type"}
          </Button>
        </>
      }
    >
      <form
        className="stack"
        style={{ gap: 14 }}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {existing?.isProtected ? (
          <Alert tone="info">
            This type is used by the platform itself. Its details can be edited, but it cannot be retired.
          </Alert>
        ) : null}

        <div className="grid-2" style={{ gap: 12 }}>
          <Field
            label="Code"
            required
            hint={existing ? "Fixed once created." : CODE_HINT}
            error={submitted && !existing ? codeError(code) : undefined}
          >
            <Input
              value={code}
              onChange={(event) => setCode(normaliseCode(event.target.value))}
              disabled={Boolean(existing)}
              maxLength={40}
              className="mono"
              autoFocus={!existing}
              placeholder="e.g. LPG_19KG"
            />
          </Field>

          <Field label="Weight (kg)" required error={submitted && num(weightKg) <= 0 ? "Enter a weight." : undefined}>
            <Input
              value={weightKg}
              onChange={(event) => setWeightKg(event.target.value.replace(/[^0-9.]/g, ""))}
              inputMode="decimal"
              placeholder="e.g. 19"
            />
          </Field>
        </div>

        <Field label="Label" required hint="What the apps print." error={submitted && !label.trim() ? "A label is required." : undefined}>
          <Input value={label} onChange={(event) => setLabel(event.target.value)} maxLength={120} placeholder="e.g. 19 KG Commercial" />
        </Field>

        <div className="grid-2" style={{ gap: 12 }}>
          <Field label="Short label" optional hint="For tight spaces, like a delivery slip.">
            <Input value={shortLabel} onChange={(event) => setShortLabel(event.target.value)} maxLength={80} placeholder="e.g. 19 KG" />
          </Field>
          <Field label="Variant" optional hint="Only when two sizes share a weight.">
            <Input value={variant} onChange={(event) => setVariant(event.target.value)} maxLength={40} placeholder="e.g. L or V" />
          </Field>
        </div>

        <div className="grid-2" style={{ gap: 12 }}>
          <Field label="Base rate" hint="Before markup.">
            <Input value={baseRate} onChange={(event) => setBaseRate(event.target.value.replace(/[^0-9.]/g, ""))} inputMode="decimal" />
          </Field>
          <Field label="Markup" hint={`Default unit price works out to ₹${unitPrice}.`}>
            <Input value={markup} onChange={(event) => setMarkup(event.target.value.replace(/[^0-9.]/g, ""))} inputMode="decimal" />
          </Field>
        </div>

        <div className="grid-2" style={{ gap: 12 }}>
          <Field label="GST %" hint="Included in the total, not added on top.">
            <Input value={gst} onChange={(event) => setGst(event.target.value.replace(/[^0-9.]/g, ""))} inputMode="decimal" />
          </Field>
          <Field label="HSN / SAC" optional hint="Printed on the invoice.">
            <Input value={hsnSac} onChange={(event) => setHsnSac(event.target.value)} maxLength={20} className="mono" />
          </Field>
        </div>

        <div className="grid-2" style={{ gap: 12 }}>
          <Field label="Reorder threshold" hint="Warn the godown below this count.">
            <Input value={reorder} onChange={(event) => setReorder(event.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </Field>
          <Field label="Sort order" hint="Lower comes first on the price card.">
            <Input value={sortOrder} onChange={(event) => setSortOrder(event.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </Field>
        </div>

        <Field label="Unit" hint="How it is counted on an invoice.">
          <Select
            value={unit}
            onChange={(event) => setUnit(event.target.value)}
            options={[
              { value: "PCS", label: "PCS - pieces" },
              { value: "NOS", label: "NOS - numbers" },
              { value: "KG", label: "KG - kilograms" }
            ]}
          />
        </Field>

        <ErrorAlert error={mutation.error} />
      </form>
    </Modal>
  );
}

// --- Customer type ------------------------------------------------------------------------------

export function CustomerTypeDialog({
  item,
  onClose,
  onSaved
}: {
  item: CustomerType | "new" | null;
  onClose: () => void;
  onSaved: (saved: CustomerType, created: boolean) => void;
}) {
  const existing = item && item !== "new" ? item : null;
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [codePrefix, setCodePrefix] = useState("C");
  const [requiresSites, setRequiresSites] = useState("no");
  const [requiresGst, setRequiresGst] = useState("no");
  const [isDefault, setIsDefault] = useState("no");
  const [sortOrder, setSortOrder] = useState("0");
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (item === null) return;
    setSubmitted(false);
    setCode(existing?.code ?? "");
    setLabel(existing?.label ?? "");
    setDescription(existing?.description ?? "");
    setCodePrefix(existing?.codePrefix ?? "C");
    setRequiresSites(existing?.requiresDeliverySites ? "yes" : "no");
    setRequiresGst(existing?.requiresGstInvoice ? "yes" : "no");
    setIsDefault(existing?.isDefault ? "yes" : "no");
    setSortOrder(existing ? String(existing.sortOrder) : "0");
  }, [item, existing]);

  const mutation = useMutation({
    mutationFn: async () => {
      const body = {
        label: label.trim(),
        description: description.trim() || null,
        codePrefix: codePrefix.trim() || "C",
        requiresDeliverySites: requiresSites === "yes",
        requiresGstInvoice: requiresGst === "yes",
        isDefault: isDefault === "yes",
        sortOrder: num(sortOrder)
      };
      return existing ? updateCustomerType(existing.code, body) : createCustomerType({ ...body, code: code.trim() });
    },
    onSuccess: (saved) => {
      onSaved(saved, !existing);
      onClose();
    }
  });

  function submit() {
    setSubmitted(true);
    if (!existing && codeError(code)) return;
    if (!label.trim()) return;
    mutation.mutate();
  }

  const YES_NO = [
    { value: "no", label: "No" },
    { value: "yes", label: "Yes" }
  ];

  return (
    <Modal
      open={item !== null}
      title={existing ? `Edit ${existing.label}` : "Add customer type"}
      description="Customer types decide what a customer may order and which documents their KYC needs."
      onClose={() => {
        mutation.reset();
        onClose();
      }}
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button icon="check" onClick={submit} loading={mutation.isPending} loadingText="Saving…">
            {existing ? "Save changes" : "Add customer type"}
          </Button>
        </>
      }
    >
      <form
        className="stack"
        style={{ gap: 14 }}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {existing?.isProtected ? (
          <Alert tone="info">This type is used by the platform itself and cannot be retired.</Alert>
        ) : null}

        <div className="grid-2" style={{ gap: 12 }}>
          <Field
            label="Code"
            required
            hint={existing ? "Fixed once created." : CODE_HINT}
            error={submitted && !existing ? codeError(code) : undefined}
          >
            <Input
              value={code}
              onChange={(event) => setCode(normaliseCode(event.target.value))}
              disabled={Boolean(existing)}
              maxLength={40}
              className="mono"
              autoFocus={!existing}
              placeholder="e.g. INDUSTRIAL"
            />
          </Field>
          <Field label="Customer code prefix" hint="Starts every customer number of this type.">
            <Input value={codePrefix} onChange={(event) => setCodePrefix(event.target.value.toUpperCase())} maxLength={8} className="mono" />
          </Field>
        </div>

        <Field label="Label" required error={submitted && !label.trim() ? "A label is required." : undefined}>
          <Input value={label} onChange={(event) => setLabel(event.target.value)} maxLength={100} placeholder="e.g. Industrial" />
        </Field>

        <Field label="Description" optional>
          <Textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} maxLength={255} />
        </Field>

        <div className="grid-2" style={{ gap: 12 }}>
          <Field label="Needs a delivery site" hint="Refuse an order until one is added.">
            <Select value={requiresSites} onChange={(event) => setRequiresSites(event.target.value)} options={YES_NO} />
          </Field>
          <Field label="Needs a GST invoice">
            <Select value={requiresGst} onChange={(event) => setRequiresGst(event.target.value)} options={YES_NO} />
          </Field>
        </div>

        <div className="grid-2" style={{ gap: 12 }}>
          <Field label="Default for new customers" hint="Only one type can be the default.">
            <Select value={isDefault} onChange={(event) => setIsDefault(event.target.value)} options={YES_NO} />
          </Field>
          <Field label="Sort order" hint="Lower comes first.">
            <Input value={sortOrder} onChange={(event) => setSortOrder(event.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </Field>
        </div>

        <ErrorAlert error={mutation.error} />
      </form>
    </Modal>
  );
}

// --- KYC document type --------------------------------------------------------------------------

export function KycDocumentTypeDialog({
  item,
  onClose,
  onSaved
}: {
  item: KycDocumentType | "new" | null;
  onClose: () => void;
  onSaved: (saved: KycDocumentType, created: boolean) => void;
}) {
  const existing = item && item !== "new" ? item : null;
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [pattern, setPattern] = useState("");
  const [minLength, setMinLength] = useState("");
  const [maxLength, setMaxLength] = useState("");
  const [expiry, setExpiry] = useState("no");
  const [scan, setScan] = useState("yes");
  const [sortOrder, setSortOrder] = useState("0");
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (item === null) return;
    setSubmitted(false);
    setCode(existing?.code ?? "");
    setLabel(existing?.label ?? "");
    setPattern(existing?.numberPattern ?? "");
    setMinLength(existing?.minLength ? String(existing.minLength) : "");
    setMaxLength(existing?.maxLength ? String(existing.maxLength) : "");
    setExpiry(existing?.expiryRequired ? "yes" : "no");
    setScan(existing ? (existing.scanRequired ? "yes" : "no") : "yes");
    setSortOrder(existing ? String(existing.sortOrder) : "0");
  }, [item, existing]);

  const mutation = useMutation({
    mutationFn: async () => {
      const body = {
        label: label.trim(),
        numberPattern: pattern.trim() || null,
        minLength: minLength.trim() ? num(minLength) : null,
        maxLength: maxLength.trim() ? num(maxLength) : null,
        expiryRequired: expiry === "yes",
        scanRequired: scan === "yes",
        sortOrder: num(sortOrder)
      };
      return existing
        ? updateKycDocumentType(existing.code, body)
        : createKycDocumentType({ ...body, code: code.trim() });
    },
    onSuccess: (saved) => {
      onSaved(saved, !existing);
      onClose();
    }
  });

  function submit() {
    setSubmitted(true);
    if (!existing && codeError(code)) return;
    if (!label.trim()) return;
    mutation.mutate();
  }

  const YES_NO = [
    { value: "no", label: "No" },
    { value: "yes", label: "Yes" }
  ];

  return (
    <Modal
      open={item !== null}
      title={existing ? `Edit ${existing.label}` : "Add KYC document type"}
      description="What a customer may be asked to produce. Which types are actually required is set per customer type."
      onClose={() => {
        mutation.reset();
        onClose();
      }}
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button icon="check" onClick={submit} loading={mutation.isPending} loadingText="Saving…">
            {existing ? "Save changes" : "Add document type"}
          </Button>
        </>
      }
    >
      <form
        className="stack"
        style={{ gap: 14 }}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {existing?.isProtected ? (
          <Alert tone="info">This document type is used by the platform itself and cannot be retired.</Alert>
        ) : null}

        <div className="grid-2" style={{ gap: 12 }}>
          <Field
            label="Code"
            required
            hint={existing ? "Fixed once created." : CODE_HINT}
            error={submitted && !existing ? codeError(code) : undefined}
          >
            <Input
              value={code}
              onChange={(event) => setCode(normaliseCode(event.target.value))}
              disabled={Boolean(existing)}
              maxLength={40}
              className="mono"
              autoFocus={!existing}
              placeholder="e.g. AADHAAR"
            />
          </Field>
          <Field label="Sort order" hint="Lower comes first on the KYC form.">
            <Input value={sortOrder} onChange={(event) => setSortOrder(event.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </Field>
        </div>

        <Field label="Label" required error={submitted && !label.trim() ? "A label is required." : undefined}>
          <Input value={label} onChange={(event) => setLabel(event.target.value)} maxLength={120} placeholder="e.g. Aadhaar card" />
        </Field>

        <Field
          label="Number pattern"
          optional
          hint="A regular expression the typed number must match. Leave blank to accept anything."
        >
          <Input value={pattern} onChange={(event) => setPattern(event.target.value)} maxLength={255} className="mono" placeholder="e.g. ^[0-9]{12}$" />
        </Field>

        <div className="grid-2" style={{ gap: 12 }}>
          <Field label="Minimum length" optional>
            <Input value={minLength} onChange={(event) => setMinLength(event.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </Field>
          <Field label="Maximum length" optional>
            <Input value={maxLength} onChange={(event) => setMaxLength(event.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </Field>
        </div>

        <div className="grid-2" style={{ gap: 12 }}>
          <Field label="Has an expiry date" hint="The customer must enter one.">
            <Select value={expiry} onChange={(event) => setExpiry(event.target.value)} options={YES_NO} />
          </Field>
          <Field label="Needs a scan or photo">
            <Select value={scan} onChange={(event) => setScan(event.target.value)} options={YES_NO} />
          </Field>
        </div>

        <ErrorAlert error={mutation.error} />
      </form>
    </Modal>
  );
}
