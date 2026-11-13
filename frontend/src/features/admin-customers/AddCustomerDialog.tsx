import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  getCustomerKycRequirements,
  createCustomer,
  createCustomerBranch,
  uploadDocument,
  type Customer,
  type CustomerCreateInput,
  type CustomerType,
  type KycDocumentType
} from "../../api/customers.api";
import { normalizeError } from "../../api/errors";
import type { Address } from "../../api/orders.api";
import { Button, IconButton } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { Field, Input, PhoneInput } from "../../components/forms/Field";
import { humanize } from "../../utils/format";
import { PincodeAddressFields } from "./PincodeAddressFields";
import {
  ALL_DOC_TYPES,
  DOC_META,
  DOC_PATTERNS,
  formatDocumentInput,
  formatFileSize,
  formatMobile,
  isDocumentNumberValid,
  maskIdentifier,
  validateAddress,
  validateBusinessName,
  validateDocumentNumber,
  validateEmail,
  validateMobile,
  validateName
} from "./customer-form-utils";

type DocState = {
  type: KycDocumentType;
  number: string;
  file: File | null;
};

type SiteState = {
  key: number;
  name: string;
  address: Address;
  contactName: string;
  contactMobile: string;
};

const emptyAddress = (): Address => ({ line1: "", line2: "", city: "", state: "", pincode: "" });
const STEPS = ["Customer Type", "Business Details", "KYC Documents"];
let nextKey = 1;

