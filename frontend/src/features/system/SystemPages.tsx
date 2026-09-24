import { useEffect } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "../../auth/auth-context";
import { CHANNEL_HOME } from "../../auth/permissions";
import { ButtonLink, Button } from "../../components/common/Button";
import { BrandMark } from "../../components/common/StatusBadge";
import { EmptyState } from "../../components/feedback/Feedback";
import { PageHeader } from "../../components/layout/Page";

function useTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · MBGA`;
  }, [title]);
}

function StandalonePage({ children }: { children: ReactNode }) {
  return (
    <main className="full-page-state" id="main-content">
      <div className="card" style={{ width: "min(560px, 100%)" }}>
        <div className="card__body">
          <div className="row" style={{ justifyContent: "center", marginBottom: "var(--space-2)" }}>
            <BrandMark />
          </div>
          {children}
        </div>
      </div>
    </main>
  );
}

function homePath(channel: ReturnType<typeof useAuth>["channel"]) {
  return channel ? CHANNEL_HOME[channel] : "/login";
}

export function NotFoundPage() {
  const { channel } = useAuth();
  useTitle("Page not found");
  return (
    <StandalonePage>
      <EmptyState
        icon="search"
        title="We couldn’t find that page"
        description="The link may be out of date, or the page may have moved."
        action={
          <ButtonLink to={homePath(channel)} variant="primary">
            {channel ? "Go to dashboard" : "Go to sign in"}
          </ButtonLink>
        }
      />
    </StandalonePage>
  );
}

/** Unknown address inside a panel: keeps the navigation visible. */
export function NotFoundContent() {
  const { channel } = useAuth();
  useTitle("Page not found");
  return (
    <div className="card">
      <EmptyState
        icon="search"
        title="We couldn’t find that page"
        description="The link may be out of date, or the page may have moved."
        action={
          <ButtonLink to={homePath(channel)} variant="secondary">
            Back to dashboard
          </ButtonLink>
        }
      />
    </div>
  );
}

/** Shown inside the app shell when the signed-in account lacks a permission. */
export function AccessDeniedContent() {
  const { channel } = useAuth();
  useTitle("Access denied");
  return (
    <div className="card">
      <EmptyState
        icon="lock"
        tone="warning"
        title="You don’t have access to this page"
        description="Your account does not have permission to open this page. If you need access, contact your administrator."
        action={
          <ButtonLink to={homePath(channel)} variant="secondary">
            Back to dashboard
          </ButtonLink>
        }
      />
    </div>
  );
}

/** Standalone page used when a signed-in account opens another panel's address. */
export function AccessDeniedPage() {
  const { channel } = useAuth();
  useTitle("Access denied");
  return (
    <StandalonePage>
      <EmptyState
        icon="lock"
        tone="warning"
        title="This area is not part of your panel"
        description={
          channel === "merchant"
            ? "You are signed in to the Merchant panel. Admin pages are only available to MBGA administrators."
            : "You are signed in to the Admin panel. To use the Merchant panel, sign out and sign in with a merchant account."
        }
        action={
          <ButtonLink to={homePath(channel)} variant="primary">
            Go to my dashboard
          </ButtonLink>
        }
      />
    </StandalonePage>
  );
}

export function ServiceUnavailablePage({ onRetry, message }: { onRetry?: () => void; message?: string }) {
  const auth = useAuth();
  useTitle("Service unavailable");
  return (
    <StandalonePage>
      <EmptyState
        icon="refresh"
        tone="error"
        title="The service is temporarily unavailable"
        description={message ?? "We could not load your account. Check your connection and try again."}
        action={
          <>
            {onRetry ? (
              <Button variant="primary" icon="refresh" onClick={onRetry}>
                Try again
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => void auth.signOut()}>
              Sign out
            </Button>
          </>
        }
      />
    </StandalonePage>
  );
}

const UNAVAILABLE_COPY: Record<string, { title: string; description: string }> = {
  "admin-customers": {
    title: "Customers",
    description: "Review customer applications, check submitted documents, and approve or reject customers."
  },
  "merchant-customers": { title: "Customers", description: "View and manage the customers your business serves." },
  "merchant-orders": { title: "Orders", description: "Create, assign and track cylinder orders." },
  "merchant-inventory": { title: "Inventory", description: "Track filled and empty cylinder stock." },
  "merchant-payments": { title: "Payments", description: "Record and reconcile customer payments." },
  "merchant-reports": { title: "Reports", description: "Business reports for your operations." }
};

/** Controlled placeholder for modules whose backend is not released yet. No data is shown. */
export function FeatureUnavailablePage({ feature }: { feature: keyof typeof UNAVAILABLE_COPY }) {
  const { channel } = useAuth();
  const copy = UNAVAILABLE_COPY[feature];
  return (
    <div className="page">
      <PageHeader title={copy.title} description={copy.description} />
      <div className="card">
        <EmptyState
          icon="clock"
          title="This feature is not available in the current backend release."
          description="It will appear here as soon as it is ready. Nothing needs to be done in the meantime."
          action={
            <Link to={homePath(channel)} className="btn btn--secondary">
              Back to dashboard
            </Link>
          }
        />
      </div>
    </div>
  );
}
