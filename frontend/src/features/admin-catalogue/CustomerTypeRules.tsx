import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  getCylinderEligibility,
  getKycRules,
  listCustomerTypes,
  listCylinderTypes,
  listKycDocumentTypes,
  setCylinderEligibility,
  setKycRules,
  type CylinderEligibility,
  type KycRule
} from "../../api/catalogue.api";
import { normalizeError } from "../../api/errors";
import { queryKeys } from "../../api/query-keys";
import { Button } from "../../components/common/Button";
import { Alert, EmptyState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Select } from "../../components/forms/Field";
import { Card } from "../../components/layout/Page";

/**
 * What one customer type may order, and which documents it must produce.
 *
 * This is the half of the catalogue that makes the other half mean anything: a cylinder type
 * added on the Cylinder types tab is not orderable by anybody until it appears here, and a KYC
 * document type is never asked for until a rule names it. Before this screen existed both had
 * to be set with a PUT by hand.
 *
 * Both endpoints replace the whole list, so the form always sends every row that should remain
 * - including the ones it did not touch.
 */

const LIST_PARAMS = { includeInactive: false };

const MODES = [
  { value: "", label: "Not asked for" },
  { value: "REQUIRED", label: "Required" },
  { value: "OPTIONAL", label: "Optional" },
  { value: "ANY_OF", label: "Any of a group" }
];

type CylinderRow = { included: boolean; minQuantity: string; maxQuantity: string };
type DocumentRow = { mode: string; group: string; minRequired: string };