export function AddCustomerDialog({
  open,
  merchantId,
  onClose,
  onCreated,
  branchOwnerId
}: {
  branchOwnerId?: string;
  open: boolean;
  merchantId: string;
  onClose: () => void;
  onCreated: (customer: Customer) => void;
}) {
  const [step, setStep] = useState(0);
  const [customerType, setCustomerType] = useState<CustomerType>("RETAIL");
  const [form, setForm] = useState({ businessName: "", ownerName: "", mobile: "", email: "" });
  const [address, setAddress] = useState<Address>(emptyAddress);
  const [selectedDocTypes, setSelectedDocTypes] = useState<KycDocumentType[]>(["AADHAAR"]);
  const [docs, setDocs] = useState<Record<string, DocState>>({
    AADHAAR: { type: "AADHAAR", number: "", file: null },
    PAN: { type: "PAN", number: "", file: null },
    GST: { type: "GST", number: "", file: null },
    FSSAI: { type: "FSSAI", number: "", file: null },
    MSME: { type: "MSME", number: "", file: null }
  });
  const [sites, setSites] = useState<SiteState[]>([]);
  const requirements = useQuery({queryKey:["customer-registration-requirements",customerType],queryFn:({signal})=>getCustomerKycRequirements(customerType,signal),enabled:open,retry:false});
  const requiredDocuments = (requirements.data?.documents.filter(rule=>rule.required).map(rule=>rule.type) || []) as KycDocumentType[];
  useEffect(()=>{
    if (!requirements.data) return;
    const required = requirements.data.documents.filter(rule=>rule.required).map(rule=>rule.type) as KycDocumentType[];
    setSelectedDocTypes(previous=>required.length ? required : previous.filter(code=>requirements.data!.documents.some(rule=>rule.type===code)));
  },[requirements.data]);

  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);

  // New site inline drafting state
  const [addingSite, setAddingSite] = useState(false);
  const [newSite, setNewSite] = useState<Omit<SiteState, "key">>({
    name: "",
    address: emptyAddress(),
    contactName: "",
    contactMobile: ""
  });
  const [siteErrors, setSiteErrors] = useState<Record<string, string | undefined>>({});

  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  // Reset form when modal opens
  useEffect(() => {
    if (!open) return;
    setStep(0);
    setCustomerType("RETAIL");
    setForm({ businessName: "", ownerName: "", mobile: "", email: "" });
    setAddress(emptyAddress());
    setSelectedDocTypes(["AADHAAR"]);
    setDocs({
      AADHAAR: { type: "AADHAAR", number: "", file: null },
      PAN: { type: "PAN", number: "", file: null },
      GST: { type: "GST", number: "", file: null },
      FSSAI: { type: "FSSAI", number: "", file: null },
      MSME: { type: "MSME", number: "", file: null }
    });
    setSites([]);
    setErrors({});
    setConfirmOpen(false);
    setProgress(null);
    setAddingSite(false);
  }, [open]);

  // Adjust default docs and sites when customer type changes
  const handleCustomerTypeSelect = (type: CustomerType) => {
    setCustomerType(type);
    setErrors({});
    if (type === "INDUSTRIAL") {
      setSelectedDocTypes(["FSSAI", "GST"]);
      if (sites.length === 0) {
        setSites([{ key: nextKey++, name: "Primary site", address: emptyAddress(), contactName: "", contactMobile: "" }]);
      }
    } else {
      setSelectedDocTypes(["AADHAAR"]);
      setSites([]);
    }
  };

  const clearError = (key: string) => setErrors((prev) => ({ ...prev, [key]: undefined }));

  // Validation for Step 1 (Business & Delivery details)
  const validateStep1 = (): boolean => {
    const errs: Record<string, string | undefined> = {};
    const bErr = validateBusinessName(form.businessName);
    if (bErr) errs.businessName = bErr;

    const oErr = validateName(form.ownerName, "Contact person name");
    if (oErr) errs.ownerName = oErr;

    const mErr = validateMobile(form.mobile);
    if (mErr) errs.mobile = mErr;

    const eErr = validateEmail(form.email);
    if (eErr) errs.email = eErr;

    const addrErrs = validateAddress(address);
    Object.entries(addrErrs).forEach(([k, v]) => {
      errs[`address.${k}`] = v;
    });

    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  // Validation for Step 2 (KYC documents)
  const validateStep2 = (): boolean => {
    const errs: Record<string, string | undefined> = {};
    if (!requirements.data) { setErrors({_general:"Required documents could not be loaded. Please retry."}); return false; }
    const minDocs = requirements.data.minimumDocuments;
    const reqDocs = requiredDocuments;
    let validCount = 0;

    selectedDocTypes.forEach((docType) => {
      const doc = docs[docType];
      const isReq = reqDocs.includes(docType);
      const hasNumber = Boolean(doc?.number?.trim());
      const hasFile = Boolean(doc?.file);

      if (isReq || hasNumber || hasFile) {
        const numErr = validateDocumentNumber(docType, doc?.number ?? "");
        if (numErr) errs[`doc.${docType}.number`] = numErr;
        if (!doc?.file) errs[`doc.${docType}.file`] = `Please upload ${DOC_META[docType].title} file`;

        if (!numErr && doc?.file) {
          validCount++;
        }
      }
    });

    if (validCount < minDocs) {
      errs._general = `Please complete at least ${minDocs} required document${minDocs > 1 ? "s" : ""} (number & file upload)`;
    }

    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const mutation = useMutation({
    mutationFn: async () => {
      const documents: CustomerCreateInput["documents"] = [];
      const activeDocs = selectedDocTypes.map((type) => docs[type]).filter((d) => d && d.number.trim());

      for (let i = 0; i < activeDocs.length; i++) {
        const d = activeDocs[i];
        let fileId: string | undefined;
        if (d.file) {
          setProgress(`Uploading ${DOC_META[d.type].title} (${i + 1} of ${activeDocs.length})…`);
          const res = await uploadDocument(merchantId, d.file, d.type);
          fileId = res.fileId;
        }
        documents.push({
          type: d.type,
          number: d.number.trim(),
          fileId
        });
      }

      setProgress("Registering customer…");
      const create = branchOwnerId ? (merchant: string, input: CustomerCreateInput) => createCustomerBranch(merchant, branchOwnerId, input) : createCustomer;
      return create(merchantId, {
        customerType,
        businessName: form.businessName.trim(),
        ownerName: form.ownerName.trim(),
        mobile: form.mobile.replace(/\D/g, ""),
        email: form.email.trim() || undefined,
        deliveryAddress: address,
        documents,
        sites:
          customerType === "INDUSTRIAL"
            ? [
                { name: "Primary site", address, isPrimary: true },
                ...sites.filter((s) => s.name.trim() !== "Primary site").map((s) => ({
                  name: s.name.trim(),
                  address: s.address,
                  contactName: s.contactName.trim() || undefined,
                  contactMobile: s.contactMobile.replace(/\D/g, "") || undefined,
                  isPrimary: false
                }))
              ]
            : []
      });
    },
    onSuccess: (created) => {
      setConfirmOpen(false);
      onCreated(created);
      onClose();
    },
    onError: () => {
      setConfirmOpen(false);
    },
    onSettled: () => setProgress(null)
  });

  const error = mutation.error ? normalizeError(mutation.error) : null;

  const handleNext = () => {
    if (step === 0) {
      setStep(1);
    } else if (step === 1) {
      if (validateStep1()) {
        setStep(2);
      }
    } else if (step === 2) {
      if (validateStep2()) {
        setConfirmOpen(true);
      }
    }
  };

  const handleBack = () => {
    if (step > 0) {
      setErrors({});
      setStep((s) => s - 1);
    } else {
      onClose();
    }
  };

  const handleDocNumberChange = (type: KycDocumentType, raw: string) => {
    const formatted = formatDocumentInput(type, raw);
    setDocs((prev) => ({
      ...prev,
      [type]: { ...prev[type], number: formatted }
    }));
    clearError(`doc.${type}.number`);
    clearError("_general");
  };

  const handleDocFileSelect = (type: KycDocumentType, file: File | null) => {
    if (file && file.size > 5 * 1024 * 1024) {
      setErrors((prev) => ({ ...prev, [`doc.${type}.file`]: "File exceeds 5 MB limit" }));
      return;
    }
    setDocs((prev) => ({
      ...prev,
      [type]: { ...prev[type], file }
    }));
    clearError(`doc.${type}.file`);
    clearError("_general");
  };

  const handleRemoveDoc = (type: KycDocumentType) => {
    setDocs((prev) => ({
      ...prev,
      [type]: { type, number: "", file: null }
    }));
    setSelectedDocTypes((prev) => prev.filter((t) => t !== type));
    clearError(`doc.${type}.number`);
    clearError(`doc.${type}.file`);
  };

  const availableToAdd = ALL_DOC_TYPES.filter((type) => !selectedDocTypes.includes(type) && requirements.data?.documents.some(rule=>rule.type===type));

  const handleAddSite = () => {
    const errs: Record<string, string | undefined> = {};
    if (!newSite.name.trim()) errs.name = "Site name is required";
    const addrErrs = validateAddress(newSite.address);
    Object.entries(addrErrs).forEach(([k, v]) => (errs[`address.${k}`] = v));
    if (newSite.contactMobile && !/^[6-9]\d{9}$/.test(newSite.contactMobile.replace(/\D/g, ""))) {
      errs.contactMobile = "Enter a valid 10-digit mobile";
    }

    setSiteErrors(errs);
    if (Object.keys(errs).length === 0) {
      setSites((prev) => [...prev, { key: nextKey++, ...newSite }]);
      setNewSite({ name: "", address: emptyAddress(), contactName: "", contactMobile: "" });
      setAddingSite(false);
      setSiteErrors({});
    }
  };

  const attachedCount = selectedDocTypes.filter((t) => Boolean(docs[t]?.number?.trim() && docs[t]?.file)).length;
  const minRequiredDocs = requirements.data?.minimumDocuments || 0;

  return (
    <>
      <Modal
        open={open}
        wide
        title={step === 0 ? "Select Customer Type" : step === 1 ? "Customer Details" : "KYC Documents"}
        description={
          step === 0
            ? "Choose the type of account for this customer."
            : step === 1
              ? "Enter business information and verified delivery location."
              : "Upload required identity and commercial verification documents."
        }
        onClose={() => {
          if (!mutation.isPending) {
            mutation.reset();
            onClose();
          }
        }}
        busy={mutation.isPending}
        footer={
          <div className="row-between" style={{ width: "100%" }}>
            <div>
              {step > 0 ? (
                <Button variant="secondary" icon="arrowLeft" onClick={handleBack} disabled={mutation.isPending}>
                  Back
                </Button>
              ) : (
                <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
                  Cancel
                </Button>
              )}
            </div>
            <div className="row" style={{ gap: "var(--space-2)" }}>
              {step < 2 ? (
                <Button icon="arrowRight" onClick={handleNext} disabled={mutation.isPending}>
                  Continue
                </Button>
              ) : (
                <Button
                  icon="check"
                  onClick={handleNext}
                  loading={mutation.isPending}
                  loadingText={progress ?? "Saving…"}
                >
                  Review & Register
                </Button>
              )}
            </div>
          </div>
        }
      >
        <div className="stack-lg">
          {/* Progress Stepper matching Merchant App */}
          <div className="wizard-stepper" role="navigation" aria-label="Registration steps">
            <div className="wizard-step__track">
              <div className="wizard-step__progress" style={{ width: `${(step / (STEPS.length - 1)) * 100}%` }} />
            </div>
            {STEPS.map((label, idx) => {
              const isCompleted = step > idx;
              const isActive = step === idx;
              return (
                <button
                  key={label}
                  type="button"
                  className={`wizard-step${isActive ? " is-active" : ""}${isCompleted ? " is-completed" : ""}`}
                  onClick={() => {
                    if (isCompleted) {
                      setErrors({});
                      setStep(idx);
                    }
                  }}
                  disabled={!isCompleted && !isActive}
                >
                  <div className="wizard-step__indicator">
                    {isCompleted ? <Icon name="check" size={16} /> : idx + 1}
                  </div>
                  <span className="wizard-step__label">{label}</span>
                </button>
              );
            })}
          </div>

          {/* STEP 0: CUSTOMER TYPE */}
          {step === 0 && (
            <div className="stack-md">
              <div className="grid-2">
                <div
                  className={`customer-type-card${customerType === "RETAIL" ? " is-selected" : ""}`}
                  onClick={() => handleCustomerTypeSelect("RETAIL")}
                  role="radio"
                  aria-checked={customerType === "RETAIL"}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") handleCustomerTypeSelect("RETAIL");
                  }}
                >
                  <div className="customer-type-card__icon">
                    <Icon name="store" size={24} />
                  </div>
                  <div className="customer-type-card__content">
                    <div className="customer-type-card__title">Retail Customer</div>
                    <div className="customer-type-card__desc">Restaurants, hotels, shops & small businesses</div>
                    <span className="customer-type-card__badge">5, 10 & 19 KG cylinders</span>
                  </div>
                  <div className="customer-type-card__radio">
                    {customerType === "RETAIL" && <div className="customer-type-card__radio-inner" />}
                  </div>
                </div>

                <div
                  className={`customer-type-card${customerType === "INDUSTRIAL" ? " is-selected" : ""}`}
                  onClick={() => handleCustomerTypeSelect("INDUSTRIAL")}
                  role="radio"
                  aria-checked={customerType === "INDUSTRIAL"}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") handleCustomerTypeSelect("INDUSTRIAL");
                  }}
                >
                  <div className="customer-type-card__icon">
                    <Icon name="truck" size={24} />
                  </div>
                  <div className="customer-type-card__content">
                    <div className="customer-type-card__title">Industrial Customer</div>
                    <div className="customer-type-card__desc">Industries, canteens & commercial plants</div>
                    <span className="customer-type-card__badge">47.5 KG & 422 KG Hippo</span>
                  </div>
                  <div className="customer-type-card__radio">
                    {customerType === "INDUSTRIAL" && <div className="customer-type-card__radio-inner" />}
                  </div>
                </div>
              </div>

              <Alert tone="info">
                {customerType === "RETAIL"
                  ? "Retail KYC: upload identity proof (Aadhaar, PAN, FSSAI, GST, or MSME certificate)."
                  : "Industrial KYC: upload FSSAI licence and GST / MSME certificate. Requires delivery site configuration."}
              </Alert>
            </div>
          )}

          {/* STEP 1: BUSINESS & DELIVERY DETAILS */}
          {step === 1 && (
            <div className="stack-lg">
              <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
                <legend className="field__label" style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "var(--space-2)" }}>
                  Business / Contact Details
                </legend>
                <div className="grid-2">
                  <Field label="Business / Shop name" required error={errors.businessName}>
                    <Input
                      value={form.businessName}
                      onChange={(e) => {
                        setForm((prev) => ({ ...prev, businessName: e.target.value }));
                        clearError("businessName");
                      }}
                      maxLength={100}
                      placeholder="e.g. Sharma General Store"
                      autoFocus
                    />
                  </Field>
                  <Field label="Contact person name" required error={errors.ownerName}>
                    <Input
                      value={form.ownerName}
                      onChange={(e) => {
                        setForm((prev) => ({ ...prev, ownerName: e.target.value }));
                        clearError("ownerName");
                      }}
                      maxLength={60}
                      placeholder="Full name"
                    />
                  </Field>
                  <Field
                    label="Customer mobile number"
                    required
                    hint="The customer signs in to the MBGA Customer app with this number"
                    error={errors.mobile}
                  >
                    <PhoneInput
                      value={form.mobile}
                      onChange={(e) => {
                        setForm((prev) => ({ ...prev, mobile: e.target.value }));
                        clearError("mobile");
                      }}
                    />
                  </Field>
                  <Field label="Email" optional error={errors.email}>
                    <Input
                      type="email"
                      value={form.email}
                      onChange={(e) => {
                        setForm((prev) => ({ ...prev, email: e.target.value }));
                        clearError("email");
                      }}
                      maxLength={100}
                      placeholder="name@business.com"
                    />
                  </Field>
                </div>
              </fieldset>

              <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
                <legend className="field__label" style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "var(--space-2)" }}>
                  Delivery Address
                </legend>
                <PincodeAddressFields
                  value={address}
                  onChange={(next) => {
                    setAddress(next);
                    clearError("address.pincode");
                    clearError("address.line1");
                    clearError("address.city");
                    clearError("address.state");
                  }}
                  prefix="Delivery"
                  merchantId={merchantId}
                />
                {errors["address.line1"] && <div className="field__error">{errors["address.line1"]}</div>}
                {errors["address.city"] && <div className="field__error">{errors["address.city"]}</div>}
                {errors["address.state"] && <div className="field__error">{errors["address.state"]}</div>}
                {errors["address.pincode"] && <div className="field__error">{errors["address.pincode"]}</div>}
              </fieldset>

              {/* INDUSTRIAL DELIVERY SITES */}
              {customerType === "INDUSTRIAL" && (
                <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
                  <div className="row-between" style={{ alignItems: "flex-start", marginBottom: "var(--space-2)" }}>
                    <div>
                      <legend className="field__label" style={{ fontSize: "1rem", fontWeight: 700, margin: 0 }}>
                        Additional Delivery Sites
                      </legend>
                      <p className="field__hint" style={{ marginTop: 2, margin: 0 }}>
                        The delivery address above is the primary site. Add other plants, factories or kitchens.
                      </p>
                    </div>
                    {!addingSite && (
                      <Button
                        variant="secondary"
                        size="sm"
                        icon="plus"
                        onClick={() => {
                          setAddingSite(true);
                          setNewSite({ name: "", address: emptyAddress(), contactName: "", contactMobile: "" });
                          setSiteErrors({});
                        }}
                      >
                        Add site
                      </Button>
                    )}
                  </div>

                  {sites.length > 0 && (
                    <div className="stack" style={{ gap: "var(--space-3)" }}>
                      {sites.map((site, idx) => (
                        <div key={site.key} className="card" style={{ padding: "var(--space-4)" }}>
                          <div className="row-between">
                            <strong>{site.name || `Site ${idx + 1}`}</strong>
                            <IconButton
                              icon="trash"
                              label={`Remove ${site.name}`}
                              onClick={() => setSites((prev) => prev.filter((s) => s.key !== site.key))}
                            />
                          </div>
                          <div className="text-sm text-subtle" style={{ marginTop: 4 }}>
                            {site.address.line1 ? `${site.address.line1}, ` : ""}
                            {site.address.city} {site.address.pincode}
                            {site.contactName ? ` · Contact: ${site.contactName}` : ""}
                            {site.contactMobile ? ` (${formatMobile(site.contactMobile)})` : ""}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {addingSite && (
                    <div className="card stack-md" style={{ padding: "var(--space-4)", border: "1px solid var(--blue-300)" }}>
                      <div className="row-between">
                        <strong>New Delivery Site</strong>
                        <IconButton icon="x" label="Cancel adding site" onClick={() => setAddingSite(false)} />
                      </div>
                      <div className="grid-2">
                        <Field label="Site name" required error={siteErrors.name}>
                          <Input
                            value={newSite.name}
                            onChange={(e) => {
                              setNewSite((prev) => ({ ...prev, name: e.target.value }));
                              setSiteErrors((prev) => ({ ...prev, name: undefined }));
                            }}
                            maxLength={100}
                            placeholder="e.g. Unit 2 Bottling Plant"
                          />
                        </Field>
                        <Field label="Contact person" optional>
                          <Input
                            value={newSite.contactName}
                            onChange={(e) => setNewSite((prev) => ({ ...prev, contactName: e.target.value }))}
                            maxLength={60}
                            placeholder="Site supervisor / manager"
                          />
                        </Field>
                        <Field label="Contact mobile" optional error={siteErrors.contactMobile}>
                          <PhoneInput
                            value={newSite.contactMobile}
                            onChange={(e) => {
                              setNewSite((prev) => ({ ...prev, contactMobile: e.target.value }));
                              setSiteErrors((prev) => ({ ...prev, contactMobile: undefined }));
                            }}
                          />
                        </Field>
                      </div>
                      <PincodeAddressFields
                        value={newSite.address}
                        onChange={(addr) => setNewSite((prev) => ({ ...prev, address: addr }))}
                        prefix="Site"
                        merchantId={merchantId}
                      />
                      <div className="row" style={{ justifyContent: "flex-end", gap: "var(--space-2)" }}>
                        <Button variant="secondary" size="sm" onClick={() => setAddingSite(false)}>
                          Cancel
                        </Button>
                        <Button size="sm" icon="check" onClick={handleAddSite}>
                          Save site
                        </Button>
                      </div>
                    </div>
                  )}
                </fieldset>
              )}
            </div>
          )}

          {/* STEP 2: KYC DOCUMENTS */}
          {step === 2 && (
            <div className="stack-lg">
              {/* Document status banner matching Merchant App */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--space-3)",
                  padding: "var(--space-3) var(--space-4)",
                  borderRadius: "var(--radius-md)",
                  border: `1px solid ${attachedCount >= minRequiredDocs ? "var(--success-200, #a7f3d0)" : "var(--blue-200, #bfdbfe)"}`,
                  background: attachedCount >= minRequiredDocs ? "var(--success-50, #ecfdf5)" : "var(--blue-50, #eff6ff)"
                }}
              >
                <Icon
                  name={attachedCount >= minRequiredDocs ? "checkCircle" : "info"}
                  size={20}
                  className={attachedCount >= minRequiredDocs ? "text-success" : "text-primary"}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: "0.95rem", color: attachedCount >= minRequiredDocs ? "var(--success-700, #15803d)" : "var(--blue-700, #1e40af)" }}>
                    {customerType === "RETAIL"
                      ? `${attachedCount} of ${ALL_DOC_TYPES.length} documents uploaded (at least ${minRequiredDocs} required)`
                      : `${attachedCount} of ${selectedDocTypes.length} documents uploaded (at least ${minRequiredDocs} required: ${requiredDocuments.map(type=>DOC_META[type]?.title || type).join(" & ")})`}
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: 2 }}>
                    PDF, JPG or PNG up to 5 MB each. Encrypted and verified during KYC review.
                  </div>
                </div>
              </div>

              {requirements.isError ? <Alert tone="error">Could not load required documents.<Button variant="secondary" onClick={()=>void requirements.refetch()}>Retry requirements</Button></Alert> : null}
              {errors._general && <Alert tone="error">{errors._general}</Alert>}

              {/* Active Document Cards */}
              <div className="stack" style={{ gap: "var(--space-4)" }}>
                {selectedDocTypes.map((docType) => {
                  const meta = DOC_META[docType];
                  const doc = docs[docType] || { type: docType, number: "", file: null };
                  const isRequired = requiredDocuments.includes(docType);
                  const pattern = DOC_PATTERNS[docType];
                  const isNumberValid = isDocumentNumberValid(docType, doc.number);

                  return (
                    <div key={docType} className="doc-card-modern">
                      <div className="doc-header-modern">
                        <div className="doc-header-modern__title-row">
                          <div className="doc-icon-badge" style={{ background: meta.bgColor, color: meta.color }}>
                            <Icon name={meta.icon} size={20} />
                          </div>
                          <div>
                            <div style={{ fontWeight: 700, fontSize: "1rem", color: "var(--text)" }}>{meta.title}</div>
                            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>{meta.subtitle}</div>
                          </div>
                        </div>

                        <div className="row" style={{ gap: "var(--space-2)" }}>
                          <span className={`doc-badge-pill${isRequired ? " is-required" : ""}`}>
                            {isRequired ? "1 required" : "Optional"}
                          </span>
                          {!isRequired && selectedDocTypes.length > 1 && (
                            <IconButton
                              icon="trash"
                              label={`Remove ${meta.title}`}
                              onClick={() => handleRemoveDoc(docType)}
                            />
                          )}
                        </div>
                      </div>

                      {/* Document Number Input with real-time format validation */}
                      <div style={{ position: "relative" }}>
                        <Field
                          label={`${meta.title.toUpperCase()} NUMBER`}
                          required={isRequired}
                          error={errors[`doc.${docType}.number`]}
                          hint={doc.number ? `Stored as ${maskIdentifier(doc.number)}` : pattern.hint}
                        >
                          <Input
                            value={doc.number}
                            onChange={(e) => handleDocNumberChange(docType, e.target.value)}
                            maxLength={pattern.maxLength}
                            placeholder={pattern.placeholder}
                            style={isNumberValid ? { paddingRight: "36px" } : undefined}
                          />
                        </Field>
                        {isNumberValid && (
                          <div
                            style={{
                              position: "absolute",
                              right: 12,
                              top: 34,
                              color: "var(--success-600, #16a34a)",
                              display: "flex",
                              pointerEvents: "none"
                            }}
                          >
                            <Icon name="checkCircle" size={18} />
                          </div>
                        )}
                      </div>

                      {/* File Upload Zone */}
                      <div>
                        <div className="row-between" style={{ marginBottom: "var(--space-1)" }}>
                          <span className="field__label" style={{ fontSize: "0.85rem", margin: 0 }}>
                            Document File {isRequired ? <span aria-hidden="true">*</span> : null}
                          </span>
                          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                            PDF, JPG, PNG · Max 5 MB
                          </span>
                        </div>

                        <input
                          type="file"
                          ref={(el) => {
                            fileInputRefs.current[docType] = el;
                          }}
                          accept=".pdf,.jpg,.jpeg,.png"
                          style={{ display: "none" }}
                          onChange={(e) => {
                            const f = e.target.files?.[0] ?? null;
                            handleDocFileSelect(docType, f);
                          }}
                        />

                        {!doc.file ? (
                          <div
                            className="doc-dropzone"
                            onClick={() => fileInputRefs.current[docType]?.click()}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") fileInputRefs.current[docType]?.click();
                            }}
                          >
                            <Icon name="fileText" size={26} className="text-primary" />
                            <div style={{ marginTop: 6, fontWeight: 600, color: "var(--blue-600, #2563eb)", fontSize: "0.9rem" }}>
                              Click to choose a file or drag & drop
                            </div>
                            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: 2 }}>
                              A clear photo or scanned document
                            </div>
                          </div>
                        ) : (
                          <div className="doc-file-card">
                            <div className="doc-file-card__info">
                              <div className="doc-file-card__icon">
                                <Icon name="fileText" size={20} />
                              </div>
                              <div style={{ minWidth: 0 }}>
                                <div
                                  style={{
                                    fontWeight: 600,
                                    fontSize: "0.9rem",
                                    color: "var(--text)",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap"
                                  }}
                                >
                                  {doc.file.name}
                                </div>
                                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: 2 }}>
                                  {formatFileSize(doc.file.size)} · <span style={{ color: "var(--success-600, #16a34a)", fontWeight: 600 }}>Attached</span>
                                </div>
                              </div>
                            </div>
                            <div className="row" style={{ gap: "var(--space-2)" }}>
                              <Button
                                variant="secondary"
                                size="sm"
                                icon="refresh"
                                onClick={() => fileInputRefs.current[docType]?.click()}
                              >
                                Replace
                              </Button>
                              <IconButton
                                icon="trash"
                                label="Remove attached file"
                                onClick={() => handleDocFileSelect(docType, null)}
                              />
                            </div>
                          </div>
                        )}
                        {errors[`doc.${docType}.file`] && (
                          <div className="field__error" style={{ marginTop: 4 }}>
                            {errors[`doc.${docType}.file`]}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Add Another Document Button */}
              {availableToAdd.length > 0 && (
                <div className="row-between" style={{ padding: "var(--space-2) 0" }}>
                  <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
                    Additional verification documents (optional):
                  </span>
                  <div className="row" style={{ gap: "var(--space-2)" }}>
                    {availableToAdd.map((type) => (
                      <Button
                        key={type}
                        variant="secondary"
                        size="sm"
                        icon="plus"
                        onClick={() => setSelectedDocTypes((prev) => [...prev, type])}
                      >
                        Add {DOC_META[type].title}
                      </Button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {error && (
            <Alert tone="error" title={error.userMessage}>
              {error.fieldErrors && Object.keys(error.fieldErrors).length ? (
                <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
                  {Object.entries(error.fieldErrors).map(([field, message]) => (
                    <li key={field}>
                      <strong>{humanize(field.split(".").pop() ?? field)}</strong>: {message}
                    </li>
                  ))}
                </ul>
              ) : null}
            </Alert>
          )}
        </div>
      </Modal>

      {/* CONFIRMATION / REVIEW MODAL MATCHING MERCHANT APP */}
      <Modal
        open={confirmOpen}
        title="Register this customer?"
        description="The application goes to KYC review. Once approved, the customer can sign in to the MBGA Customer app with this mobile number."
        onClose={() => {
          if (!mutation.isPending) setConfirmOpen(false);
        }}
        busy={mutation.isPending}
        footer={
          <div className="row-between" style={{ width: "100%" }}>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)} disabled={mutation.isPending}>
              Back to edit
            </Button>
            <Button
              icon="check"
              onClick={() => mutation.mutate()}
              loading={mutation.isPending}
              loadingText={progress ?? "Creating customer…"}
            >
              Confirm & Register Customer
            </Button>
          </div>
        }
      >
        <div className="stack-md">
          <div className="summary-review-card">
            <div className="summary-row">
              <span className="summary-row__label">Customer Type</span>
              <span className="summary-row__value">{customerType === "RETAIL" ? "Retail" : "Industrial"}</span>
            </div>
            <div className="summary-row">
              <span className="summary-row__label">Business / Shop</span>
              <span className="summary-row__value">{form.businessName}</span>
            </div>
            <div className="summary-row">
              <span className="summary-row__label">Contact Person</span>
              <span className="summary-row__value">{form.ownerName}</span>
            </div>
            <div className="summary-row">
              <span className="summary-row__label">Mobile</span>
              <span className="summary-row__value">{formatMobile(form.mobile)}</span>
            </div>
            {form.email && (
              <div className="summary-row">
                <span className="summary-row__label">Email</span>
                <span className="summary-row__value">{form.email}</span>
              </div>
            )}
            <div className="summary-row">
              <span className="summary-row__label">Delivery Address</span>
              <span className="summary-row__value">
                {address.line1}
                {address.line2 ? `, ${address.line2}` : ""}, {address.city}, {address.state} - {address.pincode}
              </span>
            </div>
            <div className="summary-row">
              <span className="summary-row__label">KYC Documents</span>
              <span className="summary-row__value">
                {selectedDocTypes
                  .filter((t) => Boolean(docs[t]?.number && docs[t]?.file))
                  .map((t) => `${DOC_META[t].title} (${maskIdentifier(docs[t].number)})`)
                  .join(", ") || "None"}
              </span>
            </div>
            {customerType === "INDUSTRIAL" && sites.length > 0 && (
              <div className="summary-row">
                <span className="summary-row__label">Delivery Sites</span>
                <span className="summary-row__value">
                  {`Primary site + ${sites.length} additional site${sites.length > 1 ? "s" : ""}`}
                </span>
              </div>
            )}
          </div>
        </div>
      </Modal>
    </>
  );
}
