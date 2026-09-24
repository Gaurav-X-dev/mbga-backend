import { useMutation } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { requestOtp, resendOtp, verifyOtp, type OtpRequestResponse } from "../../api/auth.api";
import { normalizeError, type AppError } from "../../api/errors";
import { useAuth } from "../../auth/auth-context";
import { CHANNEL_HOME, safeRedirectPath } from "../../auth/permissions";
import type { AuthChannel } from "../../auth/token-storage";
import { Button } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { BrandMark } from "../../components/common/StatusBadge";
import { Alert, FullPageLoader } from "../../components/feedback/Feedback";
import { Field, PhoneInput } from "../../components/forms/Field";
import { OTP_LENGTH, OTPInput, type OTPInputHandle } from "../../components/forms/OTPInput";
import { env } from "../../config/env";
import { formatCountdown, useCountdown } from "../../hooks/useCountdown";
import { mobileSchema } from "../../schemas/common";
import { maskMobileNumber, normalizeMobileNumber } from "../../utils/mobile";

type Challenge = {
  requestId: string;
  mobile: string;
  resendAt: number;
  expiresAt: number;
};

/** Codes after which the current verification code can no longer be used. */
const DEAD_CODE_ERRORS = new Set(["OTP_EXPIRED", "OTP_ATTEMPTS_EXCEEDED", "OTP_ALREADY_USED", "OTP_PURPOSE_MISMATCH"]);
/** Account-level problems: a new code will not help. */
const ACCOUNT_ERRORS = new Set([
  "NUMBER_NOT_REGISTERED",
  "ROLE_NOT_ASSIGNED",
  "PERMISSION_DENIED",
  "CHANNEL_NOT_ALLOWED",
  "ACCOUNT_BLOCKED",
  "ACCOUNT_INACTIVE",
  "ACCOUNT_PENDING_APPROVAL"
]);

function toChallenge(response: OtpRequestResponse, mobile: string): Challenge {
  const now = Date.now();
  return {
    requestId: response.request_id,
    mobile,
    resendAt: now + response.resend_after * 1000,
    expiresAt: now + response.expires_in * 1000
  };
}

function panelFromPath(path: unknown): AuthChannel | null {
  if (typeof path !== "string") return null;
  if (path.startsWith("/merchant")) return "merchant";
  if (path.startsWith("/admin")) return "admin";
  return null;
}

