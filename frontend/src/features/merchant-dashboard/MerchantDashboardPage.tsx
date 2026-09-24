import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listDeliveryMembers } from "../../api/delivery-team.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { ButtonLink } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, ErrorState, InlineError, RefreshIndicator, Skeleton } from "../../components/feedback/Feedback";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { formatNumber, formatRelativeTime } from "../../utils/format";
import { deliveryTypeLabel } from "../../utils/labels";

const STALE = 60_000;

/** Counts come from the list total of the merchant-scoped endpoint (limit 1). */
function useTeamCount(filters: { delivery_user_type?: string; status?: string }, enabled: boolean) {
  const params = { ...filters, limit: 1, offset: 0 };
  return useQuery({
    queryKey: queryKeys.deliveryTeam.list(params),
    queryFn: ({ signal }) => listDeliveryMembers(params, signal),
    select: (data) => data.total,
    enabled,
    staleTime: STALE
  });
}

export function MerchantDashboardPage() {
  const auth = useAuth();
  const canTeam = auth.can(PERMISSIONS.deliveryUsersView);
  const total = useTeamCount({}, canTeam);
  const activeDrivers = useTeamCount({ delivery_user_type: "DRIVER", status: "ACTIVE" }, canTeam);
  const activeHelpers = useTeamCount({ delivery_user_type: "HELPER", status: "ACTIVE" }, canTeam);
  const blocked = useTeamCount({ status: "BLOCKED" }, canTeam);
  const recentParams = { limit: 5, offset: 0 };
  const recent = useQuery({
    queryKey: queryKeys.deliveryTeam.list(recentParams),
    queryFn: ({ signal }) => listDeliveryMembers(recentParams, signal),
    enabled: canTeam,
    staleTime: STALE
  });

  const countError = total.error ?? activeDrivers.error ?? activeHelpers.error ?? blocked.error;
  const firstName = auth.user?.display_name?.split(" ")[0];
  const value = (query: { data?: number; isLoading: boolean }) =>
    query.isLoading ? <Skeleton width={56} height={32} /> : formatNumber(query.data);

  return (
    <div className="page">
      <PageHeader
        title="Dashboard"
        description={firstName ? `Welcome back, ${firstName}.` : "Welcome back."}
        meta={<RefreshIndicator active={total.isFetching && !total.isLoading} />}
        actions={
          auth.can(PERMISSIONS.deliveryUsersCreate) ? (
            <ButtonLink to="/merchant/delivery-team/new" variant="accent" icon="plus">
              Add team member
            </ButtonLink>
          ) : undefined
        }
      />

      {canTeam ? (
        <section className="stack" aria-labelledby="team-heading">
          <h2 id="team-heading" className="section-title">
            Delivery team
          </h2>
          {countError && total.data === undefined ? (
            <InlineError
              error={countError}
              title="Team figures could not be loaded"
              onRetry={() => {
                void total.refetch();
                void activeDrivers.refetch();
                void activeHelpers.refetch();
                void blocked.refetch();
              }}
            />
          ) : (
            <div className="stat-grid">
              <StatCard
                label="Team members"
                icon="users"
                accent
                value={value(total)}
                to="/merchant/delivery-team"
                linkLabel="View team"
              />
              <StatCard
                label="Active drivers"
                icon="truck"
                value={value(activeDrivers)}
                to="/merchant/delivery-team?type=DRIVER&status=ACTIVE"
                linkLabel="View drivers"
              />
              <StatCard
                label="Active helpers"
                icon="user"
                value={value(activeHelpers)}
                to="/merchant/delivery-team?type=HELPER&status=ACTIVE"
                linkLabel="View helpers"
              />
              <StatCard
                label="Blocked members"
                icon="ban"
                value={value(blocked)}
                to="/merchant/delivery-team?status=BLOCKED"
                linkLabel="View blocked"
              />
            </div>
          )}
        </section>
      ) : null}

      <div className="grid-sidebar">
        {canTeam ? (
          <Card
            title="Recently added team members"
            actions={
              <Link to="/merchant/delivery-team" className="text-small">
                View all
              </Link>
            }
          >
            {recent.isLoading ? (
              <div className="stack" role="status">
                <span className="sr-only">Loading team members…</span>
                {[0, 1, 2].map((index) => (
                  <Skeleton key={index} height={18} />
                ))}
              </div>
            ) : recent.error ? (
              <ErrorState error={recent.error} onRetry={() => void recent.refetch()} />
            ) : recent.data && recent.data.items.length > 0 ? (
              <ul className="list-plain">
                {recent.data.items.map((member) => (
                  <li key={member.id} className="activity-item" style={{ alignItems: "center" }}>
                    <UserAvatar name={member.full_name} />
                    <div className="stack" style={{ gap: 0, flex: 1, minWidth: 0 }}>
                      <Link to={`/merchant/delivery-team/${member.id}`} style={{ fontWeight: 600 }}>
                        {member.full_name ?? "Unnamed"}
                      </Link>
                      <span className="meta">
                        {deliveryTypeLabel(member.delivery_user_type)} · added {formatRelativeTime(member.created_at)}
                      </span>
                    </div>
                    <StatusBadge status={member.status} />
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon="truck"
                title="No team members yet"
                description="Add your drivers and helpers so they can use the MBGA Delivery app."
                action={
                  auth.can(PERMISSIONS.deliveryUsersCreate) ? (
                    <ButtonLink to="/merchant/delivery-team/new" variant="accent" icon="plus">
                      Add team member
                    </ButtonLink>
                  ) : undefined
                }
              />
            )}
          </Card>
        ) : (
          <Card title="Welcome">
            <p className="text-muted">Your account does not have access to any operational modules yet. Contact MBGA support if this is unexpected.</p>
          </Card>
        )}

        <Card title="Shortcuts">
          <ul className="shortcut-list list-plain">
            {auth.can(PERMISSIONS.deliveryUsersCreate) ? (
              <li>
                <Link to="/merchant/delivery-team/new?type=DRIVER" className="shortcut">
                  <Icon name="truck" />
                  Add a driver
                  <Icon name="chevronRight" />
                </Link>
              </li>
            ) : null}
            {auth.can(PERMISSIONS.deliveryUsersCreate) ? (
              <li>
                <Link to="/merchant/delivery-team/new?type=HELPER" className="shortcut">
                  <Icon name="user" />
                  Add a helper
                  <Icon name="chevronRight" />
                </Link>
              </li>
            ) : null}
            <li>
              <Link to="/merchant/profile" className="shortcut">
                <Icon name="lock" />
                My account
                <Icon name="chevronRight" />
              </Link>
            </li>
          </ul>
          <p className="meta" style={{ marginTop: "var(--space-4)" }}>
            Orders, inventory, payments and reports will appear here when they are released.
          </p>
        </Card>
      </div>
    </div>
  );
}
