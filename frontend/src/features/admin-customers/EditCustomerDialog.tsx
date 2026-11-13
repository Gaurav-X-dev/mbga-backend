import { useState } from "react";
import { getLogisticsOptions } from "../../api/logistics.api";
import { useOptionalAuth } from "../../auth/auth-context";
import { useMutation, useQuery } from "@tanstack/react-query";
import { getCustomerKycRequirements, uploadDocument, updateCustomer, updateCustomerBranch, BRANCH_PERMISSIONS, CUSTOMER_PERMISSION_LABELS as permissionLabels, type Customer, type CustomerType, type CustomerCreateInput, type KycDocumentType } from "../../api/customers.api";
import { ConversionKycFields, conversionComplete, type ConversionDocument } from "./ConversionKycFields";
import { normalizeError } from "../../api/errors";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";

export function EditCustomerDialog({ customer, merchantId, onClose, onSaved, branchOwnerId, permissionCatalog = [...BRANCH_PERMISSIONS] }: { permissionCatalog?: string[]; branchOwnerId?: string; customer: Customer; merchantId: string; onClose: () => void; onSaved: () => void }) {
  const [mobile, setMobile] = useState((customer.mobile || "").replace(/^\+91/, ""));
  const [permissions, setPermissions] = useState<string[]>(customer.branchPermissions ?? permissionCatalog);
  const auth=useOptionalAuth();
  const [customerType, setCustomerType] = useState<CustomerType>((customer.customerType as CustomerType) || "RETAIL");
  const typeChanged = customerType !== customer.customerType;
  const [conversionDocuments, setConversionDocuments] = useState<Record<string, ConversionDocument>>({});
  const [siteName, setSiteName] = useState("Primary site");
  const requirements = useQuery({queryKey:["customer-conversion-requirements",customerType],queryFn:({signal})=>getCustomerKycRequirements(customerType,signal),enabled:typeChanged,retry:false});
  const conversionReady = !typeChanged || Boolean(requirements.data && conversionComplete(customer,requirements.data,conversionDocuments));
  const [priority,setPriority]=useState(customer.priorityCode || "");
  const options=useQuery({queryKey:["logistics","options",merchantId],queryFn:({signal})=>getLogisticsOptions({merchant:auth?.channel==="merchant",merchantId},signal),retry:false});
  const [name, setName] = useState(customer.businessName || customer.ownerName || "");
  const [owner, setOwner] = useState(customer.ownerName || ""); const [email, setEmail] = useState(customer.email || "");
  const [address, setAddress] = useState(customer.deliveryAddress); const [addressChanged, setAddressChanged] = useState(false);
  const [reason, setReason] = useState("");
  const save = useMutation({ mutationFn: async () => {
    if (!conversionReady) throw new Error("Complete the required registration details and documents.");
    const documents: CustomerCreateInput["documents"] = [];
    if (typeChanged && requirements.data) {
      for (const rule of requirements.data.documents) {
        const draft = conversionDocuments[rule.type];
        if (!draft?.replace || !draft.number.trim()) continue;
        let fileId = draft.fileId;
        if (!fileId && draft.file) {
          fileId = (await uploadDocument(merchantId, draft.file, rule.type as KycDocumentType)).fileId;
          setConversionDocuments(previous=>({...previous,[rule.type]:{...draft,fileId}}));
        }
        documents.push({type:rule.type as KycDocumentType,number:draft.number.trim(),fileId});
      }
    }
    const body = {
      ...(typeChanged ? {customerType,documents,sites:requirements.data?.requiresDeliverySites ? [{name:siteName.trim(),address:{...address,latitude:null,longitude:null},isPrimary:true}] : []} : {}),
      ...(priority!==(customer.priorityCode || "") ? {priorityCode:priority || null} : {}),
      businessName:name.trim(),ownerName:owner.trim() || null,email:email.trim() || null,
      ...(addressChanged || typeChanged ? {deliveryAddress:{...address,latitude:null,longitude:null}} : {}),reason:reason.trim()
    };
    return branchOwnerId ? updateCustomerBranch(merchantId,branchOwnerId,customer.id,{...body,mobile,permissions}) : updateCustomer(merchantId,customer.id,body);
  },onSuccess:()=>{onSaved();onClose();} });
  return <Modal open wide title={branchOwnerId ? "Edit branch" : "Edit customer"} onClose={onClose} busy={save.isPending}><form className="stack" onSubmit={e => { e.preventDefault(); if (reason.trim().length >= 3 && conversionReady) save.mutate(); }}>
    <p className="meta">Update customer type, contact and delivery address details. Existing orders, invoices, KYC and credit history remain intact.</p>
    <Field label="Customer type" hint="Changing type requires completing the target registration details and KYC."><Select value={customerType} options={[{value:"RETAIL",label:"Retail"},{value:"INDUSTRIAL",label:"Industrial"}]} onChange={e=>setCustomerType(e.target.value as CustomerType)}/></Field>
    <div className="form-grid"><Field label="Business / customer name"><Input required maxLength={160} value={name} onChange={e => setName(e.target.value)} /></Field><Field label="Owner name" required={typeChanged}><Input required={typeChanged} maxLength={160} value={owner} onChange={e => setOwner(e.target.value)} /></Field><Field label="Email"><Input type="email" maxLength={255} value={email} onChange={e => setEmail(e.target.value)} /></Field>
    {([['line1','Address line 1'],['line2','Address line 2'],['city','City'],['state','State'],['pincode','Pincode']] as const).map(([key,label]) => <Field label={label} key={key}><Input required={(addressChanged || typeChanged) && key !== 'line2'} value={address?.[key] || ""} maxLength={key === 'pincode' ? 6 : key === 'city' || key === 'state' ? 120 : 255} pattern={key === 'pincode' ? '[1-9][0-9]{5}' : undefined} onChange={e => { setAddress({ ...address, [key]: e.target.value }); setAddressChanged(true); }} /></Field>)}</div>
    {typeChanged ? <>
      {requirements.isLoading ? <p role="status">Loading required registration documents…</p> : null}
      {requirements.isError ? <Alert tone="error">Required documents could not be loaded. Retry before saving.<Button variant="secondary" onClick={()=>void requirements.refetch()}>Retry requirements</Button></Alert> : null}
      {requirements.data ? <><ConversionKycFields customer={customer} requirements={requirements.data} drafts={conversionDocuments} onChange={(type,value)=>setConversionDocuments(previous=>({...previous,[type]:value}))}/>{requirements.data.requiresDeliverySites ? <Field label="Primary delivery site name" required hint="This site uses the delivery address above."><Input required minLength={2} value={siteName} onChange={e=>setSiteName(e.target.value)}/></Field> : null}</> : null}
    </> : null}
    {branchOwnerId ? <><Field label="Branch phone number" hint="The new number becomes this branch’s OTP login. Existing branch sessions are revoked."><Input required inputMode="tel" maxLength={10} pattern="[6-9][0-9]{9}" value={mobile} onChange={e=>setMobile(e.target.value.replace(/\D/g, ""))}/></Field><Field label="Branch permissions"><div className="hierarchy-checks">{permissionCatalog.map(permission=><label key={permission}><input type="checkbox" checked={permissions.includes(permission)} onChange={e=>setPermissions(e.target.checked ? [...permissions,permission] : permissions.filter(p=>p!==permission))}/><span>{permissionLabels[permission] || permission}</span></label>)}</div></Field></> : null}
    <Field label="Customer priority" hint="New orders inherit this priority. Existing orders retain their saved priority."><Select value={priority} placeholder={options.data?`Use default (${options.data.policy.priorities.find(p=>p.code===options.data!.policy.defaultPriority)?.label || options.data.policy.defaultPriority})`:"Loading priorities…"} disabled={!options.data} options={(options.data?.policy.priorities || []).map(p=>({value:p.code,label:p.label}))} onChange={e=>setPriority(e.target.value)}/></Field>
    <Field label="Reason for change"><Textarea required minLength={3} maxLength={255} value={reason} onChange={e => setReason(e.target.value)} /></Field>
    {save.isError ? <Alert tone="error">{normalizeError(save.error).userMessage}</Alert> : null}
    <Button type="submit" disabled={!name.trim() || reason.trim().length < 3 || !conversionReady} loading={save.isPending}>Save customer changes</Button>
  </form></Modal>;
}
