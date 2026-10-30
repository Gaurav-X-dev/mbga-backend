import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";

import { listInvoices, type InvoiceSummary } from "../../api/einvoice.api";
import { queryKeys } from "../../api/query-keys";
import { Card, PageHeader } from "../../components/layout/Page";
import { EInvoiceStatusCard } from "./EInvoiceStatusCard";

/**
 * GST filing, invoice by invoice.
 *
 * Only invoices that are *supposed* to be filed are listed, and that is the whole point of
 * the screen: a gas agency raises mostly domestic B2C invoices, which the portal does not
 * accept and which would bury the handful that matter. The rule - the customer has a GSTIN -
 * is the backend's, and this list applies the same one so the two cannot drift apart.
 */

function money(rupees: number) {
  return `₹${rupees.toLocaleString("en-IN")}`;
}

function issuedOn(value: string) {
  return new Date(value).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric"
  });
}

export function AdminEInvoicePage() {
  const [selected, setSelected] = useState<string | null>(null);

  const invoices = useQuery({
    queryKey: queryKeys.einvoice.invoices(),
    queryFn: ({ signal }) => listInvoices(signal)
  });

  // Filed through the portal only when the buyer is registered. Everything else is a cash
  // memo and has no business on a compliance screen.
  const filable: InvoiceSummary[] = (invoices.data ?? []).filter((row) =>
    Boolean((row.gstin ?? "").trim())
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="e-Invoice (GST)"
        description="IRN and e-Way Bill filing for invoices raised to registered buyers."
      />

      {invoices.isLoading ? (
        <Card className="p-6">
          <p className="text-gray-600">Loading invoices…</p>
        </Card>
      ) : invoices.isError ? (
        <Card className="p-6">
          <p className="text-red-600">Invoices could not be loaded.</p>
        </Card>
      ) : filable.length === 0 ? (
        <Card className="p-6">
          <p className="text-gray-600">
            No invoices to file. An invoice is sent to the portal only when the customer has a
            GSTIN — a domestic sale is B2C and is never filed.
          </p>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Invoice</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">GSTIN</th>
                <th className="px-4 py-3 text-right">Value</th>
                <th className="px-4 py-3">Issued</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {filable.map((row) => {
                const open = selected === row.id;
                return (
                  <Fragment key={row.id}>
                    <tr className="align-middle">
                      <td className="px-4 py-3 font-mono text-gray-900">{row.invoiceNumber}</td>
                      <td className="px-4 py-3 text-gray-900">{row.customerName}</td>
                      <td className="px-4 py-3 font-mono text-xs text-gray-600">{row.gstin}</td>
                      <td className="px-4 py-3 text-right text-gray-900">
                        {money(row.totalAmount)}
                        {row.totalAmount > 50000 ? (
                          <span className="ml-2 text-xs text-amber-700">+ e-Way Bill</span>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-gray-600">{issuedOn(row.issuedAt)}</td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => setSelected(open ? null : row.id)}
                          className="text-sm font-medium text-blue-700 hover:underline"
                        >
                          {open ? "Hide" : "Status"}
                        </button>
                      </td>
                    </tr>
                    {open ? (
                      <tr>
                        <td colSpan={6} className="bg-gray-50 px-4 py-4">
                          <EInvoiceStatusCard invoiceId={row.id} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

export default AdminEInvoicePage;
