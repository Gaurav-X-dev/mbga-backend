import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import type { AuthChannel } from "../../auth/token-storage";
import { PANEL_LABEL, PANEL_SUMMARY, type NavSection } from "../../config/navigation";
import { Icon } from "../common/Icon";

const OPEN_KEY = "mbga.web.sidebar-sections";

function readClosed(): string[] {
  try {
    const raw = window.localStorage.getItem(OPEN_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

type SidebarProps = {
  channel: AuthChannel;
  sections: NavSection[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
};

export function Sidebar({ channel, sections, collapsed, onToggleCollapsed }: SidebarProps) {
  const location = useLocation();
  const { pathname } = location;
  const [closed, setClosed] = useState<string[]>(readClosed);

  // A section holding the page you are on is never left folded away.
  useEffect(() => {
    const active = sections.find((section) => section.items.some((item) => pathname.startsWith(item.to)));
    if (active && closed.includes(active.title)) {
      setClosed((value) => value.filter((title) => title !== active.title));
    }
    // Only react to navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  function toggleSection(title: string) {
    setClosed((value) => {
      const next = value.includes(title) ? value.filter((item) => item !== title) : [...value, title];
      try {
        window.localStorage.setItem(OPEN_KEY, JSON.stringify(next));
      } catch {
        // Preference only; ignore storage failures.
      }
      return next;
    });
  }

  /**
   * NavLink matches the path only, so "/admin/payments" and "/admin/payments?view=invoices" would
   * both light up. A link with a query is active when the address carries that query; the plain
   * link to the same path steps aside when a sibling's query matches.
   */
  const allLinks = sections.flatMap((section) => section.items.map((item) => item.to));
  function queryMatches(to: string) {
    const [path, query] = to.split("?");
    if (!query || location.pathname !== path) return false;
    const current = new URLSearchParams(location.search);
    return [...new URLSearchParams(query)].every(([key, value]) => current.get(key) === value);
  }
  function linkActive(to: string, pathActive: boolean) {
    if (to.includes("?")) return queryMatches(to);
    if (!pathActive && location.pathname !== to) return false;
    return !allLinks.some((other) => other !== to && other.startsWith(`${to}?`) && queryMatches(other));
  }

  return (
    <aside className="sidebar" aria-label={`${PANEL_LABEL[channel]} navigation`} id="app-sidebar">
      <NavLink to={`/${channel}/dashboard`} className="sidebar__brand">
        {/* The mark carries its own colour and shape, so it gets a plain surface rather than a
            tinted tile that would fight the blue in the artwork. */}
        <img src="/mbga-logo.png" alt="" className="sidebar__logo" />
        <span className="brand-text">
          <span className="brand-text__name">MBGA</span>
          <span className="brand-text__panel">{PANEL_SUMMARY[channel]}</span>
        </span>
        <span className="sr-only">Go to dashboard</span>
      </NavLink>

      <nav className="sidebar__nav" aria-label="Main">
        {sections.map((section) => {
          const open = collapsed || !closed.includes(section.title);
          const listId = `nav-${section.title.replace(/\W+/g, "-").toLowerCase()}`;
          return (
            <div key={section.title} className="nav-section">
              <button
                type="button"
                className="nav-section__title"
                aria-expanded={open}
                aria-controls={listId}
                onClick={() => toggleSection(section.title)}
              >
                <span>{section.title}</span>
                <Icon name={open ? "chevronDown" : "chevronRight"} size={13} />
              </button>
              {open ? (
                <ul className="nav-list" id={listId}>
                  {section.items.map((item) => (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        className={({ isActive }) => (linkActive(item.to, isActive) ? "nav-link active" : "nav-link")}
                        aria-current={linkActive(item.to, false) ? "page" : undefined}
                        title={collapsed ? item.label : undefined}
                      >
                        <Icon name={item.icon} size={17} />
                        <span className="nav-link__label">{item.label}</span>
                        {item.unavailable ? <span className="nav-link__tag">Soon</span> : null}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          );
        })}
      </nav>

      <div className="sidebar__footer">
        <button
          type="button"
          className="sidebar__collapse"
          onClick={onToggleCollapsed}
          aria-expanded={!collapsed}
          aria-controls="app-sidebar"
          title={collapsed ? "Expand sidebar" : undefined}
        >
          <Icon name={collapsed ? "chevronRight" : "chevronLeft"} size={16} />
          <span className="sidebar__collapse-label">Collapse</span>
          {collapsed ? <span className="sr-only">Expand sidebar</span> : null}
        </button>
      </div>
    </aside>
  );
}
