import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadCsv } from "./csv";

describe("downloadCsv", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps negative numbers numeric but neutralises formula-like text", async () => {
    let blob: Blob | undefined;
    // jsdom has no object URLs; stand them in.
    Object.assign(URL, {
      createObjectURL: (b: Blob) => {
        blob = b;
        return "blob:x";
      },
      revokeObjectURL: () => undefined
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    downloadCsv("t.csv", ["a", "b"], [[-115, "=SUM(A1)"]]);
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob!);
    });
    expect(text).toContain('"-115"');
    expect(text).toContain(`"'=SUM(A1)"`);
  });
});
