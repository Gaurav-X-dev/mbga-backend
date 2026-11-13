import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { AdminExpensesPage } from "./AdminExpensesPage";
import * as api from "../../api/expenses.api";
import { expenseMonth, expenseToday, fuelMileage } from "./expense-utils";

vi.mock("../../auth/auth-context", async (original) => ({...await original<typeof import("../../auth/auth-context")>(), useOptionalAuth: () => null}));
vi.mock("../../api/expenses.api", async (original) => ({
  ...await original<typeof api>(), listExpenses:vi.fn(),listExpensePeriods:vi.fn(),listExpenseCategories:vi.fn(),getExpenseBreakdown:vi.fn(),getExpenseFuelOptions:vi.fn(),createExpense:vi.fn(),updateExpense:vi.fn(),uploadExpenseReceipt:vi.fn()
}));
vi.mock("../../api/merchants.api", () => ({listMerchants:vi.fn().mockResolvedValue({items:[{id:"m1",business_name:"Agency"}],total:1})}));
const categories = [
  {id:"fuel",code:"FUEL",label:"Fuel",icon:"fuel",isActive:true,isCustom:false,sortOrder:0},
  {id:"rent",code:"RENT",label:"Rent",icon:"rent",isActive:true,isCustom:false,sortOrder:1}
];
const expense = {id:"e1",category:categories[0],amount:1000,date:expenseToday(),period:expenseMonth(),periodLabel:"Month",recordedBy:"Manager",createdAt:new Date().toISOString(),updatedAt:new Date().toISOString()};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listExpenseCategories).mockResolvedValue(categories);
  vi.mocked(api.listExpensePeriods).mockResolvedValue([]);
  vi.mocked(api.listExpenses).mockResolvedValue({items:[],total:0,page:1,pageSize:20,summary:{totalAmount:0,entryCount:0}});
  vi.mocked(api.getExpenseBreakdown).mockResolvedValue({totalAmount:1000,entryCount:1,categories:[]});
  vi.mocked(api.getExpenseFuelOptions).mockResolvedValue({vehicles:[{value:"v1",label:"MP09AB1234"}],drivers:[{value:"d1",label:"Driver One"}],fuelTypes:[{value:"DIESEL",label:"Diesel"},{value:"BIOFUEL",label:"Custom biofuel"}]});
  vi.mocked(api.createExpense).mockResolvedValue(expense);
  vi.mocked(api.updateExpense).mockResolvedValue(expense);
  vi.mocked(api.uploadExpenseReceipt).mockResolvedValue(undefined);
});

async function openNew(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("option",{name:"Fuel"});
  await user.click(screen.getAllByRole("button",{name:"Add expense"})[0]);
  await user.selectOptions(screen.getAllByLabelText(/^Category/).slice(-1)[0],"fuel");
  await screen.findByRole("option",{name:"Driver One"});
}

