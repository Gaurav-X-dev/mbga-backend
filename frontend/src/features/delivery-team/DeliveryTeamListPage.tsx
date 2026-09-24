import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { listDeliveryMembers, type DeliveryMember } from "../../api/delivery-team.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { ButtonLink } from "../../components/common/Button";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDate } from "../../utils/format";
import { deliveryTypeLabel } from "../../utils/labels";
import { formatMobileNumber } from "../../utils/mobile";
import { useDeliveryMemberStatus } from "./useDeliveryMemberStatus";

const PAGE_SIZE = 20;
const FILTERS = ["search", "type", "status"] as const;

export function DeliveryTeamListPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const status = useDeliveryMemberStatus();

  const params = {
    search: values.search || undefined,
    delivery_user_type: values.type || undefined,
    status: values.status || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.deliveryTeam.list(params),
    queryFn: ({ signal }) => listDeliveryMembers(params, signal),
    placeholderData: keepPreviousData
  });
  const canCreate = auth.can(PERMISSIONS.deliveryUsersCreate);

  const columns: Column<DeliveryMember>[] = [
    {
      key: "name",
      header: "Team member",
      primary: true,
      render: (member) => (
        <div className="cell-primary">
          <UserAvatar name={member.full_name} />
          <div className="cell-primary__text">
            <Link to={`/merchant/delivery-team/${member.id}`} className="cell-primary__title">
              {member.full_name ?? "Unnamed"}
            </Link>
            <span className="cell-primary__subtitle">Employee code {member.employee_code ?? "—"}</span>
          </div>
        </div>
      )
    },
    {
      key: "type",
      header: "Type",
      render: (member) => (
        <Badge tone={member.delivery_user_type === "DRIVER" ? "info" : "neutral"}>{deliveryTypeLabel(member.delivery_user_type)}</Badge>
      )
    },
    {
      key: "mobile",
      header: "Mobile number",
      render: (member) => <span className="nowrap">{formatMobileNumber(member.mobile_number) || "—"}</span>
    },
    { key: "status", header: "Status", render: (member) => <StatusBadge status={member.status} /> },
    { key: "added", header: "Added on", render: (member) => <span className="nowrap">{formatDate(member.created_at)}</span> }
  ];

  return (
    <div className="page">
      <PageHeader
        title="Delivery team"
        description="Drivers and helpers who deliver for your business using the MBGA Delivery app."
        breadcrumbs={[{ label: "Dashboard", to: "/merchant/dashboard" }, { label: "Delivery team" }]}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          canCreate ? (
            <ButtonLink to="/merchant/delivery-team/new" variant="accent" icon="plus">
              Add team member
            </ButtonLink>
          ) : undefined
        }
      />
      <Card bodyless className="table-card">
        <FilterBar onReset={reset} canReset={hasFilters}>
          <SearchInput
            label="Search team members"
            placeholder="Search by name, mobile or employee code"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <Field label="Type">
            <Select
              value={values.type}
              onChange={(event) => setFilter("type", event.target.value)}
              options={[
                { value: "DRIVER", label: "Drivers" },
                { value: "HELPER", label: "Helpers" }
              ]}
              placeholder="Drivers and helpers"
            />
          </Field>
          <Field label="Status">
            <Select
              value={values.status}
              onChange={(event) => setFilter("status", event.target.value)}
              options={[
                { value: "ACTIVE", label: "Active" },
                { value: "BLOCKED", label: "Blocked" }
              ]}
              placeholder="All statuses"
            />
          </Field>
        </FilterBar>
        {query.error && query.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
          </div>
        ) : null}
        <DataTable
          caption="Delivery team members"
          columns={columns}
          rows={query.data?.items}
          getRowKey={(member) => member.id}
          getRowHref={(member) => `/merchant/delivery-team/${member.id}`}
          rowLabel={(member) => member.full_name ?? "team member"}
          rowActions={(member) => [
            { label: "View details", icon: "eye", onSelect: () => navigate(`/merchant/delivery-team/${member.id}`) },
            ...status.actionsFor(member)
          ]}
          isLoading={query.isLoading}
          error={query.error}
          onRetry={() => void query.refetch()}
          empty={
            hasFilters ? (
              <EmptyState icon="search" title="No team members match your filters" description="Try a different search or clear the filters." />
            ) : (
              <EmptyState
                icon="truck"
                title="No team members yet"
                description="Add your drivers and helpers so they can sign in to the MBGA Delivery app."
                action={
                  canCreate ? (
                    <ButtonLink to="/merchant/delivery-team/new" variant="accent" icon="plus">
                      Add team member
                    </ButtonLink>
                  ) : undefined
                }
              />
            )
          }
          footer={
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={query.data?.total ?? 0}
              onPageChange={setPage}
              itemLabel="team members"
              disabled={query.isFetching}
            />
          }
        />
      </Card>
      {status.dialog}
    </div>
  );
}
