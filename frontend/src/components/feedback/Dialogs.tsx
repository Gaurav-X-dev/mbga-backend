import { useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

import { normalizeError } from "../../api/errors";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { Button, IconButton, type ButtonVariant } from "../common/Button";
import { Alert } from "./Feedback";

type ModalProps = {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  children?: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  /** Prevent closing (e.g. while a request is running). */
  busy?: boolean;
  role?: "dialog" | "alertdialog";
};

export function Modal({ open, title, description, onClose, children, footer, wide, busy, role = "dialog" }: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const close = () => {
    if (!busy) onClose();
  };
  useFocusTrap(ref, open, close);
  if (!open) return null;
  return createPortal(
    <div
      className="overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={ref}
        className={`modal${wide ? " modal--wide" : ""}`}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
      >
        <div className="modal__header">
          <div>
            <h2 id={titleId} className="modal__title">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="modal__description">
                {description}
              </p>
            ) : null}
          </div>
          <IconButton icon="x" label="Close" onClick={close} disabled={busy} />
        </div>
        {children ? <div className="modal__body">{children}</div> : null}
        {footer ? <div className="modal__footer">{footer}</div> : null}
      </div>
    </div>,
    document.body
  );
}

type ConfirmationDialogProps = {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  confirmVariant?: ButtonVariant;
  onConfirm: () => Promise<unknown> | void;
  onClose: () => void;
  /** Optional extra content, e.g. a required reason field. */
  children?: ReactNode;
  confirmDisabled?: boolean;
};

/**
 * Used for every destructive or account-affecting action. Keeps itself open and shows
 * the safe error message if the action fails.
 */
export function ConfirmationDialog({
  open,
  title,
  description,
  confirmLabel,
  confirmVariant = "danger",
  onConfirm,
  onClose,
  children,
  confirmDisabled
}: ConfirmationDialogProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  async function handleConfirm() {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (caught) {
      setError(normalizeError(caught).userMessage);
    } finally {
      setPending(false);
    }
  }

  function handleClose() {
    setError(null);
    onClose();
  }

  return (
    <Modal
      open={open}
      title={title}
      description={description}
      onClose={handleClose}
      busy={pending}
      role="alertdialog"
      footer={
        <>
          <Button ref={cancelRef} variant="secondary" onClick={handleClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            variant={confirmVariant}
            onClick={() => void handleConfirm()}
            loading={pending}
            loadingText="Please wait…"
            disabled={confirmDisabled}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children || error ? (
        <div className="stack">
          {children}
          {error ? <Alert tone="error">{error}</Alert> : null}
        </div>
      ) : null}
    </Modal>
  );
}

type DrawerProps = {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
};

export function Drawer({ open, title, onClose, children, footer }: DrawerProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(ref, open, onClose);
  if (!open) return null;
  return createPortal(
    <div
      className="overlay overlay--drawer"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div ref={ref} className="drawer" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="drawer__header">
          <h2 id={titleId} className="drawer__title">
            {title}
          </h2>
          <IconButton icon="x" label="Close" onClick={onClose} />
        </div>
        <div className="drawer__body">{children}</div>
        {footer ? <div className="drawer__footer">{footer}</div> : null}
      </div>
    </div>,
    document.body
  );
}
