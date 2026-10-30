import {screen,waitFor,within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {beforeEach,describe,it,expect,vi} from "vitest";
import {renderWithProviders} from "../../test/render";
import {AdminInventoryPage} from "./AdminInventoryPage";
import {getInventory,listStockMovements,updateReorderThreshold} from "../../api/inventory.api";
import {useOptionalAuth,type AuthContextValue} from "../../auth/auth-context";
vi.mock("../../auth/auth-context",async(original)=>({...await original<typeof import("../../auth/auth-context")>(),useOptionalAuth:vi.fn()}));
vi.mock("../../api/inventory.api",async(original)=>({...await original<typeof import("../../api/inventory.api")>(),getInventory:vi.fn(),listStockMovements:vi.fn(),updateReorderThreshold:vi.fn()}));
vi.mock("../../api/merchants.api",()=>({listMerchants:vi.fn().mockResolvedValue({items:[{id:"m1",business_name:"Agency"}],total:1})}));
let threshold=150;
beforeEach(()=>{
 vi.clearAllMocks();threshold=150;
 vi.mocked(useOptionalAuth).mockReturnValue({can:()=>true} as unknown as AuthContextValue);
 vi.mocked(getInventory).mockImplementation(async()=>({items:[{cylinderType:"LPG_5KG",cylinderLabel:"5 KG",filled:47,empty:2,damaged:0,reorderThreshold:threshold}],alerts:[],asOf:"2026-10-29T00:00:00Z"}));
 vi.mocked(listStockMovements).mockResolvedValue([]);
 vi.mocked(updateReorderThreshold).mockImplementation(async(_merchant,_type,value)=>{threshold=value;return {cylinderType:"LPG_5KG",cylinderLabel:"5 KG",filled:47,empty:2,damaged:0,reorderThreshold:value};});
});
describe("inventory reorder settings",()=>{
 it("opens the existing value and saves a new database setting",async()=>{
  const user=userEvent.setup();renderWithProviders(<AdminInventoryPage merchantId="m1"/>,"/admin/inventory");
  await user.click(await screen.findByRole("button",{name:"Edit reorder level for 5 KG"}));
  const input=screen.getByLabelText(/Reorder level \(filled cylinders\)/);
  expect(input).toHaveValue(150);
  await user.clear(input);await user.type(input,"75");
  await user.click(screen.getByRole("button",{name:"Save reorder level"}));
  await waitFor(()=>expect(updateReorderThreshold).toHaveBeenCalledWith("m1","LPG_5KG",75));
  expect(await screen.findByText("Reorder at 75 filled")).toBeInTheDocument();
 });
 it("allows zero and refreshes the health badge without changing quantities",async()=>{
  const user=userEvent.setup();renderWithProviders(<AdminInventoryPage merchantId="m1"/>,"/admin/inventory");
  await user.click(await screen.findByRole("button",{name:"Edit reorder level for 5 KG"}));
  const input=screen.getByLabelText(/Reorder level \(filled cylinders\)/);
  await user.clear(input);await user.type(input,"0");await user.click(screen.getByRole("button",{name:"Save reorder level"}));
  await screen.findByText("Reorder at 0 filled");
  const card=screen.getByRole("heading",{name:"5 KG"}).closest("section")!;
  expect(within(card).getByText("Healthy")).toBeInTheDocument();
  expect(within(card).getByText("47")).toBeInTheDocument();
 });
 it("hides edit controls without inventory adjustment permission",async()=>{
  vi.mocked(useOptionalAuth).mockReturnValue({can:()=>false} as unknown as AuthContextValue);
  renderWithProviders(<AdminInventoryPage merchantId="m1"/>,"/admin/inventory");
  await screen.findByText("Reorder at 150 filled");
  expect(screen.queryByRole("button",{name:/Edit reorder level/})).not.toBeInTheDocument();
 });
});
