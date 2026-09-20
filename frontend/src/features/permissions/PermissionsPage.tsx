import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listPermissionsGrouped } from "../../api/permissions.api";
import { queryKeys } from "../../api/query-keys";
import { EmptyState, ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { FilterBar } from "../../components/tables/DataTable";
import { formatNumber } from "../../utils/format";
import { PERMISSION_MODULES, permissionDescription, permissionModuleLabel, permissionModuleOrder } from "../../utils/labels";

/** Read-only catalogue. Permissions are defined by the backend release, not edited here. */
export function PermissionsPage() {
  const [search, setSearch] = useState("");
  const [module, setModule] = useState("");
  const query = useQuery({
    queryKey: queryKeys.permissions.grouped(),
    queryFn: ({ signal }) => listPermissionsGrouped(signal),
    staleTime: 10 * 60_000
  });

  const groups = [...(query.data?.groups ?? [])].sort(
    (a, b) => permissionModuleOrder(a.module) - permissionModuleOrder(b.module)
  );
  const term = search.trim().toLowerCase();
  const visible = groups
    .filter((group) => !module || group.module === module)
    .map((group) => ({
      ...group,
      permissions: group.permissions.filter(
        (item) =>
          !term ||
          item.name.toLowerCase().includes(term) ||
          (item.description ?? "").toLowerCase().includes(term) ||
          permissionModuleLabel(group.module).toLowerCase().includes(term)
      )
    }))
    .filter((group) => group.permissions.length > 0);

  return (
    <div className="page">
      <PageHeader
        title="Permissions"
        description="Everything a role can be allowed to do. To give someone access, add these permissions to one of their roles."
        breadcrumbs={[{ label: "Dashboard", to: "/admin/dashboard" }, { label: "Permissions" }]}
        meta={query.data ? <span className="meta">{formatNumber(query.data.total)} permissions available</span> : undefined}
      />
      <Card bodyless>
        <FilterBar
          onReset={() => {
            setSearch("");
            setModule("");
          }}
          canReset={Boolean(search || module)}
        >
          <SearchInput
            label="Search permissions"
            placeholder="Search permissions"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Field label="Area">
            <Select
              value={module}
              onChange={(event) => setModule(event.target.value)}
              placeholder="All areas"
              options={groups.map((group) => ({ value: group.module, label: permissionModuleLabel(group.module) }))}
            />
          </Field>
        </FilterBar>
        <div className="card__body">
          {query.isLoading ? (
            <LoadingSkeleton rows={6} label="Loading permissions" />
          ) : query.error ? (
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          ) : visible.length === 0 ? (
            <EmptyState
              icon={term || module ? "search" : "key"}
              title={term || module ? "No permissions match your filters" : "No permissions available"}
            />
          ) : (
            <div>
              {visible.map((group) => (
                <section key={group.module} className="permission-group" aria-labelledby={`perm-${group.module}`}>
                  <div className="permission-group__header">
                    <div>
                      <h2 id={`perm-${group.module}`} className="text-small" style={{ fontWeight: 650 }}>
                        {permissionModuleLabel(group.module)}
                      </h2>
                      {PERMISSION_MODULES[group.module] ? (
                        <p className="meta">{PERMISSION_MODULES[group.module].description}</p>
                      ) : null}
                    </div>
                    <span className="meta">{group.permissions.length}</span>
                  </div>
                  <ul className="permission-group__items list-plain">
                    {group.permissions.map((item) => (
                      <li key={item.id} className="stack" style={{ gap: 2 }}>
                        <span className="text-small" style={{ fontWeight: 600 }}>
                          {item.name}
                        </span>
                        {permissionDescription(item) ? <span className="meta">{permissionDescription(item)}</span> : null}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
