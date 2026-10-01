import { formatNumber } from "../../utils/format";

/**
 * "3/4 verified" as a row of ticks plus the numbers.
 *
 * The count is announced as words rather than left to the swatches, so the column means the
 * same thing to a screen reader as it does at a glance.
 */
export function DocumentProgress({ verified, total }: { verified: number; total: number }) {
  if (total === 0) return <span className="cell-muted">None uploaded</span>;
  return (
    <span className="doc-count">
      <span className="doc-count__bar" aria-hidden="true">
        {Array.from({ length: total }, (_, index) => (
          <i key={index} className={index < verified ? "is-ok" : undefined} />
        ))}
      </span>
      <span aria-hidden="true">
        {formatNumber(verified)}/{formatNumber(total)}
      </span>
      <span className="sr-only">
        {verified} of {total} documents verified
      </span>
    </span>
  );
}
