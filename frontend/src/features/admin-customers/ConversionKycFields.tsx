import type { Customer, CustomerKycRequirements } from "../../api/customers.api";
import { Field, Input } from "../../components/forms/Field";
import { Alert } from "../../components/feedback/Feedback";
export type ConversionDocument = { number: string; file: File | null; fileId?: string; replace?: boolean };
export function reusableDocument(customer: Customer, type: string) {
  return customer.documents?.find(doc => doc.type === type && doc.status !== "REJECTED" && doc.numberMasked && (doc.fileId || doc.files?.length));
}
export function conversionComplete(customer: Customer, requirements: CustomerKycRequirements, drafts: Record<string, ConversionDocument>) {
  const available = requirements.documents.filter(rule => {
    const draft = drafts[rule.type];
    const existing = reusableDocument(customer, rule.type);
    return (!draft?.replace && existing) || (draft?.number.trim() && (draft.file || draft.fileId));
  });
  if (requirements.documents.some(rule => rule.required && !available.some(doc => doc.type === rule.type))) return false;
  if (available.length < requirements.minimumDocuments) return false;
  if (requirements.documents.some(rule => rule.requiredGroup && !available.some(doc => doc.requiredGroup === rule.requiredGroup))) return false;
  return requirements.documents.every(rule => {
    const draft = drafts[rule.type];
    return !draft?.replace && reusableDocument(customer, rule.type) || !draft?.number.trim() && !draft?.file && !draft?.fileId || Boolean(draft?.number.trim() && (draft.file || draft.fileId));
  });
}
export function ConversionKycFields({customer,requirements,drafts,onChange}:{customer:Customer;requirements:CustomerKycRequirements;drafts:Record<string,ConversionDocument>;onChange:(type:string,value:ConversionDocument)=>void}) {
  return <section className="stack">
    <Alert tone="warning">Changing customer type requires the same details and KYC as a new {requirements.customerType.toLowerCase()} registration. Existing valid documents can be reused. The updated registration will require KYC review.</Alert>
    <p>Complete required documents below. Minimum documents: {requirements.minimumDocuments}.</p>
    {requirements.documents.map(rule => {
      const draft = drafts[rule.type] || {number:"",file:null};
      const existing = reusableDocument(customer,rule.type);
      const editing = !existing || draft.replace;
      return <div className="stack" key={rule.type}>
        <strong>{rule.label}{rule.required ? " (required)" : rule.requiredGroup ? " (choose from this group)" : " (optional)"}</strong>
        {existing ? <><p>On file: {existing.numberMasked} · {existing.fileName || "Uploaded document"}</p><label><input type="checkbox" checked={Boolean(draft.replace)} onChange={e=>onChange(rule.type,{number:"",file:null,replace:e.target.checked})}/> Replace {rule.label}</label></> : null}
        {editing ? <><Field label={`${rule.label} number`} required={rule.required} hint={rule.numberFormat}><Input required={rule.required || Boolean(draft.file)} value={draft.number} maxLength={40} onChange={e=>onChange(rule.type,{...draft,number:e.target.value,replace:true})}/></Field><Field label={`${rule.label} document`} required={rule.required}><Input type="file" accept="application/pdf,image/jpeg,image/png" required={!draft.fileId && !draft.file && (rule.required || Boolean(draft.number))} onChange={e=>onChange(rule.type,{...draft,file:e.target.files?.[0] || null,fileId:undefined,replace:true})}/></Field></> : null}
      </div>;
    })}
  </section>;
}
