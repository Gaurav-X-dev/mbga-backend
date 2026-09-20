import { useEffect } from "react";
import type { FieldErrors } from "react-hook-form";
import { useBlocker } from "react-router-dom";

import { Button } from "../common/Button";
import { Alert } from "../feedback/Feedback";
import { Modal } from "../feedback/Dialogs";

/** Lists every invalid field with a link that moves focus to it. */
export function FormErrorSummary({
  errors,
  labels,
  message
}: {
  errors: FieldErrors;
  labels: Record<string, string>;
  message?: string | null;
}) {
  // List problems in the order the fields appear on screen.
  const order = Object.keys(labels);
  const rank = (name: string) => (order.includes(name) ? order.indexOf(name) : order.length);
  const entries = Object.entries(errors)
    .filter(([, value]) => value && typeof value.message === "string")
    .sort(([a], [b]) => rank(a) - rank(b));
  if (entries.length === 0 && !message) return null;
  return (
    <Alert tone="error" title={message ?? "Please check the highlighted information."}>
      {entries.length > 0 ? (
        <ul>
          {entries.map(([name, value]) => (
            <li key={name}>
              <a
                href={`#field-${name}`}
                onClick={(event) => {
                  event.preventDefault();
                  document.getElementById(`field-${name}`)?.focus();
                }}
              >
                {labels[name] ?? "Field"}: {String(value?.message)}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </Alert>
  );
}

/** Warns before leaving a form with unsaved changes (in-app navigation and tab close). */
export function UnsavedChangesGuard({ when }: { when: boolean }) {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => when && currentLocation.pathname !== nextLocation.pathname
  );

  useEffect(() => {
    if (!when) return;
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [when]);

  return (
    <Modal
      open={blocker.state === "blocked"}
      title="Leave without saving?"
      description="The information you entered on this page has not been saved."
      onClose={() => blocker.reset?.()}
      role="alertdialog"
      footer={
        <>
          <Button variant="secondary" onClick={() => blocker.reset?.()}>
            Stay on this page
          </Button>
          <Button variant="danger" onClick={() => blocker.proceed?.()}>
            Leave page
          </Button>
        </>
      }
    />
  );
}
