import { Fragment } from "react";
import { Link, useLocation } from "react-router-dom";

import type { AuthChannel } from "../../auth/token-storage";
import { NAVIGATION, PANEL_LABEL } from "../../config/navigation";
import { Icon } from "../common/Icon";

type Crumb = { label: string; to?: string };

/**
 * A readable label for a path segment the navigation does not know about.
 *
 * Detail routes end in an id - `/admin/merchants/9f3c-…` - and an id in a breadcrumb tells the
 * reader nothing. The page itself shows the record's name in its title, so the trail says
 * "Details" and stops, rather than printing a UUID nobody can read.
 */
function labelFor(segment: string): string {
  if (segment === "new") return "New";
  if (/^[0-9a-f-]{8,}$/i.test(segment)) return "Details";
  return segment.replace(/-/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/**
 * Where you are, derived from the route and the navigation config.
 *
 * Built from `NAVIGATION` rather than from a per-page prop, so a section renamed in one place
 * is renamed everywhere - and a page cannot end up with a trail that disagrees with the menu
 * it was opened from.
 */
export function Breadcrumbs({ channel }: { channel: AuthChannel }) {
  const { pathname } = useLocation();
  const segments = pathname.split("/").filter(Boolean);
  // The first segment is the channel itself, which the panel label already says.
  const rest = segments.slice(1);

  const crumbs: Crumb[] = [{ label: PANEL_LABEL[channel], to: `/${channel}/dashboard` }];
  let walked = `/${channel}`;

  rest.forEach((segment, index) => {
    walked += `/${segment}`;
    const known = NAVIGATION[channel]
      .flatMap((section) => section.items)
      .find((item) => item.to === walked);
    crumbs.push({
      label: known?.label ?? labelFor(segment),
      // The last crumb is where you already are, so it is not a link.
      to: index === rest.length - 1 ? undefined : walked
    });
  });

  // On the dashboard the trail would just repeat the page title.
  if (crumbs.length < 2) return null;

  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <ol>
        {crumbs.map((crumb, index) => (
          <Fragment key={`${crumb.label}-${index}`}>
            {index > 0 ? (
              <li className="breadcrumbs__sep" aria-hidden="true">
                <Icon name="chevronRight" size={14} />
              </li>
            ) : null}
            <li>
              {crumb.to ? (
                <Link to={crumb.to}>{crumb.label}</Link>
              ) : (
                <span aria-current="page">{crumb.label}</span>
              )}
            </li>
          </Fragment>
        ))}
      </ol>
    </nav>
  );
}
