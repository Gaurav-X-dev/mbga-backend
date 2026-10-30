import type { Address } from "../../api/orders.api";
import { GoogleMapLocationPicker } from "../../components/maps/GoogleMapLocationPicker";

/**
 * Google Maps Delivery Address Flow (Rapido-style) with Live Location Capture,
 * Places search, interactive center-pin map, and MBGA pincode serviceability check.
 */
export function PincodeAddressFields({
  value,
  onChange,
  prefix = "Delivery",
  merchantId,
  onServiceabilityChange,
}: {
  value: Address;
  onChange: (next: Address) => void;
  prefix?: string;
  merchantId?: string;
  onServiceabilityChange?: (isServiceable: boolean, errorMsg?: string) => void;
}) {
  return (
    <GoogleMapLocationPicker
      value={value}
      onChange={onChange}
      prefix={prefix}
      merchantId={merchantId}
      onServiceabilityChange={onServiceabilityChange}
    />
  );
}
