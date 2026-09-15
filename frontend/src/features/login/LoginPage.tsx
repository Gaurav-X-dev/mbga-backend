import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { requestOtp, verifyOtp, type AuthChannel } from "../../api/auth.api";
import { useAuth } from "../../auth/AuthProvider";

function friendlyError(error: unknown) {
  if (typeof error === "object" && error && "response" in error) {
    const response = (error as { response?: { data?: { detail?: { code?: string } } } }).response;
    return response?.data?.detail?.code ?? "Unable to complete login";
  }
  return "Unable to complete login";
}

export function LoginPage() {
  const [channel, setChannel] = useState<AuthChannel>("admin");
  const [mobileNumber, setMobileNumber] = useState("");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const otpRefs = useRef<Array<HTMLInputElement | null>>([]);
  const [resendAfter, setResendAfter] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const auth = useAuth();
  const navigate = useNavigate();

  async function onRequestOtp() {
    setLoading(true);
    setError(null);
    try {
      const response = await requestOtp(channel, mobileNumber);
      setRequestId(response.request_id);
      setResendAfter(response.resend_after);
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setLoading(false);
    }
  }

  async function onVerifyOtp() {
    if (!requestId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await verifyOtp(channel, requestId, otp);
      await auth.completeLogin(channel, response.token);
      navigate("/");
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setLoading(false);
    }
  }

  function updateOtp(index: number, value: string) {
    const digit = value.replace(/\D/g, "").slice(-1);
    const next = otp.padEnd(4, " ").split("");
    next[index] = digit || " ";
    const joined = next.join("").replace(/\s/g, "");
    setOtp(joined);
    if (digit && index < 3) {
      otpRefs.current[index + 1]?.focus();
    }
  }

  function onOtpKeyDown(index: number, key: string) {
    if (key === "Backspace" && !otp[index] && index > 0) {
      otpRefs.current[index - 1]?.focus();
    }
  }

  function onOtpPaste(value: string) {
    const digits = value.replace(/\D/g, "");
    if (digits.length === 4) {
      setOtp(digits);
      otpRefs.current[3]?.focus();
    }
  }

  return (
    <section className="login-panel">
      <h1>MBGA Web Panel Login</h1>
      <label>
        Channel
        <select value={channel} onChange={(event) => setChannel(event.target.value as AuthChannel)}>
          <option value="admin">Super Admin / Admin</option>
          <option value="merchant">Merchant / Staff</option>
        </select>
      </label>
      <label>
        Mobile number
        <input
          value={mobileNumber}
          onChange={(event) => setMobileNumber(event.target.value)}
          placeholder="+919876543210"
          inputMode="tel"
        />
      </label>
      {!requestId ? (
        <button type="button" disabled={loading || mobileNumber.length < 10} onClick={() => void onRequestOtp()}>
          {loading ? "Requesting..." : "Request OTP"}
        </button>
      ) : (
        <>
          <p className="hint">We have sent a 4-digit code.</p>
          <label>
            OTP
            <div className="otp-boxes" aria-label="Enter 4-digit OTP">
              {[0, 1, 2, 3].map((index) => (
                <input
                  key={index}
                  ref={(element) => {
                    otpRefs.current[index] = element;
                  }}
                  aria-label={`OTP digit ${index + 1}`}
                  value={otp[index] ?? ""}
                  onChange={(event) => updateOtp(index, event.target.value)}
                  onKeyDown={(event) => onOtpKeyDown(index, event.key)}
                  onPaste={(event) => {
                    event.preventDefault();
                    onOtpPaste(event.clipboardData.getData("text"));
                  }}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={1}
                />
              ))}
            </div>
          </label>
          <button type="button" disabled={loading || otp.length !== 4} onClick={() => void onVerifyOtp()}>
            {loading ? "Verifying..." : "Verify OTP"}
          </button>
          <button type="button" className="link-button" onClick={() => { setRequestId(null); setOtp(""); }}>
            Change number
          </button>
          <p className="hint">Use the locally configured development OTP. Resend after {resendAfter}s.</p>
        </>
      )}
      {error ? <p role="alert" className="error">{error}</p> : null}
    </section>
  );
}