function loginErrorMessage(error: AppError): string {
  if (error.code === "ROLE_NOT_ASSIGNED" || error.code === "PERMISSION_DENIED" || error.code === "CHANNEL_NOT_ALLOWED") {
    return "Your account does not have access to this panel. Check that you selected the correct account type.";
  }
  return error.userMessage;
}

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const from = (location.state as { from?: string } | null)?.from;
  const initialChannel: AuthChannel =
    panelFromPath(from) ?? (searchParams.get("panel") === "merchant" ? "merchant" : "admin");

  const [channel, setChannel] = useState<AuthChannel>(initialChannel);
  const [mobileInput, setMobileInput] = useState("");
  const [mobileError, setMobileError] = useState<string | undefined>();
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [otp, setOtp] = useState("");
  const [formError, setFormError] = useState<AppError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [codeIsDead, setCodeIsDead] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const otpRef = useRef<OTPInputHandle>(null);
  const mobileRef = useRef<HTMLInputElement>(null);
  const otpHelpId = useId();

  const resendIn = useCountdown(challenge?.resendAt ?? null);
  const expiresIn = useCountdown(challenge?.expiresAt ?? null);

  useEffect(() => {
    document.title = "Sign in · MBGA";
  }, []);

  const { endReason, clearEndReason } = auth;
  useEffect(() => {
    if (endReason === "expired") setNotice("Your session has ended. Please sign in again.");
    else if (endReason === "signed_out") setNotice("You have signed out.");
    if (endReason) clearEndReason();
  }, [endReason, clearEndReason]);

  const requestMutation = useMutation({
    mutationFn: (mobile: string) => requestOtp(channel, mobile),
    onSuccess: (response, mobile) => {
      setChallenge(toChallenge(response, mobile));
      setOtp("");
      setFormError(null);
      setCodeIsDead(false);
      setNotice(null);
    },
    onError: (error) => {
      const appError = normalizeError(error);
      if (appError.code === "INVALID_MOBILE_NUMBER") setMobileError(appError.userMessage);
      else setFormError(appError);
    }
  });

  const resendMutation = useMutation({
    mutationFn: async (current: Challenge) => {
      try {
        return await resendOtp(channel, current.requestId);
      } catch (error) {
        // An expired or used code cannot be "resent"; start a fresh request instead.
        const appError = normalizeError(error);
        if (appError.code && DEAD_CODE_ERRORS.has(appError.code)) return requestOtp(channel, current.mobile);
        throw appError;
      }
    },
    onSuccess: (response, current) => {
      setChallenge(toChallenge(response, current.mobile));
      setOtp("");
      setFormError(null);
      setCodeIsDead(false);
      setNotice("We sent a new verification code.");
      otpRef.current?.focus();
    },
    onError: (error) => setFormError(normalizeError(error))
  });

  const verifyMutation = useMutation({
    mutationFn: async ({ current, code }: { current: Challenge; code: string }) => {
      const response = await verifyOtp(channel, current.requestId, code);
      if (!response.token) {
        throw normalizeError(new Error("missing token"));
      }
      await auth.completeLogin(channel, response.token);
    },
    onSuccess: () => {
      setRedirecting(true);
      navigate(safeRedirectPath(from, channel), { replace: true });
    },
    onError: (error) => {
      const appError = normalizeError(error);
      setFormError(appError);
      setNotice(null);
      if (appError.code && DEAD_CODE_ERRORS.has(appError.code)) setCodeIsDead(true);
      setOtp("");
      window.setTimeout(() => otpRef.current?.focus(), 0);
    }
  });

  if (auth.status === "authenticated" && auth.channel && !redirecting && !verifyMutation.isPending) {
    return <Navigate to={from && panelFromPath(from) === auth.channel ? safeRedirectPath(from, auth.channel) : CHANNEL_HOME[auth.channel]} replace />;
  }
  if (auth.status === "loading" && !verifyMutation.isPending && !redirecting) {
    return <FullPageLoader label="Checking your session" />;
  }

  function submitMobile(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    const parsed = mobileSchema.safeParse(mobileInput);
    if (!parsed.success) {
      setMobileError(parsed.error.issues[0]?.message);
      mobileRef.current?.focus();
      return;
    }
    setMobileError(undefined);
    const normalized = normalizeMobileNumber(parsed.data);
    if (normalized) requestMutation.mutate(normalized);
  }

  function submitOtp(code: string) {
    if (!challenge || code.length !== OTP_LENGTH || verifyMutation.isPending || codeIsDead) return;
    setFormError(null);
    verifyMutation.mutate({ current: challenge, code });
  }

  function changeNumber() {
    setChallenge(null);
    setOtp("");
    setFormError(null);
    setNotice(null);
    setCodeIsDead(false);
    window.setTimeout(() => mobileRef.current?.focus(), 0);
  }

  const busy = verifyMutation.isPending || redirecting;
  const accountProblem = formError?.code ? ACCOUNT_ERRORS.has(formError.code) : false;

  return (
    <div className="auth-page">
      <aside className="auth-aside" aria-hidden="true">
        <div className="row">
          <BrandMark />
          <span className="brand-text">
            <span className="brand-text__name" style={{ color: "#fff" }}>
              MBGA
            </span>
            <span className="brand-text__panel">LPG operations</span>
          </span>
        </div>
        <div className="stack-lg">
          <p className="auth-aside__headline">Run your LPG distribution with confidence.</p>
          <ul className="auth-aside__list">
            <li>
              <Icon name="store" />
              <span>Manage merchant businesses and their accounts in one place.</span>
            </li>
            <li>
              <Icon name="truck" />
              <span>Keep your delivery team of drivers and helpers up to date.</span>
            </li>
            <li>
              <Icon name="shield" />
              <span>Control who can see and do what, with a full activity history.</span>
            </li>
          </ul>
        </div>
        <p className="meta" style={{ color: "#8fa0b8" }}>
          © MBGA. For authorised business users only.
        </p>
      </aside>

      <main className="auth-main" id="main-content">
        <div className="auth-card">
          <div className="auth-card__header">
            <div className="row">
              <BrandMark />
            </div>
            <h1 className="page-title">Welcome to MBGA</h1>
            <p className="text-muted">Sign in to manage your MBGA operations.</p>
          </div>

          {notice ? <Alert tone={notice.startsWith("Your session") ? "warning" : "info"}>{notice}</Alert> : null}

          {!challenge ? (
            <form className="stack-lg" onSubmit={submitMobile} noValidate>
              <fieldset className="field" style={{ border: 0, margin: 0, padding: 0 }}>
                <legend className="field__label" style={{ marginBottom: "var(--space-2)" }}>
                  Sign in to
                </legend>
                <div className="segmented">
                  {(
                    [
                      ["admin", "Admin panel", "shield"],
                      ["merchant", "Merchant panel", "store"]
                    ] as const
                  ).map(([value, label, icon]) => (
                    <label key={value} className="segmented__option">
                      <input
                        type="radio"
                        name="panel"
                        value={value}
                        checked={channel === value}
                        disabled={requestMutation.isPending}
                        onChange={() => {
                          setChannel(value);
                          setFormError(null);
                        }}
                      />
                      <span>
                        <Icon name={icon} size={16} />
                        {label}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <Field
                label="Mobile number"
                required
                error={mobileError}
                hint="Enter the 10-digit mobile number registered with MBGA."
              >
                <PhoneInput
                  ref={mobileRef}
                  name="mobile"
                  value={mobileInput}
                  autoFocus
                  disabled={requestMutation.isPending}
                  onChange={(event) => {
                    setMobileInput(event.target.value);
                    if (mobileError) setMobileError(undefined);
                  }}
                />
              </Field>

              {formError ? <Alert tone="error">{loginErrorMessage(formError)}</Alert> : null}

              <Button
                type="submit"
                variant="accent"
                size="lg"
                block
                loading={requestMutation.isPending}
                loadingText="Sending code…"
              >
                Send verification code
              </Button>

              <p className="auth-footnote">
                <Icon name="lock" size={14} />
                <span>We will send a one-time verification code to this number. Never share this code with anyone.</span>
              </p>
            </form>
          ) : (
            <form
              className="stack-lg"
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                submitOtp(otp);
              }}
            >
              <div className="stack" style={{ gap: "var(--space-2)" }}>
                <h2 className="section-title">Enter verification code</h2>
                <p className="text-muted">
                  If <strong className="nowrap">{maskMobileNumber(challenge.mobile)}</strong> has access to the{" "}
                  {channel === "admin" ? "Admin" : "Merchant"} panel, we sent it a {OTP_LENGTH}-digit code.{" "}
                  <button type="button" className="btn btn--link" onClick={changeNumber} disabled={busy}>
                    Change mobile number
                  </button>
                </p>
              </div>

              <div className="stack" style={{ gap: "var(--space-2)" }}>
                <OTPInput
                  ref={otpRef}
                  value={otp}
                  onChange={(value) => {
                    setOtp(value);
                    if (formError && !codeIsDead && !accountProblem) setFormError(null);
                  }}
                  onComplete={submitOtp}
                  disabled={busy || codeIsDead}
                  invalid={Boolean(formError) && !accountProblem}
                  describedBy={otpHelpId}
                  autoFocus
                />
                <p id={otpHelpId} className="field__hint" aria-live="polite">
                  {expiresIn > 0
                    ? `The code expires in ${formatCountdown(expiresIn)}.`
                    : "This code has expired. Request a new code."}
                  {env.previewMode ? " Local development: use the verification code configured on the local server." : ""}
                </p>
              </div>

              {formError ? <Alert tone="error">{loginErrorMessage(formError)}</Alert> : null}

              <Button
                type="submit"
                variant="accent"
                size="lg"
                block
                loading={busy}
                loadingText="Verifying…"
                disabled={otp.length !== OTP_LENGTH || codeIsDead || expiresIn === 0}
              >
                Verify and continue
              </Button>

              <div className="row-between text-small">
                <span className="text-muted">Didn’t get the code?</span>
                {resendIn > 0 && !codeIsDead ? (
                  <span className="text-muted" aria-live="polite">
                    Resend code in {formatCountdown(resendIn)}
                  </span>
                ) : (
                  <Button
                    variant="link"
                    onClick={() => resendMutation.mutate(challenge)}
                    loading={resendMutation.isPending}
                    loadingText="Sending…"
                    disabled={busy}
                  >
                    {codeIsDead ? "Request a new code" : "Resend code"}
                  </Button>
                )}
              </div>
            </form>
          )}
        </div>
      </main>
    </div>
  );
}
