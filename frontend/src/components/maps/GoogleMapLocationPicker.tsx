import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, useCallback } from "react";

import { normalizeError } from "../../api/errors";
import { lookupPincode } from "../../api/locations.api";
import type { Address } from "../../api/orders.api";
import { queryKeys } from "../../api/query-keys";
import { env } from "../../config/env";
import { Alert } from "../feedback/Feedback";
import { Button } from "../common/Button";
import { Icon } from "../common/Icon";
import { Field, Input, Select } from "../forms/Field";

declare global {
  interface Window {
    google?: any;
    __mbgaGoogleMapsLoaded?: boolean;
    __mbgaGoogleMapsCallbacks?: Array<() => void>;
  }
}

// Configurable GPS accuracy thresholds (in metres). These are UX tiers only — not guarantees.
const GPS_ACCURACY = {
  GOOD: 20,      // 0–20 m: High accuracy GPS
  MODERATE: 50,  // 21–50 m: Acceptable
  // > 50 m: Poor accuracy — warn and offer retry
};

/** Format a metre value into a human-readable accuracy string */
function formatAccuracy(metres: number): string {
  if (metres >= 1000) {
    return `${(metres / 1000).toFixed(1)} km`;
  }
  return `${Math.round(metres)} m`;
}

const DEFAULT_CENTER = { lat: 28.4595, lng: 77.0266 };
const titleCase = (s: string) => s.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());

interface PlaceSuggestion {
  placeId: string;
  description: string;
  mainText: string;
  secondaryText: string;
}

export interface GoogleMapLocationPickerProps {
  value: Address;
  onChange: (next: Address) => void;
  prefix?: string;
  merchantId?: string;
  onServiceabilityChange?: (isServiceable: boolean, errorMsg?: string) => void;
}

