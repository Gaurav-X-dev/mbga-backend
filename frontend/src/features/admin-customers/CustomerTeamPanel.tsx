import { useState } from "react";
import { CUSTOMER_PERMISSION_LABELS as labels } from "../../api/customers.api";
import { useMutation,useQuery,useQueryClient } from "@tanstack/react-query";
import { listCustomerTeam,saveCustomerTeam,removeCustomerTeam,type TeamData,type TeamMember,type TeamInput,type TeamScope } from "../../api/customer-team.api";
import { normalizeError } from "../../api/errors";
import { Button } from "../../components/common/Button";
import { ConfirmationDialog,Modal } from "../../components/feedback/Dialogs";
import { Alert,ErrorState } from "../../components/feedback/Feedback";
import { Field,Input,Select } from "../../components/forms/Field";
import { Card } from "../../components/layout/Page";


export function CustomerTeamPanel({scope,canManage}:{scope:TeamScope;canManage:boolean}) {
 const client=useQueryClient();
 const [open,setOpen]=useState(false);const [offset,setOffset]=useState(0);
 const [editing,setEditing]=useState<TeamMember|"new"|null>(null);const [removing,setRemoving]=useState<TeamMember|null>(null);
 const query=useQuery({queryKey:["customer-team",scope.merchantId,scope.ownerId,offset],enabled:open,queryFn:({signal})=>listCustomerTeam(scope,offset,signal)});
 const refresh=async()=>{await client.invalidateQueries({queryKey:["customer-team",scope.merchantId,scope.ownerId]});};
 const data=query.data;
 return <Card title="Team">
  <p>Give each employee their own mobile login and access to the accounts they work on. Owner access stays unchanged.</p>
  <Button variant="secondary" onClick={()=>setOpen(!open)}>{open?"Hide team":"Manage team"}</Button>
  {open?<section className="stack" style={{marginTop:16}}>
   {query.isLoading?<p role="status">Loading team…</p>:null}
   {query.isError?<ErrorState error={query.error} onRetry={()=>void query.refetch()}/>:null}
   {data?<>
    {canManage?<Button onClick={()=>setEditing("new")}>Add team member</Button>:null}
    <div className="hierarchy-branches">{data.items.map(member=><article className="hierarchy-branch" key={member.id}>
     <h4>{member.name}</h4><p>{member.mobile}</p><p>{data.presets.find(p=>p.code===member.preset)?.label || "Custom permissions"} · {member.scopeType==="ALL"?"Owner account and all branches":data.accounts.find(a=>a.id===member.accountId)?.name || "Account no longer linked"}</p>
     <p className="meta">{member.permissions.map(code=>labels[code]||code).join(" · ")}</p>
     {canManage?<div className="hierarchy-actions"><Button variant="secondary" onClick={()=>setEditing(member)}>Edit access</Button><Button variant="danger" onClick={()=>setRemoving(member)}>Remove access</Button></div>:null}
    </article>)}</div>
    {!data.items.length?<p>No team members yet. Primary owner and branch logins work without adding them here.</p>:null}
    {data.total>20?<div className="hierarchy-actions"><Button variant="secondary" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-20))}>Previous team members</Button><span>{offset+1}–{Math.min(offset+20,data.total)} of {data.total}</span><Button variant="secondary" disabled={offset+20>=data.total} onClick={()=>setOffset(offset+20)}>Next team members</Button></div>:null}
   </>:null}
  </section>:null}
  {editing&&data?<TeamEditor scope={scope} data={data} member={editing==="new"?undefined:editing} onClose={()=>setEditing(null)} onSaved={async()=>{setEditing(null);await refresh();}}/>:null}
  <ConfirmationDialog open={Boolean(removing)} title="Remove this person's access?" description={`${removing?.name||"This person"} will lose this Team entry's access immediately. Other account grants, if any, stay separate.`} confirmLabel="Remove access" confirmVariant="danger" onClose={()=>setRemoving(null)} onConfirm={async()=>{await removeCustomerTeam(scope,removing!.id);setRemoving(null);await refresh();}}/>
 </Card>;
}
function TeamEditor({scope,data,member,onClose,onSaved}:{scope:TeamScope;data:TeamData;member?:TeamMember;onClose:()=>void;onSaved:()=>Promise<void>}) {
 const initial=data.presets.find(p=>p.code==="VIEW_ONLY")||data.presets[0];
 const [name,setName]=useState(member?.name||"");const [mobile,setMobile]=useState((member?.mobile||"").replace(/^\+91/,""));
 const [scopeType,setScopeType]=useState<"ALL"|"ACCOUNT">(member?.scopeType||"ACCOUNT");
 const [accountId,setAccountId]=useState(member?.accountId||scope.ownerId);
 const [preset,setPreset]=useState(member?.preset||initial.code);
 const [permissions,setPermissions]=useState(member?.permissions||initial.permissions);
 const mutation=useMutation({mutationFn:()=>saveCustomerTeam(scope,{name:name.trim(),mobile,scopeType,accountId:scopeType==="ACCOUNT"?accountId:null,preset,permissions} as TeamInput,member?.id),onSuccess:onSaved});
 const valid=name.trim().length>=2&&/^[6-9][0-9]{9}$/.test(mobile)&&permissions.length>0&&(scopeType==="ALL"||Boolean(accountId));
 return <Modal open wide title={member?"Edit team access":"Add team member"} busy={mutation.isPending} onClose={onClose}>
  <form className="stack" onSubmit={event=>{event.preventDefault();if(valid)mutation.mutate();}}>
   <Field label="Employee name" required><Input required maxLength={160} value={name} onChange={e=>setName(e.target.value)}/></Field>
   <Field label="Employee mobile" required hint="They sign in with their own OTP. No invitation acceptance is needed."><Input required inputMode="tel" maxLength={10} pattern="[6-9][0-9]{9}" value={mobile} onChange={e=>setMobile(e.target.value.replace(/\D/g,""))}/></Field>
   <Field label="Account access"><Select value={scopeType} options={[{value:"ACCOUNT",label:"Only the selected account"},{value:"ALL",label:"Owner account and all branches"}]} onChange={e=>setScopeType(e.target.value as "ALL"|"ACCOUNT")}/></Field>
   {scopeType==="ACCOUNT"?<Field label="Account" required><Select value={accountId} options={data.accounts.map(a=>({value:a.id,label:`${a.name} · ${a.code}`}))} onChange={e=>setAccountId(e.target.value)}/></Field>:null}
   <Field label="Access preset"><Select value={preset} options={[...data.presets.map(p=>({value:p.code,label:p.label})),{value:"CUSTOM",label:"Custom permissions"}]} onChange={e=>{setPreset(e.target.value);const selected=data.presets.find(p=>p.code===e.target.value);if(selected)setPermissions(selected.permissions);}}/></Field>
   <Field label="Permissions"><div className="hierarchy-checks">{data.permissionCatalog.map(code=><label key={code}><input type="checkbox" checked={permissions.includes(code)} onChange={e=>{setPermissions(e.target.checked?[...permissions,code]:permissions.filter(p=>p!==code));setPreset("CUSTOM");}}/><span>{labels[code]||code}</span></label>)}</div></Field>
   <Alert tone="info">Employees cannot create branches or manage the Team. Each account keeps its own balance and transaction history.</Alert>
   {mutation.isError?<Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert>:null}
   <Button type="submit" disabled={!valid} loading={mutation.isPending}>Save team access</Button>
  </form>
 </Modal>;
}
