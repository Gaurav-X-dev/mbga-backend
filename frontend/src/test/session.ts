import { apiClient } from "../api/client";
import { tokenStorage } from "../auth/token-storage";

/** Signs in against the fake backend without going through the UI. */
export async function seedSession(channel: "admin" | "merchant", mobile: string) {
  const { data: challenge } = await apiClient.post(`/${channel}/auth/otp/request`, { mobile_number: mobile });
  const { data } = await apiClient.post(`/${channel}/auth/otp/verify`, { request_id: challenge.request_id, otp: "1234" });
  tokenStorage.set({ channel, accessToken: data.token.access_token, refreshToken: data.token.refresh_token });
}
