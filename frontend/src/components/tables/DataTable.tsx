import { useMemo, useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { formatNumber } from "../../utils/format";
import { Button } from "../common/Button";
import { Icon } from "../common/Icon";
import { Menu, type MenuAction } from "../common/Menu";
import { ErrorState, Skeleton } from "../feedback/Feedback";

export type Column<T> = {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  /** Label used in the compact mobile card; defaults to the header. */
  mobileLabel?: string;
  /** The main identifying column (shown as the card title on small screens). */
  primary?: boolean;
  width?: string;
  className?: string;
  hideOnMobile?: boolean;
  align?: "left" | "right" | "center";
  /** Makes the header sortable. Sorting applies to the rows currently loaded. */
  sortValue?: (row: T) => string | number | null | undefined;
};

type SortState = { key: string; direction: "asc" | "desc" } | null;

type DataTableProps<T> = {
  caption: string;
  columns: Column<T>[];
  rows: T[] | undefined;
  getRowKey: (row: T) => string;
  /** Mouse convenience; the primary cell must still contain a real link for keyboard users. */
  getRowHref?: (row: T) => string;
  /** Row click for drawers; the primary cell must still contain a real button. */
  onRowClick?: (row: T) => void;
  rowActions?: (row: T) => MenuAction[];
  rowLabel?: (row: T) => string;
  isSelected?: (row: T) => boolean;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty: ReactNode;
  footer?: ReactNode;
  skeletonRows?: number;
};

function compare(a: string | number | null | undefined, b: string | number | null | undefined) {
  if (a === b) return 0;
  if (a === null || a === undefined || a === "") return 1;
  if (b === null || b === undefined || b === "") return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "en-IN", { numeric: true, sensitivity: "base" });
}

