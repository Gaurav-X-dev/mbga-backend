import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { formatNumber } from "../../utils/format";
import { Button } from "../common/Button";
import { Menu, type MenuAction } from "../common/Menu";
import { ErrorState, LoadingSkeleton } from "../feedback/Feedback";

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
};

type DataTableProps<T> = {
  caption: string;
  columns: Column<T>[];
  rows: T[] | undefined;
  getRowKey: (row: T) => string;
  /** Mouse convenience; the primary cell must still contain a real link for keyboard users. */
  getRowHref?: (row: T) => string;
  rowActions?: (row: T) => MenuAction[];
  rowLabel?: (row: T) => string;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty: ReactNode;
  footer?: ReactNode;
};

export function DataTable<T>({
  caption,
  columns,
  rows,
  getRowKey,
  getRowHref,
  rowActions,
  rowLabel,
  isLoading,
  error,
  onRetry,
  empty,
  footer
}: DataTableProps<T>) {
  const navigate = useNavigate();

  if (isLoading) return <LoadingSkeleton label={`Loading ${caption.toLowerCase()}`} />;
  if (error && !rows) return <ErrorState error={error} onRetry={onRetry} />;
  if (!rows || rows.length === 0) return <>{empty}</>;

  const primary = columns.find((column) => column.primary) ?? columns[0];
  const secondary = columns.filter((column) => column !== primary && !column.hideOnMobile);

  return (
    <>
      <div className="table-wrap has-mobile-list">
        <table className="data-table">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} scope="col" style={column.width ? { width: column.width } : undefined}>
                  {column.header}
                </th>
              ))}
              {rowActions ? (
                <th scope="col" className="col-actions">
                  <span className="sr-only">Actions</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const href = getRowHref?.(row);
              return (
                <tr
                  key={getRowKey(row)}
                  className={href ? "is-clickable" : undefined}
                  onClick={
                    href
                      ? (event) => {
                          const target = event.target as HTMLElement;
                          if (target.closest("a, button, input, select, [role='menu']")) return;
                          navigate(href);
                        }
                      : undefined
                  }
                >
                  {columns.map((column) =>
                    column === primary ? (
                      <th key={column.key} scope="row" className={column.className}>
                        {column.render(row)}
                      </th>
                    ) : (
                      <td key={column.key} className={column.className}>
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
        {rows.map((row) => (
          <li key={getRowKey(row)} className="mobile-list__item">
            <div className="row-between" style={{ flexWrap: "nowrap" }}>
              <div style={{ minWidth: 0 }}>{primary.render(row)}</div>
              {rowActions ? (
                <Menu label={`Actions for ${rowLabel?.(row) ?? "this row"}`} actions={rowActions(row)} />
              ) : null}
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

export function Pagination({ page, pageSize, total, onPageChange, itemLabel = "records", disabled }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav className="table-footer" aria-label="Pagination">
      <p aria-live="polite">
        Showing {formatNumber(from)}–{formatNumber(to)} of {formatNumber(total)} {itemLabel}
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
          Previous
        </Button>
        <span className="text-small">
          Page {formatNumber(page)} of {formatNumber(totalPages)}
        </span>
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

export function FilterBar({ children, onReset, canReset }: { children: ReactNode; onReset?: () => void; canReset?: boolean }) {
  return (
    <div className="filter-bar" role="search">
      {children}
      {onReset ? (
        <div className="filter-bar__actions">
          <Button variant="ghost" onClick={onReset} disabled={!canReset}>
            Clear filters
          </Button>
        </div>
      ) : null}
    </div>
  );
}
