import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { normalizeError } from "../../api/errors";
import { importPostalLocations } from "../../api/locations.api";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert } from "../../components/feedback/Feedback";
import { formatNumber, humanize } from "../../utils/format";

/** Loads or refreshes the platform's pincode table from India Post's CSV. Not merchant-scoped. */
export function PostalImportButton() {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const mutation = useMutation({ mutationFn: (f: File) => importPostalLocations(f) });

  function close() {
    setFile(null);
    mutation.reset();
  }

  const result = mutation.data;
  // The response shape is not documented; show whatever counts it reports.
  const counts = result ? Object.entries(result).filter(([, v]) => typeof v === "number" || typeof v === "string") : [];

  return (
    <>
      <Button variant="secondary" icon="download" onClick={() => input.current?.click()} title="Import or update India Post pincodes">
        Import pincodes
      </Button>
      <input
        ref={input}
        type="file"
        accept=".csv,text/csv"
        hidden
        onChange={(e) => {
          setFile(e.target.files?.[0] ?? null);
          e.target.value = "";
        }}
      />
      <Modal
        open={file !== null}
        title="Import India Post pincodes"
        description="Adds new pincodes and updates existing ones for every merchant. Vehicle mappings are not changed."
        onClose={close}
        busy={mutation.isPending}
        footer={
          result ? (
            <Button onClick={close}>Done</Button>
          ) : (
            <>
              <Button variant="secondary" onClick={close} disabled={mutation.isPending}>
                Cancel
              </Button>
              <Button icon="check" onClick={() => file && mutation.mutate(file)} loading={mutation.isPending} loadingText="Importing…">
                Import
              </Button>
            </>
          )
        }
      >
        <div className="stack">
          {file ? (
            <p style={{ margin: 0 }}>
              <strong>{file.name}</strong> <span className="text-muted">({formatNumber(Math.round(file.size / 1024))} KB)</span>
            </p>
          ) : null}
          {mutation.isPending ? <Alert tone="info">Large files can take a few minutes. Keep this window open.</Alert> : null}
          {result ? (
            <Alert tone="success">
              Import finished.
              {counts.length ? (
                <ul className="list-plain" style={{ margin: "6px 0 0" }}>
                  {counts.map(([k, v]) => (
                    <li key={k}>
                      {humanize(k)}: <strong>{typeof v === "number" ? formatNumber(v) : String(v)}</strong>
                    </li>
                  ))}
                </ul>
              ) : null}
            </Alert>
          ) : null}
          {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
        </div>
      </Modal>
    </>
  );
}