/** Table-shaped placeholder so the page does not jump when rows arrive. */
function TableSkeleton({ columns, rows, label }: { columns: number; rows: number; label: string }) {
  return (
    <div className="table-wrap" role="status" aria-live="polite">
      <span className="sr-only">{label}…</span>
      <table className="data-table data-table--skeleton" aria-hidden="true">
        <thead>
          <tr>
            {Array.from({ length: columns }, (_, index) => (
              <th key={index}>
                <Skeleton width={index === 0 ? 90 : 64} height={10} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }, (_, row) => (
            <tr key={row}>
              {Array.from({ length: columns }, (_, index) => (
                <td key={index}>
                  {index === 0 ? (
                    <span className="row" style={{ flexWrap: "nowrap", gap: 10 }}>
                      <Skeleton width={32} height={32} style={{ borderRadius: "50%", flexShrink: 0 }} />
                      <span className="stack" style={{ gap: 6, flex: 1 }}>
                        <Skeleton width={`${55 + ((row * 17) % 30)}%`} height={11} />
                        <Skeleton width="40%" height={9} />
                      </span>
                    </span>
                  ) : (
                    <Skeleton width={`${40 + ((row * 13 + index * 7) % 45)}%`} height={11} />
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  getRowKey,
  getRowHref,
  onRowClick,
  rowActions,
  rowLabel,
  isSelected,
  isLoading,
  error,
  onRetry,
  empty,
  footer,
  skeletonRows = 6
}: DataTableProps<T>) {
  const navigate = useNavigate();
  const [sort, setSort] = useState<SortState>(null);

  const sorted = useMemo(() => {
    if (!rows || !sort) return rows;
    const column = columns.find((item) => item.key === sort.key);
    if (!column?.sortValue) return rows;
    const factor = sort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => factor * compare(column.sortValue!(a), column.sortValue!(b)));
  }, [rows, sort, columns]);

  if (isLoading) {
    return <TableSkeleton columns={columns.length + (rowActions ? 1 : 0)} rows={skeletonRows} label={`Loading ${caption.toLowerCase()}`} />;
  }
  if (error && !rows) return <ErrorState error={error} onRetry={onRetry} />;
  if (!sorted || sorted.length === 0) return <>{empty}</>;

  const primary = columns.find((column) => column.primary) ?? columns[0];
  const secondary = columns.filter((column) => column !== primary && !column.hideOnMobile);

  function toggleSort(key: string) {
    setSort((current) => {
      if (!current || current.key !== key) return { key, direction: "asc" };
      if (current.direction === "asc") return { key, direction: "desc" };
      return null;
    });
  }

  function onClickRow(row: T) {
    const href = getRowHref?.(row);
    if (!href && !onRowClick) return undefined;
    return (event: MouseEvent<HTMLTableRowElement>) => {
      const target = event.target as HTMLElement;
      if (target.closest("a, button, input, select, label, [role='menu']")) return;
      if (onRowClick) onRowClick(row);
      else if (href) navigate(href);
    };
  }

  return (
    <>
      <div className="table-wrap has-mobile-list">
        <table className="data-table">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => {
                const active = sort?.key === column.key;
                const ariaSort = active ? (sort.direction === "asc" ? "ascending" : "descending") : undefined;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    style={column.width ? { width: column.width } : undefined}
                    className={column.align ? `is-${column.align}` : undefined}
                    aria-sort={column.sortValue ? (ariaSort ?? "none") : undefined}
                  >
                    {column.sortValue ? (
                      <button type="button" className={`th-sort${active ? " is-active" : ""}`} onClick={() => toggleSort(column.key)}>
                        {column.header}
                        <Icon
                          name={active ? (sort.direction === "asc" ? "arrowUp" : "arrowDown") : "sort"}
                          size={13}
                        />
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
              {rowActions ? (
                <th scope="col" className="col-actions">
                  <span className="sr-only">Actions</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const handler = onClickRow(row);
              const selected = isSelected?.(row);
              return (
                <tr
                  key={getRowKey(row)}
                  className={[handler && "is-clickable", selected && "is-selected"].filter(Boolean).join(" ") || undefined}
                  onClick={handler}
                >
                  {columns.map((column) =>
                    column === primary ? (
                      <th key={column.key} scope="row" className={[column.className, column.align && `is-${column.align}`].filter(Boolean).join(" ") || undefined}>
                        {column.render(row)}
                      </th>
                    ) : (
                      <td key={column.key} className={[column.className, column.align && `is-${column.align}`].filter(Boolean).join(" ") || undefined}>
                        {column.render(row)}
                      </td>
                    )
                  )}
                  {rowActions ? (
                    <td className="col-actions">
                      <Menu label={`Actions for ${rowLabel?.(row) ?? "this row"}`} actions={rowActions(row)} />
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ul className="mobile-list" aria-label={caption}>
        {sorted.map((row) => (
          <li key={getRowKey(row)} className="mobile-list__item">
            <div className="row-between" style={{ flexWrap: "nowrap" }}>
              <div style={{ minWidth: 0 }}>{primary.render(row)}</div>
              {rowActions ? <Menu label={`Actions for ${rowLabel?.(row) ?? "this row"}`} actions={rowActions(row)} /> : null}
            </div>
            {secondary.map((column) => (
              <div key={column.key} className="mobile-list__row">
                <span className="mobile-list__label">{column.mobileLabel ?? column.header}</span>
                <span>{column.render(row)}</span>
              </div>
            ))}
          </li>
        ))}
      </ul>
      {footer}
    </>
  );
}

type PaginationProps = {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  itemLabel?: string;
  disabled?: boolean;
};

/** Page numbers around the current one, with ellipses: 1 … 4 5 [6] 7 8 … 20 */
function pageWindow(page: number, totalPages: number): Array<number | "gap"> {
  const pages = new Set([1, totalPages, page - 1, page, page + 1]);
  const list = [...pages].filter((value) => value >= 1 && value <= totalPages).sort((a, b) => a - b);
  const result: Array<number | "gap"> = [];
  list.forEach((value, index) => {
    if (index > 0 && value - list[index - 1] > 1) result.push("gap");
    result.push(value);
  });
  return result;
}

export function Pagination({ page, pageSize, total, onPageChange, itemLabel = "records", disabled }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav className="table-footer" aria-label="Pagination">
      <p aria-live="polite">
        Showing <strong>{formatNumber(from)}</strong>–<strong>{formatNumber(to)}</strong> of{" "}
        <strong>{formatNumber(total)}</strong> {itemLabel}
      </p>
      <div className="pagination">
        <Button
          variant="secondary"
          size="sm"
          icon="chevronLeft"
          onClick={() => onPageChange(page - 1)}
          disabled={disabled || page <= 1}
          aria-label="Previous page"
        >
          Prev
        </Button>
        {pageWindow(page, totalPages).map((value, index) =>
          value === "gap" ? (
            <span key={`gap-${index}`} className="pagination__gap" aria-hidden="true">
              …
            </span>
          ) : (
            <button
              key={value}
              type="button"
              className={`pagination__page${value === page ? " is-current" : ""}`}
              aria-current={value === page ? "page" : undefined}
              aria-label={`Page ${value}`}
              disabled={disabled && value !== page}
              onClick={() => value !== page && onPageChange(value)}
            >
              {value}
            </button>
          )
        )}
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onPageChange(page + 1)}
          disabled={disabled || page >= totalPages}
          aria-label="Next page"
        >
          Next
        </Button>
      </div>
    </nav>
  );
}

/** Search + filters above a table. Children are laid out in one wrapping row. */
export function FilterBar({
  children,
  onReset,
  canReset,
  actions
}: {
  children: ReactNode;
  onReset?: () => void;
  canReset?: boolean;
  /** Right-aligned controls such as Export. */
  actions?: ReactNode;
}) {
  return (
    <div className="filter-bar" role="search">
      <div className="filter-bar__fields">{children}</div>
      {onReset || actions ? (
        <div className="filter-bar__actions">
          {onReset ? (
            <Button variant="ghost" size="sm" icon="x" onClick={onReset} disabled={!canReset}>
              Clear filters
            </Button>
          ) : null}
          {actions}
        </div>
      ) : null}
    </div>
  );
}

/** Title row inside a table card: "All merchants · 24" with optional controls. */
export function TableHeader({ title, count, description, actions }: { title: ReactNode; count?: number; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="table-header">
      <div>
        <h2 className="card-title">
          {title}
          {count !== undefined ? <span className="table-header__count">{formatNumber(count)}</span> : null}
        </h2>
        {description ? <p className="card-subtitle">{description}</p> : null}
      </div>
      {actions ? <div className="row">{actions}</div> : null}
    </div>
  );
}
