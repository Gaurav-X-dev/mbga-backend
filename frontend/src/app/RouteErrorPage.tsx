import { isRouteErrorResponse, useRouteError } from "react-router-dom";

import { Button } from "../components/common/Button";
import { EmptyState } from "../components/feedback/Feedback";

/** Last-resort screen for unexpected rendering errors. Never shows technical details. */
export function RouteErrorPage() {
  const error = useRouteError();
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  return (
    <main className="full-page-state" id="main-content">
      <div className="card" style={{ width: "min(560px, 100%)" }}>
        <EmptyState
          icon={notFound ? "search" : "alert"}
          tone={notFound ? "default" : "error"}
          title={notFound ? "We couldn’t find that page" : "Something went wrong"}
          description={
            notFound
              ? "The link may be out of date, or the page may have moved."
              : "This page could not be displayed. Reload the page to try again. If the problem continues, contact support."
          }
          action={
            <>
              <Button variant="primary" icon="refresh" onClick={() => window.location.reload()}>
                Reload page
              </Button>
              <Button variant="secondary" onClick={() => window.location.assign("/")}>
                Go to start
              </Button>
            </>
          }
        />
      </div>
    </main>
  );
}
