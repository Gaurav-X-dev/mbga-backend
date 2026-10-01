import { useQuery } from "@tanstack/react-query";
import { forwardRef, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { listAuditLogs } from "../../api/audit-logs.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import type { AuthChannel } from "../../auth/token-storage";
import {
  NAVIGATION,
  PANEL_LABEL,
  QUICK_ACTIONS,
  SEARCH_PLACEHOLDER,
  SEARCH_TARGETS,
  type NavSection
} from "../../config/navigation";
import { useTheme } from "../../theme/theme-context";
import { formatDateTime, formatRelativeTime } from "../../utils/format";
import { auditEntityLabel, auditEventLabel, auditSeverity, roleLabel } from "../../utils/labels";
import { Icon, type IconName } from "../common/Icon";
import { Menu } from "../common/Menu";
import { Popover } from "../common/Popover";
import { UserAvatar } from "../common/StatusBadge";
import { Skeleton } from "../feedback/Feedback";
import { Breadcrumbs } from "./Breadcrumbs";

type SearchOption = { id: string; label: string; hint: string; icon: IconName; to: string };

/** Top-bar search: jumps to a list pre-filtered by the query, or straight to a matching page. */
function GlobalSearch({ channel, sections }: { channel: AuthChannel; sections: NavSection[] }) {
  const auth = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  const term = query.trim();
  const options = useMemo<SearchOption[]>(() => {
    if (!term) return [];
    const lists = SEARCH_TARGETS[channel]
      .filter((target) => target.permissions.every((code) => auth.permissions.includes(code)))
      .map((target) => ({
        id: `list-${target.path}`,
        label: `Search ${target.label.toLowerCase()} for “${term}”`,
        hint: target.label,
        icon: target.icon,
        to: `${target.path}?search=${encodeURIComponent(term)}`
      }));
    const lower = term.toLowerCase();
    const pages = sections
      .flatMap((section) => section.items.map((item) => ({ ...item, section: section.title })))
      .filter((item) => item.label.toLowerCase().includes(lower))
      .map((item) => ({ id: `page-${item.to}`, label: item.label, hint: item.section, icon: item.icon, to: item.to }));
    return [...pages, ...lists];
  }, [term, channel, sections, auth.permissions]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  function go(option: SearchOption | undefined) {
    if (!option) return;
    navigate(option.to);
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
  }

  const expanded = open && options.length > 0;

  return (
    <div className="global-search" role="search">
      <Icon name="search" size={16} />
      <input
        ref={inputRef}
        type="search"
        className="global-search__input"
        placeholder={SEARCH_PLACEHOLDER[channel]}
        aria-label="Search the panel"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={expanded ? listId : undefined}
        aria-activedescendant={expanded ? `${listId}-${active}` : undefined}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((value) => (options.length ? (value + 1) % options.length : 0));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((value) => (options.length ? (value - 1 + options.length) % options.length : 0));
          } else if (event.key === "Enter") {
            event.preventDefault();
            go(options[active]);
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      <kbd className="global-search__kbd" aria-hidden="true">
        Ctrl K
      </kbd>
      {expanded ? (
        <ul id={listId} role="listbox" className="global-search__results list-plain" aria-label="Search suggestions">
          {options.map((option, index) => (
            <li
              key={option.id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className={index === active ? "is-active" : undefined}
              onMouseDown={(event) => {
                event.preventDefault();
                go(option);
              }}
              onMouseEnter={() => setActive(index)}
            >
              <span className="global-search__icon" aria-hidden="true">
                <Icon name={option.icon} size={15} />
              </span>
              <span className="global-search__label">{option.label}</span>
              <span className="global-search__hint">{option.hint}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Latest audit events. Fetched only when opened, so merely loading a page costs no request. */
function NotificationsPanel({ close }: { close: () => void }) {
  const params = { page: 1, page_size: 6 };
  const query = useQuery({
    queryKey: queryKeys.auditLogs.list(params),
    queryFn: ({ signal }) => listAuditLogs(params, signal),
    staleTime: 30_000
  });
  return (
    <div className="notifications">
      <div className="notifications__header">
        <strong>Recent activity</strong>
        <span className="meta">From the audit trail</span>
      </div>
      {query.isLoading ? (
        <div className="stack" style={{ padding: "var(--space-4)", gap: 10 }} role="status">
          <span className="sr-only">Loading recent activity…</span>
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} height={28} />
          ))}
        </div>
      ) : query.error ? (
        <p className="notifications__empty">Recent activity could not be loaded.</p>
      ) : query.data && query.data.items.length > 0 ? (
        <ul className="list-plain notifications__list">
          {query.data.items.map((item) => (
            <li key={item.id}>
              <span className={`notifications__dot sev-${auditSeverity(item.event_type)}`} aria-hidden="true" />
              <span className="notifications__text">
                <strong>{auditEventLabel(item.event_type)}</strong>
                <span>
                  {auditEntityLabel(item.entity_type)} ·{" "}
                  <time dateTime={item.created_at} title={formatDateTime(item.created_at)}>
                    {formatRelativeTime(item.created_at)}
                  </time>
                </span>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="notifications__empty">You are all caught up.</p>
      )}
      <Link to="/admin/audit-logs" className="notifications__footer" onClick={close}>
        View audit trail <Icon name="arrowRight" size={14} />
      </Link>
    </div>
  );
}

/** Switches between light and dark. The icon shows the theme you would get by pressing it. */
function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" className="icon-btn" onClick={toggle} aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}>
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}

function currentModule(channel: AuthChannel, pathname: string) {
  const items = NAVIGATION[channel].flatMap((section) => section.items.map((item) => ({ ...item, section: section.title })));
  return items
    .filter((item) => pathname === item.to || pathname.startsWith(`${item.to}/`))
    .sort((a, b) => b.to.length - a.to.length)[0];
}

type TopbarProps = {
  channel: AuthChannel;
  sections: NavSection[];
  mobileOpen: boolean;
  onToggleMobile: () => void;
  onSignOut: () => void;
  onSignOutEverywhere: () => void;
  signingOut: boolean;
};

export const Topbar = forwardRef<HTMLButtonElement, TopbarProps>(function Topbar(
  { channel, sections, mobileOpen, onToggleMobile, onSignOut, onSignOutEverywhere, signingOut },
  menuButtonRef
) {
  const auth = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const user = auth.user;
  const displayName = user?.display_name ?? "Operator";
  const primaryRole = user?.active_roles[0];
  const module = currentModule(channel, pathname);
  const quickActions = QUICK_ACTIONS[channel].filter((action) => action.permissions.every((code) => auth.permissions.includes(code)));
  const canAudit = channel === "admin" && auth.can(PERMISSIONS.auditLogsView);

  return (
    <header className="topbar">
      <button
        ref={menuButtonRef}
        type="button"
        className="icon-btn topbar__menu"
        aria-label={mobileOpen ? "Close menu" : "Open menu"}
        title={mobileOpen ? "Close menu" : "Open menu"}
        aria-expanded={mobileOpen}
        aria-controls="app-sidebar"
        onClick={onToggleMobile}
      >
        <Icon name={mobileOpen ? "x" : "menu"} />
      </button>

      <div className="topbar__context">
        <p className="topbar__module">
          {module ? (
            <>
              <span className="topbar__module-section">{module.section}</span>
              <span className="topbar__module-name">{module.label}</span>
            </>
          ) : (
            <span className="topbar__module-name">{PANEL_LABEL[channel]}</span>
          )}
        </p>
        <Breadcrumbs channel={channel} />
      </div>

      <GlobalSearch channel={channel} sections={sections} />

      <div className="topbar__actions">
        {quickActions.length > 0 ? (
          <Menu
            label="Create new"
            triggerClassName="btn btn--primary btn--sm topbar__create"
            trigger={() => (
              <>
                <Icon name="plus" size={16} />
                <span className="topbar__create-label">Create</span>
              </>
            )}
            actions={quickActions.map((action) => ({ label: action.label, icon: action.icon, onSelect: () => navigate(action.to) }))}
          />
        ) : null}

        {canAudit ? (
          <Popover label="Recent activity" trigger={<Icon name="bell" />} panelClassName="popover__panel--wide">
            {(close) => <NotificationsPanel close={close} />}
          </Popover>
        ) : null}

        <ThemeToggle />

        <div className="user-menu">
          <Menu
            label="Account menu"
            triggerClassName="user-menu__trigger"
            trigger={() => (
              <>
                <UserAvatar name={user?.display_name} />
                <span className="user-menu__name">
                  <span className="user-menu__display">{displayName}</span>
                  {primaryRole ? <span className="user-menu__role">{roleLabel(primaryRole)}</span> : null}
                </span>
                <Icon name="chevronDown" size={15} />
                <span className="sr-only">Open account menu</span>
              </>
            )}
            header={
              <>
                <strong>{displayName}</strong>
                <div className="meta">
                  {primaryRole ? `${roleLabel(primaryRole)} · ` : ""}
                  {PANEL_LABEL[channel]}
                </div>
              </>
            }
            actions={[
              { label: "Profile settings", icon: "settings", onSelect: () => navigate(`/${channel}/profile`) },
              { label: "Sign out from all devices", icon: "devices", onSelect: onSignOutEverywhere },
              { label: signingOut ? "Signing out..." : "Sign out", icon: "logout", disabled: signingOut, onSelect: onSignOut }
            ]}
          />
        </div>
      </div>
    </header>
  );
});
