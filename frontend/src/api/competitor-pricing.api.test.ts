import { afterEach, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { createCompetitorPricingApi, competitorPricingApi } from "./competitor-pricing.api";

afterEach(() => vi.restoreAllMocks());
const filters = { pincode: "110001", customerType: "Retail (Domestic)", cylinderType: "LPG_19KG" };

it("keeps merchant API requests free of admin scope", async () => {
  const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: [] });
  await competitorPricingApi.comparison(filters);
  expect(get).toHaveBeenCalledWith("/merchant/competitor-pricing/comparison", { params: filters, signal: undefined });
});

it("scopes admin reads, surveys, depot updates and benchmarks to the selected merchant", async () => {
  const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: [] });
  const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { success: true } });
  const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({ data: {} });
  const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: { success: true } });
  const api = createCompetitorPricingApi("merchant-one");
  await api.comparison(filters);
  expect(get).toHaveBeenLastCalledWith("/admin/competitor-pricing/comparison", { params: { ...filters, merchantId: "merchant-one" }, signal: undefined });
  const input = { competitorId: "brand", cylinderType: "LPG_19KG", customerType: "Retail", price: 1900, effectiveDate: "2026-11-02", locationPincode: "110001" };
  await api.survey(input);
  expect(post).toHaveBeenLastCalledWith("/admin/competitor-pricing/prices", input, { params: { merchantId: "merchant-one" } });
  await api.updateDepot("brand", { city: "Delhi" });
  expect(patch).toHaveBeenLastCalledWith("/admin/competitor-pricing/competitors/brand", { depotAddress: { city: "Delhi" }, notes: undefined }, { params: { merchantId: "merchant-one" } });
  await api.benchmark({ cylinderType: "LPG_19KG", price: 1880 });
  expect(put).toHaveBeenLastCalledWith("/admin/pricing/base-rates", { cylinderType: "LPG_19KG", price: 1880 }, { params: { merchantId: "merchant-one" } });
  await createCompetitorPricingApi("merchant-two").brands("");
  expect(get).toHaveBeenLastCalledWith("/admin/competitor-pricing/competitors", { params: { merchantId: "merchant-two", search: undefined }, signal: undefined });
});

it("uses explicit admin merchant scope for download requests too", async () => {
  const get = vi.spyOn(apiClient, "get").mockRejectedValue(new Error("No download in this test"));
  const params = { ...filters, timeframe: "30D" as const, format: "XLSX" as const, dataset: "comparison" as const, includeAudit: true };
  await expect(createCompetitorPricingApi("merchant-one").exportReport(params)).rejects.toThrow();
  expect(get).toHaveBeenCalledWith("/admin/competitor-pricing/export", { params: { ...params, merchantId: "merchant-one" }, responseType: "blob", timeout: 60000 });
  expect(() => createCompetitorPricingApi("")).toThrow("Select a merchant");
});
