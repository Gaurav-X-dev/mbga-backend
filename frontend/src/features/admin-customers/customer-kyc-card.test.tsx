import {screen} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {beforeEach,describe,it,expect,vi} from "vitest";
import {renderWithProviders} from "../../test/render";
import {CustomerKycDocumentsCard} from "./CustomerKycDocumentsCard";
import {revealDocumentNumber} from "../../api/customer-kyc.api";
import {useOptionalAuth} from "../../auth/auth-context";
import type {AuthContextValue} from "../../auth/auth-context";
import type {CustomerDocument} from "../../api/customers.api";

vi.mock("../../api/customer-kyc.api",async(original)=>({...await original<typeof import("../../api/customer-kyc.api")>(),revealDocumentNumber:vi.fn()}));
vi.mock("../../auth/auth-context",async(original)=>({...await original<typeof import("../../auth/auth-context")>(),useOptionalAuth:vi.fn(()=>null)}));
beforeEach(()=>{vi.clearAllMocks();vi.mocked(useOptionalAuth).mockReturnValue(null);});
const document:CustomerDocument={id:"doc-1",type:"AADHAAR",numberMasked:"XXXX XXXX 1234",fileName:"front.jpg",fileId:"front",uploadedAt:"2026-10-29T00:00:00Z",status:"VERIFIED",files:[{fileId:"front",fileName:"front.jpg",side:"FRONT"},{fileId:"back",fileName:"back.jpg",side:"BACK"}]};
describe("customer KYC documents card",()=>{
 it("keeps the document identity, status and both file actions visible",()=>{
  renderWithProviders(<CustomerKycDocumentsCard merchantId="m1" applicationId="application-1" documents={[document]}/>);
  expect(screen.getByText("Aadhaar")).toBeInTheDocument();
  expect(screen.getByText("Verified")).toBeInTheDocument();
  expect(screen.getByRole("button",{name:"Front"})).toBeEnabled();
  expect(screen.getByRole("button",{name:"Back"})).toBeEnabled();
  expect(screen.getByText("1 document · 2 files")).toBeInTheDocument();
  expect(screen.queryByText("application-1")).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"Show numbers"})).not.toBeInTheDocument();
 });
 it("preserves Show and Hide numbers behavior",async()=>{
  const user=userEvent.setup();
  renderWithProviders(<CustomerKycDocumentsCard merchantId="m1" documents={[document]}/>);
  expect(screen.queryByText(document.numberMasked)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"Show number"}));
  expect(screen.getByText(document.numberMasked)).toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"Hide number"}));
  expect(screen.queryByText(document.numberMasked)).not.toBeInTheDocument();
 });
 it("supports legacy single-file documents and empty records",()=>{
  const {unmount}=renderWithProviders(<CustomerKycDocumentsCard merchantId="m1" documents={[{...document,files:undefined}]}/>);
  expect(screen.getByRole("button",{name:"View"})).toBeEnabled();
  unmount();
  renderWithProviders(<CustomerKycDocumentsCard merchantId="m1" documents={[]}/>);
  expect(screen.getByText("No documents on file.")).toBeInTheDocument();
 });
 it("fetches the full number for Super Admin on demand and removes it when hidden",async()=>{
  vi.mocked(useOptionalAuth).mockReturnValue({channel:"admin",user:{active_roles:["super_admin"]},can:()=>true} as unknown as AuthContextValue);
  vi.mocked(revealDocumentNumber).mockResolvedValue({documentId:"doc-1",documentType:"AADHAAR",number:"123412341234",numberMasked:document.numberMasked});
  const user=userEvent.setup();
  renderWithProviders(<CustomerKycDocumentsCard merchantId="m1" applicationId="application-1" documents={[document]}/>);
  expect(revealDocumentNumber).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button",{name:"Show number"}));
  expect(await screen.findByText("123412341234")).toBeInTheDocument();
  expect(revealDocumentNumber).toHaveBeenCalledWith("application-1","doc-1");
  await user.click(screen.getByRole("button",{name:"Hide number"}));
  expect(screen.queryByText("123412341234")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"Show number"}));
  await screen.findByText("123412341234");
  expect(revealDocumentNumber).toHaveBeenCalledTimes(2);
 });
 it("keeps other users masked without calling the full-number API",async()=>{
  vi.mocked(useOptionalAuth).mockReturnValue({channel:"admin",user:{active_roles:["admin"]},can:()=>true} as unknown as AuthContextValue);
  const user=userEvent.setup();renderWithProviders(<CustomerKycDocumentsCard merchantId="m1" applicationId="application-1" documents={[document]}/>);
  await user.click(screen.getByRole("button",{name:"Show number"}));
  expect(screen.getByText(document.numberMasked)).toBeInTheDocument();
  expect(revealDocumentNumber).not.toHaveBeenCalled();
 });
 it("shows an unavailable-number error without claiming a masked number is full",async()=>{
  vi.mocked(useOptionalAuth).mockReturnValue({channel:"admin",user:{active_roles:["super_admin"]},can:()=>true} as unknown as AuthContextValue);
  vi.mocked(revealDocumentNumber).mockRejectedValue(new Error("Unavailable"));
  const user=userEvent.setup();renderWithProviders(<CustomerKycDocumentsCard merchantId="m1" applicationId="application-1" documents={[document]}/>);
  await user.click(screen.getByRole("button",{name:"Show number"}));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText(document.numberMasked)).not.toBeInTheDocument();
 });

});
