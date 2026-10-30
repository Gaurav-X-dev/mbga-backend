/** Downloads rows as CSV in the browser. Values are quoted; spreadsheet formulas are neutralised. */
export function downloadCsv(filename: string, header: string[], rows: Array<Array<string | number | null | undefined>>) {
  const escape = (value: string | number | null | undefined) => {
    let text = value === null || value === undefined ? "" : String(value);
    // Only text can smuggle a formula; a real number like -115 must stay a number Excel can sum.
    if (typeof value !== "number" && /^[=+\-@]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  };
  const csv = [header, ...rows].map((line) => line.map(escape).join(",")).join("\r\n");
  // The BOM tells Excel the file is UTF-8, so ₹ and non-English names open correctly.
  const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
