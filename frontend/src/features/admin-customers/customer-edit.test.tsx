import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { EditCustomerDialog } from "./EditCustomerDialog";
import { getCustomerKycRequirements, uploadDocument, updateCustomer, updateCustomerBranch, type Customer } from "../../api/customers.api";
vi.mock("../../api/customers.api",async(original)=>({...await original<typeof import("../../api/customers.api")>(),getCustomerKycRequirements:vi.fn(),uploadDocument:vi.fn(),updateCustomer:vi.fn(),updateCustomerBranch:vi.fn()}));
vi.mock("../../api/logistics.api",()=>({getLogisticsOptions:vi.fn().mockResolvedValue({policy:{priorities:[],defaultPriority:"MEDIUM"}})}));
beforeEach(()=>{vi.clearAllMocks();vi.mocked(updateCustomer).mockResolvedValue({} as Customer);vi.mocked(uploadDocument).mockResolvedValue({fileId:"new-file",fileName:"proof.pdf",contentType:"application/pdf",size:100});vi.mocked(getCustomerKycRequirements).mockImplementation(async type=>({customerType:type,minimumDocuments:type==="INDUSTRIAL"?2:1,requiresDeliverySites:type==="INDUSTRIAL",documents:(type==="INDUSTRIAL"?["GST","PAN"]:["AADHAAR"]).map(code=>({type:code,label:code,required:true,numberFormat:"Valid registration number"}))}));});
it.each([["RETAIL","INDUSTRIAL"],["INDUSTRIAL","RETAIL"]] as const)("saves customer conversion from %s to %s",async(from,to)=>{
 const saved=vi.fn(); const close=vi.fn();
 render(<QueryClientProvider client={new QueryClient()}><EditCustomerDialog customer={{id:"c1",mobile:"9123456789",accountStatus:"APPROVED",kycStatus:"VERIFIED",pricingTier:"STANDARD",runningBalance:0,customerType:from,businessName:"Bakery",ownerName:"Owner",documents:["AADHAAR","PAN","GST"].map(type=>({type,numberMasked:"MASKED",fileId:type,fileName:type+".pdf",status:"VERIFIED"})),deliveryAddress:{line1:"Street",city:"Delhi",state:"Delhi",pincode:"110001"}} as Customer} merchantId="m1" onSaved={saved} onClose={close}/></QueryClientProvider>);
 const user=userEvent.setup();
 await user.selectOptions(screen.getByLabelText("Customer type"),to);
 await user.type(screen.getByLabelText("Reason for change"),"Correct classification");
 await user.click(screen.getByRole("button",{name:"Save customer changes"}));
 await waitFor(()=>expect(updateCustomer).toHaveBeenCalledWith("m1","c1",expect.objectContaining({customerType:to,reason:"Correct classification"})));
 expect(saved).toHaveBeenCalledOnce();expect(close).toHaveBeenCalledOnce();
});

it("updates a branch phone and permissions directly without invitations or roles",async()=>{
 vi.mocked(updateCustomerBranch).mockResolvedValue({} as Customer);
 render(<QueryClientProvider client={new QueryClient()}><EditCustomerDialog customer={{id:"b1",customerType:"RETAIL",businessName:"Delhi Branch",mobile:"9123456789",branchPermissions:["profile.view","orders.view"],deliveryAddress:{}} as Customer} merchantId="m1" branchOwnerId="owner" onSaved={vi.fn()} onClose={vi.fn()}/></QueryClientProvider>);
 const user=userEvent.setup();
 await user.clear(screen.getByLabelText("Branch phone number"));
 await user.type(screen.getByLabelText("Branch phone number"),"9988776655");
 await user.click(screen.getByRole("checkbox",{name:"Place orders"}));
 await user.type(screen.getByLabelText("Reason for change"),"Updated branch phone and permissions");
 await user.click(screen.getByRole("button",{name:"Save customer changes"}));
 await waitFor(()=>expect(updateCustomerBranch).toHaveBeenCalledWith("m1","owner","b1",expect.objectContaining({mobile:"9988776655",permissions:["profile.view","orders.view","orders.create"]})));
 expect(updateCustomer).not.toHaveBeenCalled();
 expect(screen.queryByText(/invitation|manage login|additional user/i)).not.toBeInTheDocument();
});

it("blocks type conversion until missing required numbers and documents are supplied",async()=>{
 render(<QueryClientProvider client={new QueryClient()}><EditCustomerDialog customer={{id:"c1",mobile:"9123456789",accountStatus:"APPROVED",kycStatus:"VERIFIED",pricingTier:"STANDARD",runningBalance:0,customerType:"RETAIL",businessName:"Bakery",ownerName:"Owner",documents:[],deliveryAddress:{line1:"Street",city:"Delhi",state:"Delhi",pincode:"110001"}} as Customer} merchantId="m1" onSaved={vi.fn()} onClose={vi.fn()}/></QueryClientProvider>);
 const user=userEvent.setup();await user.selectOptions(screen.getByLabelText("Customer type"),"INDUSTRIAL");
 await screen.findByLabelText(/GST number/i);
 await user.type(screen.getByLabelText("Reason for change"),"Convert to industrial");
 expect(screen.getByRole("button",{name:"Save customer changes"})).toBeDisabled();
 await user.type(screen.getByLabelText(/GST number/i),"23ABCDE1234F1Z5");
 await user.upload(screen.getByLabelText(/GST document/i),new File(["%PDF-test"],"gst.pdf",{type:"application/pdf"}));
 expect(screen.getByRole("button",{name:"Save customer changes"})).toBeDisabled();
 await user.type(screen.getByLabelText(/PAN number/i),"ABCDE1234F");
 await user.upload(screen.getByLabelText(/PAN document/i),new File(["%PDF-test"],"pan.pdf",{type:"application/pdf"}));
 expect(Array.from(document.querySelectorAll("input:invalid,select:invalid,textarea:invalid")).map(element=>({id:element.id,type:(element as HTMLInputElement).type,value:(element as HTMLInputElement).value}))).toEqual([]);
 await user.click(screen.getByRole("button",{name:"Save customer changes"}));
 await waitFor(()=>expect(updateCustomer).toHaveBeenCalledWith("m1","c1",expect.objectContaining({customerType:"INDUSTRIAL",documents:[{type:"GST",number:"23ABCDE1234F1Z5",fileId:"new-file"},{type:"PAN",number:"ABCDE1234F",fileId:"new-file"}],sites:[expect.objectContaining({name:"Primary site",isPrimary:true})]})));
}, 15000);
