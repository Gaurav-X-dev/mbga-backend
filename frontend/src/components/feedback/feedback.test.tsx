import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { describe, expect, it, vi } from "vitest";

import { AppError } from "../../api/errors";
import { ConfirmationDialog } from "./Dialogs";
import { EmptyState, ErrorState, InlineError, LoadingSkeleton } from "./Feedback";

describe("state components", () => {
  it("announces loading", () => {
    render(<LoadingSkeleton label="Loading merchants" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading merchants…");
  });

  it("renders an empty state with an action", () => {
    render(<EmptyState title="No merchants yet" description="Add one" action={<button>Add merchant</button>} />);
    expect(screen.getByRole("heading", { name: "No merchants yet" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add merchant" })).toBeInTheDocument();
  });

  it("shows a safe message and retry for network errors", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const error = new AxiosError("Network Error", "ERR_NETWORK", {} as InternalAxiosRequestConfig, {});
    render(<ErrorState error={error} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Can’t reach the server");
    expect(screen.getByRole("alert")).not.toHaveTextContent("Network Error");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("does not offer retry for permission errors", () => {
    render(<ErrorState error={new AppError({ kind: "forbidden", userMessage: "No access." })} onRetry={() => undefined} />);
    expect(screen.getByText("You don’t have access to this")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("renders nothing for an empty inline error", () => {
    const { container } = render(<InlineError error={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ConfirmationDialog", () => {
  it("is a labelled modal dialog that closes with Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <ConfirmationDialog
        open
        title="Block Sharma Gas?"
        description="Staff will be signed out."
        confirmLabel="Block account"
        onConfirm={() => undefined}
        onClose={onClose}
      />
    );
    const dialog = screen.getByRole("alertdialog", { name: "Block Sharma Gas?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("Staff will be signed out.");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps focus inside the dialog", async () => {
    const user = userEvent.setup();
    render(
      <ConfirmationDialog open title="Confirm" description="Sure?" confirmLabel="Yes" onConfirm={() => undefined} onClose={() => undefined} />
    );
    const dialog = screen.getByRole("alertdialog");
    for (let index = 0; index < 5; index += 1) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
  });

  it("runs the action, then closes", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <ConfirmationDialog open title="Confirm" description="Sure?" confirmLabel="Yes, do it" onConfirm={onConfirm} onClose={onClose} />
    );
    await user.click(screen.getByRole("button", { name: "Yes, do it" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("stays open and shows a safe message when the action fails", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <ConfirmationDialog
        open
        title="Confirm"
        description="Sure?"
        confirmLabel="Yes"
        onConfirm={() => Promise.reject(new AppError({ kind: "forbidden", userMessage: "You don’t have permission to perform this action." }))}
        onClose={onClose}
      />
    );
    await user.click(screen.getByRole("button", { name: "Yes" }));
    expect(await screen.findByText("You don’t have permission to perform this action.")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