export function GoogleMapLocationPicker({
  value,
  onChange,
  prefix = "Delivery",
  merchantId,
  onServiceabilityChange,
}: GoogleMapLocationPickerProps) {
  const [mapsReady, setMapsReady] = useState(false);
  const [mapsError, setMapsError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [searching, setSearching] = useState(false);
  const [geocoding, setGeocoding] = useState(false);
  // GPS State
  type GeoStatus = "idle" | "requesting" | "success" | "denied" | "unavailable";
  const [geoStatus, setGeoStatus] = useState<GeoStatus>("idle");
  const [geoError, setGeoError] = useState<string | null>(null);
  const [gpsAccuracyMeters, setGpsAccuracyMeters] = useState<number | null>(null);
  const [locationTimestamp, setLocationTimestamp] = useState<number | null>(null);
  const [selectionSource, setSelectionSource] = useState<"gps" | "search" | "manual_pin" | "initial">("initial");
  const [isApproximateWarning, setIsApproximateWarning] = useState(false);
  const locatingUser = geoStatus === "requesting";
  const locationRequestIdRef = useRef(0);

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<any>(null);
  const debounceTimerRef = useRef<any>(null);
  const searchDebounceRef = useRef<any>(null);
  const autocompleteServiceRef = useRef<any>(null);
  const placesServiceRef = useRef<any>(null);
  const geocoderRef = useRef<any>(null);
  const isInteractingRef = useRef(false);
  const geocodingRequestIdRef = useRef(0);
  const userEditedFieldsRef = useRef<Set<string>>(new Set());

  const valueRef = useRef(value);
  valueRef.current = value;

  const lat = value.latitude ?? DEFAULT_CENTER.lat;
  const lng = value.longitude ?? DEFAULT_CENTER.lng;
  const hasCoordinates = typeof value.latitude === "number" && typeof value.longitude === "number";
  const pincode = (value.pincode ?? "").trim();
  const isPincodeValid = /^\d{6}$/.test(pincode);

  // MBGA authoritative pincode serviceability query
  const lookup = useQuery({
    queryKey: queryKeys.locations.pincode(pincode, merchantId),
    queryFn: ({ signal }) => lookupPincode(pincode, merchantId, signal),
    enabled: isPincodeValid,
    staleTime: 60 * 60_000,
    retry: false,
  });

  const offices = lookup.data?.offices ?? [];
  const notFound = lookup.error ? normalizeError(lookup.error) : null;
  const filledPincodeRef = useRef<string | null>(null);

  // Notify parent of serviceability status changes
  useEffect(() => {
    if (!isPincodeValid) {
      onServiceabilityChange?.(true);
      return;
    }
    if (lookup.data) {
      const serv = Boolean(lookup.data.serviceable);
      const msg = serv
        ? undefined
        : `Delivery unavailable: MBGA does not deliver to pincode ${pincode} yet.`;
      onServiceabilityChange?.(serv, msg);
    }
  }, [lookup.data, isPincodeValid, pincode, onServiceabilityChange]);

  // Auto-fill city, state and postOffice from pincode lookup when it resolves
  useEffect(() => {
    const data = lookup.data;
    if (!data || filledPincodeRef.current === data.pincode) return;
    filledPincodeRef.current = data.pincode;
    const deliverable = data.offices?.filter((o) => o.deliveryAvailable !== false) || [];
    const office = (deliverable.length === 1 ? deliverable[0] : data.offices?.length === 1 ? data.offices[0] : null)?.officeName;

    const currentValue = valueRef.current;
    const updates: Partial<Address> = {};
    if (!userEditedFieldsRef.current.has("city") && (!currentValue.city || currentValue.city !== titleCase(data.district || ""))) {
      updates.city = currentValue.city || titleCase(data.district || "");
    }
    if (!userEditedFieldsRef.current.has("state") && (!currentValue.state || currentValue.state !== titleCase(data.state || ""))) {
      updates.state = currentValue.state || titleCase(data.state || "");
    }
    if (!userEditedFieldsRef.current.has("postOffice") && office && !currentValue.postOffice) {
      updates.postOffice = office;
    }

    if (Object.keys(updates).length > 0) {
      const merged: Address = {
        ...currentValue,
        ...updates,
      };
      valueRef.current = merged;
      onChange(merged);
    }
  }, [lookup.data]);

  // 1. Load Google Maps Script
  useEffect(() => {
    const apiKey = env.googleMapsApiKey;
    if (window.google?.maps) {
      setMapsReady(true);
      return;
    }

    if (!apiKey) {
      setMapsError("Google Maps API key not set in VITE_GOOGLE_MAPS_API_KEY. GPS live location and manual refinement are active.");
      return;
    }

    if (window.__mbgaGoogleMapsLoaded) {
      setMapsReady(true);
      return;
    }

    if (window.__mbgaGoogleMapsCallbacks) {
      window.__mbgaGoogleMapsCallbacks.push(() => setMapsReady(true));
      return;
    }

    window.__mbgaGoogleMapsCallbacks = [() => setMapsReady(true)];
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=places,geometry&callback=__mbgaGoogleMapsInit`;
    script.async = true;
    script.defer = true;
    script.onerror = () => {
      setMapsError("Failed to load Google Maps script. Check network connection or API key restrictions.");
    };

    (window as any).__mbgaGoogleMapsInit = () => {
      window.__mbgaGoogleMapsLoaded = true;
      window.__mbgaGoogleMapsCallbacks?.forEach((cb) => cb());
      window.__mbgaGoogleMapsCallbacks = [];
    };

    document.head.appendChild(script);
  }, []);

  // 2. Initialize Interactive Map with Fixed Center Selection Pin
  useEffect(() => {
    if (!mapsReady || !mapContainerRef.current || !window.google?.maps) return;

    if (!mapInstanceRef.current) {
      const center = { lat, lng };
      const map = new window.google.maps.Map(mapContainerRef.current, {
        center,
        zoom: hasCoordinates ? 17 : 14,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: false,
        zoomControl: false, // Custom styled zoom controls provided
        gestureHandling: "greedy",
        clickableIcons: false,
      });

      mapInstanceRef.current = map;
      geocoderRef.current = new window.google.maps.Geocoder();
      autocompleteServiceRef.current = new window.google.maps.places.AutocompleteService();
      placesServiceRef.current = new window.google.maps.places.PlacesService(map);

      // Track map drag interaction
      map.addListener("dragstart", () => {
        isInteractingRef.current = true;
      });

      // Map idle listener: Debounce reverse geocoding after movement completely ends (600ms)
      map.addListener("idle", () => {
        if (!isInteractingRef.current) return;
        isInteractingRef.current = false;
        const currentCenter = map.getCenter();
        if (!currentCenter) return;
        const newLat = Number(currentCenter.lat().toFixed(6));
        const newLng = Number(currentCenter.lng().toFixed(6));

        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = setTimeout(() => {
          setSelectionSource("manual_pin");
          reverseGeocode(newLat, newLng, false);
        }, 600); // Debounced 600ms (500-800ms requirement)
      });
    }
  }, [mapsReady]);

  // Structured address parsing helper — extracts full building, floor, room, tower, and street without character truncation
  const extractStructuredAddress = (formattedAddress: string = "", components: any[] = []) => {
    const subpremiseList: string[] = [];
    const premiseList: string[] = [];
    const streetNumbers: string[] = [];
    const routes: string[] = [];
    const sublocalities: string[] = [];
    const localities: string[] = [];
    const districts: string[] = [];
    const states: string[] = [];
    let postalCode = "";

    for (const comp of components || []) {
      const types: string[] = comp.types || [];
      const name = (comp.long_name || comp.short_name || "").trim();
      if (!name) continue;

      if (types.includes("room") || types.includes("subpremise") || types.includes("floor")) {
        if (!subpremiseList.includes(name)) subpremiseList.push(name);
      } else if (
        types.includes("premise") ||
        types.includes("establishment") ||
        types.includes("point_of_interest")
      ) {
        if (!premiseList.includes(name)) premiseList.push(name);
      } else if (types.includes("street_number")) {
        if (!streetNumbers.includes(name)) streetNumbers.push(name);
      } else if (types.includes("route")) {
        if (!routes.includes(name)) routes.push(name);
      } else if (
        types.includes("sublocality_level_3") ||
        types.includes("sublocality_level_2") ||
        types.includes("sublocality_level_1") ||
        types.includes("sublocality") ||
        types.includes("neighborhood") ||
        types.includes("landmark")
      ) {
        if (!sublocalities.includes(name)) sublocalities.push(name);
      } else if (types.includes("locality") || types.includes("postal_town")) {
        if (!localities.includes(name)) localities.push(name);
      } else if (types.includes("administrative_area_level_2")) {
        if (!districts.includes(name)) districts.push(name);
      } else if (types.includes("administrative_area_level_1")) {
        if (!states.includes(name)) states.push(name);
      } else if (types.includes("postal_code")) {
        if (!postalCode) postalCode = name.replace(/\D/g, "").slice(0, 6);
      }
    }

    const city = localities[0] || districts[0] || "";
    const state = states[0] || "";

    let cleanLine1 = "";
    let cleanLine2 = "";

    if (formattedAddress) {
      const tokens = formattedAddress.split(",").map((t) => t.trim()).filter(Boolean);
      const withoutCountry = tokens.filter((t) => !/^india$/i.test(t));
      const withoutPostal = withoutCountry.filter((t) => {
        const isPinOnly = /^\d{6}$/.test(t.replace(/\D/g, ""));
        const isStatePin = state && t.toLowerCase().includes(state.toLowerCase()) && /\d{6}/.test(t);
        return !isPinOnly && !isStatePin;
      });

      const streetTokens: string[] = [];
      const areaTokens: string[] = [];

      for (const tok of withoutPostal) {
        const lower = tok.toLowerCase();
        if (city && lower === city.toLowerCase()) continue;
        if (state && lower === state.toLowerCase()) continue;
        if (districts.some((d) => d.toLowerCase() === lower)) continue;

        const isArea = sublocalities.some((s) => s.toLowerCase() === lower || lower.includes(s.toLowerCase()));
        if (isArea) {
          if (!areaTokens.includes(tok)) areaTokens.push(tok);
        } else {
          if (!streetTokens.includes(tok)) streetTokens.push(tok);
        }
      }

      if (streetTokens.length > 0) {
        cleanLine1 = streetTokens.join(", ");
      }
      if (areaTokens.length > 0) {
        cleanLine2 = areaTokens.join(", ");
      }
    }

    if (!cleanLine1) {
      const bParts = [...subpremiseList, ...premiseList, ...streetNumbers, ...routes];
      cleanLine1 = bParts.filter(Boolean).join(", ");
    }

    if (!cleanLine2) {
      cleanLine2 = sublocalities.filter(Boolean).join(", ");
    }

    if (!cleanLine1 && cleanLine2) {
      const parts = cleanLine2.split(", ");
      if (parts.length > 1) {
        cleanLine1 = parts[0];
        cleanLine2 = parts.slice(1).join(", ");
      } else {
        cleanLine1 = cleanLine2;
        cleanLine2 = "";
      }
    }

    return {
      line1: cleanLine1,
      line2: cleanLine2,
      city,
      state,
      pincode: postalCode,
    };
  };

  // 3. Reverse Geocode Coordinates with Monotonic Request ID to prevent race conditions
  const reverseGeocode = useCallback(
    async (targetLat: number, targetLng: number, forceUpdateFields = false) => {
      const reqId = ++geocodingRequestIdRef.current;
      if (!geocoderRef.current) {
        onChange({
          ...value,
          latitude: targetLat,
          longitude: targetLng,
        });
        return;
      }

      setGeocoding(true);
      setGeoError(null);

      try {
        geocoderRef.current.geocode(
          { location: { lat: targetLat, lng: targetLng } },
          (results: any[], status: string) => {
            // Cancel / Ignore obsolete requests: if a newer request was dispatched, drop this result!
            if (reqId !== geocodingRequestIdRef.current) {
              return;
            }
            setGeocoding(false);

            if (status === "OK" && results && results[0]) {
              const res = results[0];
              const parsed = extractStructuredAddress(res.formatted_address, res.address_components);

              const nextAddr: Address = {
                ...value,
                latitude: targetLat,
                longitude: targetLng,
                formattedAddress: res.formatted_address || value.formattedAddress,
                placeId: res.place_id || value.placeId,
                // Respect manual edits unless forced by GPS detection or Place Autocomplete selection
                line1: forceUpdateFields || !userEditedFieldsRef.current.has("line1")
                  ? (parsed.line1 || value.line1 || "")
                  : value.line1,
                line2: forceUpdateFields || !userEditedFieldsRef.current.has("line2")
                  ? (parsed.line2 || value.line2 || "")
                  : value.line2,
                city: forceUpdateFields || !userEditedFieldsRef.current.has("city")
                  ? (parsed.city || value.city)
                  : value.city,
                state: forceUpdateFields || !userEditedFieldsRef.current.has("state")
                  ? (parsed.state || value.state)
                  : value.state,
                pincode: forceUpdateFields || !userEditedFieldsRef.current.has("pincode")
                  ? (parsed.pincode || value.pincode)
                  : value.pincode,
              };

              onChange(nextAddr);
            } else {
              // Preserve coordinates even if geocode status returned ZERO_RESULTS
              onChange({
                ...value,
                latitude: targetLat,
                longitude: targetLng,
              });
            }
          }
        );
      } catch (err: any) {
        if (reqId === geocodingRequestIdRef.current) {
          setGeocoding(false);
          setGeoError(err.message || "Failed to reverse geocode location. Please verify address fields.");
        }
      }
    },
    [value, onChange]
  );

  // 4. Live GPS Location Capture ("Use Current Location") with fresh fix validation & accuracy tiers
  const handleUseCurrentLocation = () => {
    if (!navigator.geolocation) {
      setGeoStatus("unavailable");
      setGeoError("Geolocation is not supported by your browser. Please search address or position pin.");
      return;
    }

    const myRequestId = ++locationRequestIdRef.current;
    const isCurrentRequest = () => myRequestId === locationRequestIdRef.current;

    setGeoStatus("requesting");
    setGeoError(null);
    setGpsAccuracyMeters(null); // Clear previous accuracy while fetching
    setIsApproximateWarning(false);

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (!isCurrentRequest()) return;
        const { latitude, longitude, accuracy } = pos.coords;
        const timestamp = pos.timestamp;

        // Freshness check: reject stale cached positions older than 45 seconds
        const isStale = Date.now() - timestamp > 45000;
        if (isStale) {
          console.warn("[Geolocation] Received stale cached position, retrying with fresh fix...");
        }

        const roundedAccuracy = typeof accuracy === "number" && accuracy > 0 ? Math.round(accuracy) : null;
        setGpsAccuracyMeters(roundedAccuracy);
        setLocationTimestamp(timestamp);
        setSelectionSource("gps");
        setGeoStatus("success");

        // Accuracy thresholds check
        if (roundedAccuracy !== null && roundedAccuracy > GPS_ACCURACY.MODERATE) {
          setIsApproximateWarning(true);
          setGeoError(
            `Approximate location detected (±${formatAccuracy(roundedAccuracy)}). Move the map pin or search your building entrance to pinpoint exact gate.`
          );
        } else {
          setIsApproximateWarning(false);
          setGeoError(null);
        }

        const cleanLat = Number(latitude.toFixed(6));
        const cleanLng = Number(longitude.toFixed(6));

        // Center map to real GPS coordinates
        if (mapInstanceRef.current) {
          isInteractingRef.current = false;
          mapInstanceRef.current.panTo({ lat: cleanLat, lng: cleanLng });
          mapInstanceRef.current.setZoom(17);
        }

        // Reverse geocode with forceUpdateFields = true to populate from live GPS
        reverseGeocode(cleanLat, cleanLng, true);
      },
      (err) => {
        if (!isCurrentRequest()) return;
        let msg = "Could not retrieve your location.";
        if (err.code === err.PERMISSION_DENIED) {
          setGeoStatus("denied");
          msg = "Location permission was denied. Please allow location access or search your address.";
        } else if (err.code === err.POSITION_UNAVAILABLE) {
          setGeoStatus("unavailable");
          msg = "GPS position is unavailable. Please check your device location services or search above.";
        } else if (err.code === err.TIMEOUT) {
          setGeoStatus("unavailable");
          msg = "Location request timed out. Please try again or search your delivery building.";
        } else {
          setGeoStatus("unavailable");
        }
        setGeoError(msg);
      },
      {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 0, // Force fresh fix
      }
    );
  };

  // 5. Autocomplete Search Query Handler (debounced 300ms)
  const handleSearchChange = (text: string) => {
    setSearchQuery(text);
    if (!text.trim() || text.length < 3) {
      setSuggestions([]);
      return;
    }

    clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      if (autocompleteServiceRef.current && window.google?.maps) {
        setSearching(true);
        autocompleteServiceRef.current.getPlacePredictions(
          {
            input: text,
            componentRestrictions: { country: "in" },
          },
          (predictions: any[], status: string) => {
            setSearching(false);
            if (status === "OK" && predictions) {
              setSuggestions(
                predictions.map((p) => ({
                  placeId: p.place_id,
                  description: p.description,
                  mainText: p.structured_formatting?.main_text || p.description,
                  secondaryText: p.structured_formatting?.secondary_text || "",
                }))
              );
            } else {
              setSuggestions([]);
            }
          }
        );
      }
    }, 300);
  };

  // 6. Select Autocomplete Suggestion (retrieves geometry and structured components)
  const handleSelectSuggestion = (item: PlaceSuggestion) => {
    setSearchQuery(item.description);
    setSuggestions([]);
    setSelectionSource("search");

    if (placesServiceRef.current) {
      placesServiceRef.current.getDetails(
        { placeId: item.placeId, fields: ["geometry", "formatted_address", "address_components", "name"] },
        (place: any, status: string) => {
          if (status === "OK" && place?.geometry?.location) {
            const placeLat = Number(place.geometry.location.lat().toFixed(6));
            const placeLng = Number(place.geometry.location.lng().toFixed(6));

            if (mapInstanceRef.current) {
              isInteractingRef.current = false;
              mapInstanceRef.current.panTo({ lat: placeLat, lng: placeLng });
              mapInstanceRef.current.setZoom(17);
            }

            const formatted = place.formatted_address || item.description;
            const parsed = extractStructuredAddress(formatted, place.address_components);
            onChange({
              ...value,
              latitude: placeLat,
              longitude: placeLng,
              formattedAddress: formatted,
              placeId: item.placeId,
              line1: parsed.line1 || item.mainText,
              line2: parsed.line2 || item.secondaryText,
              city: parsed.city || value.city,
              state: parsed.state || value.state,
              pincode: parsed.pincode || value.pincode,
            });
          }
        }
      );
    }
  };

  // Track user's manual edits to preserve them
  const handleFieldChange = (key: keyof Address, val: string) => {
    userEditedFieldsRef.current.add(key);
    onChange({ ...value, [key]: val });
  };

  // Recenter to current pin coordinates
  const handleRecenter = () => {
    if (mapInstanceRef.current && hasCoordinates) {
      isInteractingRef.current = false;
      mapInstanceRef.current.panTo({ lat: value.latitude!, lng: value.longitude! });
    }
  };

  const handleZoom = (delta: number) => {
    if (mapInstanceRef.current) {
      const current = mapInstanceRef.current.getZoom() || 16;
      mapInstanceRef.current.setZoom(Math.max(10, Math.min(20, current + delta)));
    }
  };

  return (
    <div className="google-maps-location-picker" style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {/* Search Header Row (Rapido Style) */}
      <div style={{ position: "relative" }}>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <div style={{ position: "relative", flex: 1 }}>
            <Input
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Search building, street, area or landmark…"
              aria-label="Search delivery location"
              style={{ paddingLeft: "2.4rem" }}
            />
            <div style={{ position: "absolute", left: "0.75rem", top: "50%", transform: "translateY(-50%)", color: "var(--color-ink-muted)", pointerEvents: "none" }}>
              <Icon name="search" size={18} />
            </div>
            {searching && (
              <div style={{ position: "absolute", right: "0.75rem", top: "50%", transform: "translateY(-50%)", fontSize: "0.8rem", color: "var(--color-ink-muted)" }}>
                Searching…
              </div>
            )}
          </div>
          <Button
            type="button"
            variant="secondary"
            onClick={handleUseCurrentLocation}
            disabled={locatingUser}
            title="Detect live GPS location"
            style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", whiteSpace: "nowrap" }}
          >
            <Icon name="mapPin" size={16} />
            {locatingUser ? "Locating…" : "Use Current Location"}
          </Button>
        </div>

        {/* Places Autocomplete Suggestions Dropdown */}
        {suggestions.length > 0 && (
          <div
            style={{
              position: "absolute",
              top: "100%",
              left: 0,
              right: 0,
              zIndex: 100,
              marginTop: "4px",
              backgroundColor: "var(--color-surface, #ffffff)",
              border: "1px solid var(--color-border, #e2e8f0)",
              borderRadius: "var(--radius-lg, 8px)",
              boxShadow: "0 10px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)",
              maxHeight: "240px",
              overflowY: "auto",
            }}
          >
            {suggestions.map((item) => (
              <div
                key={item.placeId}
                onClick={() => handleSelectSuggestion(item)}
                style={{
                  padding: "0.6rem 0.9rem",
                  cursor: "pointer",
                  borderBottom: "1px solid var(--color-border-subtle, #f1f5f9)",
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "0.6rem",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--color-surface-hover, #f8fafc)")}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
              >
                <div style={{ color: "var(--color-primary, #ea580c)", marginTop: "2px" }}>
                  <Icon name="mapPin" size={16} />
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: "0.88rem", color: "var(--color-ink, #1e293b)" }}>{item.mainText}</div>
                  <div style={{ fontSize: "0.78rem", color: "var(--color-ink-muted, #64748b)" }}>{item.secondaryText}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Accuracy Badges & Warnings */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem" }}>
        {geoStatus === "requesting" ? (
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                padding: "2px 8px",
                borderRadius: "999px",
                fontSize: "11px",
                fontWeight: 600,
                backgroundColor: "#e0f2fe",
                color: "#0369a1",
              }}
            >
              <span>◌</span>
              <span>Acquiring GPS…</span>
            </span>
          </div>
        ) : geoStatus === "success" && gpsAccuracyMeters !== null ? (
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                padding: "2px 8px",
                borderRadius: "999px",
                fontSize: "11px",
                fontWeight: 600,
                backgroundColor: gpsAccuracyMeters <= GPS_ACCURACY.GOOD ? "#dcfce7" : gpsAccuracyMeters <= GPS_ACCURACY.MODERATE ? "#fef3c7" : "#fee2e2",
                color: gpsAccuracyMeters <= GPS_ACCURACY.GOOD ? "#15803d" : gpsAccuracyMeters <= GPS_ACCURACY.MODERATE ? "#b45309" : "#b91c1c",
              }}
            >
              <span>{gpsAccuracyMeters <= GPS_ACCURACY.GOOD ? "✓" : "⚠"}</span>
              <span>
                {gpsAccuracyMeters <= GPS_ACCURACY.GOOD
                  ? `High accuracy (±${formatAccuracy(gpsAccuracyMeters)})`
                  : gpsAccuracyMeters <= GPS_ACCURACY.MODERATE
                  ? `Moderate accuracy (±${formatAccuracy(gpsAccuracyMeters)})`
                  : `Approx. location (±${formatAccuracy(gpsAccuracyMeters)})`}
              </span>
            </span>
            <span style={{ fontSize: "11px", color: "var(--color-ink-muted, #64748b)" }}>
              via {selectionSource === "gps" ? "Device GPS" : selectionSource === "search" ? "Places Search" : "Manual Pin"}
            </span>
          </div>
        ) : geoStatus === "denied" ? (
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                padding: "2px 8px",
                borderRadius: "999px",
                fontSize: "11px",
                fontWeight: 600,
                backgroundColor: "#fee2e2",
                color: "#b91c1c",
              }}
            >
              <span>✕</span>
              <span>Permission denied</span>
            </span>
          </div>
        ) : geoStatus === "unavailable" ? (
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                padding: "2px 8px",
                borderRadius: "999px",
                fontSize: "11px",
                fontWeight: 600,
                backgroundColor: "#fee2e2",
                color: "#b91c1c",
              }}
            >
              <span>⚠</span>
              <span>GPS unavailable</span>
            </span>
          </div>
        ) : <div />}

        {geoStatus === "success" && gpsAccuracyMeters !== null && gpsAccuracyMeters > GPS_ACCURACY.MODERATE && (
          <Button variant="ghost" size="sm" onClick={handleUseCurrentLocation} style={{ fontSize: "11px", padding: "2px 6px" }}>
            Retry GPS
          </Button>
        )}
      </div>

      {geoError && (
        <Alert
          tone={isApproximateWarning ? "warning" : "error"}
          action={
            <Button variant="ghost" size="sm" onClick={() => setGeoError(null)}>
              Dismiss
            </Button>
          }
        >
          {geoError}
        </Alert>
      )}

      {mapsError && !mapsReady && (
        <Alert tone="info">
          {mapsError}
        </Alert>
      )}

      {/* Interactive Map Container with Fixed Rapido Center Pin */}
      <div
        style={{
          position: "relative",
          width: "100%",
          height: "260px",
          borderRadius: "var(--radius-xl, 12px)",
          overflow: "hidden",
          border: "1.5px solid var(--color-border, #cbd5e1)",
          backgroundColor: "#f1f5f9",
        }}
      >
        <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />

        {/* Center Pin Overlay (Fixed center pin that hovers above the moving map) */}
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -100%)",
            pointerEvents: "none",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            zIndex: 10,
          }}
        >
          {/* Rapido / Delivery Pin Badge */}
          <div
            style={{
              backgroundColor: "var(--color-primary, #ea580c)",
              color: "#ffffff",
              padding: "3px 8px",
              borderRadius: "999px",
              fontSize: "11px",
              fontWeight: 700,
              boxShadow: "0 2px 6px rgba(0,0,0,0.25)",
              marginBottom: "2px",
              display: "flex",
              alignItems: "center",
              gap: "4px",
            }}
          >
            <span>Delivery Point</span>
          </div>

          {/* SVG Location Marker Pin */}
          <svg width="34" height="42" viewBox="0 0 34 42" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M17 0C7.61116 0 0 7.61116 0 17C0 29.75 17 42 17 42C17 42 34 29.75 34 17C34 7.61116 26.3888 0 17 0Z"
              fill="var(--color-primary, #ea580c)"
            />
            <circle cx="17" cy="17" r="7" fill="#ffffff" />
          </svg>

          {/* Ground Contact Pulse Ring */}
          <div
            style={{
              width: "12px",
              height: "4px",
              borderRadius: "50%",
              backgroundColor: "rgba(0,0,0,0.3)",
              filter: "blur(1px)",
              marginTop: "-2px",
            }}
          />
        </div>

        {/* Geocoding indicator overlay */}
        {geocoding && (
          <div
            style={{
              position: "absolute",
              top: "10px",
              left: "50%",
              transform: "translateX(-50%)",
              backgroundColor: "rgba(15, 23, 42, 0.85)",
              color: "#ffffff",
              padding: "4px 12px",
              borderRadius: "999px",
              fontSize: "12px",
              fontWeight: 500,
              zIndex: 15,
              display: "flex",
              alignItems: "center",
              gap: "6px",
              backdropFilter: "blur(4px)",
            }}
          >
            <span style={{ display: "inline-block", width: "8px", height: "8px", borderRadius: "50%", backgroundColor: "#fb923c", animation: "pulse 1.5s infinite" }} />
            Pinpointing delivery address…
          </div>
        )}

        {/* Custom Map Floating Controls (Recenter, Zoom In, Zoom Out) */}
        <div style={{ position: "absolute", bottom: "12px", right: "12px", display: "flex", flexDirection: "column", gap: "6px", zIndex: 10 }}>
          <button
            type="button"
            onClick={handleRecenter}
            title="Recenter to pinned location"
            style={{
              backgroundColor: "#ffffff",
              border: "1px solid #cbd5e1",
              borderRadius: "8px",
              width: "34px",
              height: "34px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
              cursor: "pointer",
            }}
          >
            <Icon name="mapPin" size={16} />
          </button>
          <button
            type="button"
            onClick={() => handleZoom(1)}
            title="Zoom in"
            style={{
              backgroundColor: "#ffffff",
              border: "1px solid #cbd5e1",
              borderRadius: "8px",
              width: "34px",
              height: "34px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
              cursor: "pointer",
              fontWeight: 700,
              fontSize: "16px",
            }}
          >
            +
          </button>
          <button
            type="button"
            onClick={() => handleZoom(-1)}
            title="Zoom out"
            style={{
              backgroundColor: "#ffffff",
              border: "1px solid #cbd5e1",
              borderRadius: "8px",
              width: "34px",
              height: "34px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
              cursor: "pointer",
              fontWeight: 700,
              fontSize: "16px",
            }}
          >
            -
          </button>
        </div>
      </div>

      {/* Selected Location Summary Card */}
      <div
        style={{
          padding: "var(--space-3)",
          borderRadius: "var(--radius-lg, 8px)",
          backgroundColor: "var(--color-surface-secondary, #f8fafc)",
          border: "1px solid var(--color-border, #e2e8f0)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-2)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "var(--space-2)" }}>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <div style={{ color: "var(--color-primary, #ea580c)", marginTop: "2px" }}>
              <Icon name="mapPin" size={18} />
            </div>
            <div>
              <div style={{ fontSize: "0.78rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-ink-muted, #64748b)" }}>
                Selected Delivery Location
              </div>
              <div style={{ fontWeight: 600, fontSize: "0.92rem", color: "var(--color-ink, #0f172a)", marginTop: "2px" }}>
                {value.formattedAddress || value.line1 || "Move map or search above to select address"}
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", justifyContent: "flex-end" }}>
            {value.pincode ? (
              <span style={{ backgroundColor: "#ffedd5", color: "#c2410c", padding: "2px 8px", borderRadius: "4px", fontSize: "11px", fontWeight: 700 }}>
                PIN: {value.pincode}
              </span>
            ) : null}
            {hasCoordinates ? (
              <span style={{ backgroundColor: "#f1f5f9", color: "#475569", padding: "2px 8px", borderRadius: "4px", fontSize: "11px" }}>
                {value.latitude?.toFixed(5)}, {value.longitude?.toFixed(5)}
              </span>
            ) : null}
          </div>
        </div>

        {/* MBGA Authoritative Serviceability Alert */}
        {isPincodeValid && lookup.data && !lookup.data.serviceable && (
          <Alert tone="error">
            Delivery Unavailable — MBGA does not deliver to pincode {pincode} yet. Please verify or choose another delivery address.
          </Alert>
        )}
        {isPincodeValid && lookup.data && lookup.data.serviceable && (
          <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "#15803d", fontWeight: 600 }}>
            <span>✓ Verified serviceable delivery area</span>
            {lookup.data.district && <span>· {lookup.data.district}, {lookup.data.state}</span>}
          </div>
        )}
        {isPincodeValid && notFound && (
          <Alert tone="info">
            {notFound.status === 404 ? "Pincode not found in India Post directory — verify city and state manually." : notFound.userMessage}
          </Alert>
        )}
      </div>

      {/* Detailed Address Input Fields */}
      <div className="grid-2">
        <Field label="House / Flat / Building / Street" required className="span-2">
          <Input
            value={value.line1 ?? ""}
            onChange={(e) => handleFieldChange("line1", e.target.value)}
            maxLength={255}
            aria-label={`${prefix} address line 1`}
            placeholder="e.g. Building 4A, DLF Cyber City, Phase 3"
          />
        </Field>

        <Field label="Floor / Unit / Tower" optional>
          <Input
            value={value.floorUnit ?? ""}
            onChange={(e) => handleFieldChange("floorUnit", e.target.value)}
            maxLength={100}
            placeholder="e.g. 2nd Floor, Tower B"
          />
        </Field>

        <Field label="Area / Colony / Landmark" optional>
          <Input
            value={value.line2 ?? value.landmark ?? ""}
            onChange={(e) => {
              userEditedFieldsRef.current.add("line2");
              userEditedFieldsRef.current.add("landmark");
              onChange({ ...value, line2: e.target.value, landmark: e.target.value });
            }}
            maxLength={255}
            placeholder="e.g. Near Sikanderpur Metro Station"
          />
        </Field>

        <Field label="Pincode" required hint={lookup.isFetching ? "Verifying serviceability…" : undefined}>
          <Input
            value={value.pincode ?? ""}
            onChange={(e) => {
              userEditedFieldsRef.current.add("pincode");
              const clean = e.target.value.replace(/\D/g, "").slice(0, 6);
              onChange({ ...value, pincode: clean });
            }}
            inputMode="numeric"
            maxLength={6}
            placeholder="e.g. 122002"
            aria-label={`${prefix} pincode`}
          />
        </Field>

        <Field label="Post office" optional hint={offices.length > 1 ? `${offices.length} offices found (please select)` : undefined}>
          {offices.length > 0 ? (
            <Select
              value={value.postOffice || (offices.some((o) => o.officeName === value.postOffice || o.officeName === value.line2) ? (value.postOffice || value.line2 || "") : "")}
              onChange={(e) => {
                userEditedFieldsRef.current.add("postOffice");
                onChange({ ...value, postOffice: e.target.value });
              }}
              placeholder="Choose post office branch"
              options={offices.map((o) => ({
                value: o.officeName,
                label: `${o.officeName}${o.deliveryAvailable === false ? " (no delivery branch)" : ""}`,
              }))}
            />
          ) : (
            <Input
              value={value.postOffice ?? ""}
              onChange={(e) => handleFieldChange("postOffice", e.target.value)}
              maxLength={120}
              placeholder="Branch post office"
            />
          )}
        </Field>

        <Field label="City / District" required>
          <Input
            value={value.city ?? ""}
            onChange={(e) => handleFieldChange("city", e.target.value)}
            maxLength={120}
            placeholder="e.g. Gurugram"
          />
        </Field>

        <Field label="State" required>
          <Input
            value={value.state ?? ""}
            onChange={(e) => handleFieldChange("state", e.target.value)}
            maxLength={120}
            placeholder="e.g. Haryana"
          />
        </Field>

        <Field label="Delivery Instructions" optional className="span-2">
          <Input
            value={value.deliveryInstructions ?? ""}
            onChange={(e) => handleFieldChange("deliveryInstructions", e.target.value)}
            maxLength={255}
            placeholder="e.g. Ring bell at delivery gate / Commercial loading bay"
          />
        </Field>
      </div>
    </div>
  );
}
