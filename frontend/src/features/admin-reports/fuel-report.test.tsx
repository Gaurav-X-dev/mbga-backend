import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { AdminReportsPage } from "./AdminReportsPage";
import { getReport, exportReport, type Report } from "../../api/reports.api";

vi.mock("../../auth/auth-context",async (original) => ({...await original<typeof import("../../auth/auth-context")>(),useOptionalAuth:()=>null}));
vi.mock("../../api/reports.api",async(original)=>({...await original<typeof import("../../api/reports.api")>(),getReport:vi.fn(),exportReport:vi.fn()}));
vi.mock("../../api/merchants.api",()=>({listMerchants:vi.fn().mockResolvedValue({items:[{id:"m1",business_name:"Agency"}],total:1})}));
vi.mock("../../api/customers.api",async(original)=>({...await original<typeof import("../../api/customers.api")>(),listCustomers:vi.fn().mockResolvedValue({items:[],total:0})}));
const result:Report={type:"FUEL",title:"Fuel Sheet Report",period:{from:"2026-10-01",to:"2026-10-31"},generatedAt:"2026-10-28T00:00:00Z",summary:[{label:"Average (km/L)",value:15}],columns:[{key:"date",label:"Date"},{key:"kmReading",label:"KM Reading"},{key:"liters",label:"Fuel (L)"},{key:"mileage",label:"Avg. (km/L)"},{key:"destination",label:"Destination"}],rows:[{id:"e1",date:"2026-10-01",kmReading:15000,liters:10,mileage:15,destination:"Indore"}],metadata:{fuelOptions:{fuelTypes:[{value:"DIESEL",label:"Diesel"},{value:"BIOFUEL",label:"Custom biofuel"}],vehicles:[{value:"v1",label:"MP09AB1234"}],drivers:[{value:"d1",label:"Driver One"}],recorders:[{value:"staff",label:"Manager"}]}}};
beforeEach(()=>{vi.clearAllMocks();vi.mocked(getReport).mockResolvedValue(result);vi.mocked(exportReport).mockResolvedValue("fuel.csv");});

describe("Fuel Sheet report",()=>{
 it("shows the sheet columns and keeps export filters identical to the screen",async()=>{
  const user=userEvent.setup();renderWithProviders(<AdminReportsPage merchantId="m1"/>,"/admin/reports?type=FUEL&vehicleId=v1&driverId=d1&fuelType=DIESEL&minMileage=10&hasReceipt=true");
  await screen.findByRole("heading",{name:/Fuel Sheet Report/});
  expect(screen.getByRole("columnheader",{name:/KM Reading/})).toBeInTheDocument();
  expect(screen.getByRole("columnheader",{name:/Destination/})).toBeInTheDocument();
  expect(screen.getByRole("option",{name:"Custom biofuel"})).toBeInTheDocument();
  expect(getReport).toHaveBeenCalledWith(expect.objectContaining({type:"FUEL",allTime:true,from:undefined,to:undefined,vehicleId:"v1",driverId:"d1",fuelType:"DIESEL",minMileage:"10",hasReceipt:"true"}),expect.anything());
  await user.selectOptions(screen.getByLabelText("Export format"),"CSV");
  await user.click(screen.getByRole("button",{name:"Export"}));
  await waitFor(()=>expect(exportReport).toHaveBeenCalledWith(expect.objectContaining({type:"FUEL",vehicleId:"v1",driverId:"d1",minMileage:"10",hasReceipt:"true"}),"CSV"));
 });
 it("offers filtering controls and clears fuel filters without changing the report",async()=>{
  const user=userEvent.setup();renderWithProviders(<AdminReportsPage merchantId="m1"/>,"/admin/reports?type=FUEL&destination=Indore&minAmount=500");
  await screen.findByRole("heading",{name:/Fuel Sheet Report/});
  expect(screen.getByLabelText("Destination")).toHaveValue("Indore");
  expect(screen.getByLabelText("Minimum Amount (₹)")).toHaveValue(500);
  await user.click(screen.getByRole("button",{name:"Clear fuel filters"}));
  await waitFor(()=>expect(getReport).toHaveBeenLastCalledWith(expect.objectContaining({type:"FUEL",destination:undefined,minAmount:undefined}),expect.anything()));
 });
});
