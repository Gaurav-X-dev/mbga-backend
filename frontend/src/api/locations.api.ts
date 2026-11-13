import { apiClient } from "./client";

/** Admin channel: India Post pincode data, used to fill addresses from a pincode. */
export type PostOffice = {
  officeName: string;
  officeType?: string | null;
  deliveryAvailable?: boolean | null;
  latitude?: number | null;
  longitude?: number | null;
};

export type PincodeDetails = {
  pincode: string;
  serviceable: boolean;
  district: string;
  state: string;
  offices: PostOffice[];
};

/** 404 when India Post has no such pincode. */
export async function lookupPincode(pincode: string, merchantId?: string, signal?: AbortSignal, channel: "admin" | "merchant" = "admin") {
  const { data } = await apiClient.get<PincodeDetails>(`/${channel}/locations/pincodes/${encodeURIComponent(pincode)}`, {
    params: channel === "admin" && merchantId ? { merchantId } : undefined,
    signal
  });
  return data;
}

/** Loads or refreshes the pincode table from the India Post CSV. */
export async function importPostalLocations(file: File) {
  const body = new FormData();
  body.append("upload", file);
  const { data } = await apiClient.post<Record<string, unknown>>("/admin/postal-locations/import", body, { timeout: 300_000 });
  return data;
}
