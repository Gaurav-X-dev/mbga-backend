import { AxiosError, AxiosHeaders } from "axios";
import { expect, it } from "vitest";
import { apiClient } from "./client";

it("decodes JSON download failures before normalizing their error code", async () => {
  await expect(apiClient.get("/merchant/competitor-pricing/export", {
    responseType: "blob",
    adapter: async config => {
      throw new AxiosError("Export failed", "ERR_BAD_REQUEST", config, {}, {
        config, status: 422, statusText: "Unprocessable Content", headers: new AxiosHeaders({ "content-type": "application/json" }),
        data: { text: async () => JSON.stringify({ detail: { code: "COMPETITOR_EXPORT_LIMIT", message: "Too many rows", fields: [] } }) }
      });
    }
  })).rejects.toMatchObject({ status: 422, code: "COMPETITOR_EXPORT_LIMIT", userMessage: "More than 10,000 audit events match. Select a shorter date range and export again." });
});
