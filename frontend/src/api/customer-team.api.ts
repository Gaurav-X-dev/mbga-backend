import { apiClient } from "./client";
export type TeamPermission = string;
export type TeamPreset = {code:string;label:string;permissions:TeamPermission[]};
export type TeamMember = {id:string;name:string;mobile:string;scopeType:"ALL"|"ACCOUNT";accountId:string|null;preset:string;permissions:TeamPermission[];status:string};
export type TeamInput = Omit<TeamMember,"id"|"status">;
export type TeamData = {items:TeamMember[];total:number;limit:number;offset:number;presets:TeamPreset[];permissionCatalog:TeamPermission[];accounts:Array<{id:string;name:string;code:string;status:string}>};
export type TeamScope = {ownerId:string;merchantId:string;merchant:boolean};
const root=(scope:TeamScope)=>`/${scope.merchant?"merchant":"admin"}/customer-access/customers/${encodeURIComponent(scope.ownerId)}/team`;
const params=(scope:TeamScope)=>scope.merchant?{}:{merchantId:scope.merchantId};
export async function listCustomerTeam(scope:TeamScope,offset=0,signal?:AbortSignal) {
 return (await apiClient.get<TeamData>(root(scope),{params:{...params(scope),limit:20,offset},signal})).data;
}
export async function saveCustomerTeam(scope:TeamScope,input:TeamInput,id?:string) {
 return (id?await apiClient.patch<TeamMember>(`${root(scope)}/${encodeURIComponent(id)}`,input,{params:params(scope)}):await apiClient.post<TeamMember>(root(scope),input,{params:params(scope)})).data;
}
export async function removeCustomerTeam(scope:TeamScope,id:string) {
 await apiClient.delete(`${root(scope)}/${encodeURIComponent(id)}`,{params:params(scope)});
}
