import { useState } from "react";
import { useOptionalAuth } from "../../auth/auth-context";
import { getLogisticsOptions } from "../../api/logistics.api";
import { useMutation, useQuery } from "@tanstack/react-query";
import { editOrder, type Order } from "../../api/orders.api";
import { normalizeError } from "../../api/errors";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { formatCurrency, todayInputValue } from "../../utils/format";

export function EditOrderDialog({ order, merchantId, onClose, onSaved }: { order: Order; merchantId: string; onClose: () => void; onSaved: () => void }) {
 const auth=useOptionalAuth();
 const options=useQuery({queryKey:["logistics","options",merchantId],queryFn:({signal})=>getLogisticsOptions({merchant:auth?.channel==="merchant",merchantId},signal),retry:false});
 const [priority,setPriority]=useState(order.priorityCode || "");
 const [quantities,setQuantities]=useState<Record<string,number>>(Object.fromEntries((order.items || []).map(i=>[i.cylinderType,i.quantity])));
 const [date,setDate]=useState(order.cutoff.scheduledDeliveryDate); const [reason,setReason]=useState("");
 const items=(order.items || []).filter(i=>(quantities[i.cylinderType] || 0)>0).map(i=>({cylinderType:i.cylinderType,quantity:quantities[i.cylinderType]}));
 const total=(order.items || []).reduce((sum,i)=>sum+i.unitPrice*(quantities[i.cylinderType] || 0),0);
 const itemsChanged=(order.items || []).some(i=>quantities[i.cylinderType]!==i.quantity);
 const dateChanged=date!==order.cutoff.scheduledDeliveryDate;
 const priorityChanged=priority!==order.priorityCode && Boolean(priority);
 const valid=(itemsChanged || dateChanged || priorityChanged) && items.length>0 && Object.values(quantities).every(q=>Number.isInteger(q)&&q>=0) && reason.trim().length>=3 && date>=todayInputValue();
 const save=useMutation({ mutationFn:()=>editOrder(merchantId,order.id,{...(priorityChanged ? {priorityCode:priority} : {}),...(itemsChanged ? {items} : {}),...(dateChanged ? {deliveryDate:date} : {}),reason:reason.trim(),expectedVersion:order.editVersion!}),onSuccess:()=>{onSaved();onClose();} });
 return <Modal open title="Edit order / reschedule" onClose={onClose} busy={save.isPending}><form className="stack" onSubmit={e=>{e.preventDefault();if(valid)save.mutate();}}><p className="meta">Change booked cylinder quantities or delivery date before dispatch. Original unit rates are retained. Set quantity to zero to remove a line; keep at least one line.</p>
 {(order.items || []).map(i=><Field key={i.cylinderType} label={`${i.cylinderLabel || i.cylinderType} · ${formatCurrency(i.unitPrice)} each`}><Input type="number" min={0} step={1} required value={quantities[i.cylinderType]} onChange={e=>setQuantities({...quantities,[i.cylinderType]:Number(e.target.value)})}/></Field>)}
 <Field label="Order priority override" hint="Changes this order only; the customer’s default stays unchanged."><Select disabled={!options.data} value={priority} placeholder="Select priority" options={(options.data?.policy.priorities || []).map(p=>({value:p.code,label:p.label}))} onChange={e=>setPriority(e.target.value)}/></Field>
 <Field label="Delivery date"><Input type="date" required min={todayInputValue()} value={date} onChange={e=>setDate(e.target.value)}/></Field><p><strong>Revised order total: {formatCurrency(total)}</strong></p><p className="meta">Advance reservations and credit eligibility are checked by the server. Assignment availability is checked again when rescheduling.</p>
 <Field label="Reason for change"><Textarea required minLength={3} maxLength={255} value={reason} onChange={e=>setReason(e.target.value)}/></Field>{save.isError?<Alert tone="error">{normalizeError(save.error).userMessage}</Alert>:null}<Button type="submit" loading={save.isPending} disabled={!valid}>Confirm order changes</Button></form></Modal>;
}