export function CustomerTypeRules() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");

  const customerTypes = useQuery({
    queryKey: queryKeys.catalogue.customerTypes(LIST_PARAMS),
    queryFn: ({ signal }) => listCustomerTypes(LIST_PARAMS, signal)
  });
  const cylinderTypes = useQuery({
    queryKey: queryKeys.catalogue.cylinderTypes(LIST_PARAMS),
    queryFn: ({ signal }) => listCylinderTypes(LIST_PARAMS, signal)
  });
  const documentTypes = useQuery({
    queryKey: queryKeys.catalogue.kycDocumentTypes(LIST_PARAMS),
    queryFn: ({ signal }) => listKycDocumentTypes(LIST_PARAMS, signal)
  });

  // Open on the default customer type rather than an empty screen.
  useEffect(() => {
    if (code) return;
    const rows = customerTypes.data ?? [];
    const first = rows.find((row) => row.isDefault) ?? rows[0];
    if (first) setCode(first.code);
  }, [code, customerTypes.data]);

  const eligibility = useQuery({
    queryKey: queryKeys.catalogue.eligibility(code),
    queryFn: ({ signal }) => getCylinderEligibility(code, signal),
    enabled: Boolean(code)
  });
  const kycRules = useQuery({
    queryKey: queryKeys.catalogue.kycRules(code),
    queryFn: ({ signal }) => getKycRules(code, signal),
    enabled: Boolean(code)
  });

  const [cylinderRows, setCylinderRows] = useState<Record<string, CylinderRow>>({});
  const [documentRows, setDocumentRows] = useState<Record<string, DocumentRow>>({});

  // Every cylinder type gets a row, whether it is allowed or not - the screen is the list of
  // what could be allowed, with ticks on what is.
  useEffect(() => {
    if (!cylinderTypes.data || !eligibility.data) return;
    const saved = new Map(eligibility.data.map((row) => [row.cylinderTypeCode, row]));
    const next: Record<string, CylinderRow> = {};
    for (const type of cylinderTypes.data) {
      const row = saved.get(type.code);
      next[type.code] = {
        included: Boolean(row?.isActive),
        minQuantity: row ? String(row.minQuantity) : "1",
        maxQuantity: row?.maxQuantity ? String(row.maxQuantity) : ""
      };
    }
    setCylinderRows(next);
  }, [cylinderTypes.data, eligibility.data]);

  useEffect(() => {
    if (!documentTypes.data || !kycRules.data) return;
    const saved = new Map(kycRules.data.map((row) => [row.documentTypeCode, row]));
    const next: Record<string, DocumentRow> = {};
    for (const type of documentTypes.data) {
      const row = saved.get(type.code);
      next[type.code] = {
        mode: row?.isActive ? row.requirementMode : "",
        group: row?.requirementGroup ?? "",
        minRequired: row ? String(row.minRequired) : "1"
      };
    }
    setDocumentRows(next);
  }, [documentTypes.data, kycRules.data]);

  const saveCylinders = useMutation({
    mutationFn: () => {
      const items: CylinderEligibility[] = Object.entries(cylinderRows)
        .filter(([, row]) => row.included)
        .map(([cylinderTypeCode, row], index) => ({
          cylinderTypeCode,
          minQuantity: Math.max(1, Number(row.minQuantity) || 1),
          maxQuantity: row.maxQuantity.trim() ? Number(row.maxQuantity) : null,
          sortOrder: index,
          isActive: true
        }));
      return setCylinderEligibility(code, items);
    },
    onSuccess: () => {
      toast.success("Cylinder rules saved.");
      void queryClient.invalidateQueries({ queryKey: queryKeys.catalogue.all });
    }
  });

  const saveDocuments = useMutation({
    mutationFn: () => {
      const items: KycRule[] = Object.entries(documentRows)
        .filter(([, row]) => row.mode)
        .map(([documentTypeCode, row], index) => ({
          documentTypeCode,
          requirementMode: row.mode as KycRule["requirementMode"],
          requirementGroup: row.mode === "ANY_OF" ? row.group.trim() || null : null,
          minRequired: Math.max(1, Number(row.minRequired) || 1),
          isActive: true,
          sortOrder: index
        }));
      return setKycRules(code, items);
    },
    onSuccess: () => {
      toast.success("KYC rules saved.");
      void queryClient.invalidateQueries({ queryKey: queryKeys.catalogue.all });
    }
  });

  function setCylinder(typeCode: string, patch: Partial<CylinderRow>) {
    setCylinderRows((rows) => ({ ...rows, [typeCode]: { ...rows[typeCode], ...patch } }));
  }
  function setDocument(typeCode: string, patch: Partial<DocumentRow>) {
    setDocumentRows((rows) => ({ ...rows, [typeCode]: { ...rows[typeCode], ...patch } }));
  }

  function errorOf(error: unknown) {
    if (!error) return null;
    const normalised = normalizeError(error);
    const field = normalised.fieldErrors ? Object.values(normalised.fieldErrors)[0] : undefined;
    return <Alert tone="error">{field || normalised.userMessage}</Alert>;
  }

  if (customerTypes.isLoading) return <LoadingSkeleton rows={4} label="Loading customer types" />;
  if (!customerTypes.data?.length) {
    return (
      <Card>
        <EmptyState icon="users" title="No customer types" description="Add a customer type before setting its rules." />
      </Card>
    );
  }

  const chosenCylinders = Object.values(cylinderRows).filter((row) => row.included).length;
  const chosenDocuments = Object.values(documentRows).filter((row) => row.mode).length;

  return (
    <div className="stack" style={{ gap: 16 }}>
      <Card>
        <Field label="Customer type" hint="Rules below apply to customers of this type.">
          <Select
            value={code}
            onChange={(event) => setCode(event.target.value)}
            options={customerTypes.data.map((row) => ({
              value: row.code,
              label: row.isDefault ? `${row.label} (default)` : row.label
            }))}
          />
        </Field>
      </Card>

      <Card
        title="What this type may order"
        subtitle={`${chosenCylinders} of ${cylinderTypes.data?.length ?? 0} cylinder types allowed. A type that is not ticked cannot be ordered at all.`}
        headingLevel={3}
      >
        {eligibility.isLoading || cylinderTypes.isLoading ? (
          <LoadingSkeleton rows={4} label="Loading cylinder rules" />
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            {(cylinderTypes.data ?? []).map((type) => {
              const row = cylinderRows[type.code];
              if (!row) return null;
              return (
                <div
                  key={type.code}
                  className="row"
                  style={{ gap: 12, alignItems: "center", flexWrap: "wrap", paddingBottom: 8, borderBottom: "1px solid var(--border, #e2e8f0)" }}
                >
                  <label style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 220 }}>
                    <input
                      type="checkbox"
                      checked={row.included}
                      onChange={(event) => setCylinder(type.code, { included: event.target.checked })}
                    />
                    <span>
                      {type.label} <small className="mono text-muted">{type.code}</small>
                    </span>
                  </label>

                  <Field label="Min" hideLabel>
                    <Input
                      value={row.minQuantity}
                      onChange={(event) => setCylinder(type.code, { minQuantity: event.target.value.replace(/\D/g, "") })}
                      disabled={!row.included}
                      inputMode="numeric"
                      aria-label={`Minimum quantity for ${type.label}`}
                      placeholder="Min"
                      style={{ width: 90 }}
                    />
                  </Field>

                  <Field label="Max" hideLabel>
                    <Input
                      value={row.maxQuantity}
                      onChange={(event) => setCylinder(type.code, { maxQuantity: event.target.value.replace(/\D/g, "") })}
                      disabled={!row.included}
                      inputMode="numeric"
                      aria-label={`Maximum quantity for ${type.label}`}
                      placeholder="No limit"
                      style={{ width: 110 }}
                    />
                  </Field>
                </div>
              );
            })}

            {errorOf(saveCylinders.error)}

            <div className="row" style={{ justifyContent: "flex-end" }}>
              <Button icon="check" onClick={() => saveCylinders.mutate()} loading={saveCylinders.isPending} loadingText="Saving…">
                Save cylinder rules
              </Button>
            </div>
          </div>
        )}
      </Card>

      <Card
        title="Documents this type must produce"
        subtitle={`${chosenDocuments} of ${documentTypes.data?.length ?? 0} document types asked for. "Any of a group" lets the customer satisfy one rule with whichever document they have.`}
        headingLevel={3}
      >
        {kycRules.isLoading || documentTypes.isLoading ? (
          <LoadingSkeleton rows={4} label="Loading KYC rules" />
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            {(documentTypes.data ?? []).map((type) => {
              const row = documentRows[type.code];
              if (!row) return null;
              return (
                <div
                  key={type.code}
                  className="row"
                  style={{ gap: 12, alignItems: "center", flexWrap: "wrap", paddingBottom: 8, borderBottom: "1px solid var(--border, #e2e8f0)" }}
                >
                  <span style={{ minWidth: 220 }}>
                    {type.label} <small className="mono text-muted">{type.code}</small>
                  </span>

                  <Field label="Requirement" hideLabel>
                    <Select
                      value={row.mode}
                      onChange={(event) => setDocument(type.code, { mode: event.target.value })}
                      options={MODES}
                      aria-label={`Requirement for ${type.label}`}
                    />
                  </Field>

                  {row.mode === "ANY_OF" ? (
                    <Field label="Group" hideLabel>
                      <Input
                        value={row.group}
                        onChange={(event) => setDocument(type.code, { group: event.target.value })}
                        placeholder="Group name"
                        aria-label={`Group for ${type.label}`}
                        style={{ width: 150 }}
                      />
                    </Field>
                  ) : null}
                </div>
              );
            })}

            {errorOf(saveDocuments.error)}

            <div className="row" style={{ justifyContent: "flex-end" }}>
              <Button icon="check" onClick={() => saveDocuments.mutate()} loading={saveDocuments.isPending} loadingText="Saving…">
                Save KYC rules
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
