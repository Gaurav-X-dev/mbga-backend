import { Suspense, useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../../auth/auth-context";
import type { AuthChannel } from "../../auth/token-storage";
import { visibleNavigation } from "../../config/navigation";
import { ConfirmationDialog } from "../feedback/Dialogs";
import { LoadingSkeleton } from "../feedback/Feedback";
import { useToast } from "../feedback/toast-context";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const COLLAPSE_KEY = "mbga.web.sidebar-collapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

export function AppShell({ channel }: { channel: AuthChannel }) {
  const auth = useAuth();
  const toast = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [confirmEverywhere, setConfirmEverywhere] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const sections = visibleNavigation(channel, auth.permissions);

  useEffect(() => {
    setMobileOpen(false);
    // Move focus to the page on navigation so screen-reader users hear the new page.
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [location.pathname]);

  useEffect(() => {
    if (!mobileOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMobileOpen(false);
        menuButtonRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  function toggleCollapsed() {
    setCollapsed((value) => {
      try {
        window.localStorage.setItem(COLLAPSE_KEY, value ? "0" : "1");
      } catch {
        // Preference only; ignore storage failures.
      }
      return !value;
    });
  }

  async function handleSignOut() {
    setSigningOut(true);
    await auth.signOut();
    navigate("/login", { replace: true });
  }

  const shellClass = ["app-shell", collapsed && "is-collapsed", mobileOpen && "is-mobile-open"].filter(Boolean).join(" ");

  return (
    <div className={shellClass}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <Sidebar channel={channel} sections={sections} collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
      {mobileOpen ? (
        <button type="button" className="drawer-backdrop" aria-label="Close menu" onClick={() => setMobileOpen(false)} />
      ) : null}

      <div className="app-main">
        <Topbar
          ref={menuButtonRef}
          channel={channel}
          sections={sections}
          mobileOpen={mobileOpen}
          onToggleMobile={() => setMobileOpen((value) => !value)}
          onSignOut={() => void handleSignOut()}
          onSignOutEverywhere={() => setConfirmEverywhere(true)}
          signingOut={signingOut}
        />

        <main id="main-content" ref={mainRef} className="app-content" tabIndex={-1}>
          <Suspense fallback={<LoadingSkeleton rows={6} label="Loading page" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <ConfirmationDialog
        open={confirmEverywhere}
        title="Sign out from all devices?"
        description="You will be signed out on this computer and on every other device where you are signed in to MBGA."
        confirmLabel="Sign out everywhere"
        onClose={() => setConfirmEverywhere(false)}
        onConfirm={async () => {
          await auth.signOutEverywhere();
          toast.success("You have been signed out from all devices.");
          navigate("/login", { replace: true });
        }}
      />
    </div>
  );
}
