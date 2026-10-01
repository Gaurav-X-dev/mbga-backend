import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { listUsers } from "../../api/users.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { ButtonLink } from "../../components/common/Button";
import { Menu } from "../../components/common/Menu";
import { StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, ErrorState, Skeleton } from "../../components/feedback/Feedback";
import { Card, MiniStat, PageHeader } from "../../components/layout/Page";
import { listKycApplications } from "../../api/customer-kyc.api";
import { formatDate, formatNumber, formatRelativeTime } from "../../utils/format";
import { roleLabel } from "../../utils/labels";
import { useMerchantStatusActions } from "../merchants/useMerchantStatus";
import { useUserStatusActions } from "../users/useUserActions";
import { userDisplayName } from "../users/user-utils";

function ListSkeleton() {
  return (
    <div className="stack" role="status">
      <span className="sr-only">Loading…</span>
      {[0, 1, 2].map((index) => (
        <Skeleton key={index} height={36} />
      ))}
    </div>
  );
}

/** Everything across the network that is waiting on a head-office decision. */
export function ApprovalsPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const canUsers = auth.can(PERMISSIONS.usersView);
  const canMerchants = auth.can(PERMISSIONS.merchantsView);
  const userActions = useUserStatusActions();
  const merchantActions = useMerchantStatusActions();

  const pendingUsersParams = { status: "PENDING", limit: 10, offset: 0 };
  const pendingUsers = useQuery({
    queryKey: queryKeys.users.list(pendingUsersParams),
    queryFn: ({ signal }) => listUsers(pendingUsersParams, signal),
    enabled: canUsers
  });
  const blockedMerchantsParams = { status: "BLOCKED", limit: 10, offset: 0 };
  const blockedMerchants = useQuery({
    queryKey: queryKeys.merchants.list(blockedMerchantsParams),
    queryFn: ({ signal }) => listMerchants(blockedMerchantsParams, signal),
    enabled: canMerchants
  });
  const kycParams = { status: "PENDING", limit: 10, offset: 0 };
  const kycQuery = useQuery({
    queryKey: queryKeys.customerKyc.list(kycParams),
    queryFn: ({ signal }) => listKycApplications(kycParams, signal),
    retry: false
  });
  const kycPending = kycQuery.data?.items ?? [];

  const total = (kycQuery.data?.total ?? 0) + (pendingUsers.data?.total ?? 0) + (blockedMerchants.data?.total ?? 0);

  return (
    <div className="page">
      <PageHeader
        title="Approvals"
        documentTitle="Approvals"
        description="Review Queue: everything across the network that is waiting on a head-office decision."
      />

      <div className="mini-stat-strip" aria-label="Queue summary">
        <MiniStat label="Items awaiting action" value={formatNumber(total)} icon="inbox" tone="blue" />
        <MiniStat label="Customer KYC" value={formatNumber(kycQuery.data?.total)} icon="idCard" tone="amber" />
        {canUsers ? <MiniStat label="Pending team users" value={formatNumber(pendingUsers.data?.total)} icon="userPlus" tone="green" /> : null}
        {canMerchants ? <MiniStat label="Blocked merchants" value={formatNumber(blockedMerchants.data?.total)} icon="store" tone="red" /> : null}
      </div>

      <div className="grid-3">
        <Card
          title="Customer KYC"
          subtitle="Applications to verify"
          headingLevel={2}
          footer={
            <Link to="/admin/customers" className="text-small">
              Open KYC review →
            </Link>
          }
        >
          {kycQuery.isLoading ? (
            <ListSkeleton />
          ) : kycQuery.error ? (
            <ErrorState error={kycQuery.error} onRetry={() => void kycQuery.refetch()} />
          ) : kycPending.length === 0 ? (
            <EmptyState icon="idCard" title="No KYC requests pending" description="New customer registrations will appear here for review." />
          ) : (
            <ul className="activity-list list-plain">
              {kycPending.map((item) => (
                <li key={item.id} className="activity-item">
                  <UserAvatar name={item.customer_name} />
                  <div className="activity-item__body">
                    <span className="activity-item__title">
                      <Link to={`/admin/customers/${item.id}`}>{item.customer_name ?? "Unnamed customer"}</Link>
                      <StatusBadge status={item.status} />
                    </span>
                    <span className="activity-item__description">{item.merchant_name ?? "Unassigned"}</span>
                    <span className="activity-item__time">Submitted {formatRelativeTime(item.submitted_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {canUsers ? (
          <Card
            title="Pending team users"
            subtitle="Accounts waiting to be activated"
            headingLevel={2}
            footer={
              <Link to="/admin/users?status=PENDING" className="text-small">
                View all pending users →
              </Link>
            }
          >
            {pendingUsers.isLoading ? (
              <ListSkeleton />
            ) : pendingUsers.error ? (
              <ErrorState error={pendingUsers.error} onRetry={() => void pendingUsers.refetch()} />
            ) : pendingUsers.data && pendingUsers.data.items.length > 0 ? (
              <ul className="activity-list list-plain">
                {pendingUsers.data.items.map((user) => (
                  <li key={user.id} className="activity-item">
                    <UserAvatar name={userDisplayName(user)} />
                    <div className="activity-item__body">
                      <span className="activity-item__title">
                        <Link to={`/admin/users/${user.id}`}>{userDisplayName(user)}</Link>
                      </span>
                      <span className="activity-item__description">{roleLabel(user.role)}</span>
                      <span className="activity-item__time">Added {formatDate(user.created_at)}</span>
                    </div>
                    <Menu
                      label={`Actions for ${userDisplayName(user)}`}
                      actions={[
                        { label: "View details", icon: "eye", onSelect: () => navigate(`/admin/users/${user.id}`) },
                        ...userActions.actionsFor(user)
                      ]}
                    />
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon="userCheck" title="No pending users" description="Every team account has been activated." />
            )}
          </Card>
        ) : null}

        {canMerchants ? (
          <Card
            title="Blocked merchants"
            subtitle="Agencies that cannot sign in"
            headingLevel={2}
            footer={
              <Link to="/admin/merchants?status=BLOCKED" className="text-small">
                View in Merchant Network →
              </Link>
            }
          >
            {blockedMerchants.isLoading ? (
              <ListSkeleton />
            ) : blockedMerchants.error ? (
              <ErrorState error={blockedMerchants.error} onRetry={() => void blockedMerchants.refetch()} />
            ) : blockedMerchants.data && blockedMerchants.data.items.length > 0 ? (
              <ul className="activity-list list-plain">
                {blockedMerchants.data.items.map((merchant) => (
                  <li key={merchant.id} className="activity-item">
                    <UserAvatar name={merchant.business_name} />
                    <div className="activity-item__body">
                      <span className="activity-item__title">
                        <Link to={`/admin/merchants/${merchant.id}`}>{merchant.business_name}</Link>
                      </span>
                      <span className="activity-item__description">{[merchant.city, merchant.state].filter(Boolean).join(", ") || "Location not set"}</span>
                    </div>
                    <Menu
                      label={`Actions for ${merchant.business_name}`}
                      actions={[
                        { label: "View details", icon: "eye", onSelect: () => navigate(`/admin/merchants/${merchant.id}`) },
                        ...merchantActions.actionsFor(merchant)
                      ]}
                    />
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon="checkCircle" title="No blocked merchants" description="Every agency on the network can operate." />
            )}
          </Card>
        ) : null}
      </div>

      {auth.can(PERMISSIONS.merchantsCreate) ? (
        <div className="row">
          <ButtonLink to="/admin/merchants/new" variant="secondary" icon="plus">
            Onboard a merchant
          </ButtonLink>
        </div>
      ) : null}
      {userActions.dialog}
      {merchantActions.dialog}
    </div>
  );
}
