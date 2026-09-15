import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "./app/providers";
import { LoginPage } from "./features/login/LoginPage";

vi.mock("./api/auth.api", async () => {
  const actual = await vi.importActual<typeof import("./api/auth.api")>("./api/auth.api");
  return {
    ...actual,
    requestOtp: vi.fn(async () => ({
      request_id: "request-id",
      code: "OTP_REQUEST_ACCEPTED",
      message: "OTP request accepted",
      expires_in: 300,
      resend_after: 30
    })),
    verifyOtp: vi.fn()
  };
});

describe("App", () => {
  it("renders the login screen before authentication", () => {
    render(
      <AppProviders>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </AppProviders>
    );

    expect(screen.getByText("MBGA Web Panel Login")).toBeInTheDocument();
  });

  it("renders four OTP boxes and supports four-digit paste", async () => {
    const user = userEvent.setup();
    render(
      <AppProviders>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </AppProviders>
    );

    await user.type(screen.getByLabelText("Mobile number"), "+919876543210");
    await user.click(screen.getByRole("button", { name: "Request OTP" }));

    const boxes = await screen.findAllByLabelText(/OTP digit/i);
    expect(boxes).toHaveLength(4);

    await user.click(boxes[0]);
    await user.paste("1234");

    expect(screen.getByLabelText("OTP digit 1")).toHaveValue("1");
    expect(screen.getByLabelText("OTP digit 2")).toHaveValue("2");
    expect(screen.getByLabelText("OTP digit 3")).toHaveValue("3");
    expect(screen.getByLabelText("OTP digit 4")).toHaveValue("4");
  });
});
