import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {render,screen} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {MemoryRouter} from "react-router-dom";
import {beforeEach,it,expect,vi} from "vitest";
import {apiClient} from "../../api/client";
import {CustomerAccessPanel} from "./CustomerAccessPanel";
vi.mock("../../api/client",()=>({apiClient:{get:vi.fn(),post:vi.fn(),patch:vi.fn(),delete:vi.fn()}}));
vi.mock("./AddCustomerDialog",()=>({AddCustomerDialog:({branchOwnerId}:{branchOwnerId:string})=><p>New branch for {branchOwnerId}</p>}));
const hierarchy={brand:{id:"b1",name:"Owner"},owner:{id:"c1",name:"Owner",code:"R1",mobile:"9876543210",status:"APPROVED"},branches:[{id:"b2",name:"Delhi branch",code:"B2",mobile:"9123456789",status:"APPROVED",permissions:["orders.view"]}],isOwner:true,accountKind:"OWNER",canCreateBranches:true,permissionCatalog:["orders.view"]};
beforeEach(()=>{vi.clearAllMocks();vi.mocked(apiClient.get).mockResolvedValue({data:hierarchy});});
function mount(manage=true){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><CustomerAccessPanel merchant={false} merchantId="m1" customerId="c1" customerName="Owner" canManage={manage} canCreate={manage} canDelete={manage}/></MemoryRouter></QueryClientProvider>);}
it("shows direct branch actions and never invitations, roles or manage login",async()=>{
 mount();const user=userEvent.setup();await user.click(await screen.findByRole("button",{name:"View branches (1)"}));
 expect(screen.getByRole("button",{name:"Create branch"})).toBeEnabled();
 expect(screen.getByRole("button",{name:"Edit branch"})).toBeEnabled();
 expect(screen.getByRole("button",{name:"Delete branch"})).toBeEnabled();
 expect(screen.queryByText(/additional users|manage login|create invitation/i)).not.toBeInTheDocument();
 expect(apiClient.get).toHaveBeenCalledTimes(1);
 await user.click(screen.getByRole("button",{name:"Create branch"}));
 expect(screen.getByText("New branch for c1")).toBeInTheDocument();
});
it("child shows its owner and no branch-create or management option",async()=>{
 vi.mocked(apiClient.get).mockResolvedValue({data:{...hierarchy,accountKind:"BRANCH",isOwner:false,canCreateBranches:false,branches:[]}});
 mount();expect(await screen.findByText("Branch account")).toBeInTheDocument();
 expect(screen.getByRole("link",{name:"Owner"})).toBeInTheDocument();
 expect(screen.queryByRole("button",{name:/create branch|edit branch|delete branch|view branches/i})).not.toBeInTheDocument();
 expect(screen.queryByText(/manage login|additional users/i)).not.toBeInTheDocument();
});
it("read-only staff see branch account links without mutation controls",async()=>{
 mount(false);await userEvent.click(await screen.findByRole("button",{name:"View branches (1)"}));
 expect(screen.getByRole("link",{name:"Open branch"})).toBeInTheDocument();
 expect(screen.queryByRole("button",{name:/create branch|edit branch|delete branch/i})).not.toBeInTheDocument();
});
