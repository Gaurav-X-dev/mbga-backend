import type { AuthChannel } from "../auth/token-storage";
import { apiClient, WEB_DEVICE } from "./client";

export type { AuthChannel } from "../auth/token-storage";

/** POST /{channel}/auth/otp/request and /otp/resend (202) */
export type OtpRequestResponse = {
  request_id: string;
  code: string;
  message: string;
  expires_in: number;
  resend_after: number;
};

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

/** POST /{channel}/auth/otp/verify */
export type OtpVerifyResponse = {
  token: TokenPair | null;
  user_id: string | null;
  role?: string | null;
  login_channel: string | null;
  is_new_user?: boolean;
  code: string;
  message: string;
};

/** GET /{channel}/auth/me */
export type MeResponse = {
  user_id: string;
  display_name?: string | null;
  mobile_number?: string | null;
  country_code?: string | null;
  role?: string | null;
  login_channel?: string | null;
  active_roles: string[];
  effective_permissions: string[];
  status: string;
  merchant?: Record<string, unknown> | null;
  profile?: Record<string, unknown> | null;
};

/** `mobileNumber` must already be normalised to +91XXXXXXXXXX. */
export async function requestOtp(channel: AuthChannel, mobileNumber: string): Promise<OtpRequestResponse> {
  const { data } = await apiClient.post<OtpRequestResponse>(
    `/${channel}/auth/otp/request`,
    { mobile_number: mobileNumber, country_code: "+91", device: WEB_DEVICE },
    { skipAuth: true, skipAuthRefresh: true }
  );
  return data;
}

export async function resendOtp(channel: AuthChannel, requestId: string): Promise<OtpRequestResponse> {
  const { data } = await apiClient.post<OtpRequestResponse>(
    `/${channel}/auth/otp/resend`,
    { request_id: requestId, device: WEB_DEVICE },
    { skipAuth: true, skipAuthRefresh: true }
  );
  return data;
}

export async function verifyOtp(channel: AuthChannel, requestId: string, otp: string): Promise<OtpVerifyResponse> {
  const { data } = await apiClient.post<OtpVerifyResponse>(
    `/${channel}/auth/otp/verify`,
    { request_id: requestId, otp, device: WEB_DEVICE },
    { skipAuth: true, skipAuthRefresh: true }
  );
  return data;
}

/** Uses the stored session unless an explicit token is supplied (used right after verification). */
export async function fetchMe(channel: AuthChannel, accessToken?: string, signal?: AbortSignal): Promise<MeResponse> {
  const { data } = await apiClient.get<MeResponse>(`/${channel}/auth/me`, {
    signal,
    ...(accessToken
      ? { headers: { Authorization: `Bearer ${accessToken}` }, skipAuth: true, skipAuthRefresh: true }
      : {})
  });
  return data;
}

export async function logout(channel: AuthChannel, refreshToken: string | null): Promise<void> {
  await apiClient.post(
    `/${channel}/auth/logout`,
    { refresh_token: refreshToken, device_id: WEB_DEVICE.device_id },
    { skipAuth: true, skipAuthRefresh: true }
  );
}

export async function logoutAll(channel: AuthChannel): Promise<void> {
  await apiClient.post(`/${channel}/auth/logout-all`);
}
