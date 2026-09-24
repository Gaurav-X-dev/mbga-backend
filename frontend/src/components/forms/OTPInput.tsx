import { forwardRef, useImperativeHandle, useRef } from "react";
import type { ClipboardEvent, KeyboardEvent } from "react";

export const OTP_LENGTH = 4;

type OTPInputProps = {
  value: string;
  onChange: (value: string) => void;
  /** Called once all four digits are present. */
  onComplete?: (value: string) => void;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
  autoFocus?: boolean;
};

export type OTPInputHandle = { focus: () => void; clear: () => void };

/** Exactly four single-digit boxes with paste, arrow, backspace and auto-advance support. */
export const OTPInput = forwardRef<OTPInputHandle, OTPInputProps>(function OTPInput(
  { value, onChange, onComplete, disabled, invalid, describedBy, autoFocus },
  ref
) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = Array.from({ length: OTP_LENGTH }, (_, index) => value[index] ?? "");

  useImperativeHandle(ref, () => ({
    focus: () => refs.current[Math.min(value.length, OTP_LENGTH - 1)]?.focus(),
    clear: () => {
      onChange("");
      refs.current[0]?.focus();
    }
  }));

  function focusBox(index: number) {
    const box = refs.current[Math.max(0, Math.min(OTP_LENGTH - 1, index))];
    box?.focus();
    box?.select();
  }

  function commit(next: string[]) {
    // Keep digits contiguous from the left so the value is always a prefix.
    const joined = next.join("").replace(/\D/g, "").slice(0, OTP_LENGTH);
    onChange(joined);
    if (joined.length === OTP_LENGTH) onComplete?.(joined);
  }

  function handleInput(index: number, raw: string) {
    const typed = raw.replace(/\D/g, "");
    if (!typed) return;
    if (typed.length > 1) {
      // Autofill or fast typing can deliver several digits at once.
      fillFrom(index, typed);
      return;
    }
    const next = [...digits];
    const target = Math.min(index, value.length);
    next[target] = typed;
    commit(next);
    focusBox(target + 1);
  }

  function fillFrom(index: number, text: string) {
    const start = Math.min(index, value.length);
    const next = [...digits];
    const incoming = text.replace(/\D/g, "").slice(0, OTP_LENGTH - start).split("");
    incoming.forEach((digit, offset) => {
      next[start + offset] = digit;
    });
    commit(next);
    focusBox(start + incoming.length);
  }

  function handleKeyDown(index: number, event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace") {
      event.preventDefault();
      const next = [...digits];
      if (digits[index]) {
        next.splice(index, 1);
        commit(next);
        focusBox(index);
      } else if (index > 0) {
        next.splice(index - 1, 1);
        commit(next);
        focusBox(index - 1);
      }
    } else if (event.key === "Delete") {
      event.preventDefault();
      const next = [...digits];
      next.splice(index, 1);
      commit(next);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      focusBox(index - 1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      focusBox(Math.min(index + 1, value.length));
    } else if (event.key.length === 1 && !/\d/.test(event.key) && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
    }
  }

  function handlePaste(index: number, event: ClipboardEvent<HTMLInputElement>) {
    event.preventDefault();
    const text = event.clipboardData.getData("text");
    if (/\d/.test(text)) fillFrom(index, text);
  }

  return (
    <div className="otp-input" role="group" aria-label="Verification code" aria-describedby={describedBy}>
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={(element) => {
            refs.current[index] = element;
          }}
          className="otp-input__box"
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          maxLength={OTP_LENGTH}
          aria-label={`Digit ${index + 1} of ${OTP_LENGTH}`}
          aria-invalid={invalid || undefined}
          value={digit}
          disabled={disabled}
          autoFocus={autoFocus && index === 0}
          onFocus={(event) => event.target.select()}
          onChange={(event) => handleInput(index, event.target.value.replace(digit, "") || event.target.value)}
          onKeyDown={(event) => handleKeyDown(index, event)}
          onPaste={(event) => handlePaste(index, event)}
        />
      ))}
    </div>
  );
});
