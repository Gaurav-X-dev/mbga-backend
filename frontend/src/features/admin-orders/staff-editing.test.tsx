import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { EditOrderDialog } from "./EditOrderDialog";
import { EditCustomerDialog } from "../admin-customers/EditCustomerDialog";
import { editOrder, type Order } from "../../api/orders.api";
import { updateCustomer, type Customer } from "../../api/customers.api";
import { todayInputValue } from "../../utils/format";
vi.mock("../../api/orders.api", async original => ({ ...await original<typeof import("../../api/orders.api")>(), editOrder: vi.fn() }));
vi.mock("../../api/customers.api", async original => ({ ...await original<typeof import("../../api/customers.api")>(), updateCustomer: vi.fn() }));
function mount(content: React.ReactNode) { return render(<QueryClientProvider client={new QueryClient({defaultOptions:{mutations:{retry:false}}})}>{content}</QueryClientProvider>); }
it("previews quantity changes at booked rates and submits a versioned edit",async()=>{
 const user=userEvent.setup(); const saved=vi.fn();
 const order={id:"o1",items:[{cylinderType:"LPG_19KG",cylinderLabel:"19 kg",quantity:3,unitPrice:1000}],cutoff:{scheduledDeliveryDate:todayInputValue()},editVersion:"a".repeat(64)} as Order;
 mount(<EditOrderDialog order={order} merchantId="m1" onClose={()=>{}} onSaved={saved}/>);
 expect(screen.getByRole("button",{name:"Confirm order changes"})).toBeDisabled();
 const quantity=screen.getByRole("spinbutton"); await user.clear(quantity); await user.type(quantity,"2");
 await user.type(screen.getByLabelText("Reason for change"),"Customer needs two");
 await user.click(screen.getByRole("button",{name:"Confirm order changes"}));
 await waitFor(()=>expect(editOrder).toHaveBeenCalledWith("m1","o1",expect.objectContaining({items:[{cylinderType:"LPG_19KG",quantity:2}],expectedVersion:"a".repeat(64)})));
 expect(saved).toHaveBeenCalled();
});
it("edits customer contact details without changing login identity",async()=>{
 const user=userEvent.setup();
 const customer={id:"c1",customerType:"RETAIL",businessName:"Old Shop",ownerName:"Owner",email:null,mobile:"9876543210",deliveryAddress:{line1:"Plot 1",city:"Gurugram",state:"Haryana",pincode:"122001"}} as Customer;
 mount(<EditCustomerDialog customer={customer} merchantId="m1" onClose={()=>{}} onSaved={()=>{}}/>);
 const name=screen.getByLabelText("Business / customer name"); await user.clear(name); await user.type(name,"New Shop");
 await user.type(screen.getByLabelText("Reason for change"),"Correct business name");
 await user.click(screen.getByRole("button",{name:"Save customer changes"}));
 await waitFor(()=>expect(updateCustomer).toHaveBeenCalledWith("m1","c1",{businessName:"New Shop",ownerName:"Owner",email:null,reason:"Correct business name"}));
});
