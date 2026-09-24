import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { OTPInput } from "./OTPInput";

function Harness({ onComplete = () => undefined }: { onComplete?: (value: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <>
      <OTPInput value={value} onChange={setValue} onComplete={onComplete} />
      <output data-testid="value">{value}</output>
    </>
  );
}

const boxes = () => screen.getAllByRole("textbox");

describe("OTPInput", () => {
  it("renders exactly four labelled digit boxes", () => {
    render(<Harness />);
    expect(boxes()).toHaveLength(4);
    expect(screen.getByLabelText("Digit 1 of 4")).toBeInTheDocument();
    expect(screen.getByLabelText("Digit 4 of 4")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Verification code" })).toBeInTheDocument();
  });

  it("moves focus forward while typing and reports completion", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    await user.click(boxes()[0]);
    await user.keyboard("12");
    expect(boxes()[2]).toHaveFocus();
    await user.keyboard("34");
    expect(screen.getByTestId("value")).toHaveTextContent("1234");
    expect(onComplete).toHaveBeenCalledWith("1234");
  });

  it("ignores letters", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(boxes()[0]);
    await user.keyboard("a1b");
    expect(screen.getByTestId("value")).toHaveTextContent(/^1$/);
  });

  it("fills all boxes from a pasted code", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    await user.click(boxes()[0]);
    await user.paste("Your code is 5678");
    expect(boxes().map((box) => (box as HTMLInputElement).value)).toEqual(["5", "6", "7", "8"]);
    expect(onComplete).toHaveBeenCalledWith("5678");
  });

  it("moves back and clears with backspace", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(boxes()[0]);
    await user.keyboard("12");
    await user.keyboard("{Backspace}");
    expect(boxes()[1]).toHaveFocus();
    expect(screen.getByTestId("value")).toHaveTextContent(/^1$/);
    await user.keyboard("{Backspace}");
    expect(screen.getByTestId("value")).toBeEmptyDOMElement();
  });

  it("supports arrow key navigation", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(boxes()[0]);
    await user.keyboard("123");
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(boxes()[1]).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(boxes()[2]).toHaveFocus();
  });

  it("can be disabled", () => {
    render(<OTPInput value="" onChange={() => undefined} disabled />);
    boxes().forEach((box) => expect(box).toBeDisabled());
  });
});
