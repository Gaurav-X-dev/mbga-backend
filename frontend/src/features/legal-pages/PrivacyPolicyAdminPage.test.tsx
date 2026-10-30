import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { PrivacyPolicyAdminPage } from "./PrivacyPolicyAdminPage";
import { getPrivacyEditor, getPrivacyRevisions, savePrivacyDraft, publishPrivacyPolicy, previewPrivacyPolicy, type PolicyEditor } from "../../api/legal-pages.api";

const permission = vi.hoisted(() => ({ manage: true }));
vi.mock("../../auth/auth-context", async (original) => ({
  ...await original<typeof import("../../auth/auth-context")>(),
  useAuth: () => ({ can: () => permission.manage })
}));
vi.mock("../../api/legal-pages.api", () => ({getPrivacyEditor:vi.fn(), getPrivacyRevisions:vi.fn(), savePrivacyDraft:vi.fn(),publishPrivacyPolicy:vi.fn(),previewPrivacyPolicy:vi.fn()}));
const initial: PolicyEditor = {
  slug:"privacy-policy", revision:1, publishedRevision:null, published:null, updatedAt:null,updatedBy:null,publishedAt:null,
  publicPath:"/privacy-policy", publicationIssues:[],
  draft:{title:"Privacy Policy",publisherName:"Madhav Bharat Gas Agency",customerAppName:"Customer App",merchantAppName:"Merchant App",riderAppName:"Rider App",contactEmail:"privacy@example.com",contactUrl:"",effectiveDate:"2026-10-28",backgroundLocation:"FOREGROUND_ONLY",sdkDisclosure:"Firebase notifications and SMS OTP.",sections:[{heading:"Data collection",body:"We collect account and delivery information."}]}
};
beforeEach(() => {
  vi.clearAllMocks(); permission.manage=true;
  vi.mocked(getPrivacyEditor).mockResolvedValue(structuredClone(initial));
  vi.mocked(getPrivacyRevisions).mockResolvedValue([]);
  vi.mocked(previewPrivacyPolicy).mockResolvedValue("<!doctype html><html><body>Preview</body></html>");
});

describe("privacy policy editor", () => {
  it("saves a draft without publishing, then explicitly publishes the saved version", async () => {
    const user=userEvent.setup();
    vi.mocked(savePrivacyDraft).mockImplementation(async (revision,content) => ({...initial,revision:revision+1,draft:content}));
    vi.mocked(publishPrivacyPolicy).mockImplementation(async (revision) => ({...initial,revision:revision+1,publishedRevision:revision+1,published:initial.draft,publishedAt:"2026-10-28T10:00:00Z"}));
    renderWithProviders(<PrivacyPolicyAdminPage />);
    const title=await screen.findByLabelText(/Policy title/);
    await user.clear(title); await user.type(title,"Updated Privacy Policy");
    expect(screen.getByRole("button",{name:"Publish policy"})).toBeDisabled();
    await user.click(screen.getByRole("button",{name:"Save draft"}));
    await waitFor(() => expect(savePrivacyDraft).toHaveBeenCalledWith(1,expect.objectContaining({title:"Updated Privacy Policy"})));
    expect(publishPrivacyPolicy).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button",{name:"Publish policy"})).toBeEnabled());
    await user.click(screen.getByRole("button",{name:"Publish policy"}));
    await waitFor(() => expect(publishPrivacyPolicy).toHaveBeenCalledWith(2));
  });
  it("renders a sandboxed preview and never publishes it", async () => {
    const user=userEvent.setup(); renderWithProviders(<PrivacyPolicyAdminPage />);
    await user.click(await screen.findByRole("button",{name:"Preview draft"}));
    const frame=await screen.findByTitle("Privacy policy draft preview");
    expect(frame).toHaveAttribute("sandbox","");
    expect(frame).toHaveAttribute("srcdoc",expect.stringContaining("Preview"));
    expect(publishPrivacyPolicy).not.toHaveBeenCalled();
  });
  it("hides write controls for a read-only admin", async () => {
    permission.manage=false; renderWithProviders(<PrivacyPolicyAdminPage />);
    expect(await screen.findByLabelText(/Policy title/)).toBeDisabled();
    expect(screen.queryByRole("button",{name:"Save draft"})).not.toBeInTheDocument();
    expect(screen.queryByRole("button",{name:"Publish policy"})).not.toBeInTheDocument();
  });
  it("keeps publication disabled until required factual details are complete", async () => {
    vi.mocked(getPrivacyEditor).mockResolvedValue({...initial,publicationIssues:["Confirm Rider background location."]});
    renderWithProviders(<PrivacyPolicyAdminPage />);
    expect(await screen.findByText("Confirm Rider background location.")).toBeInTheDocument();
    expect(screen.getByRole("button",{name:"Publish policy"})).toBeDisabled();
  });
});
