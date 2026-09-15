import { apiClient } from "./client";

export type AuthChannel = "admin" | "merchant";

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

export type OtpVerifyResponse = {
  token: TokenPair;
  user_id: string;
  login_channel: string;
  code: string;
  message: string;
};

export type MeResponse = {
  user_id: string;
  display_name?: string | null;
  mobile_number?: string | null;
  login_channel?: string | null;
  active_roles: string[];
  effective_permissions: string[];
  status: string;
};

export async function requestOtp(channel: AuthChannel, mobileNumber: string): Promise<OtpRequestResponse> {
  const { data } = await apiClient.post<OtpRequestResponse>(`/${channel}/auth/otp/request`, {
    mobile_number: mobileNumber,
    device: {
      device_type: "web",
      device_id: "web-panel"
    }
  });
  return data;
}

export async function verifyOtp(channel: AuthChannel, requestId: string, otp: string): Promise<OtpVerifyResponse> {
  const { data } = await apiClient.post<OtpVerifyResponse>(`/${channel}/auth/otp/verify`, {
    request_id: requestId,
    otp,
    device: {
      device_type: "web",
      device_id: "web-panel"
    }
  });
  return data;
}

export async function fetchMe(channel: AuthChannel, accessToken: string): Promise<MeResponse> {
  const { data } = await apiClient.get<MeResponse>(`/${channel}/auth/me`, {
    headers: {
      Authorization: `Bearer ${accessToken}`
    }
  });
  return data;
}

export async function logout(channel: AuthChannel, refreshToken: string | null): Promise<void> {
  await apiClient.post(`/${channel}/auth/logout`, { refresh_token: refreshToken });
}
