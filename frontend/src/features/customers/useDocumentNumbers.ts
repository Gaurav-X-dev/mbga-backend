import { useEffect, useRef, useState } from "react";
import { revealDocumentNumber } from "../../api/customer-kyc.api";
import { normalizeError } from "../../api/errors";
import { useOptionalAuth } from "../../auth/auth-context";

type NumberDocument = { id?: string; type: string; fileId?: string | null; numberMasked: string };
export const documentNumberKey = (document: NumberDocument) => document.id ?? `${document.type}-${document.fileId ?? document.numberMasked}`;

/** Full values stay in component memory only and use the existing audited reveal endpoint. */
export function useDocumentNumbers(applicationId?: string | null) {
  const auth = useOptionalAuth();
  const canReveal = Boolean(auth?.channel === "admin" && auth.user?.active_roles.includes("super_admin") &&
    ["customers.review", "customer_documents.review", "customers.verify"].every(permission => auth.can(permission)));
  const [shownNumbers, setShownNumbers] = useState<Set<string>>(new Set());
  const [fullNumbers, setFullNumbers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const generation = useRef(0);
  const userId = auth?.user?.user_id;
  useEffect(() => {
    generation.current++;
    setShownNumbers(new Set()); setFullNumbers({}); setLoading(new Set()); setErrors({});
    return () => { generation.current++; };
  }, [applicationId, userId, canReveal]);

  function hideAll() {
    generation.current++;
    setShownNumbers(new Set()); setFullNumbers({}); setLoading(new Set()); setErrors({});
  }
  async function reveal(document: NumberDocument) {
    const key = documentNumberKey(document);
    if (loading.has(key) || shownNumbers.has(key)) return;
    if (!canReveal) { setShownNumbers(previous => new Set(previous).add(key)); return; }
    if (!applicationId || !document.id) {
      setErrors(previous => ({ ...previous, [key]: "The full number is unavailable because this document is not linked to an application." }));
      return;
    }
    const current = generation.current;
    setErrors(previous => { const next = { ...previous }; delete next[key]; return next; });
    setLoading(previous => new Set(previous).add(key));
    try {
      const result = await revealDocumentNumber(applicationId, document.id);
      if (current !== generation.current) return;
      setFullNumbers(previous => ({ ...previous, [key]: result.number }));
      setShownNumbers(previous => new Set(previous).add(key));
    } catch (error) {
      if (current === generation.current) setErrors(previous => ({ ...previous, [key]: normalizeError(error).userMessage }));
    } finally {
      if (current === generation.current) setLoading(previous => { const next = new Set(previous); next.delete(key); return next; });
    }
  }
  async function toggleNumber(document: NumberDocument) {
    const key = documentNumberKey(document);
    if (shownNumbers.has(key)) {
      setShownNumbers(previous => { const next = new Set(previous); next.delete(key); return next; });
      setFullNumbers(previous => { const next = { ...previous }; delete next[key]; return next; });
    } else await reveal(document);
  }
  async function showAll(documents: NumberDocument[]) {
    await Promise.all(documents.map(reveal));
  }
  return { canReveal, shownNumbers, fullNumbers, loading, errors, toggleNumber, showAll, hideAll };
}
