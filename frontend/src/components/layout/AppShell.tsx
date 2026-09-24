import { Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../../auth/auth-context";
import type { AuthChannel } from "../../auth/token-storage";
import { PANEL_LABEL, visibleNavigation } from "../../config/navigation";
import { roleLabel } from "../../utils/labels";
import { IconButton } from "../common/Button";
import { Icon } from "../common/Icon";
import { Menu } from "../common/Menu";
import { BrandMark, UserAvatar } from "../common/StatusBadge";
import { ConfirmationDialog } from "../feedback/Dialogs";
import { LoadingSkeleton } from "../feedback/Feedback";
import { useToast } from "../feedback/toast-context";

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
  const user = auth.user;
  const primaryRole = user?.active_roles[0];

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
        // ignore
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

      <aside className="sidebar" aria-label={`${PANEL_LABEL[channel]} navigation`} id="app-sidebar">
        <NavLink to={channel === "admin" ? "/admin/dashboard" : "/merchant/dashboard"} className="sidebar__brand">
          <BrandMark />
          <span className="brand-text">
            <span className="brand-text__name">MBGA</span>
            <span className="brand-text__panel">{PANEL_LABEL[channel]}</span>
          </span>
          <span className="sr-only">Go to dashboard</span>
        </NavLink>
        <nav className="sidebar__nav" aria-label="Main">
          {sections.map((section) => (
            <div key={section.title} className="nav-section">
              <h2 className="nav-section__title">{section.title}</h2>
              <ul className="nav-list">
                {section.items.map((item) => (
                  <li key={item.to}>
                    <NavLink to={item.to} className="nav-link" title={collapsed ? item.label : undefined}>
                      <Icon name={item.icon} />
                      <span className="nav-link__label">{item.label}</span>
                      {item.unavailable ? <span className="nav-link__tag">Soon</span> : null}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="sidebar__footer">
          <button
            type="button"
            className="btn btn--ghost sidebar__collapse"
            onClick={toggleCollapsed}
            aria-expanded={!collapsed}
            aria-controls="app-sidebar"
          >
            <Icon name="sidebar" />
            <span className="sidebar__collapse-label">{collapsed ? "Expand menu" : "Collapse menu"}</span>
            {collapsed ? <span className="sr-only">Expand menu</span> : null}
          </button>
        </div>
      </aside>
      {mobileOpen ? (
        <button type="button" className="drawer-backdrop" aria-label="Close menu" onClick={() => setMobileOpen(false)} />
      ) : null}

      <div className="app-main">
        <header className="app-header">
          <IconButton
            ref={menuButtonRef}
            icon="menu"
            label={mobileOpen ? "Close menu" : "Open menu"}
            className="app-header__menu"
            aria-expanded={mobileOpen}
            aria-controls="app-sidebar"
            onClick={() => setMobileOpen((value) => !value)}
          />
          <div className="app-header__spacer" />
          <span className="channel-label">{PANEL_LABEL[channel]}</span>
          <div className="user-menu">
            <Menu
              label="Account menu"
              triggerClassName="user-menu__trigger"
              trigger={() => (
                <>
                  <UserAvatar name={user?.display_name} />
                  <span className="user-menu__name">
                    <span className="text-small" style={{ fontWeight: 600 }}>
                      {user?.display_name ?? "Signed in"}
                    </span>
                    {primaryRole ? <span className="user-menu__role">{roleLabel(primaryRole)}</span> : null}
                  </span>
                  <Icon name="chevronDown" size={16} />
                  <span className="sr-only">Open account menu</span>
                </>
              )}
              header={
                <>
                  <strong>{user?.display_name ?? "Signed in"}</strong>
                  <div className="meta">{PANEL_LABEL[channel]}</div>
                </>
              }
              actions={[
                { label: "My account", icon: "user", onSelect: () => navigate(`/${channel}/profile`) },
                {
                  label: "Sign out from all devices",
                  icon: "devices",
                  onSelect: () => setConfirmEverywhere(true)
                },
                {
                  label: signingOut ? "Signing out…" : "Sign out",
                  icon: "logout",
                  disabled: signingOut,
                  onSelect: () => void handleSignOut()
                }
              ]}
            />
          </div>
        </header>

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