describe("expense form and dashboard", () => {
  it("calculates Indian month boundaries and mileage without infinity", () => {
    const now=new Date("2026-12-31T19:00:00Z");
    expect(expenseToday(now)).toBe("2027-01-01");
    expect(expenseMonth(-1,now)).toBe("2026-12");
    expect(fuelMileage("150","10")).toBe(15);
    expect(fuelMileage("150","0")).toBeNull();
  });
  it("expands Fuel, calculates live mileage and uploads the receipt after saving",async () => {
    const user=userEvent.setup();renderWithProviders(<AdminExpensesPage merchantId="m1" />,"/admin/expenses");
    await openNew(user);
    await user.type(screen.getByLabelText(/Amount/),"1000");
    await user.selectOptions(screen.getByLabelText(/^Vehicle/),"v1");
    await user.selectOptions(screen.getByLabelText(/^Driver/),"d1");
    await user.selectOptions(screen.getByLabelText(/^Fuel type/),"DIESEL");
    await user.type(screen.getByLabelText(/Starting odometer/),"14850");
    await user.type(screen.getByLabelText(/Ending odometer/),"15000");
    await user.type(screen.getByLabelText(/Fuel consumed/),"10");
    expect(screen.getByText(/Distance: 150.00 km · Mileage: 15.00 km\/L/)).toBeInTheDocument();
    await user.upload(screen.getByLabelText(/^Receipt/),new File(["image"],"bill.png",{type:"image/png"}));
    await user.click(screen.getAllByRole("button",{name:"Add expense"}).slice(-1)[0]);
    await waitFor(() => expect(api.uploadExpenseReceipt).toHaveBeenCalledWith("m1","e1",expect.any(File)));
    expect(api.createExpense).toHaveBeenCalledWith("m1",expect.objectContaining({vehicleId:"v1",driverId:"d1",startOdometer:14850,endOdometer:15000,liters:10,fuelType:"DIESEL"}));
  });
  it("keeps non-fuel expense payloads unchanged",async () => {
    const user=userEvent.setup();renderWithProviders(<AdminExpensesPage merchantId="m1" />,"/admin/expenses");
    await openNew(user);
    await user.selectOptions(screen.getAllByLabelText(/^Category/).slice(-1)[0],"rent");
    expect(screen.queryByLabelText(/Fuel consumed/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/Amount/),"2000");
    await user.click(screen.getAllByRole("button",{name:"Add expense"}).slice(-1)[0]);
    await waitFor(() => expect(api.createExpense).toHaveBeenCalledWith("m1",{categoryId:"rent",amount:2000,date:expenseToday(),note:undefined}));
  });
  it("allows legacy Fuel expenses to be edited without adding telemetry",async () => {
    vi.mocked(api.listExpenses).mockResolvedValue({items:[expense],total:1,page:1,pageSize:20,summary:{totalAmount:1000,entryCount:1}});
    const user=userEvent.setup();renderWithProviders(<AdminExpensesPage merchantId="m1" />,"/admin/expenses");
    await screen.findAllByRole("button",{name:"Fuel"});
    await user.click(screen.getAllByRole("button",{name:"Fuel"})[0]);
    expect(screen.queryByLabelText(/Fuel consumed/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button",{name:"Save changes"}));
    await waitFor(() => expect(api.updateExpense).toHaveBeenCalledWith("m1","e1",expect.not.objectContaining({vehicleId:expect.anything()})));
  });
  it("passes custom dates to both the list and category breakdown",async () => {
    const user=userEvent.setup();renderWithProviders(<AdminExpensesPage merchantId="m1" />,"/admin/expenses?period=CUSTOM&from=2026-01-01&to=2026-01-31");
    await waitFor(() => expect(api.listExpenses).toHaveBeenCalledWith(expect.objectContaining({period:"ALL",from:"2026-01-01",to:"2026-01-31"}),expect.anything()));
    expect(api.getExpenseBreakdown).toHaveBeenCalledWith("m1","ALL",expect.anything(),{from:"2026-01-01",to:"2026-01-31"});
    await user.selectOptions(screen.getByLabelText("Period"),"LAST");
    await waitFor(() => expect(api.listExpenses).toHaveBeenLastCalledWith(expect.objectContaining({period:expenseMonth(-1)}),expect.anything()));
  });
  it("retries a failed receipt upload without creating a duplicate expense",async () => {
    vi.mocked(api.uploadExpenseReceipt).mockRejectedValueOnce(new Error("Upload failed"));
    const user=userEvent.setup();renderWithProviders(<AdminExpensesPage merchantId="m1" />,"/admin/expenses");
    await openNew(user);
    await user.selectOptions(screen.getAllByLabelText(/^Category/).slice(-1)[0],"rent");
    await user.type(screen.getByLabelText(/Amount/),"2000");
    await user.upload(screen.getByLabelText(/^Receipt/),new File(["image"],"bill.png",{type:"image/png"}));
    await user.click(screen.getAllByRole("button",{name:"Add expense"}).slice(-1)[0]);
    await screen.findByText("Expense saved. Retry to finish attaching the receipt.");
    await user.click(screen.getAllByRole("button",{name:"Add expense"}).slice(-1)[0]);
    await waitFor(() => expect(api.uploadExpenseReceipt).toHaveBeenCalledTimes(2));
    expect(api.createExpense).toHaveBeenCalledTimes(1);
    expect(api.updateExpense).toHaveBeenCalledWith("m1","e1",expect.anything());
  });

});
